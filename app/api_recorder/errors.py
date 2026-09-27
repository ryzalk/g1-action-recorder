"""One place that turns service errors into HTTP answers the page can show as they are."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

from config.settings import use_utf8_output
from util.byteplus_tts_helper import ByteplusTtsError
from util.minimax_tts_helper import MinimaxTtsError

# 409 is what the page answers with a "Replace it?" confirm.
STATUS_BY_ERROR = {FileExistsError: 409, FileNotFoundError: 404, ValueError: 422, KeyError: 422, ByteplusTtsError: 502,
                   MinimaxTtsError: 502}


def register_error_handlers(app: FastAPI) -> None:
    for error_type, status in STATUS_BY_ERROR.items():
        app.add_exception_handler(error_type, _handler(status))
    # Anything unexpected still reaches the page with its message, not just "500".
    app.add_exception_handler(Exception, _handler(500))


def _handler(status: int):
    async def handle(request: Request, error: Exception) -> JSONResponse:
        detail = str(error).strip("'") or type(error).__name__
        logger.warning("{} {} -> {}: {}", request.method, request.url.path, status, detail)
        response = JSONResponse({"detail": detail}, status_code=status)
        return response

    return handle


def demo_errors() -> None:
    from fastapi.testclient import TestClient

    app = FastAPI()
    register_error_handlers(app)

    @app.get("/exists")
    def exists():
        raise FileExistsError("wave_left already exists")

    response = TestClient(app).get("/exists")
    logger.info("{} {}", response.status_code, response.json())


def main() -> None:
    use_utf8_output()
    demo_errors()


if __name__ == "__main__":
    main()
