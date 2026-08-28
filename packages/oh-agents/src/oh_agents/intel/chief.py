"""Chief Analyst（首席分析师）：ICD 203 情报简报合成。

纪律：Key Judgments 必须挂概率语言（ICD 203 七档，schema 强制），
禁裸数字置信与"高/低"式模糊表述（超越 TradingAgents 的 confidence: high/low）。

双路径：LLM（strategic tier）合成；离线降级=ACH 结论+分位驱动模板。
"""

from __future__ import annotations

from typing import Any

from oh_contracts.enums import Tier
from oh_contracts.intel import AchMatrix, KeyJudgment
from pydantic import BaseModel, Field

from oh_agents.intel.ach import EvidenceBundle

__all__ = ["ChiefAnalystAgent", "KJDraft"]


class _KJ(BaseModel):
    judgment: str = Field(min_length=2)
    probability: float = Field(ge=0.0, le=1.0)
    drivers: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class KJDraft(BaseModel):
    """LLM 中间产物：2-4 条 Key Judgments + 一段总结。"""

    judgments: list[_KJ] = Field(min_length=2, max_length=4)
    summary: str = Field(min_length=2)

    model_config = {"extra": "forbid"}


class ChiefAnalystAgent:
    SYSTEM = (
        "你是情报机构首席分析师，按 ICD 203 标准输出 Key Judgments。"
        "每条判断必须：可证伪（指向可观察量）、挂概率（0-1，将自动映射为"
        "ICD 203 概率语言）、列 1-3 个驱动因子。判断措辞禁用『预测/择时/买入』"
        "——本产品为描述性情报，非投资建议。"
    )

    def __init__(self, router: Any | None = None) -> None:
        self._router = router

    async def run(
        self,
        bundle: EvidenceBundle,
        ach: AchMatrix,
        ndi_percentile: float | None = None,
    ) -> tuple[list[KeyJudgment], str]:
        if self._router is None:
            return self._offline(bundle, ach, ndi_percentile)
        try:
            draft, _ref = await self._router.invoke(
                Tier.STRATEGIC,
                self.SYSTEM,
                (
                    f"巡逻范围：{bundle.scope}\n"
                    f"证据包：{bundle.evidence_lines()}\n"
                    f"ACH 结论假设：{ach.hypotheses[ach.conclusion_index].hypothesis}\n"
                    f"NDI 历史分位：{ndi_percentile if ndi_percentile is not None else 'NA'}\n"
                    "输出 2-4 条 Key Judgments 与总结。"
                ),
                KJDraft,
            )
            kjs = [
                KeyJudgment(judgment=k.judgment, probability=k.probability, drivers=k.drivers)
                for k in draft.judgments
            ]
            return kjs, draft.summary
        except Exception:  # noqa: BLE001 —— LLM 失败降级模板
            return self._offline(bundle, ach, ndi_percentile)

    def _offline(
        self,
        bundle: EvidenceBundle,
        ach: AchMatrix,
        ndi_percentile: float | None,
    ) -> tuple[list[KeyJudgment], str]:
        concl = ach.hypotheses[ach.conclusion_index]
        p_main = {0: 0.62, 1: 0.55, 2: 0.70}.get(ach.conclusion_index, 0.55)
        kjs = [
            KeyJudgment(
                judgment=f"『{concl.hypothesis}』是当前对观测证据最具解释力的假设",
                probability=p_main,
                drivers=[c.evidence for c in concl.cells if c.score == 1][:3] or ["基础统计"],
            ),
            KeyJudgment(
                judgment="叙事分歧指数 NDI 维持描述性监测口径，不构成收益预测",
                probability=0.97,
                drivers=["ICD 203 措辞纪律", "测量效度门禁未过"],
            ),
        ]
        if bundle.ndi_latest is not None and ndi_percentile is not None:
            kjs.insert(
                0,
                KeyJudgment(
                    judgment=f"叙事分歧处于近窗分位 {ndi_percentile:.0%}"
                    + ("（偏高位）" if ndi_percentile >= 0.8 else "（中性区）"),
                    probability=0.75 if ndi_percentile >= 0.8 else 0.55,
                    drivers=[f"NDI={bundle.ndi_latest:.3f}"],
                ),
            )
        summary = (
            f"本轮巡逻范围：{bundle.scope}。红队裁决：{concl.hypothesis}"
            f"（矛盾证据 {concl.inconsistency} 条）。"
            + (f"NDI 最新 {bundle.ndi_latest:.3f}。" if bundle.ndi_latest is not None else "")
            + "全部判断为描述性情报（ICD 203），非投资建议。"
        )
        return kjs, summary
