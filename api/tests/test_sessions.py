from __future__ import annotations

from app.models.models import AttendanceSession, SessionStatus
from app.services import qr
from tests.conftest import auth, login, make_course, make_instructor, make_student


class TestSessionCreate:
    def test_creates_session_with_qr(self, client, db, r):
        _, instructor = make_instructor(db)
        course = make_course(db, instructor, code="CS300")
        resp = client.post("/api/v1/sessions", json={"course_id": course.id, "title": "Week 1"},
                           headers=auth(login(client, "instructor@test.com")))
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "active"
        assert data["qr_token"]
        assert len(data["qr_image_base64"]) > 100
        assert data["qr_url"].startswith("http://testserver/student/scan?token=")
        assert data["id"] in qr.active_sessions(r)

    def test_only_one_active_session_per_course(self, client, db, r):
        _, instructor = make_instructor(db)
        course = make_course(db, instructor, code="CS301")
        headers = auth(login(client, "instructor@test.com"))
        first = client.post("/api/v1/sessions", json={"course_id": course.id}, headers=headers).json()["id"]
        client.post("/api/v1/sessions", json={"course_id": course.id}, headers=headers)
        assert db.get(AttendanceSession, first).status == SessionStatus.closed
        assert first not in qr.active_sessions(r)

    def test_student_cannot_create_session(self, client, db):
        make_student(db)
        resp = client.post("/api/v1/sessions", json={"course_id": 1}, headers=auth(login(client, "student@test.com")))
        assert resp.status_code == 403

    def test_wrong_instructor_course_rejected(self, client, db):
        _, inst1 = make_instructor(db, email="inst1@test.com")
        make_instructor(db, email="inst2@test.com")
        course = make_course(db, inst1, code="CS302")
        resp = client.post("/api/v1/sessions", json={"course_id": course.id},
                           headers=auth(login(client, "inst2@test.com")))
        assert resp.status_code == 404

    def test_qr_url_uses_public_url_when_set(self, client, db, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "PUBLIC_URL", "https://attendify.example.edu")
        _, instructor = make_instructor(db)
        course = make_course(db, instructor, code="CS303")
        resp = client.post("/api/v1/sessions", json={"course_id": course.id},
                           headers=auth(login(client, "instructor@test.com")))
        assert resp.json()["qr_url"].startswith("https://attendify.example.edu/student/scan?token=")

    def test_qr_url_follows_forwarded_host(self, client, db):
        _, instructor = make_instructor(db)
        course = make_course(db, instructor, code="CS304")
        headers = {
            **auth(login(client, "instructor@test.com")),
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "abc.trycloudflare.com",
        }
        resp = client.post("/api/v1/sessions", json={"course_id": course.id}, headers=headers)
        assert resp.json()["qr_url"].startswith("https://abc.trycloudflare.com/student/scan?token=")


class TestSessionClose:
    def test_close_session(self, client, db, r):
        _, instructor = make_instructor(db)
        course = make_course(db, instructor, code="CS310")
        headers = auth(login(client, "instructor@test.com"))
        sid = client.post("/api/v1/sessions", json={"course_id": course.id}, headers=headers).json()["id"]
        resp = client.post(f"/api/v1/sessions/{sid}/close", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"
        assert sid not in qr.active_sessions(r)
        assert client.get(f"/api/v1/sessions/{sid}/qr", headers=headers).status_code == 400


class TestCurrentQr:
    def test_get_qr_returns_same_token_within_window(self, client, db):
        _, instructor = make_instructor(db)
        course = make_course(db, instructor, code="CS320")
        headers = auth(login(client, "instructor@test.com"))
        created = client.post("/api/v1/sessions", json={"course_id": course.id}, headers=headers).json()
        resp = client.get(f"/api/v1/sessions/{created['id']}/qr", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["token"] == created["qr_token"]
        assert 0 <= body["expires_in"] <= body["rotate_seconds"]

    def test_renew_qr_endpoint_is_gone(self, client, db):
        _, instructor = make_instructor(db)
        course = make_course(db, instructor, code="CS321")
        headers = auth(login(client, "instructor@test.com"))
        sid = client.post("/api/v1/sessions", json={"course_id": course.id}, headers=headers).json()["id"]
        assert client.post(f"/api/v1/sessions/{sid}/renew-qr", headers=headers).status_code in (404, 405)

    def test_other_instructor_cannot_read_qr(self, client, db):
        _, instructor = make_instructor(db)
        make_instructor(db, email="other@test.com")
        course = make_course(db, instructor, code="CS322")
        sid = client.post("/api/v1/sessions", json={"course_id": course.id},
                          headers=auth(login(client, "instructor@test.com"))).json()["id"]
        resp = client.get(f"/api/v1/sessions/{sid}/qr", headers=auth(login(client, "other@test.com")))
        assert resp.status_code == 404
