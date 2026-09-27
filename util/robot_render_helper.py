"""Still pictures of the G1 in given joint values: MuJoCo offscreen rendering, robot only on a plain background,
as PNG bytes."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor

import cv2
import mujoco
import numpy as np
from loguru import logger

from config.settings import PathConfig, PreviewConfig, use_utf8_output


class RobotRenderHelper:
    """Every picture is drawn on one worker thread, with a GL context made and closed inside that call:
    a context only works on the thread that made it, and freeing it from another thread (garbage collection,
    interpreter exit) crashes the process. So render() can be called from any thread."""

    def __init__(self, mjcf_path: Path = PathConfig.MJCF_PATH, **kwargs) -> None:
        self.mjcf_path = mjcf_path
        self.width = kwargs.get("width", PreviewConfig.WIDTH)
        self.height = kwargs.get("height", PreviewConfig.HEIGHT)
        self.background = kwargs.get("background", PreviewConfig.BACKGROUND_RGB)
        self.camera_settings = kwargs.get("camera", PreviewConfig.CAMERA)
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="robot-render")
        self.model = None

    def render(self, joint_values: Mapping[str, float]) -> bytes:
        """Joints not given stay at the model's zero; the floating base stays where the model puts it."""
        png = self.worker.submit(self._render, dict(joint_values)).result()
        return png

    def _render(self, joint_values: dict[str, float]) -> bytes:
        if self.model is None:
            self._open()
        self.data.qpos[:] = self.model.qpos0
        for name, value in joint_values.items():
            self.data.qpos[self.qpos_address[name]] = value
        mujoco.mj_forward(self.model, self.data)
        with mujoco.Renderer(self.model, self.height, self.width) as renderer:
            renderer.update_scene(self.data, self.camera)
            rgb = renderer.render().copy()
            renderer.enable_segmentation_rendering()
            renderer.update_scene(self.data, self.camera)
            segments = renderer.render().copy()
        # Keep the robot's own pixels; the floor, sky and anything else become the plain background.
        robot = (segments[:, :, 1] == int(mujoco.mjtObj.mjOBJ_GEOM)) & np.isin(segments[:, :, 0], self.robot_geoms)
        rgb[~robot] = self.background
        ok, encoded = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        if not ok:
            raise RuntimeError("Couldn't encode the picture as PNG")
        png = encoded.tobytes()
        return png

    def _open(self) -> None:
        self.model = mujoco.MjModel.from_xml_path(str(self.mjcf_path))
        self.data = mujoco.MjData(self.model)
        self.qpos_address = {mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, joint_id):
                             int(self.model.jnt_qposadr[joint_id]) for joint_id in range(self.model.njnt)
                             if self.model.jnt_type[joint_id] == mujoco.mjtJoint.mjJNT_HINGE}
        self.robot_geoms = np.asarray([geom_id for geom_id in range(self.model.ngeom)
                                       if self.model.geom_bodyid[geom_id] != 0])
        self.camera = mujoco.MjvCamera()
        self.camera.lookat[:] = self.camera_settings["look_at"]
        self.camera.distance = self.camera_settings["distance"]
        self.camera.azimuth = self.camera_settings["azimuth"]
        self.camera.elevation = self.camera_settings["elevation"]


def demo_robot_render_helper() -> None:
    helper = RobotRenderHelper()
    folder = PathConfig.DEMO_DIR / "robot_render"
    folder.mkdir(parents=True, exist_ok=True)
    poses = {"zero": {}, "left_elbow": {"left_shoulder_pitch_joint": -1.2, "left_elbow_joint": 0.3,
                                        "right_elbow_joint": 1.2}}
    for name, values in poses.items():
        path = folder / f"{name}.png"
        path.write_bytes(helper.render(values))
        logger.info("{}: {:,} bytes", path, path.stat().st_size)


def main() -> None:
    use_utf8_output()
    demo_robot_render_helper()


if __name__ == "__main__":
    main()
