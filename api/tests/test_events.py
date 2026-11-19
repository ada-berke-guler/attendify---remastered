"""R1.10: live events over Redis pub/sub and SSE."""
from __future__ import annotations

import asyncio
import json

from app.api.v1.endpoints.sessions import event_stream
from app.services import events
from tests.conftest import auth, blink, login, qr_token_for, setup_class, submit


def _subscribe(r, session_id: int):
    pubsub = r.pubsub()
    pubsub.subscribe(events.channel(session_id))
    pubsub.get_message(timeout=1)  # subscription confirmation
    return pubsub


def _next_event(pubsub) -> dict:
    message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
    assert message is not None, "no event published"
    return json.loads(message["data"])


def test_submit_publishes_attendance_created(client, db, r):
    _, _, session, _, student = setup_class(db, r)
    token = login(client, "student@test.com")
    ticket = blink(client, token)
    pubsub = _subscribe(r, session.id)

    resp = submit(client, token, qr_token_for(r, session), ticket)
    assert resp.status_code == 201

    event = _next_event(pubsub)
    assert event["type"] == "attendance.created"
    assert event["session_id"] == session.id
    assert event["data"]["student_id"] == student.id
    assert event["data"]["student_number"] == "20210001"
    assert event["data"]["verification_method"] == "face"
    assert event["data"]["record_id"] == resp.json()["id"]


def test_manual_add_and_remove_publish(client, db, r):
    _, _, session, _, student = setup_class(db, r)
    headers = auth(login(client, "instructor@test.com"))
    pubsub = _subscribe(r, session.id)

    client.post(f"/api/v1/sessions/{session.id}/mark-present", json={"student_id": student.id}, headers=headers)
    assert _next_event(pubsub)["type"] == "attendance.created"

    client.delete(f"/api/v1/sessions/{session.id}/mark-present/{student.id}", headers=headers)
    removed = _next_event(pubsub)
    assert removed["type"] == "attendance.removed"
    assert removed["data"]["student_id"] == student.id


def test_pending_flow_publishes(client, db, r):
    _, _, session, _, _ = setup_class(db, r)
    pubsub = _subscribe(r, session.id)
    pending = client.post(
        "/api/v1/attendance/notify-instructor",
        json={"session_id": session.id, "reason": "qr_failed", "note": "phone died"},
        headers=auth(login(client, "student@test.com")),
    ).json()
    created = _next_event(pubsub)
    assert created["type"] == "pending.created"
    assert created["data"]["note"] == "phone died"

    client.patch(f"/api/v1/sessions/{session.id}/pending/{pending['id']}", json={"action": "decline"},
                 headers=auth(login(client, "instructor@test.com")))
    resolved = _next_event(pubsub)
    assert resolved["type"] == "pending.resolved"
    assert resolved["data"] == {"pending_id": pending["id"], "status": "declined"}


def test_events_token_requires_session_owner(client, db, r):
    from tests.conftest import make_instructor

    _, _, session, _, _ = setup_class(db, r)
    make_instructor(db, email="other@test.com")
    ok = client.post(f"/api/v1/sessions/{session.id}/events-token", headers=auth(login(client, "instructor@test.com")))
    assert ok.status_code == 200 and ok.json()["expires_in"] == 60
    denied = client.post(f"/api/v1/sessions/{session.id}/events-token", headers=auth(login(client, "other@test.com")))
    assert denied.status_code == 404


def test_events_stream_rejects_bad_tokens(client, db, r):
    _, _, session, _, _ = setup_class(db, r)
    access_token = login(client, "instructor@test.com")
    assert client.get(f"/api/v1/sessions/{session.id}/events?token=garbage").status_code == 401
    # A normal access token is not an events token.
    assert client.get(f"/api/v1/sessions/{session.id}/events?token={access_token}").status_code == 401
    # A token for another session does not open this one.
    other = client.post(f"/api/v1/sessions/{session.id}/events-token", headers=auth(access_token)).json()["token"]
    assert client.get(f"/api/v1/sessions/{session.id + 1}/events?token={other}").status_code == 401


class _FakeRequest:
    def __init__(self) -> None:
        self.disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


def test_sse_stream_forwards_published_events(redis_clients):
    sync_r, async_r = redis_clients

    async def scenario() -> list[str]:
        request = _FakeRequest()
        stream = event_stream(request, async_r, 42, heartbeat=60)
        frames = [await stream.__anext__(), await stream.__anext__()]  # retry + hello
        events.publish(sync_r, 42, events.ATTENDANCE_CREATED, {"student_id": 7})
        frames.append(await asyncio.wait_for(stream.__anext__(), timeout=5))
        request.disconnected = True
        await stream.aclose()
        return frames

    frames = asyncio.run(scenario())
    assert frames[0].startswith("retry:")
    assert frames[1].startswith("event: hello")
    assert frames[2].startswith("event: attendance.created\ndata: ")
    payload = json.loads(frames[2].split("data: ", 1)[1])
    assert payload["data"] == {"student_id": 7}


def test_websocket_fallback_delivers_events(client, db, r):
    _, _, session, _, student = setup_class(db, r)
    headers = auth(login(client, "instructor@test.com"))
    token = client.post(f"/api/v1/sessions/{session.id}/events-token", headers=headers).json()["token"]
    with client.websocket_connect(f"/api/v1/sessions/{session.id}/ws?token={token}") as ws:
        assert json.loads(ws.receive_text())["type"] == "hello"
        client.post(f"/api/v1/sessions/{session.id}/mark-present", json={"student_id": student.id}, headers=headers)
        event = json.loads(ws.receive_text())
        assert event["type"] == "attendance.created"
        assert event["data"]["student_id"] == student.id


def test_websocket_rejects_bad_token(client, db, r):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    _, _, session, _, _ = setup_class(db, r)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/v1/sessions/{session.id}/ws?token=garbage") as ws:
            ws.receive_text()
    assert exc.value.code == 4401
