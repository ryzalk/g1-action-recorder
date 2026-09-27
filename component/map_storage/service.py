"""Loading, saving and exporting maps. data/maps is written only through here."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from loguru import logger

from component.map_storage.floor_height import FloorHeight
from config.settings import MapCloudConfig, MapGridConfig, MapPathConfig, use_utf8_output
from util.map_package_helper import MapPackageHelper
from util.occupancy_grid_helper import OccupancyGrid, OccupancyGridHelper
from util.point_cloud_helper import PointCloud, PointCloudHelper


@dataclass
class MapDocument:
    """A map being edited. Produced by MapStorage.load; edits change it in place."""

    folder: Path
    manifest: dict
    grid_original: OccupancyGrid
    grid: OccupancyGrid
    map_cloud: PointCloud
    ground_cloud: PointCloud
    # Points are only marked, never removed from the arrays, so every edit can be undone.
    map_deleted: np.ndarray
    ground_deleted: np.ndarray
    # Cell of each point, computed once at load, so a mask lookup is a plain index.
    map_cells: tuple[np.ndarray, np.ndarray, np.ndarray]      # rows, cols, inside
    ground_cells: tuple[np.ndarray, np.ndarray, np.ndarray]
    ground_z: float                  # building-wide floor, used where no local floor applies
    floor: np.ndarray                # H×W floor z per cell (see floor_height.py)
    # Height of each point above the floor of its own cell: every "x m above the floor" uses these.
    map_height: np.ndarray
    ground_height: np.ndarray

    @property
    def map_id(self) -> str:
        map_id = self.manifest["map_id"]
        return map_id


class MapStorage:
    # The three files an edit can change; grid.yaml and manifest.json keep their content.
    EDITED_FILES = (MapGridConfig.GRID_FILE, MapCloudConfig.MAP_FILE, MapCloudConfig.GROUND_FILE)

    def __init__(self, **kwargs) -> None:
        self.grid_helper = OccupancyGridHelper(**kwargs)
        self.cloud_helper = PointCloudHelper()
        self.package_helper = MapPackageHelper()
        self.floor_height = FloorHeight(**kwargs)
        self.package_dir = Path(kwargs.get("package_dir", MapPathConfig.PACKAGE_DIR))
        self.map_root = Path(kwargs.get("map_root", MapPathConfig.MAP_ROOT))

    def list_maps(self) -> list[dict]:
        """Every map folder under map_root (one holding a manifest.json), most recently changed first."""
        maps = []
        for folder in self.map_root.iterdir() if self.map_root.exists() else []:
            if not (folder / self.package_helper.MANIFEST_FILE).exists():
                continue
            manifest = self.package_helper.read_manifest(folder)
            maps.append({
                "folder": folder.name,
                "map_id": manifest["map_id"],
                "name": manifest["name"],
                "tour_points": len(manifest["tour_points"]),
                "saved": self.has_originals(folder),
                "modified": (folder / MapGridConfig.GRID_FILE).stat().st_mtime,
            })
        maps.sort(key=lambda entry: entry["modified"], reverse=True)
        return maps

    def import_package(self, data: bytes) -> Path:
        """An uploaded map (a zipped map folder), checksums verified, unpacked into a new folder
        named after its map_id.
        A folder of that name already there is never touched: the new one becomes <map_id>-2, -3, …
        Its manifest keeps the original map_id, so an export still uploads as the same map."""
        package = self.package_helper.unpack_bytes(data)
        # Only letters, digits, _ and -: a map_id like "../x" must not reach outside map_root.
        name = re.sub(r"[^\w-]", "_", package["manifest"]["map_id"]) or "map"
        folder = self.map_root / name
        suffix = 2
        while folder.exists():
            folder = self.map_root / f"{name}-{suffix}"
            suffix += 1
        self.package_helper.extract(package, folder)
        logger.info("Imported {}: {}", package["manifest"]["map_id"], folder)
        return folder

    def map_folder(self, name: str) -> Path:
        """A folder under map_root by its name alone; a name with a path in it is cut to its last part."""
        folder = self.map_root / Path(name).name
        return folder

    def remember(self, folder: Path) -> None:
        """The next start opens this map again."""
        self.map_root.mkdir(parents=True, exist_ok=True)
        (self.map_root / MapPathConfig.LAST_MAP_FILE).write_text(Path(folder).name, encoding="utf-8")

    def last_opened(self) -> Path | None:
        """The map opened last, if it is still there."""
        path = self.map_root / MapPathConfig.LAST_MAP_FILE
        folder = self.map_folder(path.read_text(encoding="utf-8").strip()) if path.exists() else None
        if folder is not None and not (folder / self.package_helper.MANIFEST_FILE).exists():
            folder = None
        return folder

    def load(self, folder: Path = MapPathConfig.MAP_DIR, **kwargs) -> MapDocument:
        """ground_z= overrides the building floor measured from map.pcd."""
        folder = Path(folder)
        grid = self.grid_helper.read(folder)
        map_cloud = self.cloud_helper.read(folder / MapCloudConfig.MAP_FILE)
        ground_cloud = self.cloud_helper.read(folder / MapCloudConfig.GROUND_FILE)
        # After a save the pre-edit grid lives on in grid.orig.pgm; comparing against it keeps
        # every change visible across restarts, not just this session's.
        grid_original = grid.copy()
        original_path = self.original_path(folder, MapGridConfig.GRID_FILE)
        if original_path.exists():
            grid_original.image = self.grid_helper.read_image(original_path)
        ground_z = kwargs["ground_z"] if "ground_z" in kwargs else self.floor_height.building_floor(map_cloud)
        floor = self.floor_height.estimate(grid, map_cloud, ground_z)
        map_cells = self._cells(grid, map_cloud)
        ground_cells = self._cells(grid, ground_cloud)
        document = MapDocument(
            folder=folder,
            manifest=self.package_helper.read_manifest(folder),
            grid_original=grid_original,
            grid=grid,
            map_cloud=map_cloud,
            ground_cloud=ground_cloud,
            map_deleted=np.zeros(map_cloud.count, dtype=bool),
            ground_deleted=np.zeros(ground_cloud.count, dtype=bool),
            map_cells=map_cells,
            ground_cells=ground_cells,
            ground_z=ground_z,
            floor=floor,
            map_height=self._heights(map_cloud, map_cells, floor, ground_z),
            ground_height=self._heights(ground_cloud, ground_cells, floor, ground_z),
        )
        return document

    def save(self, document: MapDocument) -> dict:
        """Original files -> backup -> temp files -> read back and check -> replace -> manifest -> zip."""
        folder = document.folder
        self._keep_originals(folder)
        backup_dir = self._backup(folder)
        counts = self._write_verified(document)
        self._update_manifest(folder)
        package_path = self.export(document)
        result = {"backup_dir": str(backup_dir), "package_path": str(package_path), **counts}
        logger.info("Saved {}: map.pcd {:,} points, ground_map.pcd {:,} points; backup {}; export {}",
                    folder, counts["map_points"], counts["ground_points"], backup_dir, package_path)
        return result

    def export(self, document: MapDocument) -> Path:
        """The map folder's files as they are on disk now, zipped for download (a copy stays in package_dir)."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        package_path = self.package_helper.zip_folder(document.folder,
                                                      self.package_dir / f"{document.folder.name}_{stamp}.zip")
        return package_path

    def has_originals(self, folder: Path) -> bool:
        """True once the map has been saved: the pre-edit files exist and can be restored."""
        exists = all(self.original_path(folder, name).exists() for name in self.EDITED_FILES)
        return exists

    def restore(self, folder: Path) -> Path | None:
        """Put the *.orig.* files back in place; the version they replace goes to .backup first.
        A map never saved has no originals and is left alone (None)."""
        folder = Path(folder)
        if not self.has_originals(folder):
            return None
        backup_dir = self._backup(folder)
        for name in self.EDITED_FILES:
            shutil.copy2(self.original_path(folder, name), folder / name)
        # An uploaded package fills the checksums; left alone they would still describe the edited files.
        self._update_manifest(folder)
        logger.info("Restored the original of {}; the version before is in {}", folder, backup_dir)
        return backup_dir

    def write_log(self, folder: Path, session: str, commands: list[dict]) -> Path:
        """edits.json keeps one entry per editing session; saving again replaces that session's entry."""
        path = Path(folder) / MapPathConfig.EDIT_LOG_FILE
        sessions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        sessions = [entry for entry in sessions if entry["session"] != session]
        sessions.append({"session": session, "saved_at": datetime.now().isoformat(timespec="seconds"),
                         "commands": commands})
        path.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def original_path(folder: Path, name: str) -> Path:
        """grid.pgm -> grid.orig.pgm."""
        stem, suffix = name.rsplit(".", 1)
        path = Path(folder) / f"{stem}{MapPathConfig.ORIGINAL_SUFFIX}.{suffix}"
        return path

    @staticmethod
    def _cells(grid: OccupancyGrid, cloud: PointCloud) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        rows, cols = grid.world_to_pixel(cloud.xyz[:, :2])
        inside = grid.contains(rows, cols)
        # Clipped so mask[rows, cols] is always a valid index; `inside` keeps the outliers out.
        rows = np.clip(rows, 0, grid.height - 1)
        cols = np.clip(cols, 0, grid.width - 1)
        cells = (rows, cols, inside)
        return cells

    @staticmethod
    def _heights(cloud: PointCloud, cells: tuple, floor: np.ndarray, ground_z: float) -> np.ndarray:
        """z above the floor of the point's cell; points off the grid measure from ground_z."""
        rows, cols, inside = cells
        heights = cloud.data["z"] - np.where(inside, floor[rows, cols], ground_z)
        return heights

    def _keep_originals(self, folder: Path) -> None:
        """First save only; *.orig.* are never overwritten, they are how the map gets restored."""
        for name in self.EDITED_FILES:
            original = self.original_path(folder, name)
            if not original.exists():
                shutil.copy2(folder / name, original)

    def _backup(self, folder: Path) -> Path:
        """The version on disk right before this save, as a complete package folder.
        Two backups within one second (save, then restore) get separate folders, never share one."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = folder / MapPathConfig.BACKUP_DIR_NAME / stamp
        suffix = 2
        while backup_dir.exists():
            backup_dir = folder / MapPathConfig.BACKUP_DIR_NAME / f"{stamp}-{suffix}"
            suffix += 1
        backup_dir.mkdir(parents=True)
        for name in (*self.package_helper.FILES, self.package_helper.MANIFEST_FILE):
            shutil.copy2(folder / name, backup_dir / name)
        return backup_dir

    def _write_verified(self, document: MapDocument) -> dict:
        """Everything goes to a temporary name first and is read back; only a file that checks out
        replaces the real one, so the robot never gets a half-written or malformed map."""
        folder = document.folder
        temporary = {name: folder / f"{name}.tmp" for name in self.EDITED_FILES}
        map_keep = ~document.map_deleted
        ground_keep = ~document.ground_deleted
        self.grid_helper.write(document.grid, temporary[MapGridConfig.GRID_FILE])
        self.cloud_helper.write(document.map_cloud, temporary[MapCloudConfig.MAP_FILE], keep=map_keep)
        self.cloud_helper.write(document.ground_cloud, temporary[MapCloudConfig.GROUND_FILE], keep=ground_keep)

        image = self.grid_helper.read_image(temporary[MapGridConfig.GRID_FILE])
        if image.shape != document.grid.image.shape or not np.isin(image, MapGridConfig.VALUES).all():
            raise ValueError("The grid.pgm written changed size or holds values other than 0/205/254")
        if not np.array_equal(image, document.grid.image):
            raise ValueError("The grid.pgm written differs from the grid in memory")
        for name, cloud, keep in ((MapCloudConfig.MAP_FILE, document.map_cloud, map_keep),
                                  (MapCloudConfig.GROUND_FILE, document.ground_cloud, ground_keep)):
            written = self.cloud_helper.read(temporary[name])
            if self._fixed_header(written.header_lines) != self._fixed_header(cloud.header_lines):
                raise ValueError(f"The {name} written has a different header (beyond WIDTH / POINTS) from the original")
            if written.count != int(keep.sum()) or written.data.tobytes() != cloud.data[keep].tobytes():
                raise ValueError(f"The {name} written holds different points from memory")

        for name, path in temporary.items():
            os.replace(path, folder / name)
        counts = {
            "map_points": int(map_keep.sum()),
            "ground_points": int(ground_keep.sum()),
            "cells_changed": int((document.grid.image != document.grid_original.image).sum()),
        }
        return counts

    @staticmethod
    def _fixed_header(lines: list[str]) -> list[str]:
        fixed = [line for line in lines if not line.startswith(("WIDTH ", "POINTS "))]
        return fixed

    def _update_manifest(self, folder: Path) -> None:
        """Empty checksums stay empty, as g1_api update_grid leaves them; filled ones are refreshed."""
        manifest = self.package_helper.read_manifest(folder)
        if manifest["checksums"]:
            manifest["checksums"] = self.package_helper.checksums(folder)
            self.package_helper.write_manifest(folder, manifest)


def copy_map(source: Path, target: Path) -> Path:
    """Package files only (no .orig / .backup), for demos and test runs that must not touch the real map."""
    target.mkdir(parents=True, exist_ok=True)
    for name in (*MapPackageHelper.FILES, MapPackageHelper.MANIFEST_FILE):
        shutil.copy2(source / name, target / name)
    return target


def demo_load() -> None:
    started = time.perf_counter()
    document = MapStorage().load()
    logger.info("Loaded {}: {:.2f} s", document.map_id, time.perf_counter() - started)
    logger.info("Grid {}×{}; map.pcd {:,} points ({} off the grid); ground_map.pcd {:,} points ({} off the grid)",
                document.grid.width, document.grid.height,
                document.map_cloud.count, int((~document.map_cells[2]).sum()),
                document.ground_cloud.count, int((~document.ground_cells[2]).sum()))
    assert document.grid.image is not document.grid_original.image


def demo_save_copy() -> None:
    """On a fresh copy under output/demo/storage/<time>/: edit -> save -> reload -> same; save twice ->
    the originals stay the first ones. The real data/maps/RTLAB is only read."""
    run_dir = MapPathConfig.DEMO_DIR / "storage" / datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = copy_map(MapPathConfig.MAP_DIR, run_dir / "RTLAB")
    storage = MapStorage(package_dir=run_dir / "map_exports")
    document = storage.load(folder)

    document.grid.image[200:210, 200:210] = MapGridConfig.OCCUPIED
    document.map_deleted[:1000] = True
    document.ground_deleted[-10:] = True
    first = storage.save(document)
    again = storage.load(folder)
    assert np.array_equal(again.grid.image, document.grid.image)
    assert again.map_cloud.count == document.map_cloud.count - 1000
    assert again.map_cloud.data.tobytes() == document.map_cloud.data[1000:].tobytes()
    assert again.ground_cloud.count == document.ground_cloud.count - 10

    time.sleep(1.1)
    document.map_deleted[:1000] = False
    second = storage.save(document)
    restored = storage.load(folder)
    assert restored.map_cloud.count == document.map_cloud.count, "saving after an undo writes every point back"
    original = storage.original_path(folder, MapCloudConfig.MAP_FILE)
    sample = (MapPathConfig.MAP_DIR / MapCloudConfig.MAP_FILE).read_bytes()
    assert original.read_bytes() == sample, ".orig was overwritten"
    assert storage.package_helper.read_manifest(folder)["checksums"] == {}
    assert np.array_equal(restored.grid_original.image, storage.load(MapPathConfig.MAP_DIR).grid.image), \
        "with grid.orig.pgm present it should be the comparison base"

    storage.write_log(folder, "demo", [{"id": 1, "summary": "first"}])
    log_path = storage.write_log(folder, "demo", [{"id": 1, "summary": "first"}, {"id": 2, "summary": "second"}])
    assert len(json.loads(log_path.read_text(encoding="utf-8"))) == 1, "a second save replaces the session's entry"
    restore_backup = storage.restore(folder)
    assert (folder / MapCloudConfig.MAP_FILE).read_bytes() == sample
    assert storage.restore(run_dir / "never_saved") is None, "restore without *.orig.* should do nothing"
    logger.info("First save: {}", first)
    logger.info("Second save: {}", second)
    logger.info("Restored: map.pcd matches the original byte for byte; the version before is in {}", restore_backup)
    logger.info("Copy folder holds: {}", sorted(path.name for path in folder.iterdir()))


def demo_import() -> None:
    """Into an empty map root under output/demo/storage/<time>/: upload RTLAB twice -> RTLAB and RTLAB-2,
    both byte for byte the sample; the list shows both; the last opened one is remembered."""
    run_dir = MapPathConfig.DEMO_DIR / "storage" / datetime.now().strftime("%Y%m%d-%H%M%S")
    storage = MapStorage(map_root=run_dir / "maps", package_dir=run_dir / "map_exports")
    assert storage.list_maps() == [] and storage.last_opened() is None
    # A copy whose manifest carries checksums, as a map from the robot does, zipped as Save & export would.
    source = copy_map(MapPathConfig.MAP_DIR, run_dir / "source" / "RTLAB")
    helper = storage.package_helper
    helper.write_manifest(source, {**helper.read_manifest(source), "checksums": helper.checksums(source)})
    data = helper.zip_folder(source, run_dir / "RTLAB.zip").read_bytes()
    first = storage.import_package(data)
    second = storage.import_package(data)
    assert (first.name, second.name) == ("RTLAB", "RTLAB-2")
    for name in storage.package_helper.FILES:
        assert (second / name).read_bytes() == (MapPathConfig.MAP_DIR / name).read_bytes()
    maps = storage.list_maps()
    assert sorted(entry["folder"] for entry in maps) == ["RTLAB", "RTLAB-2"]
    assert {entry["map_id"] for entry in maps} == {"RTLAB"}
    storage.remember(second)
    assert storage.last_opened() == second
    assert storage.map_folder("../../RTLAB") == run_dir / "maps" / "RTLAB"
    document = storage.load(second)
    logger.info("Imported twice: {}, {}; list {}; last opened {}; floor z = {}", first.name, second.name,
                [entry["folder"] for entry in maps], storage.last_opened().name, document.ground_z)

    # Its checksums are filled: save and restore both keep them true to the files.
    document.grid.image[200:210, 200:210] = MapGridConfig.OCCUPIED
    storage.save(document)
    assert helper.read_manifest(second)["checksums"] == helper.checksums(second), "checksums match after saving"
    storage.restore(second)
    assert helper.read_manifest(second)["checksums"] == helper.checksums(second), "checksums match after restoring"
    logger.info("An imported map keeps manifest checksums in step with its files through save and restore")


def main() -> None:
    use_utf8_output()
    demo_load()
    demo_save_copy()
    demo_import()


if __name__ == "__main__":
    main()
