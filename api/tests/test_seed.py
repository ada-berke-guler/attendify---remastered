from __future__ import annotations

from app.models.models import Course, CourseSchedule, Enrollment, User
from seed import seed


def test_seed_is_idempotent(db):
    seed(db)
    counts = [db.query(m).count() for m in (User, Course, CourseSchedule, Enrollment)]
    seed(db)
    assert [db.query(m).count() for m in (User, Course, CourseSchedule, Enrollment)] == counts
    assert counts == [5, 2, 4, 6]
