from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .captions_fallback import ExpressionLabel, get_fallback_captions


_BANNED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(老婆|老公|对象|谈恋爱|恋爱|心动|撩|撩人|在一起)"),
    re.compile(r"(亲亲|亲一口|亲一下|亲个|么么|接吻|舌|湿身|性感|内衣|私密|胸|脱)"),
    re.compile(r"(傻|蠢|废物|滚|恶心|丑|死|讨厌你)"),
    re.compile(r"(地址|小区|门牌|学校|班级|医院|上火|病|生病|发烧|过敏|用药|打针)"),
]

_PROMPT_MAX_CHARS = 240


def detect_crop_preference(prompt: str | None) -> str:
    if not prompt:
        return ""
    s = prompt.strip()
    mouth = ("嘴", "嘴巴", "嘴唇", "口水")
    closeup = ("特写", "近景", "只要", "只留", "只保留", "只看")
    exclude = ("不要口水巾", "别拍口水巾", "不含口水巾", "不要围兜", "别拍围兜", "不要衣服", "别拍衣服")

    if any(k in s for k in mouth) and any(k in s for k in closeup):
        return "mouth_closeup"
    if any(k in s for k in exclude) and any(k in s for k in mouth):
        return "mouth_closeup"
    return ""


def is_caption_safe(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    if len(s) > 60:
        return False
    for pat in _BANNED_PATTERNS:
        if pat.search(s):
            return False
    return True


def sanitize_caption(text: str) -> str:
    s = re.sub(r"\\s+", " ", (text or "")).strip()
    s = s.replace("\u200b", "")
    s = s.strip("，,。.!！?？…")
    return s or "收到"


def sanitize_user_prompt(text: str | None) -> tuple[str | None, str]:
    """
    Returns (sanitized_prompt_or_none, reason).
    If returned prompt is None, callers should ignore user customization.
    """
    if text is None:
        return None, "empty"
    s = re.sub(r"\\s+", " ", text).strip()
    s = s.replace("\u200b", "")
    if not s:
        return None, "empty"
    if len(s) > _PROMPT_MAX_CHARS:
        s = s[:_PROMPT_MAX_CHARS].rstrip()
    for pat in _BANNED_PATTERNS:
        if pat.search(s):
            return None, "unsafe"
    return s, "ok"


def pick_expression_label(model_label: str | None) -> ExpressionLabel:
    if model_label in ("开心", "委屈", "生气", "震惊", "困"):
        return model_label  # type: ignore[return-value]
    return "不确定"


def ensure_5_safe_captions(candidates: Iterable[str], fallback_label: ExpressionLabel) -> tuple[list[str], bool]:
    safe: list[str] = []
    for c in candidates:
        s = sanitize_caption(c)
        if is_caption_safe(s):
            safe.append(s)
        if len(safe) >= 5:
            break

    if len(safe) >= 5:
        return safe[:5], False

    fallback = get_fallback_captions(fallback_label, 5)
    while len(safe) < 5:
        safe.append(fallback[len(safe)])
    return safe, True


@dataclass(frozen=True)
class FallbackDecision:
    fallback_used: bool
    reason: str
    suggestions: list[str]


DEFAULT_SUGGESTIONS = [
    "请尽量让脸部清晰、光线充足、避免背光",
    "尽量单人入镜，脸部占画面 1/3 以上",
    "避免强遮挡（口罩/帽檐压眼睛等）",
    "尽量正面或微侧，眼睛与嘴巴清楚可见",
]
