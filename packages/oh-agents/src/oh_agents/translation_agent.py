"""E1 跨语言整合 agent（TranslationGraph）：翻译学家工作流。

流程（langgraph）：source（bronze 文本） → translate（Tier.EXECUTE，按源语言
切换翻译学家规则 prompt，裁决 1） → verify（确定性校验：实体别名/专有名词
保留检查，结论入 term_notes） → persist（translations 独立表，裁决 5）。

降级语义：LLM 失败/超时 → engine=offline + body 空（诚实降级，不冒充）。
"""

import asyncio
import datetime as _dt
import operator
import re
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from oh_contracts.enums import Tier
from pydantic import BaseModel

from .agent_base import AgentSessions, make_checkpointer

# 翻译 prompt 版本（纪律改动须同步递增；run output 双写供审计）
TRANSLATE_PROMPT_VERSION = "translate-v1"

_LLM_TIMEOUT = 90.0

# 裁决 1：不同语言 → 不同翻译学家规则（prompt 拼段）
_LINGUIST_RULES: dict[str, str] = {
    "zh": "中文译写规范：专有名词保留原文并在首次出现时括注；机构名按官方中译；数字与日期本地化。",
    "ja": "日本語規範：固有名詞は原文併記、公式訳語を採用、敬体で統一。",
    "ko": "한국어 규범: 고유명사 병기, 공식 용어 채택.",
    "ar": "قواعد الترجمة: أسماء أعلام مع النص الأصلي بين قوسين، مراعاة اتجاه الكتابة.",
    "ru": "Правила: имена собственные с оригиналом в скобках, официальные переводы.",
    "default": (
        "General rules: keep proper nouns with original in parentheses on first"
        " mention; preserve numbers, dates and entities; do not add information."
    ),
}


class TranslationOutputP(BaseModel):
    title: str = ""
    body: str = ""
    term_notes: list[str] = []


class TranslationState(TypedDict, total=False):
    item_key: str
    title: str
    text: str
    source_language: str
    target_language: str
    title_out: str
    body_out: str
    notes: list[str]
    translation: dict
    llm_failed: str
    errors: Annotated[list[str], operator.add]
    _model_hint: str
    usage: dict[str, Any]


def _system_prompt(source_language: str) -> str:
    rule = _LINGUIST_RULES.get(source_language, _LINGUIST_RULES["default"])
    return (
        "你是资深财经翻译学家。把给定标题与正文翻译为目标语言，仅输出 JSON。"
        f"{rule}"
        "禁止编造或增删信息；长句按目标语言语序重组但语义必须忠实。"
    )


def _verify_terms(title: str, text: str, title_out: str, body_out: str) -> tuple[bool, list[str]]:
    """确定性校验：原文专名（大写词序列/机构缩写）应在译文保留或括注。"""
    notes: list[str] = []
    pattern = r"\b(?:[A-Z][a-zA-Z&]+(?:\s+[A-Z][a-zA-Z&]+){0,3}|[A-Z]{2,})\b"
    tokens = re.findall(pattern, f"{title} {text}")
    candidates = [t for t in dict.fromkeys(tokens) if len(t) >= 3][:8]
    joined = f"{title_out} {body_out}"
    missing = [t for t in candidates if t not in joined]
    if candidates and missing:
        notes.append(f"以下专名未在译文出现，请人工复核是否已意译：{'、'.join(missing[:4])}")
    if len(body_out) < max(20, len(text) // 8):
        notes.append("译文长度明显偏短，可能存在截断或漏译，请复核。")
    return (not missing, notes)


def build_translation_graph(
    *,
    router: Any = None,
    store: Any = None,
    now_fn: Any = None,
    sessions: AgentSessions | None = None,
):
    async def translate_node(state: TranslationState) -> dict[str, Any]:
        if router is None:
            return {"errors": ["llm_unavailable"], "llm_failed": "router 未配置"}
        user = (
            f"目标语言：{state.get('target_language', 'en')}\n"
            f"标题：{state.get('title', '')}\n正文：\n{state.get('text', '')}"
            f"\n（Prompt 版本：{TRANSLATE_PROMPT_VERSION}）"
        )
        try:
            async with asyncio.timeout(_LLM_TIMEOUT):
                parsed, ref, usage = await router.invoke(
                    Tier.EXECUTE,
                    _system_prompt(state.get("source_language", "")),
                    user,
                    TranslationOutputP,
                )
        except Exception as exc:  # noqa: BLE001 —— 诚实降级
            msg = str(exc) or type(exc).__name__
            return {"errors": [f"llm_failed: {msg}"], "llm_failed": msg}
        if not parsed.body.strip():
            return {"errors": ["llm_empty_output"], "llm_failed": "LLM 返回空译文"}
        return {
            "title_out": parsed.title,
            "body_out": parsed.body,
            "notes": list(parsed.term_notes),
            "_model_hint": f"{ref.provider}/{ref.model_id}",
            "usage": {
                "provider": ref.provider,
                "model": ref.model_id,
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
                "latency_ms": usage.latency_ms if usage else 0,
            },
        }

    async def persist_node(state: TranslationState) -> dict[str, Any]:
        now = now_fn() if now_fn else _dt.datetime.now(_dt.UTC).isoformat()
        if state.get("llm_failed"):
            engine, model_hint = "offline", ""
            title_out, body_out = "", ""
            notes: list[str] = [f"翻译未完成：{state.get('llm_failed', '')[:80]}"]
        else:
            engine = "llm"
            model_hint = state.get("_model_hint", "")
            title_out = state.get("title_out", "")
            body_out = state.get("body_out", "")
            _, vnotes = _verify_terms(
                state.get("title", ""), state.get("text", ""), title_out, body_out
            )
            notes = list(state.get("notes") or []) + vnotes
        from oh_contracts.translations import TranslationItem

        item = TranslationItem(
            translation_id=f"tr-{state['item_key'][:8]}-{state.get('target_language', 'en')}",
            item_key=state["item_key"],
            source_language=state.get("source_language", ""),
            target_language=state.get("target_language", "en"),
            title_translated=title_out,
            body_translated=body_out,
            term_notes=notes,
            engine=engine,  # type: ignore[arg-type]
            model_hint=model_hint,
            translated_at=str(now),
        )
        if store is not None:
            store.upsert_translation(
                item.item_key,
                item.model_dump(mode="json"),
                engine=engine,
                source_language=item.source_language,
                target_language=item.target_language,
                translated_at=str(now),
            )
        return {"translation": item.model_dump(mode="json")}

    g: StateGraph = StateGraph(TranslationState)
    g.add_node("translate", translate_node)
    g.add_node("persist", persist_node)
    g.set_entry_point("translate")
    g.add_edge("translate", "persist")
    g.add_edge("persist", END)
    if sessions is not None:
        return g.compile(checkpointer=make_checkpointer(sessions))
    return g.compile()
