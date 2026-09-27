"""G1 map packages: manifest.json and the map folder as a .zip (manifest.json, map.pcd, ground_map.pcd, grid.pgm,
grid.yaml), for download and upload alike."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import hashlib
import io
import json
import time
import zipfile

from loguru import logger

from config.settings import MapPathConfig, use_utf8_output


class MapPackageHelper:
    # Same order as g1_api MAP_FILES.
    FILES = ("map.pcd", "ground_map.pcd", "grid.pgm", "grid.yaml")
    MANIFEST_FILE = "manifest.json"

    def read_manifest(self, folder: Path) -> dict:
        manifest = json.loads((Path(folder) / self.MANIFEST_FILE).read_text(encoding="utf-8"))
        return manifest

    def write_manifest(self, folder: Path, manifest: dict) -> Path:
        """ensure_ascii=False, indent=2 — the way g1_api writes it, so tour point names stay readable."""
        path = Path(folder) / self.MANIFEST_FILE
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def checksums(self, folder: Path) -> dict[str, str]:
        checksums = {name: hashlib.sha256((Path(folder) / name).read_bytes()).hexdigest() for name in self.FILES}
        return checksums

    def zip_folder(self, folder: Path, out_path: Path) -> Path:
        """The map folder's own files, byte for byte, under <folder name>/ in a zip; the working files
        (*.orig.*, .backup/, edits.json) stay behind. Read back once, so a bad zip never leaves here."""
        folder = Path(folder)
        names = (self.MANIFEST_FILE, *self.FILES)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                archive.write(folder / name, f"{folder.name}/{name}")
        with zipfile.ZipFile(out_path) as archive:
            for name in names:
                if archive.read(f"{folder.name}/{name}") != (folder / name).read_bytes():
                    raise ValueError(f"{out_path.name} doesn't hold {name} as it is on disk")
        return out_path

    def unpack(self, path: Path) -> dict:
        package = self.unpack_bytes(Path(path).read_bytes())
        return package

    def unpack_bytes(self, data: bytes) -> dict:
        """{"manifest": ..., "manifest_bytes": ..., "files": {name: bytes}}. Raises on a missing file or
        a checksum mismatch, which is what g1_api's upload would reject.

        Members are only read into memory by name, never extracted by the paths the archive gives,
        so a crafted member name cannot write outside a map folder.
        """
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise ValueError("Upload a .zip of a map folder (what Save & export downloads)")
        # The files at the top of the zip, or in one folder inside it.
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            contents = {Path(name).name: archive.read(name) for name in archive.namelist()
                        if not name.endswith("/") and Path(name).name in (self.MANIFEST_FILE, *self.FILES)}
        missing = [name for name in (self.MANIFEST_FILE, *self.FILES) if name not in contents]
        if missing:
            raise ValueError(f"This zip has no {', '.join(missing)}")
        manifest = json.loads(contents[self.MANIFEST_FILE].decode("utf-8"))
        files = {name: contents[name] for name in self.FILES}
        for name, expected in manifest["checksums"].items():
            if hashlib.sha256(files[name]).hexdigest() != expected:
                raise ValueError(f"{name} doesn't match its checksum")
        package = {"manifest": manifest, "manifest_bytes": contents[self.MANIFEST_FILE], "files": files}
        return package

    def extract(self, package: dict, folder: Path) -> Path:
        """An unpacked package as a map folder, byte for byte. The folder must not exist yet:
        mkdir without exist_ok stops rather than overwrite a map already there."""
        folder = Path(folder)
        folder.mkdir(parents=True)
        for name, data in package["files"].items():
            (folder / name).write_bytes(data)
        (folder / self.MANIFEST_FILE).write_bytes(package["manifest_bytes"])
        return folder


def demo_manifest() -> None:
    manifest = MapPackageHelper().read_manifest(MapPathConfig.MAP_DIR)
    logger.info("map_id {}, resolution {}, origin {}, {} tour points, checksums {}",
                manifest["map_id"], manifest["resolution"], manifest["origin"],
                len(manifest["tour_points"]), manifest["checksums"])


def demo_zip() -> None:
    """RTLAB -> output/demo/map/package/RTLAB.zip -> back: every file identical; unpacking over it stops."""
    helper = MapPackageHelper()
    out_path = helper.zip_folder(MapPathConfig.MAP_DIR, MapPathConfig.DEMO_DIR / "package" / "RTLAB.zip")
    package = helper.unpack(out_path)
    for name in helper.FILES:
        assert package["files"][name] == (MapPathConfig.MAP_DIR / name).read_bytes()
    with zipfile.ZipFile(out_path) as archive:
        names = archive.namelist()
    logger.info("{}: {:,} bytes, members {}", out_path, out_path.stat().st_size, names)
    folder = MapPathConfig.DEMO_DIR / "package" / "extracted" / f"RTLAB_{time.strftime('%Y%m%d-%H%M%S')}"
    helper.extract(package, folder)
    for name in helper.FILES:
        assert (folder / name).read_bytes() == (MapPathConfig.MAP_DIR / name).read_bytes()
    try:
        helper.extract(package, folder)
        raise AssertionError("unpacking into an existing folder should stop")
    except FileExistsError:
        logger.info("Unpacked to {}: files match byte for byte; unpacking there again stops, never overwrites", folder)
    try:
        helper.unpack_bytes(b"not a zip")
    except ValueError as error:
        logger.info("Not a zip: {}", error)


def main() -> None:
    use_utf8_output()
    demo_manifest()
    demo_zip()


if __name__ == "__main__":
    main()
