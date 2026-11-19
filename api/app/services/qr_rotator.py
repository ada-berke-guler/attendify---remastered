"""Server-side QR rotation.

A single asyncio task started in the app lifespan. Once a second it looks at the active
session set in Redis and rotates every session whose QR is due, publishing qr.rotated so
instructor screens refresh over SSE. The per-session SET NX lock in services/qr.py keeps
several api replicas from rotating the same session twice.
"""
from __future__ import annotations

import asyncio
import logging

import redis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import get_redis_client
from app.db.session import SessionLocal
from app.models.models import AttendanceSession, SessionStatus
from app.services import events, qr

logger = logging.getLogger("attendify.qr")

TICK_SECONDS = 1.0


def rotate_due_sessions(r: redis.Redis) -> list[int]:
    rotated: list[int] = []
    for session_id in qr.active_sessions(r):
        if not qr.is_due(r, session_id):
            continue
        if qr.try_rotate(r, session_id) is None:
            continue
        rotated.append(session_id)
        events.publish(
            r, session_id, events.QR_ROTATED,
            {"expires_in": settings.QR_ROTATE_SECONDS, "rotate_seconds": settings.QR_ROTATE_SECONDS},
        )
    return rotated


def sync_active_sessions(db: Session, r: redis.Redis) -> int:
    """After a restart (or a Redis flush) make Redis agree with the database."""
    db_active = {
        sid for (sid,) in db.query(AttendanceSession.id).filter(AttendanceSession.status == SessionStatus.active)
    }
    for stale in set(qr.active_sessions(r)) - db_active:
        qr.deactivate(r, stale)
    for sid in db_active:
        r.sadd(qr.ACTIVE_SET, sid)
    return len(db_active)


async def run_rotator(stop: asyncio.Event) -> None:
    r = get_redis_client()
    try:
        def _sync() -> int:
            with SessionLocal() as db:
                return sync_active_sessions(db, r)

        count = await asyncio.to_thread(_sync)
        logger.info("QR rotator started, %d active session(s), every %ss", count, settings.QR_ROTATE_SECONDS)
    except Exception:
        logger.exception("QR rotator could not sync active sessions; continuing")

    while not stop.is_set():
        try:
            await asyncio.to_thread(rotate_due_sessions, r)
        except Exception:
            logger.exception("QR rotation tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
        except asyncio.TimeoutError:
            pass
