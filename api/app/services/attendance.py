"""Attendance submission flow.

Order of checks (cheap and non-destructive first, the liveness ticket is consumed only
after the request is otherwise valid):

  1. QR token signature + nonce is current/previous     -> 400
  2. session exists and is active                       -> 404
  3. student is enrolled in the course                  -> 403
  4. no record yet for this session                     -> 409
  5. liveness ticket: exists, unused, issued to me      -> 403
  6. face in the submitted image                        -> 422 / 503 if face service down
  7. same face as the one that blinked                  -> 422
  8. pgvector distance to enrolled embeddings           -> 422
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

import redis
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import (
    AttendanceRecord, AttendanceSession, AttendanceStatus, Enrollment,
    SessionStatus, Student, VerificationMethod,
)
from app.services import events, liveness, qr
from app.services.face_client import FaceClient, FaceServiceUnavailable
from app.services.face_matching import best_distance

FACE_SERVICE_DOWN = "Face service is unavailable. Try again in a moment."


def _l2(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=False)))


def record_event_payload(record: AttendanceRecord, student: Student) -> dict:
    return {
        "record_id": record.id,
        "student_id": student.id,
        "student_number": student.student_number,
        "full_name": student.user.full_name if student.user else None,
        "verification_method": record.verification_method.value if record.verification_method else None,
        "face_distance": record.face_distance,
        "submitted_at": record.submitted_at,
    }


def submit(
    *,
    db: Session,
    r: redis.Redis,
    face: FaceClient,
    student: Student,
    qr_token: str,
    liveness_ticket: str,
    image_bytes: bytes,
    ip_address: Optional[str],
) -> AttendanceRecord:
    try:
        session_id = qr.validate_token(r, qr_token)
    except qr.QrError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    session = db.query(AttendanceSession).filter(
        AttendanceSession.id == session_id,
        AttendanceSession.status == SessionStatus.active,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Attendance session not found or not active")

    enrolled = db.query(Enrollment).filter(
        Enrollment.student_id == student.id, Enrollment.course_id == session.course_id
    ).first()
    if not enrolled:
        raise HTTPException(status_code=403, detail="You are not enrolled in this course")

    existing = db.query(AttendanceRecord).filter(
        AttendanceRecord.session_id == session.id, AttendanceRecord.student_id == student.id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Attendance already recorded for this session")

    if len(image_bytes) > settings.MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")

    ticket = liveness.consume_ticket(r, liveness_ticket, student.user_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Liveness check required. Blink at the camera and try again.",
        )

    try:
        analysis = face.analyze(image_bytes, with_embedding=True)
    except FaceServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=FACE_SERVICE_DOWN) from exc
    if analysis.face_count == 0 or analysis.embedding is None:
        raise HTTPException(status_code=422, detail="No face detected in the submitted image")
    if analysis.face_count > 1:
        raise HTTPException(status_code=422, detail="Multiple faces detected")

    if ticket.embedding is not None and _l2(ticket.embedding, analysis.embedding) > settings.FACE_MATCH_MAX_DISTANCE:
        raise HTTPException(status_code=422, detail="The face does not match the face from the liveness check")

    distance = best_distance(db, student.id, analysis.embedding)
    if distance is None:
        raise HTTPException(
            status_code=422,
            detail="No face embeddings enrolled. Please complete face registration first.",
        )
    if distance > settings.FACE_MATCH_MAX_DISTANCE:
        raise HTTPException(status_code=422, detail=f"Face verification failed (distance: {distance:.2f})")

    record = AttendanceRecord(
        session_id=session.id,
        student_id=student.id,
        status=AttendanceStatus.present,
        face_distance=distance,
        verification_method=VerificationMethod.face,
        qr_validated=True,
        face_validated=True,
        ip_address=ip_address,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    events.publish(r, session.id, events.ATTENDANCE_CREATED, record_event_payload(record, student))
    return record
