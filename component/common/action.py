"""An action (ordered poses with timing, schema-1 JSON) and its sampled trajectory (schema-2 NPZ)."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime

import numpy as np
from loguru import logger

from component.common.g1_joint_schema import PoseType
from component.common.pose import parse_utc, utc_now, utc_text
from config.settings import RobotConfig, use_utf8_output


@dataclass
class ActionStep:
    """Move into a pose over move_seconds, then stay there for hold_seconds."""

    pose_type: PoseType
    pose_name: str
    move_seconds: float
    hold_seconds: float = 0.0


@dataclass
class Action:
    """Starts at the home pose; the last step always returns to it."""

    name: str
    steps: list[ActionStep]
    notes: str = ""
    created_at: datetime = field(default_factory=utc_now)

    @property
    def total_seconds(self) -> float:
        total = sum(step.move_seconds + step.hold_seconds for step in self.steps)
        return total

    def to_dict(self, model_id: str) -> dict:
        payload = {
            "schema_version": 1,
            "name": self.name,
            "robot_model_id": model_id,
            "initial_pose": {"pose_type": PoseType.BASE.value, "name": RobotConfig.HOME_POSE_NAME},
            "transitions": [{"target_pose": {"pose_type": step.pose_type.value, "name": step.pose_name},
                             "duration_seconds": step.move_seconds, "hold_seconds": step.hold_seconds}
                            for step in self.steps],
            "created_at": utc_text(self.created_at),
            "notes": self.notes,
        }
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> Action:
        steps = [ActionStep(PoseType(item["target_pose"]["pose_type"]), item["target_pose"]["name"],
                            float(item["duration_seconds"]), float(item.get("hold_seconds", 0.0)))
                 for item in payload["transitions"]]
        action = cls(payload["name"], steps, payload.get("notes", ""), parse_utc(payload["created_at"]))
        return action


@dataclass
class Trajectory:
    """Time-sampled joint positions. keyframe_indices[i] is where keyframe_names[i] is reached."""

    name: str
    joint_names: tuple[str, ...]
    timestamps: np.ndarray
    joint_positions: np.ndarray
    keyframe_indices: tuple[int, ...]
    keyframe_names: tuple[str, ...]
    keyframe_holds: tuple[float, ...]
    fps: float
    max_tracking_error: float = 0.0

    @property
    def sample_count(self) -> int:
        count = len(self.timestamps)
        return count

    @property
    def duration(self) -> float:
        seconds = float(self.timestamps[-1])
        return seconds

    def values_at(self, index: int) -> dict[str, float]:
        values = dict(zip(self.joint_names, (float(value) for value in self.joint_positions[index]), strict=True))
        return values

    def only(self, joint_names: Sequence[str]) -> Trajectory:
        """The same samples restricted to some joints."""
        columns = [self.joint_names.index(name) for name in joint_names]
        subset = replace(self, joint_names=tuple(joint_names), joint_positions=self.joint_positions[:, columns])
        return subset

    def to_arrays(self, model_id: str) -> dict[str, np.ndarray]:
        arrays = {
            "schema_version": np.asarray(2, dtype=np.int64),
            "action_name": np.asarray(self.name),
            "robot_model_id": np.asarray(model_id),
            "fps": np.asarray(self.fps, dtype=np.float64),
            "joint_names": np.asarray(self.joint_names),
            "timestamps": np.asarray(self.timestamps, dtype=np.float64),
            "joint_positions": np.asarray(self.joint_positions, dtype=np.float64),
            "keyframe_sample_indices": np.asarray(self.keyframe_indices, dtype=np.int64),
            "source_pose_names": np.asarray(self.keyframe_names),
            "keyframe_hold_seconds": np.asarray(self.keyframe_holds, dtype=np.float64),
            "max_tracking_error": np.asarray(self.max_tracking_error, dtype=np.float64),
        }
        return arrays

    @classmethod
    def from_arrays(cls, arrays: dict[str, np.ndarray]) -> Trajectory:
        if int(arrays["schema_version"]) != 2:
            raise ValueError(f"Unsupported trajectory schema {int(arrays['schema_version'])}; expected 2")
        trajectory = cls(name=str(arrays["action_name"]),
                         joint_names=tuple(str(name) for name in arrays["joint_names"]),
                         timestamps=np.asarray(arrays["timestamps"], dtype=np.float64),
                         joint_positions=np.asarray(arrays["joint_positions"], dtype=np.float64),
                         keyframe_indices=tuple(int(index) for index in arrays["keyframe_sample_indices"]),
                         keyframe_names=tuple(str(name) for name in arrays["source_pose_names"]),
                         keyframe_holds=tuple(float(hold) for hold in arrays["keyframe_hold_seconds"]),
                         fps=float(arrays["fps"]), max_tracking_error=float(arrays["max_tracking_error"]))
        return trajectory


def demo_action() -> None:
    action = Action("wave", [ActionStep(PoseType.COMPOSED, "wave_up", 1.0, 0.5),
                             ActionStep(PoseType.BASE, RobotConfig.HOME_POSE_NAME, 1.0)])
    restored = Action.from_dict(action.to_dict("demo_model"))
    logger.info("{}: {} steps, {:.1f} s, round trip equal: {}", restored.name, len(restored.steps),
                restored.total_seconds, restored == action)
    trajectory = Trajectory("wave", ("a", "b"), np.asarray([0.0, 0.5, 1.0]), np.zeros((3, 2)), (0, 1, 2),
                            ("home", "up", "home"), (0.0, 0.0, 0.0), 2.0)
    restored_trajectory = Trajectory.from_arrays(trajectory.to_arrays("demo_model"))
    logger.info("Trajectory {} samples, {:.1f} s, columns of b: {}", restored_trajectory.sample_count,
                restored_trajectory.duration, restored_trajectory.only(["b"]).joint_positions.shape)


def main() -> None:
    use_utf8_output()
    demo_action()


if __name__ == "__main__":
    main()
