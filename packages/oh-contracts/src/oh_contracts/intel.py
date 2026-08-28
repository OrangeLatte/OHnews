"""情报循环契约（超越 TradingAgents 的六角色编排：schemas 层）。

- AchCell / AchRow：CIA Analysis of Competing Hypotheses 一致性矩阵单元
  （evidence × hypothesis：+1 一致 / 0 中性 / -1 矛盾 / None 不适用）。
- KeyJudgment：ICD 203 概率语言强制挂载的判断（禁裸数字置信）。
- IntelReport：一轮情报循环的完整产物（Scout/Cartographer/RedTeam/Chief）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from oh_contracts.schemas import _Strict

__all__ = ["AchCell", "AchRow", "AchMatrix", "KeyJudgment", "IntelReport"]


class AchCell(_Strict):
    """证据 × 假设一致性单元：+1 一致 / 0 中性 / -1 矛盾 / None 不适用。"""

    evidence: str = Field(min_length=1)
    score: int | None = Field(default=None, ge=-1, le=1)


class AchRow(_Strict):
    """一条竞争假设及其跨证据一致性列。"""

    hypothesis: str = Field(min_length=1)
    cells: list[AchCell] = Field(min_length=1)
    note: str | None = None

    @property
    def inconsistency(self) -> int:
        """ACH 诊断量：矛盾分数量（越低=越能解释全部证据）。"""
        return sum(1 for c in self.cells if c.score == -1)

    @property
    def weighted_score(self) -> float:
        """一致性得分（+1 计 1，-1 计 -2，N/A 不计）——诊断式而非评分式。"""
        return (
            float(sum(c.score if c.score is not None else 0 for c in self.cells))
            - self.inconsistency
        )


class AchMatrix(_Strict):
    """完整 ACH：假设行 × 证据列 + 结论（最具解释力假设的下标）。"""

    evidence: list[str] = Field(min_length=1)
    hypotheses: list[AchRow] = Field(min_length=1)
    conclusion_index: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_shape(self) -> AchMatrix:
        if self.conclusion_index >= len(self.hypotheses):
            raise ValueError("conclusion_index 越界")
        for h in self.hypotheses:
            if len(h.cells) != len(self.evidence):
                raise ValueError("假设 cells 数必须与 evidence 数一致")
        return self

    def ranked(self) -> list[tuple[int, float, int]]:
        """按 (一致性得分降序, 矛盾数升序) 排名的 (index, score, inconsistency)。"""
        ranked = sorted(
            ((i, h.weighted_score, h.inconsistency) for i, h in enumerate(self.hypotheses)),
            key=lambda t: (-t[1], t[2]),
        )
        return ranked


class KeyJudgment(_Strict):
    """ICD 203：判断 + 概率语言（probability∈[0,1] 自动归带，禁裸置信）。"""

    judgment: str = Field(min_length=1)
    probability: float = Field(ge=0.0, le=1.0)
    term: str = ""
    drivers: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _attach_term(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("term"):
            from oh_contracts.icd203 import term_for_probability

            data = {**data, "term": term_for_probability(float(data["probability"])).value}
        return data


class IntelReport(_Strict):
    """一轮情报循环完整产物。"""

    report_id: str
    created_at: str
    scope: str = Field(min_length=1, description="巡逻范围描述（全库/实体）")
    engine: Literal["llm", "offline"] = "offline"
    scout_findings: list[dict[str, Any]] = Field(default_factory=list)
    network: dict[str, Any] = Field(default_factory=dict)
    ach: AchMatrix | None = None
    key_judgments: list[KeyJudgment] = Field(default_factory=list)
    summary: str = ""
