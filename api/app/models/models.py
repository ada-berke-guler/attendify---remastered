from __future__ import annotations

import enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean, Column, DateTime, Enum as SAEnum,
    Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base

EMBEDDING_DIM = 128

class UserRole(str, enum.Enum):
    student = "student"
    instructor = "instructor"
    admin = "admin"

class SessionStatus(str, enum.Enum):
    active = "active"
    closed = "closed"
    expired = "expired"

class AttendanceStatus(str, enum.Enum):
    present = "present"
    absent = "absent"
    pending = "pending"

class DayOfWeek(str, enum.Enum):
    monday = "monday"
    tuesday = "tuesday"
    wednesday = "wednesday"
    thursday = "thursday"
    friday = "friday"

class PendingAttendanceStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    declined = "declined"

class VerificationMethod(str, enum.Enum):
    face = "face"
    manual = "manual"
    pending_approved = "pending_approved"

class PendingReason(str, enum.Enum):
    qr_failed = "qr_failed"
    camera_error = "camera_error"
    other = "other"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    student_profile = relationship("Student", back_populates="user", uselist=False)
    instructor_profile = relationship("Instructor", back_populates="user", uselist=False)
    system_config = relationship("SystemConfig", back_populates="user", uselist=False)
    password_reset_tokens = relationship("PasswordResetToken", back_populates="user")
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

class Student(Base):
    __tablename__ = "students"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    student_number = Column(String(20), unique=True, nullable=False, index=True)
    department = Column(String(100))
    face_enrolled = Column(Boolean, default=False)
    enrollment_consent = Column(Boolean, default=False)
    user = relationship("User", back_populates="student_profile")
    enrollments = relationship("Enrollment", back_populates="student")
    attendance_records = relationship("AttendanceRecord", back_populates="student")
    face_embeddings = relationship("FaceEmbedding", back_populates="student")
    pending_attendances = relationship("PendingAttendance", back_populates="student")

class Instructor(Base):
    __tablename__ = "instructors"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    department = Column(String(100))
    title = Column(String(50))
    user = relationship("User", back_populates="instructor_profile")
    courses = relationship("Course", back_populates="instructor")

class Course(Base):
    __tablename__ = "courses"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    instructor_id = Column(Integer, ForeignKey("instructors.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    instructor = relationship("Instructor", back_populates="courses")
    enrollments = relationship("Enrollment", back_populates="course")
    sessions = relationship("AttendanceSession", back_populates="course")
    schedules = relationship("CourseSchedule", back_populates="course", cascade="all, delete-orphan")

class CourseSchedule(Base):
    __tablename__ = "course_schedules"
    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    day_of_week = Column(SAEnum(DayOfWeek), nullable=False)
    start_time = Column(String(5), nullable=False)
    end_time = Column(String(5), nullable=False)
    room = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    course = relationship("Course", back_populates="schedules")

class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("student_id", "course_id"),)
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    enrolled_at = Column(DateTime(timezone=True), server_default=func.now())
    student = relationship("Student", back_populates="enrollments")
    course = relationship("Course", back_populates="enrollments")

class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"
    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200))
    status = Column(SAEnum(SessionStatus), default=SessionStatus.active)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True))
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    course = relationship("Course", back_populates="sessions")
    attendance_records = relationship("AttendanceRecord", back_populates="session")
    pending_attendances = relationship("PendingAttendance", back_populates="session")

class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("session_id", "student_id"),)
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("attendance_sessions.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    status = Column(SAEnum(AttendanceStatus), default=AttendanceStatus.present)
    # L2 distance between the submitted face and the closest enrolled embedding (lower is better).
    face_distance = Column(Float)
    verification_method = Column(
        SAEnum(VerificationMethod, name="verificationmethod"),
        nullable=False,
        default=VerificationMethod.face,
    )
    qr_validated = Column(Boolean, default=False)
    face_validated = Column(Boolean, default=False)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    ip_address = Column(String(50))
    session = relationship("AttendanceSession", back_populates="attendance_records")
    student = relationship("Student", back_populates="attendance_records")

class PendingAttendance(Base):
    __tablename__ = "pending_attendances"
    __table_args__ = (UniqueConstraint("session_id", "student_id"),)
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("attendance_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    reason = Column(SAEnum(PendingReason), nullable=False, default=PendingReason.qr_failed)
    note = Column(Text, nullable=True)
    status = Column(SAEnum(PendingAttendanceStatus), nullable=False, default=PendingAttendanceStatus.pending)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    session = relationship("AttendanceSession", back_populates="pending_attendances")
    student = relationship("Student", back_populates="pending_attendances")

class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"
    __table_args__ = (
        # 1:1 verification filters by student_id, which is already selective.
        # HNSW (L2) serves 1:N search; ivfflat lost recall on small tables.
        Index(
            "face_embeddings_embedding_hnsw_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_l2_ops"},
        ),
    )
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, default=1)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)
    student = relationship("Student", back_populates="face_embeddings")

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    code = Column(String(6), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User", back_populates="password_reset_tokens")

class SystemConfig(Base):
    __tablename__ = "system_configs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    absence_threshold = Column(Integer, default=20)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    user = relationship("User", back_populates="system_config")
