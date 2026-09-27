"""MiniMax T2A v2: one text with its voice settings in, a 16 kHz mono WAV out."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import requests
from loguru import logger

from config.settings import MinimaxTtsConfig, SpeechConfig, use_utf8_output


class MinimaxTtsError(RuntimeError):
    """MiniMax didn't return usable audio."""


class MinimaxTtsHelper:
    # base_resp.status_code values, in words a user can act on.
    KNOWN_ERRORS = {1001: "the request timed out", 1002: "too many requests, try again shortly",
                    1004: "the API key is invalid or not allowed", 1039: "the token quota is used up",
                    1042: "too many invalid characters in the text",
                    2013: "a parameter was refused; check the model and voice"}

    def __init__(self, api_key: str = MinimaxTtsConfig.API_KEY, **kwargs) -> None:
        self.api_key = api_key.strip()
        self.url = kwargs.get("url", MinimaxTtsConfig.URL)
        self.timeout = kwargs.get("timeout", MinimaxTtsConfig.TIMEOUT)
        self.session = kwargs.get("session") or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def payload(self, text: str, voice: str, **kwargs) -> dict:
        """text may hold pauses <#0.5#> and sound tags (laughs). kwargs: model, emotion (API name),
        speed, volume, pitch, language, text_normalization."""
        voice_setting = {"voice_id": voice, "speed": kwargs.get("speed", 1.0), "vol": kwargs.get("volume", 1.0),
                         "pitch": kwargs.get("pitch", 0),
                         "text_normalization": kwargs.get("text_normalization", False)}
        if kwargs.get("emotion"):
            voice_setting["emotion"] = kwargs["emotion"]
        payload = {"model": kwargs.get("model", MinimaxTtsConfig.DEFAULT_MODEL), "text": text, "stream": False,
                   "output_format": "hex", "language_boost": kwargs.get("language", "auto"),
                   "voice_setting": voice_setting,
                   "audio_setting": {"sample_rate": SpeechConfig.SAMPLE_RATE, "format": "wav", "channel": 1}}
        return payload

    def list_voices(self) -> dict:
        """Every voice the account can use: system_voice, voice_cloning, voice_generation lists."""
        url = self.url.rsplit("/v1/", 1)[0] + "/v1/get_voice"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            response = self.session.post(url, headers=headers, json={"voice_type": "all"}, timeout=self.timeout)
            answer = response.json()
        except (requests.RequestException, ValueError) as error:
            raise MinimaxTtsError(f"Couldn't list MiniMax voices: {error}") from error
        status = (answer.get("base_resp") or {}).get("status_code", 0)
        if response.status_code >= 400 or status:
            raise MinimaxTtsError(f"MiniMax refused the voice list ({status or response.status_code})")
        return answer

    def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        """The WAV file MiniMax returns, as bytes."""
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            response = self.session.post(self.url, headers=headers, json=self.payload(text, voice, **kwargs),
                                         timeout=self.timeout)
            answer = response.json()
        except requests.RequestException as error:
            raise MinimaxTtsError(f"Couldn't reach MiniMax: {error}") from error
        except ValueError as error:
            raise MinimaxTtsError(f"MiniMax answered HTTP {response.status_code} with no JSON") from error
        status = (answer.get("base_resp") or {}).get("status_code", 0)
        if response.status_code >= 400 or status:
            message = (answer.get("base_resp") or {}).get("status_msg") or f"HTTP {response.status_code}"
            raise MinimaxTtsError(f"MiniMax failed ({status}): {self.KNOWN_ERRORS.get(status, message)}")
        data = answer.get("data") or {}
        if data.get("status", 2) != 2 or not data.get("audio"):
            raise MinimaxTtsError("MiniMax returned no finished audio")
        try:
            audio = bytes.fromhex(data["audio"])
        except ValueError as error:
            raise MinimaxTtsError("MiniMax sent audio that isn't valid hex") from error
        return audio


def demo_minimax_tts_helper() -> None:
    """Without MINIMAX_API_KEY only the request is shown; with it, one short clip is generated."""
    helper = MinimaxTtsHelper()
    logger.info("Request: {}", helper.payload("你好<#0.5#>(laughs) 欢迎！", MinimaxTtsConfig.DEFAULT_VOICE,
                                              emotion="happy"))
    if not helper.configured:
        logger.info("MINIMAX_API_KEY not set; no request sent")
        return
    wav = helper.synthesize("你好，欢迎来到展厅。", MinimaxTtsConfig.DEFAULT_VOICE, emotion="happy")
    path = BASE_DIR / "output" / "demo" / "minimax_tts" / "hello.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav)
    logger.info("{}: {:,} bytes", path, len(wav))


def main() -> None:
    use_utf8_output()
    demo_minimax_tts_helper()


if __name__ == "__main__":
    main()
