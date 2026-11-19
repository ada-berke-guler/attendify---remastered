from __future__ import annotations

import logging
import secrets
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("attendify.config")

MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    APP_NAME: str = "Attendify"
    APP_VERSION: str = "2.0.0"
    ENV: Literal["development", "production", "test"] = "development"

    # Security. No default on purpose: see validate_secret_key below.
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    EVENTS_TOKEN_EXPIRE_SECONDS: int = 60

    DATABASE_URL: str = "postgresql://attendify:attendify@localhost:5432/attendify"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Public origin used in QR links. Empty: derived from the request's Host header.
    PUBLIC_URL: str = ""
    # Single-origin deployment needs no CORS. Comma separated, only for the Vite dev server.
    DEV_CORS_ORIGINS: str = ""
    # Read the client IP from X-Forwarded-For (we always sit behind Caddy in compose).
    TRUST_PROXY_HEADERS: bool = True

    # Face service
    FACE_MODE: Literal["real", "mock"] = "real"
    FACE_SERVICE_URL: str = "http://localhost:8001"
    FACE_SERVICE_TIMEOUT_SECONDS: float = 15.0
    FACE_MATCH_MAX_DISTANCE: float = 0.45
    MAX_FACE_PHOTOS: int = 10
    MIN_FACE_PHOTOS: int = 1
    MAX_IMAGE_BYTES: int = 10 * 1024 * 1024

    # Liveness (blink challenge)
    LIVENESS_TTL_SECONDS: int = 60
    LIVENESS_TICKET_TTL_SECONDS: int = 60
    LIVENESS_MIN_BLUR_SCORE: float = 10.0
    EAR_CLOSED_THRESHOLD: float = 0.21
    EAR_OPEN_THRESHOLD: float = 0.25

    # QR rotation
    QR_ROTATE_SECONDS: int = 15
    QR_ROTATOR_ENABLED: bool = True

    # Rate limits (per minute)
    RATE_LIMIT_LOGIN: int = 10
    RATE_LIMIT_ATTENDANCE: int = 30   # /attendance/submit, per user
    # Blink detection needs a few frames per second, so 30/min would lock a student out
    # after ~12 s of trying. 120/min still caps a scripted client at 2 frames/s.
    RATE_LIMIT_LIVENESS: int = 120

    SEED_DEMO_DATA: bool = False

    # Optional SMTP. When MAIL_SERVER is empty, reset codes are logged instead.
    MAIL_SERVER: str = ""
    MAIL_PORT: int = 587
    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""
    MAIL_FROM: str = ""
    MAIL_STARTTLS: bool = True

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    @model_validator(mode="after")
    def validate_secret_key(self) -> "Settings":
        if self.ENV == "production":
            if len(self.SECRET_KEY) < MIN_SECRET_KEY_LENGTH:
                raise ValueError(
                    f"SECRET_KEY must be set and at least {MIN_SECRET_KEY_LENGTH} characters "
                    "when ENV=production"
                )
        elif not self.SECRET_KEY:
            self.SECRET_KEY = secrets.token_urlsafe(48)
            logger.warning(
                "SECRET_KEY is empty: generated a random key for this process. "
                "Tokens will not survive a restart. Set SECRET_KEY in .env."
            )
        return self

    @property
    def dev_cors_origins(self) -> list[str]:
        return [o.strip() for o in self.DEV_CORS_ORIGINS.split(",") if o.strip()]

    @property
    def mail_enabled(self) -> bool:
        return bool(self.MAIL_SERVER and self.MAIL_FROM)


settings = Settings()
