from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_student_profile
from app.db.session import get_db
from app.models.models import FaceEmbedding, Student
from app.schemas.schemas import ErrorResponse, FaceEnrollmentResult, MessageResponse
from app.services.attendance import FACE_SERVICE_DOWN
from app.services.face_client import FaceClient, FaceServiceUnavailable, get_face_client

router = APIRouter()


@router.post(
    "/enroll",
    response_model=FaceEnrollmentResult,
    summary="Enroll face photos",
    description=(
        "Extracts one 128-d embedding per photo and stores it in a pgvector column. "
        "Photos themselves are not kept. Re-enrolling replaces the previous embeddings."
    ),
    responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def enroll_face(
    consent: bool = Form(...),
    photos: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    student: Student = Depends(get_current_student_profile),
    face: FaceClient = Depends(get_face_client),
) -> FaceEnrollmentResult:
    if not consent:
        raise HTTPException(status_code=400, detail="Biometric consent is required for face enrollment")
    if len(photos) < settings.MIN_FACE_PHOTOS:
        raise HTTPException(status_code=400, detail=f"Please provide at least {settings.MIN_FACE_PHOTOS} photos")
    if len(photos) > settings.MAX_FACE_PHOTOS:
        raise HTTPException(status_code=400, detail=f"Maximum {settings.MAX_FACE_PHOTOS} photos allowed")

    embeddings: List[List[float]] = []
    for photo in photos:
        image_bytes = photo.file.read()
        if len(image_bytes) > settings.MAX_IMAGE_BYTES:
            continue
        try:
            analysis = face.analyze(image_bytes, with_embedding=True)
        except FaceServiceUnavailable as exc:
            raise HTTPException(status_code=503, detail=FACE_SERVICE_DOWN) from exc
        if analysis.face_count == 1 and analysis.embedding:
            embeddings.append(analysis.embedding)

    if len(embeddings) < settings.MIN_FACE_PHOTOS:
        raise HTTPException(
            status_code=422,
            detail=f"Only {len(embeddings)} valid face photos detected. Need at least {settings.MIN_FACE_PHOTOS}.",
        )

    db.query(FaceEmbedding).filter(FaceEmbedding.student_id == student.id).delete()
    db.add_all(FaceEmbedding(student_id=student.id, embedding=e, version=1, is_active=True) for e in embeddings)
    student.face_enrolled = True
    student.enrollment_consent = True
    db.commit()
    return FaceEnrollmentResult(
        success=True,
        photos_processed=len(embeddings),
        message=f"Successfully enrolled {len(embeddings)} face photos.",
    )


@router.delete("/enroll", response_model=MessageResponse, summary="Delete my face data (withdraw consent)")
def delete_face_enrollment(
    db: Session = Depends(get_db),
    student: Student = Depends(get_current_student_profile),
) -> MessageResponse:
    db.query(FaceEmbedding).filter(FaceEmbedding.student_id == student.id).delete()
    student.face_enrolled = False
    student.enrollment_consent = False
    db.commit()
    return MessageResponse(message="Face enrollment data deleted successfully")


@router.get("/enroll/status", summary="My face enrollment status")
def get_enrollment_status(
    db: Session = Depends(get_db),
    student: Student = Depends(get_current_student_profile),
) -> Dict[str, Any]:
    count = db.query(FaceEmbedding).filter(
        FaceEmbedding.student_id == student.id, FaceEmbedding.is_active.is_(True)
    ).count()
    return {
        "face_enrolled": student.face_enrolled,
        "embedding_count": count,
        "consent_given": student.enrollment_consent,
    }
