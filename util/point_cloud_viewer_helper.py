"""A thin wrapper over a Viser scene for maps: point clouds, the grid texture, switches, the camera."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import time

import numpy as np
import viser
from loguru import logger

from config.settings import MapViewerConfig, use_utf8_output


class PointCloudViewerHelper:
    def __init__(self, host: str = MapViewerConfig.HOST, port: int = MapViewerConfig.PORT, **kwargs) -> None:
        self.host = host
        self.port = port
        self.point_size = kwargs.get("point_size", MapViewerConfig.POINT_SIZE)
        self.server = None
        # Node name -> viser handle, so a refresh updates the node in place instead of re-adding it.
        self.handles = {}

    @property
    def url(self) -> str:
        url = f"http://{self.host}:{self.port}"
        return url

    def start(self) -> None:
        self.server = viser.ViserServer(host=self.host, port=self.port, verbose=False)
        self.server.scene.set_up_direction("+z")
        # The page carries the layer switches itself, so viser's own panel is kept as small as it goes
        # and covers as little of the view as it can.
        self.server.gui.configure_theme(control_layout="floating", control_width="small",
                                        show_logo=False, show_share_button=False)

    def set_points(self, name: str, points: np.ndarray, colors: np.ndarray, **kwargs) -> None:
        """An empty set hides the node instead of sending a zero-length cloud."""
        handle = self.handles.get(name)
        if len(points) == 0:
            if handle is not None:
                handle.visible = False
            return
        # float32: float16 positions step by ~1.5 cm at 16 m from the origin, visibly off the grid.
        if handle is None:
            self.handles[name] = self.server.scene.add_point_cloud(
                name, points, colors, point_size=kwargs.get("point_size", self.point_size),
                point_shape="rounded", precision="float32", visible=kwargs.get("visible", True))
            return
        handle.points = points
        handle.colors = colors
        if "visible" in kwargs:
            handle.visible = kwargs["visible"]

    def set_image(self, name: str, rgb: np.ndarray, width_m: float, height_m: float, position: tuple) -> None:
        handle = self.handles.get(name)
        if handle is None:
            self.handles[name] = self.server.scene.add_image(
                name, rgb, width_m, height_m, format="png", position=position,
                cast_shadow=False, receive_shadow=False)
            return
        handle.image = rgb

    def set_lines(self, name: str, segments: np.ndarray, color: tuple, thickness: float) -> None:
        """segments: (N, 2, 3) start and end points in metres; none removes the node."""
        self.remove(name)
        if len(segments) == 0:
            return
        self.handles[name] = self.server.scene.add_line_segments(
            name, segments.astype(np.float32), np.array(color, dtype=np.uint8), thickness=thickness)

    def set_visible(self, name: str, visible: bool) -> None:
        self.handles[name].visible = visible

    def remove(self, name: str) -> None:
        """Drop a node, e.g. an image whose size changes; the next set_* adds it afresh."""
        handle = self.handles.pop(name, None)
        if handle is not None:
            handle.remove()

    def add_note(self, text: str) -> None:
        """A line of text in viser's panel. With nothing of its own in the panel, viser opens its
        settings page there instead, which covers much more of a small view."""
        self.server.gui.add_markdown(text)

    def look_at(self, position: tuple, target: tuple) -> None:
        """New clients start here; connected ones are moved now."""
        self.server.initial_camera.position = position
        self.server.initial_camera.look_at = target
        for client in self.server.get_clients().values():
            client.camera.position = position
            client.camera.look_at = target


def demo_viewer() -> None:
    """Random cloud over a chequered image; open the printed URL, Ctrl+C to stop."""
    viewer = PointCloudViewerHelper()
    viewer.start()
    generator = np.random.default_rng(0)
    points = generator.uniform(-2, 2, (5_000, 3)).astype(np.float32)
    colors = ((points - points.min(0)) / np.ptp(points, 0) * 255).astype(np.uint8)
    viewer.set_points("/demo/cloud", points, colors)
    board = (np.indices((8, 8)).sum(axis=0) % 2 * 200 + 40).astype(np.uint8)
    viewer.set_image("/demo/board", np.repeat(board[..., None], 3, axis=2), 4.0, 4.0, (0, 0, -2))
    viewer.look_at((6, -6, 6), (0, 0, 0))
    logger.info("Viser started: {}", viewer.url)
    while True:
        time.sleep(1)


def main() -> None:
    use_utf8_output()
    demo_viewer()


if __name__ == "__main__":
    main()
