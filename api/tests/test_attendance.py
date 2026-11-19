from __future__ import annotations

from app.models.models import AttendanceRecord, AttendanceSession, SessionStatus, VerificationMethod
from tests.conftest import (
    auth, blink, login, make_course, make_instructor, make_student, qr_token_for, setup_class, submit,
)


class TestSubmitAttendance:
    def test_successful_submission(self, client, db, r):
        _, _, session, _, _ = setup_class(db, r)
        token = login(client, "student@test.com")
        resp = submit(client, token, qr_token_for(r, session), blink(client, token))
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["qr_validated"] is True
        assert data["face_validated"] is True
        assert data["verification_method"] == "face"
        assert data["face_distance"] is not None and data["face_distance"] < 0.01

    def test_different_face_rejected(self, client, db, r):
        _, _, session, _, _ = setup_class(db, r, face_id="alice")
        token = login(client, "student@test.com")
        ticket = blink(client, token, face_id="mallory")
        resp = submit(client, token, qr_token_for(r, session), ticket, face_id="mallory")
        assert resp.status_code == 422
        assert "distance" in resp.json()["detail"]

    def test_face_must_be_the_one_that_blinked(self, client, db, r):
        """A live blink by someone else plus a photo of the real student is rejected."""
        _, _, session, _, _ = setup_class(db, r, face_id="alice")
        token = login(client, "student@test.com")
        ticket = blink(client, token, face_id="accomplice")
        resp = submit(client, token, qr_token_for(r, session), ticket, face_id="alice")
        assert resp.status_code == 422
        assert "liveness" in resp.json()["detail"]

    def test_no_face_detected(self, client, db, r):
        _, _, session, _, _ = setup_class(db, r)
        token = login(client, "student@test.com")
        ticket = blink(client, token)
        resp = client.post(
            "/api/v1/attendance/submit",
            data={"qr_token": qr_token_for(r, session), "liveness_ticket": ticket},
            files={"image": ("face.jpg", b"MOCK:faces=0\n", "image/jpeg")},
            headers=auth(token),
        )
        assert resp.status_code == 422
        assert "No face" in resp.json()["detail"]

    def test_invalid_qr_rejected(self, client, db):
        make_student(db)
        token = login(client, "student@test.com")
        resp = submit(client, token, "totally.invalid.token", "whatever")
        assert resp.status_code == 400

    def test_duplicate_submission_rejected(self, client, db, r):
        _, _, session, _, _ = setup_class(db, r)
        token = login(client, "student@test.com")
        assert submit(client, token, qr_token_for(r, session), blink(client, token)).status_code == 201
        resp = submit(client, token, qr_token_for(r, session), blink(client, token))
        assert resp.status_code == 409

    def test_unenrolled_student_rejected(self, client, db, r):
        from tests.conftest import start_session

        _, instructor = make_instructor(db)
        session = start_session(db, r, make_course(db, instructor, code="CS401"), instructor)
        make_student(db)
        token = login(client, "student@test.com")
        resp = submit(client, token, qr_token_for(r, session), blink(client, token))
        assert resp.status_code == 403

    def test_closed_session_rejected(self, client, db, r):
        _, _, session, _, _ = setup_class(db, r)
        token = login(client, "student@test.com")
        qr_token = qr_token_for(r, session)
        session.status = SessionStatus.closed
        db.commit()
        resp = submit(client, token, qr_token, blink(client, token))
        assert resp.status_code == 404

    def test_instructor_cannot_submit(self, client, db, r):
        _, _, session, _, _ = setup_class(db, r)
        token = login(client, "instructor@test.com")
        assert submit(client, token, qr_token_for(r, session), "t").status_code == 403


class TestManualAttendance:
    def test_mark_present_sets_method_manual(self, client, db, r):
        _, _, session, _, student = setup_class(db, r)
        resp = client.post(
            f"/api/v1/sessions/{session.id}/mark-present",
            json={"student_id": student.id},
            headers=auth(login(client, "instructor@test.com")),
        )
        assert resp.status_code == 201
        assert resp.json()["verification_method"] == "manual"

    def test_pending_approval_sets_method_pending_approved(self, client, db, r):
        _, _, session, _, _ = setup_class(db, r)
        student_token = login(client, "student@test.com")
        pending = client.post(
            "/api/v1/attendance/notify-instructor",
            json={"session_id": session.id, "reason": "camera_error"},
            headers=auth(student_token),
        )
        assert pending.status_code == 201
        resp = client.patch(
            f"/api/v1/sessions/{session.id}/pending/{pending.json()['id']}",
            json={"action": "approve"},
            headers=auth(login(client, "instructor@test.com")),
        )
        assert resp.status_code == 200
        record = db.query(AttendanceRecord).filter(AttendanceRecord.session_id == session.id).one()
        assert record.verification_method == VerificationMethod.pending_approved

    def test_session_attendance_list(self, client, db, r):
        _, _, session, _, _ = setup_class(db, r)
        token = login(client, "student@test.com")
        submit(client, token, qr_token_for(r, session), blink(client, token))
        resp = client.get(f"/api/v1/sessions/{session.id}/attendance", headers=auth(login(client, "instructor@test.com")))
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_present"] == 1
        assert body["records"][0]["student"]["student_number"] == "20210001"


class TestAttendanceHistory:
    def test_student_views_own_history(self, client, db, r):
        _, _, session, _, _ = setup_class(db, r)
        token = login(client, "student@test.com")
        submit(client, token, qr_token_for(r, session), blink(client, token))
        resp = client.get("/api/v1/attendance/my", headers=auth(token))
        assert resp.status_code == 200
        assert resp.json()[0]["course_code"] == "CS400"

    def test_student_summary(self, client, db, r):
        _, _, session, _, _ = setup_class(db, r)
        token = login(client, "student@test.com")
        submit(client, token, qr_token_for(r, session), blink(client, token))
        resp = client.get("/api/v1/attendance/my/summary", headers=auth(token))
        assert resp.status_code == 200
        assert resp.json()[0]["attendance_rate"] == 100.0

    def test_session_visible_only_to_participants(self, client, db, r):
        _, _, session, _, _ = setup_class(db, r)
        make_student(db, email="outsider@test.com", student_number="X1")
        assert client.get(f"/api/v1/sessions/{session.id}", headers=auth(login(client, "student@test.com"))).status_code == 200
        assert client.get(f"/api/v1/sessions/{session.id}", headers=auth(login(client, "outsider@test.com"))).status_code == 404
        assert db.get(AttendanceSession, session.id) is not None
