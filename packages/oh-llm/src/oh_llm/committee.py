"""标注委员会（裁决 B 的 LLM 化实现：双标注员 + 裁决员）。

方法论诚实声明（必须随结果披露）：
- 基准性质 = 模型共识，不是人工标注 ground truth；
- 标注员互相隔离（各自独立调用，只看原文，不看彼此输出与 LLM 解释）；
- 标注员分属两个模型家族（DeepSeek vs GLM），裁决员与标注员 B 同家族但有代差；
- 测量效度 ρ≥0.8 门禁照常执行，但对外措辞为"模型共识基准"。
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from oh_contracts.enums import FrameLabel, Tier
from pydantic import BaseModel, Field, model_validator

_FRAMES: tuple[FrameLabel, ...] = tuple(FrameLabel)

CODEBOOK_PROMPT = """\
你是金融文本框架标注员。对给定句子输出五个叙事框架+other 的概率分布（总和必须为 1）。

框架判据（Entman 四功能操作化，句级多标签归一）：
- loss（损失框架）：强调负面后果——衰退/风险/危机/损失/裁员/恶化
- gain（收益框架）：强调正面结果——增长/复苏/改善/机遇/提振/盈利
- responsibility（责任框架）：归因与问责——归咎/责任/应对不力/政策失误
- conflict（冲突框架）：对抗与争端——制裁/关税/分歧/对抗/报复/威胁
- human_interest（人情味框架）：个体影响——家庭/民众/工人/小企业/储户
- other：以上皆弱（程序性/中性陈述）

规则：
1. 依据句子文本本身，禁止使用外部知识补全；
2. 多框架并存时按语义强度分配概率，主导框架必须显著；
3. 全部概率为 0~1，六项总和 = 1；
4. 争议大于 0.3 的判断倾向 other。"""

JUDGE_PROMPT = """你是框架标注仲裁员。两名独立标注员对同一句子给出了不同框架分布。
请重新独立判断并输出最终分布（六项总和 = 1）。不要简单平均两个答案；
仅当双方各自有理时才可折中。判据与规则同标注员。"""


class FrameDist(BaseModel):
    """五框架+other 概率分布（Σ=1 容差校验，不过即候选失败触发 fallback）。"""

    loss: float = Field(ge=0.0, le=1.0)
    gain: float = Field(ge=0.0, le=1.0)
    responsibility: float = Field(ge=0.0, le=1.0)
    conflict: float = Field(ge=0.0, le=1.0)
    human_interest: float = Field(ge=0.0, le=1.0)
    other: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _sums_to_one(self) -> FrameDist:
        total = sum(self.model_dump().values())
        if not 0.95 <= total <= 1.05:
            raise ValueError(f"概率分布总和须为 1，得到 {total:.3f}")
        return self

    def to_dict(self) -> dict[FrameLabel, float]:
        return {FrameLabel(k): v for k, v in self.model_dump().items()}

    @classmethod
    def from_any(cls, d: Mapping[str, float]) -> FrameDist:
        """宽容构造：缺项补 0，Σ≠1 归一化。"""
        merged = {f.value: float(d.get(f.value, 0.0)) for f in _FRAMES}
        total = sum(merged.values())
        if total <= 0:
            raise ValueError("概率分布全为 0")
        return cls(**{k: v / total for k, v in merged.items()})


def normalize_dist(d: Mapping[FrameLabel, float]) -> dict[FrameLabel, float]:
    total = sum(d.values())
    if total <= 0:
        raise ValueError("概率分布全为 0")
    return {f: d.get(f, 0.0) / total for f in _FRAMES}


def jsd_dist(p: Mapping[FrameLabel, float], q: Mapping[FrameLabel, float]) -> float:
    """分布间 JS 散度距离（base 2，sqrt 化）。"""

    def _h(r: Mapping[FrameLabel, float]) -> float:
        return -sum(v * math.log2(v) for v in r.values() if v > 0)

    m = {f: (p.get(f, 0.0) + q.get(f, 0.0)) / 2 for f in _FRAMES}
    return math.sqrt(max(0.0, min(1.0, _h(m) - (_h(p) + _h(q)) / 2)))


@dataclass(frozen=True)
class AnnotationResult:
    """单条标注的完整审计记录。"""

    item_id: str
    label_a: dict[FrameLabel, float]
    label_b: dict[FrameLabel, float]
    verdict: dict[FrameLabel, float] | None
    final: dict[FrameLabel, float]
    agreed: bool
    annotators: tuple[str, str]
    judge: str | None


class AnnotationCommittee:
    """双标注员独立标注 → JSD 分歧门 → 超门裁决员合成。"""

    def __init__(
        self,
        router,
        *,
        annotator_tiers: tuple[Tier, Tier] = (Tier.IO, Tier.EXECUTE),
        judge_tier: Tier = Tier.STRATEGIC,
        agreement_jsd: float = 0.4,
    ) -> None:
        self._router = router
        self._annotator_tiers = annotator_tiers
        self._judge_tier = judge_tier
        self._agreement = agreement_jsd

    async def annotate_frame(self, item_id: str, text: str) -> AnnotationResult:
        user = f"待标注句子：\n{text}"
        a, ref_a = await self._router.invoke(
            self._annotator_tiers[0], CODEBOOK_PROMPT, user, FrameDist
        )
        b, ref_b = await self._router.invoke(
            self._annotator_tiers[1], CODEBOOK_PROMPT, user, FrameDist
        )
        da, db = a.to_dict(), b.to_dict()
        gap = jsd_dist(da, db)
        if gap <= self._agreement:
            return AnnotationResult(
                item_id=item_id,
                label_a=da,
                label_b=db,
                verdict=None,
                final=normalize_dist({f: (da[f] + db[f]) / 2 for f in _FRAMES}),
                agreed=True,
                annotators=(
                    f"{ref_a.provider}/{ref_a.model_id}",
                    f"{ref_b.provider}/{ref_b.model_id}",
                ),
                judge=None,
            )
        judge_input = (
            f"待标注句子：\n{text}\n\n"
            f"标注员 A 分布：{_fmt(da)}\n标注员 B 分布：{_fmt(db)}\n"
            f"两者 JS 散度距离 = {gap:.3f}，存在实质分歧。"
        )
        verdict, ref_j = await self._router.invoke(
            self._judge_tier, JUDGE_PROMPT, judge_input, FrameDist
        )
        return AnnotationResult(
            item_id=item_id,
            label_a=da,
            label_b=db,
            verdict=verdict.to_dict(),
            final=verdict.to_dict(),
            agreed=False,
            annotators=(f"{ref_a.provider}/{ref_a.model_id}", f"{ref_b.provider}/{ref_b.model_id}"),
            judge=f"{ref_j.provider}/{ref_j.model_id}",
        )


def _fmt(d: Mapping[FrameLabel, float]) -> str:
    return ", ".join(f"{f.value}={d.get(f, 0.0):.2f}" for f in _FRAMES)


def krippendorff_alpha_nominal(labels_a: Sequence[str], labels_b: Sequence[str]) -> float:
    """两标注者 nominal Krippendorff's α（无缺失值简化）。

    α = 1 − D_o / D_e；
    D_o = 标签不一致的单元比例；
    D_e = 1 − Σ_k π_k²（π_k 为两标注者合并标签频率）。
    完全一致 → 1.0；统计独立 → ≈0；系统性反向 → 可为负。
    """
    if len(labels_a) != len(labels_b) or not labels_a:
        raise ValueError("两标注序列长度须一致且非空")
    n = len(labels_a)
    disagreements = sum(1 for a, b in zip(labels_a, labels_b, strict=True) if a != b)
    do = disagreements / n
    counts: Counter[str] = Counter(labels_a) + Counter(labels_b)
    total = 2 * n
    de = 1 - sum((c / total) ** 2 for c in counts.values())
    if de == 0:
        return 1.0
    return 1 - do / de
