"""ROS-style occupancy grids (PGM + YAML): reading, writing and coordinate conversion."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import json
from dataclasses import dataclass

import numpy as np
import yaml
from loguru import logger

from config.settings import MapGridConfig, MapPathConfig, use_utf8_output


@dataclass
class OccupancyGrid:
    """What read() hands back — defined here so a caller gets the shape from the same import."""

    image: np.ndarray                     # H×W uint8; row 0 is the top of the picture
    resolution: float
    origin: tuple[float, float, float]    # world position of the bottom-left corner
    header: bytes                         # original PGM header, written back byte for byte

    @property
    def height(self) -> int:
        height = self.image.shape[0]
        return height

    @property
    def width(self) -> int:
        width = self.image.shape[1]
        return width

    def world_to_pixel(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """N×2 metres -> (rows, cols) int. May land outside the image; see contains()."""
        cols = np.floor((xy[:, 0] - self.origin[0]) / self.resolution).astype(np.int64)
        # ROS puts the origin at the bottom-left, PGM puts row 0 at the top.
        rows = self.height - 1 - np.floor((xy[:, 1] - self.origin[1]) / self.resolution).astype(np.int64)
        pixels = (rows, cols)
        return pixels

    def pixel_to_world(self, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
        """Cell centres, N×2 metres."""
        x = self.origin[0] + (cols + 0.5) * self.resolution
        y = self.origin[1] + (self.height - 1 - rows + 0.5) * self.resolution
        xy = np.stack([x, y], axis=1)
        return xy

    def contains(self, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
        inside = (rows >= 0) & (rows < self.height) & (cols >= 0) & (cols < self.width)
        return inside

    def copy(self) -> OccupancyGrid:
        grid = OccupancyGrid(self.image.copy(), self.resolution, self.origin, self.header)
        return grid


class OccupancyGridHelper:
    def __init__(self, **kwargs) -> None:
        self.yaml_file = kwargs.get("yaml_file", MapGridConfig.YAML_FILE)

    def read(self, folder: Path) -> OccupancyGrid:
        """The PGM is whatever grid.yaml's `image` names."""
        meta = yaml.safe_load((Path(folder) / self.yaml_file).read_text(encoding="utf-8"))
        header, image = self._read_pgm(Path(folder) / meta["image"])
        grid = OccupancyGrid(
            image=image,
            resolution=float(meta["resolution"]),
            origin=tuple(float(value) for value in meta["origin"]),
            header=header,
        )
        return grid

    def read_image(self, path: Path) -> np.ndarray:
        """Pixels only — for reading back a PGM just written."""
        _, image = self._read_pgm(path)
        return image

    def write(self, grid: OccupancyGrid, path: Path) -> Path:
        """PGM only. grid.yaml never changes because the raster never resizes."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(grid.header + grid.image.tobytes())
        return path

    def _read_pgm(self, path: Path) -> tuple[bytes, np.ndarray]:
        raw = Path(path).read_bytes()
        header_size, width, height = self._parse_header(raw)
        image = np.frombuffer(raw, dtype=np.uint8, count=width * height, offset=header_size)
        pgm = (raw[:header_size], image.reshape(height, width).copy())
        return pgm

    @staticmethod
    def _parse_header(raw: bytes) -> tuple[int, int, int]:
        """P5 header: magic, width, height, maxval, then one whitespace byte before the pixels.

        Comment lines (#) may sit anywhere before maxval.
        """
        tokens = []
        position = 0
        while len(tokens) < 4:
            while raw[position:position + 1].isspace():
                position += 1
            if raw[position:position + 1] == b"#":
                position = raw.index(b"\n", position) + 1
                continue
            start = position
            while not raw[position:position + 1].isspace():
                position += 1
            tokens.append(raw[start:position])
        header_size = position + 1
        width = int(tokens[1])
        height = int(tokens[2])
        header = (header_size, width, height)
        return header


def demo_round_trip() -> None:
    """RTLAB -> output/demo/grid/: the PGM must come back byte for byte."""
    helper = OccupancyGridHelper()
    grid = helper.read(MapPathConfig.MAP_DIR)
    logger.info("Grid {}×{}, resolution {}, origin {}, header {!r}",
                grid.width, grid.height, grid.resolution, grid.origin, grid.header)

    out_path = helper.write(grid, MapPathConfig.DEMO_DIR / "grid" / "grid.pgm")
    original = (MapPathConfig.MAP_DIR / "grid.pgm").read_bytes()
    assert out_path.read_bytes() == original, "grid.pgm written back differs from the original"
    logger.info("Wrote {} back byte for byte ({} bytes)", out_path, len(original))

    values, counts = np.unique(grid.image, return_counts=True)
    for value, count in zip(values, counts, strict=False):
        known = "" if value in MapGridConfig.VALUES else "  <- not one of 0/205/254"
        logger.info("Value {:>3}: {:>7} cells{}", value, count, known)


def demo_coordinates() -> None:
    """pixel -> world -> pixel is exact; world -> pixel -> world is off by at most half a cell."""
    grid = OccupancyGridHelper().read(MapPathConfig.MAP_DIR)
    generator = np.random.default_rng(0)

    rows = generator.integers(0, grid.height, 10_000)
    cols = generator.integers(0, grid.width, 10_000)
    back_rows, back_cols = grid.world_to_pixel(grid.pixel_to_world(rows, cols))
    assert np.array_equal(rows, back_rows) and np.array_equal(cols, back_cols)

    low = np.array(grid.origin[:2])
    high = low + np.array([grid.width, grid.height]) * grid.resolution
    xy = generator.uniform(low, high, (10_000, 2))
    error = np.abs(grid.pixel_to_world(*grid.world_to_pixel(xy)) - xy).max()
    assert error <= grid.resolution / 2 + 1e-9
    logger.info("Round trips: pixel->world->pixel exact; world->pixel->world max error {:.4f} m", error)

    corners = np.array([low, high - 1e-9])
    corner_rows, corner_cols = grid.world_to_pixel(corners)
    logger.info("Bottom left {} -> pixel (row {}, col {}); top right {} -> pixel (row {}, col {})",
                corners[0].round(2), corner_rows[0], corner_cols[0],
                corners[1].round(2), corner_rows[1], corner_cols[1])

    manifest = json.loads((MapPathConfig.MAP_DIR / "manifest.json").read_text(encoding="utf-8"))
    for point in manifest["tour_points"]:
        point_rows, point_cols = grid.world_to_pixel(np.array([[point["x"], point["y"]]]))
        value = grid.image[point_rows[0], point_cols[0]]
        logger.info("{} ({}, {}) -> pixel (row {}, col {}), value {}",
                    point["name"], point["x"], point["y"], point_rows[0], point_cols[0], value)


def main() -> None:
    use_utf8_output()
    demo_round_trip()
    demo_coordinates()


if __name__ == "__main__":
    main()
