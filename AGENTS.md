# AGENTS.md

Rules for working on this project. README.md explains what it does and how to run it.

## Layout

- `app/` is interface only. `api_recorder/` holds every route (REST and the WebSocket); the page in
  `ui_recorder/` only renders the layout and does all its work through that API.
- `app/context.py` is two lines: import `RecorderApplication`, create `recorder_context`.
- `component/recorder_application.py` is the facade the API calls. Business rules live there or in
  the block services (`component/<noun>_<activity>/service.py`), never in routes or JavaScript. The
  Map page's blocks (`map_storage`, `map_editing`, `map_inspection`, `map_display`) sit behind their
  own facade, `component/map_session/service.py`, which the API reaches as `recorder_context.map`.
- `util/` wraps libraries and files and knows nothing about poses or actions; it never imports from
  `component/`. Name helpers after the capability (`pink_ik_helper.py`), not the domain.
- `config/settings.py` holds `XxxConfig` classes with UPPERCASE attributes.
- Dependencies point one way: `app -> component -> util`.

## Code

- One class per module, shared state in members, minor parameters in `**kwargs`.
- Every module ends with `demo_xxx()` called from `main()`, runnable from an IDE right-click; demos
  write only under `output/demo/` and never change `data/`.
- `return` a named variable; logging via loguru.
- Validate at the edges only: pydantic request models, `G1JointSchema.check` for joint values,
  `clean_name` for names. No defensive checks elsewhere.
- IK goes through Pink. Do not replace it with hand-written math.
- Keep `tests/` passing (`uv run python -m unittest discover -s tests -t .`) and `uv run ruff check .`
  clean. Tests work on a temporary copy of `data/`.

## UI

- Preline (CDN) + Tailwind browser build, no frontend build step. Shared class sets are in
  `templates/ui.html`.
- Text in English; hints short; tab and button labels short but unambiguous. The one exception: the
  BytePlus Voice Direction presets and field values keep their Chinese names (and the prompt stays
  Chinese), as in `services/concierge-audio`.
- One primary button per panel. Replacing an existing name is confirmed with a dialog, not a checkbox.
  Feedback is a toast.
- Pages are reached from the sidebar and the address hash (`#record` … `#speech-minimax`); Speech has
  two sub-pages, BytePlus and MiniMax.
- The robot's 3D view is Viser in an iframe; the one playback bar under it is shared by the four
  workflow pages. The Map page has its own Viser (point clouds) on its own port.

## Robot

- Left and right are the robot's own sides. The G1 faces +X; its left is +Y.
- Simulation only. Any future real-robot command must go through a separate safety layer (limits,
  mode, communication checks, stop); UI widgets are not safety mechanisms.
