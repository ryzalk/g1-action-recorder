"""Library: list what is saved and what depends on what, delete to data/.trash, import and export."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from loguru import logger

from app.context import recorder_context
from component.common.g1_joint_schema import PoseType
from config.settings import use_utf8_output

router = APIRouter(prefix="/api/library", tags=["library"])


@router.get("")
def get_library() -> dict:
    listing = recorder_context.library()
    return listing


@router.delete("/poses/{pose_type}/{name}")
def delete_pose(pose_type: PoseType, name: str) -> dict:
    moved = recorder_context.delete_pose(pose_type, name)
    result = {"name": name, "trash": str(moved)}
    return result


@router.delete("/actions/{name}")
def delete_action(name: str) -> dict:
    recorder_context.delete_action(name)
    result = {"name": name}
    return result


@router.post("/poses/import")
async def import_pose(request: Request, filename: str, overwrite: bool = False) -> dict:
    """The raw .json file is the request body."""
    result = recorder_context.import_pose(filename, await request.body(), overwrite)
    return result


@router.get("/actions/export")
def export_actions(names: Annotated[list[str], Query(min_length=1)]) -> Response:
    """One zip for the actions named (?names=a&names=b): definitions, NPZs and every pose they need;
    Import action reads it back."""
    bundle = recorder_context.actions.export_bundle(names)
    filename = f"{names[0]}.zip" if len(names) == 1 else f"actions_{len(names)}_{datetime.now():%Y%m%d-%H%M%S}.zip"
    response = Response(bundle, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    return response


@router.get("/actions/{name}/export")
def export_action(name: str) -> Response:
    """The same zip for one action (Build action's Export .zip link)."""
    response = export_actions([name])
    return response


@router.post("/actions/import")
async def import_action(request: Request, filename: str, overwrite: bool = False) -> dict:
    """The raw .zip from Export is the request body."""
    result = recorder_context.import_action(filename, await request.body(), overwrite)
    return result


def demo_library_api() -> None:
    """Lists the library, exports an action and imports it back unchanged; nothing is written."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api_recorder.errors import register_error_handlers

    app = FastAPI()
    app.include_router(router)
    register_error_handlers(app)
    client = TestClient(app)
    listing = client.get("/api/library").json()
    logger.info("{} actions, poses {}", len(listing["actions"]),
                {pose_type: len(poses) for pose_type, poses in listing["poses"].items()})
    name = listing["actions"][0]["name"]
    bundle = client.get(f"/api/library/actions/{name}/export")
    logger.info("Export {}: {} bytes, {}", name, len(bundle.content), bundle.headers["content-disposition"])
    again = client.post("/api/library/actions/import", params={"filename": f"{name}.zip"}, content=bundle.content)
    logger.info("Import it back: {}", again.json())
    names = [action["name"] for action in listing["actions"]]
    everything = client.get("/api/library/actions/export", params={"names": names})
    logger.info("Export all {}: {:,} bytes, {}", len(names), len(everything.content),
                everything.headers["content-disposition"])
    home = client.delete(f"/api/library/poses/base/{listing['home']}")
    logger.info("Delete {}: {} {}", listing["home"], home.status_code, home.json()["detail"])


def main() -> None:
    use_utf8_output()
    demo_library_api()


if __name__ == "__main__":
    main()
