"""Pink differential IK over the fixed-base G1 URDF."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pink
import pinocchio as pin
from loguru import logger
from pink.tasks import PostureTask

from config.settings import PathConfig, use_utf8_output


@dataclass
class PostureTrajectory:
    """Samples Pink produced while tracking minimum-jerk posture references."""

    joint_names: tuple[str, ...]
    timestamps: np.ndarray
    joint_positions: np.ndarray
    keyframe_indices: tuple[int, ...]
    max_tracking_error: float


class PinkIKHelper:
    def __init__(self, urdf_path: Path = PathConfig.URDF_PATH, **kwargs) -> None:
        self.solver = kwargs.get("solver", "quadprog")
        # A move counts as reached when every joint is this close to its target.
        self.endpoint_tolerance = kwargs.get("endpoint_tolerance", 1e-8)
        self.model = pin.buildModelFromUrdf(str(urdf_path))

    def solve_posture_trajectory(self, keyframes: Sequence[Mapping[str, float]], joint_names: Sequence[str],
                                 durations: Sequence[float], holds: Sequence[float],
                                 sample_hz: float, **kwargs) -> PostureTrajectory:
        """Move through the keyframes one after another; the joints not listed stay where the first keyframe put them.

        Each move follows a minimum-jerk reference that Pink tracks within the URDF position and velocity
        limits. A hold repeats the reached pose. Every keyframe index points at the arrival sample, except
        the last one, which points at the very end. kwargs: labels, one per keyframe, used in errors.
        """
        joint_names = tuple(joint_names)
        labels = kwargs.get("labels") or [f"keyframe {index + 1}" for index in range(len(keyframes))]
        full_keyframes = [self._full_configuration(keyframe) for keyframe in keyframes]
        # Locking every other joint means a solve can only ever move the listed ones.
        locked_ids = [self.model.getJointId(name) for name in self.model.names[1:] if name not in joint_names]
        reduced = pin.buildReducedModel(self.model, locked_ids, full_keyframes[0])
        full_index = [self.model.joints[self.model.getJointId(name)].idx_q for name in joint_names]
        reduced_index = [reduced.joints[reduced.getJointId(name)].idx_q for name in joint_names]

        targets = []
        for values in full_keyframes:
            target = pin.neutral(reduced)
            target[reduced_index] = values[full_index]
            targets.append(target)

        configuration = pink.Configuration(reduced, reduced.createData(), targets[0].copy())
        task = PostureTask(cost=1.0, gain=1.0)
        timestamps = [0.0]
        positions = [configuration.q[reduced_index].copy()]
        keyframe_indices = [0]
        elapsed = 0.0
        max_error = 0.0
        for index, (duration, hold) in enumerate(zip(durations, holds, strict=True)):
            start, target = targets[index], targets[index + 1]
            local_times = np.linspace(0.0, duration, max(1, math.ceil(duration * sample_hz)) + 1)
            for previous_time, local_time in zip(local_times[:-1], local_times[1:], strict=True):
                phase = local_time / duration
                blend = 10.0 * phase**3 - 15.0 * phase**4 + 6.0 * phase**5
                desired = start + blend * (target - start)
                task.set_target(desired)
                step = float(local_time - previous_time)
                velocity = pink.solve_ik(configuration, [task], step, solver=self.solver)
                configuration.integrate_inplace(velocity, step)
                max_error = max(max_error, float(np.max(np.abs(configuration.q - desired))))
                timestamps.append(elapsed + float(local_time))
                positions.append(configuration.q[reduced_index].copy())
            endpoint_error = float(np.max(np.abs(configuration.q - target)))
            if endpoint_error > self.endpoint_tolerance:
                raise ValueError(f"{duration:g} s is too short to move into {labels[index + 1]} within the joint "
                                 f"speed limits (still {endpoint_error:.3f} rad away). Give that move more time.")
            elapsed += duration
            # Snap the clock so keyframes land on their exact requested times.
            timestamps[-1] = elapsed
            arrival_index = len(timestamps) - 1
            if hold > 0.0:
                hold_times = np.linspace(0.0, hold, max(1, math.ceil(hold * sample_hz)) + 1)
                for hold_time in hold_times[1:]:
                    timestamps.append(elapsed + float(hold_time))
                    positions.append(positions[-1].copy())
                elapsed += hold
                timestamps[-1] = elapsed
            is_last = index == len(durations) - 1
            keyframe_indices.append(len(timestamps) - 1 if is_last else arrival_index)

        trajectory = PostureTrajectory(joint_names=joint_names, timestamps=np.asarray(timestamps),
                                       joint_positions=np.asarray(positions), keyframe_indices=tuple(keyframe_indices),
                                       max_tracking_error=max_error)
        return trajectory

    def _full_configuration(self, joint_values: Mapping[str, float]) -> np.ndarray:
        values = pin.neutral(self.model)
        for name, value in joint_values.items():
            values[self.model.joints[self.model.getJointId(name)].idx_q] = value
        return values


def demo_pink_ik_helper() -> None:
    """Raise the left elbow and come back; prints the sample count and the Pink tracking error."""
    helper = PinkIKHelper()
    rest = {"left_elbow_joint": 0.0}
    raised = {"left_elbow_joint": 1.2}
    trajectory = helper.solve_posture_trajectory([rest, raised, rest], ["left_elbow_joint"], [1.0, 1.0],
                                                 [0.5, 0.0], 25.0)
    logger.info("{} samples over {:.2f} s, keyframes {}, max tracking error {:.2e} rad",
                len(trajectory.timestamps), trajectory.timestamps[-1], trajectory.keyframe_indices,
                trajectory.max_tracking_error)


def main() -> None:
    use_utf8_output()
    demo_pink_ik_helper()


if __name__ == "__main__":
    main()
