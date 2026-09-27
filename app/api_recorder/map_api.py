"""Map: open or upload a G1 map, the 2D layers, edits with preview, undo and redo, candidates, save and zip."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from typing import Literal

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel, Field

from app.context import recorder_context
from config.settings import MapCloudConfig, MapInspectionConfig, use_utf8_output

router = APIRouter(prefix="/api/map", tags=["map"])

Tool = Literal["lasso_erase", "rect_erase", "brush_erase", "polyline_wall", "polygon_fill", "rect_fill",
               "obstacle_brush", "candidate_erase", "candidate_fill"]


class Geometry(BaseModel):
    """A closed polygon, or a polyline drawn width_m wide (walls and brushes); metres in the map frame."""

    polygon: list[tuple[float, float]] | None = None
    polyline: list[tuple[float, float]] | None = None
    width_m: float | None = Field(default=None, gt=0, le=5)


class EditParams(BaseModel):
    grid_value: Literal[254, 205] = 254
    apply_to_pcd: bool = True
    keep_protected: bool = True
    z_range_rel: tuple[float, float] = MapCloudConfig.ERASE_Z_RANGE_REL
    ground_z_range_rel: tuple[float, float] = MapCloudConfig.GROUND_ERASE_Z_RANGE_REL


class Edit(BaseModel):
    tool: Tool
    action: Literal["erase", "obstacle"]
    geometry: Geometry
    params: EditParams = EditParams()

    def request(self) -> dict:
        """The plain dict the map blocks take; unset geometry keys are left out."""
        request = {"tool": self.tool, "action": self.action, "geometry": self.geometry.model_dump(exclude_none=True),
                   "params": self.params.model_dump()}
        return request


class OpenMap(BaseModel):
    folder: str


class SceneLayer(BaseModel):
    name: Literal["map", "ground", "grid"]
    visible: bool


class Focus(BaseModel):
    x: float
    y: float
    distance: float = Field(default=6.0, gt=0, le=100)


def png_response(png: bytes) -> Response:
    # no-store: the same URL returns a different picture after every edit.
    response = Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})
    return response


@router.get("")
def map_info() -> dict:
    info = recorder_context.map.map_info()
    return info


@router.get("/maps")
def list_maps() -> dict:
    listing = recorder_context.map.maps()
    return listing


@router.post("/maps/open")
def open_map(command: OpenMap) -> dict:
    opened = recorder_context.map.open_map(command.folder)
    return opened


@router.post("/maps/upload")
async def upload_map(request: Request) -> dict:
    """The body is the .zip of a map folder itself; it is unpacked into a new folder and opened."""
    opened = recorder_context.map.upload_map(await request.body())
    return opened


@router.get("/grid.png")
def grid_png(which: Literal["current", "original"] = "current") -> Response:
    response = png_response(recorder_context.map.grid_png(which))
    return response


@router.get("/projection.png")
def projection_png(z_lo: float = MapCloudConfig.PROJECTION_Z_RANGE_REL[0],
                   z_hi: float = MapCloudConfig.PROJECTION_Z_RANGE_REL[1],
                   source: Literal["map", "ground"] = "map") -> Response:
    """z_lo / z_hi are metres above the floor."""
    response = png_response(recorder_context.map.projection_png(z_lo, z_hi, source))
    return response


@router.get("/diff.png")
def diff_png() -> Response:
    response = png_response(recorder_context.map.diff_png())
    return response


@router.get("/protection.png")
def protection_png() -> Response:
    response = png_response(recorder_context.map.protection_png())
    return response


@router.post("/scene/layer")
def scene_layer(command: SceneLayer) -> dict:
    layers = recorder_context.map.set_scene_layer(command.name, command.visible)
    return layers


@router.post("/edit/preview")
def preview_edit(edit: Edit) -> dict:
    preview = recorder_context.map.preview(edit.request())
    return preview


@router.post("/edit/cancel")
def cancel_edit() -> dict:
    recorder_context.map.cancel_preview()
    return {}


@router.post("/edit")
def apply_edit(edit: Edit) -> dict:
    result = recorder_context.map.apply(edit.request())
    return result


@router.post("/undo")
def undo() -> dict:
    result = recorder_context.map.undo()
    return result


@router.post("/redo")
def redo() -> dict:
    result = recorder_context.map.redo()
    return result


@router.get("/history")
def history() -> dict:
    state = recorder_context.map.history()
    return state


@router.post("/history/jump/{command_id}")
def jump(command_id: int) -> dict:
    """Undo or redo to just after command_id; 0 goes back to before the first edit."""
    result = recorder_context.map.jump(command_id)
    return result


@router.post("/restore")
def restore() -> dict:
    """Puts the *.orig.* files back (the replaced version goes to .backup) and reloads."""
    result = recorder_context.map.restore()
    return result


@router.post("/save")
def save() -> dict:
    """Writes the map folder (with backups) and zips its files for the page to download."""
    result = recorder_context.map.save()
    result["package_url"] = f"/api/map/package/{Path(result['package_path']).name}"
    return result


@router.get("/package/{name}")
def package(name: str) -> FileResponse:
    """An exported map zip; only a file directly inside the export folder."""
    path = recorder_context.map.package_dir / Path(name).name
    if not path.is_file():
        raise FileNotFoundError(f"No exported map named {name}")
    response = FileResponse(path, filename=path.name, media_type="application/octet-stream")
    return response


@router.post("/focus")
def focus(command: Focus) -> dict:
    recorder_context.map.focus(command.x, command.y, command.distance)
    return {}


@router.get("/candidates")
def candidates(z_lo: float = MapInspectionConfig.CANDIDATE_Z_RANGE_REL[0],
               z_hi: float = MapInspectionConfig.CANDIDATE_Z_RANGE_REL[1],
               min_points: int = Query(default=MapInspectionConfig.CANDIDATE_MIN_POINTS, ge=1),
               min_cells: int = Query(default=MapInspectionConfig.CANDIDATE_MIN_CELLS, ge=1)) -> list[dict]:
    """z_lo / z_hi metres above the floor, min_points per cell, min_cells per candidate."""
    found = recorder_context.map.candidates(z_range_rel=(z_lo, z_hi), min_points=min_points, min_cells=min_cells)
    return found


def demo_map_api() -> None:
    """On a copy of the sample map under output/demo/map: open, layers, preview, apply, undo, candidates, save."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api_recorder.errors import register_error_handlers
    from component.map_session.service import open_demo_copy

    app = FastAPI()
    app.include_router(router)
    register_error_handlers(app)
    client = TestClient(app)
    open_demo_copy(recorder_context.map, "map_api")
    info = client.get("/api/map").json()
    logger.info("{} {}×{}, {} tour points", info["map_id"], info["width"], info["height"], len(info["tour_points"]))
    for url in ("/api/map/grid.png", "/api/map/projection.png?source=ground", "/api/map/diff.png"):
        logger.info("{} -> {} bytes", url, len(client.get(url).content))
    erase = {"tool": "brush_erase", "action": "erase",
             "geometry": {"polyline": [[0.5, 3.5], [0.5, 8.0]], "width_m": 0.6}}
    logger.info("Preview {}", client.post("/api/map/edit/preview", json=erase).json())
    logger.info("Applied {}", client.post("/api/map/edit", json=erase).json()["command"]["summary"])
    logger.info("Undo {}", client.post("/api/map/undo").json()["command"]["id"])
    logger.info("{} candidates", len(client.get("/api/map/candidates").json()))
    saved = client.post("/api/map/save").json()
    logger.info("Saved; download {} -> {}", saved["package_url"], client.get(saved["package_url"]).status_code)
    logger.info("Bad tool -> {}", client.post("/api/map/edit", json={**erase, "tool": "nope"}).status_code)


def main() -> None:
    use_utf8_output()
    demo_map_api()


if __name__ == "__main__":
    main()
