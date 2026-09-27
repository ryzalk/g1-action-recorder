"""Floor height per cell: the z of the floor under each grid cell; every "x m above the floor" uses it.

RTLAB's floor is not level: the left room sits at z ≈ -1.23 while the hall,
corridor and top area sit at ≈ -1.10. Measured against one global floor, the
higher part's floor shows up 0.14 m "above ground" — the grey fog in the
projection that the design doc took for segmentation noise. It is the floor;
deleting it would take floor points from the localiser. Measuring every height
against the local floor makes it disappear without touching a point.

The floor of each 0.5 m tile is the lowest dense height layer among its low
map.pcd points; tiles with too few points, or a floor off the building's level,
take their nearest measured neighbour's.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import time

import cv2
import numpy as np
from loguru import logger
from scipy import ndimage

from config.settings import MapCloudConfig, MapPathConfig, use_utf8_output
from util.occupancy_grid_helper import OccupancyGrid, OccupancyGridHelper
from util.point_cloud_helper import PointCloud, PointCloudHelper


class FloorHeight:
    def __init__(self, **kwargs) -> None:
        self.tile_m = kwargs.get("floor_tile_m", MapCloudConfig.FLOOR_TILE_M)
        self.search_rel = kwargs.get("floor_search_rel", MapCloudConfig.FLOOR_SEARCH_REL)
        self.min_points = kwargs.get("floor_min_points", MapCloudConfig.FLOOR_MIN_POINTS)
        self.bin_m = kwargs.get("floor_bin_m", MapCloudConfig.FLOOR_BIN_M)
        self.dense_share = kwargs.get("floor_dense_share", MapCloudConfig.FLOOR_DENSE_SHARE)
        self.plausible_rel = kwargs.get("floor_plausible_rel", MapCloudConfig.FLOOR_PLAUSIBLE_REL)

    def building_floor(self, cloud: PointCloud) -> float:
        """The building-wide floor z: the densest height layer in the lower half of the cloud.

        A floor holds more points than any other level, except perhaps a ceiling, which the lower
        half leaves out. The half is taken between the 1st and 99th percentiles, so a few stray
        points far below or above do not move it. Measured: RTLAB -1.25, delta -1.27.
        """
        z = cloud.xyz[:, 2]
        bottom, top = np.percentile(z, [1, 99])
        lower = z[(z >= bottom) & (z < (bottom + top) / 2)]
        # Bins on whole multiples of bin_m, so the answer does not hinge on where the percentile fell.
        start = np.floor(bottom / self.bin_m) * self.bin_m
        counts, edges = np.histogram(lower, bins=np.arange(start, (bottom + top) / 2 + self.bin_m, self.bin_m))
        floor_z = round(float(edges[counts.argmax()] + self.bin_m / 2), 3)
        return floor_z

    def estimate(self, grid: OccupancyGrid, cloud: PointCloud, ground_z: float) -> np.ndarray:
        """H×W floor z for every grid cell; ground_z is the building floor the tiles are searched around."""
        tile = max(1, int(round(self.tile_m / grid.resolution)))
        tiles_high = -(-grid.height // tile)
        tiles_wide = -(-grid.width // tile)
        xyz = cloud.xyz
        rows, cols = grid.world_to_pixel(xyz[:, :2])
        low, high = ground_z + self.search_rel[0], ground_z + self.search_rel[1]
        keep = grid.contains(rows, cols) & (xyz[:, 2] > low) & (xyz[:, 2] < high)
        bins = int(np.ceil((high - low) / self.bin_m))
        tile_index = (rows[keep] // tile) * tiles_wide + cols[keep] // tile
        bin_index = np.minimum(((xyz[keep, 2] - low) / self.bin_m).astype(np.int64), bins - 1)
        # One height histogram per tile, all at once: counts[tile, bin].
        counts = np.bincount(tile_index * bins + bin_index, minlength=tiles_high * tiles_wide * bins)
        counts = counts.reshape(tiles_high * tiles_wide, bins)
        # The floor is the lowest dense layer, not the densest: a table top can hold more points
        # than the floor under it.
        dense = counts >= self.dense_share * counts.max(axis=1, keepdims=True)
        floor = (low + (dense.argmax(axis=1) + 0.5) * self.bin_m).reshape(tiles_high, tiles_wide)
        measured = counts.sum(axis=1).reshape(tiles_high, tiles_wide) >= self.min_points
        # A "floor" far off the building's level is furniture seen from above; its neighbours know better.
        measured &= (floor > ground_z + self.plausible_rel[0]) & (floor < ground_z + self.plausible_rel[1])
        # Unmeasured tiles copy their nearest measured tile, then a 3×3 median evens out single odd tiles.
        _, (near_rows, near_cols) = ndimage.distance_transform_edt(~measured, return_indices=True)
        floor = ndimage.median_filter(floor[near_rows, near_cols], size=3)
        cells = cv2.resize(floor.astype(np.float32), (tiles_wide * tile, tiles_high * tile),
                           interpolation=cv2.INTER_LINEAR)[:grid.height, :grid.width]
        return cells


def demo_floor() -> None:
    grid = OccupancyGridHelper().read(MapPathConfig.MAP_DIR)
    cloud = PointCloudHelper().read(MapPathConfig.MAP_DIR / MapCloudConfig.MAP_FILE)
    floor_height = FloorHeight()
    started = time.perf_counter()
    ground_z = floor_height.building_floor(cloud)
    floor = floor_height.estimate(grid, cloud, ground_z)
    seconds = time.perf_counter() - started
    logger.info("Building floor z = {}", ground_z)
    places = {"left room": (1.5, 1.0), "fog centre": (7.6, 6.3), "corridor": (12.0, 2.0), "top": (5.0, 11.0)}
    for name, (x, y) in places.items():
        rows, cols = grid.world_to_pixel(np.array([[x, y]]))
        logger.info("{} ({}, {}): floor z = {:.3f}", name, x, y, floor[rows[0], cols[0]])
    free = grid.image == 254
    logger.info("Floor under free cells {:.2f} ~ {:.2f}, median {:.2f}; {:.2f} s",
                floor[free].min(), floor[free].max(), float(np.median(floor[free])), seconds)

    rows, cols = grid.world_to_pixel(cloud.xyz[:, :2])
    inside = grid.contains(rows, cols)
    height = cloud.xyz[inside, 2] - floor[rows[inside], cols[inside]]
    fog = inside.copy()
    fog[inside] = (height > 0.10) & (height < 0.30)
    global_fog = inside & (cloud.xyz[:, 2] > ground_z + 0.10) & (cloud.xyz[:, 2] < ground_z + 0.30)
    logger.info("Points 0.10 ~ 0.30 m above the floor: {:,} by the global floor, {:,} per cell",
                int(global_fog.sum()), int(fog.sum()))


def main() -> None:
    use_utf8_output()
    demo_floor()


if __name__ == "__main__":
    main()
