"""文章拆解契约（M5-A3）：18 元素结构化拆解，LLM 产出、颜色标注渲染。

拆解是 02 页核心：每篇文章 → 结构化元素（主体/客体/事实/数据/动作/因果/
时间线/视角/立场/倾向/情绪/修辞/信源属性/论证/动机/背景），原文 span 定位
供前端颜色标注。item_key 即 hash 主键（复用 bronze make_item_key）。
"""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from oh_contracts.strict import _StrictBase

DissectionEngine = Literal["llm", "lexicon", "offline"]

ELEMENT_KEYS = (
    "actor",  # 主体 Actor/Subject
    "target",  # 客体 Object/Target
    "stakeholder",  # 利益相关方 Stakeholders
    "hard_fact",  # 核心事实 Hard Facts
    "quant_data",  # 硬核数据 Quantitative Data
    "data_scope",  # 数据定义域 Data Scope
    "action",  # 核心动作 Action/Verb
    "causal_link",  # 因果链条 Causal Link
    "timeline",  # 时间线 Timeline/Stage
    "perspective",  # 叙事视角 Perspective/Framing
    "explicit_stance",  # 显性立场 Explicit Stance
    "implicit_bias",  # 隐性倾向 Implicit Bias
    "tone",  # 情绪基调 Tone/Sentiment
    "diction",  # 修辞与用词 Diction
    "source_reliability",  # 信源属性 Source Reliability
    "argument_structure",  # 论证逻辑 Argument Structure
    "intent",  # 发布动机 Intent
    "context",  # 时代/行业背景 Context
)  # 18 元素闭集（顺序即展示序）

ElementKey = Literal[
    "actor",
    "target",
    "stakeholder",
    "hard_fact",
    "quant_data",
    "data_scope",
    "action",
    "causal_link",
    "timeline",
    "perspective",
    "explicit_stance",
    "implicit_bias",
    "tone",
    "diction",
    "source_reliability",
    "argument_structure",
    "intent",
    "context",
]


class DissectionSpan(_StrictBase):
    """原文定位片段（前端颜色标注用）。start/end 为字符偏移，end>start。

    quote 为模型自报的该偏移切片逐字原文（可选）：持久层用它做
    「坐标切片 vs 自报引文」子串双重校验，无子串关系即丢弃该 span
    （P0-2 锚点纪律：不得把漂移坐标伪装成原文高亮）。
    """

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = ""

    @model_validator(mode="after")
    def _end_after_start(self) -> "DissectionSpan":
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class DissectionElement(_StrictBase):
    """单个拆解元素：闭集 key + 内容 + 可选原文定位。

    confidence 为模型自报置信度（校准规则由拆解 prompt 约束：1.0 仅限
    原文逐字可引的显式事实；0.6-0.85 推断类；≤0.5 证据不足）；
    None 表示模型未自报（offline 词典兜底等），由持久层按 engine 定值。
    """

    element: ElementKey
    content: str = Field(min_length=1)
    spans: list[DissectionSpan] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class ArticleDissection(_StrictBase):
    """一篇文章的拆解结果（item_key 即主键，重跑幂等覆盖）。

    elements 可为部分元素（LLM 按需产出）；渲染时未出现的元素显示
    「未提取」而非空壳。language 为文章源语言（拆解解释语言由 UI 层决定）。
    """

    item_key: str = Field(min_length=1)
    title: str = ""
    elements: list[DissectionElement] = Field(default_factory=list)
    engine: DissectionEngine = "llm"
    language: str = ""
    model_hint: str = ""  # 产出模型标识（如 zhipu/glm-5.3），诚实溯源
    dissected_at: datetime
