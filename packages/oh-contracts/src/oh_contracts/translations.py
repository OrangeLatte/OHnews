"""E1 跨语言整合契约：翻译副本独立存储（原文不可变，裁决 5）。

翻译学家工作流按源语言切换 prompt（裁决 1）；校验结果诚实入 term_notes。
"""

from typing import Literal

from pydantic import Field

from .strict import _StrictBase

TranslationEngine = Literal["llm", "offline"]
TranslationTarget = Literal["en", "zh", "ja", "ko", "fr", "es", "de", "ru", "ar"]


class TranslationItem(_StrictBase):
    """单篇文章的翻译副本（独立表，不改写 bronze 原文）。"""

    translation_id: str
    item_key: str
    source_language: str = ""
    target_language: TranslationTarget = "en"
    title_translated: str = ""
    body_translated: str = ""
    term_notes: list[str] = Field(default_factory=list)
    engine: TranslationEngine = "llm"
    model_hint: str = ""
    translated_at: str


class TranslationQuality(_StrictBase):
    """校验结论：确定性检查 + LLM 回译要点（诚实呈现，不静默）。"""

    term_ok: bool
    notes: list[str] = Field(default_factory=list)


__all__ = [
    "TRANSLATION_ENGINES",
    "TRANSLATION_TARGETS",
    "TranslationEngine",
    "TranslationItem",
    "TranslationQuality",
    "TranslationTarget",
]

TRANSLATION_ENGINES: tuple[TranslationEngine, ...] = ("llm", "offline")
TRANSLATION_TARGETS: tuple[TranslationTarget, ...] = (
    "en",
    "zh",
    "ja",
    "ko",
    "fr",
    "es",
    "de",
    "ru",
    "ar",
)
