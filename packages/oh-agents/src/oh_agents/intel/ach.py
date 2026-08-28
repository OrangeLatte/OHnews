"""Red Team（红队）：CIA ACH 竞争假设分析。

Heuer ACH 核心纪律：不给假设"打分选最高"，而是找"最经得起反证"的
假设——矛盾证据（-1）计数最少者胜。矩阵诊断量见 oh_contracts.intel。

双路径：
- LLM（strategic tier）：生成竞争假设并对每条证据评分（schema 强制）。
- 离线降级：从统计量（NDI 水平/官方簇参与/Scout 异常）机械生成标准
  三假设矩阵——无 keys 时情报循环完整可用。
"""

from __future__ import annotations

from typing import Any

from oh_contracts.enums import Tier
from oh_contracts.intel import AchCell, AchMatrix, AchRow
from oh_contracts.schemas import NDIPoint
from pydantic import BaseModel, Field

__all__ = ["RedTeamAgent", "AchDraft", "EvidenceBundle"]


class AchDraft(BaseModel):
    """LLM 中间产物：原始矩阵（conclusion 由本地 ranked() 裁决，不信 LLM）。"""

    evidence: list[str] = Field(min_length=2, max_length=8)
    hypotheses: list[str] = Field(min_length=2, max_length=5)
    scores: list[list[int]] = Field(min_length=2)
    notes: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class EvidenceBundle(BaseModel):
    """喂给红队/首席的确定性证据包（全部可溯源到库内统计）。"""

    scope: str
    ndi_latest: float | None = None
    ndi_absent_ratio: float | None = None
    official_share: float | None = None
    social_share: float | None = None
    scout_anomalies: list[str] = Field(default_factory=list)
    top_hubs: list[str] = Field(default_factory=list)

    def evidence_lines(self) -> list[str]:
        """证据清单（ACH 矩阵的列）。"""
        out: list[str] = []
        if self.ndi_latest is not None:
            out.append(f"叙事分歧指数 NDI={self.ndi_latest:.3f}（描述性）")
        if self.ndi_absent_ratio is not None:
            out.append(f"事件 NDI 弃权率={self.ndi_absent_ratio:.0%}")
        if self.official_share is not None:
            out.append(f"官方簇(L1) stance 占比={self.official_share:.0%}")
        if self.social_share is not None:
            out.append(f"社媒(L4) stance 占比={self.social_share:.0%}")
        out.extend(self.scout_anomalies)
        if self.top_hubs:
            out.append(f"网络枢纽实体：{', '.join(self.top_hubs[:5])}")
        return out


def _bundle_from_stats(
    ndi_points: list[NDIPoint],
    official_rows: int,
    total_rows: int,
    bundle: EvidenceBundle,
) -> None:
    if total_rows:
        bundle.official_share = official_rows / total_rows
        bundle.social_share = 0.0  # 由调用方覆盖（无 L4 分类时保持 0）
    if ndi_points:
        ok = [p for p in ndi_points if p.ndi is not None]
        bundle.ndi_absent_ratio = 1 - len(ok) / len(ndi_points) if ndi_points else None
        if ok:
            bundle.ndi_latest = ok[-1].ndi


class RedTeamAgent:
    """ACH 竞争假设生成 + 一致性矩阵裁决。"""

    SYSTEM = (
        "你是情报分析红队，执行 CIA ACH（Analysis of Competing Hypotheses）纪律。"
        "生成 2-4 个相互竞争的假设（至少一个应与直觉相反），对每条证据"
        "给一致性分：+1 支持、0 中性、-1 矛盾。要求：至少一个假设必须"
        "在某条证据上得 -1（若全部假设都完美解释所有证据，说明假设不"
        "够具体）。notes 逐假设给出关键判据。"
    )

    def __init__(self, router: Any | None = None) -> None:
        self._router = router

    async def run(self, bundle: EvidenceBundle) -> AchMatrix:
        evidence = bundle.evidence_lines()
        if len(evidence) < 2:
            evidence = evidence + ["证据不足：仅基础统计可用"]
        if self._router is None:
            return self._offline(bundle, evidence)
        try:
            draft, _ref = await self._router.invoke(
                Tier.STRATEGIC,
                self.SYSTEM,
                f"巡逻范围：{bundle.scope}\n证据清单：\n" + "\n".join(f"- {e}" for e in evidence),
                AchDraft,
            )
            return self._to_matrix(draft, evidence)
        except Exception:  # noqa: BLE001 —— LLM 失败降级机械 ACH
            return self._offline(bundle, evidence)

    def _to_matrix(self, draft: AchDraft, evidence: list[str]) -> AchMatrix:
        n = len(evidence)
        rows = [
            AchRow(
                hypothesis=h,
                cells=[
                    AchCell(evidence=evidence[i], score=int(draft.scores[j][i]))
                    for i in range(min(n, len(draft.scores[j])))
                ]
                or [AchCell(evidence=evidence[0], score=0)],
                note=(draft.notes[j] if j < len(draft.notes) else None),
            )
            for j, h in enumerate(draft.hypotheses)
        ]
        conclusion = min(
            range(len(rows)),
            key=lambda i: (-rows[i].weighted_score, rows[i].inconsistency),
        )
        return AchMatrix(evidence=evidence, hypotheses=rows, conclusion_index=conclusion)

    def _offline(self, bundle: EvidenceBundle, evidence: list[str]) -> AchMatrix:
        """机械 ACH：标准三假设 × 统计证据（确定性评分规则）。"""
        ndi_hi = (bundle.ndi_latest or 0) >= 0.5
        absen_hi = (bundle.ndi_absent_ratio or 0) >= 0.5
        official_lo = (bundle.official_share or 0) < 0.2
        anomaly = bool(bundle.scout_anomalies)

        # 每条证据对 [H1 叙事透支, H2 基本面反转, H3 采样噪声] 的一致性
        per_evidence: list[list[int]] = []
        for idx, _e in enumerate(evidence):
            if idx == 0:  # NDI 水平
                per_evidence.append([1 if ndi_hi else 0, -1 if ndi_hi else 0, 0])
            elif idx == 1:  # 弃权率
                per_evidence.append([0, 0, 1 if absen_hi else 0])
            elif idx == 2:  # 官方簇占比
                per_evidence.append([0, 0 if official_lo else 1, 1 if official_lo else 0])
            else:  # Scout 异常 / 枢纽
                per_evidence.append([1 if anomaly else 0, 0, -1 if anomaly else 0])
        # ACH 纪律：不允许所有假设完美解释全部证据
        if all(all(s >= 0 for s in col) for col in per_evidence):
            per_evidence[0][0] = 1
            per_evidence[0][1] = -1
        notes = [
            "叙事透支：分歧扩大但价格未跟随，警惕情绪耗尽",
            "基本面反转：真实信息驱动重定价",
            "采样噪声：官方簇稀疏导致指数波动",
        ]
        rows = [
            AchRow(
                hypothesis=f"H{i + 1} {name}",
                cells=[
                    AchCell(evidence=e, score=per_evidence[j][i]) for j, e in enumerate(evidence)
                ],
                note=notes[i],
            )
            for i, name in enumerate(["叙事透支", "基本面反转", "采样噪声"])
        ]
        conclusion = min(
            range(len(rows)),
            key=lambda i: (-rows[i].weighted_score, rows[i].inconsistency),
        )
        return AchMatrix(evidence=evidence, hypotheses=rows, conclusion_index=conclusion)
