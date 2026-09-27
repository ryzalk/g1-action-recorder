"""Names double as file names, so every pose, action and clip name passes through here."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from loguru import logger

from config.settings import use_utf8_output

UNSAFE_CHARACTERS = '<>:"/\\|?*'


def clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Enter a name")
    if len(cleaned) > 100 or cleaned in (".", "..") or any(character in UNSAFE_CHARACTERS for character in cleaned):
        raise ValueError(f"A name can't contain {UNSAFE_CHARACTERS} or be longer than 100 characters")
    return cleaned


def demo_naming() -> None:
    logger.info("{!r}", clean_name("  wave_left  "))
    try:
        clean_name("a/b")
    except ValueError as error:
        logger.info("Refused: {}", error)


def main() -> None:
    use_utf8_output()
    demo_naming()


if __name__ == "__main__":
    main()
