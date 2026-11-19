"""S3: a QR screenshot must stop working after two rotations."""
from __future__ import annotations

import time
from datetime import timedelta

import pytest

from app.core.security import create_qr_token
from app.services import qr
from app.services.qr_rotator import rotate_due_sessions, sync_active_sessions
from tests.conftest import (
    blink, login, make_course, make_instructor, qr_token_for, setup_class, start_session, submit,
)


def test_s3_old_qr_token_rejected(client, db, r):
    """Token from two rotations ago is rejected even though its JWT exp has not passed."""
    _, _, session, _, _ = setup_class(db, r)
    old_token = qr_token_for(r, session)
    qr.rotate(r, session.id)
    qr.rotate(r, session.id)

    with pytest.raises(qr.QrError):
        qr.validate_token(r, old_token)

    token = login(client, "student@test.com")
    resp = submit(client, token, old_token, blink(client, token))
    assert resp.status_code == 400
    assert "rotated" in resp.json()["detail"]


def test_previous_nonce_still_accepted(client, db, r):
    """Scanning right before a rotation must not fail."""
    _, _, session, _, _ = setup_class(db, r)
    token_before = qr_token_for(r, session)
    qr.rotate(r, session.id)
    assert qr.validate_token(r, token_before) == session.id

    student_token = login(client, "student@test.com")
    resp = submit(client, student_token, token_before, blink(client, student_token))
    assert resp.status_code == 201, resp.text


def test_s3_forged_nonce_rejected(db, r):
    _, instructor = make_instructor(db)
    session = start_session(db, r, make_course(db, instructor), instructor)
    forged = create_qr_token(session.id, "guessed-nonce", timedelta(seconds=30))
    with pytest.raises(qr.QrError):
        qr.validate_token(r, forged)


def test_s3_token_dead_after_session_closed(db, r):
    _, instructor = make_instructor(db)
    session = start_session(db, r, make_course(db, instructor), instructor)
    token = qr_token_for(r, session)
    qr.deactivate(r, session.id)
    with pytest.raises(qr.QrError):
        qr.validate_token(r, token)


def test_qr_jwt_expiry_is_two_rotation_intervals(db, r):
    from jose import jwt

    from app.core.config import settings

    _, instructor = make_instructor(db)
    session = start_session(db, r, make_course(db, instructor), instructor)
    token = qr_token_for(r, session)
    claims = jwt.get_unverified_claims(token)
    lifetime = claims["exp"] - time.time()
    assert settings.QR_ROTATE_SECONDS < lifetime <= settings.QR_ROTATE_SECONDS * 2 + 1


def test_rotator_rotates_due_sessions_and_publishes(db, r, monkeypatch):
    _, instructor = make_instructor(db)
    session = start_session(db, r, make_course(db, instructor), instructor)
    pubsub = r.pubsub()
    pubsub.subscribe(f"session:{session.id}:events")
    pubsub.get_message(timeout=1)  # subscribe confirmation

    assert rotate_due_sessions(r) == []  # freshly activated: not due yet

    r.set(f"qr:{session.id}:rotated_at", f"{time.time() - 60:.3f}")
    before = r.get(f"qr:{session.id}:current")
    assert rotate_due_sessions(r) == [session.id]
    assert r.get(f"qr:{session.id}:current") != before
    assert r.get(f"qr:{session.id}:previous") == before

    message = pubsub.get_message(timeout=1)
    assert message and '"qr.rotated"' in message["data"]


def test_rotation_lock_prevents_double_rotation(db, r):
    """Two api replicas ticking at the same moment rotate once."""
    _, instructor = make_instructor(db)
    session = start_session(db, r, make_course(db, instructor), instructor)
    assert qr.try_rotate(r, session.id) is not None
    assert qr.try_rotate(r, session.id) is None


def test_sync_active_sessions_repairs_redis(db, r):
    _, instructor = make_instructor(db)
    session = start_session(db, r, make_course(db, instructor), instructor)
    r.delete(qr.ACTIVE_SET)
    r.sadd(qr.ACTIVE_SET, 999_999)
    sync_active_sessions(db, r)
    assert qr.active_sessions(r) == [session.id]
