"""Idempotent demo data.

  python seed.py

Creates (skipping anything that already exists, matched by email / course code):
  admin       admin@test.com   / admin123
  instructor  hoca@test.com    / hoca123
  students    ali@test.com, ayse@test.com, mehmet@test.com / 123456
  courses     CS101, CS201 with a weekly schedule, all students enrolled
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.db.session import SessionLocal
from app.models.models import Course, CourseSchedule, DayOfWeek, Enrollment, Instructor, Student, User, UserRole

logger = logging.getLogger("attendify.seed")

DEMO_STUDENTS = [
    ("ali@test.com", "Ali", "Yilmaz", "20210001"),
    ("ayse@test.com", "Ayse", "Demir", "20210002"),
    ("mehmet@test.com", "Mehmet", "Kaya", "20210003"),
]
DEMO_COURSES = [
    ("CS101", "Introduction to Programming", "Python basics",
     [(DayOfWeek.monday, "09:00", "11:00", "A101"), (DayOfWeek.wednesday, "09:00", "11:00", "A101")]),
    ("CS201", "Data Structures", "Trees, graphs, hash tables",
     [(DayOfWeek.tuesday, "13:00", "15:00", "B205"), (DayOfWeek.thursday, "13:00", "15:00", "B205")]),
]


def _user(db: Session, *, email: str, password: str, first_name: str, last_name: str, role: UserRole) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(
        email=email, hashed_password=get_password_hash(password),
        first_name=first_name, last_name=last_name, role=role, is_active=True,
    )
    db.add(user)
    db.flush()
    logger.info("created %s %s", role.value, email)
    return user


def seed(db: Session) -> None:
    _user(db, email="admin@test.com", password="admin123", first_name="System", last_name="Admin", role=UserRole.admin)

    hoca_user = _user(db, email="hoca@test.com", password="hoca123", first_name="Ali", last_name="Hoca",
                      role=UserRole.instructor)
    hoca = db.query(Instructor).filter(Instructor.user_id == hoca_user.id).first()
    if not hoca:
        hoca = Instructor(user_id=hoca_user.id, department="Computer Engineering", title="Dr.")
        db.add(hoca)
        db.flush()

    students = []
    for email, first, last, number in DEMO_STUDENTS:
        user = _user(db, email=email, password="123456", first_name=first, last_name=last, role=UserRole.student)
        student = db.query(Student).filter(Student.user_id == user.id).first()
        if not student:
            student = Student(user_id=user.id, student_number=number, department="Computer Engineering",
                              face_enrolled=False, enrollment_consent=False)
            db.add(student)
            db.flush()
        students.append(student)

    for code, name, description, slots in DEMO_COURSES:
        course = db.query(Course).filter(Course.code == code).first()
        if not course:
            course = Course(code=code, name=name, description=description, instructor_id=hoca.id, is_active=True)
            db.add(course)
            db.flush()
            logger.info("created course %s", code)
        for day, start, end, room in slots:
            exists = db.query(CourseSchedule).filter(
                CourseSchedule.course_id == course.id, CourseSchedule.day_of_week == day,
                CourseSchedule.start_time == start,
            ).first()
            if not exists:
                db.add(CourseSchedule(course_id=course.id, day_of_week=day, start_time=start, end_time=end, room=room))
        for student in students:
            if not db.query(Enrollment).filter(
                Enrollment.student_id == student.id, Enrollment.course_id == course.id
            ).first():
                db.add(Enrollment(student_id=student.id, course_id=course.id))
    db.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with SessionLocal() as db:
        seed(db)
    logger.info("demo data ready: admin@test.com/admin123, hoca@test.com/hoca123, ali@test.com/123456")


if __name__ == "__main__":
    main()
