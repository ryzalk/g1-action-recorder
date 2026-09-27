from __future__ import annotations

import io
import pickle
import unittest

import numpy as np

from component.action_playback.motion_import import MotionImport
from component.common.g1_joint_schema import G1JointSchema
from config.settings import PathConfig


class _RunsCode:
    def __reduce__(self):
        return eval, ("1 + 1",)


def npz_bytes(**arrays) -> bytes:
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    content = buffer.getvalue()
    return content


class MotionImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = G1JointSchema()
        self.importer = MotionImport(self.schema, {name: 0.0 for name in self.schema.UPPER_BODY_JOINT_NAMES})
        self.rest = np.tile(np.eye(3), (5, 34, 1, 1))

    def test_recorder_npz_keeps_arms_only(self) -> None:
        path = PathConfig.BASE_DIR / "data" / "actions" / "trajectories" / "concierge_wave_left.npz"
        trajectory, file_format = self.importer.load(path.name, path.read_bytes())
        self.assertEqual(file_format, "Recorder NPZ")
        self.assertEqual(trajectory.joint_names, self.schema.ARM_JOINT_NAMES)
        self.assertEqual(trajectory.sample_count, 126)

    def test_kimodo_blends_from_and_back_to_home(self) -> None:
        trajectory, file_format = self.importer.load("k.npz", npz_bytes(global_rot_mats=self.rest), fps=30.0)
        self.assertEqual(file_format, "Kimodo NPZ")
        # 30 blend-in samples + 5 motion frames + 30 blend-out samples, sharing the joins.
        self.assertEqual(trajectory.sample_count, 31 + 4 + 30)
        np.testing.assert_allclose(trajectory.joint_positions[0], 0.0)
        np.testing.assert_allclose(trajectory.joint_positions[-1], 0.0)

    def test_kimodo_embedded_fps_and_missing_fps(self) -> None:
        trajectory, _ = self.importer.load("k.npz", npz_bytes(local_rot_mats=self.rest, fps=np.asarray(20.0)))
        self.assertEqual(trajectory.fps, 20.0)
        with self.assertRaisesRegex(ValueError, "no FPS"):
            self.importer.load("k.npz", npz_bytes(global_rot_mats=self.rest))

    def test_ardy_session(self) -> None:
        session = {"version": "1.0", "model_fps": 25.0, "skeleton": {"nbjoints": 34},
                   "motion": {"joints_rot": self.rest[None]}}
        trajectory, file_format = self.importer.load("a.pkl", pickle.dumps(session))
        self.assertEqual((file_format, trajectory.fps), ("ARDY PKL", 25.0))

    def test_ardy_refuses_code(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported pickle global"):
            self.importer.load("bad.pkl", pickle.dumps(_RunsCode()))

    def test_not_an_npz(self) -> None:
        with self.assertRaisesRegex(ValueError, "not an NPZ"):
            self.importer.load("notes.npz", b"hello")


if __name__ == "__main__":
    unittest.main()
