from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis import eye_aspect_ratio, filter_faces, laplacian_variance  # noqa: E402


def _eye(height: float):
    # p1..p6 around an eye 30px wide; p2/p3 above, p5/p6 below the centre line.
    return [(0, 0), (10, -height), (20, -height), (30, 0), (20, height), (10, height)]


def test_ear_open_eye():
    assert abs(eye_aspect_ratio(_eye(4.5)) - 0.30) < 1e-6


def test_ear_closed_eye_is_lower():
    assert eye_aspect_ratio(_eye(1.0)) < 0.21 < 0.25 < eye_aspect_ratio(_eye(4.5))


def test_ear_degenerate_inputs():
    assert eye_aspect_ratio([(0, 0)] * 6) == 0.0
    assert eye_aspect_ratio([(0, 0), (1, 1)]) == 0.0


def test_blur_flat_image_is_zero():
    assert laplacian_variance(np.full((40, 40), 128.0)) == 0.0


def test_blur_sharp_beats_smooth():
    rng = np.random.default_rng(0)
    sharp = rng.integers(0, 255, (64, 64)).astype(np.float32)
    smooth = np.tile(np.linspace(0, 255, 64, dtype=np.float32), (64, 1))
    assert laplacian_variance(sharp) > 1000 > laplacian_variance(smooth)


def test_filter_faces_drops_small_background_faces():
    big = (0, 300, 300, 0)          # 300x300
    small = (0, 60, 60, 0)          # 60x60, < 40% of big
    tiny_alone = [(0, 10, 10, 0)]   # < 3% of a 1000x1000 frame
    assert filter_faces([big, small], (1000, 1000, 3)) == [big]
    assert filter_faces(tiny_alone, (1000, 1000, 3)) == []
    assert filter_faces([], (10, 10, 3)) == []
