"""情报循环契约测试（ACH 矩阵诊断语义 + ICD 203 强制挂带）。"""

from __future__ import annotations

import pytest
from oh_contracts import AchCell, AchMatrix, AchRow, KeyJudgment
from pydantic import ValidationError


def _row(h: str, scores: list[int | None]) -> AchRow:
    return AchRow(
        hypothesis=h,
        cells=[AchCell(evidence=f"E{i}", score=s) for i, s in enumerate(scores)],
    )


def test_ach_row_diagnostics() -> None:
    # +1+0-1：weighted = 1+0-1 -1(矛盾惩罚) = -1；inconsistency=1
    r = _row("H1", [1, 0, -1])
    assert r.inconsistency == 1
    assert r.weighted_score == -1.0
    # N/A 不计分
    r2 = _row("H2", [1, None, None])
    assert r2.weighted_score == 1.0


def test_ach_matrix_rank_and_conclusion() -> None:
    m = AchMatrix(
        evidence=["E0", "E1", "E2"],
        hypotheses=[
            _row("叙事透支", [1, 0, -1]),
            _row("基本面反转", [1, 1, 1]),
            _row("数据噪声", [0, 0, 1]),
        ],
        conclusion_index=1,
    )
    ranked = m.ranked()
    assert ranked[0][0] == 1  # 基本面反转：+3 最高
    assert ranked[1][0] == 2
    assert ranked[2][0] == 0


def test_ach_matrix_shape_enforced() -> None:
    with pytest.raises(ValidationError):
        AchMatrix(evidence=["E0"], hypotheses=[_row("H", [1, 1])], conclusion_index=0)
    with pytest.raises(ValidationError):
        AchMatrix(evidence=["E0"], hypotheses=[_row("H", [1])], conclusion_index=5)


def test_key_judgment_attaches_icd203_term() -> None:
    kj = KeyJudgment(judgment="叙事分歧继续走高", probability=0.85, drivers=["NDI P90"])
    assert kj.term == "highly_likely"
    kj2 = KeyJudgment(judgment="中性", probability=0.5)
    assert kj2.term == "roughly_even"
    with pytest.raises(ValidationError):
        KeyJudgment(judgment="x", probability=1.5)
