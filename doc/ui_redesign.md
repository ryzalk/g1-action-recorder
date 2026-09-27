# UI redesign (built 2026-09-27; see current_state.md)

Asked for on 2026-09-26: a Preline admin-portal layout, designed first, code only after the user
approves the design. Drawn in the local Penpot (`C:\Users\rfouy\workspace\app\penpot`, MCP connected
in Claude Code as `penpot`): file "G1 Action Recorder", page "Screens", 1440 x 900 boards
(1 Record, 1b Record left arm, 2 Compose, 3 Build, 4 Play, 5 Library actions, 5b Library composed,
6–6d Speech BytePlus / MiniMax, 7 States). Exported copies go to `services/UI/g1-action-recorder`.

## Layout

- Desktop web only: minimum page width 1280 px, horizontal scroll below that, no mobile layout.
- Left: fixed sidebar, 260 px. Brand (G1 Action Recorder, "Simulation only"); section "Workflow" with
  numbered items 1 Record pose, 2 Compose pose, 3 Build action, 4 Play action; section "Manage" with
  Library and Speech (icons; Speech has sub-items BytePlus and MiniMax); bottom card "Data folder" showing the data path (real `data/` or a copy).
- Main: page header (title, one-line hint, "Simulation live" status pill on the right), then two equal
  halves: operations panel on the left, 3D view (Viser) with the shared playback bar on the right.
- Library and Speech have no 3D view: their content fills the whole main area.
- The playback bar belongs to the 3D view and is shared by the four workflow pages.

## Editor pattern (Record, Compose, Build are the same)

- Top bar of the panel: an Open select that lists only what this page opens, and a New button.
  Record also has a pose-type switch above it: Whole body / Left arm / Right arm.
- Middle: the page's editor, scrolls on its own.
- Bottom bar, pinned: Name field and Save. Opening fills in the name; New goes back to the start and
  clears the name; Save asks before replacing an existing name.
- Record: the pose type decides both what Open lists and what Save writes. For an arm type the groups
  that are not saved collapse and grey out ("Not part of a left-arm pose").
- Build: Preview sits under the steps table next to the total, so the bottom bar is only Name + Save.
- Placeholders: "Open a whole-body pose…", "Open a left-arm pose…", "Open a composed pose…",
  "Open a saved action…".

## Pages

- Record pose: pose type + Open/New; cards Waist (Yaw, Roll, Pitch), Left arm and Right arm (Shoulder
  pitch/roll/yaw, Elbow, Wrist roll/pitch/yaw) with a slider and degree box per joint, Reset per card,
  "Copy to right/left arm" on the arms; Name + Save.
- Compose pose: Open/New; card with Body, Left arm, Right arm selects ("Keep the body's … arm"), hint
  "Each change shows on the robot right away."; Name + Save.
- Build action: Open/New; steps table (#, Pose, Move s, Hold s, up/down/remove; Start and Return rows
  fixed at concierge_init), add-pose row; Total, sample rate, Preview; Name + Save.
- Play action: card Saved action (select + Play); card Motion file (drop zone, Source FPS, .pkl
  warning); card Save a frame as an arm pose (name, Save left arm, Save right arm).
- Library (full width): tabs Actions / Whole body / Left arm / Right arm / Composed with counts, Import
  pose and Import action buttons; table. Actions: Name, Poses, Length, Compiled, Export + Delete.
  Poses: Name, Made from (composed parts), Used by (action chips), Delete or "In use" with a lock.
- Speech (full width): see "Speech with MiniMax and BytePlus" below.

## Look

Preline on Tailwind: gray-50 page, white cards with gray-200 borders and rounded-xl, blue-600
primary, blue-50 active nav item, text-sm / text-xs, Inter. 3D view dark (gray-900) with the camera
buttons top left and "View settings" (Viser) top right.

## New data the API would need

- Data folder path for the sidebar card.
- Composed poses' parts in the Library listing ("Made from").

## Checked against the current code (2026-09-26)

The design follows what the page and API do today; where it differs, it is a deliberate change.

- Kept from the code: six camera views (Front, Front left, Left, Back, Right, Front right) and the
  hint "Left and right are the robot's own · drag to orbit"; the playback bar as it is (Play/Pause,
  Stop, frame step, scrub, `time / duration s`, Loop; state badge No action / Ready / Playing /
  Paused / Done, `name · source`, phase, `frame i / n`); group colours waist gray, left arm blue,
  right arm orange; Build's Start and Return rows at the home pose, Return with its own move time,
  Sample rate and the "Download NPZ" note after Save; Library's used-by / part-of rules and locks.
- The header status shows the WebSocket link (Connecting / Connected / Disconnected), not a fixed
  "Simulation live".
- No playback speed: the API has none.
- Replace, delete and import questions become a Preline dialog instead of `window.confirm`.
- Drawn at 1440 px only; the narrow layouts the code already has (down to 479 px) stay as they are.
- API additions: `data_dir` for the sidebar card; `source_parts` of composed poses in the Library
  listing ("Made from"; the pose files already hold it).

## Speech with MiniMax and BytePlus (asked 2026-09-26)

Reference: `services/concierge-audio` (MiniMax + BytePlus studio). Agreed with the user:

- Port its TTS code here, trimmed to this project's layout: `util/byteplus_tts_helper.py`,
  `util/minimax_tts_helper.py`, `util/wav_helper.py`; `component/speech_generation/` holds the script
  model, the BytePlus prompt mapper, the preset table and the service. One app, one `data/tts/`.
- Tone and rhythm: per-segment tone, pauses, per-segment pace, MiniMax sound tags, and BytePlus's full
  Voice Direction (emotion, intensity, social tone, mental state ≤2, intent, voice texture ≤2, pace,
  pitch, energy).
- All 150 BytePlus presets with their Chinese names and categories (8 top-level, their subcategories;
  default 接待服务 → 身份介绍 → 自我介绍). This is the one exception to "UI text in English"; every
  other label stays English.
- Voices: a short list per provider plus a Voice ID field for anything else.
- Left out: MiniMax long-text async, voice modifier and sound effects, full voice catalogues.

### The script

The text is a list of parts, so nothing but words reaches the speech engines:

- text segment: `{text, tone}`; tone is a BytePlus style (preset id + nine fields) or a MiniMax
  emotion, plus an optional pace; no tone means the clip default.
- pause: `{pause_seconds}` (0.25 / 0.5 / 1.0 / 1.5 or custom 0.01–10).
- sound tag (MiniMax only): `{sound: "laughs"}`.

Generation: adjacent segments with the same tone merge; each remaining segment is one request;
MiniMax gets pauses and sound tags inline (`<#0.5#>`, `(laughs)`), BytePlus gets pauses as silence
between segments. The PCM is joined into one 16 kHz mono 16-bit WAV and checked. The BytePlus prompt
goes in `context_texts`, never in the text.

Clip JSON becomes schema 2: provider, model, voice, rate / volume / pitch, the script, and per request
the prompt or emotion actually sent. Schema-1 clips (today's BytePlus clips) still list and play.

### Page

Boards 6 (BytePlus, Voice Direction open), 6b (BytePlus, Advanced open, Clips tab), 6c (MiniMax,
Emotion open), 6d (MiniMax, Sound tag menu); Speech states on board 7.

- Navigation: Speech in the sidebar has two sub-items, BytePlus and MiniMax, each with a dot (green:
  key set, gray: no key). Each is its own page, "Speech · BytePlus" / "Speech · MiniMax"; the header
  also shows "G1 audio · 16 kHz · mono · 16-bit WAV". Clips are shared by both pages.
- Two columns, no 3D view, laid out like concierge-audio's studio.
- Left card "Script": character count; toolbar BytePlus: Voice Direction (needs a text selection),
  Pause ▾; MiniMax: Emotion, Pause ▾, Sound tag ▾ (speech-2.8 only). Editor: toned parts are tinted
  spans with a label chip (preset name or emotion; colour per subcategory / emotion as in
  concierge-audio), the one being edited outlined; pauses and sound tags are inline chips. Under it:
  "5 segments · 2 pauses → 5 requests to BytePlus, joined into one WAV". Footer: Name + Generate.
- Voice Direction panel (anchored under the selection): quoted text; Presets (150): category select,
  search, subcategory chips, preset cards with the scene line; Advanced (closed by default) with the
  nine fields (English field names, Chinese values as in concierge-audio; "Custom" once changed);
  Prompt sent to BytePlus (not spoken); Remove tone / Cancel / Apply to selection.
- Emotion panel (MiniMax): 8 emotions with their colours; Pace for this part (speed of this request
  only); Remove / Cancel / Apply to selection.
- Pause menu: 0.25 / 0.5 / 1.0 / 1.5 s or custom seconds, inserted at the cursor. Sound tag menu: the
  19 tags, inserted at the cursor.
- Right card, tabs Settings / Clips (count).
  - BytePlus settings: Voice (short list, "Other Voice ID…"), Speech rate and Loudness (-50…100).
  - MiniMax settings: Model, Voice, Language, Speed (0.5–2), Pitch (-12…12), Volume (0.01–10), Text
    normalization.
  - Clips: name, provider badge, length · voice · parts, the script with its tints, audio, Download,
    Delete; schema-1 clips marked "older clip".
- A provider without a key: gray dot, a banner with the env variable, Generate off.

### API

- `GET /api/speech`: per provider configured, voices, models; presets tree; field options; emotions;
  sound tags; clips.
- `POST /api/speech/prompt`: script segment → the BytePlus prompt (for the preview).
- `POST /api/speech`: name, provider, model, voice, rate / volume / pitch, script, overwrite.
- `.env`: `BYTEPLUS_API_KEY`, `MINIMAX_API_KEY`.

## Map editor (asked 2026-09-27)

Reference: `services/map-editor` (Flask, Chinese UI, same `app -> component -> util` layout). Ported
here, not called: its `component/map_*` blocks and `util/*` helpers move over, its Flask routes become
FastAPI routes in `app/api_recorder/map_api.py`, its page becomes the Map page. UI text in English.
Maps live in `data/maps/<name>/` (an unpacked `.g1map`); exports go to `output/g1map/`. Its own Viser
(point clouds) runs on its own port so the robot view is untouched. Tour points are shown, not edited.

Boards 8 (Tools, lasso erase pending), 8b (Check), 8c (Layers + map info), 8d (History + Open map
dialog). Sidebar: Map under Manage, between Library and Speech.

- Map toolbar: map name and size, Open map…, "Unsaved changes", Undo, Redo, Hold for original, Fit,
  Save & export (primary; saves the folder, keeps `*.orig.*` and `.backup/`, downloads the `.g1map`).
- Three columns: tool panel (tabs Tools / Check / Layers / History), 2D map, 3D view, the last two
  equal. The 2D map has zoom buttons, the main-direction chip (θ₀), a readout bar (x y, row col,
  value, tool hint, zoom) and the pending card floating at its bottom (erase preview: cells, points,
  protected points kept; Cancel Esc / Confirm Enter). The 3D view has toggles (map.pcd,
  ground_map.pcd, Grid texture, Follow preview) and a legend (to delete, protected, height).
- Tools: Pan; Erase ghosts (Lasso, Rectangle, Brush; preview first); Add obstacles (Wall, Polygon,
  Rectangle, Brush; applies at once); erase options (erase to free / unknown, also delete points,
  keep protected points, map.pcd and ground_map height bands); sizes (brush radius, wall width);
  drawing aids (snap to θ₀ + k·90°, 45°, to end points and walls, rectangles along θ₀).
- Check: Ghosts / Gaps with counts, candidate list (largest first, click to go there, Clear or Fill),
  detection settings.
- Layers: original grid, current grid, point cloud projection, changes, protected zone, candidate
  outlines, tour points; projection source and height band; map info.
- History: steps (click to jump), Restore original… (after the first save).
- Open map dialog: maps in `data/maps`, upload a `.g1map` (checksums checked, never overwrites:
  name-2).
