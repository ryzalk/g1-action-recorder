"""Rasterising and image encoding (cv2). Coordinates are pixel (col, row) floats; whole numbers are pixel centres."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import cv2
import numpy as np
from loguru import logger

from config.settings import MapPathConfig, use_utf8_output


class RasterHelper:
    def __init__(self, **kwargs) -> None:
        # Narrower than this, an 8-connected diagonal leaves gaps an 8-neighbour planner slips through.
        self.thin_line_px = kwargs.get("thin_line_px", 2)
        # cv2 takes fixed-point coordinates; 4 fractional bits keep sub-pixel precision.
        self.shift = kwargs.get("shift", 4)

    def polygon_mask(self, shape: tuple[int, int], points_px: np.ndarray) -> np.ndarray:
        mask = np.zeros(shape, dtype=np.uint8)
        cv2.fillPoly(mask, [self._fixed(points_px)], 1, lineType=cv2.LINE_8, shift=self.shift)
        result = mask.astype(bool)
        return result

    def polyline_mask(self, shape: tuple[int, int], points_px: np.ndarray, width_px: float) -> np.ndarray:
        """Thick lines get round ends from cv2, which is what a brush stroke should look like."""
        mask = np.zeros(shape, dtype=np.uint8)
        thickness = max(1, int(round(width_px)))
        line_type = cv2.LINE_4 if width_px < self.thin_line_px else cv2.LINE_8
        cv2.polylines(mask, [self._fixed(points_px)], False, 1, thickness=thickness,
                      lineType=line_type, shift=self.shift)
        result = mask.astype(bool)
        return result

    @staticmethod
    def bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
        """r0, r1, c0, c1, end exclusive. An empty mask gives an empty box at the corner."""
        rows = np.flatnonzero(mask.any(axis=1))
        cols = np.flatnonzero(mask.any(axis=0))
        if len(rows) == 0:
            box = (0, 0, 0, 0)
            return box
        box = (int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1)
        return box

    @staticmethod
    def to_png(image: np.ndarray) -> bytes:
        """Gray, RGB or RGBA uint8 -> PNG bytes. cv2 wants BGR order, so colour is swapped here."""
        if image.ndim == 3 and image.shape[2] == 3:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        if image.ndim == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGRA)
        _, encoded = cv2.imencode(".png", image)
        png = encoded.tobytes()
        return png

    @staticmethod
    def line_segments(mask: np.ndarray, **kwargs) -> np.ndarray:
        """Straight segments in a binary image (probabilistic Hough), N×4 as x1, y1, x2, y2 in pixels."""
        found = cv2.HoughLinesP(mask.astype(np.uint8) * 255, 1, np.pi / 360,
                                threshold=kwargs.get("threshold", 30),
                                minLineLength=kwargs.get("min_length", 20),
                                maxLineGap=kwargs.get("max_gap", 3))
        segments = np.zeros((0, 4), np.int32) if found is None else found.reshape(-1, 4)
        return segments

    @staticmethod
    def colormap(values: np.ndarray) -> np.ndarray:
        """0..1 -> N×3 uint8 RGB on the viridis ramp (purple low, yellow high). It holds no red,
        orange or magenta, so points highlighted in those colours stand out against it."""
        scaled = (np.clip(values, 0.0, 1.0) * 255).astype(np.uint8).reshape(-1, 1)
        bgr = cv2.applyColorMap(scaled, cv2.COLORMAP_VIRIDIS).reshape(-1, 3)
        rgb = np.ascontiguousarray(bgr[:, ::-1])
        return rgb

    def _fixed(self, points_px: np.ndarray) -> np.ndarray:
        fixed = np.round(np.asarray(points_px, dtype=np.float64) * (1 << self.shift)).astype(np.int32)
        return fixed


def demo_png() -> None:
    helper = RasterHelper()
    gray = np.arange(256, dtype=np.uint8).reshape(16, 16)
    rgba = np.zeros((4, 4, 4), np.uint8)
    rgba[..., 0] = 255
    rgba[..., 3] = 128
    for name, image in (("gray", gray), ("RGBA", rgba)):
        png = helper.to_png(image)
        decoded = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
        if decoded.ndim == 3:
            decoded = cv2.cvtColor(decoded, cv2.COLOR_BGRA2RGBA)
        assert np.array_equal(decoded, image)
        logger.info("{} {} -> PNG {} bytes, decodes back identical", name, image.shape, len(png))


def demo_masks() -> None:
    """A square, and diagonals 1 and 2 px wide. The 1 px one must be 4-connected: no corner-only steps."""
    helper = RasterHelper()
    shape = (40, 40)
    square = helper.polygon_mask(shape, np.array([[4.0, 4.0], [13.0, 4.0], [13.0, 13.0], [4.0, 13.0]]))
    assert square.sum() == 100 and helper.bbox(square) == (4, 14, 4, 14)

    diagonal = np.array([[2.0, 20.0], [37.0, 35.0]])
    thin = helper.polyline_mask(shape, diagonal, 1.0)
    rows, cols = np.nonzero(thin)
    for row, col in zip(rows, cols, strict=False):
        neighbours = thin[max(row - 1, 0):row + 2, max(col - 1, 0):col + 2]
        four = thin[row, max(col - 1, 0):col + 2].sum() + thin[max(row - 1, 0):row + 2, col].sum() - 2
        assert four >= 1 or neighbours.sum() == 1, "a 1-pixel diagonal has cells joined only at corners"
    thick = helper.polyline_mask(shape, diagonal, 2.0)
    empty = helper.polygon_mask(shape, np.array([[1.0, 1.0], [1.2, 1.0], [1.1, 1.1]]))
    logger.info("Square {} cells; diagonal 1 px {} cells (4-connected), 2 px {} cells; tiny polygon {} cells, box {}",
                int(square.sum()), int(thin.sum()), int(thick.sum()), int(empty.sum()), helper.bbox(empty))

    out_dir = MapPathConfig.DEMO_DIR / "masks"
    out_dir.mkdir(parents=True, exist_ok=True)
    picture = np.full(shape, 255, np.uint8)
    picture[square | thin] = 0
    picture[thick & ~thin] = 128
    cv2.imwrite(str(out_dir / "masks.png"), cv2.resize(picture, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST))


def main() -> None:
    use_utf8_output()
    demo_png()
    demo_masks()


if __name__ == "__main__":
    main()
