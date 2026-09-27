"""Speech clips for the robot: a toned script sent to BytePlus or MiniMax, joined into data/tts/<name>.wav
with a <name>.json that records exactly what was asked for."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from collections.abc import Mapping
from urllib.parse import quote

from loguru import logger

from component.common.naming import clean_name
from component.common.pose import utc_now, utc_text
from component.speech_generation.speech_script import SpeechScript
from component.speech_generation.voice_catalog import VoiceCatalog
from component.speech_generation.voice_direction import VoiceDirection
from component.speech_generation.voice_samples import VoiceSamples
from config.settings import ByteplusTtsConfig, MinimaxTtsConfig, PathConfig, SpeechConfig, use_utf8_output
from util.byteplus_tts_helper import ByteplusTtsHelper
from util.data_file_helper import DataFileHelper
from util.minimax_tts_helper import MinimaxTtsHelper
from util.wav_helper import WavHelper


class SpeechService:
    SCHEMA_VERSION = 2
    PROVIDER_NAMES = {"byteplus": "BytePlus", "minimax": "MiniMax"}

    def __init__(self, speech_dir: Path = PathConfig.DATA_DIR / "tts", **kwargs) -> None:
        """kwargs: byteplus, minimax (helpers; tests pass fakes), catalog. Samples are in speech_dir/sample."""
        self.speech_dir = speech_dir
        self.byteplus = kwargs.get("byteplus") or ByteplusTtsHelper()
        self.minimax = kwargs.get("minimax") or MinimaxTtsHelper()
        self.direction = VoiceDirection()
        self.catalog = kwargs.get("catalog") or VoiceCatalog(self.minimax)
        self.samples = VoiceSamples(speech_dir / "sample", minimax=self.minimax, catalog=self.catalog)
        self.wav = WavHelper()
        self.files = DataFileHelper()

    def options(self) -> dict:
        byteplus_default = self._playable("byteplus", self.catalog.find("byteplus", ByteplusTtsConfig.DEFAULT_VOICE))
        options = {
            "byteplus": {"configured": self.byteplus.configured, "default_voice": byteplus_default,
                         "rate_range": ByteplusTtsConfig.RATE_RANGE},
            "minimax": {"configured": self.minimax.configured,
                        "default_voice": self._minimax_default(),
                        "models": [{"id": model, "label": label} for model, label in MinimaxTtsConfig.MODELS],
                        "default_model": MinimaxTtsConfig.DEFAULT_MODEL,
                        "sound_tag_models": MinimaxTtsConfig.SOUND_TAG_MODELS,
                        "languages": [{"id": code, "label": label} for code, label in MinimaxTtsConfig.LANGUAGES],
                        "emotions": MinimaxTtsConfig.EMOTIONS, "sound_tags": MinimaxTtsConfig.SOUND_TAGS,
                        "speed_range": MinimaxTtsConfig.SPEED_RANGE, "pitch_range": MinimaxTtsConfig.PITCH_RANGE,
                        "volume_range": MinimaxTtsConfig.VOLUME_RANGE},
            "voice_direction": self.direction.options(),
            "pause_choices": SpeechConfig.PAUSE_CHOICES,
            "max_pause_seconds": SpeechConfig.MAX_PAUSE_SECONDS,
            "max_characters": SpeechConfig.MAX_TEXT_CHARACTERS,
            "max_requests": SpeechConfig.MAX_REQUESTS,
        }
        return options

    def voices(self, provider: str) -> dict:
        """The whole list for the voice panel, with the languages it covers; sample_url is set only for
        voices whose sample has been made."""
        catalog = self.catalog.voices(provider)
        listing = {**catalog, "voices": [self._playable(provider, voice) for voice in catalog["voices"]]}
        return listing

    def voice_sample(self, provider: str, voice_id: str) -> Path:
        """The sample made ahead of time; nothing is generated here."""
        path = self.samples.path(provider, voice_id)
        if not path.is_file():
            raise FileNotFoundError(f"No sample for {voice_id} yet. Make them with "
                                    "uv run python component/speech_generation/voice_samples.py --build")
        return path

    def _playable(self, provider: str, voice: dict | None) -> dict | None:
        """A copy of the voice with the URL of its sample, or sample_url None when there is none yet."""
        if voice is None:
            return None
        url = (f"/api/speech/voices/{provider}/sample?voice_id={quote(voice['id'])}"
               if self.samples.has(provider, voice["id"]) else None)
        playable = {key: value for key, value in voice.items() if key != "sample_source"}
        playable["sample_url"] = url
        return playable

    def _minimax_default(self) -> dict:
        voice = self._playable("minimax", self.catalog.find("minimax", MinimaxTtsConfig.DEFAULT_VOICE))
        default = voice or {"id": MinimaxTtsConfig.DEFAULT_VOICE, "name": MinimaxTtsConfig.DEFAULT_VOICE,
                            "language": "Mandarin Chinese", "gender": "", "description": "", "sample_url": None}
        return default

    def clips(self) -> list[dict]:
        clips = [self._view(self.files.read_json(self.speech_dir / f"{name}.json"))
                 for name in self.files.list_names(self.speech_dir, ".json")]
        return clips

    def direct(self, tone: Mapping) -> dict:
        """The prompt a BytePlus tone turns into, and the label its span shows."""
        direction = {"prompt": self.direction.prompt(tone), "label": self.direction.label(tone)}
        return direction

    def plan(self, provider: str, parts: list[Mapping], model: str = MinimaxTtsConfig.DEFAULT_MODEL) -> list[dict]:
        """The requests a Generate would send, with each one's prompt or emotion; nothing is sent."""
        units = SpeechScript(parts).requests(provider)
        if provider == "minimax" and model not in MinimaxTtsConfig.SOUND_TAG_MODELS and any(
                part["type"] == "sound" for part in parts):
            raise ValueError(f"Sound tags need speech-2.8; {model} would read them out")
        planned = []
        for unit in units:
            if unit["kind"] == "silence":
                planned.append({"kind": "silence", "seconds": round(unit["seconds"], 3)})
            elif provider == "byteplus":
                prompt = self.direction.prompt(unit["tone"]) if unit["tone"] else ""
                planned.append({"kind": "speech", "text": unit["text"], "prompt": prompt})
            else:
                emotion = (unit["tone"] or {}).get("emotion")
                if emotion is not None and emotion not in MinimaxTtsConfig.EMOTIONS:
                    raise ValueError(f"MiniMax has no emotion {emotion}")
                planned.append({"kind": "speech", "text": unit["text"],
                                "emotion": "calm" if emotion == "neutral" else emotion, "pace": unit["pace"]})
        return planned

    def generate(self, name: str, provider: str, voice: str, parts: list[Mapping], overwrite: bool = False,
                 **settings) -> dict:
        """settings: BytePlus speech_rate, loudness_rate; MiniMax model, speed, pitch, volume, language,
        text_normalization."""
        helper = self.byteplus if provider == "byteplus" else self.minimax
        if not helper.configured:
            key = "BYTEPLUS_API_KEY" if provider == "byteplus" else "MINIMAX_API_KEY"
            raise ValueError(f"{self.PROVIDER_NAMES[provider]} isn't set up. Put {key} in .env and restart.")
        name = clean_name(name)
        json_path = self.speech_dir / f"{name}.json"
        if json_path.exists() and not overwrite:
            raise FileExistsError(f"{name} already exists")
        voice = voice.strip()
        if not voice:
            raise ValueError("Choose a voice")
        model = settings.get("model", MinimaxTtsConfig.DEFAULT_MODEL)
        planned = self.plan(provider, parts, model)
        pcm = bytearray()
        for request in planned:
            if request["kind"] == "silence":
                pcm.extend(self.wav.silence(request["seconds"]))
            elif provider == "byteplus":
                pcm.extend(self.byteplus.synthesize(request["text"], voice, request["prompt"],
                                                    speech_rate=settings.get("speech_rate", 0),
                                                    loudness_rate=settings.get("loudness_rate", 0)))
            else:
                wav = self.minimax.synthesize(request["text"], voice, model=model, emotion=request["emotion"],
                                              speed=request["pace"] or settings.get("speed", 1.0),
                                              pitch=settings.get("pitch", 0), volume=settings.get("volume", 1.0),
                                              language=settings.get("language", "auto"),
                                              text_normalization=settings.get("text_normalization", False))
                pcm.extend(self.wav.pcm_from_wav(wav))
        wav_path = self.wav.write(bytes(pcm), self.speech_dir / f"{name}.wav")
        kept = ("speech_rate", "loudness_rate") if provider == "byteplus" else (
            "model", "speed", "pitch", "volume", "language", "text_normalization")
        clip = {"schema_version": self.SCHEMA_VERSION, "name": name, "provider": provider, "voice": voice,
                "settings": {key: settings[key] for key in kept if key in settings},
                "script": [dict(part) for part in parts], "text": SpeechScript(parts).text(),
                "requests": planned, "wav_filename": wav_path.name,
                "duration_seconds": round(self.wav.seconds(bytes(pcm)), 3),
                "sample_rate_hz": SpeechConfig.SAMPLE_RATE, "channels": 1, "sample_width_bytes": 2,
                "created_at": utc_text(utc_now())}
        self.files.write_json(json_path, clip, overwrite=True)
        logger.info("Generated {} with {}: {} requests, {:.2f} s", name, provider,
                    sum(request["kind"] == "speech" for request in planned), clip["duration_seconds"])
        view = self._view(clip)
        return view

    def audio_path(self, name: str) -> Path:
        path = self.speech_dir / f"{clean_name(name)}.wav"
        if not path.exists():
            raise FileNotFoundError(f"No speech clip named {name}")
        return path

    def delete(self, name: str) -> None:
        """Removes exactly this clip's WAV and JSON."""
        name = clean_name(name)
        for path in (self.speech_dir / f"{name}.wav", self.speech_dir / f"{name}.json"):
            path.unlink(missing_ok=True)
        logger.info("Deleted speech clip {}", name)

    def _view(self, clip: dict) -> dict:
        """One shape for the page, whichever schema the file has. Schema 1 (before MiniMax) was BytePlus with
        one tone for the whole text."""
        if clip.get("schema_version", 1) < 2:
            voice = clip["speaker"]
            script = [{"type": "text", "text": clip["text"], "label": clip.get("tone_name")}]
            provider = "byteplus"
        else:
            voice = clip["voice"]
            provider = clip["provider"]
            script = [self._labelled(provider, part) for part in clip["script"]]
        known = self._playable(provider, self.catalog.find(provider, voice))
        voice_info = known or {"id": voice, "name": voice, "language": "", "gender": "", "description": "",
                               "sample_url": None}
        voice_name = voice_info["name"]
        view = {"name": clip["name"], "provider": provider, "voice": voice, "voice_name": voice_name,
                "voice_info": voice_info,
                "duration_seconds": clip["duration_seconds"], "text": clip["text"], "script": script,
                "requests": sum(request["kind"] == "speech" for request in clip.get("requests", [])) or 1,
                "wav_filename": clip["wav_filename"], "created_at": clip["created_at"],
                "older": clip.get("schema_version", 1) < 2, "settings": clip.get("settings", {})}
        return view

    def _labelled(self, provider: str, part: dict) -> dict:
        """A text part with the label and colour group its span shows on the page."""
        if part["type"] != "text" or not part.get("tone"):
            return part
        if provider == "minimax":
            labelled = {**part, "label": part["tone"]["emotion"].capitalize(), "group": part["tone"]["emotion"]}
            return labelled
        preset = self.direction.by_id.get(part["tone"].get("preset_id") or "")
        labelled = {**part, "label": self.direction.label(part["tone"]),
                    "group": preset["subcategory"] if preset else "custom"}
        return labelled


def demo_speech_service() -> None:
    """Plans a BytePlus and a MiniMax script without sending anything; lists the clips in data/tts."""
    service = SpeechService()
    options = service.options()
    logger.info("BytePlus set up: {}; MiniMax set up: {}; {} presets", options["byteplus"]["configured"],
                options["minimax"]["configured"], len(options["voice_direction"]["presets"]))
    parts = [{"type": "text", "text": "您好，欢迎来到展厅！", "tone": {"preset_id": "101"}},
             {"type": "pause", "seconds": 0.5},
             {"type": "text", "text": "我是今天的接待机器人。", "tone": {"preset_id": "103"}}]
    for request in service.plan("byteplus", parts):
        logger.info("BytePlus {}", request)
    parts = [{"type": "text", "text": "您好！", "tone": {"emotion": "happy"}}, {"type": "sound", "tag": "laughs"},
             {"type": "pause", "seconds": 0.5}, {"type": "text", "text": "欢迎。", "tone": {"emotion": "neutral"}}]
    for request in service.plan("minimax", parts):
        logger.info("MiniMax {}", request)
    logger.info("Clips in {}: {}", service.speech_dir, [clip["name"] for clip in service.clips()])


def main() -> None:
    use_utf8_output()
    demo_speech_service()


if __name__ == "__main__":
    main()
