from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import AsyncIterator, List, Optional

import redis
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_instructor_profile, get_current_user
from app.core.redis import get_async_redis, get_redis
from app.core.request_utils import public_base_url
from app.core.security import create_events_token, decode_events_token
from app.db.session import get_db
from app.models.models import (
    AttendanceRecord, AttendanceSession, AttendanceStatus, Course, Enrollment, Instructor,
    PendingAttendance, PendingAttendanceStatus, SessionStatus, Student, User, UserRole,
    VerificationMethod,
)
from app.schemas.schemas import (
    AttendanceOut, AttendanceWithStudent, ErrorResponse, EventsTokenOut, IdentifyCandidate,
    IdentifyResponse, ManualAttendancePayload, MessageResponse, PendingAttendanceOut, QrOut,
    ResolvePendingPayload, ResolvePendingResponse, SessionAttendanceSummary, SessionCreate,
    SessionOut, SessionWithQR, StudentOut, UserOut,
)
from app.services import events, qr
from app.services.attendance import FACE_SERVICE_DOWN, record_event_payload
from app.services.face_client import FaceClient, FaceServiceUnavailable, get_face_client
from app.services.face_matching import identify_in_course

router = APIRouter()

NOT_FOUND = {404: {"model": ErrorResponse, "description": "Session not found or not yours"}}
SSE_HEARTBEAT_SECONDS = 15


def _owned_session(db: Session, instructor: Instructor, session_id: int) -> AttendanceSession:
    session = (
        db.query(AttendanceSession)
        .join(Course)
        .filter(AttendanceSession.id == session_id, Course.instructor_id == instructor.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _session_out(db: Session, s: AttendanceSession, with_counts: bool = False) -> SessionOut:
    out = SessionOut(
        id=s.id, course_id=s.course_id,
        course_code=s.course.code, course_name=s.course.name,
        title=s.title, status=s.status,
        started_at=s.started_at, ended_at=s.ended_at,
    )
    if with_counts:
        out.attended_count = db.query(func.count(AttendanceRecord.id)).filter(
            AttendanceRecord.session_id == s.id
        ).scalar()
        out.total_enrolled = db.query(func.count(Enrollment.id)).filter(
            Enrollment.course_id == s.course_id
        ).scalar()
    return out


def _close(r: redis.Redis, session: AttendanceSession) -> None:
    session.status = SessionStatus.closed
    session.ended_at = datetime.now(UTC)
    qr.deactivate(r, session.id)


@router.post(
    "",
    response_model=SessionWithQR,
    status_code=201,
    summary="Start an attendance session",
    description="Closes any other active session of the course and starts rotating a QR code.",
    responses={404: {"model": ErrorResponse}},
)
def create_session(
    payload: SessionCreate,
    request: Request,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
    r: redis.Redis = Depends(get_redis),
) -> SessionWithQR:
    course = db.query(Course).filter(
        Course.id == payload.course_id, Course.instructor_id == instructor.id, Course.is_active.is_(True)
    ).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found or not yours")
    for old in db.query(AttendanceSession).filter(
        AttendanceSession.course_id == course.id, AttendanceSession.status == SessionStatus.active
    ):
        _close(r, old)
    title = payload.title or f"Session – {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}"
    session = AttendanceSession(
        course_id=course.id, title=title, status=SessionStatus.active, created_by_id=instructor.user_id
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    qr.activate(r, session.id)
    code = qr.current_qr(r, session.id, public_base_url(request))
    return SessionWithQR(
        **_session_out(db, session).model_dump(),
        qr_token=code.token,
        qr_url=code.url,
        qr_image_base64=code.image_base64,
        qr_expires_in=code.expires_in,
        rotate_seconds=code.rotate_seconds,
    )


@router.get("", response_model=List[SessionOut], summary="My sessions, newest first")
def list_my_sessions(
    status: Optional[str] = Query(None, description="`live` or `active` for running sessions only"),
    course_id: Optional[int] = None,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> List[SessionOut]:
    query = (
        db.query(AttendanceSession)
        .join(Course, AttendanceSession.course_id == Course.id)
        .filter(Course.instructor_id == instructor.id)
    )
    if status in ("live", "active"):
        query = query.filter(AttendanceSession.status == SessionStatus.active)
    if course_id is not None:
        query = query.filter(AttendanceSession.course_id == course_id)
    sessions = query.order_by(AttendanceSession.started_at.desc()).all()
    return [_session_out(db, s, with_counts=True) for s in sessions]


@router.get(
    "/{session_id}/qr",
    response_model=QrOut,
    summary="Current QR code",
    description=(
        f"The QR rotates server side every {settings.QR_ROTATE_SECONDS}s; listen for `qr.rotated` "
        "on the events stream and fetch this again."
    ),
    responses={**NOT_FOUND, 400: {"model": ErrorResponse}},
)
def get_qr(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
    r: redis.Redis = Depends(get_redis),
) -> QrOut:
    session = _owned_session(db, instructor, session_id)
    if session.status != SessionStatus.active:
        raise HTTPException(status_code=400, detail="Session is not active")
    code = qr.current_qr(r, session.id, public_base_url(request))
    return QrOut(
        session_id=code.session_id, token=code.token, url=code.url, image_base64=code.image_base64,
        expires_in=code.expires_in, rotate_seconds=code.rotate_seconds,
    )


@router.post(
    "/{session_id}/events-token",
    response_model=EventsTokenOut,
    summary="Short-lived token for the SSE stream",
    description="EventSource cannot send an Authorization header, so the stream takes this token as a query parameter.",
    responses=NOT_FOUND,
)
def create_events_token_endpoint(
    session_id: int,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> EventsTokenOut:
    session = _owned_session(db, instructor, session_id)
    return EventsTokenOut(
        token=create_events_token(instructor.user_id, session.id),
        expires_in=settings.EVENTS_TOKEN_EXPIRE_SECONDS,
    )


async def event_stream(
    request: Request, r: aioredis.Redis, session_id: int, heartbeat: float = SSE_HEARTBEAT_SECONDS
) -> AsyncIterator[str]:
    pubsub = r.pubsub()
    await pubsub.subscribe(events.channel(session_id))
    try:
        yield "retry: 3000\n\n"
        yield events.format_sse(events.build_event("hello", session_id))
        loop = asyncio.get_running_loop()
        last_beat = loop.time()
        while True:
            if await request.is_disconnected():
                break
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                yield events.format_sse(message["data"])
            elif loop.time() - last_beat >= heartbeat:
                last_beat = loop.time()
                yield ": keep-alive\n\n"
    finally:
        await pubsub.unsubscribe(events.channel(session_id))
        await pubsub.aclose()


@router.get(
    "/{session_id}/events",
    summary="Live events (Server-Sent Events)",
    description=(
        "Event types: `attendance.created`, `attendance.removed`, `pending.created`, "
        "`pending.resolved`, `qr.rotated`. Authenticate with `?token=` from /events-token."
    ),
    responses={200: {"content": {"text/event-stream": {}}}, 401: {"model": ErrorResponse}},
)
async def session_events(
    session_id: int,
    request: Request,
    token: str = Query(...),
    r: aioredis.Redis = Depends(get_async_redis),
) -> StreamingResponse:
    payload = decode_events_token(token)
    if not payload or payload.get("session_id") != session_id:
        raise HTTPException(status_code=401, detail="Invalid or expired events token")
    return StreamingResponse(
        event_stream(request, r, session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.websocket("/{session_id}/ws")
async def session_events_ws(
    websocket: WebSocket,
    session_id: int,
    token: str = Query(...),
    r: aioredis.Redis = Depends(get_async_redis),
) -> None:
    """Same events as /events, over a WebSocket.

    Fallback for proxies that buffer text/event-stream (Cloudflare quick tunnels do).
    The client switches here when the SSE `hello` does not arrive in time.
    """
    payload = decode_events_token(token)
    if not payload or payload.get("session_id") != session_id:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    pubsub = r.pubsub()
    await pubsub.subscribe(events.channel(session_id))
    try:
        await websocket.send_text(events.build_event("hello", session_id))
        loop = asyncio.get_running_loop()
        last_beat = loop.time()
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                await websocket.send_text(message["data"])
            elif loop.time() - last_beat >= SSE_HEARTBEAT_SECONDS:
                last_beat = loop.time()
                await websocket.send_text(events.build_event("ping", session_id))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await pubsub.unsubscribe(events.channel(session_id))
        await pubsub.aclose()


@router.post("/{session_id}/close", response_model=SessionOut, summary="Close a session", responses=NOT_FOUND)
def close_session(
    session_id: int,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
    r: redis.Redis = Depends(get_redis),
) -> SessionOut:
    session = _owned_session(db, instructor, session_id)
    _close(r, session)
    db.commit()
    db.refresh(session)
    return _session_out(db, session)


@router.post(
    "/{session_id}/identify",
    response_model=IdentifyResponse,
    summary="Find a student by photo (1:N pgvector search)",
    description=(
        "Returns the 3 closest students enrolled in this session's course, ordered by L2 distance. "
        "Used by the manual attendance screen."
    ),
    responses={**NOT_FOUND, 422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def identify_student(
    session_id: int,
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
    face: FaceClient = Depends(get_face_client),
) -> IdentifyResponse:
    session = _owned_session(db, instructor, session_id)
    try:
        analysis = face.analyze(image.file.read(), with_embedding=True)
    except FaceServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=FACE_SERVICE_DOWN) from exc
    if analysis.face_count != 1 or not analysis.embedding:
        raise HTTPException(status_code=422, detail="Need exactly one face in the photo")
    present = {
        sid for (sid,) in db.query(AttendanceRecord.student_id).filter(AttendanceRecord.session_id == session.id)
    }
    candidates = identify_in_course(db, session.course_id, analysis.embedding)
    return IdentifyResponse(
        max_distance=settings.FACE_MATCH_MAX_DISTANCE,
        candidates=[
            IdentifyCandidate(
                student_id=c.student.id,
                student_number=c.student.student_number,
                full_name=c.student.user.full_name,
                distance=round(c.distance, 4),
                is_match=c.is_match,
                already_present=c.student.id in present,
            )
            for c in candidates
        ],
    )


@router.post(
    "/{session_id}/mark-present",
    response_model=AttendanceOut,
    status_code=201,
    summary="Mark a student present manually",
    responses={**NOT_FOUND, 403: {"model": ErrorResponse}},
)
def mark_present_manually(
    session_id: int,
    payload: ManualAttendancePayload,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
    r: redis.Redis = Depends(get_redis),
) -> AttendanceOut:
    session = _owned_session(db, instructor, session_id)
    student = db.get(Student, payload.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    enrolled = db.query(Enrollment).filter(
        Enrollment.student_id == student.id, Enrollment.course_id == session.course_id
    ).first()
    if not enrolled:
        raise HTTPException(status_code=403, detail="Student is not enrolled in this course")
    record = db.query(AttendanceRecord).filter(
        AttendanceRecord.session_id == session.id, AttendanceRecord.student_id == student.id
    ).first()
    if record is None:
        record = AttendanceRecord(session_id=session.id, student_id=student.id)
        db.add(record)
    record.status = AttendanceStatus.present
    record.verification_method = VerificationMethod.manual
    record.qr_validated = False
    record.face_validated = False
    record.face_distance = None
    db.commit()
    db.refresh(record)
    events.publish(r, session.id, events.ATTENDANCE_CREATED, record_event_payload(record, student))
    return AttendanceOut.model_validate(record)


@router.delete(
    "/{session_id}/mark-present/{student_id}",
    response_model=MessageResponse,
    summary="Remove an attendance record",
    responses=NOT_FOUND,
)
def remove_attendance(
    session_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
    r: redis.Redis = Depends(get_redis),
) -> MessageResponse:
    session = _owned_session(db, instructor, session_id)
    record = db.query(AttendanceRecord).filter(
        AttendanceRecord.session_id == session.id, AttendanceRecord.student_id == student_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    record_id = record.id
    db.delete(record)
    db.commit()
    events.publish(r, session.id, events.ATTENDANCE_REMOVED, {"record_id": record_id, "student_id": student_id})
    return MessageResponse(message="Attendance record removed successfully")


def _pending_out(p: PendingAttendance) -> PendingAttendanceOut:
    return PendingAttendanceOut(
        id=p.id, session_id=p.session_id, student_id=p.student_id,
        student_name=p.student.user.full_name, student_number=p.student.student_number,
        reason=p.reason, note=p.note, status=p.status, created_at=p.created_at,
    )


@router.get(
    "/{session_id}/pending",
    response_model=List[PendingAttendanceOut],
    summary="Open manual-attendance requests",
    responses=NOT_FOUND,
)
def get_pending_attendances(
    session_id: int,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> List[PendingAttendanceOut]:
    _owned_session(db, instructor, session_id)
    pendings = (
        db.query(PendingAttendance)
        .filter(PendingAttendance.session_id == session_id, PendingAttendance.status == PendingAttendanceStatus.pending)
        .order_by(PendingAttendance.created_at.asc())
        .all()
    )
    return [_pending_out(p) for p in pendings]


@router.patch(
    "/{session_id}/pending/{pending_id}",
    response_model=ResolvePendingResponse,
    summary="Approve or decline a manual-attendance request",
    responses={**NOT_FOUND, 400: {"model": ErrorResponse}},
)
def resolve_pending(
    session_id: int,
    pending_id: int,
    payload: ResolvePendingPayload,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
    r: redis.Redis = Depends(get_redis),
) -> ResolvePendingResponse:
    session = _owned_session(db, instructor, session_id)
    pending = db.query(PendingAttendance).filter(
        PendingAttendance.id == pending_id, PendingAttendance.session_id == session.id
    ).first()
    if not pending:
        raise HTTPException(status_code=404, detail="Pending attendance not found")
    if pending.status != PendingAttendanceStatus.pending:
        raise HTTPException(status_code=400, detail="This request has already been resolved")
    pending.resolved_at = datetime.now(UTC)
    record = None
    if payload.action == "approve":
        pending.status = PendingAttendanceStatus.approved
        record = db.query(AttendanceRecord).filter(
            AttendanceRecord.session_id == session.id, AttendanceRecord.student_id == pending.student_id
        ).first()
        if record is None:
            record = AttendanceRecord(
                session_id=session.id, student_id=pending.student_id,
                qr_validated=False, face_validated=False, face_distance=None,
            )
            db.add(record)
        record.status = AttendanceStatus.present
        record.verification_method = VerificationMethod.pending_approved
    else:
        pending.status = PendingAttendanceStatus.declined
    db.commit()

    record_dict = None
    if record is not None:
        db.refresh(record)
        record_dict = {
            "id": record.id, "session_id": record.session_id, "student_id": record.student_id,
            "status": record.status.value, "verification_method": record.verification_method.value,
            "face_validated": record.face_validated, "qr_validated": record.qr_validated,
        }
        events.publish(r, session.id, events.ATTENDANCE_CREATED, record_event_payload(record, pending.student))
    events.publish(r, session.id, events.PENDING_RESOLVED, {"pending_id": pending.id, "status": pending.status.value})
    return ResolvePendingResponse(pending_id=pending.id, status=pending.status, attendance_record=record_dict)


@router.get(
    "/course/{course_id}",
    response_model=List[SessionOut],
    summary="Sessions of one of my courses",
    responses={404: {"model": ErrorResponse}},
)
def list_sessions_for_course(
    course_id: int,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> List[SessionOut]:
    course = db.query(Course).filter(Course.id == course_id, Course.instructor_id == instructor.id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    sessions = (
        db.query(AttendanceSession)
        .filter(AttendanceSession.course_id == course_id)
        .order_by(AttendanceSession.started_at.desc())
        .all()
    )
    return [_session_out(db, s, with_counts=True) for s in sessions]


@router.get(
    "/{session_id}",
    response_model=SessionOut,
    summary="Session details (owner instructor or enrolled student)",
    responses={404: {"model": ErrorResponse}},
)
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionOut:
    session = db.get(AttendanceSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    allowed = current_user.role == UserRole.admin
    if current_user.role == UserRole.instructor:
        allowed = bool(session.course.instructor and session.course.instructor.user_id == current_user.id)
    elif current_user.role == UserRole.student:
        allowed = db.query(Enrollment).join(Student).filter(
            Student.user_id == current_user.id, Enrollment.course_id == session.course_id
        ).first() is not None
    if not allowed:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_out(db, session)


@router.get(
    "/{session_id}/attendance",
    response_model=SessionAttendanceSummary,
    summary="Attendance list of a session",
    responses=NOT_FOUND,
)
def get_session_attendance(
    session_id: int,
    db: Session = Depends(get_db),
    instructor: Instructor = Depends(get_current_instructor_profile),
) -> SessionAttendanceSummary:
    session = _owned_session(db, instructor, session_id)
    total_enrolled = db.query(func.count(Enrollment.id)).filter(Enrollment.course_id == session.course_id).scalar()
    records = (
        db.query(AttendanceRecord)
        .filter(AttendanceRecord.session_id == session_id)
        .order_by(AttendanceRecord.submitted_at.asc())
        .all()
    )
    enriched = []
    for rec in records:
        student = rec.student
        if not student or not student.user:
            continue
        enriched.append(AttendanceWithStudent(
            **AttendanceOut.model_validate(rec).model_dump(),
            student=StudentOut(
                id=student.id, user_id=student.user_id,
                student_number=student.student_number or "",
                department=student.department, face_enrolled=bool(student.face_enrolled),
                user=UserOut.model_validate(student.user),
            ),
        ))
    total_present = sum(1 for rec in records if rec.status == AttendanceStatus.present)
    return SessionAttendanceSummary(
        session_id=session.id, session_title=session.title,
        course_code=session.course.code, course_name=session.course.name,
        started_at=session.started_at, total_enrolled=total_enrolled,
        total_present=total_present,
        attendance_rate=round(total_present / total_enrolled * 100, 1) if total_enrolled else 0.0,
        records=enriched,
    )
