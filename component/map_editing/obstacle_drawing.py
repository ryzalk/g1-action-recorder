"""Add obstacles: cells in the mask become occupied; the point clouds are not touched."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import numpy as np
from loguru import logger

from component.map_editing.region import EditRegion, Region
from component.map_storage.service import MapDocument, MapStorage
from config.settings import MapGridConfig, use_utf8_output


class ObstacleDrawing:
    def __init__(self, **kwargs) -> None:
        self.grid_value = MapGridConfig.OCCUPIED

    def paint(self, document: MapDocument, region: Region) -> np.ndarray:
        """The bbox pixels after drawing, computed without touching document.grid."""
        r0, r1, c0, c1 = region.bbox
        after = document.grid.image[r0:r1, c0:c1].copy()
        after[region.mask[r0:r1, c0:c1]] = self.grid_value
        return after


def demo_paint() -> None:
    document = MapStorage().load()
    region = EditRegion().build(document.grid, {"polyline": [[0.0, 0.0], [3.0, 1.73]], "width_m": 0.10})
    after = ObstacleDrawing().paint(document, region)
    logger.info("30° wall 3.46 m: {} cells, {} occupied in the bounding box after", region.cells,
                int((after == 0).sum()))
    assert (after[region.mask[region.bbox[0]:region.bbox[1], region.bbox[2]:region.bbox[3]]] == 0).all()


def main() -> None:
    use_utf8_output()
    demo_paint()


if __name__ == "__main__":
    main()
