"""The whole API through FastAPI's test client, on a copy of data/ and without the 3D server."""

from __future__ import annotations

import io
import json
import time
import unittest
import zipfile

from config.settings import PathConfig
from tests.support import copy_data

# app.context builds the application on import, so point it at the copy first.
FOLDER, DATA_DIR = copy_data()
PathConfig.DATA_DIR = DATA_DIR

from fastapi.testclient import TestClient  # noqa: E402

from app.context import recorder_context  # noqa: E402
from app.main import create_app  # noqa: E402
from config.settings import RobotConfig  # noqa: E402
from tests.test_speech_service import FakeByteplus, FakeMinimax  # noqa: E402

HOME = RobotConfig.HOME_POSE_NAME


def tearDownModule() -> None:
    FOLDER.cleanup()


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # No test reaches BytePlus or MiniMax, whatever keys .env holds.
        speech = recorder_context.speech
        speech.byteplus, speech.minimax = FakeByteplus(), FakeMinimax()
        speech.catalog.minimax = speech.minimax
        cls.client = TestClient(create_app())

    def test_page_and_scripts(self) -> None:
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.text.count("data-slider"), 17)
        self.assertEqual(self.client.get("/static/js/stage.js").status_code, 200)

    def test_record_pose_with_replace(self) -> None:
        home = self.client.get(f"/api/poses/base/{HOME}").json()["joint_values"]
        arm = {name: value for name, value in home.items() if name.startswith("right_")}
        body = {"pose_type": "right_arm", "name": "api_arm", "joint_positions": arm}
        self.assertEqual(self.client.post("/api/poses", json=body).status_code, 200)
        conflict = self.client.post("/api/poses", json=body)
        self.assertEqual(conflict.status_code, 409)
        self.assertIn("already exists", conflict.json()["detail"])
        self.assertEqual(self.client.post("/api/poses", json={**body, "overwrite": True}).status_code, 200)
        self.assertIn("api_arm", self.client.get("/api/poses").json()["names"]["right_arm"])
        # Record saves an arm or the whole robot as a composed pose (with its picture), never a base pose.
        whole = self.client.post("/api/poses", json={"pose_type": "composed", "name": "api_whole",
                                                     "joint_positions": home})
        self.assertEqual(whole.status_code, 200)
        self.assertTrue((DATA_DIR / "poses" / "composed" / "api_whole.png").exists())
        base = self.client.post("/api/poses", json={"pose_type": "base", "name": "api_whole", "joint_positions": home})
        self.assertEqual(base.status_code, 422)

    def test_pose_preview_picture(self) -> None:
        picture = self.client.get(f"/api/poses/base/{HOME}/preview.png")
        self.assertEqual((picture.status_code, picture.headers["content-type"]), (200, "image/png"))
        self.assertTrue(picture.content.startswith(bytes([0x89]) + b"PNG"))
        arm = self.client.get("/api/poses/left_arm/concierge_speak_3/preview.png")
        self.assertEqual(arm.status_code, 200)
        self.assertNotEqual(arm.content, picture.content)
        # A pose saved before pictures existed gets one on first request, kept beside it.
        self.assertTrue((DATA_DIR / "poses" / "left_arm" / "concierge_speak_3.png").exists())
        self.assertEqual(self.client.get("/api/poses/base/nothing_here/preview.png").status_code, 404)
        # Deleting a pose takes its picture along to the trash.
        self.client.post("/api/poses/compose", json={"base": HOME, "name": "api_gone"})
        self.assertEqual(self.client.delete("/api/library/poses/composed/api_gone").status_code, 200)
        self.assertFalse((DATA_DIR / "poses" / "composed" / "api_gone.png").exists())
        self.assertTrue(list((DATA_DIR / ".trash").glob("*/poses/composed/api_gone.png")))

    def test_mirror_and_bad_joint(self) -> None:
        left = {"left_shoulder_roll_joint": 0.3, "left_shoulder_pitch_joint": 0.1, "left_shoulder_yaw_joint": 0.0,
                "left_elbow_joint": 0.5, "left_wrist_roll_joint": 0.0, "left_wrist_pitch_joint": 0.0,
                "left_wrist_yaw_joint": 0.0}
        mirrored = self.client.post("/api/poses/mirror", json={"source": "left_arm", "joint_positions": left})
        self.assertAlmostEqual(mirrored.json()["joint_positions"]["right_shoulder_roll_joint"], -0.3)
        refused = self.client.put("/api/robot/joints", json={"joint_positions": {"left_elbow_joint": 9.0}})
        self.assertEqual(refused.status_code, 422)

    def test_compose_then_build_save_and_download(self) -> None:
        left = self.client.get("/api/poses").json()["names"]["left_arm"][0]
        saved = self.client.post("/api/poses/compose", json={"base": HOME, "left_arm": left, "name": "api_mix"})
        self.assertEqual((saved.json()["pose_type"], saved.json()["source_parts"]),
                         ("composed", {"base": HOME, "left_arm": left}))
        # Saved with its picture, beside the pose file.
        picture = DATA_DIR / "poses" / "composed" / "api_mix.png"
        self.assertTrue(picture.read_bytes().startswith(bytes([0x89]) + b"PNG"))
        served = self.client.get("/api/poses/composed/api_mix/preview.png")
        self.assertEqual(served.content, picture.read_bytes())
        # Saving it again with another arm draws it again.
        right = self.client.get("/api/poses").json()["names"]["right_arm"][0]
        body = {"base": HOME, "left_arm": left, "right_arm": right, "name": "api_mix", "overwrite": True}
        self.assertEqual(self.client.post("/api/poses/compose", json=body).status_code, 200)
        self.assertNotEqual(picture.read_bytes(), served.content)
        library = self.client.get("/api/library").json()
        entry = next(item for item in library["poses"]["composed"] if item["name"] == "api_mix")
        self.assertEqual(entry["made_from"], {"base": HOME, "left_arm": left, "right_arm": right})
        draft = {"name": "api_action", "return_seconds": 1.0,
                 "steps": [{"pose_type": "composed", "pose_name": "api_mix", "move_seconds": 1.0, "hold_seconds": 0.2}]}
        result = self.client.post("/api/actions", json=draft).json()
        self.assertEqual(result["npz_url"], "/api/actions/api_action/npz")
        self.assertEqual(self.client.get(result["npz_url"]).status_code, 200)
        editor = self.client.get("/api/actions/api_action").json()
        self.assertEqual((editor["steps"][0]["pose_name"], editor["return_seconds"]), ("api_mix", 1.0))

    def test_playback_import_seek_and_capture(self) -> None:
        path = DATA_DIR / "actions" / "trajectories" / "concierge_wave_left.npz"
        loaded = self.client.post("/api/playback/import", params={"filename": path.name}, content=path.read_bytes())
        self.assertEqual((loaded.json()["source"], loaded.json()["count"]), ("Recorder NPZ", 126))
        self.client.post("/api/playback/play", json={})
        time.sleep(0.3)
        self.assertEqual(self.client.post("/api/playback/seek", json={"index": 60}).json()["state"], "paused")
        captured = self.client.post("/api/playback/capture", json={"pose_type": "left_arm", "name": "api_capture"})
        self.assertIn("frame 61/126", captured.json()["notes"])
        # The whole robot from the same frame: both arms from the frame, the waist as shown, with its picture.
        whole = self.client.post("/api/playback/capture", json={"pose_type": "composed", "name": "api_capture_all"})
        self.assertEqual(whole.json()["pose_type"], "composed")
        values = self.client.get("/api/poses/composed/api_capture_all").json()["joint_values"]
        arm = self.client.get("/api/poses/left_arm/api_capture").json()["joint_values"]
        self.assertEqual({name: values[name] for name in arm}, arm)
        self.assertIn("waist_yaw_joint", values)
        self.assertTrue((DATA_DIR / "poses" / "composed" / "api_capture_all.png").exists())
        refused = self.client.post("/api/playback/capture", json={"pose_type": "base", "name": "api_capture_base"})
        self.assertEqual(refused.status_code, 422)
        garbage = self.client.post("/api/playback/import", params={"filename": "x.npz"}, content=b"hello")
        self.assertEqual(garbage.status_code, 422)

    def test_library_delete_export_import(self) -> None:
        name = "concierge_present_right"
        self.assertEqual(self.client.get("/api/library").json()["home"], HOME)
        self.assertEqual(self.client.delete(f"/api/library/poses/base/{HOME}").status_code, 422)
        exported = self.client.get(f"/api/library/actions/{name}/export")
        self.assertEqual(exported.headers["content-type"], "application/zip")
        self.assertIn(f'filename="{name}.zip"', exported.headers["content-disposition"])
        several = self.client.get("/api/library/actions/export",
                                  params={"names": [name, "concierge_wave_left"]})
        self.assertRegex(several.headers["content-disposition"], r'filename="actions_2_[0-9-]+\.zip"')
        self.assertEqual(self.client.get("/api/library/actions/export").status_code, 422)
        self.assertEqual(self.client.get("/api/library/actions/export", params={"names": ["nope"]}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/library/actions/{name}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/library/actions/{name}").status_code, 404)
        imported = self.client.post("/api/library/actions/import", params={"filename": f"{name}.zip"},
                                    content=exported.content)
        self.assertEqual(imported.json()["status"], "added")
        pose = json.loads((DATA_DIR / "poses" / "composed" / f"{name}.json").read_text(encoding="utf-8"))
        pose["joint_values"]["right_elbow_joint"] = 0.4
        params = {"filename": "pose.json"}
        conflict = self.client.post("/api/library/poses/import", params=params, content=json.dumps(pose))
        self.assertEqual(conflict.status_code, 409)
        self.assertTrue(conflict.json()["detail"].endswith("Replace?"))
        replaced = self.client.post("/api/library/poses/import", params={**params, "overwrite": True},
                                    content=json.dumps(pose))
        self.assertEqual(replaced.json()["status"], "replaced")

    def test_unknown_camera_view(self) -> None:
        self.assertEqual(self.client.post("/api/robot/camera/top").status_code, 422)

    def test_websocket_sends_state(self) -> None:
        with self.client.websocket_connect("/api/robot/ws") as socket:
            types = {socket.receive_json()["type"], socket.receive_json()["type"]}
        self.assertEqual(types, {"robot", "playback"})


    def test_speech_plan_direction_generate(self) -> None:
        listing = self.client.get("/api/speech").json()
        self.assertEqual(len(listing["voice_direction"]["presets"]), 150)
        direction = self.client.post("/api/speech/direction", json={"preset_id": "103"}).json()
        self.assertEqual(direction["label"], "自我介绍")
        self.assertIn("像接待机器人向访客介绍自己", direction["prompt"])
        parts = [{"type": "text", "text": "您好！", "tone": {"emotion": "happy"}}, {"type": "sound", "tag": "laughs"},
                 {"type": "pause", "seconds": 0.5}, {"type": "text", "text": "欢迎。"}]
        planned = self.client.post("/api/speech/plan", json={"provider": "minimax", "parts": parts}).json()
        self.assertEqual([request["kind"] for request in planned["requests"]], ["speech", "silence", "speech"])
        refused = self.client.post("/api/speech/plan", json={"provider": "byteplus", "parts": parts})
        self.assertEqual(refused.status_code, 422)
        self.assertIn("MiniMax only", refused.json()["detail"])
        bad_tag = self.client.post("/api/speech/plan",
                                   json={"provider": "minimax", "parts": [{"type": "sound", "tag": "x"}]})
        self.assertEqual(bad_tag.status_code, 422)
        body = {"name": "api_clip", "provider": "minimax", "voice": "English_CalmWoman", "parts": parts}
        clip = self.client.post("/api/speech", json=body).json()
        self.assertEqual((clip["provider"], clip["requests"]), ("minimax", 2))
        self.assertEqual(self.client.post("/api/speech", json=body).status_code, 409)
        audio = self.client.get("/api/speech/api_clip/audio")
        self.assertEqual(audio.content[:4], b"RIFF")
        self.assertEqual(self.client.delete("/api/speech/api_clip").status_code, 200)
        self.assertEqual(self.client.get("/api/speech/api_clip/audio").status_code, 404)

    def test_map_edit_save_restore(self) -> None:
        recorder_context.map.storage.package_dir = DATA_DIR.parent / "map_exports"
        listing = self.client.get("/api/map/maps").json()
        self.assertEqual([entry["folder"] for entry in listing["maps"]], ["RTLAB"])
        self.assertEqual(self.client.post("/api/map/maps/open", json={"folder": "RTLAB"}).json()["folder"], "RTLAB")
        info = self.client.get("/api/map").json()
        self.assertEqual((info["width"], info["height"]), (445, 466))
        self.assertTrue(self.client.get("/api/map/grid.png").content.startswith(bytes([0x89]) + b"PNG"))
        erase = {"tool": "rect_erase", "action": "erase",
                 "geometry": {"polygon": [[0.2, 3.0], [0.8, 3.0], [0.8, 8.5], [0.2, 8.5]]}}
        preview = self.client.post("/api/map/edit/preview", json=erase).json()
        applied = self.client.post("/api/map/edit", json=erase).json()
        self.assertEqual(applied["command"]["map_points"], preview["map_points"])
        self.assertTrue(applied["history"]["dirty"])
        wall = {"tool": "polyline_wall", "action": "obstacle",
                "geometry": {"polyline": [[1, 1], [2, 1]], "width_m": 0.1}}
        self.assertEqual(self.client.post("/api/map/edit", json=wall).json()["command"]["id"], 2)
        self.assertEqual(self.client.post("/api/map/undo").json()["command"]["id"], 2)
        self.assertEqual(self.client.post("/api/map/history/jump/0").json()["moved"], 1)
        self.assertEqual(self.client.post("/api/map/redo").json()["command"]["id"], 1)
        found = self.client.get("/api/map/candidates").json()
        self.assertGreater(len(found), 0)
        # Fencing one off in 3D and taking the fence away (the 3D server isn't running here: a no-op).
        body = {"outline": found[0]["polygon"], "kind": found[0]["kind"]}
        self.assertEqual(self.client.post("/api/map/highlight", json=body).status_code, 200)
        self.assertEqual(self.client.post("/api/map/highlight", json={"outline": []}).status_code, 200)
        self.assertEqual(self.client.post("/api/map/highlight", json={"kind": "other"}).status_code, 422)
        self.assertEqual(self.client.post("/api/map/edit", json={**erase, "tool": "nope"}).status_code, 422)
        saved = self.client.post("/api/map/save").json()
        self.assertFalse(saved["history"]["dirty"])
        package = self.client.get(saved["package_url"])
        self.assertEqual(package.status_code, 200)
        self.assertTrue(saved["package_url"].endswith(".zip"))
        folder = DATA_DIR / "maps" / "RTLAB"
        with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
            names = ["manifest.json", "map.pcd", "ground_map.pcd", "grid.pgm", "grid.yaml"]
            self.assertEqual(sorted(archive.namelist()), sorted(f"RTLAB/{name}" for name in names))
            for name in names:
                self.assertEqual(archive.read(f"RTLAB/{name}"), (folder / name).read_bytes(), name)
        self.assertEqual(self.client.get("/api/map/package/..%2Fsettings.py").status_code, 404)
        restored = self.client.post("/api/map/restore").json()
        self.assertTrue(restored["restored"])
        self.assertEqual(restored["history"]["changed_cells"], 0)
        # The export goes back in as a second map, never over the first.
        opened = self.client.post("/api/map/maps/upload", content=package.content).json()
        self.assertEqual(opened["folder"], "RTLAB-2")
        refused = self.client.post("/api/map/maps/upload", content=b"not a map")
        self.assertEqual(refused.status_code, 422)
        self.assertIn(".zip", refused.json()["detail"])

    def test_voice_lists(self) -> None:
        byteplus = self.client.get("/api/speech/voices/byteplus").json()
        self.assertEqual(len(byteplus["voices"]), 177)
        minimax = self.client.get("/api/speech/voices/minimax").json()
        self.assertIn("my_clone_1", [voice["id"] for voice in minimax["voices"]])
        self.assertEqual(self.client.get("/api/speech/voices/other").status_code, 422)
        options = self.client.get("/api/speech").json()
        self.assertEqual(options["byteplus"]["default_voice"]["name"], "Kian")

    def test_library_made_from(self) -> None:
        composed = self.client.get("/api/library").json()["poses"]["composed"]
        wave = next(pose for pose in composed if pose["name"] == "concierge_wave_right")
        self.assertEqual(wave["made_from"], {"base": HOME, "right_arm": "concierge_wave_right"})


if __name__ == "__main__":
    unittest.main()
