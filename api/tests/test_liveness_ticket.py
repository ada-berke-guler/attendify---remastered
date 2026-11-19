"""S1, S2, S8: liveness must be enforced server side, fail closed, and live in Redis."""
from __future__ import annotations

from app.services import liveness
from app.services.face_client import FaceServiceUnavailable, get_face_client
from app.main import app
from tests.conftest import (
    auth, blink, frame, login, make_student, qr_token_for, setup_class, submit,
)


class DownFaceClient:
    def analyze(self, image_bytes: bytes, with_embedding: bool = True):
        raise FaceServiceUnavailable("connection refused")


def test_s1_submit_without_ticket_rejected(client, db, r):
    _, _, session, _, _ = setup_class(db, r)
    token = login(client, "student@test.com")
    resp = submit(client, token, qr_token_for(r, session), ticket=None)
    assert resp.status_code == 403


def test_s1_made_up_ticket_rejected(client, db, r):
    _, _, session, _, _ = setup_class(db, r)
    token = login(client, "student@test.com")
    assert submit(client, token, qr_token_for(r, session), "0" * 32).status_code == 403


def test_s1_ticket_is_single_use(client, db, r):
    _, _, session, _, _ = setup_class(db, r)
    token = login(client, "student@test.com")
    ticket = blink(client, token)
    # First use fails on the face check, but the ticket is spent anyway.
    first = submit(client, token, qr_token_for(r, session), ticket, face_id="someone-else")
    assert first.status_code == 422
    second = submit(client, token, qr_token_for(r, session), ticket)
    assert second.status_code == 403


def test_s1_ticket_of_another_user_rejected(client, db, r):
    _, _, session, _, _ = setup_class(db, r)
    other_user, _ = make_student(db, email="other@test.com", student_number="20219999")
    foreign_ticket = liveness.issue_ticket(r, other_user.id)
    token = login(client, "student@test.com")
    assert submit(client, token, qr_token_for(r, session), foreign_ticket).status_code == 403


def test_s1_expired_ticket_rejected(client, db, r):
    _, _, session, student_user, _ = setup_class(db, r)
    ticket = liveness.issue_ticket(r, student_user.id)
    r.delete(f"liveness_ticket:{ticket}")  # what the TTL does after 60 s
    token = login(client, "student@test.com")
    assert submit(client, token, qr_token_for(r, session), ticket).status_code == 403


def test_open_eyes_alone_do_not_pass(client, db, r):
    setup_class(db, r)
    token = login(client, "student@test.com")
    for _ in range(3):
        resp = client.post("/api/v1/attendance/liveness-check",
                           files={"image": ("f.jpg", frame(ear=0.33), "image/jpeg")}, headers=auth(token))
        assert resp.json() == {"is_live": False, "reason": "need_blink_close", "liveness_ticket": None,
                               "ticket_expires_in": None}


def test_blurry_frame_rejected(client, db, r):
    setup_class(db, r)
    token = login(client, "student@test.com")
    resp = client.post("/api/v1/attendance/liveness-check",
                       files={"image": ("f.jpg", frame(blur=1.0), "image/jpeg")}, headers=auth(token))
    assert resp.json()["reason"] == "blur"


def test_multiple_faces_rejected(client, db, r):
    setup_class(db, r)
    token = login(client, "student@test.com")
    resp = client.post("/api/v1/attendance/liveness-check",
                       files={"image": ("f.jpg", frame(faces=2), "image/jpeg")}, headers=auth(token))
    assert resp.json()["reason"] == "multiple_faces"


def test_s2_liveness_fails_closed_when_face_service_down(client, db, r):
    setup_class(db, r)
    token = login(client, "student@test.com")
    app.dependency_overrides[get_face_client] = lambda: DownFaceClient()
    resp = client.post("/api/v1/attendance/liveness-check",
                       files={"image": ("f.jpg", frame(), "image/jpeg")}, headers=auth(token))
    assert resp.status_code == 503


def test_s2_submit_fails_closed_when_face_service_down(client, db, r):
    _, _, session, _, _ = setup_class(db, r)
    token = login(client, "student@test.com")
    ticket = blink(client, token)
    app.dependency_overrides[get_face_client] = lambda: DownFaceClient()
    resp = submit(client, token, qr_token_for(r, session), ticket)
    assert resp.status_code == 503


def test_s2_http_client_raises_when_unreachable():
    import pytest

    from app.services.face_client import HttpFaceClient

    client = HttpFaceClient("http://127.0.0.1:9", timeout=0.5)
    with pytest.raises(FaceServiceUnavailable):
        client.analyze(b"jpeg")


def test_s8_liveness_state_lives_in_redis(client, db, r):
    """Half a blink on one request is remembered by the next one, via Redis only."""
    _, _, _, student_user, _ = setup_class(db, r)
    token = login(client, "student@test.com")
    client.post("/api/v1/attendance/liveness-check",
                files={"image": ("f.jpg", frame(ear=0.15), "image/jpeg")}, headers=auth(token))
    state = r.hgetall(f"liveness:{student_user.id}")
    assert state == {"saw_closed": "1", "saw_open": "0"}
    assert 0 < r.ttl(f"liveness:{student_user.id}") <= 60

    # A "different worker": nothing but the shared Redis carries the state.
    resp = client.post("/api/v1/attendance/liveness-check",
                       files={"image": ("f.jpg", frame(ear=0.32), "image/jpeg")}, headers=auth(token))
    body = resp.json()
    assert body["is_live"] is True
    assert r.exists(f"liveness:{student_user.id}") == 0
    assert r.exists(f"liveness_ticket:{body['liveness_ticket']}") == 1


def test_s8_liveness_window_does_not_extend(client, db, r):
    _, _, _, student_user, _ = setup_class(db, r)
    token = login(client, "student@test.com")
    client.post("/api/v1/attendance/liveness-check",
                files={"image": ("f.jpg", frame(ear=0.15), "image/jpeg")}, headers=auth(token))
    r.expire(f"liveness:{student_user.id}", 5)
    client.post("/api/v1/attendance/liveness-check",
                files={"image": ("f.jpg", frame(ear=0.15), "image/jpeg")}, headers=auth(token))
    assert r.ttl(f"liveness:{student_user.id}") <= 5
