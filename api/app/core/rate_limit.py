"""Fixed-window rate limiting backed by Redis.

Key: rl:{name}:{subject}:{window_index}. INCR, set EXPIRE on the first hit, reject with
429 + Retry-After once the counter passes the limit.
"""
from __future__ import annotations

import time
from typing import Callable

import redis
from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.redis import get_redis
from app.core.request_utils import client_ip
from app.models.models import User


def _now() -> float:
    return time.time()


def hit(r: redis.Redis, name: str, subject: str, limit: int, window: int = 60) -> None:
    now = int(_now())
    window_index = now // window
    key = f"rl:{name}:{subject}:{window_index}"
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, window, nx=True)
    count, _ = pipe.execute()
    if count > limit:
        retry_after = window - (now % window)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests, slow down.",
            headers={"Retry-After": str(retry_after)},
        )


def limit_by_ip(name: str, limit: Callable[[], int]) -> Callable[..., None]:
    def dependency(request: Request, r: redis.Redis = Depends(get_redis)) -> None:
        hit(r, name, client_ip(request), limit())

    return dependency


def limit_by_user(name: str, limit: Callable[[], int]) -> Callable[..., None]:
    def dependency(
        user: User = Depends(get_current_user),
        r: redis.Redis = Depends(get_redis),
    ) -> None:
        hit(r, name, str(user.id), limit())

    return dependency


login_rate_limit = limit_by_ip("login", lambda: settings.RATE_LIMIT_LOGIN)
password_reset_rate_limit = limit_by_ip("password-reset", lambda: settings.RATE_LIMIT_LOGIN)
submit_rate_limit = limit_by_user("attendance-submit", lambda: settings.RATE_LIMIT_ATTENDANCE)
liveness_rate_limit = limit_by_user("attendance-liveness", lambda: settings.RATE_LIMIT_LIVENESS)
