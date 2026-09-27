"""Fetch a public file over HTTP(S) into bytes, with a clear error when it can't."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import requests
from loguru import logger

from config.settings import use_utf8_output


class HttpDownloadError(RuntimeError):
    """The file couldn't be fetched."""


class HttpDownloadHelper:
    def __init__(self, **kwargs) -> None:
        self.timeout = kwargs.get("timeout", (10.0, 60.0))
        self.attempts = kwargs.get("attempts", 3)
        self.session = kwargs.get("session") or requests.Session()

    def fetch(self, url: str) -> bytes:
        """A dropped connection or a server error is tried again, up to attempts times."""
        for attempt in range(1, self.attempts + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as error:
                if attempt == self.attempts:
                    raise HttpDownloadError(f"Couldn't fetch {url}: {error}") from error
                logger.warning("Fetching {} failed ({}), trying again", url, error)
                continue
            if response.status_code < 500 or attempt == self.attempts:
                break
        if response.status_code >= 400 or not response.content:
            raise HttpDownloadError(f"Couldn't fetch {url}: HTTP {response.status_code}")
        content = response.content
        return content


def demo_http_download_helper() -> None:
    content = HttpDownloadHelper().fetch("https://www.example.com/")
    path = BASE_DIR / "output" / "demo" / "http_download" / "example.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    logger.info("{}: {:,} bytes", path, len(content))


def main() -> None:
    use_utf8_output()
    demo_http_download_helper()


if __name__ == "__main__":
    main()
