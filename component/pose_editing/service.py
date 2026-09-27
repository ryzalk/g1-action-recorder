"""Saved poses: data/poses/<pose_type>/<name>.json, plus composing and mirroring them."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import json
from collections.abc import Mapping

from loguru import logger

from component.common.g1_joint_schema import G1JointSchema, PoseType
from component.common.naming import clean_name
from component.common.pose import Pose
from config.settings import PathConfig, RobotConfig, use_utf8_output
from util.data_file_helper import DataFileHelper

# Reflection across the robot's sagittal plane: pitch-like joints keep their sign, roll/yaw flip.
MIRROR_SIGNS = {"shoulder_pitch": 1.0, "shoulder_roll": -1.0, "shoulder_yaw": -1.0, "elbow": 1.0,
                "wrist_roll": -1.0, "wrist_pitch": 1.0, "wrist_yaw": -1.0}


class PoseService:
    def __init__(self, schema: G1JointSchema, pose_dir: Path = PathConfig.DATA_DIR / "poses") -> None:
        self.schema = schema
        self.pose_dir = pose_dir
        self.files = DataFileHelper()

    def names(self) -> dict[str, list[str]]:
        names = {pose_type.value: self.files.list_names(self.pose_dir / pose_type.value, ".json")
                 for pose_type in PoseType}
        return names

    def load(self, pose_type: PoseType, name: str) -> Pose:
        path = self._path(pose_type, name)
        if not path.exists():
            raise FileNotFoundError(f"No {pose_type.value} pose named {name}")
        pose = Pose.from_dict(self.files.read_json(path))
        pose.joint_values = self.schema.check(pose_type, pose.joint_values)
        return pose

    def save(self, pose: Pose, overwrite: bool = False) -> Path:
        pose.name = clean_name(pose.name)
        pose.joint_values = self.schema.check(pose.pose_type, pose.joint_values)
        payload = pose.to_dict(self.schema.model_id)
        path = self.files.write_json(self._path(pose.pose_type, pose.name), payload, overwrite)
        logger.info("Saved pose {}", path)
        return path

    def home(self) -> Pose:
        """The pose every action starts and ends at; all zeros if it hasn't been saved yet."""
        if self._path(PoseType.BASE, RobotConfig.HOME_POSE_NAME).exists():
            pose = self.load(PoseType.BASE, RobotConfig.HOME_POSE_NAME)
            return pose
        logger.warning("No saved {} pose; starting from all zeros", RobotConfig.HOME_POSE_NAME)
        zeros = {name: 0.0 for name in self.schema.UPPER_BODY_JOINT_NAMES}
        pose = Pose(RobotConfig.HOME_POSE_NAME, PoseType.BASE, zeros)
        return pose

    def compose(self, name: str, base: str, left_arm: str = "", right_arm: str = "") -> Pose:
        """A whole-body pose, with either arm optionally swapped for a saved arm pose."""
        values = dict(self.load(PoseType.BASE, base).joint_values)
        parts = {"base": base}
        for pose_type, part in ((PoseType.LEFT_ARM, left_arm), (PoseType.RIGHT_ARM, right_arm)):
            if part:
                values.update(self.load(pose_type, part).joint_values)
                parts[pose_type.value] = part
        pose = Pose(name, PoseType.COMPOSED, values, source="composition", source_parts=parts)
        return pose

    def mirror(self, source: PoseType, joint_values: Mapping[str, float]) -> dict[str, float]:
        """One arm's values reflected onto the other arm, keyed by the other arm's joints."""
        source_side, target_side = ("left", "right") if source is PoseType.LEFT_ARM else ("right", "left")
        mirrored = {f"{target_side}_{part}_joint": sign * joint_values[f"{source_side}_{part}_joint"]
                    for part, sign in MIRROR_SIGNS.items()}
        checked = self.schema.check_some(mirrored)
        return checked

    def exists(self, pose_type: PoseType, name: str) -> bool:
        found = self._path(pose_type, name).exists()
        return found

    def matches(self, pose: Pose) -> bool:
        """Whether the saved pose of the same type and name has the same joint values."""
        saved = self.load(pose.pose_type, pose.name).joint_values
        same = all(abs(saved[joint] - value) < 1e-9 for joint, value in pose.joint_values.items())
        return same

    def parse(self, content: bytes, filename: str = "file") -> Pose:
        """A pose read from a file somewhere else, checked like one of ours but not saved."""
        # Picking the wrong JSON is the usual mistake; name the file rather than a bare missing key.
        try:
            payload = json.loads(content.decode("utf-8"))
            pose = Pose.from_dict(payload)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ValueError(f"{filename} isn't a pose file") from error
        if payload.get("robot_model_id") != self.schema.model_id:
            raise ValueError(f"{filename} is a pose for {payload.get('robot_model_id')}, not {self.schema.model_id}")
        pose.name = clean_name(pose.name)
        pose.joint_values = self.schema.check(pose.pose_type, pose.joint_values)
        return pose

    def compositions(self) -> list[dict]:
        """Every pose saved from Compose (any type) and the parts it was made from: {pose_type, name, source_parts}."""
        made = [{"pose_type": pose_type, "name": name, "source_parts": pose.source_parts}
                for pose_type, names in self.names().items() for name in names
                if (pose := self.load(PoseType(pose_type), name)).source == "composition"]
        return made

    def parts(self) -> dict[tuple[PoseType, str], list[str]]:
        """Which poses made in Compose each pose went into; they hold copied values, so this is history only."""
        used = {}
        for made in self.compositions():
            for part_type, part_name in made["source_parts"].items():
                used.setdefault((PoseType(part_type), part_name), []).append(made["name"])
        return used

    def picture_path(self, pose_type: PoseType, name: str) -> Path:
        """The pose's picture, beside its file."""
        path = self._path(pose_type, name).with_suffix(".png")
        return path

    def delete(self, pose_type: PoseType, name: str, trash_dir: Path) -> Path:
        """Moves the file (and its picture) into trash_dir, keeping its poses/<type>/ path there."""
        path = self._path(pose_type, name)
        if not path.exists():
            raise FileNotFoundError(f"No {pose_type.value} pose named {name}")
        picture = self.picture_path(pose_type, name)
        if picture.exists():
            self.files.move(picture, trash_dir / "poses" / pose_type.value / picture.name)
        moved = self.files.move(path, trash_dir / "poses" / pose_type.value / path.name)
        logger.info("Moved pose {} to {}", path, moved)
        return moved

    def _path(self, pose_type: PoseType, name: str) -> Path:
        path = self.pose_dir / pose_type.value / f"{clean_name(name)}.json"
        return path


def demo_pose_service() -> None:
    """Reads the real poses; writes only to output/demo."""
    service = PoseService(G1JointSchema())
    logger.info("Saved poses: {}", {pose_type: len(names) for pose_type, names in service.names().items()})
    home = service.home()
    left_arms = service.names()["left_arm"]
    composed = service.compose("demo_composed", home.name, left_arm=left_arms[0] if left_arms else "")
    logger.info("Composed from {}", composed.source_parts)
    mirrored = service.mirror(PoseType.LEFT_ARM, {name: composed.joint_values[name]
                                                  for name in service.schema.LEFT_ARM_JOINT_NAMES})
    logger.info("Mirrored right shoulder roll {:.3f}", mirrored["right_shoulder_roll_joint"])
    demo_service = PoseService(service.schema, PathConfig.DEMO_DIR / "poses")
    logger.info("Wrote {}", demo_service.save(composed, overwrite=True))
    path = demo_service._path(PoseType.COMPOSED, "demo_composed")
    parsed = demo_service.parse(path.read_bytes(), path.name)
    logger.info("Parsed back {}; same as saved: {}", parsed.name, demo_service.matches(parsed))
    logger.info("Parts of real poses: {} entries", len(service.parts()))
    moved = demo_service.delete(PoseType.COMPOSED, "demo_composed", PathConfig.DEMO_DIR / "trash")
    logger.info("Deleted to {}", moved)


def main() -> None:
    use_utf8_output()
    demo_pose_service()


if __name__ == "__main__":
    main()
