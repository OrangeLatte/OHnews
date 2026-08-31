"""认知快照契约（阶段 2 判断闭环）。

设计纪律（产品纲领）：
- 判断只能由用户主动确认产生，系统绝不代写（BeliefSnapshot 仅用户提交时写入）；
- 系统不自动提高统计置信度：confidence 是用户自评，与任何模型/指标解耦；
- 认知时间线回答「我的看法如何演变、与前一版本差异是什么」。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .strict import NonEmptyStr, _StrictBase

BeliefStance = Literal["maintain", "adjust", "reverse", "uncertain"]
BeliefChangeType = Literal["new", "revised"]

_STANCE_ZH: dict[str, str] = {
    "maintain": "维持原判",
    "adjust": "调整看法",
    "reverse": "反转看法",
    "uncertain": "存疑待查",
}


def stance_zh(stance: str) -> str:
    """stance 的人话映射（前端展示用，契约内单一真源）。"""
    return _STANCE_ZH.get(stance, stance)


class BeliefCreate(_StrictBase):
    """用户提交判断的请求体（snapshot_id/change_type/believed_at 由服务端生成）。"""

    change_id: NonEmptyStr
    subject_id: NonEmptyStr
    subject_label: str = ""
    stance: BeliefStance
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


class BeliefSnapshot(_StrictBase):
    """一次用户认知快照：对某变化的判断 + 自评信心 + 依据。

    believed_at 只在用户确认保存时由服务端锚定；
    change_type 由服务端对比该 change 的既有快照自动判定（首条=new）。
    """

    snapshot_id: NonEmptyStr
    change_id: NonEmptyStr
    subject_id: NonEmptyStr
    subject_label: NonEmptyStr = ""
    stance: BeliefStance
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""
    change_type: BeliefChangeType
    believed_at: datetime

    def diff_from(self, previous: BeliefSnapshot) -> str:
        """与前一版本的差异人话（系统计算，仅供展示）。"""
        parts: list[str] = []
        if previous.stance != self.stance:
            parts.append(f"立场由「{stance_zh(previous.stance)}」变为「{stance_zh(self.stance)}」")
        delta = self.confidence - previous.confidence
        if abs(delta) >= 0.05:
            word = "上升" if delta > 0 else "下降"
            parts.append(f"信心{word} {abs(delta):.0%}")
        if not parts:
            return "与前一版本一致"
        return "；".join(parts)


__all__ = ["BeliefChangeType", "BeliefCreate", "BeliefSnapshot", "BeliefStance", "stance_zh"]
