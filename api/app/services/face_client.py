"""Client for the internal face service.

The face service is stateless: it only answers "what is in this frame" (face count, eye
aspect ratio, blur score and optionally the 128-d embedding). Matching happens in
PostgreSQL (pgvector) and the blink state machine lives in services/liveness.py.

Any transport error or 5xx raises FaceServiceUnavailable. Callers turn that into 503:
we never treat an unreachable face service as a pass (fail closed).
"""
from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from typing import List, Optional, Protocol

import httpx

from app.core.config import settings
from app.models.models import EMBEDDING_DIM

logger = logging.getLogger("attendify.face")


class FaceServiceUnavailable(Exception):
    """The face service could not be reached or returned a server error."""


@dataclass(frozen=True)
class FaceAnalysis:
    face_count: int
    ear: Optional[float] = None
    blur_score: Optional[float] = None
    embedding: Optional[List[float]] = None


class FaceClient(Protocol):
    def analyze(self, image_bytes: bytes, with_embedding: bool = True) -> FaceAnalysis: ...


class HttpFaceClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def analyze(self, image_bytes: bytes, with_embedding: bool = True) -> FaceAnalysis:
        try:
            resp = httpx.post(
                f"{self.base_url}/analyze",
                params={"embedding": str(with_embedding).lower()},
                files={"image": ("frame.jpg", image_bytes, "image/jpeg")},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            logger.error("face service unreachable: %s", exc)
            raise FaceServiceUnavailable(str(exc)) from exc
        if resp.status_code >= 500:
            logger.error("face service error %s: %s", resp.status_code, resp.text[:200])
            raise FaceServiceUnavailable(f"face service returned {resp.status_code}")
        if resp.status_code >= 400:
            # Undecodable image and similar client errors: treat as "no face".
            return FaceAnalysis(face_count=0)
        data = resp.json()
        return FaceAnalysis(
            face_count=int(data.get("face_count", 0)),
            ear=data.get("ear"),
            blur_score=data.get("blur_score"),
            embedding=data.get("embedding"),
        )


def _unit_vector_from_seed(seed: bytes) -> List[float]:
    values: List[float] = []
    counter = 0
    while len(values) < EMBEDDING_DIM:
        block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        values.extend((b - 127.5) / 127.5 for b in block)
        counter += 1
    values = values[:EMBEDDING_DIM]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


class MockFaceClient:
    """Deterministic stand-in for tests and machines without dlib.

    The embedding is derived from a hash of the image bytes, so the same image always
    matches itself and two different images are ~1.4 apart (random unit vectors in 128-d),
    far above the 0.45 threshold. There is no "every face matches" mode.

    Test frames can steer the result with a text header, e.g.
    b"MOCK:faces=1;ear=0.15;blur=50;id=alice". `id` seeds the embedding, so two
    different frames of "alice" match each other.
    """

    def analyze(self, image_bytes: bytes, with_embedding: bool = True) -> FaceAnalysis:
        params = self._parse_header(image_bytes)
        digest = hashlib.sha256(image_bytes).digest()
        face_count = int(params.get("faces", 1))
        # Without an explicit value the EAR swings between "closed" and "open" from frame
        # to frame, so a real camera can still complete the blink challenge in mock mode.
        ear = float(params["ear"]) if "ear" in params else 0.15 + (digest[0] / 255) * 0.2
        blur = float(params.get("blur", 100.0))
        embedding = None
        if with_embedding and face_count == 1:
            seed = params["id"].encode() if "id" in params else digest
            embedding = _unit_vector_from_seed(seed)
        return FaceAnalysis(face_count=face_count, ear=ear, blur_score=blur, embedding=embedding)

    @staticmethod
    def _parse_header(image_bytes: bytes) -> dict:
        if not image_bytes.startswith(b"MOCK:"):
            return {}
        header = image_bytes[5:].split(b"\n", 1)[0].decode("utf-8", "ignore")
        pairs = (item.split("=", 1) for item in header.split(";") if "=" in item)
        return {k.strip(): v.strip() for k, v in pairs}


_client: Optional[FaceClient] = None


def build_face_client() -> FaceClient:
    if settings.FACE_MODE == "mock":
        return MockFaceClient()
    return HttpFaceClient(settings.FACE_SERVICE_URL, settings.FACE_SERVICE_TIMEOUT_SECONDS)


def get_face_client() -> FaceClient:
    """FastAPI dependency."""
    global _client
    if _client is None:
        _client = build_face_client()
    return _client
