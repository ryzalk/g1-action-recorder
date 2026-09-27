"""Read, write, move and zip the JSON and NPZ files the project stores."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import io
import json
import re
import zipfile

import numpy as np
from loguru import logger

from config.settings import PathConfig, use_utf8_output


class DataFileHelper:
    def write_json(self, path: Path, payload: dict, overwrite: bool = False) -> Path:
        self._check_overwrite(path, overwrite)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def read_json(self, path: Path) -> dict:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload

    def write_npz(self, path: Path, arrays: dict, overwrite: bool = False) -> Path:
        self._check_overwrite(path, overwrite)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, **arrays)
        return path

    @staticmethod
    def npz_bytes(arrays: dict) -> bytes:
        """What write_npz would put in a file, kept in memory."""
        buffer = io.BytesIO()
        np.savez(buffer, **arrays)
        content = buffer.getvalue()
        return content

    def read_npz(self, path: Path) -> dict[str, np.ndarray]:
        arrays = self.read_npz_bytes(path.read_bytes())
        return arrays

    def read_npz_bytes(self, content: bytes) -> dict[str, np.ndarray]:
        # np.load reads anything that isn't a zip as a pickle and then complains about pickles.
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise ValueError("This is not an NPZ file")
        # Pickle stays off: an NPZ that needs it is not one of ours.
        with np.load(io.BytesIO(content), allow_pickle=False) as archive:
            arrays = {name: archive[name] for name in archive.files}
        return arrays

    def list_names(self, directory: Path, suffix: str) -> list[str]:
        """Numbers sort as numbers, so speak_2 comes before speak_10."""
        names = sorted((path.stem for path in directory.glob(f"*{suffix}")),
                       key=lambda name: [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)])
        return names

    def move(self, source: Path, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        return target

    def pack(self, files: dict[str, bytes]) -> bytes:
        """A zip holding each value under its key's path."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        packed = buffer.getvalue()
        return packed

    def unpack(self, content: bytes) -> dict[str, bytes]:
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise ValueError("This is not a zip file")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            files = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
        return files

    @staticmethod
    def _check_overwrite(path: Path, overwrite: bool) -> None:
        if path.exists() and not overwrite:
            raise FileExistsError(f"{path.stem} already exists")


def demo_data_file_helper() -> None:
    helper = DataFileHelper()
    folder = PathConfig.DEMO_DIR / "data_file_helper"
    json_path = helper.write_json(folder / "示例.json", {"name": "示例"}, overwrite=True)
    arrays = {"fps": np.asarray(25.0), "q": np.zeros((3, 17))}
    npz_path = helper.write_npz(folder / "sample.npz", arrays, overwrite=True)
    logger.info("{} -> {}", json_path.name, helper.read_json(json_path))
    logger.info("{} -> {}", npz_path.name, {name: array.shape for name, array in helper.read_npz(npz_path).items()})
    logger.info("JSON files: {}", helper.list_names(folder, ".json"))
    packed = helper.pack({"a/one.json": b"{}", "two.npz": npz_path.read_bytes()})
    logger.info("Zip of {} bytes holds {}", len(packed), sorted(helper.unpack(packed)))
    moved = helper.move(json_path, folder / "moved" / json_path.name)
    helper.move(moved, json_path)
    logger.info("Moved to {} and back", moved.parent.name)


def main() -> None:
    use_utf8_output()
    demo_data_file_helper()


if __name__ == "__main__":
    main()
