from __future__ import annotations

import redis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_student_profile
from app.core.redis import get_redis
from app.db.session import get_db
from app.models.models import (
    AttendanceRecord, AttendanceSession, Enrollment, PendingAttendance,
    PendingAttendanceStatus, SessionStatus, Student,
)
from app.schemas.schemas import ErrorResponse, NotifyInstructorPayload, PendingAttendanceOut
from app.services import events, qr

router = APIRouter()


@router.post(
    "/notify-instructor",
    response_model=PendingAttendanceOut,
    status_code=201,
    summary="Ask the instructor for manual attendance",
    description="Fallback when the camera or QR flow fails. Shows up live on the instructor screen.",
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def notify_instructor(
    payload: NotifyInstructorPayload,
    db: Session = Depends(get_db),
    student: Student = Depends(get_current_student_profile),
    r: redis.Redis = Depends(get_redis),
) -> PendingAttendanceOut:
    session_id = payload.session_id
    if session_id is None and payload.qr_token:
        # Only signature + expiry here: the request is reviewed by a human anyway.
        try:
            session_id = qr.session_id_from_token(payload.qr_token)
        except qr.QrError as exc:
            raise HTTPException(status_code=400, detail="Invalid or expired QR token") from exc
    if session_id is None:
        raise HTTPException(status_code=400, detail="session_id or qr_token is required")

    session = db.query(AttendanceSession).filter(
        AttendanceSession.id == session_id, AttendanceSession.status == SessionStatus.active
    ).first()
    if not session:
        raise HTTPException(status_code=400, detail="Session not found or not active")
    if not db.query(Enrollment).filter(
        Enrollment.student_id == student.id, Enrollment.course_id == session.course_id
    ).first():
        raise HTTPException(status_code=403, detail="You are not enrolled in this course")
    if db.query(AttendanceRecord).filter(
        AttendanceRecord.session_id == session.id, AttendanceRecord.student_id == student.id
    ).first():
        raise HTTPException(status_code=409, detail="Attendance already recorded for this session")
    if db.query(PendingAttendance).filter(
        PendingAttendance.session_id == session.id, PendingAttendance.student_id == student.id
    ).first():
        raise HTTPException(status_code=409, detail="Notification already sent for this session")

    pending = PendingAttendance(
        session_id=session.id, student_id=student.id,
        reason=payload.reason, note=payload.note, status=PendingAttendanceStatus.pending,
    )
    db.add(pending)
    db.commit()
    db.refresh(pending)
    out = PendingAttendanceOut(
        id=pending.id, session_id=pending.session_id, student_id=pending.student_id,
        student_name=student.user.full_name, student_number=student.student_number,
        reason=pending.reason, note=pending.note, status=pending.status, created_at=pending.created_at,
    )
    events.publish(r, session.id, events.PENDING_CREATED, out.model_dump(mode="json"))
    return out
