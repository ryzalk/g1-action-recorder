"""Keeps the Viser scene in step with the MapDocument: downsampled clouds, deleted points, the red preview,
the grid texture."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import time

import numpy as np
from loguru import logger

from component.map_editing.ghost_removal import Erasure
from component.map_storage.service import MapDocument, MapStorage
from config.settings import MapViewerConfig, use_utf8_output
from util.point_cloud_helper import PointCloudHelper
from util.point_cloud_viewer_helper import PointCloudViewerHelper
from util.raster_helper import RasterHelper


class SceneSync:
    MAP_NODE = "/pcd/map"
    GROUND_NODE = "/pcd/ground"
    GRID_NODE = "/grid"
    PREVIEW_NODE = "/preview/delete"
    PROTECTED_NODE = "/preview/protected"
    # Layers the page can switch; preview points are always shown.
    LAYER_NODES = {"map": MAP_NODE, "ground": GROUND_NODE, "grid": GRID_NODE}

    def __init__(self, host: str = MapViewerConfig.HOST, port: int = MapViewerConfig.PORT, **kwargs) -> None:
        self.viewer = PointCloudViewerHelper(host, port, **kwargs)
        self.raster = RasterHelper()
        self.voxel_size = kwargs.get("voxel_size", MapViewerConfig.VOXEL_SIZE)
        self.preview_limit = kwargs.get("preview_limit", MapViewerConfig.PREVIEW_LIMIT)
        self.preview_color = kwargs.get("preview_color", MapViewerConfig.PREVIEW_COLOR)
        self.protected_color = kwargs.get("protected_color", MapViewerConfig.PROTECTED_COLOR)
        self.preview_point_size = kwargs.get("preview_point_size", MapViewerConfig.PREVIEW_POINT_SIZE)
        self.color_z_range_rel = kwargs.get("color_z_range_rel", MapViewerConfig.COLOR_Z_RANGE_REL)
        # Display point -> full-resolution index, so a delete hides exactly its own points.
        self.map_display_idx = None
        self.ground_display_idx = None
        self.map_colors = None
        self.ground_colors = None
        # Before start() every scene call is a no-op, so demos and the API test client need no 3D server.
        self.started = False
        # Kept here, not only in viser, so a reloaded page shows the switches as they really are.
        self.layers = {"map": True, "ground": False, "grid": True}

    @property
    def url(self) -> str:
        url = self.viewer.url
        return url

    def start(self) -> None:
        self.viewer.start()
        self.started = True
        self.viewer.add_note("Left drag to orbit · right drag to pan · scroll to zoom; layers are on the Map page")

    def build(self, document: MapDocument) -> None:
        """For a newly opened map: its grid texture has its own size and place, the camera starts over."""
        if not self.started:
            return
        self.viewer.remove(self.GRID_NODE)
        self.reload(document)
        for name, visible in self.layers.items():
            self.viewer.set_visible(self.LAYER_NODES[name], visible)
        self.focus(document)
        logger.info("3D scene: map.pcd shows {:,} points, ground_map.pcd {:,} points, {}",
                    len(self.map_display_idx), len(self.ground_display_idx), self.url)

    def reload(self, document: MapDocument) -> None:
        """For a document with different points (first build, or after restoring the original)."""
        if not self.started:
            return
        map_xyz = document.map_cloud.xyz
        ground_xyz = document.ground_cloud.xyz
        self.map_display_idx = PointCloudHelper.voxel_indices(map_xyz, self.voxel_size)
        self.ground_display_idx = PointCloudHelper.voxel_indices(ground_xyz, self.voxel_size)
        self.map_colors = self._height_colors(document.map_height[self.map_display_idx])
        self.ground_colors = self._height_colors(document.ground_height[self.ground_display_idx])
        self.clear_preview()
        self.refresh(document)

    def refresh(self, document: MapDocument) -> None:
        """Redraw after an edit: deleted points drop out, the grid texture follows the current grid."""
        if not self.started:
            return
        map_xyz = document.map_cloud.xyz
        ground_xyz = document.ground_cloud.xyz
        map_keep = ~document.map_deleted[self.map_display_idx]
        ground_keep = ~document.ground_deleted[self.ground_display_idx]
        self.viewer.set_points(self.MAP_NODE, map_xyz[self.map_display_idx[map_keep]], self.map_colors[map_keep])
        self.viewer.set_points(self.GROUND_NODE, ground_xyz[self.ground_display_idx[ground_keep]],
                               self.ground_colors[ground_keep])
        grid = document.grid
        width_m = grid.width * grid.resolution
        height_m = grid.height * grid.resolution
        centre = (grid.origin[0] + width_m / 2, grid.origin[1] + height_m / 2, document.ground_z - 0.01)
        self.viewer.set_image(self.GRID_NODE, self._grid_texture(document), width_m, height_m, centre)

    def set_layer(self, name: str, visible: bool) -> None:
        self.layers[name] = visible
        if not self.started:
            return
        self.viewer.set_visible(self.LAYER_NODES[name], visible)

    def show_preview(self, document: MapDocument, erasure: Erasure) -> None:
        """Points to delete in red, hit points in the protection zone in magenta (kept or not)."""
        if not self.started:
            return
        delete_map = np.setdiff1d(erasure.map_idx, erasure.protected_map_idx, assume_unique=True)
        delete_ground = np.setdiff1d(erasure.ground_idx, erasure.protected_ground_idx, assume_unique=True)
        self._show_points(self.PREVIEW_NODE, document, delete_map, delete_ground, self.preview_color)
        self._show_points(self.PROTECTED_NODE, document, erasure.protected_map_idx, erasure.protected_ground_idx,
                          self.protected_color)

    def clear_preview(self) -> None:
        if not self.started:
            return
        for node in (self.PREVIEW_NODE, self.PROTECTED_NODE):
            self.viewer.set_points(node, np.zeros((0, 3), np.float32), np.zeros((0, 3), np.uint8))

    def _show_points(self, node: str, document: MapDocument, map_idx: np.ndarray, ground_idx: np.ndarray,
                     color: tuple) -> None:
        """Full resolution; above the limit an even subset is drawn, the count on the page stays full."""
        points = np.concatenate([document.map_cloud.xyz[map_idx], document.ground_cloud.xyz[ground_idx]])
        if len(points) > self.preview_limit:
            points = points[np.linspace(0, len(points) - 1, self.preview_limit).astype(np.int64)]
        colors = np.tile(np.array(color, dtype=np.uint8), (len(points), 1))
        self.viewer.set_points(node, points, colors, point_size=self.preview_point_size, visible=True)

    def focus(self, document: MapDocument, **kwargs) -> None:
        """Look at a spot from above and to the south; with no target, the whole map."""
        if not self.started:
            return
        grid = document.grid
        width_m = grid.width * grid.resolution
        height_m = grid.height * grid.resolution
        target_x = kwargs.get("x", grid.origin[0] + width_m / 2)
        target_y = kwargs.get("y", grid.origin[1] + height_m / 2)
        distance = kwargs.get("distance", max(width_m, height_m))
        target = (target_x, target_y, document.ground_z)
        position = (target_x, target_y - distance * 0.6, document.ground_z + distance * 0.9)
        self.viewer.look_at(position, target)

    def _height_colors(self, height: np.ndarray) -> np.ndarray:
        """Coloured by height above the local floor, so the same colour means the same height everywhere."""
        low, high = self.color_z_range_rel
        colors = self.raster.colormap((height - low) / (high - low))
        return colors

    @staticmethod
    def _grid_texture(document: MapDocument) -> np.ndarray:
        """Flipped upside down: viser draws image row 0 toward -y, while PGM row 0 is the map's +y edge.
        Measured on RTLAB (2026-09-24) — unflipped, the corridor pointed the opposite way to the cloud."""
        texture = np.repeat(document.grid.image[::-1, :, None], 3, axis=2)
        return texture


def demo_scene() -> None:
    """Loads RTLAB, builds the scene and previews a patch of points; open the printed URL."""
    document = MapStorage().load()
    scene = SceneSync()
    scene.start()
    scene.build(document)
    xyz = document.map_cloud.xyz
    patch = np.flatnonzero((np.abs(xyz[:, 0] - 2.0) < 1.0) & (np.abs(xyz[:, 1] - 3.0) < 1.0))
    scene.show_preview(document, Erasure(map_idx=patch, ground_idx=np.zeros(0, np.int64), cells=0))
    logger.info("Previewing {:,} points (red). Open {} to look, Ctrl+C to stop", len(patch), scene.url)
    while True:
        time.sleep(1)


def main() -> None:
    use_utf8_output()
    demo_scene()


if __name__ == "__main__":
    main()
