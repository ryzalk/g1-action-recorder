"""Read joint limits and the model id from the pinned G1 model files."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import json
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass

from loguru import logger

from config.settings import PathConfig, use_utf8_output


@dataclass
class JointLimit:
    lower: float
    upper: float
    velocity: float


class RobotModelHelper:
    def __init__(self, urdf_path: Path = PathConfig.URDF_PATH, **kwargs) -> None:
        self.urdf_path = urdf_path
        self.mjcf_path = kwargs.get("mjcf_path", PathConfig.MJCF_PATH)
        self.metadata_path = kwargs.get("metadata_path", PathConfig.METADATA_PATH)

    def model_id(self) -> str:
        metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        model_id = str(metadata["model_id"])
        return model_id

    def joint_limits(self) -> dict[str, JointLimit]:
        """Movable URDF joints in file order."""
        root = ElementTree.parse(self.urdf_path).getroot()
        limits = {}
        for joint in root.iter("joint"):
            if joint.get("type") not in ("revolute", "prismatic"):
                continue
            limit = joint.find("limit")
            limits[joint.get("name")] = JointLimit(float(limit.get("lower")), float(limit.get("upper")),
                                                   float(limit.get("velocity")))
        return limits

    def mjcf_joint_names(self) -> list[str]:
        """Hinge joints in the MJCF, skipping the floating base."""
        root = ElementTree.parse(self.mjcf_path).getroot()
        names = [joint.get("name") for joint in root.find("worldbody").iter("joint") if joint.get("type") != "free"]
        return names


def demo_robot_model_helper() -> None:
    helper = RobotModelHelper()
    limits = helper.joint_limits()
    logger.info("{}: {} URDF joints, {} MJCF joints", helper.model_id(), len(limits), len(helper.mjcf_joint_names()))
    logger.info("left_elbow_joint {}", limits["left_elbow_joint"])


def main() -> None:
    use_utf8_output()
    demo_robot_model_helper()


if __name__ == "__main__":
    main()
