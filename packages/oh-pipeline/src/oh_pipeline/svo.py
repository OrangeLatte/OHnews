"""句级主体-动作-方向词级结构解析（光谱 v2 地基，交互式工作台的数据源）。

与 v0 spectra 的差异：不再整句染一色（框架词袋），而是词级标注
主体（已知实体）与动作（域+方向），渲染时颜色落在语义单元上。

诚实边界：v0 动作词典是精选高频集（货币/贸易/业绩/人事/市场/政策
六域十二方向），未命中动作的句子仍带框架色作兜底；测量效度门禁
（裁决 B）未过前全部输出仅供内部开发用途。
"""

from __future__ import annotations

import re
from typing import Any

from oh_pipeline.entities import EntityRegistry
from oh_pipeline.rules import STANCE_NEGATIVE, STANCE_POSITIVE
from oh_pipeline.spectra import split_sentences
from oh_pipeline.tagger import _count_hits

# —— 动作词典：域 → 方向 → 线索词（lowercase；ASCII 走词边界，中文子串）——
ACTION_LEXICON: dict[str, dict[str, tuple[str, ...]]] = {
    "monetary": {
        "easing": (
            "降息",
            "降准",
            "宽松",
            "量化宽松",
            "下调利率",
            "注入流动性",
            "rate cut",
            "cuts rates",
            "cut rates",
            "easing",
            "pivot to cuts",
            "lower rates",
            "quantitative easing",
            "rate-cut",
        ),
        "tightening": (
            "加息",
            "紧缩",
            "缩表",
            "上调利率",
            "收紧",
            "鹰派",
            "rate hike",
            "hikes rates",
            "hiked",
            "tighten",
            "tightening",
            "raise rates",
            "raises rates",
            "hawkish",
            "quantitative tightening",
        ),
        "hold": (
            "按兵不动",
            "维持利率",
            "利率不变",
            "hold rates",
            "holds rates",
            "unchanged rates",
            "pause",
        ),
    },
    "trade": {
        "escalate": (
            "加征关税",
            "关税",
            "制裁",
            "禁令",
            "报复",
            "贸易战",
            "出口管制",
            "拉黑",
            "tariff",
            "tariffs",
            "sanction",
            "sanctions",
            "export controls",
            "retaliat",
            "trade war",
            "blacklist",
            "crackdown",
            "restrictions",
        ),
        "deescalate": (
            "豁免",
            "取消关税",
            "达成协议",
            "休战",
            "缓和",
            "磋商",
            "谈判",
            "exempt",
            "exemption",
            "truce",
            "de-escalat",
            "reach a deal",
            "trade deal",
            "talks",
            "suspend tariffs",
            "rollback",
        ),
    },
    "earnings": {
        "beat": (
            "超预期",
            "超出预期",
            "上调指引",
            "业绩预增",
            "创纪录营收",
            "beat",
            "beats",
            "above expectations",
            "raises guidance",
            "record revenue",
            "blowout",
        ),
        "miss": (
            "不及预期",
            "低于预期",
            "下调指引",
            "业绩预警",
            "盈警",
            "miss",
            "misses",
            "missed",
            "below expectations",
            "cuts guidance",
            "warns on",
            "profit warning",
        ),
    },
    "personnel": {
        "exit": (
            "辞职",
            "离职",
            "卸任",
            "下台",
            "被解职",
            "裁员",
            "退休",
            "resign",
            "resigns",
            "step down",
            "steps down",
            "departs",
            "fired",
            "ousted",
            "layoff",
            "layoffs",
            "job cuts",
        ),
        "enter": (
            "任命",
            "提名",
            "接任",
            "上任",
            "聘任",
            "appointed",
            "appoints",
            "nominate",
            "nominates",
            "named as",
            "sworn in",
            "takes over",
        ),
    },
    "market": {
        "rally": (
            "暴涨",
            "飙升",
            "大涨",
            "创新高",
            "走强",
            "反弹",
            "surge",
            "surges",
            "soars",
            "rallies",
            "rally",
            "record high",
            "jumps",
            "climbs",
        ),
        "plunge": (
            "暴跌",
            "重挫",
            "崩盘",
            "熔断",
            "跳水",
            "下挫",
            "plunge",
            "plunges",
            "slump",
            "slumps",
            "crash",
            "crashes",
            "tumbles",
            "selloff",
            "sell-off",
            "sink",
        ),
    },
    "policy": {
        "expand": (
            "刺激",
            "减税",
            "补贴",
            "扩表",
            "发债",
            "stimulus",
            "tax cut",
            "tax cuts",
            "subsidy",
            "subsidies",
            "fiscal boost",
            "spending package",
        ),
        "restrict": (
            "加税",
            "削减",
            "紧缩财政",
            "提高税",
            "austerity",
            "spending cuts",
            "tax increase",
            "tax hike",
            "levy",
            "levies",
        ),
    },
}

_DIRECTION_ORDER: tuple[str, ...] = (
    "easing",
    "tightening",
    "hold",
    "escalate",
    "deescalate",
    "beat",
    "miss",
    "exit",
    "enter",
    "rally",
    "plunge",
    "expand",
    "restrict",
)


def _domain_of(direction: str) -> str:
    for domain, dirs in ACTION_LEXICON.items():
        if direction in dirs:
            return domain
    raise KeyError(direction)


def _word_pattern(word: str) -> re.Pattern[str] | None:
    """ASCII 词走边界匹配（防 "hold"⊂"threshold"），中文返回 None 用子串。"""
    if word.isascii():
        return re.compile(rf"\b{re.escape(word.strip())}\b")
    return None


def match_actions(text: str) -> list[dict[str, Any]]:
    """词级动作定位：[{domain,direction,text,start,end}]，重叠保留先到者。"""
    low = text.lower()
    raw: list[tuple[int, int, str, str, str]] = []
    for domain, dirs in ACTION_LEXICON.items():
        for direction, words in dirs.items():
            for w in words:
                w = w.lower().strip()
                if not w:
                    continue
                pat = _word_pattern(w)
                if pat is not None:
                    for m in pat.finditer(low):
                        raw.append((m.start(), m.end(), domain, direction, w))
                else:
                    start = 0
                    while (i := low.find(w, start)) != -1:
                        raw.append((i, i + len(w), domain, direction, w))
                        start = i + 1
    raw.sort(key=lambda t: (t[0], -(t[1] - t[0])))
    picked: list[dict[str, Any]] = []
    last_end = -1
    for s, e, domain, direction, w in raw:
        if s >= last_end:
            picked.append(
                {"domain": domain, "direction": direction, "text": w, "start": s, "end": e}
            )
            last_end = e
    return picked


def parse_sentence(text: str, registry: EntityRegistry) -> dict[str, Any]:
    """单句词级结构：主体（实体定位）+ 动作（域/方向）+ 立场 + 框架兜底。

    返回 {text, entities[], actions[], stance, frame}；entities/actions
    的 start/end 均为原句字节偏移（lowercase 不改变长度，可直接切片）。
    """
    low = text.lower()
    entities = [
        {"entity_id": eid, "text": text[s:e], "start": s, "end": e}
        for eid, s, e, _alias in registry.match_with_positions(text)
    ]
    actions = match_actions(text)
    pos = _count_hits(low, STANCE_POSITIVE)
    neg = _count_hits(low, STANCE_NEGATIVE)
    stance = "critical" if neg > pos else ("supportive" if pos > neg else None)
    return {
        "text": text,
        "entities": entities,
        "actions": actions,
        "stance": stance,
        "frame": None,  # 由调用方按需用 spectra.sentence_spectrum 兜底
    }


def parse_passage(text: str, registry: EntityRegistry) -> list[dict[str, Any]]:
    """全文逐句结构解析（光谱 v2 主入口）。"""
    return [parse_sentence(s, registry) for s in split_sentences(text)]
