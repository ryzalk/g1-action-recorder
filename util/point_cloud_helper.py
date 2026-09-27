"""PCD point clouds (binary_compressed): reading, writing and voxel downsampling.

Read and written by hand rather than through a PCD library: the localiser on
the robot reads these files, so the header must come back exactly as it was,
with only WIDTH and POINTS changed.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import struct
import time
from dataclasses import dataclass

import cv2
import lzf
import numpy as np
from loguru import logger

from config.settings import MapCloudConfig, MapPathConfig, use_utf8_output
from util.occupancy_grid_helper import OccupancyGridHelper


@dataclass
class PointCloud:
    """What read() hands back. Points live in a structured array, one named column per PCD field."""

    header_lines: list[str]    # original header up to and including DATA; only WIDTH / POINTS change on write
    data: np.ndarray           # structured, one record per point: data["x"], data["intensity"], ...

    @property
    def fields(self) -> tuple[str, ...]:
        fields = self.data.dtype.names
        return fields

    @property
    def count(self) -> int:
        count = len(self.data)
        return count

    @property
    def xyz(self) -> np.ndarray:
        xyz = np.stack([self.data["x"], self.data["y"], self.data["z"]], axis=1)
        return xyz


class PointCloudHelper:
    # PCD TYPE letter -> numpy kind.
    KINDS = {"F": "f", "I": "i", "U": "u"}

    def read(self, path: Path) -> PointCloud:
        raw = Path(path).read_bytes()
        header_lines, position = self._split_header(raw)
        header = dict(line.split(" ", 1) for line in header_lines if not line.startswith("#"))
        dtype = self._dtype(header)
        count = int(header["POINTS"])

        # binary_compressed: two uint32 sizes, then one LZF block holding the
        # fields one after another (all x, then all y, ...), not point by point.
        compressed_size, raw_size = struct.unpack_from("<II", raw, position)
        start = position + 8
        buffer = lzf.decompress(raw[start:start + compressed_size], raw_size)

        data = np.empty(count, dtype=dtype)
        offset = 0
        for name in dtype.names:
            field = dtype.fields[name][0]
            size = field.itemsize * count
            data[name] = np.frombuffer(buffer, dtype=field.base, count=size // field.base.itemsize,
                                       offset=offset).reshape(data[name].shape)
            offset += size
        cloud = PointCloud(header_lines=header_lines, data=data)
        return cloud

    def write(self, cloud: PointCloud, path: Path, keep: np.ndarray | None = None) -> Path:
        """keep is a bool mask over the points; the rest are left out of the file."""
        data = cloud.data if keep is None else cloud.data[keep]
        header_lines = [self._resize_line(line, len(data)) for line in cloud.header_lines]

        buffer = b"".join(np.ascontiguousarray(data[name]).tobytes() for name in data.dtype.names)
        # LZF can grow incompressible input slightly; this bound always fits.
        compressed = lzf.compress(buffer, len(buffer) + len(buffer) // 16 + 64)

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            handle.write(("\n".join(header_lines) + "\n").encode("ascii"))
            handle.write(struct.pack("<II", len(compressed), len(buffer)))
            handle.write(compressed)
        return path

    @staticmethod
    def voxel_indices(xyz: np.ndarray, voxel: float) -> np.ndarray:
        """One point per voxel, returned as sorted indices so a display point traces back to its source."""
        keys = np.floor(xyz / voxel).astype(np.int64)
        keys -= keys.min(axis=0)
        dims = keys.max(axis=0) + 1
        flat = (keys[:, 0] * dims[1] + keys[:, 1]) * dims[2] + keys[:, 2]
        _, indices = np.unique(flat, return_index=True)
        indices.sort()
        return indices

    @staticmethod
    def _split_header(raw: bytes) -> tuple[list[str], int]:
        lines = []
        position = 0
        while True:
            end = raw.index(b"\n", position)
            line = raw[position:end].decode("ascii")
            lines.append(line)
            position = end + 1
            if line.startswith("DATA"):
                break
        header = (lines, position)
        return header

    def _dtype(self, header: dict[str, str]) -> np.dtype:
        names = header["FIELDS"].split()
        sizes = header["SIZE"].split()
        types = header["TYPE"].split()
        counts = header["COUNT"].split()
        columns = []
        for name, size, kind, count in zip(names, sizes, types, counts, strict=False):
            base = f"<{self.KINDS[kind]}{size}"
            columns.append((name, base) if count == "1" else (name, base, (int(count),)))
        dtype = np.dtype(columns)
        return dtype

    @staticmethod
    def _resize_line(line: str, count: int) -> str:
        if line.startswith("WIDTH ") or line.startswith("POINTS "):
            line = f"{line.split(' ', 1)[0]} {count}"
        return line


def demo_round_trip() -> None:
    """Both clouds -> output/demo/cloud/ -> back: header line for line, every value bit for bit."""
    helper = PointCloudHelper()
    for name in (MapCloudConfig.MAP_FILE, MapCloudConfig.GROUND_FILE):
        source = MapPathConfig.MAP_DIR / name
        started = time.perf_counter()
        cloud = helper.read(source)
        read_seconds = time.perf_counter() - started

        started = time.perf_counter()
        out_path = helper.write(cloud, MapPathConfig.DEMO_DIR / "cloud" / name)
        write_seconds = time.perf_counter() - started
        again = helper.read(out_path)

        assert again.header_lines == cloud.header_lines, f"{name} header differs"
        assert again.data.tobytes() == cloud.data.tobytes(), f"{name} point data differs"
        original = source.read_bytes()
        header_size = len("\n".join(cloud.header_lines)) + 1
        assert out_path.read_bytes()[:header_size] == original[:header_size]
        identical = out_path.read_bytes() == original

        xyz = cloud.xyz
        logger.info("{}: {:,} points, fields {}", name, cloud.count, " ".join(cloud.fields))
        logger.info("  x {:.2f} ~ {:.2f}, y {:.2f} ~ {:.2f}, z {:.2f} ~ {:.2f}",
                    xyz[:, 0].min(), xyz[:, 0].max(), xyz[:, 1].min(), xyz[:, 1].max(),
                    xyz[:, 2].min(), xyz[:, 2].max())
        logger.info("  read {:.2f} s, write {:.2f} s; header and data read back identical; "
                    "whole file {}identical to the original",
                    read_seconds, write_seconds, "" if identical else "not ")


def demo_voxel() -> None:
    helper = PointCloudHelper()
    cloud = helper.read(MapPathConfig.MAP_DIR / MapCloudConfig.MAP_FILE)
    for voxel in (0.05, 0.08, 0.10):
        started = time.perf_counter()
        indices = helper.voxel_indices(cloud.xyz, voxel)
        logger.info("Voxel {:.2f} m: {:,} -> {:,} points ({:.2f} s)",
                    voxel, cloud.count, len(indices), time.perf_counter() - started)


def demo_overlay() -> None:
    """Does map.pcd sit on grid.pgm? Draws the height-band projection over the grid and
    checks which pixel shift lines the two up best — it should be no shift at all."""
    grid = OccupancyGridHelper().read(MapPathConfig.MAP_DIR)
    helper = PointCloudHelper()
    cloud = helper.read(MapPathConfig.MAP_DIR / MapCloudConfig.MAP_FILE)
    ground = helper.read(MapPathConfig.MAP_DIR / MapCloudConfig.GROUND_FILE)

    xyz = cloud.xyz
    # The floor is the densest 2 cm layer of the sample map (the editor measures each map's own at load).
    counts, edges = np.histogram(xyz[:, 2], bins=np.arange(xyz[:, 2].min(), xyz[:, 2].max() + 0.02, 0.02))
    floor_z = edges[counts.argmax()] + 0.01
    logger.info("ground_map.pcd z at 5% / 50% / 95%: {:.2f} / {:.2f} / {:.2f} (map.pcd densest layer {:.2f})",
                *np.percentile(ground.data["z"], [5, 50, 95]), floor_z)

    z_lo, z_hi = (floor_z + value for value in MapCloudConfig.PROJECTION_Z_RANGE_REL)
    rows, cols = grid.world_to_pixel(xyz[:, :2])
    inside = grid.contains(rows, cols)
    band = inside & (xyz[:, 2] > z_lo) & (xyz[:, 2] < z_hi)
    logger.info("map.pcd points off the grid: {:,}; in the band {:.2f} ~ {:.2f}: {:,}",
                int((~inside).sum()), z_lo, z_hi, int(band.sum()))

    density = np.zeros(grid.image.shape, dtype=np.int32)
    np.add.at(density, (rows[band], cols[band]), 1)
    support = density >= 3
    occupied = grid.image == 0

    # Slide the projection over the grid; the best overlap should be at (0, 0).
    overlaps = {}
    for dr in range(-4, 5):
        for dc in range(-4, 5):
            shifted = np.roll(np.roll(support, dr, axis=0), dc, axis=1)
            overlaps[(dr, dc)] = int((shifted & occupied).sum())
    best = max(overlaps, key=overlaps.get)
    near_support = cv2.dilate(support.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    logger.info("Best shift (row, col) = {}, {} cells overlap; {} without shifting", best, overlaps[best],
                overlaps[(0, 0)])
    logger.info("{:,} occupied cells, {:.1%} with points within one cell",
                int(occupied.sum()), (occupied & near_support).sum() / occupied.sum())

    out_dir = MapPathConfig.DEMO_DIR / "overlay"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = cv2.cvtColor(grid.image, cv2.COLOR_GRAY2BGR)
    tint = base.copy()
    tint[support] = (0, 0, 255)
    overlay = cv2.addWeighted(base, 0.4, tint, 0.6, 0)
    projection = np.full(base.shape, 255, np.uint8)
    projection[support] = (0, 0, 255)
    scale = 3
    for name, image in (("overlay.png", overlay), ("projection.png", projection)):
        big = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        cv2.imwrite(str(out_dir / name), big)
    logger.info("Overlay (red is the point cloud, scaled {}×): {}", scale, out_dir / "overlay.png")


def main() -> None:
    use_utf8_output()
    demo_round_trip()
    demo_voxel()
    demo_overlay()


if __name__ == "__main__":
    main()
