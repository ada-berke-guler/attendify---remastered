from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.deps import get_current_admin, get_current_user
from app.core.rate_limit import login_rate_limit, password_reset_rate_limit
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.session import get_db
from app.models.models import Instructor, PasswordResetToken, Student, User, UserRole
from app.schemas.schemas import (
    ChangePasswordPayload, ErrorResponse, ForgotPasswordPayload, InstructorCreate, MessageResponse,
    ResetPasswordPayload, StudentCreate, Token, UpdateProfilePayload, UserOut,
)
from app.services.mailer import send_reset_code

router = APIRouter()

RESET_CODE_TTL = timedelta(minutes=15)


def user_out(user: User, db: Session) -> UserOut:
    """UserOut plus the role-specific profile fields."""
    out = UserOut.model_validate(user)
    if user.role == UserRole.student:
        s = db.query(Student).filter(Student.user_id == user.id).first()
        if s:
            out.student_number = s.student_number
            out.department = s.department
            out.face_enrolled = s.face_enrolled
        else:
            out.face_enrolled = False
    else:
        i = db.query(Instructor).filter(Instructor.user_id == user.id).first()
        if i:
            out.department = i.department
            out.title = i.title
            out.instructor_id = i.id
    return out


@router.post(
    "/login",
    response_model=Token,
    summary="Log in with email (or student number) and password",
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    dependencies=[Depends(login_rate_limit)],
)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> Token:
    identifier = form_data.username.strip()
    if "@" in identifier:
        user = db.query(User).filter(User.email == identifier).first()
    else:  # students may sign in with their student number
        user = db.query(User).join(Student, Student.user_id == User.id).filter(
            Student.student_number == identifier
        ).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Account is inactive")
    profile = user_out(user, db)
    return Token(
        access_token=create_access_token({"sub": str(user.id), "role": user.role.value}),
        role=user.role,
        user_id=user.id,
        full_name=user.full_name,
        student_number=profile.student_number,
        face_enrolled=profile.face_enrolled,
        department=profile.department,
    )


def _next_student_number(db: Session) -> str:
    prefix = f"STU-{datetime.now(UTC).year}-"
    nums = []
    for (sn,) in db.query(Student.student_number).filter(Student.student_number.like(f"{prefix}%")):
        try:
            nums.append(int(sn.removeprefix(prefix)))
        except ValueError:
            pass
    return f"{prefix}{(max(nums) + 1) if nums else 1:03d}"


@router.post(
    "/register/student",
    response_model=UserOut,
    status_code=201,
    summary="Create a student account (admin only)",
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def register_student(
    payload: StudentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> UserOut:
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if payload.student_number:
        if db.query(Student).filter(Student.student_number == payload.student_number).first():
            raise HTTPException(status_code=400, detail="Student number already registered")
        student_number = payload.student_number
    else:
        student_number = _next_student_number(db)

    user = User(
        email=payload.email, hashed_password=get_password_hash(payload.password),
        first_name=payload.first_name, last_name=payload.last_name, role=UserRole.student,
    )
    db.add(user)
    db.flush()
    db.add(Student(user_id=user.id, student_number=student_number, department=payload.department))
    db.commit()
    db.refresh(user)
    return user_out(user, db)


@router.post(
    "/register/instructor",
    response_model=UserOut,
    status_code=201,
    summary="Create an instructor account (admin only)",
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def register_instructor(
    payload: InstructorCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> UserOut:
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=payload.email, hashed_password=get_password_hash(payload.password),
        first_name=payload.first_name, last_name=payload.last_name, role=UserRole.instructor,
    )
    db.add(user)
    db.flush()
    db.add(Instructor(user_id=user.id, department=payload.department, title=payload.title))
    db.commit()
    db.refresh(user)
    return user_out(user, db)


@router.get("/me", response_model=UserOut, summary="Current user")
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserOut:
    return user_out(current_user, db)


@router.patch("/me", response_model=UserOut, summary="Update my profile")
def update_profile(
    payload: UpdateProfilePayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    if payload.first_name:
        current_user.first_name = payload.first_name
    if payload.last_name:
        current_user.last_name = payload.last_name
    if current_user.role == UserRole.student and payload.department:
        s = db.query(Student).filter(Student.user_id == current_user.id).first()
        if s:
            s.department = payload.department
    elif current_user.role in (UserRole.instructor, UserRole.admin):
        i = db.query(Instructor).filter(Instructor.user_id == current_user.id).first()
        if i:
            if payload.department:
                i.department = payload.department
            if payload.title:
                i.title = payload.title
    db.commit()
    db.refresh(current_user)
    return user_out(current_user, db)


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change my password",
    responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def change_password(
    payload: ChangePasswordPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=422, detail="Passwords do not match")
    current_user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return MessageResponse(message="Password updated successfully")


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Send a 6-digit reset code",
    description="Without SMTP settings the code is written to the api log at WARNING level.",
    dependencies=[Depends(password_reset_rate_limit)],
)
def forgot_password(
    payload: ForgotPasswordPayload,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> MessageResponse:
    user = db.query(User).filter(User.email == payload.email).first()
    if user:
        db.query(PasswordResetToken).filter(PasswordResetToken.email == payload.email).delete()
        code = f"{secrets.randbelow(1_000_000):06d}"
        db.add(PasswordResetToken(
            user_id=user.id, email=payload.email, code=code,
            expires_at=datetime.now(UTC) + RESET_CODE_TTL,
        ))
        db.commit()
        background.add_task(send_reset_code, payload.email, code)
    # Same answer either way, so the endpoint cannot be used to discover accounts.
    return MessageResponse(message="If this email exists, a reset code was sent.")


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password with the emailed code",
    responses={400: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    dependencies=[Depends(password_reset_rate_limit)],
)
def reset_password(payload: ResetPasswordPayload, db: Session = Depends(get_db)) -> MessageResponse:
    token = db.query(PasswordResetToken).filter(
        PasswordResetToken.email == payload.email,
        PasswordResetToken.code == payload.code,
        PasswordResetToken.used_at.is_(None),
    ).first()
    now = datetime.now(UTC)
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    expires_at = token.expires_at if token.expires_at.tzinfo else token.expires_at.replace(tzinfo=UTC)
    if now > expires_at:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    user = db.get(User, token.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    user.hashed_password = get_password_hash(payload.new_password)
    token.used_at = now
    db.commit()
    return MessageResponse(message="Password reset successfully")
