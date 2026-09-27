"""A still picture of a pose, drawn when the pose is saved and kept beside its file
(data/poses/<type>/<name>.png), so actions can be designed by sight."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from collections.abc import Mapping

from loguru import logger

from config.settings import PathConfig, use_utf8_output
from util.robot_render_helper import RobotRenderHelper


class PosePreview:
    def __init__(self, **kwargs) -> None:
        """kwargs: renderer (a RobotRenderHelper; tests pass a fake)."""
        self.renderer = kwargs.get("renderer") or RobotRenderHelper()

    def draw(self, joint_values: Mapping[str, float], path: Path) -> Path:
        """The PNG of the robot in these values (every joint the picture should show, legs included),
        written to path, replacing any older picture there."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.renderer.render(joint_values))
        logger.info("Drew pose picture {}", path)
        return path


def demo_pose_preview() -> None:
    preview = PosePreview()
    wave = {"right_shoulder_pitch_joint": -1.4, "right_shoulder_roll_joint": -0.6, "right_elbow_joint": 0.4}
    path = preview.draw(wave, PathConfig.DEMO_DIR / "pose_previews" / "wave.png")
    logger.info("{}: {:,} bytes", path, path.stat().st_size)


def main() -> None:
    use_utf8_output()
    demo_pose_preview()


if __name__ == "__main__":
    main()
