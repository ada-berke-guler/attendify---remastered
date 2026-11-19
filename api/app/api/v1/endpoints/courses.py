from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_instructor_profile, get_current_user
from app.db.session import get_db
from app.models.models import (
    AttendanceRecord, AttendanceSession, AttendanceStatus, Course, CourseSchedule, Enrollment,
    Instructor, Student, User, UserRole,
)
from app.schemas.schemas import (
    CourseCreate, CourseOut, CourseUpdate, CourseWithInstructor, EnrollmentCreate, EnrollmentOut,
    ErrorResponse, MessageResponse, ScheduleSlotOut, SetSchedulePayload, SetScheduleResponse,
)

router = APIRouter()

NOT_FOUND = {404: {"model": ErrorResponse, "description": "Course not found or not yours"}}


def _owned_course(db: Session, instructor: Instructor, course_id: int) -> Course:
    course = db.query(Course).filter(Course.id == course_id, Course.instructor_id == instructor.id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


def _attended(db: Session, course_id: int, student_id: int | None = None) -> int:
    query = (
        db.query(func.count(AttendanceRecord.id))
        .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
        .filter(AttendanceSession.course_id == course_id, AttendanceRecord.status == AttendanceStatus.present)
    )
    if student_id is not None:
        query = query.filter(AttendanceRecord.student_id == student_id)
    return query.scalar()


def _session_count(db: Session, course_id: int) -> int:
    return db.query(func.count(AttendanceSession.id)).filter(AttendanceSession.course_id == course_id).scalar()


@router.post("", response_model=CourseOut, status_code=201, summary="Create a course",
             responses={400: {"model": ErrorResponse}})
def create_course(
    payload: CourseCreate,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> CourseOut:
    if db.query(Course).filter(Course.code == payload.code).first():
        raise HTTPException(status_code=400, detail="Course code already exists")
    course = Course(code=payload.code, name=payload.name, description=payload.description, instructor_id=instructor.id)
    db.add(course)
    db.commit()
    db.refresh(course)
    return course  # type: ignore[return-value]


@router.get("", response_model=List[CourseOut], summary="My courses (taught or enrolled)")
def list_my_courses(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> List[CourseOut]:
    if current_user.role in (UserRole.instructor, UserRole.admin):
        instructor = db.query(Instructor).filter(Instructor.user_id == current_user.id).first()
        if not instructor:
            return []
        return db.query(Course).filter(Course.instructor_id == instructor.id, Course.is_active.is_(True)).all()  # type: ignore[return-value]
    student = db.query(Student).filter(Student.user_id == current_user.id).first()
    if not student:
        return []
    return (  # type: ignore[return-value]
        db.query(Course)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .filter(Enrollment.student_id == student.id, Course.is_active.is_(True))
        .all()
    )


@router.get("/{course_id}", response_model=CourseWithInstructor, summary="Course details", responses=NOT_FOUND)
def get_course(course_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> CourseWithInstructor:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course  # type: ignore[return-value]


@router.patch("/{course_id}", response_model=CourseOut, summary="Update a course",
              responses={**NOT_FOUND, 400: {"model": ErrorResponse}})
def update_course(
    course_id: int,
    payload: CourseUpdate,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> CourseOut:
    course = _owned_course(db, instructor, course_id)
    if payload.code is not None and payload.code != course.code:
        if db.query(Course).filter(Course.code == payload.code, Course.id != course_id).first():
            raise HTTPException(status_code=400, detail="Course code already exists")
        course.code = payload.code
    if payload.name is not None:
        course.name = payload.name
    if payload.description is not None:
        course.description = payload.description
    if payload.is_active is not None:
        course.is_active = payload.is_active
    db.commit()
    db.refresh(course)
    return course  # type: ignore[return-value]


@router.delete("/{course_id}", response_model=MessageResponse, summary="Archive a course", responses=NOT_FOUND)
def delete_course(
    course_id: int,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> MessageResponse:
    course = _owned_course(db, instructor, course_id)
    course.is_active = False
    db.commit()
    return MessageResponse(message="Course deleted successfully")


@router.get("/{course_id}/stats", summary="Enrollment, session count and attendance rate", responses=NOT_FOUND)
def get_course_stats(
    course_id: int,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> Dict[str, Any]:
    _owned_course(db, instructor, course_id)
    student_count = db.query(func.count(Enrollment.id)).filter(Enrollment.course_id == course_id).scalar()
    session_count = _session_count(db, course_id)
    attendance_rate = None
    if session_count and student_count:
        attendance_rate = round(_attended(db, course_id) / (student_count * session_count), 2)
    return {"student_count": student_count, "session_count": session_count, "attendance_rate": attendance_rate}


@router.post("/{course_id}/enroll", response_model=EnrollmentOut, status_code=201, summary="Enroll a student",
             responses={**NOT_FOUND, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
def enroll_student(
    course_id: int,
    payload: EnrollmentCreate,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> EnrollmentOut:
    _owned_course(db, instructor, course_id)
    if payload.student_number:
        student = db.query(Student).filter(Student.student_number == payload.student_number).first()
    elif payload.student_id is not None:
        student = db.get(Student, payload.student_id)
    else:
        raise HTTPException(status_code=422, detail="Provide student_id or student_number")
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if db.query(Enrollment).filter(Enrollment.student_id == student.id, Enrollment.course_id == course_id).first():
        raise HTTPException(status_code=409, detail="Student already enrolled")
    enrollment = Enrollment(student_id=student.id, course_id=course_id)
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return enrollment  # type: ignore[return-value]


@router.delete("/{course_id}/enroll/{student_id}", response_model=MessageResponse, summary="Unenroll a student",
               responses=NOT_FOUND)
def unenroll_student(
    course_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> MessageResponse:
    _owned_course(db, instructor, course_id)
    enrollment = db.query(Enrollment).filter(
        Enrollment.student_id == student_id, Enrollment.course_id == course_id
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    db.delete(enrollment)
    db.commit()
    return MessageResponse(message="Student unenrolled successfully")


@router.get("/{course_id}/students", summary="Enrolled students with attendance rate", responses=NOT_FOUND)
def list_course_students(
    course_id: int,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> List[Dict[str, Any]]:
    _owned_course(db, instructor, course_id)
    total_sessions = _session_count(db, course_id)
    result = []
    for e in db.query(Enrollment).filter(Enrollment.course_id == course_id).all():
        attended = _attended(db, course_id, e.student.id)
        result.append({
            "student_id": e.student.id,
            "student_number": e.student.student_number,
            "full_name": e.student.user.full_name,
            "email": e.student.user.email,
            "face_enrolled": e.student.face_enrolled,
            "attendance_rate": round(attended / total_sessions, 2) if total_sessions else 0.0,
            "attended_sessions": attended,
            "total_sessions": total_sessions,
        })
    return result


@router.get("/{course_id}/students/search", summary="Search students to enroll", responses=NOT_FOUND)
def search_students_for_course(
    course_id: int,
    q: str = Query("", min_length=0),
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> List[Dict[str, Any]]:
    _owned_course(db, instructor, course_id)
    enrolled_ids = {sid for (sid,) in db.query(Enrollment.student_id).filter(Enrollment.course_id == course_id)}
    query = db.query(Student).join(User, Student.user_id == User.id)
    if q:
        term = f"%{q}%"
        query = query.filter(User.first_name.ilike(term) | User.last_name.ilike(term) | Student.student_number.ilike(term))
    return [
        {
            "student_id": s.id,
            "student_number": s.student_number,
            "full_name": s.user.full_name,
            "email": s.user.email,
            "already_enrolled": s.id in enrolled_ids,
        }
        for s in query.limit(20).all()
    ]


@router.post("/{course_id}/schedule", response_model=SetScheduleResponse, status_code=201,
             summary="Replace the weekly schedule", responses=NOT_FOUND)
def set_course_schedule(
    course_id: int,
    payload: SetSchedulePayload,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> SetScheduleResponse:
    _owned_course(db, instructor, course_id)
    db.query(CourseSchedule).filter(CourseSchedule.course_id == course_id).delete()
    slots = [
        CourseSchedule(course_id=course_id, day_of_week=slot.day_of_week,
                       start_time=slot.start_time, end_time=slot.end_time, room=slot.room)
        for slot in payload.schedule
    ]
    db.add_all(slots)
    db.commit()
    for s in slots:
        db.refresh(s)
    return SetScheduleResponse(message="Schedule set successfully", slots=slots)  # type: ignore[arg-type]


@router.get("/{course_id}/schedule", response_model=List[ScheduleSlotOut], summary="Weekly schedule",
            responses=NOT_FOUND)
def get_course_schedule(
    course_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> List[ScheduleSlotOut]:
    if not db.get(Course, course_id):
        raise HTTPException(status_code=404, detail="Course not found")
    return db.query(CourseSchedule).filter(CourseSchedule.course_id == course_id).all()  # type: ignore[return-value]
