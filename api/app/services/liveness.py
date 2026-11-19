"""Blink-based liveness challenge with single-use tickets.

State lives in Redis, not in the face service, so it survives restarts and works with
several api/face workers:

  liveness:{user_id}          hash {saw_closed, saw_open}, TTL LIVENESS_TTL_SECONDS
                              (set once, not refreshed: the blink must happen in that window)
  liveness_ticket:{uuid}      JSON {user_id, embedding}, TTL LIVENESS_TICKET_TTL_SECONDS

When the student closes and reopens their eyes we mint a ticket. /attendance/submit must
present it and consumes it with GETDEL, so it works exactly once and only for the user it
was issued to. The ticket also carries the embedding of the frame that completed the blink;
submit checks that the submitted face is the same face that blinked.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import List, Optional

import redis

from app.core.config import settings
from app.services.face_client import FaceClient


@dataclass(frozen=True)
class LivenessResult:
    is_live: bool
    reason: str
    ticket: Optional[str] = None
    ear: Optional[float] = None
    blur_score: Optional[float] = None


@dataclass(frozen=True)
class Ticket:
    user_id: int
    embedding: Optional[List[float]]


def _state_key(user_id: int) -> str:
    return f"liveness:{user_id}"


def _ticket_key(ticket: str) -> str:
    return f"liveness_ticket:{ticket}"


def process_frame(r: redis.Redis, face: FaceClient, user_id: int, image_bytes: bytes) -> LivenessResult:
    """Feed one camera frame into the blink state machine.

    Raises FaceServiceUnavailable if the face service is down (caller returns 503).
    """
    analysis = face.analyze(image_bytes, with_embedding=False)
    if analysis.face_count == 0:
        return LivenessResult(False, "no_face")
    if analysis.face_count > 1:
        return LivenessResult(False, "multiple_faces")
    blur = analysis.blur_score or 0.0
    if blur < settings.LIVENESS_MIN_BLUR_SCORE:
        return LivenessResult(False, "blur", blur_score=blur)
    if analysis.ear is None:
        return LivenessResult(False, "no_eye_landmarks", blur_score=blur)
    ear = float(analysis.ear)

    key = _state_key(user_id)
    pipe = r.pipeline()
    pipe.hsetnx(key, "saw_closed", 0)
    pipe.hsetnx(key, "saw_open", 0)
    pipe.expire(key, settings.LIVENESS_TTL_SECONDS, nx=True)
    pipe.hgetall(key)
    state = pipe.execute()[-1]
    saw_closed = state.get("saw_closed") == "1"
    saw_open = state.get("saw_open") == "1"

    if ear < settings.EAR_CLOSED_THRESHOLD and not saw_closed:
        saw_closed = True
        r.hset(key, "saw_closed", 1)
    elif saw_closed and ear > settings.EAR_OPEN_THRESHOLD:
        saw_open = True

    if not saw_closed:
        return LivenessResult(False, "need_blink_close", ear=ear, blur_score=blur)
    if not saw_open:
        return LivenessResult(False, "need_blink_open", ear=ear, blur_score=blur)

    # Blink complete. Take the embedding of this exact frame so submit can prove the
    # face it receives is the one that blinked.
    with_embedding = face.analyze(image_bytes, with_embedding=True)
    r.delete(key)
    ticket = issue_ticket(r, user_id, with_embedding.embedding)
    return LivenessResult(True, "live", ticket=ticket, ear=ear, blur_score=blur)


def issue_ticket(r: redis.Redis, user_id: int, embedding: Optional[List[float]] = None) -> str:
    ticket = uuid.uuid4().hex
    r.set(
        _ticket_key(ticket),
        json.dumps({"user_id": user_id, "embedding": embedding}),
        ex=settings.LIVENESS_TICKET_TTL_SECONDS,
    )
    return ticket


def consume_ticket(r: redis.Redis, ticket: str, user_id: int) -> Optional[Ticket]:
    """Atomically take the ticket. None if missing, expired, used, or someone else's."""
    if not ticket:
        return None
    raw = r.getdel(_ticket_key(ticket))
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if data.get("user_id") != user_id:
        return None
    return Ticket(user_id=user_id, embedding=data.get("embedding"))


def reset(r: redis.Redis, user_id: int) -> None:
    r.delete(_state_key(user_id))
