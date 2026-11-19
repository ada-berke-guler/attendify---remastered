"""R1.9: Redis fixed-window rate limits."""
from __future__ import annotations

import pytest

from app.core import rate_limit
from app.core.config import settings
from tests.conftest import auth, frame, login, make_student


@pytest.fixture(autouse=True)
def frozen_window(monkeypatch):
    """Pin the clock mid-window so a test never straddles a minute boundary."""
    monkeypatch.setattr(rate_limit, "_now", lambda: 1_800_000_030.0)
    monkeypatch.setattr(settings, "RATE_LIMIT_LIVENESS", 8)


def test_login_limited_per_ip(client, db):
    make_student(db)
    for _ in range(settings.RATE_LIMIT_LOGIN):
        resp = client.post("/api/v1/auth/login", data={"username": "student@test.com", "password": "wrong"})
        assert resp.status_code == 401
    resp = client.post("/api/v1/auth/login", data={"username": "student@test.com", "password": "wrong"})
    assert resp.status_code == 429
    assert 0 < int(resp.headers["Retry-After"]) <= 60


def test_login_limit_is_per_client_ip(client, db):
    make_student(db)
    for _ in range(settings.RATE_LIMIT_LOGIN):
        client.post("/api/v1/auth/login", data={"username": "x@test.com", "password": "x"},
                    headers={"X-Forwarded-For": "203.0.113.7"})
    blocked = client.post("/api/v1/auth/login", data={"username": "x@test.com", "password": "x"},
                          headers={"X-Forwarded-For": "203.0.113.7"})
    other = client.post("/api/v1/auth/login", data={"username": "x@test.com", "password": "x"},
                        headers={"X-Forwarded-For": "198.51.100.9"})
    assert blocked.status_code == 429
    assert other.status_code == 401


def test_spoofed_forwarded_for_does_not_escape_bucket(client, db):
    """Prepending fake hops is ignored: the right-most public address is used."""
    for i in range(settings.RATE_LIMIT_LOGIN):
        client.post("/api/v1/auth/login", data={"username": "x@test.com", "password": "x"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"})
    resp = client.post("/api/v1/auth/login", data={"username": "x@test.com", "password": "x"},
                       headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
    assert resp.status_code == 429


def test_liveness_limited_per_user(client, db):
    make_student(db)
    token = login(client, "student@test.com")
    for _ in range(settings.RATE_LIMIT_LIVENESS):
        resp = client.post("/api/v1/attendance/liveness-check",
                           files={"image": ("f.jpg", frame(ear=0.3), "image/jpeg")}, headers=auth(token))
        assert resp.status_code == 200
    resp = client.post("/api/v1/attendance/liveness-check",
                       files={"image": ("f.jpg", frame(ear=0.3), "image/jpeg")}, headers=auth(token))
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_submit_limited_per_user(client, db):
    make_student(db)
    token = login(client, "student@test.com")
    for _ in range(settings.RATE_LIMIT_ATTENDANCE):
        client.post("/api/v1/attendance/submit", data={"qr_token": "x"},
                    files={"image": ("f.jpg", b"x", "image/jpeg")}, headers=auth(token))
    resp = client.post("/api/v1/attendance/submit", data={"qr_token": "x"},
                       files={"image": ("f.jpg", b"x", "image/jpeg")}, headers=auth(token))
    assert resp.status_code == 429
