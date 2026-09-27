from __future__ import annotations

import unittest

from component.common.g1_joint_schema import G1JointSchema, PoseType
from component.common.pose import Pose
from component.pose_editing.service import PoseService
from config.settings import RobotConfig
from tests.support import copy_data


class PoseServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder, data_dir = copy_data()
        self.schema = G1JointSchema()
        self.service = PoseService(self.schema, data_dir / "poses")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_every_saved_pose_loads(self) -> None:
        for pose_type, names in self.service.names().items():
            for name in names:
                self.assertEqual(self.service.load(PoseType(pose_type), name).name, name)

    def test_numbers_in_names_sort_as_numbers(self) -> None:
        composed = self.service.names()["composed"]
        self.assertLess(composed.index("concierge_speak_2"), composed.index("concierge_speak_10"))

    def test_save_load_and_overwrite(self) -> None:
        values = {name: 0.1 for name in self.schema.LEFT_ARM_JOINT_NAMES}
        self.service.save(Pose("test_arm", PoseType.LEFT_ARM, values))
        self.assertEqual(self.service.load(PoseType.LEFT_ARM, "test_arm").joint_values, values)
        with self.assertRaises(FileExistsError):
            self.service.save(Pose("test_arm", PoseType.LEFT_ARM, values))
        self.service.save(Pose("test_arm", PoseType.LEFT_ARM, values), overwrite=True)

    def test_save_refuses_unsafe_name(self) -> None:
        values = {name: 0.0 for name in self.schema.LEFT_ARM_JOINT_NAMES}
        with self.assertRaisesRegex(ValueError, "can't contain"):
            self.service.save(Pose("../escape", PoseType.LEFT_ARM, values))

    def test_compose_swaps_in_the_arm(self) -> None:
        left = self.service.names()["left_arm"][0]
        pose = self.service.compose("mix", RobotConfig.HOME_POSE_NAME, left_arm=left)
        arm = self.service.load(PoseType.LEFT_ARM, left).joint_values
        home = self.service.home().joint_values
        self.assertEqual(pose.source_parts, {"base": RobotConfig.HOME_POSE_NAME, "left_arm": left})
        for name in self.schema.LEFT_ARM_JOINT_NAMES:
            self.assertEqual(pose.joint_values[name], arm[name])
        for name in self.schema.RIGHT_ARM_JOINT_NAMES + self.schema.WAIST_JOINT_NAMES:
            self.assertEqual(pose.joint_values[name], home[name])

    def test_mirror_twice_is_the_original(self) -> None:
        left = {name: 0.2 for name in self.schema.LEFT_ARM_JOINT_NAMES}
        right = self.service.mirror(PoseType.LEFT_ARM, left)
        self.assertEqual(right["right_shoulder_roll_joint"], -0.2)
        self.assertEqual(right["right_elbow_joint"], 0.2)
        self.assertEqual(self.service.mirror(PoseType.RIGHT_ARM, right), left)


if __name__ == "__main__":
    unittest.main()

