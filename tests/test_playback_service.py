from __future__ import annotations

import time
import unittest

import numpy as np

from component.action_playback.service import PlaybackService
from component.common.action import Trajectory
from component.common.g1_joint_schema import G1JointSchema
from component.robot_state.service import RobotStateService


class PlaybackServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = G1JointSchema()
        self.robot = RobotStateService(self.schema)
        fixed = {name: 0.0 for name in self.schema.LEG_JOINT_NAMES + self.schema.WAIST_JOINT_NAMES}
        self.player = PlaybackService(self.schema, self.robot, fixed)
        # 0.4 s: move 0 -> 1 over 0.2 s, hold 0.1 s, move back over 0.1 s, at 20 Hz.
        timestamps = np.round(np.arange(9) * 0.05, 6)
        elbow = np.asarray([0.0, 0.25, 0.5, 0.75, 1.0, 1.0, 1.0, 0.5, 0.0])
        positions = np.zeros((9, 14))
        positions[:, self.schema.ARM_JOINT_NAMES.index("left_elbow_joint")] = elbow
        self.trajectory = Trajectory("test", self.schema.ARM_JOINT_NAMES, timestamps, positions, (0, 4, 8),
                                     ("home", "up", "home"), (0.0, 0.1, 0.0), 20.0)

    def elbow(self) -> float:
        value = self.robot.snapshot()["joint_positions"]["left_elbow_joint"]
        return value

    def test_load_shows_first_sample(self) -> None:
        self.robot.update({"left_elbow_joint": 1.5})
        snapshot = self.player.load(self.trajectory, "test")
        self.assertEqual((snapshot["state"], snapshot["index"], snapshot["count"]), ("ready", 0, 9))
        self.assertEqual(self.elbow(), 0.0)

    def test_play_runs_to_done(self) -> None:
        self.player.load(self.trajectory, "test")
        self.player.play()
        time.sleep(0.7)
        snapshot = self.player.snapshot()
        self.assertEqual((snapshot["state"], snapshot["index"]), ("done", 8))

    def test_seek_pauses_and_applies_sample(self) -> None:
        self.player.load(self.trajectory, "test")
        snapshot = self.player.seek(3)
        self.assertEqual(snapshot["state"], "paused")
        self.assertEqual(self.elbow(), 0.75)
        self.assertEqual(self.player.paused_sample()[0], 3)

    def test_phase_labels(self) -> None:
        self.player.load(self.trajectory, "test")
        self.assertEqual(self.player.seek(0)["phase"], "At home")
        self.assertEqual(self.player.seek(2)["phase"], "Moving home → up")
        self.assertEqual(self.player.seek(5)["phase"], "Holding up")
        self.assertEqual(self.player.seek(7)["phase"], "Moving up → home")

    def test_pause_is_harmless_when_not_playing(self) -> None:
        self.assertEqual(self.player.pause()["state"], "empty")
        with self.assertRaisesRegex(ValueError, "Pause on the frame"):
            self.player.paused_sample()

    def test_loop_restarts(self) -> None:
        self.player.load(self.trajectory, "test")
        self.player.set_loop(True)
        self.player.play()
        time.sleep(0.7)
        self.assertEqual(self.player.snapshot()["state"], "playing")
        self.player.stop()
        self.assertEqual(self.player.snapshot()["state"], "ready")


if __name__ == "__main__":
    unittest.main()
