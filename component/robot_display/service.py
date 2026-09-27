"""The 3D view: follows the shared robot state in Viser and moves the camera to robot-relative views."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import threading
import time

from loguru import logger

from component.robot_state.service import RobotStateService
from config.settings import ViewerConfig, use_utf8_output
from util.robot_viewer_helper import RobotViewerHelper


class RobotDisplayService:
    def __init__(self, robot: RobotStateService) -> None:
        self.robot = robot
        self.viewer = RobotViewerHelper()
        self.started = False

    @property
    def port(self) -> int:
        return self.viewer.port

    def start(self) -> None:
        self.viewer.start()
        self.set_view("front")
        self.started = True
        threading.Thread(target=self._follow, daemon=True).start()
        logger.info("3D view at {}", self.viewer.url)

    def set_view(self, view: str) -> int:
        """front, front_left, left, back, right, front_right; returns how many open views moved."""
        self.viewer.orbit_camera(ViewerConfig.CAMERA_AZIMUTHS[view], ViewerConfig.CAMERA_DISTANCE,
                                 ViewerConfig.CAMERA_HEIGHT, ViewerConfig.CAMERA_LOOK_AT,
                                 ViewerConfig.CAMERA_FOV_DEGREES, ViewerConfig.CAMERA_MOVE_SECONDS)
        count = self.viewer.client_count()
        return count

    def _follow(self) -> None:
        # Viser redraws at most UPDATE_HZ even while playback updates the state faster.
        names = self.viewer.joint_names()
        revision = -1
        while True:
            state = self.robot.wait_for_change(revision, timeout=1.0)
            if state["revision"] != revision:
                revision = state["revision"]
                self.viewer.show([state["joint_positions"][name] for name in names], state["base_position"],
                                 state["base_wxyz"])
            time.sleep(1.0 / ViewerConfig.UPDATE_HZ)


def demo_robot_display_service() -> None:
    """Open the printed URL; the left elbow waves. Ctrl+C to stop."""
    import math

    from component.common.g1_joint_schema import G1JointSchema

    robot = RobotStateService(G1JointSchema())
    display = RobotDisplayService(robot)
    display.start()
    started = time.monotonic()
    while True:
        robot.update({"left_elbow_joint": 0.8 + 0.6 * math.sin(time.monotonic() - started)})
        time.sleep(0.02)


def main() -> None:
    use_utf8_output()
    demo_robot_display_service()


if __name__ == "__main__":
    main()
