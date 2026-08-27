"""测量效度门禁（裁决 B：三效度分离的第一道硬门禁）。

目标变量 = 人工标注的跨源框架分歧 ground truth（不是价格）。
升格"雷达信号"的唯一条件：系统 NDI 与标注分歧的 Spearman ρ ≥ 0.8
（50 事件，LLM 预标 + 人工复核，标注者只看原始信源不看 LLM 解释）。
未通过前 NDI 只是描述性监测指数（措辞纪律写死 README）。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ValidityResult:
    """测量效度检验结果。"""

    rho: float
    n_events: int
    threshold: float
    passed: bool


def _rank(values: Sequence[float]) -> list[float]:
    """平均秩（ties 同秩）：排序位次的平均值。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        raise ValueError("样本数不足")
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx**0.5 * vy**0.5)


def spearman_rho(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Spearman 秩相关：rank 后 Pearson。"""
    if len(xs) != len(ys):
        raise ValueError("序列长度不一致")
    return _pearson(_rank(xs), _rank(ys))


def measurement_validity(
    ndi_values: Sequence[float],
    gold_values: Sequence[float],
    threshold: float = 0.8,
) -> ValidityResult:
    """测量效度硬门禁：ρ ≥ threshold 才通过。"""
    rho = spearman_rho(ndi_values, gold_values)
    return ValidityResult(
        rho=round(rho, 4),
        n_events=len(ndi_values),
        threshold=threshold,
        passed=rho >= threshold,
    )


def load_gold_ndi(path: str | Path) -> dict[str, float]:
    """加载人工标注 ground truth（jsonl：每行 {"event_id", "gold_divergence"}）。"""
    gold: dict[str, float] = {}
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            gold[rec["event_id"]] = float(rec["gold_divergence"])
    return gold
