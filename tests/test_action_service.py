from __future__ import annotations

import unittest

import numpy as np

from component.action_authoring.service import ActionService
from component.common.action import Action, ActionStep
from component.common.g1_joint_schema import G1JointSchema, PoseType
from component.pose_editing.service import PoseService
from config.settings import RobotConfig
from tests.support import copy_data

HOME = RobotConfig.HOME_POSE_NAME


class ActionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder, data_dir = copy_data()
        schema = G1JointSchema()
        self.service = ActionService(schema, PoseService(schema, data_dir / "poses"),
                                     data_dir / "actions" / "definitions", data_dir / "actions" / "trajectories")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def wave(self, name: str = "test_wave", move: float = 1.0) -> Action:
        action = Action(name, [ActionStep(PoseType.COMPOSED, "concierge_wave_left", move, 0.5),
                               ActionStep(PoseType.BASE, HOME, 1.0)])
        return action

    def test_pink_recompiles_every_saved_action_exactly(self) -> None:
        for name in self.service.names():
            compiled = self.service.compile(self.service.load(name))
            stored = self.service.load_trajectory(name)
            self.assertEqual(compiled.keyframe_indices, stored.keyframe_indices, name)
            np.testing.assert_allclose(compiled.timestamps, stored.timestamps, atol=1e-12)
            np.testing.assert_allclose(compiled.joint_positions, stored.joint_positions, atol=1e-9)

    def test_compile_timing_and_keyframes(self) -> None:
        trajectory = self.service.compile(self.wave())
        self.assertAlmostEqual(trajectory.duration, 2.5)
        self.assertEqual(trajectory.keyframe_names, (HOME, "concierge_wave_left", HOME))
        self.assertEqual(trajectory.keyframe_indices[-1], trajectory.sample_count - 1)
        self.assertEqual(len(trajectory.joint_names), 17)

    def test_save_writes_json_and_npz_and_guards_overwrite(self) -> None:
        self.service.save(self.wave())
        self.assertEqual(self.service.load("test_wave").steps, self.wave().steps)
        self.assertEqual(self.service.load_trajectory("test_wave").sample_count, 64)
        with self.assertRaises(FileExistsError):
            self.service.save(self.wave())
        self.service.save(self.wave(), overwrite=True)

    def test_too_short_move_names_the_pose(self) -> None:
        with self.assertRaisesRegex(ValueError, "too short to move into concierge_wave_left"):
            self.service.compile(self.wave(move=0.01))

    def test_refuses_arm_pose_and_missing_return(self) -> None:
        arm = Action("bad", [ActionStep(PoseType.LEFT_ARM, "concierge_present_left", 1.0),
                             ActionStep(PoseType.BASE, HOME, 1.0)])
        with self.assertRaisesRegex(ValueError, "arm pose"):
            self.service.compile(arm)
        with self.assertRaisesRegex(ValueError, "at least one pose"):
            self.service.compile(Action("bad", [ActionStep(PoseType.BASE, HOME, 1.0)]))


if __name__ == "__main__":
    unittest.main()
