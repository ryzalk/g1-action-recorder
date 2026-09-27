"""The building's main direction θ₀ (how its walls run), for angle snapping and aligned rectangles."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import numpy as np
from loguru import logger

from component.map_storage.service import MapDocument, MapStorage
from config.settings import MapGridConfig, MapInspectionConfig, use_utf8_output
from util.raster_helper import RasterHelper


class MainDirection:
    def __init__(self, **kwargs) -> None:
        self.raster = RasterHelper()
        self.min_length_px = kwargs.get("direction_min_length_px", MapInspectionConfig.DIRECTION_MIN_LENGTH_PX)
        self.bin_deg = kwargs.get("direction_bin_deg", MapInspectionConfig.DIRECTION_BIN_DEG)

    def detect(self, document: MapDocument) -> float:
        """θ₀ in degrees, [0, 90), counter-clockwise from world +x.

        Walls meet at right angles, so every segment's angle is folded into one
        quarter turn; the length-weighted histogram peak is the building's grain.
        """
        occupied = document.grid.image == MapGridConfig.OCCUPIED
        segments = self.raster.line_segments(occupied, min_length=self.min_length_px)
        dx = (segments[:, 2] - segments[:, 0]).astype(np.float64)
        # Image rows grow downward, world y grows upward.
        dy = -(segments[:, 3] - segments[:, 1]).astype(np.float64)
        lengths = np.hypot(dx, dy)
        folded = np.degrees(np.arctan2(dy, dx)) % 90.0
        bins = int(round(90.0 / self.bin_deg))
        histogram, edges = np.histogram(folded, bins=bins, range=(0.0, 90.0), weights=lengths)
        peak = int(np.argmax(histogram))
        # Refine with the weighted mean of the peak and its neighbours, wrapping around 0°/90°.
        offsets = (folded - (edges[peak] + self.bin_deg / 2) + 45.0) % 90.0 - 45.0
        near = np.abs(offsets) <= 1.5 * self.bin_deg
        theta = float((edges[peak] + self.bin_deg / 2 + np.average(offsets[near], weights=lengths[near])) % 90.0)
        return theta


def demo_direction() -> None:
    """RTLAB's main walls run at about 30° / -60° (design doc 2.4)."""
    document = MapStorage().load()
    detector = MainDirection()
    theta = detector.detect(document)
    segments = detector.raster.line_segments(document.grid.image == MapGridConfig.OCCUPIED, min_length=20)
    logger.info("Main direction θ₀ = {:.1f}° (other walls {:.1f}°), from {} segments", theta, theta - 90, len(segments))
    assert 20 < theta < 40


def main() -> None:
    use_utf8_output()
    demo_direction()


if __name__ == "__main__":
    main()
