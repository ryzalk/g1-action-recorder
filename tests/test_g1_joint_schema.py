from __future__ import annotations

import unittest

from component.common.g1_joint_schema import G1JointSchema, PoseType
from util.robot_model_helper import RobotModelHelper


class G1JointSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = G1JointSchema()

    def test_urdf_mjcf_and_dds_order_agree(self) -> None:
        helper = RobotModelHelper()
        self.assertEqual(tuple(helper.joint_limits()), G1JointSchema.DDS_JOINT_NAMES)
        self.assertEqual(tuple(helper.mjcf_joint_names()), G1JointSchema.DDS_JOINT_NAMES)
        self.assertEqual(len(self.schema.UPPER_BODY_JOINT_NAMES), 17)

    def test_check_returns_canonical_order(self) -> None:
        values = {name: 0.0 for name in reversed(self.schema.LEFT_ARM_JOINT_NAMES)}
        checked = self.schema.check(PoseType.LEFT_ARM, values)
        self.assertEqual(tuple(checked), self.schema.LEFT_ARM_JOINT_NAMES)

    def test_check_refuses_wrong_joint_set(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing"):
            self.schema.check(PoseType.BASE, {"left_elbow_joint": 0.0})

    def test_check_some_refuses_out_of_limit_and_unknown(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside"):
            self.schema.check_some({"left_elbow_joint": 3.0})
        with self.assertRaisesRegex(ValueError, "Unknown joint"):
            self.schema.check_some({"tail_joint": 0.0})

    def test_group(self) -> None:
        self.assertEqual(self.schema.group("waist_yaw_joint"), "waist")
        self.assertEqual(self.schema.group("right_elbow_joint"), "right_arm")


if __name__ == "__main__":
    unittest.main()
