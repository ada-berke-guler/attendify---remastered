from __future__ import annotations

from typing import List

import redis
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_student, get_current_student_profile
from app.core.rate_limit import liveness_rate_limit, submit_rate_limit
from app.core.redis import get_redis
from app.core.request_utils import client_ip
from app.db.session import get_db
from app.models.models import (
    AttendanceRecord, AttendanceSession, AttendanceStatus, Enrollment, Student, User,
)
from app.schemas.schemas import AttendanceOut, ErrorResponse, LivenessResponse, StudentAttendanceSummary
from app.services import attendance as attendance_service
from app.services import liveness
from app.services.face_client import FaceClient, FaceServiceUnavailable, get_face_client

router = APIRouter()


def enrich(record: AttendanceRecord) -> AttendanceOut:
    out = AttendanceOut.model_validate(record)
    if record.session:
        out.session_title = record.session.title
        if record.session.course:
            out.course_id = record.session.course.id
            out.course_code = record.session.course.code
            out.course_name = record.session.course.name
    return out


@router.post(
    "/liveness-check",
    response_model=LivenessResponse,
    summary="Feed one camera frame into the blink challenge",
    description=(
        "Call repeatedly with webcam frames. Once the student has closed and reopened their "
        "eyes, the response carries a single-use `liveness_ticket` (valid "
        f"{settings.LIVENESS_TICKET_TTL_SECONDS}s) that /attendance/submit requires."
    ),
    responses={429: {"model": ErrorResponse}, 503: {"model": ErrorResponse, "description": "Face service down"}},
    dependencies=[Depends(liveness_rate_limit)],
)
def liveness_check(
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_student),
    r: redis.Redis = Depends(get_redis),
    face: FaceClient = Depends(get_face_client),
) -> LivenessResponse:
    image_bytes = image.file.read()
    if len(image_bytes) > settings.MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")
    try:
        result = liveness.process_frame(r, face, current_user.id, image_bytes)
    except FaceServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=attendance_service.FACE_SERVICE_DOWN) from exc
    return LivenessResponse(
        is_live=result.is_live,
        reason=result.reason,
        liveness_ticket=result.ticket,
        ticket_expires_in=settings.LIVENESS_TICKET_TTL_SECONDS if result.ticket else None,
    )


@router.post(
    "/submit",
    response_model=AttendanceOut,
    status_code=201,
    summary="Submit attendance (QR + liveness ticket + face)",
    responses={
        400: {"model": ErrorResponse, "description": "QR invalid, expired or rotated"},
        403: {"model": ErrorResponse, "description": "Not enrolled, or liveness ticket missing/used/foreign"},
        404: {"model": ErrorResponse, "description": "Session not active"},
        409: {"model": ErrorResponse, "description": "Already recorded"},
        422: {"model": ErrorResponse, "description": "No face / face does not match"},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse, "description": "Face service down"},
    },
    dependencies=[Depends(submit_rate_limit)],
)
def submit_attendance(
    request: Request,
    qr_token: str = Form(...),
    liveness_ticket: str = Form("", description="Ticket from /attendance/liveness-check"),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    student: Student = Depends(get_current_student_profile),
    r: redis.Redis = Depends(get_redis),
    face: FaceClient = Depends(get_face_client),
) -> AttendanceOut:
    record = attendance_service.submit(
        db=db,
        r=r,
        face=face,
        student=student,
        qr_token=qr_token,
        liveness_ticket=liveness_ticket,
        image_bytes=image.file.read(),
        ip_address=client_ip(request),
    )
    return enrich(record)


@router.get("/my", response_model=List[AttendanceOut], summary="My attendance history")
def get_my_attendance(
    db: Session = Depends(get_db),
    student: Student = Depends(get_current_student_profile),
) -> List[AttendanceOut]:
    records = (
        db.query(AttendanceRecord)
        .filter(AttendanceRecord.student_id == student.id)
        .order_by(AttendanceRecord.submitted_at.desc())
        .all()
    )
    return [enrich(r) for r in records]


@router.get("/my/summary", response_model=List[StudentAttendanceSummary], summary="My attendance rate per course")
def get_my_attendance_summary(
    db: Session = Depends(get_db),
    student: Student = Depends(get_current_student_profile),
) -> List[StudentAttendanceSummary]:
    summaries = []
    for enrollment in db.query(Enrollment).filter(Enrollment.student_id == student.id).all():
        course = enrollment.course
        total_sessions = db.query(func.count(AttendanceSession.id)).filter(
            AttendanceSession.course_id == course.id
        ).scalar()
        attended = (
            db.query(func.count(AttendanceRecord.id))
            .join(AttendanceSession)
            .filter(
                AttendanceSession.course_id == course.id,
                AttendanceRecord.student_id == student.id,
                AttendanceRecord.status == AttendanceStatus.present,
            )
            .scalar()
        )
        summaries.append(StudentAttendanceSummary(
            course_id=course.id, course_code=course.code, course_name=course.name,
            total_sessions=total_sessions, attended=attended,
            attendance_rate=round(attended / total_sessions * 100, 1) if total_sessions else 0.0,
        ))
    return summaries
