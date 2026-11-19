"""pgvector matching (R1.1) and the mock face mode (S4)."""
from __future__ import annotations

import pathlib

from sqlalchemy import text

from app.models.models import FaceEmbedding
from app.services.face_client import MockFaceClient
from app.services.face_matching import best_distance
from tests.conftest import auth, enroll_face, frame, login, make_student

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"


def _embedding(face_id: str):
    return MockFaceClient().analyze(frame(face_id=face_id)).embedding


def test_embedding_column_is_pgvector(db):
    column_type = db.execute(text(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = 'face_embeddings'::regclass AND attname = 'embedding'"
    )).scalar()
    assert column_type == "vector(128)"


def test_same_face_matches_in_sql(db):
    _, student = make_student(db)
    enroll_face(db, student, "alice")
    distance = best_distance(db, student.id, _embedding("alice"))
    assert distance is not None and distance < 1e-6


def test_different_face_does_not_match_in_sql(db):
    _, student = make_student(db)
    enroll_face(db, student, "alice")
    distance = best_distance(db, student.id, _embedding("bob"))
    assert distance is not None and distance > 0.45


def test_min_over_several_embeddings(db):
    _, student = make_student(db)
    enroll_face(db, student, "bob")
    enroll_face(db, student, "alice")
    assert best_distance(db, student.id, _embedding("alice")) < 1e-6


def test_inactive_embeddings_ignored(db):
    _, student = make_student(db)
    enroll_face(db, student, "alice")
    db.query(FaceEmbedding).update({"is_active": False})
    db.commit()
    assert best_distance(db, student.id, _embedding("alice")) is None


def test_other_students_embeddings_ignored(db):
    _, alice = make_student(db, email="a@test.com", student_number="1")
    _, bob = make_student(db, email="b@test.com", student_number="2")
    enroll_face(db, bob, "alice")  # bob enrolled a photo of alice
    assert best_distance(db, alice.id, _embedding("alice")) is None


def test_no_json_embeddings_left_in_code():
    offenders = [p for p in APP_DIR.rglob("*.py") if "json.loads(emb" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_s4_mock_mode_does_not_match_every_face():
    mock = MockFaceClient()
    a = mock.analyze(b"\xff\xd8 photo one").embedding
    b = mock.analyze(b"\xff\xd8 photo two").embedding
    distance = sum((x - y) ** 2 for x, y in zip(a, b, strict=False)) ** 0.5
    assert distance > 0.45
    assert mock.analyze(b"\xff\xd8 photo one").embedding == a  # deterministic


def test_s4_face_mode_defaults_to_real(monkeypatch):
    from app.core.config import Settings

    monkeypatch.delenv("FACE_MODE", raising=False)
    assert Settings(_env_file=None, ENV="development", SECRET_KEY="x" * 40).FACE_MODE == "real"


def test_enroll_stores_vectors_not_photos(client, db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, student = make_student(db)
    token = login(client, "student@test.com")
    resp = client.post(
        "/api/v1/face/enroll",
        data={"consent": "true"},
        files=[("photos", ("1.jpg", frame(face_id="alice"), "image/jpeg")),
               ("photos", ("2.jpg", frame(face_id="alice", ear=0.31), "image/jpeg"))],
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["photos_processed"] == 2
    assert db.query(FaceEmbedding).filter(FaceEmbedding.student_id == student.id).count() == 2
    assert list(tmp_path.iterdir()) == []


def test_enroll_requires_consent(client, db):
    make_student(db)
    resp = client.post(
        "/api/v1/face/enroll",
        data={"consent": "false"},
        files=[("photos", ("1.jpg", frame(), "image/jpeg"))],
        headers=auth(login(client, "student@test.com")),
    )
    assert resp.status_code == 400
