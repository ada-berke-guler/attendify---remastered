"""Live session events over Redis pub/sub.

Publishers (request handlers, QR rotator) push JSON to session:{id}:events. The SSE
endpoint subscribes to that channel and forwards each message to the instructor.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, Optional

import redis

logger = logging.getLogger("attendify.events")

ATTENDANCE_CREATED = "attendance.created"
ATTENDANCE_REMOVED = "attendance.removed"
PENDING_CREATED = "pending.created"
PENDING_RESOLVED = "pending.resolved"
QR_ROTATED = "qr.rotated"


def channel(session_id: int) -> str:
    return f"session:{session_id}:events"


def build_event(event_type: str, session_id: int, data: Optional[Dict[str, Any]] = None) -> str:
    return json.dumps(
        {
            "type": event_type,
            "session_id": session_id,
            "data": data or {},
            "ts": datetime.now(UTC).isoformat(),
        },
        default=str,
    )


def publish(r: redis.Redis, session_id: int, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Best effort: a Redis hiccup must not roll back an attendance record that is already committed."""
    try:
        r.publish(channel(session_id), build_event(event_type, session_id, data))
    except redis.RedisError:
        logger.exception("failed to publish %s for session %s", event_type, session_id)


def format_sse(message: str) -> str:
    """Turn a published JSON event into an SSE frame with a named event."""
    try:
        event_type = json.loads(message).get("type", "message")
    except (ValueError, AttributeError):
        event_type = "message"
    return f"event: {event_type}\ndata: {message}\n\n"
