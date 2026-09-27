"""The G1 29-DOF joint contract: names in Unitree DDS order, groups, and URDF limits."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import math
from collections.abc import Mapping
from enum import Enum

from loguru import logger

from config.settings import use_utf8_output
from util.robot_model_helper import JointLimit, RobotModelHelper


class PoseType(str, Enum):
    BASE = "base"
    LEFT_ARM = "left_arm"
    RIGHT_ARM = "right_arm"
    COMPOSED = "composed"


class G1JointSchema:
    # Unitree DDS motor order; a future LowState reader indexes motors by this.
    DDS_JOINT_NAMES = (
        "left_hip_pitch_joint", "left_hip_roll_joint", "left_hip_yaw_joint", "left_knee_joint",
        "left_ankle_pitch_joint", "left_ankle_roll_joint",
        "right_hip_pitch_joint", "right_hip_roll_joint", "right_hip_yaw_joint", "right_knee_joint",
        "right_ankle_pitch_joint", "right_ankle_roll_joint",
        "waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint",
        "left_shoulder_pitch_joint", "left_shoulder_roll_joint", "left_shoulder_yaw_joint", "left_elbow_joint",
        "left_wrist_roll_joint", "left_wrist_pitch_joint", "left_wrist_yaw_joint",
        "right_shoulder_pitch_joint", "right_shoulder_roll_joint", "right_shoulder_yaw_joint", "right_elbow_joint",
        "right_wrist_roll_joint", "right_wrist_pitch_joint", "right_wrist_yaw_joint",
    )
    LEG_JOINT_NAMES = DDS_JOINT_NAMES[:12]
    WAIST_JOINT_NAMES = DDS_JOINT_NAMES[12:15]
    LEFT_ARM_JOINT_NAMES = DDS_JOINT_NAMES[15:22]
    RIGHT_ARM_JOINT_NAMES = DDS_JOINT_NAMES[22:29]
    ARM_JOINT_NAMES = LEFT_ARM_JOINT_NAMES + RIGHT_ARM_JOINT_NAMES
    # What a whole-body (base / composed) pose stores: waist plus both arms.
    UPPER_BODY_JOINT_NAMES = WAIST_JOINT_NAMES + ARM_JOINT_NAMES

    def __init__(self, model_helper: RobotModelHelper | None = None) -> None:
        model_helper = model_helper or RobotModelHelper()
        self.model_id = model_helper.model_id()
        self.limits: dict[str, JointLimit] = model_helper.joint_limits()

    def joint_names(self, pose_type: PoseType) -> tuple[str, ...]:
        if pose_type is PoseType.LEFT_ARM:
            return self.LEFT_ARM_JOINT_NAMES
        if pose_type is PoseType.RIGHT_ARM:
            return self.RIGHT_ARM_JOINT_NAMES
        return self.UPPER_BODY_JOINT_NAMES

    def group(self, joint_name: str) -> str:
        """waist, left_arm, right_arm or legs."""
        if joint_name in self.WAIST_JOINT_NAMES:
            return "waist"
        if joint_name in self.LEFT_ARM_JOINT_NAMES:
            return "left_arm"
        if joint_name in self.RIGHT_ARM_JOINT_NAMES:
            return "right_arm"
        return "legs"

    def check(self, pose_type: PoseType, joint_values: Mapping[str, float]) -> dict[str, float]:
        """Exactly the joints this pose type stores, each within its limit, in canonical order."""
        expected = self.joint_names(pose_type)
        if set(joint_values) != set(expected):
            missing = sorted(set(expected) - set(joint_values))
            extra = sorted(set(joint_values) - set(expected))
            raise ValueError(f"A {pose_type.value} pose needs exactly its joints (missing {missing}, extra {extra})")
        checked = self.check_some({name: joint_values[name] for name in expected})
        return checked

    def check_some(self, joint_values: Mapping[str, float]) -> dict[str, float]:
        """Any subset of known joints, each finite and within its limit."""
        checked = {}
        for name, value in joint_values.items():
            if name not in self.limits:
                raise ValueError(f"Unknown joint {name}")
            limit = self.limits[name]
            value = float(value)
            # A hair of tolerance: values read back from files and sliders round at the limit.
            if not math.isfinite(value) or not limit.lower - 1e-9 <= value <= limit.upper + 1e-9:
                raise ValueError(f"{name} = {value:.4f} rad is outside [{limit.lower}, {limit.upper}]")
            checked[name] = min(max(value, limit.lower), limit.upper)
        return checked


def demo_g1_joint_schema() -> None:
    schema = G1JointSchema()
    zeros = {name: 0.0 for name in schema.UPPER_BODY_JOINT_NAMES}
    logger.info("{}: {} joints, a base pose checks {} of them", schema.model_id, len(schema.limits),
                len(schema.check(PoseType.BASE, zeros)))
    try:
        schema.check_some({"left_elbow_joint": 3.0})
    except ValueError as error:
        logger.info("Out of range is refused: {}", error)


def main() -> None:
    use_utf8_output()
    demo_g1_joint_schema()


if __name__ == "__main__":
    main()
