"""What the robot says, as parts: text with an optional tone, pauses and (MiniMax) sound tags.

A script turns into the requests one Generate sends: neighbouring text with the same tone goes out as one
request, a pause between different tones becomes silence joined in between, and nothing but the words
(and MiniMax's own <#s#> / (tag) marks) ever reaches the spoken text.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import json
import re
from collections.abc import Mapping

from loguru import logger

from config.settings import SpeechConfig, use_utf8_output


class SpeechScript:
    PROVIDERS = ("byteplus", "minimax")

    def __init__(self, parts: list[Mapping]) -> None:
        """parts: {"type": "text", "text", "tone"?, "pace"?} | {"type": "pause", "seconds"} | {"type": "sound", "tag"}.
        tone is a BytePlus Voice Direction ({preset_id, style}) or a MiniMax {"emotion"}; pace is MiniMax only."""
        self.parts = [dict(part) for part in parts]
        if not any(part["type"] == "text" and part["text"].strip() for part in self.parts):
            raise ValueError("Enter the text to speak")
        if len(self.text()) > SpeechConfig.MAX_TEXT_CHARACTERS:
            raise ValueError(f"The text is longer than {SpeechConfig.MAX_TEXT_CHARACTERS:,} characters")

    def text(self) -> str:
        """Just the words, for listing and searching."""
        text = "".join(part["text"] for part in self.parts if part["type"] == "text")
        return text

    def requests(self, provider: str) -> list[dict]:
        """In order: {"kind": "speech", "text", "tone", "pace"} and {"kind": "silence", "seconds"}."""
        units = self._byteplus_units() if provider == "byteplus" else self._minimax_units()
        speech = [unit for unit in units if unit["kind"] == "speech"]
        if len(speech) > SpeechConfig.MAX_REQUESTS:
            raise ValueError(f"{len(speech)} differently toned parts; one Generate sends at most "
                             f"{SpeechConfig.MAX_REQUESTS}")
        return units

    def _byteplus_units(self) -> list[dict]:
        units: list[dict] = []
        for part in self.parts:
            if part["type"] == "sound":
                raise ValueError("Sound tags are MiniMax only")
            if part["type"] == "pause":
                self._add_silence(units, part["seconds"])
                continue
            key = self._key(part.get("tone"), None)
            if units and units[-1]["kind"] == "speech" and units[-1]["key"] == key:
                units[-1]["text"] += part["text"]
            else:
                units.append({"kind": "speech", "text": part["text"], "tone": part.get("tone"), "pace": None,
                              "key": key})
        result = self._finish(units)
        return result

    def _minimax_units(self) -> list[dict]:
        """A pause inside one tone stays inline (<#0.5#>), where MiniMax keeps the intonation going; between
        tones it becomes silence. A sound tag follows the text before it, or leads the text after a pause."""
        units: list[dict] = []
        pause = 0.0
        lead = ""
        for part in self.parts:
            if part["type"] == "pause":
                pause += part["seconds"]
                continue
            last = units[-1] if units and units[-1]["kind"] == "speech" else None
            if part["type"] == "sound":
                if last is not None and not pause:
                    last["text"] += f"({part['tag']})"
                else:
                    lead += f"({part['tag']})"
                continue
            key = self._key(part.get("tone"), part.get("pace"))
            text = lead + part["text"]
            lead = ""
            if last is not None and last["key"] == key:
                last["text"] += (f"<#{self._seconds(pause)}#>" if pause else "") + text
            else:
                if pause:
                    self._add_silence(units, pause)
                units.append({"kind": "speech", "text": text, "tone": part.get("tone"), "pace": part.get("pace"),
                              "key": key})
            pause = 0.0
        if lead:
            last = next((unit for unit in reversed(units) if unit["kind"] == "speech"), None)
            if pause:
                self._add_silence(units, pause)
                pause = 0.0
            units.append({"kind": "speech", "text": lead, "tone": last and last["tone"],
                          "pace": last and last["pace"], "key": None})
        if pause:
            self._add_silence(units, pause)
        result = self._finish(units)
        return result

    @staticmethod
    def _add_silence(units: list[dict], seconds: float) -> None:
        if units and units[-1]["kind"] == "silence":
            units[-1]["seconds"] += seconds
        else:
            units.append({"kind": "silence", "seconds": seconds})

    @staticmethod
    def _finish(units: list[dict]) -> list[dict]:
        """Drop the grouping keys. A part with nothing to read (only spaces, punctuation or a line break,
        e.g. the "。" left after toning a sentence) is refused by the services ("No readable text"), so
        it joins the speech before it, or the speech after it, or goes."""
        finished = []
        carry = ""
        for unit in units:
            unit = {key: value for key, value in unit.items() if key != "key"}
            if unit["kind"] == "speech" and not re.search(r"\w", unit["text"]):
                previous = next((item for item in reversed(finished) if item["kind"] == "speech"), None)
                if previous is not None:
                    previous["text"] += unit["text"].rstrip(chr(10))
                else:
                    carry += unit["text"].strip()
                continue
            if unit["kind"] == "speech" and carry:
                unit["text"] = carry + unit["text"]
                carry = ""
            finished.append(unit)
        return finished

    @staticmethod
    def _key(tone: Mapping | None, pace: float | None) -> str:
        key = json.dumps([tone, pace], sort_keys=True)
        return key

    @staticmethod
    def _seconds(seconds: float) -> str:
        """MiniMax takes 0.01–99.99 s with at most two decimals."""
        text = f"{min(99.99, max(0.01, seconds)):.2f}".rstrip("0").rstrip(".")
        return text


def demo_speech_script() -> None:
    welcome = {"preset_id": "101"}
    intro = {"preset_id": "103"}
    script = SpeechScript([
        {"type": "text", "text": "您好，欢迎来到 G1 展厅！", "tone": welcome},
        {"type": "pause", "seconds": 0.5},
        {"type": "text", "text": "我是今天的接待机器人小G。", "tone": intro},
        {"type": "text", "text": "If you need anything, just ask me."},
    ])
    for unit in script.requests("byteplus"):
        logger.info("BytePlus {}", unit)
    happy = {"emotion": "happy"}
    script = SpeechScript([
        {"type": "text", "text": "您好，欢迎！", "tone": happy},
        {"type": "sound", "tag": "laughs"},
        {"type": "pause", "seconds": 0.5},
        {"type": "text", "text": "今天由我带您参观。", "tone": happy},
        {"type": "pause", "seconds": 1.0},
        {"type": "text", "text": "有问题随时问我。", "tone": {"emotion": "neutral"}, "pace": 1.1},
    ])
    for unit in script.requests("minimax"):
        logger.info("MiniMax {}", unit)


def main() -> None:
    use_utf8_output()
    demo_speech_script()


if __name__ == "__main__":
    main()
