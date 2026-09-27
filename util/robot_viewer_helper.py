"""Viser 3D view of a URDF robot: load it once, then move its joints and orbit the camera."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import math
import threading
import time
from collections.abc import Sequence

import numpy as np
import viser
from loguru import logger
from viser.extras import ViserUrdf

from config.settings import PathConfig, ViewerConfig, use_utf8_output


class RobotViewerHelper:
    def __init__(self, host: str = ViewerConfig.HOST, port: int = ViewerConfig.PORT,
                 urdf_path: Path = PathConfig.URDF_PATH) -> None:
        self.host = host
        self.port = port
        self.urdf_path = urdf_path
        self.server = None
        self.robot = None
        self.root = None
        # Bumped by every camera move, so an older move still animating stops.
        self.camera_move_id = 0

    @property
    def url(self) -> str:
        url = f"http://{self.host}:{self.port}"
        return url

    def start(self) -> None:
        self.server = viser.ViserServer(host=self.host, port=self.port, label="View settings", verbose=False)
        self.server.gui.configure_theme(dark_mode=True, show_logo=False, show_share_button=False,
                                        control_layout="floating", control_width="small")
        # The page carries every control; viser's own panel would only cover the robot. With nothing of
        # its own in it, viser opens its settings page there instead, which covers much more of a small view.
        self.server.gui.add_markdown("Controls are on the page.")
        self.server.gui.main_panel.minimize()
        self.server.scene.set_up_direction("+z")
        self.server.scene.world_axes.visible = False
        self.server.scene.add_grid("/ground", width=8.0, height=8.0, cell_size=0.25, section_size=1.0,
                                   cell_color=(65, 70, 78), section_color=(100, 108, 120),
                                   plane_color=(16, 19, 24), plane_opacity=0.85)
        self.root = self.server.scene.add_frame("/robot", show_axes=False)
        self.robot = ViserUrdf(self.server, self.urdf_path, root_node_name="/robot")

    def joint_names(self) -> tuple[str, ...]:
        names = tuple(self.robot.get_actuated_joint_names())
        return names

    def show(self, joint_positions: Sequence[float], base_position: Sequence[float],
             base_wxyz: Sequence[float]) -> None:
        """joint_positions in joint_names() order."""
        with self.server.atomic():
            self.root.position = tuple(base_position)
            self.root.wxyz = tuple(base_wxyz)
            self.robot.update_cfg(np.asarray(joint_positions))

    def client_count(self) -> int:
        count = len(self.server.get_clients())
        return count

    def orbit_camera(self, azimuth_degrees: float, distance: float, height: float, look_at: Sequence[float],
                     fov_degrees: float, seconds: float) -> None:
        """Swing every open view around look_at to the given azimuth; views opened later start there."""
        target = self._orbit_position(math.radians(azimuth_degrees), distance, height, look_at)
        self.server.initial_camera.position = target
        self.server.initial_camera.look_at = tuple(look_at)
        self.server.initial_camera.fov = math.radians(fov_degrees)
        self.camera_move_id += 1
        for client in self.server.get_clients().values():
            threading.Thread(target=self._animate, daemon=True,
                             args=(client, self.camera_move_id, math.radians(azimuth_degrees), distance, height,
                                   look_at, math.radians(fov_degrees), seconds)).start()

    def _animate(self, client, move_id: int, azimuth: float, distance: float, height: float,
                 look_at: Sequence[float], fov: float, seconds: float) -> None:
        start = np.asarray(client.camera.position) - np.asarray(look_at)
        start_azimuth = math.atan2(start[1], start[0])
        start_distance = float(np.hypot(start[0], start[1]))
        start_height = float(client.camera.position[2])
        # Shortest way round, so front -> right turns 90 degrees rather than 270.
        turn = (azimuth - start_azimuth + math.pi) % (2 * math.pi) - math.pi
        started = time.monotonic()
        while move_id == self.camera_move_id:
            progress = min(1.0, (time.monotonic() - started) / seconds)
            eased = progress * progress * (3.0 - 2.0 * progress)
            position = self._orbit_position(start_azimuth + eased * turn,
                                            start_distance + eased * (distance - start_distance),
                                            start_height + eased * (height - start_height), look_at)
            with client.atomic():
                client.camera.position = position
                client.camera.look_at = tuple(look_at)
                client.camera.up_direction = (0.0, 0.0, 1.0)
                client.camera.fov = fov
            if progress >= 1.0:
                return
            time.sleep(1.0 / 60.0)

    @staticmethod
    def _orbit_position(azimuth: float, distance: float, height: float, look_at: Sequence[float]) -> tuple:
        position = (look_at[0] + distance * math.cos(azimuth), look_at[1] + distance * math.sin(azimuth), height)
        return position


def demo_robot_viewer_helper() -> None:
    """Open the printed URL; the camera circles the robot every few seconds. Ctrl+C to stop."""
    viewer = RobotViewerHelper()
    viewer.start()
    viewer.show(np.zeros(len(viewer.joint_names())), (0.0, 0.0, 0.793), (1.0, 0.0, 0.0, 0.0))
    logger.info("Viser at {} with {} joints", viewer.url, len(viewer.joint_names()))
    for azimuth in [0.0, 90.0, 180.0, 270.0] * 100:
        viewer.orbit_camera(azimuth, ViewerConfig.CAMERA_DISTANCE, ViewerConfig.CAMERA_HEIGHT,
                            ViewerConfig.CAMERA_LOOK_AT, ViewerConfig.CAMERA_FOV_DEGREES,
                            ViewerConfig.CAMERA_MOVE_SECONDS)
        time.sleep(3.0)


def main() -> None:
    use_utf8_output()
    demo_robot_viewer_helper()


if __name__ == "__main__":
    main()
