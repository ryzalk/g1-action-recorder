"""Layer images for the 2D map: the grid and the point-cloud height-band projection."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import numpy as np
from loguru import logger

from component.map_storage.service import MapDocument, MapStorage
from config.settings import MapCloudConfig, MapDisplayConfig, MapGridConfig, MapPathConfig, use_utf8_output
from util.raster_helper import RasterHelper


class LayerImage:
    def __init__(self, **kwargs) -> None:
        self.raster = RasterHelper()
        self.projection_color = kwargs.get("projection_color", MapDisplayConfig.PROJECTION_COLOR)
        self.full_count = kwargs.get("projection_full_count", MapDisplayConfig.PROJECTION_FULL_COUNT)
        self.diff_colors = kwargs.get("diff_colors", MapDisplayConfig.DIFF_COLORS)
        self.protection_color = kwargs.get("protection_color", MapDisplayConfig.PROTECTION_COLOR)

    def grid_png(self, document: MapDocument, which: str = "current") -> bytes:
        grid = document.grid_original if which == "original" else document.grid
        png = self.raster.to_png(grid.image)
        return png

    def diff_png(self, document: MapDocument) -> bytes:
        """RGBA over the grid: cells cleared since the original in teal, cells made obstacles in orange,
        any other change (e.g. to unknown) in violet."""
        before = document.grid_original.image
        after = document.grid.image
        rgba = np.zeros((*after.shape, 4), dtype=np.uint8)
        changed = before != after
        cleared = changed & (before == MapGridConfig.OCCUPIED)
        added = changed & (after == MapGridConfig.OCCUPIED)
        rgba[changed] = self.diff_colors["other"]
        rgba[cleared] = self.diff_colors["cleared"]
        rgba[added] = self.diff_colors["added"]
        png = self.raster.to_png(rgba)
        return png

    def protection_png(self, protected: np.ndarray) -> bytes:
        """RGBA: the protection zone tinted, everything else transparent."""
        rgba = np.zeros((*protected.shape, 4), dtype=np.uint8)
        rgba[protected] = self.protection_color
        png = self.raster.to_png(rgba)
        return png

    def projection_png(self, document: MapDocument, z_lo_rel: float, z_hi_rel: float,
                       source: str = "map") -> bytes:
        """RGBA: coloured where undeleted points fall in the band, transparent elsewhere,
        so it stacks on the grid. Heights are above each cell's own floor."""
        if source == "ground":
            height, cells, deleted = document.ground_height, document.ground_cells, document.ground_deleted
        else:
            height, cells, deleted = document.map_height, document.map_cells, document.map_deleted
        rows, cols, inside = cells
        band = inside & ~deleted & (height > z_lo_rel) & (height < z_hi_rel)

        height, width = document.grid.image.shape
        density = np.bincount(rows[band] * width + cols[band], minlength=height * width).reshape(height, width)
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[..., :3] = self.projection_color
        rgba[..., 3] = (np.minimum(density / self.full_count, 1.0) * 255).astype(np.uint8)
        png = self.raster.to_png(rgba)
        return png


def demo_layers() -> None:
    document = MapStorage().load()
    layers = LayerImage()
    out_dir = MapPathConfig.DEMO_DIR / "layers"
    out_dir.mkdir(parents=True, exist_ok=True)
    z_lo, z_hi = MapCloudConfig.PROJECTION_Z_RANGE_REL
    images = {
        "grid_current.png": layers.grid_png(document),
        "grid_original.png": layers.grid_png(document, "original"),
        "projection_map.png": layers.projection_png(document, z_lo, z_hi),
        "projection_ground.png": layers.projection_png(document, z_lo, z_hi, "ground"),
        "diff.png": layers.diff_png(document),
    }
    for name, png in images.items():
        (out_dir / name).write_bytes(png)
        logger.info("{}: {:,} bytes", out_dir / name, len(png))


def main() -> None:
    use_utf8_output()
    demo_layers()


if __name__ == "__main__":
    main()
