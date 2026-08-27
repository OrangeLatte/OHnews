"""AnalysisState（蓝图图2 AST 子图）：Annotated 第二参数一律为真 reducer。

事件/立场/NDI/假设均为追加语义（并行 Send 节点各自产出）；
pending_interrupt 为 LastValue 覆盖（HITL 单值槽位）。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from oh_contracts.schemas import Hypothesis, NDIPoint


class CalibrationEntry(TypedDict):
    """校准层输出（历史分位对比；无历史时 cold_start 标注）。"""

    event_id: str
    ndi: float
    percentile: float | None
    regime: str  # cold_start | normal | extreme


class AnalysisState(TypedDict, total=False):
    event_ids: Annotated[list[str], operator.add]
    ndi_points: Annotated[list[NDIPoint], operator.add]
    calibrations: Annotated[list[CalibrationEntry], operator.add]
    hypotheses: Annotated[list[Hypothesis], operator.add]
    narrative_cards: Annotated[list[dict[str, Any]], operator.add]
    messages: Annotated[list[AnyMessage], add_messages]
    pending_interrupt: Annotated[list[dict[str, Any]], operator.add]  # 并行分支追加挂起项
    # --- 主图输入键（无 reducer，LastValue 覆盖）---
    events_input: list[dict[str, Any]]
    now: str
