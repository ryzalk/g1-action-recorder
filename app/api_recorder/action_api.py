"""Build action: open, preview, save (JSON + compiled NPZ together), download the NPZ."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import APIRouter
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel, Field

from app.context import recorder_context
from config.settings import ActionConfig, RobotConfig, use_utf8_output

router = APIRouter(prefix="/api/actions", tags=["actions"])


class Step(BaseModel):
    pose_type: str
    pose_name: str
    move_seconds: float = Field(gt=0)
    hold_seconds: float = Field(default=0.0, ge=0)


class ActionDraft(BaseModel):
    name: str = ""
    steps: list[Step]
    return_seconds: float = Field(gt=0)
    sample_hz: float = Field(default=ActionConfig.SAMPLE_HZ, gt=0)
    overwrite: bool = False


@router.get("")
def list_actions() -> dict:
    """Saved actions, and the whole-body poses a step can use."""
    names = recorder_context.poses.names()
    choices = [{"pose_type": "base", "pose_name": name} for name in names["base"] if name != RobotConfig.HOME_POSE_NAME]
    choices += [{"pose_type": "composed", "pose_name": name} for name in names["composed"]]
    result = {"actions": recorder_context.actions.names(), "compiled": recorder_context.actions.trajectory_names(),
              "choices": choices, "home": RobotConfig.HOME_POSE_NAME, "sample_hz": ActionConfig.SAMPLE_HZ,
              "default_move_seconds": ActionConfig.DEFAULT_TRAVEL_SECONDS}
    return result


@router.get("/{name}")
def open_action(name: str) -> dict:
    editor = recorder_context.open_action(name)
    return editor


@router.post("/preview")
def preview_action(draft: ActionDraft) -> dict:
    snapshot = recorder_context.preview_action(draft.name, [step.model_dump() for step in draft.steps],
                                               draft.return_seconds, draft.sample_hz)
    return snapshot


@router.post("")
def save_action(draft: ActionDraft) -> dict:
    trajectory = recorder_context.save_action(draft.name, [step.model_dump() for step in draft.steps],
                                              draft.return_seconds, draft.sample_hz, draft.overwrite)
    result = {"name": trajectory.name, "samples": trajectory.sample_count, "seconds": trajectory.duration,
              "npz_url": f"/api/actions/{trajectory.name}/npz",
              "export_url": f"/api/library/actions/{trajectory.name}/export"}
    return result


@router.get("/{name}/npz")
def download_npz(name: str) -> FileResponse:
    path = recorder_context.actions.trajectory_path(name)
    if not path.exists():
        raise FileNotFoundError(f"{name} has no compiled NPZ; save it first")
    response = FileResponse(path, filename=path.name, media_type="application/octet-stream")
    return response


def demo_action_api() -> None:
    """Opens and previews a saved action; saves nothing."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    listing = client.get("/api/actions").json()
    name = listing["actions"][0]
    editor = client.get(f"/api/actions/{name}").json()
    logger.info("Opened {}: {} steps", name, len(editor["steps"]))
    preview = client.post("/api/actions/preview", json=editor).json()
    logger.info("Preview: {} samples, {}", preview["count"], preview["state"])
    logger.info("NPZ download {}", client.get(f"/api/actions/{name}/npz").status_code)


def main() -> None:
    use_utf8_output()
    demo_action_api()


if __name__ == "__main__":
    main()
