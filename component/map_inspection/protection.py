"""Protected zone: cells of static structure (walls, pillars); erasing ghosts keeps their points by default.

Static structure reaches the ceiling, people and carts do not: on RTLAB 95% of
the cells with points above 2.1 m sit on a grid wall, while the thick ghost arc
has none (its points top out at 1.49 m). That height test marks what localisation
leans on, more directly than finding long straight lines.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import cv2
import numpy as np
from loguru import logger

from component.map_storage.service import MapDocument, MapStorage
from config.settings import MapInspectionConfig, use_utf8_output


class ProtectionZone:
    def __init__(self, **kwargs) -> None:
        self.min_height_rel = kwargs.get("protect_min_height_rel", MapInspectionConfig.PROTECT_MIN_HEIGHT_REL)
        self.min_points = kwargs.get("protect_min_points", MapInspectionConfig.PROTECT_MIN_POINTS)
        self.margin = kwargs.get("protect_margin_cells", MapInspectionConfig.PROTECT_MARGIN_CELLS)

    def mask(self, document: MapDocument) -> np.ndarray:
        """H×W bool. Built from every point, deleted or not: what counts as a wall does not change
        because some of its points were marked."""
        rows, cols, inside = document.map_cells
        tall = inside & (document.map_height > self.min_height_rel)
        height, width = document.grid.image.shape
        density = np.bincount(rows[tall] * width + cols[tall], minlength=height * width).reshape(height, width)
        core = (density >= self.min_points).astype(np.uint8)
        protected = cv2.dilate(core, np.ones((3, 3), np.uint8), iterations=self.margin) > 0
        return protected


def demo_protection() -> None:
    document = MapStorage().load()
    protected = ProtectionZone().mask(document)
    rows, cols, inside = document.map_cells
    points = int((inside & protected[rows, cols]).sum())
    arc = np.zeros_like(protected)
    arc[190:271, 78:135] = document.grid.image[190:271, 78:135] == 0
    logger.info("Protected zone {:,} cells holding {:,} map.pcd points; of the thick arc's {} cells, {} are in it",
                int(protected.sum()), points, int(arc.sum()), int((arc & protected).sum()))


def main() -> None:
    use_utf8_output()
    demo_protection()


if __name__ == "__main__":
    main()
