"""S6, S7: configuration hardening."""
from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import app


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_s7_production_refuses_empty_secret_key():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(ENV="production", SECRET_KEY="")


def test_s7_production_refuses_short_secret_key():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(ENV="production", SECRET_KEY="too-short")


def test_s7_production_accepts_long_secret_key():
    assert _settings(ENV="production", SECRET_KEY="x" * 32).SECRET_KEY == "x" * 32


def test_s7_development_generates_random_key_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="attendify.config"):
        a = _settings(ENV="development", SECRET_KEY="")
        b = _settings(ENV="development", SECRET_KEY="")
    assert len(a.SECRET_KEY) >= 32
    assert a.SECRET_KEY != b.SECRET_KEY
    assert any("SECRET_KEY" in rec.getMessage() for rec in caplog.records)


def test_s7_no_secret_key_default_in_code():
    assert Settings.model_fields["SECRET_KEY"].default == ""


def test_s6_no_cors_by_default(client):
    middleware = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" not in middleware
    resp = client.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}


def test_s6_dev_cors_origins_parsed():
    s = _settings(ENV="development", SECRET_KEY="x" * 32, DEV_CORS_ORIGINS="http://localhost:5173, http://127.0.0.1:5173")
    assert s.dev_cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"
