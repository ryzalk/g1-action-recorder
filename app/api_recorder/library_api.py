"""Library: list what is saved and what depends on what, delete to data/.trash, import and export."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import APIRouter, Request, Response
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


@router.get("/actions/{name}/export")
def export_action(name: str) -> Response:
    """A zip of the action, its NPZ and every pose it needs; Import action reads it back."""
    bundle = recorder_context.actions.export_bundle(name)
    response = Response(bundle, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})
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
    home = client.delete(f"/api/library/poses/base/{listing['home']}")
    logger.info("Delete {}: {} {}", listing["home"], home.status_code, home.json()["detail"])


def main() -> None:
    use_utf8_output()
    demo_library_api()


if __name__ == "__main__":
    main()
