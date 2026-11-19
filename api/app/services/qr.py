"""Rotating QR codes.

Every QR_ROTATE_SECONDS a session gets a fresh random nonce in Redis. The QR JWT carries
{session_id, nonce, type: "qr", exp}. On submit the nonce must equal the current one or
the one right before it (a student who scanned just before a rotation still gets in).
A screenshot of the QR therefore dies after at most two rotations, no matter what the
JWT exp says.

Keys:
  qr:{sid}:current      current nonce
  qr:{sid}:previous     previous nonce
  qr:{sid}:rotated_at   unix time of the last rotation
  qr:{sid}:lock         SET NX lock so two api replicas do not rotate the same session twice
  qr:active             set of session ids the rotator should keep rotating
"""
from __future__ import annotations

import base64
import secrets
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

import qrcode
import redis
from jose import jwt

from app.core.config import settings
from app.core.security import TOKEN_TYPE_QR, decode_qr_token

ACTIVE_SET = "qr:active"


class QrError(Exception):
    """QR token is malformed, expired or no longer current."""


@dataclass(frozen=True)
class QrCode:
    session_id: int
    token: str
    url: str
    image_base64: str
    expires_in: int
    rotate_seconds: int


def _key(session_id: int, suffix: str) -> str:
    return f"qr:{session_id}:{suffix}"


def _state_ttl() -> int:
    # Keys outlive a missed rotation or two, then vanish: if the rotator dies the QR
    # stops working instead of staying valid forever.
    return settings.QR_ROTATE_SECONDS * 3


def rotate(r: redis.Redis, session_id: int) -> str:
    """Generate a new nonce and keep the old one as `previous`."""
    nonce = secrets.token_urlsafe(16)
    ttl = _state_ttl()
    current = r.get(_key(session_id, "current"))
    pipe = r.pipeline()
    if current:
        pipe.set(_key(session_id, "previous"), current, ex=ttl)
    pipe.set(_key(session_id, "current"), nonce, ex=ttl)
    pipe.set(_key(session_id, "rotated_at"), f"{time.time():.3f}", ex=ttl)
    pipe.execute()
    return nonce


def try_rotate(r: redis.Redis, session_id: int) -> Optional[str]:
    """Rotate if this process wins the short per-session lock. Returns the nonce or None."""
    lock_ttl = max(1, settings.QR_ROTATE_SECONDS - 1)
    if not r.set(_key(session_id, "lock"), "1", nx=True, ex=lock_ttl):
        return None
    return rotate(r, session_id)


def seconds_since_rotation(r: redis.Redis, session_id: int) -> Optional[float]:
    rotated_at = r.get(_key(session_id, "rotated_at"))
    if rotated_at is None:
        return None
    return time.time() - float(rotated_at)


def is_due(r: redis.Redis, session_id: int) -> bool:
    elapsed = seconds_since_rotation(r, session_id)
    return elapsed is None or elapsed >= settings.QR_ROTATE_SECONDS


def activate(r: redis.Redis, session_id: int) -> None:
    rotate(r, session_id)
    r.sadd(ACTIVE_SET, session_id)


def deactivate(r: redis.Redis, session_id: int) -> None:
    pipe = r.pipeline()
    pipe.srem(ACTIVE_SET, session_id)
    pipe.delete(
        _key(session_id, "current"),
        _key(session_id, "previous"),
        _key(session_id, "rotated_at"),
        _key(session_id, "lock"),
    )
    pipe.execute()


def active_sessions(r: redis.Redis) -> list[int]:
    return sorted(int(sid) for sid in r.smembers(ACTIVE_SET))


def _token_for(session_id: int, nonce: str, rotated_at: float) -> str:
    # exp is derived from the rotation time, so every caller in the same window gets the
    # same token (and the same QR image).
    exp = int(rotated_at + settings.QR_ROTATE_SECONDS * 2)
    payload = {"session_id": session_id, "nonce": nonce, "type": TOKEN_TYPE_QR, "exp": exp}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def render_png_base64(data: str) -> str:
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    buffer = BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def current_qr(r: redis.Redis, session_id: int, base_url: str) -> QrCode:
    """The QR the instructor should be showing right now.

    Rotates lazily when a rotation is overdue, so the screen keeps working even if the
    background rotator is not running.
    """
    if is_due(r, session_id):
        try_rotate(r, session_id)
    nonce = r.get(_key(session_id, "current"))
    rotated_at = r.get(_key(session_id, "rotated_at"))
    if nonce is None or rotated_at is None:
        nonce = rotate(r, session_id)
        rotated_at = r.get(_key(session_id, "rotated_at"))
    rotated = float(rotated_at)
    token = _token_for(session_id, nonce, rotated)
    url = f"{base_url.rstrip('/')}/student/scan?token={token}"
    remaining = max(0, int(round(rotated + settings.QR_ROTATE_SECONDS - time.time())))
    return QrCode(
        session_id=session_id,
        token=token,
        url=url,
        image_base64=render_png_base64(url),
        expires_in=remaining,
        rotate_seconds=settings.QR_ROTATE_SECONDS,
    )


def session_id_from_token(token: str) -> int:
    """Signature and expiry only. Use validate_token before accepting attendance."""
    payload = decode_qr_token(token)
    if not payload:
        raise QrError("Invalid or expired QR code")
    return int(payload["session_id"])


def validate_token(r: redis.Redis, token: str) -> int:
    """Return the session id if the token carries the current or previous nonce."""
    payload = decode_qr_token(token)
    if not payload:
        raise QrError("Invalid or expired QR code")
    session_id = int(payload["session_id"])
    current, previous = r.mget(_key(session_id, "current"), _key(session_id, "previous"))
    if payload["nonce"] not in {n for n in (current, previous) if n}:
        raise QrError("This QR code has rotated. Scan the code on screen again.")
    return session_id
