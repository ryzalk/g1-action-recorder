"""Every voice each speech service offers, in one shape: id, name, language it speaks, gender, what it is for,
and (BytePlus) where its official recording is. Samples to play are made ahead (voice_samples.py).

BytePlus: the official TTS 2.0 list with its published recordings (config/byteplus_voices.json); a voice
speaks the one language listed. MiniMax: the account's own list, read live and cached (system voices and any cloned
ones), with the snapshot in config/minimax_voices.json standing in; the language comes from the voice id.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import json
import re
import time
from collections import Counter

from loguru import logger

from config.settings import ByteplusTtsConfig, MinimaxTtsConfig, use_utf8_output
from util.minimax_tts_helper import MinimaxTtsError, MinimaxTtsHelper

# MiniMax voice id prefix -> the language the voice speaks.
MINIMAX_LANGUAGES = {"chinese (mandarin)": "Mandarin Chinese", "arrogant": "Mandarin Chinese",
                     "robot": "Mandarin Chinese", "cantonese": "Cantonese"}
# What a sample says, in the voice's own language; anything not listed says the English line.
SAMPLE_LINES = {
    "Mandarin Chinese": "您好，我是今天的接待机器人，很高兴为您服务。",
    "Chinese": "您好，我是今天的接待机器人，很高兴为您服务。",
    "Cantonese": "你好，我係今日嘅接待機械人，好高興為你服務。",
    "English": "Hello, I'm your guide today. It's nice to meet you.",
    "Japanese": "こんにちは。本日ご案内するロボットです。よろしくお願いします。",
    "Korean": "안녕하세요. 오늘 안내를 맡은 로봇입니다. 반갑습니다.",
    "Spanish": "Hola, soy su guía de hoy. Encantado de conocerle.",
    "Portuguese": "Olá, sou o seu guia de hoje. Muito prazer.",
    "French": "Bonjour, je suis votre guide aujourd'hui. Enchanté.",
    "German": "Hallo, ich bin heute Ihr Guide. Schön, Sie kennenzulernen.",
    "Italian": "Ciao, sono la vostra guida di oggi. Piacere di conoscervi.",
    "Indonesian": "Halo, saya pemandu Anda hari ini. Senang bertemu dengan Anda.",
    "Russian": "Здравствуйте, я ваш гид сегодня. Приятно познакомиться.",
    "Thai": "สวัสดีครับ วันนี้ผมเป็นไกด์ของคุณ ยินดีที่ได้รู้จัก",
    "Vietnamese": "Xin chào, tôi là hướng dẫn viên của bạn hôm nay. Rất vui được gặp bạn.",
    "Arabic": "مرحبا، أنا مرشدك اليوم. سعيد بلقائك.",
}


class VoiceCatalog:
    def __init__(self, minimax: MinimaxTtsHelper | None = None, **kwargs) -> None:
        self.minimax = minimax or MinimaxTtsHelper()
        self.byteplus_file = kwargs.get("byteplus_file", ByteplusTtsConfig.VOICE_FILE)
        self.minimax_file = kwargs.get("minimax_file", MinimaxTtsConfig.VOICE_FILE)
        self.cache_seconds = kwargs.get("cache_seconds", MinimaxTtsConfig.VOICE_CACHE_SECONDS)
        self._minimax_cache: tuple[float, list[dict]] | None = None
        self._byteplus_cache: list[dict] | None = None

    def voices(self, provider: str) -> dict:
        """{"voices": [...], "languages": [[language, count], ...] most common first, "source": where from}."""
        voices, source = (self._byteplus(), "official list") if provider == "byteplus" else self._minimax()
        languages = Counter(voice["language"] for voice in voices).most_common()
        catalog = {"voices": voices, "languages": [list(entry) for entry in languages], "source": source}
        return catalog

    def find(self, provider: str, voice_id: str) -> dict | None:
        """Never calls out: the MiniMax list as last read, else the snapshot (for names on clips, defaults)."""
        if provider == "byteplus":
            voices = self._byteplus()
        elif self._minimax_cache:
            voices = self._minimax_cache[1]
        else:
            voices = [self._minimax_voice(voice, "System")
                      for voice in json.loads(Path(self.minimax_file).read_text(encoding="utf-8"))["voices"]]
        voice = next((voice for voice in voices if voice["id"] == voice_id), None)
        return voice

    def sample_line(self, language: str) -> str:
        """The first word of the language decides: "American English" says the English line."""
        line = SAMPLE_LINES.get(language) or next(
            (text for name, text in SAMPLE_LINES.items() if name in language.split()), SAMPLE_LINES["English"])
        return line

    def _byteplus(self) -> list[dict]:
        if self._byteplus_cache is not None:
            return self._byteplus_cache
        data = json.loads(Path(self.byteplus_file).read_text(encoding="utf-8"))
        self._byteplus_cache = voices = [{"id": voice["id"], "name": voice["name"], "language": voice["language"],
                                          "gender": voice["gender"],
                   "scenario": voice["scenario"], "description": voice["description"], "group": voice["region"],
                   "sample_source": voice["sample_url"]} for voice in data["voices"]]
        return voices

    def _minimax(self) -> tuple[list[dict], str]:
        """Live list, cached; the snapshot when there is no key or the call fails."""
        if self._minimax_cache and time.monotonic() - self._minimax_cache[0] < self.cache_seconds:
            return self._minimax_cache[1], "your MiniMax account"
        if self.minimax.configured:
            try:
                answer = self.minimax.list_voices()
                voices = [self._minimax_voice(voice, "System") for voice in answer.get("system_voice") or []]
                voices += [self._minimax_voice(voice, "My voices")
                           for voice in (answer.get("voice_cloning") or []) + (answer.get("voice_generation") or [])]
                self._minimax_cache = (time.monotonic(), voices)
                return voices, "your MiniMax account"
            except MinimaxTtsError as error:
                logger.warning("MiniMax voice list unavailable, using the snapshot: {}", error)
        snapshot = json.loads(Path(self.minimax_file).read_text(encoding="utf-8"))["voices"]
        voices = [self._minimax_voice(voice, "System") for voice in snapshot]
        return voices, "snapshot (no MiniMax key)"

    @staticmethod
    def _minimax_voice(voice: dict, group: str) -> dict:
        voice_id = voice["voice_id"]
        prefix = voice_id.split("_")[0]
        language = MINIMAX_LANGUAGES.get(prefix.lower(), prefix[:1].upper() + prefix[1:] if "_" in voice_id else "")
        description = " ".join(voice.get("description") or [])
        words = description.lower()
        gender = ("Female" if re.search(r"\b(female|woman|girl|lady|mother|sister)\b", words) else
                  "Male" if re.search(r"\b(male|man|boy|gentleman|father|brother)\b", words) else "")
        entry = {"id": voice_id, "name": voice.get("voice_name") or voice_id, "language": language or "Unknown",
                 "gender": gender, "scenario": "", "description": description, "group": group}
        return entry


def demo_voice_catalog() -> None:
    catalog = VoiceCatalog()
    for provider in ("byteplus", "minimax"):
        listing = catalog.voices(provider)
        logger.info("{}: {} voices ({}); languages {}", provider, len(listing["voices"]), listing["source"],
                    listing["languages"][:8])
    logger.info("Kian: {}", catalog.find("byteplus", ByteplusTtsConfig.DEFAULT_VOICE))
    logger.info("Sample lines: {} / {}", catalog.sample_line("Mandarin Chinese"),
                catalog.sample_line("American English"))


def main() -> None:
    use_utf8_output()
    demo_voice_catalog()


if __name__ == "__main__":
    main()
