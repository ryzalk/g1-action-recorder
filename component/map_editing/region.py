"""Edit regions: world geometry -> grid mask. Erasing and adding obstacles share the same mask."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dataclasses import dataclass

import numpy as np
from loguru import logger

from config.settings import MapPathConfig, use_utf8_output
from util.occupancy_grid_helper import OccupancyGrid, OccupancyGridHelper
from util.raster_helper import RasterHelper


@dataclass
class Region:
    mask: np.ndarray                    # H×W bool
    bbox: tuple[int, int, int, int]     # r0, r1, c0, c1, end exclusive

    @property
    def cells(self) -> int:
        cells = int(self.mask.sum())
        return cells


class EditRegion:
    def __init__(self, **kwargs) -> None:
        self.raster = RasterHelper(**kwargs)

    def build(self, grid: OccupancyGrid, geometry: dict) -> Region:
        """geometry is {"polygon": [[x, y], ...]} or {"polyline": [[x, y], ...], "width_m": w}, in metres."""
        shape = grid.image.shape
        if "polygon" in geometry:
            mask = self.raster.polygon_mask(shape, self._to_pixels(grid, geometry["polygon"]))
        else:
            width_px = geometry["width_m"] / grid.resolution
            mask = self.raster.polyline_mask(shape, self._to_pixels(grid, geometry["polyline"]), width_px)
        region = Region(mask=mask, bbox=self.raster.bbox(mask))
        return region

    @staticmethod
    def _to_pixels(grid: OccupancyGrid, points: list) -> np.ndarray:
        """World -> (col, row) float with pixel centres on integers, which is where cv2 puts them."""
        xy = np.asarray(points, dtype=np.float64)
        cols = (xy[:, 0] - grid.origin[0]) / grid.resolution - 0.5
        rows = grid.height - (xy[:, 1] - grid.origin[1]) / grid.resolution - 0.5
        pixels = np.stack([cols, rows], axis=1)
        return pixels


def demo_region() -> None:
    """A 1 m square covers 20×20 cells plus at most one ring of edge cells (cv2 draws the outline too);
    a 0.10 m wall is two cells across; a shape off the map covers nothing."""
    grid = OccupancyGridHelper().read(MapPathConfig.MAP_DIR)
    region = EditRegion()
    square = region.build(grid, {"polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]})
    wall = region.build(grid, {"polyline": [[0.0, 0.0], [4.0, 0.0]], "width_m": 0.10})
    brush = region.build(grid, {"polyline": [[2.0, 2.0], [2.0, 2.0]], "width_m": 0.30})
    outside = region.build(grid, {"polygon": [[100.0, 100.0], [101.0, 100.0], [101.0, 101.0]]})
    rows, cols = grid.world_to_pixel(np.array([[0.5, 0.5]]))
    assert square.mask[rows[0], cols[0]]
    assert 400 <= square.cells <= 22 * 22 and outside.cells == 0 and outside.bbox == (0, 0, 0, 0)
    logger.info("1 m square {} cells, box {}; 4 m × 0.10 m wall {} cells; 0.30 m brush dab {} cells; "
                "shape off the grid {} cells",
                square.cells, square.bbox, wall.cells, brush.cells, outside.cells)


def main() -> None:
    use_utf8_output()
    demo_region()


if __name__ == "__main__":
    main()
