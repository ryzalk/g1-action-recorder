"""Load a motion file for playback: a recorder NPZ, a Kimodo NPZ or an ARDY PKL, arms only."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import math
import pickle
import zipfile
from collections.abc import Mapping

import numpy as np
from loguru import logger

from component.common.action import Trajectory
from component.common.g1_joint_schema import G1JointSchema
from config.settings import ActionConfig, PathConfig, RobotConfig, use_utf8_output
from util.data_file_helper import DataFileHelper
from util.motion_file_helper import MotionFileHelper


class MotionImport:
    """Only the 14 arm joints are kept; the waist and legs follow the home pose during playback."""

    def __init__(self, schema: G1JointSchema, home_values: Mapping[str, float]) -> None:
        self.schema = schema
        self.home_arms = np.zeros(len(schema.ARM_JOINT_NAMES))
        self.files = DataFileHelper()
        self.motion_files = MotionFileHelper(schema.ARM_JOINT_NAMES)
        self.set_home(home_values)

    def set_home(self, home_values: Mapping[str, float]) -> None:
        """Imported motions blend in from and back out to these arm values."""
        self.home_arms = np.asarray([home_values[name] for name in self.schema.ARM_JOINT_NAMES])

    def load(self, filename: str, content: bytes) -> tuple[Trajectory, str]:
        """The trajectory and the format it was read as; the file itself is not kept."""
        # A wrong or damaged file is the common mistake here; say which file and why instead of a bare 500.
        try:
            result = self._read(filename, content)
        except (zipfile.BadZipFile, pickle.UnpicklingError, EOFError, KeyError, TypeError) as error:
            raise ValueError(f"Couldn't read {filename} as a recorder, Kimodo or ARDY motion ({error})") from error
        return result

    def _read(self, filename: str, content: bytes) -> tuple[Trajectory, str]:
        name = Path(filename).stem
        if filename.lower().endswith(".pkl"):
            motion = self.motion_files.read_ardy(content)
            trajectory = self._with_home_blend(name, motion.arm_positions, motion.fps)
            file_format = "ARDY PKL"
        else:
            arrays = self.files.read_npz_bytes(content)
            if "schema_version" in arrays:
                trajectory = Trajectory.from_arrays(arrays).only(self.schema.ARM_JOINT_NAMES)
                trajectory.name = name
                file_format = "Recorder NPZ"
            else:
                motion = self.motion_files.read_kimodo(arrays, ActionConfig.KIMODO_FPS)
                trajectory = self._with_home_blend(name, motion.arm_positions, motion.fps)
                file_format = "Kimodo NPZ"
        self._check_limits(trajectory)
        result = (trajectory, file_format)
        return result

    def _with_home_blend(self, name: str, positions: np.ndarray, fps: float) -> Trajectory:
        """Ease from the home arms into the first frame and from the last frame back, minimum-jerk."""
        count = max(1, math.ceil(ActionConfig.IMPORT_BLEND_SECONDS * fps))
        phase = np.linspace(0.0, 1.0, count + 1)
        blend = (phase**3 * (phase * (phase * 6.0 - 15.0) + 10.0))[:, None]
        entry = self.home_arms + blend * (positions[0] - self.home_arms)
        leave = positions[-1] + blend[1:] * (self.home_arms - positions[-1])
        samples = np.concatenate((entry, positions[1:], leave))
        home = RobotConfig.HOME_POSE_NAME
        trajectory = Trajectory(name=name, joint_names=self.schema.ARM_JOINT_NAMES,
                                timestamps=np.arange(len(samples)) / fps, joint_positions=samples,
                                keyframe_indices=(0, count, count + len(positions) - 1, len(samples) - 1),
                                keyframe_names=(home, "motion start", "motion end", home),
                                keyframe_holds=(0.0, 0.0, 0.0, 0.0), fps=fps)
        return trajectory

    def _check_limits(self, trajectory: Trajectory) -> None:
        for column, name in enumerate(trajectory.joint_names):
            limit = self.schema.limits[name]
            values = trajectory.joint_positions[:, column]
            outside = np.flatnonzero((values < limit.lower - 1e-9) | (values > limit.upper + 1e-9))
            if len(outside):
                frame = int(outside[0])
                raise ValueError(f"{name} leaves its limit [{limit.lower}, {limit.upper}] at frame {frame + 1} "
                                 f"({values[frame]:.3f} rad); this motion can't be played on the G1")


def demo_motion_import() -> None:
    """A saved recorder NPZ and a synthetic Kimodo file."""
    schema = G1JointSchema()
    home = {name: 0.0 for name in schema.UPPER_BODY_JOINT_NAMES}
    importer = MotionImport(schema, home)
    npz_path = PathConfig.DATA_DIR / "actions" / "trajectories" / "concierge_wave_left.npz"
    trajectory, file_format = importer.load(npz_path.name, npz_path.read_bytes())
    logger.info("{}: {} as {}, {} samples, {} joints", npz_path.name, trajectory.name, file_format,
                trajectory.sample_count, len(trajectory.joint_names))
    rest = np.tile(np.eye(3), (10, 34, 1, 1))
    DataFileHelper().write_npz(PathConfig.DEMO_DIR / "kimodo_rest.npz", {"global_rot_mats": rest}, overwrite=True)
    kimodo, file_format = importer.load("kimodo_rest.npz", (PathConfig.DEMO_DIR / "kimodo_rest.npz").read_bytes())
    logger.info("kimodo_rest.npz as {}: {} samples over {:.2f} s, keyframes {}", file_format, kimodo.sample_count,
                kimodo.duration, kimodo.keyframe_indices)


def main() -> None:
    use_utf8_output()
    demo_motion_import()


if __name__ == "__main__":
    main()
