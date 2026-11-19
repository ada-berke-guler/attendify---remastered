"""Test setup: real PostgreSQL + pgvector, fakeredis (or a real Redis), mock face client.

TEST_DATABASE_URL   default postgresql://attendify:attendify@localhost:5432/attendify_test
                    Append ?options=-csearch_path%3Dmyschema,public to run in a separate
                    schema of an existing database.
TEST_REDIS_URL      optional; when set, tests use that Redis (flushed per test) instead of fakeredis.
"""
from __future__ import annotations

import os
from urllib.parse import parse_qs, unquote, urlparse

# Must be set before any app import so Settings picks them up.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://attendify:attendify@localhost:5432/attendify_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENV"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-at-least-32-chars"
os.environ["FACE_MODE"] = "mock"
os.environ["QR_ROTATOR_ENABLED"] = "false"
os.environ["DEV_CORS_ORIGINS"] = ""
os.environ["PUBLIC_URL"] = ""

from typing import Iterator  # noqa: E402

import fakeredis  # noqa: E402
import pytest  # noqa: E402
import redis  # noqa: E402
import redis.asyncio as aioredis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core import redis as redis_module  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.db.session import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import (  # noqa: E402
    AttendanceSession, Course, Enrollment, FaceEmbedding, Instructor, SessionStatus, Student, User, UserRole,
)
from app.services import face_client as face_client_module  # noqa: E402
from app.services import qr  # noqa: E402
from app.services.face_client import MockFaceClient  # noqa: E402

engine = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False)


def _search_path_schema() -> str | None:
    options = parse_qs(urlparse(TEST_DATABASE_URL).query).get("options", [""])[0]
    options = unquote(options)
    if "search_path=" not in options:
        return None
    return options.split("search_path=", 1)[1].split(",")[0].strip()


@pytest.fixture(scope="session", autouse=True)
def create_tables() -> Iterator[None]:
    with engine.begin() as conn:
        schema = _search_path_schema()
        if schema:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db() -> Iterator[Session]:
    """Each test runs inside a transaction that is rolled back afterwards.

    join_transaction_mode="create_savepoint" turns the app's db.commit() calls into
    savepoint releases, so endpoints behave normally and nothing leaks between tests.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def redis_clients() -> Iterator[tuple[redis.Redis, aioredis.Redis]]:
    url = os.environ.get("TEST_REDIS_URL")
    if url:
        sync_client = redis.Redis.from_url(url, decode_responses=True)
        async_client = aioredis.Redis.from_url(url, decode_responses=True)
        sync_client.flushdb()
    else:
        server = fakeredis.FakeServer()
        sync_client = fakeredis.FakeRedis(server=server, decode_responses=True)
        async_client = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    redis_module.set_redis_clients(sync_client, async_client)
    yield sync_client, async_client
    if url:
        sync_client.flushdb()


@pytest.fixture()
def r(redis_clients) -> redis.Redis:
    return redis_clients[0]


@pytest.fixture()
def face() -> MockFaceClient:
    return MockFaceClient()


@pytest.fixture()
def client(db, redis_clients, face) -> Iterator[TestClient]:
    sync_client, async_client = redis_clients

    def _db_override():
        yield db

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[redis_module.get_redis] = lambda: sync_client
    app.dependency_overrides[redis_module.get_async_redis] = lambda: async_client
    app.dependency_overrides[face_client_module.get_face_client] = lambda: face
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Factories ─────────────────────────────────────────────────────────────

def make_user(db, *, email: str, role: UserRole, password: str = "password123") -> User:
    user = User(
        email=email,
        hashed_password=get_password_hash(password),
        first_name="Test",
        last_name=role.value.title(),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def make_admin(db, email: str = "admin@test.com", password: str = "password123") -> User:
    user = make_user(db, email=email, role=UserRole.admin, password=password)
    db.commit()
    return user


def make_student(db, email: str = "student@test.com", student_number: str = "20210001", password: str = "password123"):
    user = make_user(db, email=email, role=UserRole.student, password=password)
    student = Student(user_id=user.id, student_number=student_number)
    db.add(student)
    db.commit()
    return user, student


def make_instructor(db, email: str = "instructor@test.com", password: str = "password123"):
    user = make_user(db, email=email, role=UserRole.instructor, password=password)
    instructor = Instructor(user_id=user.id, department="CS")
    db.add(instructor)
    db.commit()
    return user, instructor


def make_course(db, instructor: Instructor, code: str = "CS101", name: str = "Intro to CS") -> Course:
    course = Course(code=code, name=name, instructor_id=instructor.id)
    db.add(course)
    db.commit()
    return course


def enroll_face(db, student: Student, face_id: str) -> None:
    """Store the mock embedding for frames tagged id=<face_id>."""
    analysis = MockFaceClient().analyze(frame(face_id=face_id))
    db.add(FaceEmbedding(student_id=student.id, embedding=analysis.embedding, is_active=True))
    student.face_enrolled = True
    db.commit()


def frame(*, face_id: str = "alice", ear: float = 0.30, faces: int = 1, blur: float = 100.0) -> bytes:
    """A fake camera frame understood by MockFaceClient."""
    return f"MOCK:faces={faces};ear={ear};blur={blur};id={face_id}\n".encode() + b"\xff\xd8\xff" + b"\x00" * 64


def start_session(db, r, course: Course, instructor: Instructor) -> AttendanceSession:
    session = AttendanceSession(
        course_id=course.id, title="Test Session", status=SessionStatus.active, created_by_id=instructor.user_id
    )
    db.add(session)
    db.commit()
    qr.activate(r, session.id)
    return session


def qr_token_for(r, session: AttendanceSession) -> str:
    return qr.current_qr(r, session.id, "http://testserver").token


def setup_class(db, r, *, face_id: str = "alice"):
    """Instructor + course + active session + enrolled student with a face on file."""
    _, instructor = make_instructor(db)
    course = make_course(db, instructor, code="CS400")
    student_user, student = make_student(db)
    db.add(Enrollment(student_id=student.id, course_id=course.id))
    db.commit()
    enroll_face(db, student, face_id)
    session = start_session(db, r, course, instructor)
    return instructor, course, session, student_user, student


def login(client: TestClient, email: str, password: str = "password123") -> str:
    resp = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def blink(client: TestClient, token: str, face_id: str = "alice") -> str:
    """Run the blink challenge and return the liveness ticket."""
    url = "/api/v1/attendance/liveness-check"
    first = client.post(url, files={"image": ("f.jpg", frame(face_id=face_id, ear=0.15), "image/jpeg")}, headers=auth(token))
    assert first.status_code == 200, first.text
    assert first.json()["reason"] == "need_blink_open"
    second = client.post(url, files={"image": ("f.jpg", frame(face_id=face_id, ear=0.32), "image/jpeg")}, headers=auth(token))
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["is_live"] is True, body
    return body["liveness_ticket"]


def submit(client: TestClient, token: str, qr_token: str, ticket: str | None, face_id: str = "alice"):
    data = {"qr_token": qr_token}
    if ticket is not None:
        data["liveness_ticket"] = ticket
    return client.post(
        "/api/v1/attendance/submit",
        data=data,
        files={"image": ("face.jpg", frame(face_id=face_id), "image/jpeg")},
        headers=auth(token),
    )
