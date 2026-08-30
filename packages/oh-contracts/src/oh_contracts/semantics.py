"""语义层契约（M3-S1 词典层 + S4 LLM 增量层共用）。

设计来源：REFACTOR_V2.md §3.1。
- EmotionLabel/EmotionVector：双层情绪（文本表达 vs 预期读者效应），
  词典 v1（engine=lexicon，粗近似）与 LLM v2（engine=llm）共用。
- SemanticRole：SRL 论元（v1 启发式：实体命中主体 + 动词后 NP/金融词表宾语 +
  日期正则时间 + 地点别名表；causality 留给 LLM v2）。
- SemanticAnnotation：文档级标注容器（annotations 表 payload、Raw Explorer 数据面）。
- EntityEdge：KG v2 类型化边（S3 cartographer 消费）。

PIT 纪律：标注只允许使用文档自身内容与 t-1 及更早信息；engine 字段强制
标注来源，UI 需向用户传达 lexicon=确定性粗近似、llm=模型标注。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from .enums import FrameLabel
from .schemas import Claim, _Strict

__all__ = [
    "ActionMention",
    "EmotionLabel",
    "EmotionVector",
    "EntityEdge",
    "SemanticAnnotation",
    "SemanticRole",
    "SEMANTIC_ENGINES",
]


SEMANTIC_ENGINES = Literal["lexicon", "llm", "offline"]


class EmotionLabel(StrEnum):
    """8 类情绪（词典 v1 与 LLM v2 的公共标签空间）。"""

    FEAR = "fear"
    ANGER = "anger"
    OPTIMISM = "optimism"
    UNCERTAINTY = "uncertainty"
    CONFIDENCE = "confidence"
    URGENCY = "urgency"
    CONCERN = "concern"
    RELIEF = "relief"


class ActionMention(_Strict):
    """动作提及（词级定位 + 方向强度近似）。

    strength：方向强度 v1 词典恒 0.5（无强度分档）；certainty：确定性近似
    （明确动词 > 转述措辞，v1 以命中词长度近似）。
    """

    verb: str
    domain: str
    direction: str
    strength: float = Field(ge=0.0, le=1.0, default=0.5)
    certainty: float = Field(ge=0.0, le=1.0)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class EmotionVector(_Strict):
    """双层情绪向量：expressed=文本表达密度；audience=预期读者效应密度。

    各键值归一 [0,1]；v1 词典法为粗近似（承 NDI 地板效应教训），UI 必须展示
    engine 与 confidence。
    """

    expressed: dict[EmotionLabel, float]
    audience: dict[EmotionLabel, float]
    intensity: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    engine: SEMANTIC_ENGINES


class SemanticRole(_Strict):
    """单句 SRL 论元（v1 启发式，字段可空；causality 仅 LLM v2 产出）。"""

    subject: str | None = None
    action: str | None = None
    object: str | None = None
    target: str | None = None
    time: str | None = None
    location: str | None = None
    causality: str | None = None
    engine: SEMANTIC_ENGINES = "lexicon"


class SemanticAnnotation(_Strict):
    """文档级语义标注容器（annotations 表 payload）。

    embedding 可空（S4 bge-small ONNX 产出）；claims 复用 schemas.Claim，
    词典 v1 不产 claim（空列表），LLM v2 开始填充。
    """

    item_key: str
    roles: list[SemanticRole] = Field(default_factory=list)
    actions: list[ActionMention] = Field(default_factory=list)
    emotions: EmotionVector | None = None
    claims: list[Claim] = Field(default_factory=list)
    frame_dist: dict[FrameLabel, float] = Field(default_factory=dict)
    event_candidates: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None
    annotated_at: datetime


class EntityEdge(_Strict):
    """KG v2 类型化边（S3）：边可溯源到 item_key 证据链。"""

    src: str
    dst: str
    kind: Literal[
        "co_occurs",
        "acts_on",
        "opposes",
        "supports",
        "regulates",
        "responds_to",
        "mentions",
        "competes_with",
        "parent_of",
    ]
    weight: float = Field(gt=0.0)
    first_seen: datetime
    last_seen: datetime
    evidence_item_keys: list[str] = Field(default_factory=list)
