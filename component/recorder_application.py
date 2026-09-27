"""Facade tying the recorder's business blocks together; the API calls only this."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from collections.abc import Mapping
from datetime import datetime

from loguru import logger

from component.action_authoring.service import ActionService
from component.action_playback.motion_import import MotionImport
from component.action_playback.service import PlaybackService
from component.common.action import Action, ActionStep, Trajectory
from component.common.g1_joint_schema import G1JointSchema, PoseType
from component.common.pose import Pose
from component.map_session.service import MapSession
from component.pose_editing.service import PoseService
from component.robot_display.service import RobotDisplayService
from component.robot_state.service import RobotStateService
from component.speech_generation.service import SpeechService
from config.settings import ActionConfig, MapPathConfig, PathConfig, RobotConfig, use_utf8_output


class RecorderApplication:
    def __init__(self, data_dir: Path | None = None) -> None:
        # Read at construction, not import, so a test can point PathConfig at a copy first.
        self.data_dir = data_dir or PathConfig.DATA_DIR
        data_dir = self.data_dir
        self.schema = G1JointSchema()
        self.poses = PoseService(self.schema, data_dir / "poses")
        self.actions = ActionService(self.schema, self.poses, data_dir / "actions" / "definitions",
                                     data_dir / "actions" / "trajectories")
        self.robot = RobotStateService(self.schema)
        self.robot.update(self.home_values())
        # Playback moves the arms only: the legs stand still and the waist stays at the home pose.
        standing = self.robot.snapshot()["joint_positions"]
        self.playback = PlaybackService(self.schema, self.robot,
                                        {name: standing[name] for name in self.schema.LEG_JOINT_NAMES})
        self.imports = MotionImport(self.schema, self.home_values())
        self._apply_home()
        self.display = RobotDisplayService(self.robot)
        self.speech = SpeechService(data_dir / "tts")
        # The Map page's own block: one folder per map under data/maps, exported zips under output/map_exports.
        self.map = MapSession(map_root=data_dir / "maps", package_dir=MapPathConfig.PACKAGE_DIR)

    def home_values(self) -> dict[str, float]:
        values = self.poses.home().joint_values
        return values

    def joint_rows(self) -> list[dict]:
        """The 17 editable joints, grouped waist / left arm / right arm, for the Record page."""
        home = self.home_values()
        rows = []
        for name in self.schema.UPPER_BODY_JOINT_NAMES:
            short = name.removesuffix("_joint").removeprefix("waist_").removeprefix("left_").removeprefix("right_")
            limit = self.schema.limits[name]
            rows.append({"name": name, "label": short.replace("_", " ").capitalize(), "group": self.schema.group(name),
                         "lower": limit.lower, "upper": limit.upper, "home": home[name]})
        return rows

    # Record pose
    def move_joints(self, joint_values: Mapping[str, float]) -> int:
        """Any hand edit pauses playback first, so the player doesn't pull the robot back."""
        self.playback.pause()
        revision = self.robot.update(joint_values)
        return revision

    def save_recorded_pose(self, pose_type: PoseType, name: str, joint_values: Mapping[str, float],
                           overwrite: bool = False) -> Pose:
        if pose_type is PoseType.COMPOSED:
            raise ValueError("Save a base, left-arm or right-arm pose")
        values = self.schema.check(pose_type, joint_values)
        self.move_joints(values)
        pose = Pose(name, pose_type, values)
        self.poses.save(pose, overwrite)
        if self._is_home(pose.pose_type, pose.name):
            self._apply_home()
        return pose

    def mirror_arm(self, source: PoseType, joint_values: Mapping[str, float]) -> dict[str, float]:
        mirrored = self.poses.mirror(source, joint_values)
        self.move_joints({**joint_values, **mirrored})
        return mirrored

    def show_pose(self, pose_type: PoseType, name: str) -> Pose:
        pose = self.poses.load(pose_type, name)
        self.move_joints(pose.joint_values)
        return pose

    # Compose pose
    def preview_composition(self, base: str, left_arm: str = "", right_arm: str = "") -> Pose:
        pose = self.poses.compose("preview", base, left_arm, right_arm)
        self.move_joints(pose.joint_values)
        return pose

    def save_composition(self, name: str, base: str, left_arm: str = "", right_arm: str = "",
                         overwrite: bool = False, pose_type: PoseType = PoseType.BASE) -> Pose:
        """Saved as a base pose (the whole combination, with the parts it was made from) or as one arm of it."""
        if pose_type is PoseType.COMPOSED:
            raise ValueError("Save a composition as a base, left-arm or right-arm pose")
        composed = self.poses.compose(name, base, left_arm, right_arm)
        self.move_joints(composed.joint_values)
        values = {joint: composed.joint_values[joint] for joint in self.schema.joint_names(pose_type)}
        pose = Pose(name, pose_type, values, source="composition", source_parts=composed.source_parts)
        self.poses.save(pose, overwrite)
        if self._is_home(pose.pose_type, pose.name):
            self._apply_home()
        return pose

    # Build action
    def build_action(self, name: str, steps: list[dict], return_seconds: float) -> Action:
        """steps are the poses between start and return; the return to home is added here."""
        action_steps = [ActionStep(PoseType(step["pose_type"]), step["pose_name"], float(step["move_seconds"]),
                                   float(step.get("hold_seconds", 0.0))) for step in steps]
        action_steps.append(ActionStep(PoseType.BASE, RobotConfig.HOME_POSE_NAME, float(return_seconds)))
        action = Action(name, action_steps)
        return action

    def open_action(self, name: str) -> dict:
        """An action as the editor shows it: the middle steps plus the return time."""
        action = self.actions.load(name)
        steps = [{"pose_type": step.pose_type.value, "pose_name": step.pose_name, "move_seconds": step.move_seconds,
                  "hold_seconds": step.hold_seconds} for step in action.steps[:-1]]
        editor = {"name": action.name, "steps": steps, "return_seconds": action.steps[-1].move_seconds,
                  "has_npz": self.actions.trajectory_path(name).exists()}
        return editor

    def preview_action(self, name: str, steps: list[dict], return_seconds: float,
                       sample_hz: float = ActionConfig.SAMPLE_HZ) -> dict:
        trajectory = self.actions.compile(self.build_action(name or "preview", steps, return_seconds), sample_hz)
        self.playback.load(trajectory, "preview")
        snapshot = self.playback.play()
        return snapshot

    def save_action(self, name: str, steps: list[dict], return_seconds: float,
                    sample_hz: float = ActionConfig.SAMPLE_HZ, overwrite: bool = False) -> Trajectory:
        trajectory = self.actions.save(self.build_action(name, steps, return_seconds), sample_hz, overwrite)
        return trajectory

    # Play action
    def play_saved(self, name: str) -> dict:
        self.playback.load(self.actions.load_trajectory(name), "saved")
        snapshot = self.playback.play()
        return snapshot

    def import_motion(self, filename: str, content: bytes, fps: float | None = None) -> dict:
        """The file is read and loaded into the player, never copied into data/."""
        trajectory, file_format = self.imports.load(filename, content, fps)
        snapshot = self.playback.load(trajectory, file_format)
        return snapshot

    def capture_arm_pose(self, pose_type: PoseType, name: str, overwrite: bool = False) -> Pose:
        """Save one arm of the frame playback is paused on."""
        if pose_type not in (PoseType.LEFT_ARM, PoseType.RIGHT_ARM):
            raise ValueError("Capture saves a left-arm or right-arm pose")
        index, seconds, values = self.playback.paused_sample()
        snapshot = self.playback.snapshot()
        note = f"Captured from {snapshot['name']!r}, frame {index + 1}/{snapshot['count']} at {seconds:.2f} s."
        pose = Pose(name, pose_type, {joint: values[joint] for joint in self.schema.joint_names(pose_type)},
                    notes=note)
        self.poses.save(pose, overwrite)
        return pose

    # Library
    def library(self) -> dict:
        """Every saved pose and action, with what depends on what, for the Library tab."""
        used_by = self.actions.references()
        part_of = self.poses.parts()
        poses = {pose_type: [{"name": name, "home": self._is_home(PoseType(pose_type), name),
                              "used_by": used_by.get((PoseType(pose_type), name), []),
                              "part_of": part_of.get((PoseType(pose_type), name), [])} for name in names]
                 for pose_type, names in self.poses.names().items()}
        # A pose saved from Compose names the parts it was made from; they may have been deleted since.
        made_from = {(made["pose_type"], made["name"]): made["source_parts"] for made in self.poses.compositions()}
        for pose_type, entries in poses.items():
            for entry in entries:
                entry["made_from"] = made_from.get((pose_type, entry["name"]), {})
        compiled = self.actions.trajectory_names()
        actions = []
        for name in self.actions.names():
            action = self.actions.load(name)
            actions.append({"name": name, "poses": len(self.actions.poses_of(action)),
                            "seconds": action.total_seconds, "compiled": name in compiled})
        listing = {"poses": poses, "actions": actions, "home": RobotConfig.HOME_POSE_NAME}
        return listing

    def delete_pose(self, pose_type: PoseType, name: str) -> Path:
        """Refused while an action needs the pose; composed poses hold their own copy of a part's values."""
        if self._is_home(pose_type, name):
            raise ValueError(f"{name} is where every action starts and ends, so it can't be deleted")
        users = self.actions.references().get((pose_type, name), [])
        if users:
            which = "that action" if len(users) == 1 else "those actions"
            raise ValueError(f"{name} is used by {', '.join(users)}. Delete or edit {which} first.")
        moved = self.poses.delete(pose_type, name, self._trash_dir())
        return moved

    def delete_action(self, name: str) -> None:
        self.actions.delete(name, self._trash_dir())

    def import_pose(self, filename: str, content: bytes, overwrite: bool = False) -> dict:
        """One pose file from anywhere; a different pose under the same name is replaced only when asked."""
        pose = self.poses.parse(content, filename)
        status = "added"
        if self.poses.exists(pose.pose_type, pose.name):
            status = "unchanged" if self.poses.matches(pose) else "replaced"
        if status == "replaced" and not overwrite:
            raise FileExistsError(self._replace_question([f"{pose.pose_type.value}/{pose.name}"]))
        if status != "unchanged":
            self.poses.save(pose, overwrite=True)
        if status == "replaced" and self._is_home(pose.pose_type, pose.name):
            self._apply_home()
        result = {"name": pose.name, "pose_type": pose.pose_type.value, "status": status}
        return result

    def import_action(self, filename: str, content: bytes, overwrite: bool = False) -> dict:
        """An exported action zip: its poses are saved first, then the action is compiled here from them."""
        action, poses, sample_hz = self.actions.read_bundle(content, filename)
        packed = {(pose.pose_type, pose.name) for pose in poses}
        missing = [f"{pose_type.value}/{name}" for pose_type, name in self.actions.poses_of(action)
                   if (pose_type, name) not in packed and not self.poses.exists(pose_type, name)]
        if missing:
            raise ValueError(f"{filename} doesn't include {', '.join(missing)}, and there is no such pose here")
        added = [pose for pose in poses if not self.poses.exists(pose.pose_type, pose.name)]
        replaced = [pose for pose in poses if pose not in added and not self.poses.matches(pose)]
        changed = [f"{pose.pose_type.value}/{pose.name}" for pose in replaced]
        status = "added"
        if action.name in self.actions.names():
            same = self.actions.load(action.name).to_dict(self.schema.model_id) == action.to_dict(self.schema.model_id)
            status = "unchanged" if same and not replaced else "replaced"
            if not same:
                changed.insert(0, f"action {action.name}")
        if changed and not overwrite:
            raise FileExistsError(self._replace_question(changed))
        for pose in added + replaced:
            self.poses.save(pose, overwrite=True)
        if status != "unchanged":
            self.actions.save(action, sample_hz, overwrite=True)
        if any(self._is_home(pose.pose_type, pose.name) for pose in replaced):
            self._apply_home()
        result = {"name": action.name, "status": status, "poses_added": [pose.name for pose in added],
                  "poses_replaced": [pose.name for pose in replaced]}
        return result

    @staticmethod
    def _is_home(pose_type: PoseType, name: str) -> bool:
        home = (pose_type, name) == (PoseType.BASE, RobotConfig.HOME_POSE_NAME)
        return home

    @staticmethod
    def _replace_question(labels: list[str]) -> str:
        """The 409 text; the page asks it as is and sends again with overwrite."""
        question = f"{', '.join(labels)} already {'exists' if len(labels) == 1 else 'exist'} with different content."
        if f"base/{RobotConfig.HOME_POSE_NAME}" in labels:
            question += f" {RobotConfig.HOME_POSE_NAME} is where every action starts and ends."
        question += " Replace?"
        return question

    def _trash_dir(self) -> Path:
        """Deleted files go to data/.trash/<time>/ under their data/ paths, so restoring is a move back."""
        trash_dir = self.data_dir / ".trash" / datetime.now().strftime("%Y%m%d-%H%M%S")
        return trash_dir

    def _apply_home(self) -> None:
        """Playback holds the waist at home and imports blend from home; keep both on the saved pose."""
        home = self.home_values()
        self.playback.hold({name: home[name] for name in self.schema.WAIST_JOINT_NAMES})
        self.imports.set_home(home)


def demo_recorder_application() -> None:
    """Works on a copy of data/ under output/demo; the real data is only read."""
    import shutil

    copy_dir = PathConfig.DEMO_DIR / "recorder_data"
    shutil.rmtree(copy_dir, ignore_errors=True)
    shutil.copytree(PathConfig.DATA_DIR, copy_dir)
    application = RecorderApplication(copy_dir)
    logger.info("{} joint rows; poses {}", len(application.joint_rows()),
                {pose_type: len(names) for pose_type, names in application.poses.names().items()})
    home = application.home_values()
    left = {name: home[name] for name in application.schema.LEFT_ARM_JOINT_NAMES}
    left["left_elbow_joint"] = 1.2
    application.save_recorded_pose(PoseType.LEFT_ARM, "demo_left", left)
    application.save_composition("demo_composed", RobotConfig.HOME_POSE_NAME, left_arm="demo_left")
    steps = [{"pose_type": "base", "pose_name": "demo_composed", "move_seconds": 1.0, "hold_seconds": 0.5}]
    trajectory = application.save_action("demo_action", steps, 1.0)
    logger.info("Saved demo_action: {} samples; editor view {}", trajectory.sample_count,
                application.open_action("demo_action"))
    application.play_saved("demo_action")
    logger.info("Seek: {}", application.playback.seek(20))
    logger.info("Captured {}", application.capture_arm_pose(PoseType.LEFT_ARM, "demo_capture").notes)
    listing = application.library()
    logger.info("Library: {} actions; made in Compose {}", len(listing["actions"]),
                [entry for entry in listing["poses"]["base"] if entry["made_from"]])
    bundle = application.actions.export_bundle("demo_action")
    application.delete_action("demo_action")
    logger.info("Delete demo_composed now that no action uses it: {}",
                application.delete_pose(PoseType.BASE, "demo_composed"))
    logger.info("Import the exported zip: {}", application.import_action("demo_action.zip", bundle))
    logger.info("Import it again: {}", application.import_action("demo_action.zip", bundle)["status"])


def main() -> None:
    use_utf8_output()
    demo_recorder_application()


if __name__ == "__main__":
    main()
