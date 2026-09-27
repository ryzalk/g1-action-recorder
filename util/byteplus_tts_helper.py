"""BytePlus Seed Speech 2.0 (unidirectional streaming TTS): one text and one style prompt in, raw PCM out."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import base64
import binascii
import codecs
import json
from collections.abc import Iterator, Mapping
from uuid import uuid4

import requests
from loguru import logger

from config.settings import ByteplusTtsConfig, SpeechConfig, use_utf8_output


class ByteplusTtsError(RuntimeError):
    """BytePlus didn't return usable audio."""


class ByteplusTtsHelper:
    # Codes BytePlus answers with, in words a user can act on.
    KNOWN_ERRORS = {40402003: "the text is too long", 45000000: "this voice isn't available to the account",
                    55000000: "server error; check that the voice matches the resource"}

    def __init__(self, api_key: str = ByteplusTtsConfig.API_KEY, **kwargs) -> None:
        self.api_key = api_key.strip()
        self.url = kwargs.get("url", ByteplusTtsConfig.URL)
        self.timeout = kwargs.get("timeout", ByteplusTtsConfig.TIMEOUT)
        self.session = kwargs.get("session") or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def payload(self, text: str, voice: str, prompt: str = "", **kwargs) -> dict:
        """The prompt goes in context_texts, never in text: it steers the delivery and is not read out.
        kwargs: speech_rate, loudness_rate (-50..100, 0 normal)."""
        additions = {"disable_markdown_filter": True, "disable_emoji_filter": True}
        if prompt:
            additions["context_texts"] = [prompt]
        payload = {
            "user": {"uid": ByteplusTtsConfig.USER_ID},
            "req_params": {
                "text": text,
                "speaker": voice,
                "audio_params": {"format": "pcm", "sample_rate": SpeechConfig.SAMPLE_RATE,
                                 "speech_rate": kwargs.get("speech_rate", 0),
                                 "loudness_rate": kwargs.get("loudness_rate", 0)},
                "additions": json.dumps(additions, ensure_ascii=False),
            },
        }
        return payload

    def synthesize(self, text: str, voice: str, prompt: str = "", **kwargs) -> bytes:
        """16 kHz mono 16-bit PCM."""
        request_id = str(uuid4())
        headers = {"X-Api-Key": self.api_key, "X-Api-Resource-Id": ByteplusTtsConfig.RESOURCE_ID,
                   "X-Api-Request-Id": request_id, "Content-Type": "application/json"}
        try:
            response = self.session.post(self.url, headers=headers, json=self.payload(text, voice, prompt, **kwargs),
                                         stream=True, timeout=self.timeout)
        except requests.RequestException as error:
            raise ByteplusTtsError(f"Couldn't reach BytePlus: {error}") from error
        if response.status_code >= 400:
            raise ByteplusTtsError(f"BytePlus answered HTTP {response.status_code} (request {request_id})")
        pcm = bytearray()
        completed = False
        # The stream is JSON objects back to back: code 0 carries base64 PCM (or sentence metadata with
        # no audio), 20000000 marks the end, anything else is a failure.
        for message in self._messages(response):
            code = message.get("code")
            if code == 20000000:
                completed = True
            elif code == 0:
                if message.get("data"):
                    try:
                        pcm.extend(base64.b64decode(message["data"], validate=True))
                    except (ValueError, binascii.Error) as error:
                        raise ByteplusTtsError("BytePlus sent audio that isn't valid base64") from error
            else:
                reason = self.KNOWN_ERRORS.get(code, message.get("message") or "unknown error")
                raise ByteplusTtsError(f"BytePlus failed ({code}): {reason}")
        response.close()
        if not completed or not pcm:
            raise ByteplusTtsError("BytePlus ended the stream without audio")
        audio = bytes(pcm)
        return audio

    @staticmethod
    def _messages(response: requests.Response) -> Iterator[Mapping]:
        """Objects may be split anywhere across network chunks, even inside a UTF-8 character."""
        decoder = json.JSONDecoder()
        utf8 = codecs.getincrementaldecoder("utf-8")()
        buffer = ""
        for chunk in [*response.iter_content(chunk_size=8192), None]:
            buffer += utf8.decode(chunk or b"", final=chunk is None)
            while True:
                buffer = buffer.lstrip()
                if buffer.startswith("data:"):
                    buffer = buffer[5:].lstrip()
                try:
                    message, end = decoder.raw_decode(buffer)
                except json.JSONDecodeError:
                    break
                buffer = buffer[end:]
                yield message
        if buffer.strip():
            raise ByteplusTtsError("BytePlus sent an incomplete message")


def demo_byteplus_tts_helper() -> None:
    """Without BYTEPLUS_API_KEY only the request is shown; with it, one short clip is generated."""
    from util.wav_helper import WavHelper

    helper = ByteplusTtsHelper()
    prompt = "用温暖亲切的语气说。"
    logger.info("Request: {}", helper.payload("你好，欢迎来到展厅。", ByteplusTtsConfig.DEFAULT_VOICE, prompt))
    if not helper.configured:
        logger.info("BYTEPLUS_API_KEY not set; no request sent")
        return
    pcm = helper.synthesize("你好，欢迎来到展厅。", ByteplusTtsConfig.DEFAULT_VOICE, prompt)
    path = WavHelper().write(pcm, BASE_DIR / "output" / "demo" / "byteplus_tts" / "hello.wav")
    logger.info("{}: {:.2f} s", path, WavHelper().seconds(pcm))


def main() -> None:
    use_utf8_output()
    demo_byteplus_tts_helper()


if __name__ == "__main__":
    main()
