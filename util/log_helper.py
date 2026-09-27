"""loguru setup: console + daily log file, with standard logging (uvicorn) routed into it."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import logging

from loguru import logger

from config.settings import PathConfig, ServerConfig, use_utf8_output


class InterceptHandler(logging.Handler):
    """Route standard-library records (uvicorn's access log) into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        logger.opt(exception=record.exc_info).log(record.levelname, record.getMessage())


def setup_logger(log_dir: Path, level: str = ServerConfig.LOG_LEVEL) -> None:
    """Called once, at the service entry."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=level, diagnose=False)
    logger.add(log_dir / "service_{time:YYYY-MM-DD}.log", rotation="00:00", retention="14 days",
               encoding="utf-8", level=level, diagnose=False)
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


def demo_logger() -> None:
    log_dir = PathConfig.DEMO_DIR / "logs"
    setup_logger(log_dir)
    logger.info("Logging to {}", log_dir)
    logging.getLogger("uvicorn").info("standard logging reaches loguru")


def main() -> None:
    use_utf8_output()
    demo_logger()


if __name__ == "__main__":
    main()
