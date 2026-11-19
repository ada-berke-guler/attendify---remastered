"""R1.2: 1:N search only looks at students enrolled in the session's course."""
from __future__ import annotations

from app.models.models import Enrollment
from tests.conftest import auth, enroll_face, frame, login, make_student, setup_class


def _identify(client, session_id: int, face_id: str):
    return client.post(
        f"/api/v1/sessions/{session_id}/identify",
        files={"image": ("q.jpg", frame(face_id=face_id), "image/jpeg")},
        headers=auth(login(client, "instructor@test.com")),
    )


def test_identify_finds_enrolled_student(client, db, r):
    _, course, session, _, student = setup_class(db, r, face_id="alice")
    _, bob = make_student(db, email="bob@test.com", student_number="20210002")
    db.add(Enrollment(student_id=bob.id, course_id=course.id))
    db.commit()
    enroll_face(db, bob, "bob")

    resp = _identify(client, session.id, "alice")
    assert resp.status_code == 200, resp.text
    candidates = resp.json()["candidates"]
    assert candidates[0]["student_id"] == student.id
    assert candidates[0]["is_match"] is True
    assert candidates[1]["student_id"] == bob.id and candidates[1]["is_match"] is False


def test_identify_only_returns_students_of_the_course(client, db, r):
    _, _, session, _, _ = setup_class(db, r, face_id="alice")
    _, outsider = make_student(db, email="out@test.com", student_number="20210003")
    enroll_face(db, outsider, "carol")  # not enrolled in the course

    candidates = _identify(client, session.id, "carol").json()["candidates"]
    assert outsider.id not in [c["student_id"] for c in candidates]
    assert all(not c["is_match"] for c in candidates)


def test_identify_returns_at_most_three(client, db, r):
    _, course, session, _, _ = setup_class(db, r, face_id="s0")
    for i in range(1, 6):
        _, s = make_student(db, email=f"s{i}@test.com", student_number=f"N{i}")
        db.add(Enrollment(student_id=s.id, course_id=course.id))
        db.commit()
        enroll_face(db, s, f"s{i}")
    assert len(_identify(client, session.id, "s3").json()["candidates"]) == 3


def test_identify_requires_owner(client, db, r):
    from tests.conftest import make_instructor

    _, _, session, _, _ = setup_class(db, r)
    make_instructor(db, email="other@test.com")
    resp = client.post(
        f"/api/v1/sessions/{session.id}/identify",
        files={"image": ("q.jpg", frame(), "image/jpeg")},
        headers=auth(login(client, "other@test.com")),
    )
    assert resp.status_code == 404


def test_identify_marks_already_present(client, db, r):
    _, _, session, _, student = setup_class(db, r, face_id="alice")
    client.post(f"/api/v1/sessions/{session.id}/mark-present", json={"student_id": student.id},
                headers=auth(login(client, "instructor@test.com")))
    assert _identify(client, session.id, "alice").json()["candidates"][0]["already_present"] is True
