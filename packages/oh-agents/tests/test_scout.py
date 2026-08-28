"""Scout 侦查员测试：z-score 突刺 / 新实体涌现 / CUSUM 节奏漂移。"""

from __future__ import annotations

from oh_agents.intel.scout import (
    detect_cadence_shift,
    detect_new_entities,
    detect_volume_spike,
    volume_zscores,
)


def test_volume_zscores_baseline_none_and_spike() -> None:
    counts = [5, 4, 6, 5, 3, 7, 5, 4, 6, 5, 50]
    zs = volume_zscores(counts, window=14, min_history=7)
    assert zs[:7] == [None] * 7
    assert zs[-1] is not None and zs[-1] > 3.0
    # 零方差历史 → None（弃权语义）
    assert volume_zscores([3] * 8, window=14, min_history=7)[-1] is None


def test_detect_volume_spike_triggers_and_gates() -> None:
    calm = [5, 4, 6, 5, 3, 7, 5, 4, 6, 5]
    assert detect_volume_spike("src_a", calm) is None
    spiked = calm + [60]
    f = detect_volume_spike("src_a", spiked)
    assert f is not None
    assert f.kind == "volume_spike"
    assert f.target == "src_a"
    assert f.score > 3.0
    # 历史不足门（min_history）→ None
    assert detect_volume_spike("src_a", [1, 2, 3]) is None


def test_detect_new_entities_order_and_threshold() -> None:
    known = {"fed": 100.0, "boe": 50.0}
    fresh = {"fed": 120.0, "petcom": 8.0, "minorco": 1.0, "novex": 3.0}
    out = detect_new_entities(known, fresh, min_volume=3)
    targets = [f.target for f in out]
    # petcom(8) 在 novex(3) 前；minorco 低于阈值被弃权
    assert targets == ["petcom", "novex"]
    assert all(f.kind == "new_entity" for f in out)


def test_detect_cadence_shift_gates_and_triggers() -> None:
    # 稳定节奏（每 6h 一篇）→ 无发现
    steady = [6.0] * 10
    assert detect_cadence_shift("src_b", steady) is None
    # 样本不足门
    assert detect_cadence_shift("src_b", [6.0] * 3) is None
    # 后半段节奏显著变慢（6h → 48h）→ 触发
    slowing = [6.0] * 5 + [48.0] * 6
    f = detect_cadence_shift("src_b", slowing)
    assert f is not None
    assert f.kind == "cadence_shift"
    assert f.score >= 5.0
