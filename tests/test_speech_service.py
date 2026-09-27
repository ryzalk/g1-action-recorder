from __future__ import annotations

import base64
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from component.speech_generation.service import SpeechService
from component.speech_generation.voice_catalog import VoiceCatalog
from component.speech_generation.voice_direction import VoiceDirection
from component.speech_generation.voice_samples import VoiceSamples
from config.settings import ByteplusTtsConfig, MinimaxTtsConfig, SpeechConfig
from util.byteplus_tts_helper import ByteplusTtsError, ByteplusTtsHelper
from util.minimax_tts_helper import MinimaxTtsHelper
from util.wav_helper import WavHelper

HALF_SECOND = b"\x01\x00" * (SpeechConfig.SAMPLE_RATE // 2)


class FakeByteplus(ByteplusTtsHelper):
    """Half a second of audio per request instead of calling BytePlus; keeps what it was asked."""

    def __init__(self, api_key: str = "test") -> None:
        super().__init__(api_key)
        self.calls = []

    def synthesize(self, text: str, voice: str, prompt: str = "", **kwargs) -> bytes:
        self.calls.append({"text": text, "voice": voice, "prompt": prompt, **kwargs})
        return HALF_SECOND


class FakeMinimax(MinimaxTtsHelper):
    def __init__(self, api_key: str = "test", sample_rate: int = SpeechConfig.SAMPLE_RATE) -> None:
        super().__init__(api_key)
        self.calls = []
        self.sample_rate = sample_rate

    def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        self.calls.append({"text": text, "voice": voice, **kwargs})
        return WavHelper(self.sample_rate).to_wav(HALF_SECOND)

    def list_voices(self) -> dict:
        """Two system voices and one cloned one, as /v1/get_voice lists them."""
        voices = {"system_voice": [
            {"voice_id": "English_CalmWoman", "voice_name": "Calm Woman",
             "description": ["A calm adult female voice."]},
            {"voice_id": "Chinese (Mandarin)_Reliable_Executive", "voice_name": "Reliable Executive",
             "description": ["A steady adult male voice in Standard Mandarin."]}],
            "voice_cloning": [{"voice_id": "my_clone_1", "description": []}]}
        return voices


class FakeDownloader:
    """Hands back a tiny WAV for any URL and keeps which were asked for."""

    def __init__(self) -> None:
        self.urls = []

    def fetch(self, url: str) -> bytes:
        self.urls.append(url)
        return WavHelper().to_wav(HALF_SECOND)


class FakeStream:
    """A requests.Response whose body arrives in the chunks given."""

    status_code = 200

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    def iter_content(self, chunk_size: int):
        return iter(self.chunks)

    def close(self) -> None:
        pass


class FakeSession:
    def __init__(self, response: FakeStream) -> None:
        self.response = response
        self.sent = None

    def post(self, url: str, **kwargs) -> FakeStream:
        self.sent = kwargs["json"]
        return self.response


class SpeechServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.speech_dir = Path(self.folder.name)
        self.byteplus = FakeByteplus()
        self.minimax = FakeMinimax()
        self.service = SpeechService(self.speech_dir, byteplus=self.byteplus, minimax=self.minimax)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_byteplus_segments_pauses_and_prompts(self) -> None:
        parts = [{"type": "text", "text": "您好，", "tone": {"preset_id": "101"}},
                 {"type": "text", "text": "欢迎！", "tone": {"preset_id": "101"}},
                 {"type": "pause", "seconds": 0.5},
                 {"type": "text", "text": "我是小G。", "tone": {"preset_id": "103"}},
                 {"type": "text", "text": " Hello."}]
        clip = self.service.generate("welcome", "byteplus", ByteplusTtsConfig.DEFAULT_VOICE, parts, speech_rate=10)
        # Same tone merges, a pause becomes silence, untoned text goes without a prompt.
        self.assertEqual([call["text"] for call in self.byteplus.calls], ["您好，欢迎！", "我是小G。", " Hello."])
        direction = VoiceDirection()
        self.assertEqual(self.byteplus.calls[1]["prompt"], direction.prompt({"preset_id": "103"}))
        self.assertEqual(self.byteplus.calls[2]["prompt"], "")
        self.assertEqual(self.byteplus.calls[0]["speech_rate"], 10)
        self.assertAlmostEqual(clip["duration_seconds"], 2.0)
        self.assertEqual(clip["requests"], 3)
        labels = [part.get("label") for part in clip["script"]]
        self.assertEqual(labels, ["首次迎宾", "首次迎宾", None, "自我介绍", None])
        self.assertEqual(clip["script"][3]["group"], "身份介绍")
        saved = json.loads((self.speech_dir / "welcome.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["schema_version"], 2)
        self.assertNotIn("语气", saved["text"])
        self.assertEqual(WavHelper().seconds(WavHelper().pcm_from_wav((self.speech_dir / "welcome.wav").read_bytes())),
                         2.0)
        self.service.delete("welcome")
        self.assertEqual(list(self.speech_dir.iterdir()), [])

    def test_minimax_inline_pause_sound_and_pace(self) -> None:
        parts = [{"type": "text", "text": "您好！", "tone": {"emotion": "happy"}},
                 {"type": "sound", "tag": "laughs"},
                 {"type": "pause", "seconds": 0.5},
                 {"type": "text", "text": "欢迎。", "tone": {"emotion": "happy"}},
                 {"type": "pause", "seconds": 1.0},
                 {"type": "text", "text": "请问。", "tone": {"emotion": "neutral"}, "pace": 1.2}]
        clip = self.service.generate("hello", "minimax", "English_CalmWoman", parts, model="speech-2.8-turbo",
                                     speed=0.9)
        self.assertEqual([call["text"] for call in self.minimax.calls], ["您好！(laughs)<#0.5#>欢迎。", "请问。"])
        self.assertEqual([call["emotion"] for call in self.minimax.calls], ["happy", "calm"])
        self.assertEqual([call["speed"] for call in self.minimax.calls], [0.9, 1.2])
        self.assertAlmostEqual(clip["duration_seconds"], 2.0)
        self.assertEqual((clip["provider"], clip["voice_name"]), ("minimax", "Calm Woman"))

    def test_punctuation_alone_is_never_a_request(self) -> None:
        # Toning a sentence but not the full stop or line break after it left "。" and "\n" as parts of their own.
        parts = [{"type": "text", "text": "您好，欢迎", "tone": {"preset_id": "101"}},
                 {"type": "text", "text": "。\n"},
                 {"type": "text", "text": "我是小G", "tone": {"preset_id": "103"}},
                 {"type": "text", "text": "！"}]
        self.service.generate("punct", "byteplus", ByteplusTtsConfig.DEFAULT_VOICE, parts)
        self.assertEqual([call["text"] for call in self.byteplus.calls], ["您好，欢迎。", "我是小G！"])
        leading = [{"type": "text", "text": "「"}, {"type": "text", "text": "你好", "tone": {"emotion": "happy"}}]
        self.assertEqual([unit["text"] for unit in self.service.plan("minimax", leading)], ["「你好"])

    def test_refusals(self) -> None:
        sound = [{"type": "text", "text": "Hi"}, {"type": "sound", "tag": "laughs"}]
        with self.assertRaisesRegex(ValueError, "MiniMax only"):
            self.service.plan("byteplus", sound)
        with self.assertRaisesRegex(ValueError, "speech-2.8"):
            self.service.plan("minimax", sound, "speech-02-hd")
        with self.assertRaisesRegex(ValueError, "text to speak"):
            self.service.plan("byteplus", [{"type": "pause", "seconds": 1.0}])
        with self.assertRaisesRegex(ValueError, "Pace can't be"):
            self.service.plan("byteplus", [{"type": "text", "text": "Hi", "tone": {"style": {"pace": "sprint"}}}])
        with self.assertRaisesRegex(ValueError, "no emotion"):
            self.service.plan("minimax", [{"type": "text", "text": "Hi", "tone": {"emotion": "bored"}}])
        many = [{"type": "text", "text": "x", "tone": {"emotion": ("happy", "sad")[index % 2]}} for index in range(60)]
        with self.assertRaisesRegex(ValueError, "at most"):
            self.service.plan("minimax", many)
        self.assertEqual(self.byteplus.calls + self.minimax.calls, [])

    def test_overwrite_and_not_configured(self) -> None:
        parts = [{"type": "text", "text": "Hi"}]
        self.service.generate("hi", "byteplus", ByteplusTtsConfig.DEFAULT_VOICE, parts)
        with self.assertRaises(FileExistsError):
            self.service.generate("hi", "byteplus", ByteplusTtsConfig.DEFAULT_VOICE, parts)
        self.service.generate("hi", "byteplus", ByteplusTtsConfig.DEFAULT_VOICE, parts, overwrite=True)
        service = SpeechService(self.speech_dir, byteplus=FakeByteplus(""), minimax=FakeMinimax(""))
        self.assertFalse(service.options()["minimax"]["configured"])
        with self.assertRaisesRegex(ValueError, "MINIMAX_API_KEY"):
            service.generate("x", "minimax", MinimaxTtsConfig.DEFAULT_VOICE, parts)

    def test_wrong_sample_rate_is_refused(self) -> None:
        service = SpeechService(self.speech_dir, byteplus=self.byteplus, minimax=FakeMinimax(sample_rate=24000))
        with self.assertRaisesRegex(ValueError, "24000 Hz"):
            service.generate("x", "minimax", MinimaxTtsConfig.DEFAULT_VOICE, [{"type": "text", "text": "Hi"}])
        self.assertFalse((self.speech_dir / "x.json").exists())

    def test_schema_one_clip_still_lists(self) -> None:
        WavHelper().write(HALF_SECOND, self.speech_dir / "old.wav")
        old = {"schema_version": 1, "name": "old", "text": "你好", "wav_filename": "old.wav", "duration_seconds": 0.5,
               "speaker": "zh_male_m191_uranus_bigtts", "speaker_name": "Kian", "tone": "warm", "tone_name": "Warm",
               "created_at": "2026-09-20T00:00:00Z"}
        (self.speech_dir / "old.json").write_text(json.dumps(old), encoding="utf-8")
        view = self.service.clips()[0]
        self.assertEqual((view["provider"], view["voice_name"], view["older"]), ("byteplus", "Kian", True))
        self.assertEqual(view["script"], [{"type": "text", "text": "你好", "label": "Warm"}])


class VoiceCatalogTest(unittest.TestCase):
    def test_byteplus_full_list_with_official_recordings(self) -> None:
        listing = VoiceCatalog(FakeMinimax("")).voices("byteplus")
        self.assertEqual(len(listing["voices"]), 177)
        self.assertTrue(all(voice["sample_source"].startswith("https://") for voice in listing["voices"]))
        kian = next(voice for voice in listing["voices"] if voice["id"] == ByteplusTtsConfig.DEFAULT_VOICE)
        self.assertEqual((kian["name"], kian["language"], kian["gender"]), ("Kian", "Chinese", "Male"))
        self.assertEqual(listing["languages"][0], ["American English", 68])

    def test_minimax_live_list_and_snapshot(self) -> None:
        live = VoiceCatalog(FakeMinimax()).voices("minimax")
        by_id = {voice["id"]: voice for voice in live["voices"]}
        self.assertEqual(by_id["Chinese (Mandarin)_Reliable_Executive"]["language"], "Mandarin Chinese")
        self.assertEqual(by_id["English_CalmWoman"]["gender"], "Female")
        self.assertEqual(by_id["my_clone_1"]["group"], "My voices")
        snapshot = VoiceCatalog(FakeMinimax("")).voices("minimax")
        self.assertGreater(len(snapshot["voices"]), 300)
        self.assertIn("snapshot", snapshot["source"])



class VoiceSamplesTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.speech_dir = Path(folder.name) / "tts"
        self.minimax = FakeMinimax()
        self.downloader = FakeDownloader()
        catalog = VoiceCatalog(self.minimax)
        self.samples = VoiceSamples(self.speech_dir / "sample", minimax=self.minimax, catalog=catalog,
                                    downloader=self.downloader, pause_seconds=0)
        self.service = SpeechService(self.speech_dir, byteplus=FakeByteplus(), minimax=self.minimax, catalog=catalog)

    def test_build_makes_missing_samples_once(self) -> None:
        report = self.samples.build("minimax")
        self.assertEqual((report["made"], report["kept"], report["failed"]), (3, 0, []))
        self.assertIn("接待机器人", next(call["text"] for call in self.minimax.calls
                                     if call["voice"] == "Chinese (Mandarin)_Reliable_Executive"))
        again = self.samples.build("minimax")
        self.assertEqual((again["made"], again["kept"], len(self.minimax.calls)), (0, 3, 3))
        self.samples.build("byteplus", limit=2)
        self.assertEqual(len(self.downloader.urls), 2)
        self.assertTrue(self.downloader.urls[0].startswith("https://"))

    def test_service_plays_only_samples_made_ahead(self) -> None:
        voice = "Chinese (Mandarin)_Reliable_Executive"
        with self.assertRaisesRegex(FileNotFoundError, "voice_samples.py --build"):
            self.service.voice_sample("minimax", voice)
        self.assertIsNone(self.service.options()["minimax"]["default_voice"]["sample_url"])
        self.samples.build("minimax")
        path = self.service.voice_sample("minimax", voice)
        self.assertEqual(path.parent, self.speech_dir / "sample" / "minimax")
        self.assertNotEqual(path.stem, voice)
        by_id = {entry["id"]: entry for entry in self.service.voices("minimax")["voices"]}
        self.assertIn("voice_id=Chinese%20%28Mandarin%29_Reliable_Executive", by_id[voice]["sample_url"])
        self.assertNotIn("sample_source", self.service.voices("byteplus")["voices"][0])
        self.assertIsNone(self.service.voices("byteplus")["voices"][0]["sample_url"])
        calls = len(self.minimax.calls)
        self.service.voice_sample("minimax", voice)
        self.assertEqual(len(self.minimax.calls), calls)
        self.assertEqual(self.service.clips(), [])


class VoiceDirectionTest(unittest.TestCase):
    def test_preset_prompt_and_custom_label(self) -> None:
        direction = VoiceDirection()
        self.assertEqual(len(direction.presets), 150)
        self.assertEqual(direction.prompt({"preset_id": "105"}),
                         "用专业、轻微的平静的语气说。内心平静，显得自信，耐心解释。声音自然，语速稍慢，音调自然，整体能量自然。"
                         "保持吐字清晰，同时充分表现上述语气和发声方式。像现场为访客指路，方向和地点读清楚，信息之间自然停顿。")
        self.assertEqual(direction.label({"preset_id": "105"}), "路线指引")
        self.assertEqual(direction.label({"preset_id": "105", "style": {"pace": "fast"}}), "自定义")


class ByteplusStreamTest(unittest.TestCase):
    def test_split_messages_metadata_and_end(self) -> None:
        pcm = b"\x02\x00" * 8
        body = (json.dumps({"code": 0, "data": base64.b64encode(pcm).decode(), "message": "好"}, ensure_ascii=False)
                + json.dumps({"code": 0, "data": None, "sentence": {"text": "你好"}}, ensure_ascii=False)
                + json.dumps({"code": 20000000, "message": "ok"})).encode()
        # Cut inside the multi-byte 好 and inside a JSON object.
        cut = body.index("好".encode()) + 1
        session = FakeSession(FakeStream([body[:cut], body[cut:cut + 7], body[cut + 7:]]))
        helper = ByteplusTtsHelper("key", session=session)
        self.assertEqual(helper.synthesize("你好", "voice", "用开心的语气说。"), pcm)
        additions = json.loads(session.sent["req_params"]["additions"])
        self.assertEqual(additions["context_texts"], ["用开心的语气说。"])
        self.assertEqual(session.sent["req_params"]["text"], "你好")

    def test_error_code_and_missing_end(self) -> None:
        failing = FakeSession(FakeStream([json.dumps({"code": 45000000, "message": "x"}).encode()]))
        with self.assertRaisesRegex(ByteplusTtsError, "voice isn't available"):
            ByteplusTtsHelper("key", session=failing).synthesize("hi", "voice")
        cut_off = FakeSession(FakeStream([json.dumps({"code": 0, "data": "AAA="}).encode()]))
        with self.assertRaisesRegex(ByteplusTtsError, "without audio"):
            ByteplusTtsHelper("key", session=cut_off).synthesize("hi", "voice")


if __name__ == "__main__":
    unittest.main()
