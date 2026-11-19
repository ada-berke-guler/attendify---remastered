from __future__ import annotations

from datetime import timedelta

from app.core.security import (
    create_access_token, create_events_token, create_qr_token, decode_access_token, decode_events_token,
    decode_qr_token, decode_token, get_password_hash, verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        assert verify_password("mysecretpassword", get_password_hash("mysecretpassword")) is True

    def test_wrong_password_fails(self):
        assert verify_password("wrong", get_password_hash("correct")) is False

    def test_hashes_differ_same_password(self):
        assert get_password_hash("same") != get_password_hash("same")


class TestJWT:
    def test_create_and_decode(self):
        payload = decode_access_token(create_access_token({"sub": "42", "role": "student"}))
        assert payload is not None and payload["sub"] == "42"

    def test_expired_returns_none(self):
        assert decode_token(create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-1))) is None

    def test_invalid_returns_none(self):
        assert decode_token("not.a.valid.token") is None


class TestTokenTypes:
    def test_qr_token_round_trip(self):
        payload = decode_qr_token(create_qr_token(5, "nonce", timedelta(seconds=30)))
        assert payload is not None
        assert payload["session_id"] == 5 and payload["nonce"] == "nonce" and payload["type"] == "qr"

    def test_expired_qr_invalid(self):
        assert decode_qr_token(create_qr_token(5, "n", timedelta(seconds=-1))) is None

    def test_access_token_rejected_as_qr(self):
        assert decode_qr_token(create_access_token({"sub": "1"})) is None

    def test_qr_token_rejected_as_access(self):
        assert decode_access_token(create_qr_token(5, "n", timedelta(seconds=30))) is None

    def test_events_token_is_not_an_access_token(self):
        token = create_events_token(1, 2)
        assert decode_events_token(token)["session_id"] == 2
        assert decode_access_token(token) is None
