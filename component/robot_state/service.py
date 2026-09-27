"""The one shared robot state: every pose shown, edited or played goes through here."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import threading
from collections.abc import Mapping

from loguru import logger

from component.common.g1_joint_schema import G1JointSchema
from config.settings import use_utf8_output
from util.robot_kinematics_helper import RobotKinematicsHelper


class RobotStateService:
    """Simulation only: nothing here reaches a real robot."""

    def __init__(self, schema: G1JointSchema) -> None:
        self.schema = schema
        self.kinematics = RobotKinematicsHelper()
        self.changed = threading.Condition()
        # Bumped on every change, so viewers and the page can tell whether they are behind.
        self.revision = 0

    def update(self, joint_values: Mapping[str, float]) -> int:
        """Set some joints (the rest keep their values); out-of-limit values are refused."""
        checked = self.schema.check_some(joint_values)
        with self.changed:
            self.kinematics.set_joints(checked)
            self.revision += 1
            self.changed.notify_all()
            revision = self.revision
        return revision

    def snapshot(self) -> dict:
        with self.changed:
            base_position, base_wxyz = self.kinematics.base_pose()
            state = {"revision": self.revision, "joint_positions": self.kinematics.joint_positions(),
                     "base_position": base_position, "base_wxyz": base_wxyz}
        return state

    def wait_for_change(self, revision: int, timeout: float) -> dict:
        """Return as soon as the state moves past revision, or after timeout."""
        with self.changed:
            self.changed.wait_for(lambda: self.revision != revision, timeout=timeout)
        state = self.snapshot()
        return state


def demo_robot_state_service() -> None:
    service = RobotStateService(G1JointSchema())
    revision = service.update({"left_elbow_joint": 1.0})
    state = service.snapshot()
    logger.info("Revision {}: left elbow {:.2f} rad, pelvis {}", revision, state["joint_positions"]["left_elbow_joint"],
                state["base_position"])


def main() -> None:
    use_utf8_output()
    demo_robot_state_service()


if __name__ == "__main__":
    main()
