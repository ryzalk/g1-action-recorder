"""The shared player: play, pause, stop, seek, loop, import a file, save the paused frame as a pose."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import APIRouter, Request
from loguru import logger
from pydantic import BaseModel

from app.context import recorder_context
from component.common.g1_joint_schema import PoseType
from config.settings import use_utf8_output

router = APIRouter(prefix="/api/playback", tags=["playback"])


class Play(BaseModel):
    # Empty plays (or resumes) what is loaded; a name loads that saved action first.
    name: str = ""


class Seek(BaseModel):
    index: int


class Loop(BaseModel):
    enabled: bool


class Capture(BaseModel):
    pose_type: PoseType
    name: str
    overwrite: bool = False


@router.get("")
def get_playback() -> dict:
    snapshot = recorder_context.playback.snapshot()
    return snapshot


@router.post("/play")
def play(command: Play) -> dict:
    snapshot = recorder_context.play_saved(command.name) if command.name else recorder_context.playback.play()
    return snapshot


@router.post("/pause")
def pause() -> dict:
    snapshot = recorder_context.playback.pause()
    return snapshot


@router.post("/stop")
def stop() -> dict:
    snapshot = recorder_context.playback.stop()
    return snapshot


@router.post("/seek")
def seek(command: Seek) -> dict:
    snapshot = recorder_context.playback.seek(command.index)
    return snapshot


@router.post("/loop")
def loop(command: Loop) -> dict:
    snapshot = recorder_context.playback.set_loop(command.enabled)
    return snapshot


@router.post("/import")
async def import_file(request: Request, filename: str) -> dict:
    """The raw file is the request body; filename decides how it is read (.npz or .pkl)."""
    snapshot = recorder_context.import_motion(filename, await request.body())
    return snapshot


@router.post("/capture")
def capture(command: Capture) -> dict:
    pose = recorder_context.capture_pose(command.pose_type, command.name, command.overwrite)
    result = {"name": pose.name, "pose_type": pose.pose_type.value, "notes": pose.notes}
    return result


def demo_playback_api() -> None:
    """Imports a saved NPZ as a file, plays, pauses and seeks; saves nothing."""
    import time

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from config.settings import PathConfig

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    path = PathConfig.DATA_DIR / "actions" / "trajectories" / "concierge_wave_left.npz"
    loaded = client.post("/api/playback/import", params={"filename": path.name}, content=path.read_bytes()).json()
    logger.info("Imported {} as {}", loaded["name"], loaded["source"])
    client.post("/api/playback/play", json={})
    time.sleep(0.5)
    logger.info("Paused at {}", client.post("/api/playback/pause").json()["index"])
    logger.info("Seek -> {}", client.post("/api/playback/seek", json={"index": 70}).json()["phase"])


def main() -> None:
    use_utf8_output()
    demo_playback_api()


if __name__ == "__main__":
    main()
