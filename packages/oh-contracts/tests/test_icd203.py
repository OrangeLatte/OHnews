"""ICD 203 概率语言：区间映射与端点归并。"""

from __future__ import annotations

import pytest
from oh_contracts.icd203 import PROBABILITY_RANGES, ProbabilityTerm, term_for_probability


def test_term_boundaries() -> None:
    assert term_for_probability(1.0) is ProbabilityTerm.ALMOST_CERTAIN
    assert term_for_probability(0.95) is ProbabilityTerm.ALMOST_CERTAIN
    assert term_for_probability(0.9) is ProbabilityTerm.HIGHLY_LIKELY
    assert term_for_probability(0.55) is ProbabilityTerm.LIKELY
    assert term_for_probability(0.5) is ProbabilityTerm.ROUGHLY_EVEN
    assert term_for_probability(0.3) is ProbabilityTerm.UNLIKELY
    assert term_for_probability(0.1) is ProbabilityTerm.HIGHLY_UNLIKELY
    assert term_for_probability(0.05) is ProbabilityTerm.ALMOST_IMPOSSIBLE
    assert term_for_probability(0.0) is ProbabilityTerm.ALMOST_IMPOSSIBLE


def test_out_of_range_raises() -> None:
    with pytest.raises(ValueError):
        term_for_probability(1.5)
    with pytest.raises(ValueError):
        term_for_probability(-0.1)


def test_ranges_are_ordered_and_partitioned() -> None:
    items = sorted(PROBABILITY_RANGES.items(), key=lambda kv: kv[1][0])
    lo = 0.0
    for term, (a, b) in items:
        assert a <= b
        assert a == lo, f"{term} 区间不连续：{a} != {lo}"
        lo = b
    assert lo == 1.0
