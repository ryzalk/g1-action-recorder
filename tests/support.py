"""Shared by the tests: a throwaway copy of data/, so no test ever writes the real poses or actions."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from config.settings import PathConfig


def copy_data() -> tuple[tempfile.TemporaryDirectory, Path]:
    """The temporary directory (keep it alive, clean it up) and the data copy inside it."""
    folder = tempfile.TemporaryDirectory()
    data_dir = Path(folder.name) / "data"
    # Voice samples are many and only read; the tests make the few they need.
    shutil.copytree(PathConfig.BASE_DIR / "data", data_dir,
                    ignore=lambda folder, names: ["sample"] if Path(folder).name == "tts" else [])
    result = (folder, data_dir)
    return result
