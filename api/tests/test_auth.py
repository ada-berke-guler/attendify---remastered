from __future__ import annotations

from tests.conftest import (
    auth, login, make_admin, make_course, make_instructor, make_student, qr_token_for, start_session,
)

STUDENT = {
    "email": "new@test.com", "password": "password123",
    "first_name": "Alice", "last_name": "Smith",
    "student_number": "20210099", "role": "student",
}
INSTRUCTOR = {
    "email": "prof@test.com", "password": "password123",
    "first_name": "Ada", "last_name": "Prof", "role": "instructor", "title": "Dr.",
}


def _admin_headers(client, db) -> dict:
    make_admin(db)
    return auth(login(client, "admin@test.com"))


class TestRegisterStudent:
    def test_admin_registers_student(self, client, db):
        resp = client.post("/api/v1/auth/register/student", json=STUDENT, headers=_admin_headers(client, db))
        assert resp.status_code == 201
        assert resp.json()["email"] == "new@test.com"
        assert resp.json()["student_number"] == "20210099"

    def test_s5_anonymous_register_rejected(self, client):
        resp = client.post("/api/v1/auth/register/student", json=STUDENT)
        assert resp.status_code == 401

    def test_s5_instructor_cannot_register_student(self, client, db):
        make_instructor(db)
        token = login(client, "instructor@test.com")
        resp = client.post("/api/v1/auth/register/student", json=STUDENT, headers=auth(token))
        assert resp.status_code == 403

    def test_duplicate_email_rejected(self, client, db):
        make_student(db, email="new@test.com", student_number="20210001")
        resp = client.post("/api/v1/auth/register/student", json=STUDENT, headers=_admin_headers(client, db))
        assert resp.status_code == 400

    def test_duplicate_student_number_rejected(self, client, db):
        make_student(db, email="s1@test.com", student_number="20210099")
        resp = client.post("/api/v1/auth/register/student", json=STUDENT, headers=_admin_headers(client, db))
        assert resp.status_code == 400

    def test_short_password_rejected(self, client, db):
        resp = client.post(
            "/api/v1/auth/register/student", json={**STUDENT, "password": "short"}, headers=_admin_headers(client, db)
        )
        assert resp.status_code == 422

    def test_student_number_generated_when_missing(self, client, db):
        payload = {k: v for k, v in STUDENT.items() if k != "student_number"}
        resp = client.post("/api/v1/auth/register/student", json=payload, headers=_admin_headers(client, db))
        assert resp.status_code == 201
        assert resp.json()["student_number"].startswith("STU-")


class TestRegisterInstructor:
    def test_admin_registers_instructor(self, client, db):
        resp = client.post("/api/v1/auth/register/instructor", json=INSTRUCTOR, headers=_admin_headers(client, db))
        assert resp.status_code == 201
        assert resp.json()["role"] == "instructor"

    def test_s5_anonymous_register_instructor_rejected(self, client):
        resp = client.post("/api/v1/auth/register/instructor", json=INSTRUCTOR)
        assert resp.status_code == 401

    def test_s5_instructor_cannot_register_instructor(self, client, db):
        make_instructor(db)
        token = login(client, "instructor@test.com")
        resp = client.post("/api/v1/auth/register/instructor", json=INSTRUCTOR, headers=auth(token))
        assert resp.status_code == 403


class TestLogin:
    def test_login_success(self, client, db):
        make_student(db, email="login@test.com")
        resp = client.post("/api/v1/auth/login", data={"username": "login@test.com", "password": "password123"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "student"
        assert "access_token" in resp.json()

    def test_wrong_password(self, client, db):
        make_student(db, email="wp@test.com")
        resp = client.post("/api/v1/auth/login", data={"username": "wp@test.com", "password": "wrong"})
        assert resp.status_code == 401

    def test_unknown_email(self, client):
        resp = client.post("/api/v1/auth/login", data={"username": "nobody@test.com", "password": "password123"})
        assert resp.status_code == 401

    def test_inactive_user_blocked(self, client, db):
        user, _ = make_student(db, email="inactive@test.com")
        user.is_active = False
        db.commit()
        resp = client.post("/api/v1/auth/login", data={"username": "inactive@test.com", "password": "password123"})
        assert resp.status_code == 400


class TestMe:
    def test_authenticated_returns_user(self, client, db):
        make_student(db, email="me@test.com")
        resp = client.get("/api/v1/auth/me", headers=auth(login(client, "me@test.com")))
        assert resp.status_code == 200
        assert resp.json()["email"] == "me@test.com"

    def test_unauthenticated_returns_401(self, client):
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_qr_token_is_not_an_access_token(self, client, db, r):
        _, instructor = make_instructor(db)
        session = start_session(db, r, make_course(db, instructor), instructor)
        resp = client.get("/api/v1/auth/me", headers=auth(qr_token_for(r, session)))
        assert resp.status_code == 401


class TestPasswordReset:
    def test_reset_flow_logs_code_without_smtp(self, client, db, caplog):
        make_student(db, email="reset@test.com")
        with caplog.at_level("WARNING", logger="attendify.mail"):
            resp = client.post("/api/v1/auth/forgot-password", json={"email": "reset@test.com"})
        assert resp.status_code == 200
        record = next(rec for rec in caplog.records if "reset code" in rec.getMessage())
        code = record.getMessage().rsplit(" ", 1)[-1]
        assert len(code) == 6 and code.isdigit()

        resp = client.post(
            "/api/v1/auth/reset-password",
            json={"email": "reset@test.com", "code": code, "new_password": "brand-new-pass"},
        )
        assert resp.status_code == 200
        assert login(client, "reset@test.com", "brand-new-pass")

    def test_unknown_email_gets_same_answer(self, client):
        resp = client.post("/api/v1/auth/forgot-password", json={"email": "ghost@test.com"})
        assert resp.status_code == 200
