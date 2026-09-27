"""MuJoCo kinematic state of the G1: set named joints, read positions and the base pose back."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from collections.abc import Mapping

import mujoco
from loguru import logger

from config.settings import PathConfig, use_utf8_output


class RobotKinematicsHelper:
    """Forward kinematics only: no physics step, so poses hold exactly as set."""

    def __init__(self, mjcf_path: Path = PathConfig.MJCF_PATH) -> None:
        self.model = mujoco.MjModel.from_xml_path(str(mjcf_path))
        self.data = mujoco.MjData(self.model)
        self.qpos_address = {}
        for joint_id in range(self.model.njnt):
            if self.model.jnt_type[joint_id] == mujoco.mjtJoint.mjJNT_HINGE:
                name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, joint_id)
                self.qpos_address[name] = int(self.model.jnt_qposadr[joint_id])
        self.pelvis_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
        mujoco.mj_forward(self.model, self.data)

    def set_joints(self, joint_values: Mapping[str, float]) -> None:
        for name, value in joint_values.items():
            self.data.qpos[self.qpos_address[name]] = value
        mujoco.mj_forward(self.model, self.data)

    def joint_positions(self) -> dict[str, float]:
        positions = {name: float(self.data.qpos[address]) for name, address in self.qpos_address.items()}
        return positions

    def base_pose(self) -> tuple[tuple[float, ...], tuple[float, ...]]:
        """Pelvis position and wxyz orientation in the world."""
        position = tuple(float(value) for value in self.data.xpos[self.pelvis_id])
        wxyz = tuple(float(value) for value in self.data.xquat[self.pelvis_id])
        pose = (position, wxyz)
        return pose


def demo_robot_kinematics_helper() -> None:
    helper = RobotKinematicsHelper()
    helper.set_joints({"left_elbow_joint": 1.0})
    logger.info("{} hinge joints, left elbow {:.2f} rad, pelvis at {}", len(helper.qpos_address),
                helper.joint_positions()["left_elbow_joint"], helper.base_pose()[0])


def main() -> None:
    use_utf8_output()
    demo_robot_kinematics_helper()


if __name__ == "__main__":
    main()
