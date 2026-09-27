# G1 Concierge Studio

Record Unitree G1 upper-body poses, compose them, sequence them into timed actions compiled with
Pink, and play actions or imported motions in a Viser 3D view. Beside that: generate the robot's speech
with BytePlus or MiniMax (tones, pauses, sound tags), and clean up G1 map packages (ghosts, obstacles).
Simulation only: nothing here sends commands to a real robot.

## Setup

Python 3.10, managed by uv.

**Linux / macOS**

```bash
uv sync
```

**Windows** (PowerShell): PyPI's pinocchio (`pin`, needed by Pink) has no Windows wheels, so
pinocchio comes from conda-forge and uv installs everything else on top of it:

```powershell
conda create -y -n g1-pinocchio -c conda-forge --override-channels python=3.10 pinocchio
uv venv --python "$env:USERPROFILE\anaconda3\envs\g1-pinocchio\python.exe" --system-site-packages
uv sync
```

Speech needs `BYTEPLUS_API_KEY=...` and/or `MINIMAX_API_KEY=...` in `.env` (see `.env.example`);
everything else works without them, and a provider without a key shows a gray dot and turns Generate off.

## Run

```bash
uv run python app/main.py
```

Open http://127.0.0.1:8930 (the robot's 3D view is served on 8931 and the map's on 8932, both embedded in
the page). Or right-click `app/main.py` in the IDE and run it. To try things without touching `data/`,
point the app at a copy: set `G1_RECORDER_DATA_DIR` to that folder before starting.

## Using it

The sidebar follows the workflow (1–4), then Library, Map and Speech. Left and right always mean the
robot's own sides. Record, Compose and Build share one pattern: Open and New at the top, the editor in
the middle, Save as, Name and Save at the bottom (Record: Left arm / Right arm / Composed; Compose: Composed).

1. **Record pose**: open any saved pose (base, composed, left or right arm) as a starting point or start
   New from `concierge_init`, drag the arm sliders (degrees) or type values, then choose **Save as** Left
   arm, Right arm or Composed (base + left arm + right arm). The waist is always shown but locked: it comes
   from the base pose. The arm a left- or right-arm pose doesn't keep folds away. Opening a pose sets Save
   as to its type (a base pose opens as Composed).
   Each joint has its own reset and each group a Reset (both back to `concierge_init`); the arms have
   Copy to other arm (mirrored).
2. **Compose pose**: pick a base pose and optionally swap in saved left/right arm poses, then save it as
   a composed pose (it remembers its parts; Open brings them back). Base and composed poses go into
   actions.
3. **Build action**: list poses with move and hold times. Add a pose opens a picker with a picture of
   every base and composed pose; each step shows its picture too. Every pose is saved with its picture
   (`data/poses/<type>/<name>.png`, drawn with MuJoCo on save; older poses get one when first shown). Every action starts and ends at
   `concierge_init`. Preview plays it without saving; Save writes the definition (JSON) and the compiled
   trajectory (NPZ) together, and Export .zip then hands over both with the poses they use.
4. **Play action**: play a saved action or open a motion file (an action NPZ saved here, a Kimodo NPZ,
   an ARDY PKL). A Kimodo file without its own fps is read at Kimodo's 30 fps.
   Only the arms move. Pause on a frame and save it the same way
   as Record: Save as Left arm, Right arm or Composed (the waist as shown, both arms from the frame).

Beside the workflow:

- **Library**: every saved action and pose, with what uses what. Delete moves files to
  `data/.trash/<time>/` (same paths as under `data/`, so restoring is moving them back).
  `concierge_init` and any pose an action uses can't be deleted; delete or edit that action first.
  Poses made in Compose keep their own copy of their parts, so an arm pose can go. Import pose takes one
  pose `.json`. Tick one, several or all actions and Export selected: one `.zip` laid out like `data/`
  (`actions/definitions`, `actions/trajectories`, `poses/<type>/` with each pose's picture), every shared
  pose once. Import action takes such a `.zip` (one or many actions), which carries the definitions, the
  trajectories and every pose they use (older zips with `action.json` still import). Anything that would change an existing pose or action is listed and asked
  about first; the action is compiled again here from the imported poses.
- **Map**: open a G1 map (`data/maps/<name>/`, one folder per map) or upload a map `.zip`, then clean
  it: erase ghosts (lasso, rectangle, brush; the grid is cleared and the points in the height band
  deleted, shown red in 3D, and confirmed before anything changes), add obstacles (wall, polygon,
  rectangle, brush), snap to the building's main direction, check the suspected ghosts (fuchsia) and gaps (blue): while
  checking, the point projection turns grey; clicking one spotlights it (the rest of the map dims) and fences
  it off in 3D, Esc shows them all again;
  undo, redo and jump in the history. Save & export writes the folder (the first save keeps the
  originals as `*.orig.*`, every save the version before in `.backup/`) and downloads the folder's own
  files (`manifest.json`, `map.pcd`, `ground_map.pcd`, `grid.pgm`, `grid.yaml`) as a `.zip`, a copy of
  which stays in `output/map_exports/`. Upload takes that `.zip`. Restore original puts
  the originals back. Ported from `services/map-editor`.
- **Speech · BytePlus** and **Speech · MiniMax**: write the script, select text and give it a tone,
  put pauses (and, on MiniMax speech-2.8, sound tags like `(laughs)`) at the cursor. BytePlus tones
  are its Voice Direction: 150 scene presets (Chinese names, as in `services/concierge-audio`) and nine
  fields under Advanced, turned into a prompt that is shown but never spoken. MiniMax tones are its
  eight emotions plus a pace for that part. Each differently toned part is one request; pauses between
  them are silence; everything is joined into one 16 kHz mono 16-bit WAV. Clips list on both pages
  and Edit loads a clip back into its editor. Voices are chosen in a panel with every voice of the
  service (BytePlus: the 177 of the official TTS 2.0 list with their recordings; MiniMax: your
  account's list, system and cloned, 332+), filtered by the language each speaks, gender and scenario,
  and heard before choosing. Samples are files made ahead of time in `data/tts/sample/<provider>/`
  (BytePlus: its official recordings; MiniMax: each voice saying one line in its own language); the
  page never generates one. Make or top them up with
  `uv run python component/speech_generation/voice_samples.py --build [byteplus|minimax]` (skips what
  is there; about 130 MB + 45 MB, in git with the rest of data/).

The playback bar under the 3D view is shared by the four workflow pages: play/pause, stop, frame step,
scrub (drag pauses), loop. Saving over an existing name, deleting, and anything else that can't be
undone asks in a dialog first.

## Data

```text
data/
├── poses/{base,left_arm,right_arm,composed}/<name>.json   schema 1, with <name>.png, its picture
├── actions/definitions/<name>.json                         schema 1: poses + move/hold seconds
├── actions/trajectories/<name>.npz                         schema 2: sampled trajectory
├── tts/<name>.wav + <name>.json                            speech clips (schema 2: provider, voice, script, requests)
├── tts/sample/{byteplus,minimax}/<voice>.wav               voice samples, made ahead
├── maps/<name>/                                            G1 maps: grid.pgm/.yaml, map.pcd, ground_map.pcd, manifest.json (git ignores it)
└── .trash/<YYYYmmdd-HHMMSS>/...                            what Library deleted (git ignores it)
```

An exported action zip is laid out like `data/`: `actions/definitions/<name>.json`,
`actions/trajectories/<name>.npz` and `poses/<type>/<name>.json` for every pose the action uses,
`concierge_init` included; unzipped into a data folder it is ready to use. An action with no NPZ is
compiled for the export.

Trajectory NPZ arrays: `schema_version` (2), `action_name`, `robot_model_id`, `fps`, `joint_names`
(17 upper-body joints), `timestamps`, `joint_positions` `[sample, joint]` in radians,
`keyframe_sample_indices`, `source_pose_names`, `keyframe_hold_seconds`, `max_tracking_error`.
Moves follow a minimum-jerk reference tracked by Pink within the URDF position and velocity limits;
a move too short to reach its pose is refused.

## API

The page does everything through these; other programs can use them too.

| Route | Does |
| --- | --- |
| `GET /api/robot`, `PUT /api/robot/joints`, `WS /api/robot/ws` | robot state; the socket pushes state and playback, takes slider moves |
| `POST /api/robot/camera/{view}` | front, front_left, left, back, right, front_right |
| `GET/POST /api/poses`, `POST /api/poses/{type}/{name}/show`, `POST /api/poses/mirror`, `POST /api/poses/compose[/preview]` | poses |
| `GET/POST /api/actions`, `GET /api/actions/{name}`, `POST /api/actions/preview`, `GET /api/actions/{name}/npz` | actions |
| `POST /api/playback/{play,pause,stop,seek,loop,import,capture}` | the player |
| `GET /api/library`, `DELETE /api/library/poses/{type}/{name}`, `DELETE /api/library/actions/{name}` | list with dependencies, delete to trash |
| `POST /api/library/poses/import`, `GET /api/library/actions/{name}/export`, `POST /api/library/actions/import` | import a pose file, export or import an action zip (409 asks before replacing) |
| `GET/POST /api/speech`, `POST /api/speech/direction`, `POST /api/speech/plan`, `GET /api/speech/{name}/audio`, `DELETE /api/speech/{name}` | options and clips, a BytePlus tone's prompt, a dry run, generate, play, delete |
| `GET /api/speech/voices/{byteplus,minimax}`, `GET /api/speech/voices/{provider}/sample?voice_id=` | every voice with its language, gender, scenario and sample URL; the sample file from `data/tts/sample` (404 if not made) |
| `GET /api/map`, `GET /api/map/maps`, `POST /api/map/maps/{open,upload}` | the open map, the maps there are, open or upload one |
| `GET /api/map/{grid,projection,diff,protection}.png`, `POST /api/map/scene/layer`, `POST /api/map/focus` | 2D layers and the 3D view |
| `POST /api/map/edit/preview`, `POST /api/map/edit[/cancel]`, `POST /api/map/{undo,redo,history/jump/{id}}`, `GET /api/map/history` | edits and history |
| `GET /api/map/candidates`, `POST /api/map/highlight`, `POST /api/map/save`, `GET /api/map/package/{name}`, `POST /api/map/restore` | suspected ghosts and gaps, fence one off in 3D, save and export, restore the original |

## Code

```text
app/        main.py (entry), context.py, api_recorder/ (all routes), ui_recorder/ (page + static)
component/  recorder_application.py (facade) and one folder per business block:
            pose_editing, action_authoring, action_playback, robot_state, robot_display,
            speech_generation (script, BytePlus Voice Direction, service),
            map_session (the Map page's facade), map_storage, map_editing, map_inspection, map_display,
            common (joint schema, pose/action models, naming)
util/       Pink IK, MuJoCo kinematics, Viser views, motion files, BytePlus / MiniMax TTS, WAV,
            occupancy grids, point clouds, map packages, raster, data files, logging
config/     settings.py
```

Every module ends with a `demo_xxx()` you can run directly for a quick check.

```bash
uv run python -m unittest discover -s tests -t .
uv run ruff check .
```
