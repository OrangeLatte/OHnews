"""标注委员会：JSD 分歧门 / 裁决员合成 / α 计算 / FrameDist 契约。"""

from __future__ import annotations

import asyncio

import pytest
from oh_contracts.enums import FrameLabel, Tier
from oh_llm.committee import (
    AnnotationCommittee,
    FrameDist,
    jsd_dist,
    krippendorff_alpha_nominal,
    normalize_dist,
)
from oh_llm.config import ModelRef
from pydantic import ValidationError


class FakeRouter:
    """按 tier 预置输出队列的假路由（鸭子类型满足委员会）。"""

    def __init__(self, outputs: dict[Tier, list]):
        self.calls: list[Tier] = []
        self._outputs = {t: list(v) for t, v in outputs.items()}

    async def invoke(self, tier, system, user, schema):
        self.calls.append(tier)
        item = self._outputs[tier].pop(0)
        if isinstance(item, Exception):
            raise item
        return item, ModelRef("fake", f"model-{tier.value}")


def _dist(main: FrameLabel, main_w: float) -> FrameDist:
    rest = (1.0 - main_w) / (len(FrameLabel) - 1)
    return FrameDist.from_any({f.value: (main_w if f == main else rest) for f in FrameLabel})


def test_agreement_path_no_judge() -> None:
    async def case():
        router = FakeRouter(
            {
                Tier.IO: [_dist(FrameLabel.LOSS, 0.7)],
                Tier.EXECUTE: [_dist(FrameLabel.LOSS, 0.65)],
            }
        )
        committee = AnnotationCommittee(router)
        res = await committee.annotate_frame("t1", "美联储警告衰退风险上升")
        assert res.agreed is True
        assert res.verdict is None
        assert router.calls == [Tier.IO, Tier.EXECUTE]
        # final = 两者平均且归一：loss = (0.7 + 0.65) / 2 = 0.675
        assert sum(res.final.values()) == pytest.approx(1.0)
        assert res.final[FrameLabel.LOSS] == pytest.approx(0.675)

    asyncio.run(case())


def test_disagreement_path_invokes_judge() -> None:
    async def case():
        verdict = _dist(FrameLabel.CONFLICT, 0.6)
        router = FakeRouter(
            {
                Tier.IO: [_dist(FrameLabel.LOSS, 0.85)],
                Tier.EXECUTE: [_dist(FrameLabel.GAIN, 0.85)],
                Tier.STRATEGIC: [verdict],
            }
        )
        committee = AnnotationCommittee(router)
        res = await committee.annotate_frame("t2", "美联储声明政策立场")
        assert res.agreed is False
        assert res.verdict is not None
        assert res.final[FrameLabel.CONFLICT] == pytest.approx(0.6)
        assert router.calls == [Tier.IO, Tier.EXECUTE, Tier.STRATEGIC]
        assert res.judge == "fake/model-strategic"

    asyncio.run(case())


def test_annotator_failure_raises() -> None:
    async def case():
        router = FakeRouter(
            {Tier.IO: [RuntimeError("boom")], Tier.EXECUTE: [_dist(FrameLabel.LOSS, 0.7)]}
        )
        committee = AnnotationCommittee(router)
        with pytest.raises(RuntimeError, match="boom"):
            await committee.annotate_frame("t3", "text")

    asyncio.run(case())


def test_jsd_identical_and_orthogonal() -> None:
    a = _dist(FrameLabel.LOSS, 0.9).to_dict()
    assert jsd_dist(a, a) == pytest.approx(0.0)
    b = _dist(FrameLabel.GAIN, 0.9).to_dict()
    assert 0.0 < jsd_dist(a, b) <= 1.0


def test_normalize_dist() -> None:
    out = normalize_dist({FrameLabel.LOSS: 3, FrameLabel.GAIN: 1})
    assert sum(out.values()) == pytest.approx(1.0)
    assert out[FrameLabel.LOSS] == pytest.approx(0.75)


def test_frame_dist_rejects_non_normalized() -> None:
    six_keys = [
        "loss",
        "gain",
        "responsibility",
        "conflict",
        "human_interest",
        "other",
    ]
    with pytest.raises(ValidationError):
        FrameDist(**dict.fromkeys(six_keys, 0.1))


def test_frame_dist_from_any_normalizes() -> None:
    d = FrameDist.from_any({"loss": 2, "gain": 0})
    assert d.loss == pytest.approx(1.0)


def test_alpha_identical_is_one() -> None:
    assert krippendorff_alpha_nominal(["a", "b", "a"], ["a", "b", "a"]) == pytest.approx(1.0)


def test_alpha_hand_case() -> None:
    # a=[x,x,y] b=[x,y,y]: do=1/3, de=0.5 → α = 1 − (1/3)/0.5 = +1/3
    assert krippendorff_alpha_nominal(["x", "x", "y"], ["x", "y", "y"]) == pytest.approx(1 / 3)


def test_alpha_two_disagreements_negative() -> None:
    # a=[x,y,y] b=[y,x,y]: do=2/3, de=1−[(2/6)²+(4/6)²]=4/9 → α = 1 − (2/3)/(4/9) = −1/2
    assert krippendorff_alpha_nominal(["x", "y", "y"], ["y", "x", "y"]) == pytest.approx(-0.5)


def test_alpha_length_mismatch() -> None:
    with pytest.raises(ValueError):
        krippendorff_alpha_nominal(["a"], ["a", "b"])
