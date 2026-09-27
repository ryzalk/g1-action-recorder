"""A saved pose: named joint values of one pose type, stored as schema-1 JSON."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dataclasses import dataclass, field
from datetime import datetime, timezone

from loguru import logger

from component.common.g1_joint_schema import PoseType
from config.settings import use_utf8_output


def utc_now() -> datetime:
    now = datetime.now(timezone.utc)
    return now


def utc_text(moment: datetime) -> str:
    text = moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return text


def parse_utc(text: str) -> datetime:
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment


@dataclass
class Pose:
    name: str
    pose_type: PoseType
    joint_values: dict[str, float]
    # simulation, mirror, composition, robot: where the values came from.
    source: str = "simulation"
    source_parts: dict[str, str] = field(default_factory=dict)
    notes: str = ""
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self, model_id: str) -> dict:
        payload = {
            "schema_version": 1,
            "name": self.name,
            "pose_type": self.pose_type.value,
            "robot_model_id": model_id,
            "joint_values": self.joint_values,
            "source": self.source,
            "created_at": utc_text(self.created_at),
            "source_parts": self.source_parts,
            "notes": self.notes,
        }
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> Pose:
        pose = cls(name=payload["name"], pose_type=PoseType(payload["pose_type"]),
                   joint_values={name: float(value) for name, value in payload["joint_values"].items()},
                   source=payload.get("source", "simulation"), source_parts=payload.get("source_parts", {}),
                   notes=payload.get("notes", ""), created_at=parse_utc(payload["created_at"]))
        return pose


def demo_pose() -> None:
    pose = Pose("wave_up", PoseType.LEFT_ARM, {"left_elbow_joint": 1.0})
    restored = Pose.from_dict(pose.to_dict("demo_model"))
    logger.info("{} round trip equal: {}", restored.name, restored == pose)


def main() -> None:
    use_utf8_output()
    demo_pose()


if __name__ == "__main__":
    main()
