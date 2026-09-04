"""LLM 补盲抽取（分层路由的 LLM 层；官方源优先，成本受 max_items 硬约束）。

只对规则层弃权（无框架信号）的官方源文章调用 LLM——官方文本程式化
导致线索词命中率低，正是真实运行 NDI 全 abstain 的根因（m0348 全链首跑）。
市场源保持规则层（85/10/5 成本纪律）。
"""

from __future__ import annotations

from datetime import datetime

from oh_contracts.enums import ExtractionEngine, StanceLabel, Tier
from oh_contracts.schemas import StanceRow
from oh_llm.committee import CODEBOOK_PROMPT, FrameDist
from oh_llm.router import ModelRouter
from pydantic import BaseModel, Field


class LLMFrameOutput(BaseModel):
    """LLM 补盲输出：框架分布 + 实体立场 + 自评置信。"""

    frame_dist: FrameDist
    stance: StanceLabel
    confidence: float = Field(ge=0.0, le=1.0)


_STANCE_PROMPT = """\\
你是金融文本立场标注员。判断文本对指定实体的立场（supportive/neutral/critical），
并给出框架分布与置信度。立场判据：实体邻域内的正面/负面评价线索；
无明确立场线索时输出 neutral。置信度反映你对框架分布的把握（0-1）。
返回 JSON：frame_dist（六框架概率，总和为 1）、stance、confidence。
"""


class LLMTagger:
    """规则层弃权行补盲（engine=llm；io tier 默认）。"""

    def __init__(self, router: ModelRouter, *, tier: Tier = Tier.IO) -> None:
        self._router = router
        self._tier = tier

    async def fill(
        self,
        *,
        event_id: str,
        source_id: str,
        entity_id: str,
        text: str,
        item_key: str,
        ts: datetime,
    ) -> StanceRow | None:
        """单（文章,实体）对的 LLM 标注；模型失败由 router 内部 fallback 处理。"""
        user = f"实体：{entity_id}\n\n文本：{text[:2000]}"
        out, _ref, _usage = await self._router.invoke(
            self._tier, _STANCE_PROMPT + "\n\n" + CODEBOOK_PROMPT, user, LLMFrameOutput
        )
        dist = out.frame_dist.to_dict()
        top = max(dist, key=lambda k: dist[k])
        return StanceRow(
            event_id=event_id,
            source_id=source_id,
            entity_id=entity_id,
            frame=top,  # type: ignore[arg-type]  # FrameDist 键即 FrameLabel 值
            stance=out.stance,
            confidence=round(out.confidence, 4),
            engine=ExtractionEngine.LLM,
            item_key=item_key,
            ts=ts,
        )
