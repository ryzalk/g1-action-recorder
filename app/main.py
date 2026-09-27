"""Service entry: the page and its API on one port, the Viser 3D view on another, in one process."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api_recorder import action_api, library_api, map_api, playback_api, pose_api, robot_api, speech_api
from app.api_recorder.errors import register_error_handlers
from app.context import recorder_context
from app.ui_recorder import ui_main
from config.settings import PathConfig, ServerConfig, use_utf8_output
from util.log_helper import setup_logger


class RevalidatedStaticFiles(StaticFiles):
    """Without a Cache-Control header browsers reuse an old script after an update; make them ask each load."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app() -> FastAPI:
    """Viser is not started here, so tests can drive the whole API without a 3D server."""
    app = FastAPI(title="G1 Concierge Studio")
    app.mount("/static", RevalidatedStaticFiles(directory=ui_main.STATIC_DIR), name="static")
    for module in (ui_main, robot_api, pose_api, action_api, playback_api, library_api, speech_api, map_api):
        app.include_router(module.router)
    register_error_handlers(app)
    return app


def demo_app() -> None:
    """Every GET the page makes answers; nothing is saved and no 3D server starts."""
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    urls = ("/", "/api/robot", "/api/poses", "/api/actions", "/api/playback", "/api/library", "/api/speech",
            "/api/map/maps", "/static/js/common.js")
    for url in urls:
        logger.info("{} -> {}", url, client.get(url).status_code)


def main() -> None:
    use_utf8_output()
    # Set to True to only run the check above.
    demo_only = False
    if demo_only:
        demo_app()
        return
    setup_logger(PathConfig.LOG_DIR)
    recorder_context.display.start()
    recorder_context.map.start_viewer()
    logger.info("G1 Concierge Studio: http://{}:{} (data in {})", ServerConfig.HOST, ServerConfig.PORT,
                PathConfig.DATA_DIR)
    # On Windows uvicorn picks the Proactor loop, which logs a ConnectionResetError traceback whenever a
    # browser tab closes its WebSocket; the selector loop doesn't, and nothing here needs subprocesses.
    uvicorn.run(create_app(), host=ServerConfig.HOST, port=ServerConfig.PORT, log_config=None,
                loop="asyncio:SelectorEventLoop")


if __name__ == "__main__":
    main()
