from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, EmailStr, Field
from app.models.models import (
    AttendanceStatus, DayOfWeek, PendingAttendanceStatus,
    PendingReason, SessionStatus, UserRole, VerificationMethod,
)

class MessageResponse(BaseModel):
    message: str

class ErrorResponse(BaseModel):
    detail: str

# ── Auth ──────────────────────────────────────────────────────────────────
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    user_id: int
    full_name: str
    student_number: Optional[str] = None
    department: Optional[str] = None
    face_enrolled: Optional[bool] = None

class TokenData(BaseModel):
    user_id: Optional[int] = None
    role: Optional[UserRole] = None

class UserBase(BaseModel):
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    role: UserRole

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)

class UserOut(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    student_number: Optional[str] = None
    department: Optional[str] = None
    face_enrolled: Optional[bool] = None
    title: Optional[str] = None
    instructor_id: Optional[int] = None
    model_config = {"from_attributes": True}

class UpdateProfilePayload(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    department: Optional[str] = None
    title: Optional[str] = None

class ChangePasswordPayload(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)
    confirm_password: str

class ForgotPasswordPayload(BaseModel):
    email: EmailStr

class ResetPasswordPayload(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=8)

# ── Student ───────────────────────────────────────────────────────────────
class StudentCreate(UserCreate):
    student_number: Optional[str] = Field(None, min_length=1, max_length=20)
    department: Optional[str] = None
    role: UserRole = UserRole.student

class StudentOut(BaseModel):
    id: int
    user_id: int
    student_number: str
    department: Optional[str] = None
    face_enrolled: bool
    user: UserOut
    model_config = {"from_attributes": True}

# ── Instructor ────────────────────────────────────────────────────────────
class InstructorCreate(UserCreate):
    department: Optional[str] = None
    title: Optional[str] = None
    role: UserRole = UserRole.instructor

class InstructorOut(BaseModel):
    id: int
    user_id: int
    department: Optional[str] = None
    title: Optional[str] = None
    user: UserOut
    model_config = {"from_attributes": True}

# ── Course Schedule ───────────────────────────────────────────────────────
class ScheduleSlot(BaseModel):
    day_of_week: DayOfWeek
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    room: Optional[str] = None

class ScheduleSlotOut(BaseModel):
    id: int
    course_id: int
    day_of_week: DayOfWeek
    start_time: str
    end_time: str
    room: Optional[str] = None
    model_config = {"from_attributes": True}

class SetSchedulePayload(BaseModel):
    schedule: List[ScheduleSlot] = Field(..., min_length=1, max_length=5)

class SetScheduleResponse(BaseModel):
    message: str
    slots: List[ScheduleSlotOut]

# ── Student Schedule ──────────────────────────────────────────────────────
class StudentScheduleItem(BaseModel):
    course_id: int
    course_code: str
    course_name: str
    instructor_name: Optional[str] = None
    day_of_week: str
    start_time: str
    end_time: str
    room: Optional[str] = None
    session_id: Optional[int] = None
    session_status: Optional[str] = None

# ── Recent Activity
class RecentActivityItem(BaseModel):
    course_code: str
    course_name: str
    status: str
    submitted_at: datetime

# ── Student Dashboard ─────────────────────────────────────────────────────
class StudentDashboard(BaseModel):
    student_id: int
    full_name: str
    student_number: str
    face_enrolled: bool
    department: Optional[str] = None
    today_class_count: int
    overall_attendance_rate: float
    recent_activity: List[RecentActivityItem]
    next_class: Optional[StudentScheduleItem] = None

# ── Course ────────────────────────────────────────────────────────────────
class CourseCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=20)
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None

class CourseUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=2, max_length=20)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    is_active: Optional[bool] = None

class CourseOut(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool
    instructor_id: Optional[int] = None
    created_at: datetime
    model_config = {"from_attributes": True}

class CourseWithInstructor(CourseOut):
    instructor: Optional[InstructorOut] = None
    model_config = {"from_attributes": True}

class EnrollmentCreate(BaseModel):
    student_id: Optional[int] = None
    student_number: Optional[str] = None
    course_id: int

class EnrollmentOut(BaseModel):
    id: int
    student_id: int
    course_id: int
    enrolled_at: datetime
    model_config = {"from_attributes": True}

# ── Session ───────────────────────────────────────────────────────────────
class SessionCreate(BaseModel):
    course_id: int
    title: Optional[str] = None

class SessionOut(BaseModel):
    id: int
    course_id: int
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    title: Optional[str] = None
    status: SessionStatus
    started_at: datetime
    ended_at: Optional[datetime] = None
    attended_count: Optional[int] = 0
    total_enrolled: Optional[int] = 0
    model_config = {"from_attributes": True}

class SessionWithQR(SessionOut):
    qr_token: str
    qr_url: str
    qr_image_base64: str
    qr_expires_in: int
    rotate_seconds: int

class QrOut(BaseModel):
    session_id: int
    token: str
    url: str
    image_base64: str
    expires_in: int = Field(..., description="Seconds until the next rotation")
    rotate_seconds: int

class EventsTokenOut(BaseModel):
    token: str
    expires_in: int

class IdentifyCandidate(BaseModel):
    student_id: int
    student_number: str
    full_name: str
    distance: float
    is_match: bool
    already_present: bool

class IdentifyResponse(BaseModel):
    candidates: List[IdentifyCandidate]
    max_distance: float

# ── Pending Attendance ────────────────────────────────────────────────────
class NotifyInstructorPayload(BaseModel):
    session_id: Optional[int] = None
    qr_token: Optional[str] = None
    reason: PendingReason = PendingReason.qr_failed
    note: Optional[str] = None

class PendingAttendanceOut(BaseModel):
    id: int
    session_id: int
    student_id: int
    student_name: str
    student_number: str
    reason: PendingReason
    note: Optional[str] = None
    status: PendingAttendanceStatus
    created_at: datetime
    model_config = {"from_attributes": True}

class ResolvePendingPayload(BaseModel):
    action: str = Field(..., pattern="^(approve|decline)$")
    note: Optional[str] = None

class ManualAttendancePayload(BaseModel):
    student_id: int
    note: Optional[str] = None

class AdminEditUserPayload(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    department: Optional[str] = None
    title: Optional[str] = None
    student_number: Optional[str] = None
    new_password: Optional[str] = None  # empty string means "keep the current password"

class ResolvePendingResponse(BaseModel):
    pending_id: int
    status: PendingAttendanceStatus
    attendance_record: Optional[Dict[str, Any]] = None

# ── Attendance ────────────────────────────────────────────────────────────
class AttendanceOut(BaseModel):
    id: int
    session_id: int
    student_id: int
    status: AttendanceStatus
    face_distance: Optional[float] = None
    verification_method: VerificationMethod
    qr_validated: bool
    face_validated: bool
    submitted_at: datetime
    session_title: Optional[str] = None
    course_id: Optional[int] = None
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    model_config = {"from_attributes": True}

class AttendanceWithStudent(AttendanceOut):
    student: StudentOut
    model_config = {"from_attributes": True}

class StudentAttendanceSummary(BaseModel):
    course_id: int
    course_code: str
    course_name: str
    total_sessions: int
    attended: int
    attendance_rate: float

# ── Session Attendance Report ─────────────────────────────────────────────
class SessionAttendanceSummary(BaseModel):
    session_id: int
    session_title: Optional[str] = None
    course_code: str
    course_name: str
    started_at: datetime
    total_enrolled: int
    total_present: int
    attendance_rate: float
    records: List[AttendanceWithStudent]
    model_config = {"from_attributes": True}

# ── Face ──────────────────────────────────────────────────────────────────
class FaceEnrollmentResult(BaseModel):
    success: bool
    photos_processed: int
    message: str

# ── System Config ─────────────────────────────────────────────────────────
class SystemConfigOut(BaseModel):
    absence_threshold: int
    model_config = {"from_attributes": True}

class SystemConfigUpdate(BaseModel):
    absence_threshold: Optional[int] = Field(None, ge=5, le=50)

# ── Liveness ──────────────────────────────────────────────────────────────
class LivenessResponse(BaseModel):
    is_live: bool
    reason: str
    liveness_ticket: Optional[str] = Field(
        None, description="Single-use ticket for /attendance/submit, present only when is_live"
    )
    ticket_expires_in: Optional[int] = None

# ── Reports ───────────────────────────────────────────────────────────────
class StudentRiskReport(BaseModel):
    student_id: int
    student_number: str
    full_name: str
    email: str
    absence_rate: float
    attended: int
    total_sessions: int
    risk_level: str
    last_active: Optional[datetime] = None
