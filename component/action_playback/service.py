"""One player for everything: previews, saved actions and imported files all play here, on the arms only."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import threading
import time
from collections.abc import Mapping

import numpy as np
from loguru import logger

from component.common.action import Trajectory
from component.common.g1_joint_schema import G1JointSchema
from component.robot_state.service import RobotStateService
from config.settings import ActionConfig, use_utf8_output


class PlaybackService:
    """States: empty (nothing loaded), ready, playing, paused, done."""

    def __init__(self, schema: G1JointSchema, robot: RobotStateService, fixed_values: Mapping[str, float]) -> None:
        self.schema = schema
        self.robot = robot
        # Waist and legs, held still under every played sample.
        self.fixed_values = dict(fixed_values)
        self.lock = threading.Lock()
        self.trajectory: Trajectory | None = None
        self.source = ""
        self.state = "empty"
        self.index = 0
        self.loop = False
        self.started_at = 0.0
        self.revision = 0
        threading.Thread(target=self._run, daemon=True).start()

    def hold(self, joint_values: Mapping[str, float]) -> None:
        """Change some of the still joints, e.g. the waist after the home pose is replaced."""
        with self.lock:
            self.fixed_values.update(joint_values)

    def load(self, trajectory: Trajectory, source: str) -> dict:
        """source says where it came from: preview, saved or the imported format."""
        with self.lock:
            self.trajectory = trajectory.only(self.schema.ARM_JOINT_NAMES)
            self.source = source
            self._go_to(0, "ready")
        snapshot = self.snapshot()
        return snapshot

    def play(self) -> dict:
        """Resume where it was paused, otherwise start from the first sample."""
        with self.lock:
            if self.trajectory is None:
                raise ValueError("Load an action first")
            if self.state != "paused":
                self._go_to(0, "playing")
            self.state = "playing"
            self.started_at = time.monotonic() - float(self.trajectory.timestamps[self.index])
            self.revision += 1
        snapshot = self.snapshot()
        return snapshot

    def pause(self) -> dict:
        """Does nothing unless playing, so any edit can call it first."""
        with self.lock:
            if self.state == "playing":
                self.state = "paused"
                self.revision += 1
        snapshot = self.snapshot()
        return snapshot

    def stop(self) -> dict:
        with self.lock:
            if self.trajectory is not None:
                self._go_to(0, "ready")
        snapshot = self.snapshot()
        return snapshot

    def seek(self, index: int) -> dict:
        """Show one exact sample; playback pauses there."""
        with self.lock:
            if self.trajectory is None:
                raise ValueError("Load an action first")
            self._go_to(int(np.clip(index, 0, self.trajectory.sample_count - 1)), "paused")
        snapshot = self.snapshot()
        return snapshot

    def set_loop(self, enabled: bool) -> dict:
        with self.lock:
            self.loop = enabled
            self.revision += 1
        snapshot = self.snapshot()
        return snapshot

    def paused_sample(self) -> tuple[int, float, dict[str, float]]:
        """Index, time and arm values of the sample paused on."""
        with self.lock:
            if self.state != "paused":
                raise ValueError("Pause on the frame you want first")
            sample = (self.index, float(self.trajectory.timestamps[self.index]), self.trajectory.values_at(self.index))
        return sample

    def snapshot(self) -> dict:
        with self.lock:
            trajectory = self.trajectory
            state = {"revision": self.revision, "state": self.state, "loop": self.loop, "source": self.source,
                     "name": trajectory.name if trajectory else "", "index": self.index,
                     "count": trajectory.sample_count if trajectory else 0,
                     "time": float(trajectory.timestamps[self.index]) if trajectory else 0.0,
                     "duration": trajectory.duration if trajectory else 0.0,
                     "phase": self._phase() if trajectory else ""}
        return state

    def _go_to(self, index: int, state: str) -> None:
        """Caller holds the lock."""
        self.index = index
        self.state = state
        self.robot.update({**self.fixed_values, **self.trajectory.values_at(index)})
        self.revision += 1

    def _run(self) -> None:
        while True:
            time.sleep(ActionConfig.PLAYBACK_TICK_SECONDS)
            with self.lock:
                if self.state != "playing":
                    continue
                elapsed = time.monotonic() - self.started_at
                last = self.trajectory.sample_count - 1
                if elapsed >= self.trajectory.duration:
                    if self.loop:
                        self.started_at = time.monotonic()
                        self._go_to(0, "playing")
                    else:
                        self._go_to(last, "done")
                    continue
                index = int(np.searchsorted(self.trajectory.timestamps, elapsed, side="right")) - 1
                if index != self.index:
                    self._go_to(index, "playing")

    def _phase(self) -> str:
        """What the robot is doing at the current sample, in keyframe terms."""
        trajectory = self.trajectory
        now = float(trajectory.timestamps[self.index])
        names, holds = trajectory.keyframe_names, trajectory.keyframe_holds
        arrivals = [float(trajectory.timestamps[index]) for index in trajectory.keyframe_indices]
        # The last keyframe index marks the end of its hold, not its arrival.
        arrivals[-1] -= holds[-1]
        for position, (name, arrival, hold) in enumerate(zip(names, arrivals, holds, strict=True)):
            if abs(now - arrival) < 1e-9 and hold == 0.0:
                return f"At {name}"
            if hold > 0.0 and arrival - 1e-9 <= now <= arrival + hold + 1e-9:
                return f"Holding {name}"
            if position + 1 < len(names) and arrival + hold < now < arrivals[position + 1]:
                return f"Moving {name} → {names[position + 1]}"
        phase = f"At {names[-1]}"
        return phase


def demo_playback_service() -> None:
    """Plays a saved NPZ for a moment, pauses, seeks, then lets it finish."""
    from component.action_playback.motion_import import MotionImport
    from config.settings import PathConfig

    schema = G1JointSchema()
    robot = RobotStateService(schema)
    player = PlaybackService(schema, robot, {name: 0.0 for name in schema.LEG_JOINT_NAMES + schema.WAIST_JOINT_NAMES})
    path = PathConfig.DATA_DIR / "actions" / "trajectories" / "concierge_wave_left.npz"
    importer = MotionImport(schema, robot.kinematics.joint_positions())
    trajectory, file_format = importer.load(path.name, path.read_bytes())
    player.load(trajectory, file_format)
    player.play()
    time.sleep(1.0)
    logger.info("After 1 s: {}", player.pause())
    logger.info("Seek 60: {}", player.seek(60))
    player.play()
    time.sleep(trajectory.duration - trajectory.timestamps[60] + 0.3)
    logger.info("End: {}", player.snapshot())


def main() -> None:
    use_utf8_output()
    demo_playback_service()


if __name__ == "__main__":
    main()
