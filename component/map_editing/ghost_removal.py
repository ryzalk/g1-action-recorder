"""Ghost removal: cells in the mask become free or unknown, points in the height band are marked deleted."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import time
from dataclasses import dataclass, field

import numpy as np
from loguru import logger

from component.map_editing.region import EditRegion, Region
from component.map_storage.service import MapDocument, MapStorage
from config.settings import MapCloudConfig, MapEditConfig, use_utf8_output


@dataclass
class Erasure:
    """What an erase hits — reported by preview, stored in the command by apply."""

    map_idx: np.ndarray      # points to delete: newly hit only, already deleted ones are left out
    ground_idx: np.ndarray
    cells: int
    # Hit points inside the protection zone. With keep_protected they are left out of
    # map_idx / ground_idx (kept); without it they are among the points to delete.
    protected_map_idx: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))
    protected_ground_idx: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))
    kept_protected: bool = True

    @property
    def protected_points(self) -> int:
        count = len(self.protected_map_idx) + len(self.protected_ground_idx)
        return count


class GhostRemoval:
    def __init__(self, **kwargs) -> None:
        self.grid_value = kwargs.get("erase_grid_value", MapEditConfig.ERASE_GRID_VALUE)
        self.z_range_rel = kwargs.get("z_range_rel", MapCloudConfig.ERASE_Z_RANGE_REL)
        self.ground_z_range_rel = kwargs.get("ground_z_range_rel", MapCloudConfig.GROUND_ERASE_Z_RANGE_REL)

    def select(self, document: MapDocument, region: Region, params: dict,
               protected: np.ndarray | None = None) -> Erasure:
        """Writes nothing. params may override the height bands, turn the clouds off (apply_to_pcd)
        and choose whether points in the protection zone (H×W bool) survive (keep_protected, default on)."""
        if not params.get("apply_to_pcd", True):
            erasure = Erasure(map_idx=np.zeros(0, np.int64), ground_idx=np.zeros(0, np.int64), cells=region.cells)
            return erasure
        z_lo, z_hi = params.get("z_range_rel", self.z_range_rel)
        ground_lo, ground_hi = params.get("ground_z_range_rel", self.ground_z_range_rel)
        map_hit = self._hit(document.map_height, document.map_cells, document.map_deleted, region.mask, z_lo, z_hi)
        ground_hit = self._hit(document.ground_height, document.ground_cells, document.ground_deleted,
                               region.mask, ground_lo, ground_hi)
        keep = params.get("keep_protected", True)
        map_protected = np.zeros_like(map_hit)
        ground_protected = np.zeros_like(ground_hit)
        if protected is not None:
            map_protected = map_hit & protected[document.map_cells[0], document.map_cells[1]]
            ground_protected = ground_hit & protected[document.ground_cells[0], document.ground_cells[1]]
        if keep:
            map_hit &= ~map_protected
            ground_hit &= ~ground_protected
        erasure = Erasure(map_idx=np.flatnonzero(map_hit), ground_idx=np.flatnonzero(ground_hit), cells=region.cells,
                          protected_map_idx=np.flatnonzero(map_protected),
                          protected_ground_idx=np.flatnonzero(ground_protected), kept_protected=keep)
        return erasure

    def paint(self, document: MapDocument, region: Region, params: dict) -> np.ndarray:
        """The bbox pixels after the erase, computed without touching document.grid."""
        r0, r1, c0, c1 = region.bbox
        after = document.grid.image[r0:r1, c0:c1].copy()
        after[region.mask[r0:r1, c0:c1]] = int(params.get("grid_value", self.grid_value))
        return after

    @staticmethod
    def _hit(height: np.ndarray, cells: tuple, deleted: np.ndarray, mask: np.ndarray,
             low: float, high: float) -> np.ndarray:
        """Undeleted points whose cell is in the mask and whose height above the local floor is in the band."""
        rows, cols, inside = cells
        hit = inside & mask[rows, cols] & (height > low) & (height < high) & ~deleted
        return hit


def demo_select() -> None:
    """A 2 m square over the thick black arc (a ghost): count what an erase would take, and how fast."""
    document = MapStorage().load()
    region = EditRegion().build(document.grid, {"polygon": [[-1.6, 5.3], [0.4, 5.3], [0.4, 7.3], [-1.6, 7.3]]})
    removal = GhostRemoval()
    started = time.perf_counter()
    erasure = removal.select(document, region, {})
    after = removal.paint(document, region, {})
    seconds = time.perf_counter() - started
    r0, r1, c0, c1 = region.bbox
    before = document.grid.image[r0:r1, c0:c1]
    logger.info("{} cells; map.pcd hits {:,} points, ground_map.pcd {:,}; occupied cells {} -> {}; {:.3f} s",
                erasure.cells, len(erasure.map_idx), len(erasure.ground_idx),
                int((before == 0).sum()), int((after == 0).sum()), seconds)
    assert not document.map_deleted.any(), "select must not write"
    assert seconds < 1.0


def main() -> None:
    use_utf8_output()
    demo_select()


if __name__ == "__main__":
    main()
