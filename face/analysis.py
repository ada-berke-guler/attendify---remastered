"""Pure image measurements. Only numpy, so they are unit-testable without dlib."""
from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np

Point = Tuple[float, float]

MIN_FACE_AREA_RATIO = 0.03   # ignore faces smaller than 3% of the frame (posters, people far behind)
RELATIVE_SIZE_FILTER = 0.4   # with several faces, drop those < 40% of the largest


def _distance(p1: Point, p2: Point) -> float:
    return float(np.hypot(p1[0] - p2[0], p1[1] - p2[1]))


def eye_aspect_ratio(eye: Sequence[Point]) -> float:
    """Soukupová & Čech (2016): (|p2-p6| + |p3-p5|) / (2 |p1-p4|).

    ~0.3 for an open eye, drops towards 0 when the eye closes.
    """
    if len(eye) < 6:
        return 0.0
    horizontal = _distance(eye[0], eye[3])
    if horizontal == 0:
        return 0.0
    vertical = _distance(eye[1], eye[5]) + _distance(eye[2], eye[4])
    return vertical / (2.0 * horizontal)


def laplacian_variance(gray: np.ndarray) -> float:
    """Variance of the 4-neighbour Laplacian. Low for blurry frames and flat printed photos."""
    img = gray.astype(np.float32)
    padded = np.pad(img, 1, mode="edge")
    lap = (
        padded[:-2, 1:-1] + padded[2:, 1:-1] + padded[1:-1, :-2] + padded[1:-1, 2:]
        - 4.0 * padded[1:-1, 1:-1]
    )
    return float(lap.var())


def to_gray(rgb: np.ndarray) -> np.ndarray:
    return rgb.mean(axis=2) if rgb.ndim == 3 else rgb


def filter_faces(
    locations: Sequence[Tuple[int, int, int, int]], image_shape: Tuple[int, ...]
) -> list[Tuple[int, int, int, int]]:
    """Drop background faces. Locations are face_recognition's (top, right, bottom, left)."""
    if not locations:
        return []
    areas = [(b - t) * (r - lft) for (t, r, b, lft) in locations]
    largest = max(areas)
    image_area = image_shape[0] * image_shape[1]
    return [
        loc for loc, area in zip(locations, areas, strict=True)
        if area >= largest * RELATIVE_SIZE_FILTER and area >= image_area * MIN_FACE_AREA_RATIO
    ]
