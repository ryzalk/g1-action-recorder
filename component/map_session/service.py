"""Everything the Map page can do with a map.

The web layer holds one of these and calls it, so no business rule lives in
the routes.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import threading
from datetime import datetime

import numpy as np
from loguru import logger

from component.map_display.service import MapDisplay
from component.map_editing.edit_history import EditCommand
from component.map_editing.service import MapEditing
from component.map_inspection.service import MapInspection
from component.map_storage.service import MapStorage, copy_map
from config.settings import (
    MapCloudConfig,
    MapEditConfig,
    MapGridConfig,
    MapInspectionConfig,
    MapPathConfig,
    use_utf8_output,
)


class MapSession:
    def __init__(self, **kwargs) -> None:
        self.storage = MapStorage(**kwargs)
        self.editing = MapEditing(**kwargs)
        self.display = MapDisplay(**kwargs)
        self.inspection = MapInspection(**kwargs)
        # Kept for loading every map the same way (and the same one again after a restore).
        self.load_kwargs = kwargs
        # Requests arrive on several threads; an edit, an undo and a save must not interleave.
        self.lock = threading.Lock()
        # Set by _load for each opened map; None until one is open (a fresh clone has no map yet).
        self.document = None
        # Names this editing session's entry in edits.json.
        self.session = None
        # Walls do not move while editing, so the building's grain and the protection zone
        # (static structure whose points an erase leaves alone) are worked out once per map.
        self.main_direction = None
        self.protection = None
        # Done-stack ids at the last save (or load), so the page can tell unsaved changes apart.
        self.saved_ids = ()

    def start_viewer(self) -> None:
        self.display.start_viewer(self.document)

    def open_last(self) -> bool:
        """Open the map opened last, if none is open yet. Loading reads the point clouds (a few seconds),
        so it waits for the Map page to ask instead of slowing every start and every test."""
        start = self.storage.last_opened() if self.document is None else None
        if start is not None:
            self.open_map(start.name)
        opened = self.document is not None
        return opened

    def _need_map(self) -> None:
        """Opens the last map if none is open; with no map at all, says so instead of failing deeper."""
        if not self.open_last():
            raise FileNotFoundError("No map is open. Open or upload one on the Map page first.")

    def maps(self) -> dict:
        """The maps that can be opened, and which one is open."""
        current = self.document.folder.name if self.document is not None else None
        result = {"maps": self.storage.list_maps(), "current": current, "root": str(self.storage.map_root)}
        return result

    def open_map(self, name: str) -> dict:
        """Open a map folder under the map root by name; this map's history ends here."""
        with self.lock:
            self._load(self.storage.map_folder(name))
            self.display.build(self.document)
        result = {"map_id": self.document.map_id, "folder": self.document.folder.name}
        return result

    def upload_map(self, data: bytes) -> dict:
        """Unpack an uploaded map .zip into a new folder (never over an existing one) and open it."""
        folder = self.storage.import_package(data)
        result = self.open_map(folder.name)
        return result

    @property
    def package_dir(self) -> Path:
        package_dir = self.storage.package_dir
        return package_dir

    def _load(self, folder: Path) -> None:
        self.document = self.storage.load(folder, **self.load_kwargs)
        self.session = datetime.now().isoformat(timespec="seconds")
        self.main_direction = self.inspection.main_direction(self.document)
        self.protection = self.inspection.protection_mask(self.document)
        self.editing.history.clear()
        self.saved_ids = ()
        self.storage.remember(folder)
        logger.info("Opened {}: {}, floor z = {}", self.document.map_id, folder, self.document.ground_z)

    def map_info(self) -> dict:
        """Everything the page needs to lay out the map, show what was loaded and fill its controls.
        With no map open, only enough for the page to ask for one."""
        self.open_last()
        document = self.document
        if document is None:
            info = {"loaded": False, "viewer_url": self.display.viewer_url}
            return info
        grid = document.grid
        values, counts = np.unique(grid.image, return_counts=True)
        tour_points = [{"name": point["name"], "x": point["x"], "y": point["y"], "yaw": point["yaw"]}
                       for point in document.manifest["tour_points"]]
        info = {
            "loaded": True,
            "map_id": document.map_id,
            "folder": str(document.folder),
            "width": grid.width,
            "height": grid.height,
            "resolution": grid.resolution,
            "origin": list(grid.origin),
            "ground_z": document.ground_z,
            # Local floor spread over free cells: heights on the page are above these, not above ground_z.
            "floor_range": [round(float(document.floor[grid.image == MapGridConfig.FREE].min()), 3),
                            round(float(document.floor[grid.image == MapGridConfig.FREE].max()), 3)],
            "map_points": document.map_cloud.count,
            "ground_points": document.ground_cloud.count,
            "map_outside": int((~document.map_cells[2]).sum()),
            "ground_outside": int((~document.ground_cells[2]).sum()),
            # Marked by edits in this session; they leave the files on the next save.
            "map_deleted": int(document.map_deleted.sum()),
            "ground_deleted": int(document.ground_deleted.sum()),
            "grid_values": {str(int(value)): int(count) for value, count in zip(values, counts, strict=False)},
            "tour_points": tour_points,
            "viewer_url": self.display.viewer_url,
            "scene_layers": self.display.scene_layers,
            "tool_names": MapEditConfig.TOOL_NAMES,
            "main_direction_deg": self.main_direction,
            # The comparison base: grid.orig.pgm once the map has been saved, else the grid as loaded.
            "original_source": "grid.orig.pgm" if self.storage.original_path(
                document.folder, MapGridConfig.GRID_FILE).exists() else "grid.pgm as opened",
            "changed_cells": int((grid.image != document.grid_original.image).sum()),
            "snap_radius_m": MapInspectionConfig.SNAP_RADIUS_M,
            "defaults": {
                "projection_z_range_rel": list(MapCloudConfig.PROJECTION_Z_RANGE_REL),
                "erase_z_range_rel": list(MapCloudConfig.ERASE_Z_RANGE_REL),
                "ground_erase_z_range_rel": list(MapCloudConfig.GROUND_ERASE_Z_RANGE_REL),
                "erase_grid_value": MapEditConfig.ERASE_GRID_VALUE,
                "wall_width_m": MapEditConfig.WALL_WIDTH_M,
                "brush_radius_m": MapEditConfig.BRUSH_RADIUS_M,
                "candidate_z_range_rel": list(MapInspectionConfig.CANDIDATE_Z_RANGE_REL),
                "candidate_min_points": MapInspectionConfig.CANDIDATE_MIN_POINTS,
                "candidate_min_cells": MapInspectionConfig.CANDIDATE_MIN_CELLS,
            },
        }
        return info

    def grid_png(self, which: str = "current") -> bytes:
        png = self.display.grid_png(self.document, which)
        return png

    def projection_png(self, z_lo_rel: float, z_hi_rel: float, source: str = "map") -> bytes:
        png = self.display.projection_png(self.document, z_lo_rel, z_hi_rel, source)
        return png

    def diff_png(self) -> bytes:
        png = self.display.diff_png(self.document)
        return png

    def protection_png(self) -> bytes:
        png = self.display.protection_png(self.protection)
        return png

    def preview(self, request: dict) -> dict:
        """Counts what the shape would change; in 3D the points to delete turn red, protected ones orange."""
        with self.lock:
            erasure = self.editing.preview(self.document, request, self.protection)
            self.display.show_preview(self.document, erasure)
        result = {
            "cells": erasure.cells,
            "map_points": len(erasure.map_idx),
            "ground_points": len(erasure.ground_idx),
            "protected_points": erasure.protected_points,
            "kept_protected": erasure.kept_protected,
            "protect_warn_points": MapInspectionConfig.PROTECT_WARN_POINTS,
        }
        return result

    def cancel_preview(self) -> None:
        self.display.clear_preview()

    def apply(self, request: dict) -> dict:
        with self.lock:
            command = self.editing.apply(self.document, request, self.protection)
            self.display.refresh(self.document)
        result = {"command": self._command_view(command), "history": self.history()}
        return result

    def undo(self) -> dict:
        with self.lock:
            command = self.editing.undo(self.document)
            self.display.refresh(self.document)
        result = {"command": self._command_view(command), "history": self.history()}
        return result

    def redo(self) -> dict:
        with self.lock:
            command = self.editing.redo(self.document)
            self.display.refresh(self.document)
        result = {"command": self._command_view(command), "history": self.history()}
        return result

    def jump(self, command_id: int) -> dict:
        """Undo or redo to just after command_id (0: before the first edit)."""
        with self.lock:
            moved = self.editing.jump(self.document, command_id)
            self.display.refresh(self.document)
        result = {"moved": len(moved), "history": self.history()}
        return result

    def restore(self) -> dict:
        """Back to the map as it was before its first save. History is cleared: the edits it holds
        were made on the version now set aside in .backup."""
        with self.lock:
            backup_dir = self.storage.restore(self.document.folder)
            if backup_dir is not None:
                self.document = self.storage.load(self.document.folder, **self.load_kwargs)
                self.protection = self.inspection.protection_mask(self.document)
                self.editing.history.clear()
                self.saved_ids = ()
                self.display.reload(self.document)
        result = {"restored": backup_dir is not None, "backup_dir": str(backup_dir) if backup_dir else None,
                  "history": self.history()}
        return result

    def history(self) -> dict:
        history = self.editing.history
        state = {
            "entries": self.editing.entries(),
            "can_undo": bool(history.done),
            "can_redo": bool(history.undone),
            "dirty": history.done_ids() != self.saved_ids,
            "changed_cells": int((self.document.grid.image != self.document.grid_original.image).sum()),
            "can_restore": self.storage.has_originals(self.document.folder),
        }
        return state

    def save(self) -> dict:
        with self.lock:
            result = self.storage.save(self.document)
            log_path = self.storage.write_log(self.document.folder, self.session, self.editing.log_entries())
            self.saved_ids = self.editing.history.done_ids()
        result = {**result, "log_path": str(log_path), "history": self.history()}
        return result

    def focus(self, x: float, y: float, distance: float) -> None:
        self._need_map()
        self.display.focus(self.document, x, y, distance)

    def highlight(self, outline: list, kind: str) -> None:
        """Fence off one candidate in 3D (outline in metres); an empty outline clears it."""
        self._need_map()
        self.display.highlight(self.document, outline, kind)

    def set_scene_layer(self, name: str, visible: bool) -> dict[str, bool]:
        """Show or hide a 3D layer (map / ground / grid); returns every layer's state."""
        self.display.set_scene_layer(name, visible)
        layers = self.display.scene_layers
        return layers

    def candidates(self, **kwargs) -> list[dict]:
        """Suspected ghosts and missed obstacles in the current map; hints only, nothing is changed."""
        self._need_map()
        candidates = self.inspection.candidate_list(self.document, **kwargs)
        return candidates

    @staticmethod
    def _command_view(command: EditCommand | None) -> dict | None:
        """The JSON shape the API returns for a command; None when nothing happened."""
        if command is None:
            return None
        view = {
            "id": command.id,
            "tool": command.tool,
            "summary": command.summary,
            "map_points": len(command.map_idx),
            "ground_points": len(command.ground_idx),
        }
        return view


def open_demo_copy(application: MapSession, name: str) -> Path:
    """For the API demos: point the application at a fresh copy of the sample map under
    output/demo/<name>/<time>/ and open it, so a demo never writes data/maps (not even .last_opened)."""
    run_dir = MapPathConfig.DEMO_DIR / name / datetime.now().strftime("%Y%m%d-%H%M%S")
    copy_map(MapPathConfig.MAP_DIR, run_dir / "maps" / MapPathConfig.MAP_ID)
    application.storage.map_root = run_dir / "maps"
    application.storage.package_dir = run_dir / "map_exports"
    application.open_map(MapPathConfig.MAP_ID)
    return run_dir


def demo_application() -> None:
    """On a copy under output/demo/application/<time>/: open -> preview -> apply -> undo -> redo -> save
    -> restore -> upload the export as a second map (no viser)."""
    run_dir = MapPathConfig.DEMO_DIR / "application" / datetime.now().strftime("%Y%m%d-%H%M%S")
    copy_map(MapPathConfig.MAP_DIR, run_dir / "maps" / "RTLAB")
    application = MapSession(map_root=run_dir / "maps", package_dir=run_dir / "map_exports")
    assert application.document is None and not application.map_info()["loaded"], "nothing opened yet"
    assert [entry["folder"] for entry in application.maps()["maps"]] == ["RTLAB"]
    application.open_map("RTLAB")
    info = application.map_info()
    logger.info("{}: {}×{}, map.pcd {:,} points, defaults {}", info["map_id"], info["width"], info["height"],
                info["map_points"], info["defaults"])

    erase = {"tool": "rect_erase", "action": "erase",
             "geometry": {"polygon": [[0.2, 3.0], [0.8, 3.0], [0.8, 8.5], [0.2, 8.5]]},
             "params": {"grid_value": 254, "apply_to_pcd": True, "z_range_rel": [0.1, 2.0],
                        "ground_z_range_rel": [0.1, 2.0]}}
    preview = application.preview(erase)
    applied = application.apply(erase)
    assert applied["command"]["map_points"] == preview["map_points"] and applied["history"]["dirty"]
    undone = application.undo()
    assert undone["history"]["can_redo"] and not undone["history"]["dirty"]
    redone = application.redo()
    saved = application.save()
    assert not saved["history"]["dirty"]
    assert application.undo()["history"]["dirty"]
    jumped = application.jump(1)
    assert jumped["moved"] == 1 and not jumped["history"]["dirty"]
    restored = application.restore()
    assert restored["restored"] and restored["history"]["changed_cells"] == 0
    assert application.document.map_cloud.count == info["map_points"]
    logger.info("Preview {}; applied {}; saved after undo and redo: {}; log {}", preview, redone["command"]["summary"],
                saved["package_path"], saved["log_path"])
    logger.info("Back at #1 it matches the save; after restoring, 0 cells changed and {:,} points again",
                application.document.map_cloud.count)

    # The exported package, uploaded again: a second folder RTLAB-2 with the saved edit in it.
    opened = application.upload_map(Path(saved["package_path"]).read_bytes())
    assert opened == {"map_id": "RTLAB", "folder": "RTLAB-2"}
    assert application.map_info()["map_points"] == saved["map_points"]
    assert not application.history()["can_undo"] and application.maps()["current"] == "RTLAB-2"
    restarted = MapSession(map_root=run_dir / "maps")
    assert restarted.open_last() and restarted.document.folder.name == "RTLAB-2", "a restart should open the last map"
    logger.info("Uploaded the export: opened {}, map.pcd {:,} points, history cleared; a restart opens it again",
                opened, saved["map_points"])


def main() -> None:
    use_utf8_output()
    demo_application()


if __name__ == "__main__":
    main()
