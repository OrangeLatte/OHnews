"""词典语义层（M3-S1）：确定性、免费、PIT 安全的文档标注引擎。

设计来源：REFACTOR_V2.md §4 S1。
三层产出（全部 engine="lexicon"）：
- Action：复用 svo.ACTION_LEXICON 词级定位 → ActionMention。
- Emotion 双层近似：expressed=情绪词密度；audience=风险/不确定性触发词密度
  （承 NDI 地板效应教训，词典法 audience 是粗近似，confidence 封顶 0.6）。
- SRL 论元启发式：subject=实体命中；object=动作词后窗内金融词表 NP；
  target=动作词后窗内实体；time=日期正则；location=地点别名表。
  causality 仅 LLM v2 产出，词典层恒 None。

诚实边界：词典覆盖有限，未命中情绪的文档 emotions 仍产出但 confidence 低；
否定语义不处理（"不加征关税" 仍命中 escalate，同 svo v0 边界）。
"""

from __future__ import annotations

import re
from datetime import datetime

from oh_contracts.semantics import (
    ActionMention,
    EmotionLabel,
    EmotionVector,
    SemanticAnnotation,
    SemanticRole,
)

from oh_pipeline.entities import EntityRegistry
from oh_pipeline.spectra import split_sentences
from oh_pipeline.svo import match_actions

# —— 情绪词典：标签 → 线索词（lowercase；ASCII 词边界，中文子串）——
EMOTION_LEXICON: dict[EmotionLabel, tuple[str, ...]] = {
    EmotionLabel.FEAR: (
        "恐慌",
        "害怕",
        "崩盘",
        "逃亡",
        "panic",
        "fear",
        "dread",
        "collapse",
    ),
    EmotionLabel.ANGER: (
        "愤怒",
        "抗议",
        "谴责",
        "怒斥",
        "愤怒",
        "anger",
        "furious",
        "outrage",
        "condemn",
        "blasts",
        "slams",
    ),
    EmotionLabel.OPTIMISM: (
        "乐观",
        "看好",
        "复苏",
        "反弹",
        "向好",
        "optimism",
        "optimistic",
        "hopeful",
        "upbeat",
        "recovery",
        "bullish",
        "confidence in",
    ),
    EmotionLabel.UNCERTAINTY: (
        "不确定",
        "未知",
        "难以预料",
        "摇摆",
        "uncertain",
        "uncertainty",
        "unpredictable",
        "unclear",
        "ambiguous",
        "mixed signals",
    ),
    EmotionLabel.CONFIDENCE: (
        "有信心",
        "坚信",
        "确信",
        "笃定",
        "confident",
        "assured",
        "certain",
        "committed to",
        "stands firm",
    ),
    EmotionLabel.URGENCY: (
        "紧急",
        "紧迫",
        "立即",
        "刻不容缓",
        "urgent",
        "urgency",
        "immediately",
        "swiftly",
        "rapid response",
        "race to",
    ),
    EmotionLabel.CONCERN: (
        "担忧",
        "关切",
        "忧虑",
        "警惕",
        "担心",
        "concern",
        "worried",
        "worry",
        "anxious",
        "caution",
        "alarmed",
        "warns of",
    ),
    EmotionLabel.RELIEF: (
        "缓和",
        "松一口气",
        "缓解",
        "退让",
        "relief",
        "eased",
        "eases",
        "ease",
        "defused",
        "de-escalat",
        "soothe",
        "reassure",
    ),
}

# —— 读者效应触发词（audience 层）：风险/不确定性放大器 ——
RISK_TRIGGERS: tuple[str, ...] = (
    "风险",
    "危机",
    "警告",
    "警报",
    "动荡",
    "失序",
    "risk",
    "crisis",
    "warning",
    "threat",
    "turbulence",
    "instability",
    "default",
    "recession",
    "contagion",
    "escalation",
)

# —— 金融宾语词表（object 启发式）：动作词后窗内命中即记 object ——
_FINANCIAL_OBJECTS: tuple[str, ...] = (
    "利率",
    "汇率",
    "关税",
    "国债",
    "股市",
    "债市",
    "通胀",
    "就业",
    "预算",
    "供应链",
    "rates",
    "tariff",
    "tariffs",
    "yields",
    "stocks",
    "bonds",
    "inflation",
    "jobs",
    "budget",
    "supply chain",
    "sanctions",
    "exports",
    "imports",
    "guidance",
    "revenue",
    "spending",
)

# —— 地点别名表（location 启发式）——
LOCATION_LEXICON: tuple[str, ...] = (
    "华盛顿",
    "北京",
    "法兰克福",
    "伦敦",
    "东京",
    "上海",
    "纽约",
    "布鲁塞尔",
    "日内瓦",
    "华盛顿特区",
    "Washington",
    "Beijing",
    "Frankfurt",
    "London",
    "Tokyo",
    "Shanghai",
    "New York",
    "Brussels",
    "Geneva",
)

_DATE_RE = re.compile(
    r"\d{4}[-/年]\d{1,2}[-/月](?:\d{1,2}日?)?|\d{1,2}月\d{1,2}日"
    r"|[A-Z][a-z]+ \d{1,2}(?:, \d{4})?"
)

_OBJECT_WINDOW = 24  # 动作词后宾语/受事探测窗口（字符）


def _count_patterns(text: str, words: tuple[str, ...]) -> int:
    """线索词计数（ASCII 词边界，中文子串）；与 svo._word_pattern 同约定。"""
    low = text.lower()
    n = 0
    for w in words:
        w = w.lower().strip()
        if not w:
            continue
        if w.isascii():
            n += len(re.findall(rf"\b{re.escape(w)}\b", low))
        else:
            n += low.count(w)
    return n


def emotion_vector(text: str) -> EmotionVector:
    """双层情绪近似：expressed=情绪词密度；audience=风险触发词密度。

    密度 = 每百字符命中数，clip [0,1]；intensity=expressed 总密度 clip；
    confidence：词典法封顶 0.6（命中越多越接近），零命中 0.1。
    """
    n_chars = max(len(text), 1)
    per_hundred = 100.0 / n_chars
    expressed: dict[EmotionLabel, float] = {}
    total = 0
    for label, words in EMOTION_LEXICON.items():
        hits = _count_patterns(text, words)
        if hits:
            expressed[label] = min(1.0, round(hits * per_hundred, 4))
            total += hits
    risk_hits = _count_patterns(text, RISK_TRIGGERS)
    audience: dict[EmotionLabel, float] = {}
    if risk_hits:
        share = min(1.0, risk_hits * per_hundred)
        # 风险触发词的读者效应按既有表达分布分摊；无表达时默认 fear/concern 对半
        if expressed:
            w_sum = sum(expressed.values())
            for label, w in expressed.items():
                audience[label] = round(share * w / w_sum, 4)
        else:
            audience = {
                EmotionLabel.FEAR: round(share * 0.5, 4),
                EmotionLabel.CONCERN: round(share * 0.5, 4),
            }
    confidence = min(0.6, 0.1 + 0.1 * (total + risk_hits))
    return EmotionVector(
        expressed=expressed,
        audience=audience,
        intensity=min(1.0, round(total * per_hundred, 4)),
        confidence=round(confidence, 2),
        engine="lexicon",
    )


def _match_location(text: str) -> str | None:
    low = text.lower()
    for loc in LOCATION_LEXICON:
        if loc.lower() in low:
            return loc
    return None


def _role_for_sentence(text: str, registry: EntityRegistry) -> SemanticRole:
    """单句 SRL 启发式：subject/action/object/target/time/location。

    object：最后一个动作词 end 起的窗口内金融词表命中（截至命中词）；
    target：同窗口内实体别名命中（取离动作最近者）。
    """
    ents = registry.match_with_positions(text)
    subject = text[ents[0][1] : ents[0][2]] if ents else None
    acts = match_actions(text)
    action = acts[-1]["direction"] if acts else None
    obj: str | None = None
    target: str | None = None
    if acts:
        win_lo = acts[-1]["end"]
        win = text[win_lo : win_lo + _OBJECT_WINDOW]
        win_low = win.lower()
        for word in _FINANCIAL_OBJECTS:
            idx = win_low.find(word)
            if idx != -1:
                obj = word
                break
        # 窗口内实体命中（偏移需加回 win_lo）
        win_ents = registry.match_with_positions(win)
        if win_ents:
            nearest = min(win_ents, key=lambda t: t[1])
            target = win[nearest[1] : nearest[2]]
    tm = _DATE_RE.search(text)
    return SemanticRole(
        subject=subject,
        action=action,
        object=obj,
        target=target,
        time=tm.group(0) if tm else None,
        location=_match_location(text),
        causality=None,
        engine="lexicon",
    )


def annotate_document(
    item_key: str,
    text: str,
    registry: EntityRegistry,
    *,
    annotated_at: datetime,
) -> SemanticAnnotation:
    """文档级词典标注（S1 主入口）：角色 + 动作 + 双层情绪；确定性幂等。

    annotated_at 由调用方注入（PIT 审计锚，通常为 bronze fetched_at 或运行时钟）；
    frame_dist 在词典层不重复计算（spectra/NDI 管线已有框架分布），恒空 dict
    由调用方按需填充；claims 留给 S4 LLM 层。
    """
    sentences = [s for s in split_sentences(text) if s.strip()]
    roles = [_role_for_sentence(s, registry) for s in sentences]
    actions = [
        ActionMention(
            verb=a["text"],
            domain=a["domain"],
            direction=a["direction"],
            strength=0.5,
            certainty=min(1.0, len(a["text"]) / 12.0),
            start=a["start"],
            end=a["end"],
        )
        for a in match_actions(text)
    ]
    return SemanticAnnotation(
        item_key=item_key,
        roles=roles,
        actions=actions,
        emotions=emotion_vector(text),
        claims=[],
        frame_dist={},
        event_candidates=[],
        embedding=None,
        annotated_at=annotated_at,
    )
