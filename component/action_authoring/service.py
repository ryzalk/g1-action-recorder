"""Actions: data/actions/definitions/<name>.json, compiled with Pink into data/actions/trajectories/<name>.npz."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import json

from loguru import logger

from component.common.action import Action, ActionStep, Trajectory
from component.common.g1_joint_schema import G1JointSchema, PoseType
from component.common.naming import clean_name
from component.common.pose import Pose
from component.pose_editing.service import PoseService
from config.settings import ActionConfig, PathConfig, RobotConfig, use_utf8_output
from util.data_file_helper import DataFileHelper
from util.pink_ik_helper import PinkIKHelper


class ActionService:
    # Where an exported zip puts them: the same paths as under data/.
    DEFINITION_DIR = "actions/definitions"
    TRAJECTORY_DIR = "actions/trajectories"

    def __init__(self, schema: G1JointSchema, poses: PoseService,
                 action_dir: Path = PathConfig.DATA_DIR / "actions" / "definitions",
                 trajectory_dir: Path = PathConfig.DATA_DIR / "actions" / "trajectories") -> None:
        self.schema = schema
        self.poses = poses
        self.action_dir = action_dir
        self.trajectory_dir = trajectory_dir
        self.files = DataFileHelper()
        self.ik = PinkIKHelper()

    def names(self) -> list[str]:
        names = self.files.list_names(self.action_dir, ".json")
        return names

    def trajectory_names(self) -> list[str]:
        names = self.files.list_names(self.trajectory_dir, ".npz")
        return names

    def load(self, name: str) -> Action:
        path = self.action_dir / f"{clean_name(name)}.json"
        if not path.exists():
            raise FileNotFoundError(f"No action named {name}")
        action = Action.from_dict(self.files.read_json(path))
        return action

    def compile(self, action: Action, sample_hz: float = ActionConfig.SAMPLE_HZ) -> Trajectory:
        """Sample the whole action with Pink; a move too short for the joint velocity limits is refused."""
        action.name = clean_name(action.name)
        if len(action.steps) < 2:
            raise ValueError("Add at least one pose between the start and the return")
        if (action.steps[-1].pose_type, action.steps[-1].pose_name) != (PoseType.BASE, RobotConfig.HOME_POSE_NAME):
            raise ValueError(f"An action must end at {RobotConfig.HOME_POSE_NAME}")
        for step in action.steps:
            if step.pose_type not in (PoseType.BASE, PoseType.COMPOSED):
                raise ValueError(f"{step.pose_name} is an arm pose; compose it into a whole-body pose first")
            if step.move_seconds <= 0 or step.hold_seconds < 0:
                raise ValueError(f"{step.pose_name}: move time must be above 0 and hold time can't be negative")
        names = [RobotConfig.HOME_POSE_NAME] + [step.pose_name for step in action.steps]
        keyframes = [self.poses.home().joint_values]
        keyframes += [self.poses.load(step.pose_type, step.pose_name).joint_values for step in action.steps]
        solved = self.ik.solve_posture_trajectory(keyframes, self.schema.UPPER_BODY_JOINT_NAMES,
                                                  [step.move_seconds for step in action.steps],
                                                  [step.hold_seconds for step in action.steps], sample_hz,
                                                  labels=names)
        trajectory = Trajectory(name=action.name, joint_names=solved.joint_names, timestamps=solved.timestamps,
                                joint_positions=solved.joint_positions, keyframe_indices=solved.keyframe_indices,
                                keyframe_names=tuple(names),
                                keyframe_holds=(0.0,) + tuple(step.hold_seconds for step in action.steps),
                                fps=sample_hz, max_tracking_error=solved.max_tracking_error)
        return trajectory

    def save(self, action: Action, sample_hz: float = ActionConfig.SAMPLE_HZ, overwrite: bool = False) -> Trajectory:
        """Write the JSON definition and its compiled NPZ together; nothing is written if compiling fails."""
        trajectory = self.compile(action, sample_hz)
        json_path = self.action_dir / f"{action.name}.json"
        npz_path = self.trajectory_path(action.name)
        if not overwrite and (json_path.exists() or npz_path.exists()):
            raise FileExistsError(f"{action.name} already exists")
        self.files.write_json(json_path, action.to_dict(self.schema.model_id), overwrite=True)
        self.files.write_npz(npz_path, trajectory.to_arrays(self.schema.model_id), overwrite=True)
        logger.info("Saved action {} ({} samples, {:.2f} s)", action.name, trajectory.sample_count, trajectory.duration)
        return trajectory

    def load_trajectory(self, name: str) -> Trajectory:
        path = self.trajectory_path(name)
        if not path.exists():
            raise FileNotFoundError(f"No compiled action named {name}")
        trajectory = Trajectory.from_arrays(self.files.read_npz(path))
        return trajectory

    def trajectory_path(self, name: str) -> Path:
        path = self.trajectory_dir / f"{clean_name(name)}.npz"
        return path

    @staticmethod
    def poses_of(action: Action) -> list[tuple[PoseType, str]]:
        """Every pose the action needs to be edited or compiled again, the home pose included."""
        needed = [(PoseType.BASE, RobotConfig.HOME_POSE_NAME)]
        for step in action.steps:
            if (step.pose_type, step.pose_name) not in needed:
                needed.append((step.pose_type, step.pose_name))
        return needed

    def references(self) -> dict[tuple[PoseType, str], list[str]]:
        """Which actions use each pose. The compiled NPZ never needs the pose; the definition does."""
        used = {}
        for name in self.names():
            for pose in self.poses_of(self.load(name)):
                used.setdefault(pose, []).append(name)
        return used

    def delete(self, name: str, trash_dir: Path) -> None:
        """Moves the definition and its compiled trajectory into trash_dir together."""
        json_path = self.action_dir / f"{clean_name(name)}.json"
        if not json_path.exists():
            raise FileNotFoundError(f"No action named {name}")
        self.files.move(json_path, trash_dir / "actions" / "definitions" / json_path.name)
        npz_path = self.trajectory_path(name)
        if npz_path.exists():
            self.files.move(npz_path, trash_dir / "actions" / "trajectories" / npz_path.name)
        logger.info("Moved action {} to {}", name, trash_dir)

    def export_bundle(self, name: str) -> bytes:
        """A zip laid out like data/: the definition and its compiled trajectory together (an action needs
        both to be played), plus every pose it uses so it can be edited again. Unzipped into a data folder
        it is ready to use. An action never compiled is compiled now, so the zip is never half an action."""
        action = self.load(name)
        npz_path = self.trajectory_path(action.name)
        if npz_path.exists():
            trajectory = npz_path.read_bytes()
        else:
            trajectory = self.files.npz_bytes(self.compile(action).to_arrays(self.schema.model_id))
        files = {f"{self.DEFINITION_DIR}/{action.name}.json": (self.action_dir / f"{action.name}.json").read_bytes(),
                 f"{self.TRAJECTORY_DIR}/{action.name}.npz": trajectory}
        for pose_type, pose_name in self.poses_of(action):
            pose = self.poses.load(pose_type, pose_name)
            files[f"poses/{pose_type.value}/{pose_name}.json"] = json.dumps(
                pose.to_dict(self.schema.model_id), ensure_ascii=False, indent=2).encode("utf-8")
        bundle = self.files.pack(files)
        return bundle

    def read_bundle(self, content: bytes, filename: str = "file") -> tuple[Action, list[Pose], float]:
        """The action, the poses packed with it and the sample rate it was compiled at; nothing is saved.
        Takes the data/-style layout and the older one (action.json + trajectory.npz at the top)."""
        try:
            files = self.files.unpack(content)
        except ValueError as error:
            raise ValueError(f"{filename} isn't an action zip; make one with Export in the Library") from error
        definitions = [path for path in files if path.startswith(f"{self.DEFINITION_DIR}/") and path.endswith(".json")]
        definition = definitions[0] if len(definitions) == 1 else "action.json"
        if definition not in files:
            raise ValueError(f"{filename} has no action definition; make action zips with Export in the Library")
        try:
            action = Action.from_dict(json.loads(files[definition].decode("utf-8")))
            action.name = clean_name(action.name)
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(f"{filename} has an unreadable action definition") from error
        poses = [self.poses.parse(data, path) for path, data in sorted(files.items())
                 if path.startswith("poses/") and path.endswith(".json")]
        trajectory = next((data for path, data in files.items()
                           if path.endswith(".npz") and (path.startswith(f"{self.TRAJECTORY_DIR}/")
                                                         or path == "trajectory.npz")), None)
        sample_hz = ActionConfig.SAMPLE_HZ
        if trajectory is not None:
            sample_hz = float(self.files.read_npz_bytes(trajectory)["fps"])
        bundle = (action, poses, sample_hz)
        return bundle

def demo_action_service() -> None:
    """Recompiles every saved action from its JSON and compares with the NPZ on disk; writes nothing."""
    schema = G1JointSchema()
    service = ActionService(schema, PoseService(schema))
    for name in service.names():
        action = service.load(name)
        compiled = service.compile(action)
        stored = service.load_trajectory(name)
        difference = abs(compiled.joint_positions - stored.joint_positions).max()
        logger.info("{}: {} samples, {:.2f} s, differs from the saved NPZ by {:.1e} rad", name,
                    compiled.sample_count, compiled.duration, difference)
    wave = Action("demo_wave", [ActionStep(PoseType.COMPOSED, "concierge_wave_left", 1.5, 0.5),
                                ActionStep(PoseType.BASE, RobotConfig.HOME_POSE_NAME, 1.0)])
    logger.info("A new action compiles to {} samples", service.compile(wave).sample_count)
    logger.info("Poses used by more than one action: {}",
                {f"{t.value}/{n}": len(users) for (t, n), users in service.references().items() if len(users) > 1})
    bundle = service.export_bundle("concierge_wave_left")
    action, poses, sample_hz = service.read_bundle(bundle, "concierge_wave_left.zip")
    logger.info("Bundle of {} bytes: {} with {} at {} Hz", len(bundle), action.name, [p.name for p in poses], sample_hz)


def main() -> None:
    use_utf8_output()
    demo_action_service()


if __name__ == "__main__":
    main()
