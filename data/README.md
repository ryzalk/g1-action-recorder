# Data

- `poses/<pose_type>/<name>.json`: saved poses (`base`, `left_arm`, `right_arm`, `composed`).
- `actions/definitions/<name>.json`: action definitions (poses with move and hold times).
- `actions/trajectories/<name>.npz`: the compiled trajectory saved with each definition.
- `tts/<name>.wav` and `<name>.json`: speech clips, created when the first clip is generated.
- `.trash/<time>/`: what the Library tab deleted, under the same paths; not tracked by git.

The app reads and writes here unless `G1_RECORDER_DATA_DIR` points it somewhere else.
