from __future__ import annotations

from tests.conftest import auth, login, make_admin, make_instructor, make_student


class TestAdminStats:
    def test_admin_gets_stats(self, client, db):
        make_admin(db)
        resp = client.get("/api/v1/admin/stats", headers=auth(login(client, "admin@test.com")))
        assert resp.status_code == 200
        assert "total_users" in resp.json()

    def test_student_blocked(self, client, db):
        make_student(db)
        resp = client.get("/api/v1/admin/stats", headers=auth(login(client, "student@test.com")))
        assert resp.status_code == 403

    def test_instructor_blocked(self, client, db):
        make_instructor(db)
        resp = client.get("/api/v1/admin/stats", headers=auth(login(client, "instructor@test.com")))
        assert resp.status_code == 403


class TestUserManagement:
    def test_list_users(self, client, db):
        make_admin(db)
        make_student(db)
        resp = client.get("/api/v1/admin/users", headers=auth(login(client, "admin@test.com")))
        assert resp.status_code == 200
        students = [u for u in resp.json() if u["role"] == "student"]
        assert students and students[0]["student_number"] == "20210001"

    def test_deactivate_and_activate(self, client, db):
        make_admin(db)
        student_user, _ = make_student(db)
        headers = auth(login(client, "admin@test.com"))
        resp = client.patch(f"/api/v1/admin/users/{student_user.id}/deactivate", headers=headers)
        assert resp.status_code == 200 and resp.json()["is_active"] is False
        resp = client.patch(f"/api/v1/admin/users/{student_user.id}/activate", headers=headers)
        assert resp.status_code == 200 and resp.json()["is_active"] is True

    def test_edit_user(self, client, db):
        make_admin(db)
        student_user, _ = make_student(db)
        headers = auth(login(client, "admin@test.com"))
        resp = client.patch(
            f"/api/v1/admin/users/{student_user.id}/edit",
            json={"first_name": "Renamed", "student_number": "999", "new_password": ""},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["first_name"] == "Renamed"
        assert resp.json()["student_number"] == "999"

    def test_delete_student(self, client, db):
        make_admin(db)
        student_user, _ = make_student(db)
        headers = auth(login(client, "admin@test.com"))
        assert client.delete(f"/api/v1/admin/users/{student_user.id}", headers=headers).status_code == 200
        ids = [u["id"] for u in client.get("/api/v1/admin/users", headers=headers).json()]
        assert student_user.id not in ids
