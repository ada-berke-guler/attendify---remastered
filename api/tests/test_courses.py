from __future__ import annotations

from app.models.models import Enrollment
from tests.conftest import auth, login, make_course, make_instructor, make_student


class TestCourseCreate:
    def test_instructor_creates_course(self, client, db):
        make_instructor(db)
        resp = client.post("/api/v1/courses", json={"code": "CS101", "name": "Intro to CS"},
                           headers=auth(login(client, "instructor@test.com")))
        assert resp.status_code == 201
        assert resp.json()["code"] == "CS101"

    def test_student_cannot_create_course(self, client, db):
        make_student(db)
        resp = client.post("/api/v1/courses", json={"code": "CS999", "name": "Forbidden"},
                           headers=auth(login(client, "student@test.com")))
        assert resp.status_code == 403

    def test_duplicate_code_rejected(self, client, db):
        _, instructor = make_instructor(db)
        make_course(db, instructor, code="CS101")
        resp = client.post("/api/v1/courses", json={"code": "CS101", "name": "Different"},
                           headers=auth(login(client, "instructor@test.com")))
        assert resp.status_code == 400


class TestCourseList:
    def test_instructor_sees_own_courses(self, client, db):
        _, instructor = make_instructor(db)
        make_course(db, instructor, code="CS101")
        make_course(db, instructor, code="CS102")
        resp = client.get("/api/v1/courses", headers=auth(login(client, "instructor@test.com")))
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_student_sees_enrolled_courses(self, client, db):
        _, instructor = make_instructor(db)
        course = make_course(db, instructor, code="CS101")
        _, student = make_student(db)
        db.add(Enrollment(student_id=student.id, course_id=course.id))
        db.commit()
        resp = client.get("/api/v1/courses", headers=auth(login(client, "student@test.com")))
        assert resp.status_code == 200
        assert [c["code"] for c in resp.json()] == ["CS101"]


class TestEnrollment:
    def test_enroll_student(self, client, db):
        _, instructor = make_instructor(db)
        course = make_course(db, instructor, code="CS200")
        _, student = make_student(db)
        resp = client.post(f"/api/v1/courses/{course.id}/enroll",
                           json={"student_id": student.id, "course_id": course.id},
                           headers=auth(login(client, "instructor@test.com")))
        assert resp.status_code == 201

    def test_double_enroll_rejected(self, client, db):
        _, instructor = make_instructor(db)
        course = make_course(db, instructor, code="CS201")
        _, student = make_student(db)
        db.add(Enrollment(student_id=student.id, course_id=course.id))
        db.commit()
        resp = client.post(f"/api/v1/courses/{course.id}/enroll",
                           json={"student_id": student.id, "course_id": course.id},
                           headers=auth(login(client, "instructor@test.com")))
        assert resp.status_code == 409

    def test_list_students(self, client, db):
        _, instructor = make_instructor(db)
        course = make_course(db, instructor, code="CS202")
        _, student = make_student(db)
        db.add(Enrollment(student_id=student.id, course_id=course.id))
        db.commit()
        resp = client.get(f"/api/v1/courses/{course.id}/students", headers=auth(login(client, "instructor@test.com")))
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_search_requires_course_ownership(self, client, db):
        _, owner = make_instructor(db, email="owner@test.com")
        make_instructor(db, email="other@test.com")
        course = make_course(db, owner, code="CS203")
        resp = client.get(f"/api/v1/courses/{course.id}/students/search?q=a",
                          headers=auth(login(client, "other@test.com")))
        assert resp.status_code == 404
