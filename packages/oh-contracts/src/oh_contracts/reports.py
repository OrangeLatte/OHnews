"""B2 研究报告契约：基于拆解结果的 6+1 类结构化报告。

纪律：报告是可核验的——sections 引用拆解元素/原文，禁编造；engine 诚实标注
（llm=模型产物 / offline=模板降级，降级时必须留根因）。
"""

from typing import Literal

from pydantic import Field

from .strict import HeadlineStr, _StrictBase

ReportKind = Literal[
    "truth",  # 真实性与可信度核查
    "intent",  # 意图与动机判定
    "causal",  # 归因与因果推演
    "narrative",  # 叙事与框架分析
    "trend",  # 动态趋势与时序分析
    "summary",  # 综合结构化摘要
]

REPORT_ENGINES = Literal["llm", "offline"]


class ReportSection(_StrictBase):
    """报告分节：title 非空 + body 非空。"""

    title: HeadlineStr
    body: str = Field(min_length=1)


class AgentReport(_StrictBase):
    """单篇文章×单一视角的研究报告。report_id=rp-{sha1(item_key|kind)[:8]} 幂等。"""

    report_id: str = Field(min_length=3)
    item_key: str = Field(min_length=1)
    kind: ReportKind
    title: HeadlineStr
    sections: list[ReportSection] = Field(default_factory=list)
    engine: REPORT_ENGINES = "llm"
    model_hint: str = ""
    created_at: str = Field(min_length=1)
