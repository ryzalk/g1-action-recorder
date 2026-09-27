"""16-bit PCM and WAV for the G1 speaker: read a WAV into PCM, make silence, join, write, measure."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import io
import wave

from loguru import logger

from config.settings import SpeechConfig, use_utf8_output


class WavHelper:
    """Everything is mono 16-bit PCM at one sample rate; anything else is refused, never converted."""

    SAMPLE_WIDTH = 2

    def __init__(self, sample_rate: int = SpeechConfig.SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate

    def pcm_from_wav(self, data: bytes) -> bytes:
        try:
            with wave.open(io.BytesIO(data), "rb") as wav_file:
                shape = (wav_file.getframerate(), wav_file.getnchannels(), wav_file.getsampwidth())
                pcm = wav_file.readframes(wav_file.getnframes())
        except (EOFError, wave.Error) as error:
            raise ValueError("The speech service didn't return a valid WAV file") from error
        if shape != (self.sample_rate, 1, self.SAMPLE_WIDTH):
            raise ValueError(f"The speech service returned {shape[0]} Hz, {shape[1]} channel(s), "
                             f"{shape[2] * 8}-bit audio instead of {self.sample_rate} Hz mono 16-bit")
        return pcm

    def silence(self, seconds: float) -> bytes:
        pcm = b"\x00\x00" * round(seconds * self.sample_rate)
        return pcm

    def seconds(self, pcm: bytes) -> float:
        seconds = len(pcm) / (self.SAMPLE_WIDTH * self.sample_rate)
        return seconds

    def to_wav(self, pcm: bytes) -> bytes:
        if not pcm or len(pcm) % self.SAMPLE_WIDTH:
            raise ValueError("No audio to write, or half a sample")
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(self.SAMPLE_WIDTH)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(pcm)
        data = output.getvalue()
        return data

    def write(self, pcm: bytes, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.to_wav(pcm))
        return path


def demo_wav_helper() -> None:
    helper = WavHelper()
    tone = b"\x10\x00" * helper.sample_rate
    pcm = tone + helper.silence(0.5) + tone
    path = helper.write(pcm, BASE_DIR / "output" / "demo" / "wav_helper" / "tone.wav")
    again = helper.pcm_from_wav(path.read_bytes())
    logger.info("{}: {:.2f} s, reads back identical: {}", path, helper.seconds(again), again == pcm)
    try:
        WavHelper(sample_rate=24000).pcm_from_wav(path.read_bytes())
    except ValueError as error:
        logger.info("A 16 kHz file where 24 kHz is expected: {}", error)


def main() -> None:
    use_utf8_output()
    demo_wav_helper()


if __name__ == "__main__":
    main()
