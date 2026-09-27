"""Voice samples, made ahead of time and kept in data/tts/sample/<provider>/, so the voice panel plays a file
and never waits on a service.

BytePlus: the official recording of each voice, downloaded once. MiniMax: each voice saying one line in its
own language, one short request per voice. Build skips what is already there, so it can be run again after
new voices appear (or to retry the ones that failed):

    uv run python component/speech_generation/voice_samples.py --build [byteplus|minimax]
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import hashlib
import re
import time

from loguru import logger

from component.speech_generation.voice_catalog import VoiceCatalog
from config.settings import MinimaxTtsConfig, PathConfig, SpeechConfig, use_utf8_output
from util.http_download_helper import HttpDownloadError, HttpDownloadHelper
from util.minimax_tts_helper import MinimaxTtsError, MinimaxTtsHelper
from util.wav_helper import WavHelper


class VoiceSamples:
    def __init__(self, sample_dir: Path = SpeechConfig.SAMPLE_DIR, **kwargs) -> None:
        """kwargs: catalog, minimax, downloader (tests pass fakes); pause_seconds between MiniMax requests."""
        self.sample_dir = sample_dir
        self.minimax = kwargs.get("minimax") or MinimaxTtsHelper()
        self.catalog = kwargs.get("catalog") or VoiceCatalog(self.minimax)
        self.downloader = kwargs.get("downloader") or HttpDownloadHelper()
        self.pause_seconds = kwargs.get("pause_seconds", 0.3)
        self.wav = WavHelper()

    def path(self, provider: str, voice_id: str) -> Path:
        """Where a voice's sample lives. An id that isn't a safe file name gets a short hash so two can't clash."""
        safe = re.sub(r"[^0-9A-Za-z_.-]", "_", voice_id)
        if safe != voice_id:
            safe += "-" + hashlib.sha1(voice_id.encode("utf-8")).hexdigest()[:6]
        path = self.sample_dir / provider / f"{safe}.wav"
        return path

    def has(self, provider: str, voice_id: str) -> bool:
        exists = self.path(provider, voice_id).is_file()
        return exists

    def build(self, provider: str, **kwargs) -> dict:
        """Makes every missing sample of that provider's list. kwargs: limit (at most this many new ones).
        Returns {"made", "kept", "failed": [[voice_id, reason], ...]}."""
        limit = kwargs.get("limit")
        report = {"made": 0, "kept": 0, "failed": []}
        voices = self.catalog.voices(provider)["voices"]
        for voice in voices:
            path = self.path(provider, voice["id"])
            if path.is_file():
                report["kept"] += 1
                continue
            if limit is not None and report["made"] >= limit:
                break
            try:
                audio = self._make(provider, voice)
            except (HttpDownloadError, MinimaxTtsError, ValueError) as error:
                logger.warning("No sample for {} {}: {}", provider, voice["id"], error)
                report["failed"].append([voice["id"], str(error)])
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(audio)
            report["made"] += 1
            logger.info("Sample {}/{} {} -> {}", report["made"] + report["kept"], len(voices), voice["id"], path.name)
        logger.info("{} samples: {} made, {} already there, {} failed", provider, report["made"], report["kept"],
                    len(report["failed"]))
        return report

    def _make(self, provider: str, voice: dict) -> bytes:
        if provider == "byteplus":
            if not voice.get("sample_source"):
                raise ValueError("the official list has no recording for this voice")
            audio = self.downloader.fetch(voice["sample_source"])
            return audio
        if not self.minimax.configured:
            raise ValueError("MINIMAX_API_KEY isn't set")
        line = self.catalog.sample_line(voice["language"])
        wav = self.minimax.synthesize(line, voice["id"], model=MinimaxTtsConfig.SAMPLE_MODEL)
        time.sleep(self.pause_seconds)
        audio = self.wav.to_wav(self.wav.pcm_from_wav(wav))
        return audio


def demo_voice_samples() -> None:
    """Two samples of each provider into output/demo/voice_samples; data/tts/sample is left alone."""
    samples = VoiceSamples(BASE_DIR / "output" / "demo" / "voice_samples")
    for provider in ("byteplus", "minimax"):
        report = samples.build(provider, limit=2)
        logger.info("{}: {}", provider, report)
    logger.info("A MiniMax id as a file: {}", samples.path("minimax", MinimaxTtsConfig.DEFAULT_VOICE).name)


def build_all(providers: list[str]) -> None:
    """The real samples, into data/tts/sample."""
    samples = VoiceSamples(PathConfig.DATA_DIR / "tts" / "sample")
    for provider in providers:
        samples.build(provider)


def main() -> None:
    use_utf8_output()
    if "--build" in sys.argv:
        build_all([name for name in ("byteplus", "minimax") if name in sys.argv] or ["byteplus", "minimax"])
    else:
        demo_voice_samples()


if __name__ == "__main__":
    main()
