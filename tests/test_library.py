"""Library rules on the facade: what may be deleted, where it goes, and importing poses and action zips."""

from __future__ import annotations

import json
import unittest

import numpy as np

from component.common.g1_joint_schema import PoseType
from component.recorder_application import RecorderApplication
from config.settings import RobotConfig
from tests.support import copy_data
from util.data_file_helper import DataFileHelper

HOME = RobotConfig.HOME_POSE_NAME
WAVE = "concierge_wave_left"


class LibraryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder, self.data_dir = copy_data()
        self.application = RecorderApplication(self.data_dir)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def pose_bytes(self, pose_type: str, name: str, **changes: float) -> bytes:
        payload = json.loads((self.data_dir / "poses" / pose_type / f"{name}.json").read_text(encoding="utf-8"))
        payload["joint_values"].update(changes)
        content = json.dumps(payload).encode("utf-8")
        return content

    def test_listing_shows_what_uses_what(self) -> None:
        listing = self.application.library()
        home = listing["poses"]["base"][0]
        self.assertTrue(home["home"])
        self.assertEqual(len(home["used_by"]), len(listing["actions"]))
        wave = next(pose for pose in listing["poses"]["composed"] if pose["name"] == WAVE)
        self.assertEqual(wave["used_by"], [WAVE])
        self.assertTrue(all(action["compiled"] for action in listing["actions"]))

    def test_delete_rules_and_trash(self) -> None:
        with self.assertRaisesRegex(ValueError, "can't be deleted"):
            self.application.delete_pose(PoseType.BASE, HOME)
        with self.assertRaisesRegex(ValueError, f"used by {WAVE}. Delete or edit that action first"):
            self.application.delete_pose(PoseType.COMPOSED, WAVE)
        self.application.delete_action(WAVE)
        self.assertNotIn(WAVE, self.application.actions.names())
        self.assertNotIn(WAVE, self.application.actions.trajectory_names())
        moved = self.application.delete_pose(PoseType.COMPOSED, WAVE)
        trash = moved.parents[2]
        self.assertEqual(trash.parent, self.data_dir / ".trash")
        self.assertTrue((trash / "actions" / "definitions" / f"{WAVE}.json").exists())
        self.assertTrue((trash / "actions" / "trajectories" / f"{WAVE}.npz").exists())
        self.assertEqual(moved, trash / "poses" / "composed" / f"{WAVE}.json")
        with self.assertRaises(FileNotFoundError):
            self.application.delete_action(WAVE)

    def test_import_pose(self) -> None:
        arm = self.application.poses.names()["left_arm"][0]
        same = self.application.import_pose("a.json", self.pose_bytes("left_arm", arm))
        self.assertEqual(same["status"], "unchanged")
        changed = self.pose_bytes("left_arm", arm, left_elbow_joint=0.4)
        with self.assertRaisesRegex(FileExistsError, f"left_arm/{arm} already exists with different content"):
            self.application.import_pose("a.json", changed)
        self.assertEqual(self.application.import_pose("a.json", changed, overwrite=True)["status"], "replaced")
        self.assertEqual(self.application.poses.load(PoseType.LEFT_ARM, arm).joint_values["left_elbow_joint"], 0.4)
        renamed = json.loads(changed)
        renamed["name"] = "imported_arm"
        self.assertEqual(self.application.import_pose("b.json", json.dumps(renamed).encode())["status"], "added")
        with self.assertRaisesRegex(ValueError, "notes.json isn't a pose file"):
            self.application.import_pose("notes.json", b"not json")
        with self.assertRaisesRegex(ValueError, "is a pose for"):
            self.application.import_pose("h1.json", json.dumps({**renamed, "robot_model_id": "h1"}).encode())

    def test_replacing_home_moves_the_held_waist(self) -> None:
        changed = self.pose_bytes("base", HOME, waist_yaw_joint=0.2, left_elbow_joint=0.3)
        with self.assertRaisesRegex(FileExistsError, "every action starts and ends"):
            self.application.import_pose("home.json", changed)
        self.application.import_pose("home.json", changed, overwrite=True)
        self.assertEqual(self.application.playback.fixed_values["waist_yaw_joint"], 0.2)
        elbow = self.application.schema.ARM_JOINT_NAMES.index("left_elbow_joint")
        self.assertEqual(self.application.imports.home_arms[elbow], 0.3)

    def test_action_zip_round_trip(self) -> None:
        bundle = self.application.actions.export_bundle(WAVE)
        names = set(DataFileHelper().unpack(bundle))
        self.assertTrue({f"actions/definitions/{WAVE}.json", f"actions/trajectories/{WAVE}.npz",
                         f"poses/composed/{WAVE}.json", "poses/base/concierge_init.json"} <= names, names)
        original = self.application.actions.load_trajectory(WAVE).joint_positions
        self.assertEqual(self.application.import_action("wave.zip", bundle)["status"], "unchanged")
        self.application.delete_action(WAVE)
        self.application.delete_pose(PoseType.COMPOSED, WAVE)
        result = self.application.import_action("wave.zip", bundle)
        self.assertEqual((result["status"], result["poses_added"]), ("added", [WAVE]))
        np.testing.assert_array_equal(self.application.actions.load_trajectory(WAVE).joint_positions, original)
        self.application.import_pose("wave.json", self.pose_bytes("composed", WAVE, left_elbow_joint=0.4),
                                     overwrite=True)
        with self.assertRaisesRegex(FileExistsError, f"composed/{WAVE} already exists"):
            self.application.import_action("wave.zip", bundle)
        result = self.application.import_action("wave.zip", bundle, overwrite=True)
        self.assertEqual((result["status"], result["poses_replaced"]), ("replaced", [WAVE]))

    def test_bad_action_zips(self) -> None:
        files = DataFileHelper()
        with self.assertRaisesRegex(ValueError, "wave.zip isn't an action zip"):
            self.application.import_action("wave.zip", b"plain text")
        with self.assertRaisesRegex(ValueError, "has no action definition"):
            self.application.import_action("wave.zip", files.pack({"readme.txt": b"hi"}))
        definition = self.data_dir / "actions" / "definitions" / f"{WAVE}.json"
        action_only = files.pack({"action.json": definition.read_bytes()})
        self.application.delete_action(WAVE)
        self.application.delete_pose(PoseType.COMPOSED, WAVE)
        with self.assertRaisesRegex(ValueError, f"doesn't include composed/{WAVE}"):
            self.application.import_action("wave.zip", action_only)


    def test_export_compiles_a_missing_trajectory(self) -> None:
        # An action whose NPZ went missing still exports whole: the trajectory is compiled into the zip.
        stored = self.application.actions.load_trajectory(WAVE).joint_positions
        self.application.actions.trajectory_path(WAVE).unlink()
        files = DataFileHelper().unpack(self.application.actions.export_bundle(WAVE))
        arrays = DataFileHelper().read_npz_bytes(files[f"actions/trajectories/{WAVE}.npz"])
        np.testing.assert_allclose(arrays["joint_positions"], stored, atol=1e-9)

    def test_older_action_zip_still_imports(self) -> None:
        files = DataFileHelper()
        new = files.unpack(self.application.actions.export_bundle(WAVE))
        old = {("action.json" if path.startswith("actions/definitions/") else
                "trajectory.npz" if path.startswith("actions/trajectories/") else path): data
               for path, data in new.items()}
        self.assertEqual(self.application.import_action("old.zip", files.pack(old))["status"], "unchanged")

if __name__ == "__main__":
    unittest.main()
