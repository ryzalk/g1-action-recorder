"""Read Kimodo NPZ and ARDY PKL motions and turn their G1-34 rotations into G1 arm joint angles."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import builtins
import io
import pickle
import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from loguru import logger

from config.settings import PathConfig, use_utf8_output

SKELETON_NAMES = (
    "pelvis_skel", "left_hip_pitch_skel", "left_hip_roll_skel", "left_hip_yaw_skel", "left_knee_skel",
    "left_ankle_pitch_skel", "left_ankle_roll_skel", "left_toe_base", "right_hip_pitch_skel", "right_hip_roll_skel",
    "right_hip_yaw_skel", "right_knee_skel", "right_ankle_pitch_skel", "right_ankle_roll_skel", "right_toe_base",
    "waist_yaw_skel", "waist_roll_skel", "waist_pitch_skel", "left_shoulder_pitch_skel", "left_shoulder_roll_skel",
    "left_shoulder_yaw_skel", "left_elbow_skel", "left_wrist_roll_skel", "left_wrist_pitch_skel",
    "left_wrist_yaw_skel", "left_hand_roll_skel", "right_shoulder_pitch_skel", "right_shoulder_roll_skel",
    "right_shoulder_yaw_skel", "right_elbow_skel", "right_wrist_roll_skel", "right_wrist_pitch_skel",
    "right_wrist_yaw_skel", "right_hand_roll_skel",
)
PARENT_INDICES = (-1, 0, 1, 2, 3, 4, 5, 6, 0, 8, 9, 10, 11, 12, 13, 0, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
                  17, 26, 27, 28, 29, 30, 31, 32)
# Axis permutation from MuJoCo (x forward, z up) to the motion skeleton's frame.
MUJOCO_TO_MOTION = np.asarray(((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)))


@dataclass
class ImportedMotion:
    arm_positions: np.ndarray
    fps: float
    source_joint_count: int


class _NumpyOnlyUnpickler(pickle.Unpickler):
    """ARDY sessions are pickles; allow only what rebuilding NumPy arrays needs, nothing that runs code."""

    ALLOWED = {
        ("builtins", "slice"): builtins.slice,
        ("numpy", "dtype"): np.dtype,
        ("numpy", "ndarray"): np.ndarray,
        ("numpy.core.multiarray", "_reconstruct"): np._core.multiarray._reconstruct,
        ("numpy._core.multiarray", "_reconstruct"): np._core.multiarray._reconstruct,
        ("numpy.core.numeric", "_frombuffer"): np._core.numeric._frombuffer,
        ("numpy._core.numeric", "_frombuffer"): np._core.numeric._frombuffer,
    }

    def find_class(self, module: str, name: str) -> object:
        if (module, name) not in self.ALLOWED:
            raise pickle.UnpicklingError(f"ARDY file uses unsupported pickle global {module}.{name}")
        found = self.ALLOWED[(module, name)]
        return found


class MotionFileHelper:
    def __init__(self, arm_joint_names: Sequence[str], mjcf_path: Path = PathConfig.MJCF_PATH) -> None:
        self.arm_joint_names = tuple(arm_joint_names)
        self.projections = self._load_projections(mjcf_path)

    def read_kimodo(self, arrays: dict[str, np.ndarray], fps: float | None) -> ImportedMotion:
        """Kimodo NPZ: local_rot_mats or global_rot_mats; an embedded fps wins over the one given."""
        if "local_rot_mats" in arrays:
            rotations = arrays["local_rot_mats"]
            positions = self.arm_positions_from_local(rotations)
        elif "global_rot_mats" in arrays:
            rotations = arrays["global_rot_mats"]
            positions = self.arm_positions_from_global(rotations)
        else:
            raise ValueError("Kimodo file has neither local_rot_mats nor global_rot_mats")
        if "fps" in arrays:
            fps = float(arrays["fps"])
        if not fps:
            raise ValueError("This Kimodo file has no FPS. Enter the source FPS and load it again.")
        motion = ImportedMotion(positions, float(fps), int(np.shape(rotations)[-3]))
        return motion

    def read_ardy(self, content: bytes) -> ImportedMotion:
        """ARDY interactive-session PKL, version 1.0, 34-joint skeleton."""
        session = _NumpyOnlyUnpickler(io.BytesIO(content)).load()
        motion = session["motion"]
        if motion.get("local_rot_mats") is not None:
            rotations = motion["local_rot_mats"]
            positions = self.arm_positions_from_local(rotations)
        else:
            rotations = motion["joints_rot"]
            positions = self.arm_positions_from_global(rotations)
        imported = ImportedMotion(positions, float(session["model_fps"]), int(np.shape(rotations)[-3]))
        return imported

    def arm_positions_from_global(self, rotations: np.ndarray) -> np.ndarray:
        global_rotations = self._frames(rotations)
        local_rotations = global_rotations.copy()
        for index, parent in enumerate(PARENT_INDICES):
            if parent >= 0:
                parent_rotation = np.swapaxes(global_rotations[:, parent], -1, -2)
                local_rotations[:, index] = parent_rotation @ global_rotations[:, index]
        positions = self.arm_positions_from_local(local_rotations)
        return positions

    def arm_positions_from_local(self, rotations: np.ndarray) -> np.ndarray:
        """Each hinge angle is the joint-frame Euler components projected onto the hinge axis."""
        local_rotations = self._frames(rotations)
        angles = {}
        for name, skeleton_index, frame_to_joint, axis in self.projections:
            joint_rotations = frame_to_joint @ local_rotations[:, skeleton_index]
            euler = np.stack((np.arctan2(joint_rotations[:, 2, 1], joint_rotations[:, 2, 2]),
                              np.arctan2(joint_rotations[:, 0, 2], joint_rotations[:, 0, 0]),
                              np.arctan2(joint_rotations[:, 1, 0], joint_rotations[:, 1, 1])), axis=-1)
            angles[name] = euler @ axis
        positions = np.column_stack([angles[name] for name in self.arm_joint_names])
        return positions

    @staticmethod
    def _frames(rotations: np.ndarray) -> np.ndarray:
        """[frame, 34, 3, 3]; a leading batch of one is dropped."""
        values = np.asarray(rotations, dtype=np.float64)
        if values.ndim == 5:
            values = values[0]
        return values

    def _load_projections(self, mjcf_path: Path) -> list[tuple[str, int, np.ndarray, np.ndarray]]:
        root = ElementTree.parse(mjcf_path).getroot()
        default_axes = {}
        for default in root.iter("default"):
            joint = default.find("joint")
            if default.get("class") and joint is not None and joint.get("axis"):
                default_axes[default.get("class")] = np.fromstring(joint.get("axis"), sep=" ")
        parents = {child: parent for parent in root.iter() for child in parent}
        projections = []
        for joint in root.find("worldbody").iter("joint"):
            name = joint.get("name")
            if name not in self.arm_joint_names:
                continue
            axis = np.fromstring(joint.get("axis"), sep=" ") if joint.get("axis") else default_axes[joint.get("class")]
            axis_motion = MUJOCO_TO_MOTION @ (axis / np.linalg.norm(axis))
            body_rotation = self._quaternion_matrix(parents[joint].get("quat", "1 0 0 0"))
            frame_to_joint = (MUJOCO_TO_MOTION @ body_rotation @ MUJOCO_TO_MOTION.T).T
            axis_in_joint = frame_to_joint @ axis_motion
            skeleton_index = SKELETON_NAMES.index(name.removesuffix("_joint") + "_skel")
            projections.append((name, skeleton_index, frame_to_joint, axis_in_joint / np.linalg.norm(axis_in_joint)))
        return projections

    @staticmethod
    def _quaternion_matrix(text: str) -> np.ndarray:
        w, x, y, z = np.fromstring(text, sep=" ") / np.linalg.norm(np.fromstring(text, sep=" "))
        matrix = np.asarray(((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
                             (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
                             (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y))))
        return matrix


def demo_motion_file_helper() -> None:
    """Identity rotations (the rest pose) through both readers; MJCF body offsets make some angles nonzero."""
    arm_names = [f"{side}_{part}_joint" for side in ("left", "right")
                 for part in ("shoulder_pitch", "shoulder_roll", "shoulder_yaw", "elbow",
                              "wrist_roll", "wrist_pitch", "wrist_yaw")]
    helper = MotionFileHelper(arm_names)
    rest = np.tile(np.eye(3), (5, 34, 1, 1))
    kimodo = helper.read_kimodo({"global_rot_mats": rest}, fps=30.0)
    session = pickle.dumps({"version": "1.0", "model_fps": 25.0, "skeleton": {"nbjoints": 34},
                            "motion": {"joints_rot": rest[None]}})
    ardy = helper.read_ardy(session)
    logger.info("Kimodo {} @ {} Hz, max |angle| {:.2e}", kimodo.arm_positions.shape, kimodo.fps,
                float(np.max(np.abs(kimodo.arm_positions))))
    logger.info("ARDY {} @ {} Hz", ardy.arm_positions.shape, ardy.fps)


def main() -> None:
    use_utf8_output()
    demo_motion_file_helper()


if __name__ == "__main__":
    main()
