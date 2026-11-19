from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Optional

import bcrypt
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_QR = "qr"
TOKEN_TYPE_EVENTS = "events"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _encode(data: Dict[str, Any], expires_delta: timedelta) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(UTC) + expires_delta
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    payload = {**data, "type": TOKEN_TYPE_ACCESS}
    return _encode(payload, expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    payload = decode_token(token)
    if payload and payload.get("type") == TOKEN_TYPE_ACCESS:
        return payload
    return None


def create_qr_token(session_id: int, nonce: str, expires_delta: timedelta) -> str:
    return _encode({"session_id": session_id, "nonce": nonce, "type": TOKEN_TYPE_QR}, expires_delta)


def decode_qr_token(token: str) -> Optional[Dict[str, Any]]:
    payload = decode_token(token)
    if payload and payload.get("type") == TOKEN_TYPE_QR and "nonce" in payload:
        return payload
    return None


def create_events_token(user_id: int, session_id: int) -> str:
    return _encode(
        {"sub": str(user_id), "session_id": session_id, "type": TOKEN_TYPE_EVENTS},
        timedelta(seconds=settings.EVENTS_TOKEN_EXPIRE_SECONDS),
    )


def decode_events_token(token: str) -> Optional[Dict[str, Any]]:
    payload = decode_token(token)
    if payload and payload.get("type") == TOKEN_TYPE_EVENTS:
        return payload
    return None
