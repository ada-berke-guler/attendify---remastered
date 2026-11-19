"""v2: embeddings in pgvector, face_distance, verification_method, drop unused fields

Revision ID: 002_v2
Revises: a39f9ad280d9
Create Date: 2026-11-19

- face_embeddings: move the JSON embedding out of photo_path into embedding vector(128),
  make it NOT NULL, drop photo_path (photos are no longer kept), replace the ivfflat
  cosine index with HNSW on L2 distance.
- attendance_records: face_similarity_score (1 - distance) becomes face_distance; add
  verification_method (face | manual | pending_approved) and backfill it.
- attendance_sessions: drop qr_token / qr_expires_at (QR state lives in Redis now).
- system_configs: drop geo_fencing_radius, qr_refresh_interval, face_verification_required.
- drop notification_preferences.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002_v2"
down_revision = "a39f9ad280d9"
branch_labels = None
depends_on = None

verification_method = sa.Enum("face", "manual", "pending_approved", name="verificationmethod")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── face_embeddings ───────────────────────────────────────────────────
    # v1 wrote json.dumps(embedding) into photo_path. pgvector parses '[1.0, 2.0, ...]'
    # directly, so a cast is enough. Rows that never got a usable 128-d vector are dropped.
    op.execute(
        """
        UPDATE face_embeddings
        SET embedding = photo_path::vector
        WHERE embedding IS NULL
          AND photo_path LIKE '[%%'
          AND json_array_length(photo_path::json) = 128
        """
    )
    op.execute("DELETE FROM face_embeddings WHERE embedding IS NULL")
    op.execute(
        """
        UPDATE students SET face_enrolled = false
        WHERE face_enrolled AND NOT EXISTS (
            SELECT 1 FROM face_embeddings fe WHERE fe.student_id = students.id
        )
        """
    )
    op.alter_column("face_embeddings", "embedding", nullable=False)
    op.drop_column("face_embeddings", "photo_path")
    op.execute("DROP INDEX IF EXISTS face_embeddings_ivfflat_idx")
    op.execute(
        "CREATE INDEX face_embeddings_embedding_hnsw_idx ON face_embeddings "
        "USING hnsw (embedding vector_l2_ops)"
    )
    op.create_index("ix_face_embeddings_student_id", "face_embeddings", ["student_id"])

    # ── attendance_records ────────────────────────────────────────────────
    op.alter_column("attendance_records", "face_similarity_score", new_column_name="face_distance")
    op.execute("UPDATE attendance_records SET face_distance = 1 - face_distance WHERE face_distance IS NOT NULL")
    verification_method.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "attendance_records",
        sa.Column("verification_method", verification_method, nullable=False, server_default="face"),
    )
    op.execute(
        """
        UPDATE attendance_records SET verification_method = CASE
            WHEN NOT qr_validated AND NOT face_validated THEN 'pending_approved'::verificationmethod
            WHEN face_distance IS NULL THEN 'manual'::verificationmethod
            ELSE 'face'::verificationmethod
        END
        """
    )
    op.alter_column("attendance_records", "verification_method", server_default=None)

    # ── attendance_sessions ───────────────────────────────────────────────
    op.drop_column("attendance_sessions", "qr_token")
    op.drop_column("attendance_sessions", "qr_expires_at")

    # ── system_configs / notification_preferences ─────────────────────────
    op.drop_column("system_configs", "geo_fencing_radius")
    op.drop_column("system_configs", "qr_refresh_interval")
    op.drop_column("system_configs", "face_verification_required")
    op.drop_index("ix_notification_preferences_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")


def downgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("email_alerts", sa.Boolean(), nullable=True),
        sa.Column("attendance_confirmation", sa.Boolean(), nullable=True),
        sa.Column("low_attendance_warning", sa.Boolean(), nullable=True),
        sa.Column("session_start_reminder", sa.Boolean(), nullable=True),
        sa.Column("weekly_summary_report", sa.Boolean(), nullable=True),
        sa.Column("at_risk_student_alert", sa.Boolean(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_notification_preferences_id", "notification_preferences", ["id"])
    op.add_column("system_configs", sa.Column("face_verification_required", sa.Boolean(), nullable=True))
    op.add_column("system_configs", sa.Column("qr_refresh_interval", sa.Integer(), nullable=True))
    op.add_column("system_configs", sa.Column("geo_fencing_radius", sa.Integer(), nullable=True))

    op.add_column("attendance_sessions", sa.Column("qr_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("attendance_sessions", sa.Column("qr_token", sa.Text(), nullable=True))

    op.drop_column("attendance_records", "verification_method")
    verification_method.drop(op.get_bind(), checkfirst=True)
    op.execute("UPDATE attendance_records SET face_distance = 1 - face_distance WHERE face_distance IS NOT NULL")
    op.alter_column("attendance_records", "face_distance", new_column_name="face_similarity_score")

    # The embedding column already existed in v1 (unused), so the vectors stay there.
    op.drop_index("ix_face_embeddings_student_id", table_name="face_embeddings")
    op.execute("DROP INDEX IF EXISTS face_embeddings_embedding_hnsw_idx")
    op.add_column("face_embeddings", sa.Column("photo_path", sa.String(500), nullable=True))
    op.alter_column("face_embeddings", "embedding", nullable=True)
    op.execute(
        "CREATE INDEX face_embeddings_ivfflat_idx ON face_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
