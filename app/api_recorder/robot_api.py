"""Robot state and the 3D camera. The WebSocket pushes state and playback, and takes slider moves."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel

from app.context import recorder_context
from config.settings import ViewerConfig, use_utf8_output

router = APIRouter(prefix="/api/robot", tags=["robot"])


class JointCommand(BaseModel):
    joint_positions: dict[str, float]


@router.get("")
def get_robot() -> dict:
    state = recorder_context.robot.snapshot()
    return state


@router.put("/joints")
def put_joints(command: JointCommand) -> dict:
    revision = recorder_context.move_joints(command.joint_positions)
    result = {"revision": revision}
    return result


@router.post("/camera/{view}")
def set_camera(view: str) -> dict:
    if view not in ViewerConfig.CAMERA_AZIMUTHS:
        raise ValueError(f"Unknown view {view}; use one of {list(ViewerConfig.CAMERA_AZIMUTHS)}")
    result = {"view": view, "clients": recorder_context.display.set_view(view)}
    return result


@router.websocket("/ws")
async def robot_socket(websocket: WebSocket) -> None:
    """Sends {"type": "robot"} and {"type": "playback"} when they change; receives {"joint_positions": ...}."""
    await websocket.accept()
    sent_robot = sent_playback = -1
    try:
        while True:
            robot = recorder_context.robot.snapshot()
            if robot["revision"] != sent_robot:
                sent_robot = robot["revision"]
                await websocket.send_json({"type": "robot", **robot})
            playback = recorder_context.playback.snapshot()
            if playback["revision"] != sent_playback:
                sent_playback = playback["revision"]
                await websocket.send_json({"type": "playback", **playback})
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=0.05)
            except asyncio.TimeoutError:
                continue
            try:
                recorder_context.move_joints(message["joint_positions"])
            except (KeyError, ValueError) as error:
                await websocket.send_json({"type": "error", "detail": str(error)})
    except WebSocketDisconnect:
        return


def demo_robot_api() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    moved = client.put("/api/robot/joints", json={"joint_positions": {"left_elbow_joint": 1.0}})
    logger.info("PUT joints -> {}", moved.json())
    with client.websocket_connect("/api/robot/ws") as socket:
        first = socket.receive_json()
        logger.info("WS first message: {} revision {}", first["type"], first["revision"])


def main() -> None:
    use_utf8_output()
    demo_robot_api()


if __name__ == "__main__":
    main()
