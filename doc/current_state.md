# Current state

Last updated: 2026-09-27. Branch `refactor/simplify-preline-ui`, not committed yet.

## What this is

Simulation-only authoring tool for Unitree G1 upper-body poses and actions: record and compose
poses, sequence them into actions compiled with Pink, play actions or imported motions (recorder
NPZ, Kimodo NPZ, ARDY PKL) in a Viser view, generate BytePlus speech clips. See README.md.

## 2026-09-25 refactor

Agreed with the user before starting:

- Layout follows the user's convention (robot-guide / map-editor): `app/context.py` two lines,
  `component/recorder_application.py` facade, one `component/<noun>_<activity>/service.py` per block,
  `util/` knows no domain. AGENTS.md cut from 1169 lines to the project's rules.
- The page does everything through the API (`app/api_recorder/`); `app/ui_recorder/` only renders.
- UI is Preline (CDN) + Viser. English, short hints, short but clear labels.
- Features the UI didn't use are gone: pose PNG and action GIF previews, IK frame-target solve,
  DDS extraction, NPZ schema 1 (all saved NPZ are schema 2), the separate unused REST/WS surface.
- `tests/` kept (rewritten, 37 tests); every source module still ends with `demo_xxx()`.
- Pink stays the IK layer (the team's standard for humanoids).

Decided while doing it:

- Windows setup: PyPI `pin` has no Windows wheels, so pinocchio comes from a conda-forge env
  (`g1-pinocchio`), the `.venv` is built on it with system site packages, and `pyproject.toml`
  skips `pin` on win32. Linux still installs everything from PyPI.
- MuJoCo is only used for forward kinematics of the shared robot state (no rendering, no EGL).
- Ports 8930 (page) / 8931 (Viser); 8000 was taken by manip-service. `G1_RECORDER_DATA_DIR`
  points the app at a data copy.
- Joint sliders are in degrees; files stay in radians.
- Save in Build action writes the JSON and the compiled NPZ together; Preview compiles in memory.
- Replacing an existing name asks in a dialog (409 from the API); no overwrite checkboxes.
- One playback bar for every tab; manual pose edits pause playback first.

Result: Python 8.3k -> 3.1k lines, frontend 3.0k -> 1.1k, tests 3.7k -> 0.5k; largest file 188 lines.

## Verification

- Pink recompiles all 5 saved actions to the stored NPZ exactly (0.0 rad difference); that is a test.
- Kimodo/ARDY rotation conversion matches the previous implementation exactly on random input.
- `uv run python -m unittest discover -s tests -t .`: 37 tests pass. `uv run ruff check .`: clean.
- Every module's `demo_xxx()` runs.
- UI self-test, each pass on a fresh copy of `data/` (`output/demo/review/data`), launch config
  `g1-recorder-review`. Checklist: A load and console, B six camera views, C Record pose (sliders,
  typed values and clamping, reset per group, mirror both ways, open saved pose, save body/left/right,
  replace confirm and cancel, empty name), D Compose pose (auto preview, each select, keep-body arm,
  save, replace, open existing), E Build action (add, reorder, remove, times, total, click to show,
  preview, sample rate, save and download NPZ, replace, new, open, errors), F Play action (saved play,
  pause/resume, frame step, scrub, stop, loop, capture left/right with replace, imports: not-an-NPZ,
  Kimodo without and with FPS, recorder NPZ), G Speech (not configured state, clip list, audio,
  download, delete cancel/confirm), H reload with tab hash, I restart keeps data, J server log and
  console after closing a tab, K real `data/` untouched; layout at 768, 1024 and 1440 px.

| Pass | Found | Fixed |
| --- | --- | --- |
| 1 | At 768 px Viser switched to its mobile sheet and covered the robot; tab bar showed a scrollbar; status badge wrapped; viewer hint overlapped | Side panel 22rem below 1280 px, note in Viser's panel, hidden scrollbar, nowrap badge, hint moved up |
| 2 | Closing a tab logged a `ConnectionResetError` traceback (Windows Proactor loop) | uvicorn runs on `asyncio:SelectorEventLoop` |
| 3 | Below 1280 px Build action cut every pose name to `concierge_sp…`; browser served stale JS after an update; Play's FPS hint overflowed | Compact step table, `Cache-Control: no-cache` on static files, shorter hint |
| 4 | Nothing new | |

Then, at the user's request, hands-on rounds with real clicks, drags and typing in the app's
browser pane (479 px wide), each on a fresh copy:

| Round | Found | Fixed |
| --- | --- | --- |
| 1 | At 479 px the page scrolled sideways and the 3D view was a sliver; switching tabs kept the previous tab's scroll position; spinner arrows covered the step times | Below 768 px the view stacks above the panel (tab labels shorten, title and status text hide); panel scrolls to top on tab change; spinners hidden in the step table |
| 2 | Nothing new | |
| 3 | Enter in a name field didn't save; the viewer hint covered a raised hand on small screens | Enter presses that field's Save; hint hidden below 640 px |
| 4 | Nothing new | |

Native confirm dialogs and file choosers can't be clicked by the test browser, so those two steps
were answered from the page script; everything else was operated as a user would.

Not tested live: BytePlus generation (no `BYTEPLUS_API_KEY` here; covered by a fake-TTS test) and
opening a real ARDY PKL in the browser (covered by unit tests with a synthetic session).

## 2026-09-26 Library: delete, import, export

Asked for: delete poses and actions, import poses from anywhere, and handle the action → pose
dependency. Agreed: a Library tab; delete goes to a trash folder; pose import is one file at a time;
action import is a zip that carries its poses (so there is an Export).

- Dependencies: an action's JSON names its poses (needed to edit or recompile it); a composed pose
  holds copies of its parts' values (history only); the NPZ needs nothing. So a pose an action uses,
  and `concierge_init`, can't be deleted; an arm pose that went into a composed pose can.
- Delete moves files to `data/.trash/<YYYYmmdd-HHMMSS>/` under their `data/` paths (git ignores it).
  An action's JSON and NPZ go together.
- Pose import: the same pose again changes nothing; a different pose under the same name is a 409
  with the whole question, and the page asks it as is. Replacing `concierge_init` says it is where
  every action starts and ends, and the held waist and import blend follow the new home at once.
- Action zip: `action.json`, `trajectory.npz`, `poses/<type>/<name>.json` for every pose it uses.
  Import lists everything it would change and asks once; then it saves the poses and compiles the
  action here (identical to the exported NPZ when the poses match; that is a test).
- Also fixed on the way: the tab bar overflowed between 640 and 1023 px (compact tabs below 768,
  title and status text hidden below 1024); names sort by number (`speak_2` before `speak_10`);
  Record's Reset follows a replaced home without a reload; Compose's "Edit a composed pose" shows
  the pose as saved and names a part that was deleted, instead of silently rebuilding without it.

Tests: 45 (8 new, in `tests/test_library.py`, `test_api.py` and `test_pose_service.py`), ruff clean.

Hands-on rounds in the app's browser pane (642 px, plus 479/768/1024/1440), each on a fresh copy:

| Round | Found | Fixed |
| --- | --- | --- |
| 1 | Tab bar hid Play/Library/Speech at 642 px; import toast said "1 replaced"; `speak_10` sorted before `speak_2`; Reset kept the old home after it was replaced | Header breakpoints; "1 pose replaced"; numeric sort; Record refreshes home values on show |
| 2 | Compose showed a wrong pose (1.19 rad off) after one of its parts was deleted; delete confirm "X keeps its own copy" was ambiguous with shared names; a wrong file for Import action didn't name the file; pose import errors carried decoder text | Open shows the saved pose and names the missing part; "Composed pose X keeps..."; "x.json isn't an action zip"; plain "x isn't a pose file" |
| 3 | The missing part's select showed blank | Falls back to its placeholder |
| 4 | Nothing new | |

## 2026-09-27 New layout, Speech with MiniMax and BytePlus, Map editor

Asked for: design the UI first (Penpot file "G1 Action Recorder", page "Screens"; see
`doc/ui_redesign.md`), then build it, add the speech features of `services/concierge-audio` and the
map editor of `services/map-editor`, and test until it passes before reporting.

Layout (as designed): sidebar navigation (workflow 1–4, Library, Map, Speech with sub-pages BytePlus
and MiniMax; provider dots), page header with the link status, Record / Compose / Build with Open +
New on top and Name + Save below, Record's pose type deciding Open and Save and folding the other
groups, Library as tabs and a table (Made from, Used by, locks), confirm dialogs instead of
`window.confirm`, a smaller toast stack. Narrow windows keep working (page select instead of the
sidebar below 1024 px, stacked Speech below 1280 px).

Speech (ported, trimmed): `util/byteplus_tts_helper.py`, `util/minimax_tts_helper.py`,
`util/wav_helper.py`; `component/speech_generation/` = `speech_script.py` (parts -> requests),
`voice_direction.py` (nine fields, 150 presets in `config/byteplus_presets.json`, the prompt),
`service.py`. Decided with the user: port, not call; per-part tone, pauses, per-part pace, MiniMax
sound tags, BytePlus's full Voice Direction; all 150 presets with Chinese names; a short voice list
plus a Voice ID field. Same-tone neighbours merge into one request; MiniMax keeps pauses and tags
inline within one tone (`<#0.5#>`, `(laughs)`), a pause between tones is silence; one WAV at the end.
Clip JSON schema 2; schema-1 clips still list ("older clip"). `util/tts_helper.py` is gone.

Map (ported): `component/map_{storage,editing,inspection,display}` and `component/map_session`
(was `map_application.py`), `util/{map_package,occupancy_grid,point_cloud,raster}_helper.py` and
`util/point_cloud_viewer_helper.py`, config classes `Map*Config`, routes in
`app/api_recorder/map_api.py`, page in `pages/map.html` + `map_canvas.js`, `map_tools.js`,
`map_page.js`. All Chinese text translated. The map loads when the Map page is first shown (it reads
the point clouds), not at start. Its own Viser on 8932. `data/maps/` holds RTLAB copied from
map-editor and is git-ignored (12 MB of point clouds). A bad upload is now a 422 with a reason.
New dependencies: opencv-python-headless, python-lzf, pyyaml, scipy.

Also: the Library listing carries `made_from` for composed poses; the sidebar shows the data folder.

Verification:
- `uv run python -m unittest discover -s tests -t .`: 54 tests pass (9 new speech tests, 3 new API
  tests for speech, map and Made from). `uv run ruff check .`: clean. Every new module's demo runs;
  every ported map demo runs on Python 3.10.
- All 150 BytePlus prompts are identical to concierge-audio's for the same presets.
- Browser, 1440 × 900, a fresh copy of `data/` each pass, real clicks, typing and dialogs
  (Playwright): Record (pose type folds groups and filters Open, type a value, save, replace
  dialog cancel then replace, New), Compose (open, New, save), Build (open, add, preview playing,
  save with NPZ note), Play (play, pause, capture), Library (tabs, Made from, In use, delete cancel
  then confirm), Speech BytePlus (select text, Voice Direction, preset, Advanced → Custom and the
  prompt follows, at most two textures, pause at the cursor, request count, click a span to edit,
  remove tone), Speech MiniMax (emotion, pace, sound tag, pause after it without moving the cursor,
  Backspace removes it, speech-02 refuses sound tags, Voice ID field), Map (open dialog that can't be
  closed without a map, lasso → pending → Enter, Ctrl+Z / Ctrl+Shift+Z, wall by clicks + double
  click, candidates locate → Clear → Esc, layers, history jumps, Save & export downloads the
  .g1map, Restore original). No console errors beyond the expected 409 / 422; no server errors.
- Live, with the keys from concierge-audio's `.env` passed to the process only: one BytePlus clip
  (two presets, 0.5 s pause: 4.44 s, 16 kHz mono 16-bit, exactly 0.5 s of silence between) and one
  MiniMax clip (happy + `(chuckle)`: 4.37 s, 16 kHz mono 16-bit). Listening is still up to you.
- Layout at 1280, 1024 and 800 px: no sideways scrolling, nothing overlapping.

Found and fixed on the way: a quoting slip that broke play.js; elements with their own display class
couldn't be hidden with the `hidden` class (now the `hidden` attribute); the Voice Direction panel
grew past the screen with Advanced open (now re-placed and scrolled inside the card); inserting a
chip lost the cursor so the next pause went to the start (the cursor now stays after the chip);
long map height labels ran into their values; a burst of toasts covered the toolbar (at most three).

## 2026-09-27 Follow-ups from the first review

1. Record, Whole body: Open lists whole-body and composed poses (grouped); saving writes a whole-body pose.
2. Actions: Save already wrote the definition and the trajectory together; the export now matches.
   The zip is laid out like `data/` (`actions/definitions/<name>.json`, `actions/trajectories/<name>.npz`,
   `poses/...`), compiles the trajectory if the NPZ is missing, and Build's saved note offers
   "Export .zip" (also when a saved action is opened) instead of the NPZ alone. Older zips still import.
3. Voices: full lists in a panel instead of a short dropdown. BytePlus: the 177 voices of the official
   TTS 2.0 list (docs.byteplus.com/en/docs/byteplusvoice/tts-voice-list, captured into
   `config/byteplus_voices.json`) with language, gender, scenario, description and BytePlus's own sample
   recording; each voice speaks the one language listed. MiniMax: the account's list read live from
   `/v1/get_voice` (system + cloned, cached 10 min; `config/minimax_voices.json` snapshot of 332 without
   a key), language from the voice id (e.g. "Chinese (Mandarin)_…" -> Mandarin Chinese), gender from the
   description; a sample is one short request in the voice's language, made on first play and kept in
   `output/voice_samples/minimax/`. Voice names on clips and defaults never call out (cache or snapshot).
   The panel: search, language chips with counts, gender, scenario (BytePlus), play/stop, choose, Voice ID.
4. Map: Save & export keeps the folder's files (manifest.json, map.pcd, ground_map.pcd, grid.pgm,
   grid.yaml, written as before with *.orig.* and .backup/) and downloads them as `<folder>/…` in a zip,
   read back byte for byte before it is offered; a copy stays in `output/map_exports/`. Upload takes that
   zip (a .g1map was also accepted then; no longer, see below).

Note: `data/maps/RTLAB` was saved from the app on 2026-09-27 09:33 (two saves, no edits in the log):
it now has `*.orig.*`, `.backup/` and `edits.json`. Restore original on the Map page puts it back.

Verified: 60 tests pass (voice catalog, MiniMax sample made once in its language, export layout and a
missing NPZ compiled into it, older zips, map zip contents byte for byte), ruff clean, demos run; browser
flows on a fresh copy pass again, including both voice panels playing a real sample (BytePlus recording,
MiniMax sample generated) and the downloaded action and map zips checked file by file.

## 2026-09-27 Second review

1. "Whole body" is called **Base** everywhere. Record: Open lists every pose (Base, Composed, Left arm,
   Right arm); **Save as Base / Left arm / Right arm** sits in the save bar, opening a pose sets it (a
   composed pose saves as Base) and the groups it doesn't keep fold away. Compose: the first part is
   "Base"; Save as Base writes the whole result as a base pose with the parts it was made from
   (`source="composition"`, `source_parts`), Save as Left/Right arm writes only that arm. Compose's Open
   lists every pose made there (any type) and restores its parts. Library shows "Made from" for all.
   Older composed poses still open, play and import.
2. Map upload takes only the `.zip` that Save & export downloads (`.g1map` is gone).
3. Voice samples are made ahead into `data/tts/sample/{byteplus,minimax}/` by
   `component/speech_generation/voice_samples.py --build` (BytePlus: the 177 official recordings;
   MiniMax: every voice of the account list saying one line in its language with speech-2.8-turbo).
   The API serves those files only; a voice without one has no play button. Samples are gitignored
   and skipped by the tests' data copy.
4. BytePlus Generate failed (45002001 "No readable text!") when a Voice Direction covered a sentence
   but not its closing mark: the leftover "！"/"。" went out as its own request. Parts with nothing to
   read now join the speech before them (or after, at the start).

## 2026-09-27 Third review

1. Play action: the ".pkl you made yourself" warning is gone; the drop zone says what opens (an action
   .npz saved here, a Kimodo .npz, an ARDY .pkl).
2. Play action: no FPS field. A Kimodo NPZ uses its stored fps, else `ActionConfig.KIMODO_FPS` (30).
3. Build action: the Return row's move time looked disabled (the whole row was grey); only the label is
   grey now, the field is an ordinary input.
4. Build action: pose pictures. `util/robot_render_helper.py` renders the G1 offscreen with MuJoCo (one
   worker thread owns the GL context; floor and sky masked to a plain background) and
   `component/pose_editing/pose_preview.py` draws each picture (see the fourth review for where it is kept). `GET /api/poses/{type}/{name}/preview.png`.
   "Add a pose" opens a picker (search, All/Base/Composed) of pictures; each step row shows a thumbnail.

## 2026-09-27 Fourth review

- Compose saves a composed pose again (no Save as there; Record keeps Save as Base / Left arm / Right arm).
- Every pose is saved with its picture, `data/poses/<type>/<name>.png`, drawn on save (Record, Compose,
  capture, import) and moved to the trash with the pose; older poses get theirs when first shown. The 48
  poses in `data/` have theirs now. The Compose page shows the saved picture after Save / Open.
- The renderer makes and closes its GL context inside each call on its worker thread (~80 ms): a
  context freed from another thread by garbage collection or at exit crashed the process.

## 2026-09-27 Map check: ghosts and gaps readable

- The "sea of red" was the point projection layer (red density, 0.1–2.0 m) under candidate outlines that were
  red too. On the Check tab the projection is now grey and faded; ghosts are fuchsia and gaps blue (colours no
  layer uses), only the kind being checked is drawn, each with a white halo, and ones too small to see at the
  current zoom get a ring.
- Clicking a candidate spotlights it: the map outside a window round it dims, it gets a thick outline and a
  label (#id, kind, cells, size), the others turn thin and dashed; in 3D it is fenced off (floor ring, ring at
  1.8 m, posts). Esc, switching kind or tab, or any edit takes the spotlight and fence away.
- `/api/map/candidates`, `/focus` and `/highlight` open the last map first and say "No map is open" instead of
  failing inside when none is.

## 2026-09-27 Pushed with data

- `data/actions`, `data/poses` (with pictures), `data/maps` and `data/tts/sample` are now in git (no longer
  ignored); `data/.trash` and speech clips made while testing stay out.

## Next

- The user reviews the new layout, Speech and Map in the running app (put the keys in `.env` to
  generate); then commit and push the branch.
- Speech clips are not yet attached to actions or map tour points.
- Hardware work stays out of scope until a read-only LowState recorder and a safety layer exist.
