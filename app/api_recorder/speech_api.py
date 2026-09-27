"""Speech: options and clips, the BytePlus prompt for a tone, a dry-run plan, generate with BytePlus or MiniMax,
play or download a WAV, delete a clip."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from typing import Annotated, Literal

from fastapi import APIRouter
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel, Field

from app.context import recorder_context
from config.settings import MinimaxTtsConfig, SpeechConfig, use_utf8_output

router = APIRouter(prefix="/api/speech", tags=["speech"])

Rate = Annotated[int, Field(ge=-50, le=100)]


class Tone(BaseModel):
    """BytePlus: preset_id and/or style fields; MiniMax: emotion."""

    preset_id: str | None = None
    style: dict[str, str | list[str]] | None = None
    emotion: str | None = None


class TextPart(BaseModel):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=SpeechConfig.MAX_TEXT_CHARACTERS)
    tone: Tone | None = None
    # MiniMax speed for this part only.
    pace: float | None = Field(default=None, ge=MinimaxTtsConfig.SPEED_RANGE[0], le=MinimaxTtsConfig.SPEED_RANGE[1])


class PausePart(BaseModel):
    type: Literal["pause"]
    seconds: float = Field(gt=0, le=SpeechConfig.MAX_PAUSE_SECONDS)


class SoundPart(BaseModel):
    type: Literal["sound"]
    tag: Literal[MinimaxTtsConfig.SOUND_TAGS]


Part = Annotated[TextPart | PausePart | SoundPart, Field(discriminator="type")]


class Script(BaseModel):
    provider: Literal["byteplus", "minimax"]
    parts: list[Part] = Field(min_length=1)
    model: Literal[tuple(model for model, _ in MinimaxTtsConfig.MODELS)] = MinimaxTtsConfig.DEFAULT_MODEL

    def plain_parts(self) -> list[dict]:
        parts = [part.model_dump(exclude_none=True) for part in self.parts]
        for part in parts:
            if part.get("tone") == {}:
                del part["tone"]
        return parts


class Generate(Script):
    name: str
    voice: str = Field(min_length=1, max_length=200)
    overwrite: bool = False
    speech_rate: Rate = 0
    loudness_rate: Rate = 0
    speed: float = Field(default=1.0, ge=MinimaxTtsConfig.SPEED_RANGE[0], le=MinimaxTtsConfig.SPEED_RANGE[1])
    pitch: int = Field(default=0, ge=MinimaxTtsConfig.PITCH_RANGE[0], le=MinimaxTtsConfig.PITCH_RANGE[1])
    volume: float = Field(default=1.0, ge=MinimaxTtsConfig.VOLUME_RANGE[0], le=MinimaxTtsConfig.VOLUME_RANGE[1])
    language: Literal[tuple(code for code, _ in MinimaxTtsConfig.LANGUAGES)] = "auto"
    text_normalization: bool = False


@router.get("")
def list_speech() -> dict:
    result = {**recorder_context.speech.options(), "clips": recorder_context.speech.clips()}
    return result


@router.get("/voices/{provider}/sample")
def voice_sample(provider: Literal["byteplus", "minimax"], voice_id: str) -> FileResponse:
    """A voice's sample from data/tts/sample, made ahead of time; 404 when it hasn't been made."""
    path = recorder_context.speech.voice_sample(provider, voice_id)
    response = FileResponse(path, media_type="audio/wav")
    return response


@router.get("/voices/{provider}")
def list_voices(provider: Literal["byteplus", "minimax"]) -> dict:
    """Every voice of that service: language it speaks, gender, scenario, description, where to hear it."""
    catalog = recorder_context.speech.voices(provider)
    return catalog


@router.post("/direction")
def direction(tone: Tone) -> dict:
    """The prompt BytePlus would get for this tone (it is never spoken) and the label its span shows."""
    result = recorder_context.speech.direct(tone.model_dump(exclude_none=True))
    return result


@router.post("/plan")
def plan(script: Script) -> dict:
    """What Generate would send, request by request; nothing is sent."""
    requests = recorder_context.speech.plan(script.provider, script.plain_parts(), script.model)
    result = {"requests": requests}
    return result


@router.post("")
def generate(command: Generate) -> dict:
    clip = recorder_context.speech.generate(
        command.name, command.provider, command.voice, command.plain_parts(), command.overwrite,
        speech_rate=command.speech_rate, loudness_rate=command.loudness_rate, model=command.model,
        speed=command.speed, pitch=command.pitch, volume=command.volume, language=command.language,
        text_normalization=command.text_normalization)
    return clip


@router.get("/{name}/audio")
def get_audio(name: str) -> FileResponse:
    path = recorder_context.speech.audio_path(name)
    response = FileResponse(path, filename=path.name, media_type="audio/wav", headers={"Cache-Control": "no-store"})
    return response


@router.delete("/{name}")
def delete_speech(name: str) -> dict:
    recorder_context.speech.delete(name)
    result = {"name": name}
    return result


def demo_speech_api() -> None:
    """Reads only: options, a prompt, a plan; a request without a key is refused, nothing is generated."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api_recorder.errors import register_error_handlers

    app = FastAPI()
    app.include_router(router)
    register_error_handlers(app)
    client = TestClient(app)
    listing = client.get("/api/speech").json()
    logger.info("{} presets, {} clips", len(listing["voice_direction"]["presets"]), len(listing["clips"]))
    logger.info("Direction {}", client.post("/api/speech/direction", json={"preset_id": "103"}).json())
    parts = [{"type": "text", "text": "您好！", "tone": {"emotion": "happy"}}, {"type": "pause", "seconds": 0.5},
             {"type": "sound", "tag": "laughs"}, {"type": "text", "text": "欢迎。"}]
    logger.info("Plan {}", client.post("/api/speech/plan", json={"provider": "minimax", "parts": parts}).json())
    refused = client.post("/api/speech/plan", json={"provider": "byteplus", "parts": parts})
    logger.info("Sound tag for BytePlus -> {} {}", refused.status_code, refused.json()["detail"])


def main() -> None:
    use_utf8_output()
    demo_speech_api()


if __name__ == "__main__":
    main()
