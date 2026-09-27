"""Possible ghosts and possible gaps: the grid checked against the point cloud, one candidate per
connected region. Hints only; nothing is changed.

- Ghost: an occupied cell with no points nearby (people or carts that moved while mapping).
- Gap: many points at a height the robot can bump into, over free cells (furniture the grid missed).
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import time
from dataclasses import dataclass

import cv2
import numpy as np
from loguru import logger

from component.map_storage.service import MapDocument, MapStorage
from config.settings import MapGridConfig, MapInspectionConfig, use_utf8_output
from util.raster_helper import RasterHelper


@dataclass
class Candidate:
    id: int
    kind: str                    # "ghost" | "missing"
    cells: int
    centre: tuple[float, float]  # metres
    size_m: float                # longer side of the bounding box
    polygon: list                # [[x, y], ...] metres, outlines the cells (ghosts one cell wider)


class CandidateDetection:
    def __init__(self, **kwargs) -> None:
        self.raster = RasterHelper()
        self.z_range_rel = kwargs.get("candidate_z_range_rel", MapInspectionConfig.CANDIDATE_Z_RANGE_REL)
        self.min_points = kwargs.get("candidate_min_points", MapInspectionConfig.CANDIDATE_MIN_POINTS)
        self.min_cells = kwargs.get("candidate_min_cells", MapInspectionConfig.CANDIDATE_MIN_CELLS)
        self.ghost_margin = kwargs.get("candidate_ghost_margin", MapInspectionConfig.CANDIDATE_GHOST_MARGIN_CELLS)

    def detect(self, document: MapDocument, **kwargs) -> list[Candidate]:
        """kwargs override z_range_rel, min_points, min_cells for one run (the page's sliders)."""
        z_lo, z_hi = kwargs.get("z_range_rel", self.z_range_rel)
        min_points = kwargs.get("min_points", self.min_points)
        min_cells = kwargs.get("min_cells", self.min_cells)
        support = self._support(document, z_lo, z_hi, min_points)
        occupied = document.grid.image == MapGridConfig.OCCUPIED
        free = document.grid.image == MapGridConfig.FREE
        # Cells the user already decided on stay out: an obstacle they drew has no cloud behind it and
        # would read as a ghost; a patch they cleared may keep protected points and read as missed.
        changed = document.grid.image != document.grid_original.image
        kernel = np.ones((3, 3), np.uint8)
        near_support = cv2.dilate(support.astype(np.uint8), kernel, iterations=self.ghost_margin) > 0
        # Opening drops single stray cells, so only solid patches count as a missed obstacle.
        solid_support = cv2.morphologyEx(support.astype(np.uint8), cv2.MORPH_OPEN, kernel) > 0
        ghosts = self._components(document, occupied & ~near_support & ~changed, "ghost", min_cells, grow=1)
        missing = self._components(document, free & solid_support & ~changed, "missing", min_cells, grow=0)
        candidates = sorted(ghosts + missing, key=lambda candidate: candidate.cells, reverse=True)
        for index, candidate in enumerate(candidates, start=1):
            candidate.id = index
        return candidates

    @staticmethod
    def _support(document: MapDocument, low: float, high: float, min_points: int) -> np.ndarray:
        """Cells holding at least min_points undeleted map.pcd points in the band above the local floor."""
        rows, cols, inside = document.map_cells
        height = document.map_height
        band = inside & ~document.map_deleted & (height > low) & (height < high)
        height, width = document.grid.image.shape
        density = np.bincount(rows[band] * width + cols[band], minlength=height * width).reshape(height, width)
        support = density >= min_points
        return support

    def _components(self, document: MapDocument, mask: np.ndarray, kind: str, min_cells: int,
                    grow: int) -> list[Candidate]:
        grid = document.grid
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        candidates = []
        for label in range(1, count):
            x, y, w, h, cells = (int(value) for value in stats[label])
            if cells < min_cells:
                continue
            # Work in a padded crop so the outline can grow without touching the image edge.
            pad = grow + 1
            r0, c0 = max(y - pad, 0), max(x - pad, 0)
            crop = (labels[r0:y + h + pad, c0:x + w + pad] == label).astype(np.uint8)
            if grow:
                crop = cv2.dilate(crop, np.ones((3, 3), np.uint8), iterations=grow)
            contours, _ = cv2.findContours(crop, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            outline = cv2.approxPolyDP(max(contours, key=cv2.contourArea), 0.7, True).reshape(-1, 2)
            polygon = grid.pixel_to_world(outline[:, 1] + r0, outline[:, 0] + c0)
            centre = grid.pixel_to_world(np.array([y + (h - 1) / 2]), np.array([x + (w - 1) / 2]))[0]
            candidates.append(Candidate(
                id=0, kind=kind, cells=cells, centre=(round(float(centre[0]), 3), round(float(centre[1]), 3)),
                size_m=round(max(w, h) * grid.resolution, 3), polygon=np.round(polygon, 4).tolist()))
        return candidates


def demo_candidates() -> None:
    """Count both kinds on RTLAB for a few height bands; the floor fog (z ≈ -1.1) sits in the lowest one."""
    document = MapStorage().load()
    detection = CandidateDetection()
    for band in ((0.10, 1.50), (0.30, 1.50)):
        started = time.perf_counter()
        candidates = detection.detect(document, z_range_rel=band)
        seconds = time.perf_counter() - started
        ghosts = [candidate for candidate in candidates if candidate.kind == "ghost"]
        missing = [candidate for candidate in candidates if candidate.kind == "missing"]
        logger.info("Band {}: {} ghosts ({} cells), {} gaps ({} cells), {:.2f} s", band,
                    len(ghosts), sum(candidate.cells for candidate in ghosts),
                    len(missing), sum(candidate.cells for candidate in missing), seconds)
        for candidate in candidates[:5]:
            logger.info("  #{} {} {} cells, centre {}, size {} m, outline {} points", candidate.id, candidate.kind,
                        candidate.cells, candidate.centre, candidate.size_m, len(candidate.polygon))


def demo_drawn_obstacle() -> None:
    """An obstacle drawn in open floor has no cloud behind it; it must not come back as a ghost."""
    document = MapStorage().load()
    detection = CandidateDetection()
    before = len(detection.detect(document))
    rows, cols = document.grid.world_to_pixel(np.array([[6.5, 0.7]]))
    document.grid.image[rows[0] - 4:rows[0] + 4, cols[0] - 4:cols[0] + 4] = MapGridConfig.OCCUPIED
    after = detection.detect(document)
    near = [candidate for candidate in after
            if abs(candidate.centre[0] - 6.5) < 0.5 and abs(candidate.centre[1] - 0.7) < 0.5]
    logger.info("Candidates before and after an 8×8 obstacle {} -> {}, near it {}", before, len(after), len(near))
    assert not near


def main() -> None:
    use_utf8_output()
    demo_candidates()
    demo_drawn_obstacle()


if __name__ == "__main__":
    main()
