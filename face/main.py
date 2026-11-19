"""Attendify face service.

Internal only (no published port). Stateless: one endpoint that says what is in a frame.
Blink state, matching and thresholds all live in the api service.

  POST /analyze?embedding=true   multipart field "image"
  -> {face_count, ear, blur_score, embedding}
"""
from __future__ import annotations

import io
import logging
from typing import List, Optional

import face_recognition
import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel

from analysis import eye_aspect_ratio, filter_faces, laplacian_variance, to_gray

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("attendify.face")

MAX_SIDE = 960  # downscale big phone photos: HOG detection time grows with pixel count

app = FastAPI(title="Attendify face service", version="2.0.0", docs_url="/docs")


class Analysis(BaseModel):
    face_count: int
    ear: Optional[float] = None
    blur_score: Optional[float] = None
    embedding: Optional[List[float]] = None


def decode(data: bytes) -> np.ndarray:
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Could not decode image") from exc
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    return np.asarray(image)


def detect(rgb: np.ndarray) -> tuple[np.ndarray, list]:
    locations = face_recognition.face_locations(rgb, number_of_times_to_upsample=1)
    if not locations:
        # Faces that touch the frame edge are often missed; retry on a padded canvas.
        pad = max(rgb.shape[:2]) // 4
        padded = np.pad(rgb, ((pad, pad), (pad, pad), (0, 0)), mode="constant", constant_values=255)
        locations = face_recognition.face_locations(padded, number_of_times_to_upsample=1)
        if locations:
            rgb = padded
    return rgb, filter_faces(locations, rgb.shape)


@app.post("/analyze", response_model=Analysis, summary="Face count, eye aspect ratio, blur and embedding")
def analyze(
    image: UploadFile = File(...),
    embedding: bool = Query(True, description="Also compute the 128-d embedding (slower)"),
) -> Analysis:
    rgb, faces = detect(decode(image.file.read()))
    if len(faces) != 1:
        return Analysis(face_count=len(faces))

    top, right, bottom, left = faces[0]
    blur = laplacian_variance(to_gray(rgb[top:bottom, left:right]))

    ear = None
    landmarks = face_recognition.face_landmarks(rgb, faces)
    if landmarks and "left_eye" in landmarks[0] and "right_eye" in landmarks[0]:
        ear = (eye_aspect_ratio(landmarks[0]["left_eye"]) + eye_aspect_ratio(landmarks[0]["right_eye"])) / 2

    vector = None
    if embedding:
        encodings = face_recognition.face_encodings(rgb, faces)
        vector = encodings[0].tolist() if encodings else None

    logger.info("faces=1 ear=%s blur=%.1f embedding=%s", f"{ear:.3f}" if ear else None, blur, vector is not None)
    return Analysis(face_count=1, ear=ear, blur_score=blur, embedding=vector)


@app.get("/health", summary="Liveness probe")
def health() -> dict:
    return {"status": "ok"}
