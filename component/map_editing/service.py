"""Map editing: request -> mask -> erase / add obstacle -> command -> history."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import numpy as np
from loguru import logger

from component.map_editing.edit_history import EditCommand, EditHistory
from component.map_editing.ghost_removal import Erasure, GhostRemoval
from component.map_editing.obstacle_drawing import ObstacleDrawing
from component.map_editing.region import EditRegion, Region
from component.map_storage.service import MapDocument, MapStorage
from config.settings import MapEditConfig, use_utf8_output


class MapEditing:
    def __init__(self, **kwargs) -> None:
        self.region = EditRegion(**kwargs)
        self.ghost_removal = GhostRemoval(**kwargs)
        self.obstacle_drawing = ObstacleDrawing(**kwargs)
        self.history = EditHistory()

    def preview(self, document: MapDocument, request: dict, protected: np.ndarray | None = None) -> Erasure:
        """What an erase would hit. Obstacles change no points, so their preview is just the cells.
        protected is the protection zone (H×W bool), see map_inspection.protection."""
        region = self.region.build(document.grid, request["geometry"])
        if request["action"] == "obstacle":
            erasure = Erasure(map_idx=np.zeros(0, np.int64), ground_idx=np.zeros(0, np.int64), cells=region.cells)
            return erasure
        erasure = self.ghost_removal.select(document, region, request.get("params", {}), protected)
        return erasure

    def apply(self, document: MapDocument, request: dict, protected: np.ndarray | None = None) -> EditCommand | None:
        """A shape that covers no cell is a no-op and returns None."""
        region = self.region.build(document.grid, request["geometry"])
        if region.cells == 0:
            return None
        command = self._build_command(document, request, region, protected)
        self.history.execute(document, command)
        logger.info("Applied #{}: {}", command.id, command.summary)
        return command

    def undo(self, document: MapDocument) -> EditCommand | None:
        command = self.history.undo(document)
        return command

    def redo(self, document: MapDocument) -> EditCommand | None:
        command = self.history.redo(document)
        return command

    def jump(self, document: MapDocument, command_id: int) -> list[EditCommand]:
        moved = self.history.jump(document, command_id)
        return moved

    def entries(self) -> list[dict]:
        entries = self.history.entries()
        return entries

    def log_entries(self) -> list[dict]:
        """The applied commands without their pixel and index arrays, for edits.json."""
        entries = [{"id": command.id, "tool": command.tool, "action": command.action, "geometry": command.geometry,
                    "params": command.params, "summary": command.summary,
                    "map_points": len(command.map_idx), "ground_points": len(command.ground_idx)}
                   for command in self.history.done]
        return entries

    def _build_command(self, document: MapDocument, request: dict, region: Region,
                       protected: np.ndarray | None) -> EditCommand:
        params = request.get("params", {})
        if request["action"] == "erase":
            erasure = self.ghost_removal.select(document, region, params, protected)
            grid_after = self.ghost_removal.paint(document, region, params)
        else:
            erasure = Erasure(map_idx=np.zeros(0, np.int64), ground_idx=np.zeros(0, np.int64), cells=region.cells)
            grid_after = self.obstacle_drawing.paint(document, region)
        r0, r1, c0, c1 = region.bbox
        command = EditCommand(
            id=self.history.new_id(),
            tool=request["tool"],
            action=request["action"],
            geometry=request["geometry"],
            params=params,
            bbox=region.bbox,
            grid_before=document.grid.image[r0:r1, c0:c1].copy(),
            grid_after=grid_after,
            map_idx=erasure.map_idx,
            ground_idx=erasure.ground_idx,
            summary=self._summary(request, erasure),
        )
        return command

    @staticmethod
    def _summary(request: dict, erasure: Erasure) -> str:
        name = MapEditConfig.TOOL_NAMES[request["tool"]]
        if request["action"] == "obstacle":
            summary = f"{name} · grid {erasure.cells:,} cells"
            return summary
        if not request.get("params", {}).get("apply_to_pcd", True):
            summary = f"{name} · grid only · {erasure.cells:,} cells"
            return summary
        points = len(erasure.map_idx) + len(erasure.ground_idx)
        summary = (f"{name} · grid + points · {erasure.cells:,} cells · {points:,} points deleted"
                   f" (map {len(erasure.map_idx):,} / ground {len(erasure.ground_idx):,})")
        if erasure.protected_points:
            verb = "kept" if erasure.kept_protected else "incl."
            summary += f" · {verb} {erasure.protected_points:,} protected points"
        return summary


def demo_edit() -> None:
    """Erase the thick arc, draw a wall, undo both, redo both — all in memory, nothing saved."""
    document = MapStorage().load()
    editing = MapEditing()
    start_grid = document.grid.image.copy()
    erase = {"tool": "lasso_erase", "action": "erase",
             "geometry": {"polygon": [[-1.6, 5.3], [0.4, 5.3], [0.4, 7.3], [-1.6, 7.3]]}, "params": {}}
    wall = {"tool": "polyline_wall", "action": "obstacle",
            "geometry": {"polyline": [[0.0, 0.0], [3.0, 1.73]], "width_m": 0.10}}
    preview = editing.preview(document, erase)
    first = editing.apply(document, erase)
    second = editing.apply(document, wall)
    assert len(first.map_idx) == len(preview.map_idx)
    assert int(document.map_deleted.sum()) == len(first.map_idx)
    editing.undo(document)
    editing.undo(document)
    assert np.array_equal(document.grid.image, start_grid) and not document.map_deleted.any()
    editing.redo(document)
    editing.redo(document)
    assert editing.undo(document) is second
    assert editing.apply(document, {"tool": "lasso_erase", "action": "erase",
                                    "geometry": {"polygon": [[100, 100], [101, 100], [101, 101]]}}) is None
    for entry in editing.entries():
        logger.info("#{} {}{}", entry["id"], entry["summary"], " (undone)" if entry["undone"] else "")


def main() -> None:
    use_utf8_output()
    demo_edit()


if __name__ == "__main__":
    main()
