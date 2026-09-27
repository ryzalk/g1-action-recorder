"""Record pose and Compose pose."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import APIRouter
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel

from app.context import recorder_context
from component.common.g1_joint_schema import PoseType
from config.settings import RobotConfig, use_utf8_output

router = APIRouter(prefix="/api/poses", tags=["poses"])


class SavePose(BaseModel):
    pose_type: PoseType
    name: str
    joint_positions: dict[str, float]
    overwrite: bool = False


class MirrorArm(BaseModel):
    source: PoseType
    joint_positions: dict[str, float]


class Composition(BaseModel):
    base: str
    left_arm: str = ""
    right_arm: str = ""
    name: str = ""
    overwrite: bool = False


@router.get("")
def list_poses() -> dict:
    result = {"names": recorder_context.poses.names(), "home": RobotConfig.HOME_POSE_NAME,
              "home_values": recorder_context.home_values()}
    return result


@router.get("/{pose_type}/{name}")
def get_pose(pose_type: PoseType, name: str) -> dict:
    pose = recorder_context.poses.load(pose_type, name)
    result = pose.to_dict(recorder_context.schema.model_id)
    return result


@router.get("/{pose_type}/{name}/preview.png")
def pose_preview(pose_type: PoseType, name: str) -> FileResponse:
    """The picture saved with the pose (data/poses/<type>/<name>.png)."""
    path = recorder_context.pose_picture(pose_type, name)
    response = FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    return response


@router.post("/{pose_type}/{name}/show")
def show_pose(pose_type: PoseType, name: str) -> dict:
    pose = recorder_context.show_pose(pose_type, name)
    result = {"joint_values": pose.joint_values, "source_parts": pose.source_parts}
    return result


@router.post("")
def save_pose(command: SavePose) -> dict:
    pose = recorder_context.save_recorded_pose(command.pose_type, command.name, command.joint_positions,
                                               command.overwrite)
    result = {"name": pose.name, "pose_type": pose.pose_type.value}
    return result


@router.post("/mirror")
def mirror_arm(command: MirrorArm) -> dict:
    mirrored = recorder_context.mirror_arm(command.source, command.joint_positions)
    result = {"joint_positions": mirrored}
    return result


@router.post("/compose/preview")
def preview_composition(command: Composition) -> dict:
    pose = recorder_context.preview_composition(command.base, command.left_arm, command.right_arm)
    result = {"joint_values": pose.joint_values}
    return result


@router.post("/compose")
def save_composition(command: Composition) -> dict:
    pose = recorder_context.save_composition(command.name, command.base, command.left_arm, command.right_arm,
                                             command.overwrite)
    result = {"name": pose.name, "pose_type": pose.pose_type.value, "source_parts": pose.source_parts}
    return result


def demo_pose_api() -> None:
    """Read-only calls against the real data."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    names = client.get("/api/poses").json()["names"]
    logger.info("Poses: {}", {pose_type: len(items) for pose_type, items in names.items()})
    preview = client.post("/api/poses/compose/preview", json={"base": RobotConfig.HOME_POSE_NAME,
                                                              "left_arm": names["left_arm"][0]})
    logger.info("Compose preview -> {} joints", len(preview.json()["joint_values"]))


def main() -> None:
    use_utf8_output()
    demo_pose_api()


if __name__ == "__main__":
    main()
