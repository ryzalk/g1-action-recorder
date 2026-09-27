"""BytePlus Voice Direction: nine style fields and 150 scene presets, turned into the one prompt BytePlus reads.

Ported from concierge-audio (component/byteplus/prompt_mapper.py and its presets). The prompt is Chinese on
purpose: it is what Seed Speech was steered with there and listened to. It goes in context_texts, never in
the spoken text.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import json
from collections.abc import Mapping

from loguru import logger

from config.settings import SpeechConfig, use_utf8_output

# value -> (label on the page, phrase in the prompt)
FIELDS: dict[str, dict[str, tuple[str, str]]] = {
    "emotion": {
        "neutral": ("平静", "平静"), "happy": ("开心", "开心"), "excited": ("兴奋", "兴奋"),
        "relieved": ("如释重负", "如释重负"), "sad": ("悲伤", "悲伤"), "disappointed": ("失望", "失望"),
        "hurt": ("受伤 / 委屈", "受伤、委屈"), "angry": ("生气", "生气"), "annoyed": ("不耐烦", "不耐烦"),
        "afraid": ("害怕", "害怕"), "nervous": ("紧张", "紧张"), "surprised": ("惊讶", "惊讶"),
        "disgusted": ("厌恶", "厌恶"), "cold": ("冷淡", "冷淡"),
    },
    "intensity": {
        "subtle": ("非常克制", "非常克制的"), "mild": ("轻微", "轻微的"), "moderate": ("适中", ""),
        "strong": ("明显", "明显的"), "intense": ("强烈", "强烈的"),
    },
    "social_tone": {
        "neutral": ("自然", "自然"), "gentle": ("温柔", "温柔"), "warm": ("温暖亲切", "温暖亲切"),
        "intimate": ("亲密", "亲密"), "flirty": ("暧昧", "暧昧"), "cute": ("撒娇感", "带一点撒娇感"),
        "comforting": ("安慰", "安慰人的"), "reassuring": ("让人安心", "让人安心的"),
        "teasing": ("俏皮调侃", "俏皮调侃"), "sarcastic": ("略带讽刺", "略带讽刺"), "firm": ("坚定", "坚定"),
        "serious": ("认真严肃", "认真严肃"), "argumentative": ("争辩", "像在争辩"),
        "distant": ("疏离冷淡", "疏离冷淡"), "professional": ("专业", "专业"), "casual": ("自然随意", "自然随意"),
    },
    "mental_state": {
        "calm": ("平静", "内心平静"), "hesitant": ("犹豫", "有些犹豫"), "shy": ("害羞", "带一点害羞"),
        "expectant": ("期待", "带着期待"), "uncertain": ("不确定", "有些不确定"),
        "restrained": ("克制", "努力克制情绪"), "hurt": ("受伤", "内心受伤"), "exhausted": ("疲惫", "显得疲惫"),
        "desperate": ("绝望", "带着绝望感"), "heartbroken": ("心碎", "有明显心碎感"),
        "confident": ("自信", "显得自信"), "impatient": ("不耐烦", "明显不耐烦"),
        "embarrassed": ("尴尬", "略显尴尬"), "confused": ("困惑", "有些困惑"), "suspicious": ("怀疑", "带着怀疑"),
        "resigned": ("无奈接受", "像是已经无奈接受"), "hopeful": ("希望", "仍带着希望"),
        "overwhelmed": ("情绪压不住", "情绪有些压不住"),
    },
    "communicative_intent": {
        "inform": ("传达信息", "自然地传达信息"), "reassure": ("让对方安心", "像是在让对方安心"),
        "comfort": ("安慰", "像是在安慰对方"), "encourage": ("鼓励", "像是在鼓励对方"),
        "persuade": ("劝说", "带有劝说感"), "question": ("询问", "带着询问感"), "confirm": ("确认", "像是在确认"),
        "warn": ("提醒 / 警告", "带着提醒或警告感"), "apologize": ("道歉", "表达真诚歉意"),
        "thank": ("感谢", "表达真诚感谢"), "complain": ("抱怨", "带一点抱怨感"), "tease": ("逗对方", "像是在逗对方"),
        "confess": ("告白", "像是在说出藏在心里的话"), "reject": ("拒绝", "明确表达拒绝"),
        "request": ("请求", "带着请求感"), "explain": ("解释", "耐心解释"), "challenge": ("挑战", "带着挑战意味"),
        "invite": ("邀请", "自然地邀请对方"),
    },
    "voice_texture": {
        "normal": ("自然", "声音自然"), "soft": ("轻柔", "声音轻柔"), "deep": ("低沉", "声音低沉"),
        "low": ("偏低", "声音偏低"), "bright": ("明亮", "声音明亮"), "hoarse": ("沙哑", "略带沙哑"),
        "breathy": ("气声", "略带气声"), "trembling": ("发颤", "声音微微发颤"), "tearful": ("哭腔", "略带哭腔"),
        "whispering": ("耳语", "用低声耳语发声，带清晰气声而非普通音量说话"), "powerful": ("有力量", "声音有力量"),
        "weak": ("虚弱", "声音略显虚弱"), "tired": ("疲惫", "声音带着疲惫感"), "smiling": ("笑意", "声音里带一点笑意"),
    },
    "pace": {
        "very_slow": ("很慢", "语速很慢"), "slow": ("较慢", "语速较慢"), "slightly_slow": ("稍慢", "语速稍慢"),
        "normal": ("自然", "语速自然"), "slightly_fast": ("稍快", "语速稍快"), "fast": ("较快", "语速较快"),
    },
    "pitch": {
        "low": ("偏低", "音调偏低"), "slightly_low": ("略低", "音调略低"), "normal": ("自然", "音调自然"),
        "slightly_high": ("略高", "音调略高"), "high": ("偏高", "音调偏高"),
    },
    "energy": {
        "very_low": ("很低", "整体能量很低"), "low": ("偏低", "整体能量偏低"), "medium": ("自然", "整体能量自然"),
        "high": ("较高", "整体能量较高"), "very_high": ("很高", "整体能量很高"),
    },
}
# Fields that take none, one or two values; the rest take exactly one.
MULTI_FIELDS = ("mental_state", "voice_texture")
DEFAULT_STYLE = {"emotion": "neutral", "intensity": "subtle", "social_tone": "neutral", "mental_state": ["calm"],
                 "communicative_intent": "inform", "voice_texture": ["normal"], "pace": "normal",
                 "pitch": "normal", "energy": "medium"}


class VoiceDirection:
    def __init__(self, preset_file: Path = SpeechConfig.PRESET_FILE) -> None:
        data = json.loads(Path(preset_file).read_text(encoding="utf-8"))
        self.default_preset_id = data["default_preset_id"]
        self.presets = data["presets"]
        self.by_id = {preset["id"]: preset for preset in self.presets}

    def options(self) -> dict:
        """For the page: the presets in order, and each field's values with their labels."""
        fields = {field: [{"value": value, "label": label} for value, (label, _) in values.items()]
                  for field, values in FIELDS.items()}
        options = {"presets": self.presets, "default_preset_id": self.default_preset_id, "fields": fields,
                   "multi_fields": list(MULTI_FIELDS), "default_style": DEFAULT_STYLE}
        return options

    def check(self, tone: Mapping) -> dict:
        """A tone as the page sends it ({preset_id?, style}) made whole and checked; ValueError names the bad field."""
        preset_id = tone.get("preset_id") or None
        if preset_id is not None and preset_id not in self.by_id:
            raise ValueError(f"Unknown BytePlus preset {preset_id}")
        base = self.by_id[preset_id]["style"] if preset_id else DEFAULT_STYLE
        style = {**base, **(tone.get("style") or {})}
        for field, values in FIELDS.items():
            chosen = style[field] if field in MULTI_FIELDS else [style[field]]
            if len(chosen) > 2:
                raise ValueError(f"Choose at most two values for {field.replace('_', ' ')}")
            unknown = [value for value in chosen if value not in values]
            if unknown:
                raise ValueError(f"{field.replace('_', ' ').capitalize()} can't be {unknown[0]}")
        checked = {"preset_id": preset_id, "style": {field: style[field] for field in FIELDS}}
        return checked

    def prompt(self, tone: Mapping) -> str:
        """The Chinese direction for one toned part; the preset's scene line goes last."""
        checked = self.check(tone)
        style = self._normalize(checked["style"])
        phrase = {field: FIELDS[field] for field in FIELDS}
        sentences = []
        special = self._special_phrase(style)
        if special:
            sentences.append(special)
        else:
            emotion = phrase["emotion"][style["emotion"]][1]
            intensity = phrase["intensity"][style["intensity"]][1]
            tone_phrase = phrase["social_tone"][style["social_tone"]][1]
            if tone_phrase == "自然" and emotion == "平静":
                sentences.append("用自然平静的语气说")
            else:
                sentences.append(f"用{tone_phrase}、{intensity}{emotion}的语气说")
            states = [phrase["mental_state"][value][1] for value in style["mental_state"]]
            sentences.append("，".join([*states, phrase["communicative_intent"][style["communicative_intent"]][1]]))
        voice = [phrase["voice_texture"][value][1] for value in style["voice_texture"]]
        voice += [phrase["pace"][style["pace"]][1], phrase["pitch"][style["pitch"]][1],
                  phrase["energy"][style["energy"]][1]]
        sentences.append("，".join(voice))
        sentences.append("保持吐字清晰，同时充分表现上述语气和发声方式")
        prompt = "。".join(sentence for sentence in sentences if sentence) + "。"
        if checked["preset_id"]:
            prompt += self.by_id[checked["preset_id"]]["scene_prompt"]
        return prompt

    def label(self, tone: Mapping) -> str:
        """What the page shows on a toned span: the preset name, or "自定义" once changed from it."""
        checked = self.check(tone)
        preset = self.by_id.get(checked["preset_id"] or "")
        custom = preset is None or checked["style"] != {field: preset["style"][field] for field in FIELDS}
        label = "自定义" if custom else preset["name"]
        return label

    @staticmethod
    def _normalize(style: dict) -> dict:
        """Combinations that fight each other are softened the way concierge-audio does."""
        style = {**style, "voice_texture": list(style["voice_texture"])}
        textures = style["voice_texture"]
        if style["social_tone"] == "intimate" and "powerful" in textures:
            textures.remove("powerful")
            if "soft" not in textures:
                textures.append("soft")
        if style["emotion"] in {"sad", "hurt", "disappointed"} and style["energy"] == "very_high":
            style["energy"] = "medium"
        afraid = style["emotion"] == "afraid" and style["intensity"] in {"strong", "intense"}
        if afraid and "trembling" not in textures:
            textures.append("trembling")
        if style["emotion"] == "cold" and style["energy"] in {"high", "very_high"}:
            style["energy"] = "low"
        if style["social_tone"] == "professional":
            textures[:] = [value for value in textures if value not in {"tearful", "whispering"}]
        style["voice_texture"] = textures[:2]
        return style

    @staticmethod
    def _special_phrase(style: dict) -> str | None:
        states = set(style["mental_state"])
        intent = style["communicative_intent"]
        if style["emotion"] == "sad" and {"hurt", "restrained"} <= states and intent == "reassure":
            return "用温柔、悲伤但克制的语气说，内心虽然受伤，但仍想让对方安心"
        if style["emotion"] == "nervous" and "shy" in states and intent == "confess":
            return "用紧张而害羞的语气说，像是在鼓起勇气说出藏在心里的话"
        return None


def demo_voice_direction() -> None:
    direction = VoiceDirection()
    options = direction.options()
    categories = list(dict.fromkeys(preset["category"] for preset in options["presets"]))
    logger.info("{} presets in {} categories: {}", len(options["presets"]), len(categories), categories)
    tone = {"preset_id": options["default_preset_id"]}
    logger.info("{} -> {}", direction.label(tone), direction.prompt(tone))
    changed = {"preset_id": "103", "style": {"voice_texture": ["normal", "smiling"], "pace": "slightly_slow"}}
    logger.info("{} -> {}", direction.label(changed), direction.prompt(changed))
    try:
        direction.prompt({"style": {"pace": "sprint"}})
    except ValueError as error:
        logger.info("Refused: {}", error)


def main() -> None:
    use_utf8_output()
    demo_voice_direction()


if __name__ == "__main__":
    main()
