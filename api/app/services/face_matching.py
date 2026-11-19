"""Face matching in PostgreSQL with pgvector.

1:1 verification and 1:N identification are both plain SQL over face_embeddings using
the L2 distance operator (<->), which is the metric face_recognition embeddings are
calibrated for (0.45 is a common "same person" cut-off).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import Enrollment, FaceEmbedding, Student


@dataclass(frozen=True)
class Candidate:
    student: Student
    distance: float

    @property
    def is_match(self) -> bool:
        return self.distance <= settings.FACE_MATCH_MAX_DISTANCE


def best_distance(db: Session, student_id: int, embedding: Sequence[float]) -> Optional[float]:
    """SELECT min(embedding <-> :q) FROM face_embeddings WHERE student_id = :sid AND is_active"""
    stmt = select(func.min(FaceEmbedding.embedding.l2_distance(list(embedding)))).where(
        FaceEmbedding.student_id == student_id,
        FaceEmbedding.is_active.is_(True),
    )
    value = db.execute(stmt).scalar()
    return float(value) if value is not None else None


def identify_in_course(
    db: Session, course_id: int, embedding: Sequence[float], limit: int = 3
) -> List[Candidate]:
    """Closest enrolled students of a course, one row per student.

    Each student can have several embeddings, so take the per-student minimum and order
    by it. The candidate set is already narrowed to one course, so this is an exact scan;
    the HNSW index on face_embeddings serves unfiltered, campus-wide lookups.
    """
    distance = FaceEmbedding.embedding.l2_distance(list(embedding))
    per_student = (
        select(FaceEmbedding.student_id, func.min(distance).label("distance"))
        .join(Enrollment, Enrollment.student_id == FaceEmbedding.student_id)
        .where(Enrollment.course_id == course_id, FaceEmbedding.is_active.is_(True))
        .group_by(FaceEmbedding.student_id)
        .order_by("distance")
        .limit(limit)
        .subquery()
    )
    rows = db.execute(
        select(Student, per_student.c.distance)
        .join(per_student, per_student.c.student_id == Student.id)
        .order_by(per_student.c.distance)
    ).all()
    return [Candidate(student=s, distance=float(d)) for s, d in rows]
