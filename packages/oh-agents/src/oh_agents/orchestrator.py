"""Orchestrator：Intent → ContextPacket → Agent 调用（REDESIGN_AGENT v3）。

职责边界：
- build_context_packet：确定性快照组装（Agent 不碰 SQL，Orchestrator 不做推理）；
- intent_message：把 Intent + Packet 渲染为注入 chat 图的首条消息；
- run_intent：LLM 路径（run_chat 注入 packet）与离线路径（模板五层输出）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from oh_contracts.enums import SourceTier
from oh_contracts.intents import (
    AnalysisArtifact,
    ArtifactKind,
    ContextPacket,
    Intent,
    IntentKind,
    TargetKind,
)

_INVESTIGATE_HINTS: dict[IntentKind, str] = {
    IntentKind.EXPLAIN_SIGNAL: "解释这个信号：它衡量什么、为何此时出现、强度与置信度如何解读。",
    IntentKind.EXPLAIN_CAUSE: "分析这个对象可能的驱动因素，并区分确定性证据与推测。",
    IntentKind.COMPARE_NARRATIVES: "对比各信源簇（官方 vs 市场）的框架与立场差异，用证据链支撑。",
    IntentKind.SHOW_EVIDENCE: "列出支持该对象的关键证据（摘录+来源+PIT），并标注缺失佐证。",
    IntentKind.START_INVESTIGATION: "就该对象展开结构化调查：假设、反例、不确定性清单。",
    IntentKind.CHALLENGE: (
        "以红队视角挑战当前结论：列出与结论竞争的替代解释、证据弱点与"
        "可能推翻结论的条件（ACH 纪律：至少给出一个反向证据）。"
    ),
}


def _signal_fallback(
    bronze: Any,
    store: Any,
    registry: Any,
    tier_map: Any,
    now: datetime,
    target_id: str,
    min_per_source: int = 10,
) -> dict[str, Any] | None:
    """按 signal_id 前缀匹配 detect_signals 输出（sig-{kind}-{entity}-{date}）。"""
    from oh_pipeline.detect import detect_signals

    signals = detect_signals(
        bronze.iter_records(),
        store,
        registry,
        tier_map,
        now,
        min_per_source=min_per_source,
        top_n=50,
    )
    for s in signals:
        if s.signal_id == target_id:
            return s.model_dump(mode="json")
    return None


def build_context_packet(
    intent: Intent,
    *,
    bronze: Any,
    store: Any,
    gold: Any,
    registry: Any,
    tier_map: Any,
    now: datetime,
    min_per_source: int = 10,
    language: str | None = None,
) -> ContextPacket:
    """确定性组装 ContextPacket：Signal/Event/Entity → 关联 NDI + stance 快照。

    language=None 表示不过滤（ndi_series 语义）；跨事件多语言点位全部
    收集，展示层/Agent 按 ts 排序读取。
    """
    notes: list[str] = []
    signal: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    entity_id: str | None = None
    event_id: str | None = None
    entity_events: list[dict[str, Any]] = []

    if intent.target_kind is TargetKind.SIGNAL:
        signal = _signal_fallback(
            bronze, store, registry, tier_map, now, intent.target_id, min_per_source=min_per_source
        )
        if signal is None:
            notes.append(f"signal {intent.target_id} not found in current detection window")
        else:
            entity_id = signal.get("entity_id")
            ev_ids = list(signal.get("evidence_ids") or [])
            event_id = ev_ids[0] if ev_ids else None
            if event_id is None:
                notes.append("signal has no linked evidence event")
    elif intent.target_kind is TargetKind.EVENT:
        for ev in store.events_asof(now):
            rec = ev.model_dump(mode="json") if hasattr(ev, "model_dump") else dict(ev)
            if rec.get("event_id") == intent.target_id:
                event = rec
                break
        if event is None:
            notes.append(f"event {intent.target_id} not found as-of {now.isoformat()}")
        else:
            ent = list(event.get("entities") or [])
            entity_id = ent[0] if ent else None
            event_id = intent.target_id
    elif intent.target_kind is TargetKind.ENTITY:
        entity_id = intent.target_id
    else:
        notes.append("topic target resolves to free-text search at agent layer")

    ndi_points: list[dict[str, Any]] = []
    if entity_id:
        for ev in store.events_asof(now):
            rec = ev.model_dump(mode="json") if hasattr(ev, "model_dump") else dict(ev)
            if entity_id in list(rec.get("entities") or []):
                entity_events.append(rec)
        if entity_events:
            if event_id is None:
                event = dict(entity_events[0])
            else:
                for rec in entity_events:
                    if rec.get("event_id") == event_id:
                        event = rec
                        break
            # 取该实体关联事件的全部 NDI 点（任意 language，rank 排序见 storage 层）
            for ev in entity_events:
                for p in gold.ndi_series(ev["event_id"], language=language):
                    d = p.model_dump(mode="json")
                    d["event_id"] = ev["event_id"]
                    ndi_points.append(d)
            ndi_points.sort(key=lambda p: p.get("ts") or "")

    stances: list[dict[str, Any]] = []
    wanted_events = {event_id} if event_id else {ev["event_id"] for ev in entity_events}
    if wanted_events:
        for r in store.stances_asof(now):
            if r.event_id not in wanted_events:
                continue
            stances.append(
                {
                    "source_id": r.source_id,
                    "entity_id": r.entity_id,
                    "frame": str(r.frame),
                    "stance": str(r.stance),
                    "confidence": r.confidence,
                    "tier": str(tier_map.get(r.source_id, "")),
                    "item_key": r.item_key,
                }
            )
        stances.sort(key=lambda s: -s["confidence"])

    return ContextPacket(
        intent=intent.intent,
        target_kind=intent.target_kind,
        target_id=intent.target_id,
        entity_id=entity_id,
        signal=signal,
        event=event,
        ndi_points=ndi_points,
        stances=stances[:20],
        evidence_ids=[event_id] if event_id else [],
        notes=notes,
    )


def intent_message(packet: ContextPacket) -> str:
    """Intent + Packet → 注入 chat 图的首条消息（Agent 直接答意图）。"""
    hint = _INVESTIGATE_HINTS.get(packet.intent, "回答用户关于该对象的问题。")
    return f"{hint}\n\n--- ContextPacket ---\n{packet.summary_text()}"


def offline_artifact(packet: ContextPacket) -> AnalysisArtifact:
    """离线降级：确定性模板五层输出（不跑 LLM，如实标注 engine=offline）。"""
    sig = packet.signal
    ndi = packet.ndi_points[-1] if packet.ndi_points else None
    official = [s for s in packet.stances if s.get("tier") == str(SourceTier.OFFICIAL)]
    market = [
        s for s in packet.stances if s.get("tier") and s.get("tier") != str(SourceTier.OFFICIAL)
    ]

    obs_parts: list[str] = []
    if sig:
        obs_parts.append(
            f"信号 {sig.get('signal_id')}（{sig.get('kind')}，强度 {sig.get('strength')}）"
        )
    if ndi:
        obs_parts.append(f"NDI {ndi.get('ndi')}（{ndi.get('status')}，n={ndi.get('n_sources')}）")
    obs_parts.append(f"stance 行：官方 {len(official)} / 市场 {len(market)}")
    observation = "；".join(obs_parts) or "目标对象在当前检测窗口内无确定性快照。"

    interpretation = _INVESTIGATE_HINTS.get(packet.intent, "")
    evidence = sorted({s["source_id"] for s in packet.stances})[:8]
    alternative: str | None = None
    if ndi and ndi.get("status") != "ok":
        alternative = "样本门未通过（弃权语义）：官方簇行数不足，不产出数值。"
    elif len(official) == 0:
        alternative = "无官方簇数据，分歧度量缺官方对照——结论仅反映市场侧分布。"
    uncertainty = "；".join(packet.notes) if packet.notes else "离线模板输出：不含 LLM 解释层。"

    if packet.intent == IntentKind.CHALLENGE:
        # 触发式红队（REDESIGN_AGENT §Challenge Mode）：确定性竞争假设，ACH 纪律=必给反向证据
        challenge_lines = [
            "H1 叙事透支：分歧可能只是注意力驱动的过度反应，随后均值回归而非趋势延续。",
            "H2 基本面反转：叙事变化或由未入样本的基本面事件驱动，叙事滞后于现实。",
            "H3 采样噪声：官方簇行数有限，Dirichlet 平滑下分歧值对样本量敏感，可能是噪声。",
        ]
        red_alternative = "；".join(challenge_lines)
        red_uncertainty = "；".join(
            filter(None, [uncertainty, "红队输出不构成对结论的否证，仅列出竞争解释。"])
        )
        return AnalysisArtifact(
            kind=ArtifactKind.CHALLENGE,
            target_id=packet.target_id,
            intent=packet.intent,
            observation=observation,
            interpretation="当前结论面临三项竞争解释（离线红队，确定性规则）：",
            evidence=evidence,
            alternative=red_alternative,
            uncertainty=red_uncertainty,
            engine="offline",
        )

    return AnalysisArtifact(
        kind=ArtifactKind.ANALYSIS,
        target_id=packet.target_id,
        intent=packet.intent,
        observation=observation,
        interpretation=interpretation,
        evidence=evidence,
        alternative=alternative,
        uncertainty=uncertainty,
        engine="offline",
    )


async def run_intent(
    packet: ContextPacket,
    *,
    bronze: Any,
    store: Any,
    gold: Any,
    registry: Any,
    router: Any = None,
    tier: Any = None,
    history: list[dict[str, str]] | None = None,
    now: datetime | None = None,
    gdelt_proxy: str | None = None,
) -> dict[str, Any]:
    """Intent 执行入口：router 在→chat 图（packet 注入）；router 缺→离线 Artifact。

    LLM 路径必须 await run_chat（chat 图为 async）；此前同步调用返回
    coroutine 的缺陷由本签名修正。
    """
    if now is None:
        now = datetime.now(UTC)
    if router is None:
        art = offline_artifact(packet)
        return {"artifact": art.model_dump(mode="json"), "reply": None, "offline": True}
    from oh_agents.chat import run_chat

    try:
        result = await run_chat(
            intent_message(packet),
            history or [],
            bronze=bronze,
            store=store,
            gold=gold,
            registry=registry,
            router=router,
            tier=tier,
            gdelt_proxy=gdelt_proxy,
            now=now,
        )
        return {"artifact": None, "offline": False, **result}
    except Exception as exc:  # LLM 全候选失败→优雅降级离线 Artifact（诚实标注失败根因）
        art = offline_artifact(packet)
        uncertainty = art.uncertainty or ""
        art = art.model_copy(
            update={
                "uncertainty": (uncertainty + "；" if uncertainty else "")
                + f"LLM 调用失败已降级离线模板（{exc}）"
            }
        )
        return {
            "artifact": art.model_dump(mode="json"),
            "reply": None,
            "offline": True,
            "llm_error": str(exc)[:400],
        }


async def answer_question(
    question: str,
    *,
    bronze: Any,
    store: Any,
    gold: Any,
    registry: Any,
    tier_map: Any,
    router: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Question Watch 的 Investigator：事件匹配 → LLM 回答或离线确定性摘要。

    返回 {status, engine, answer, events}：
    - router 在 → status=answered / engine=llm / answer=chat 回复；
    - router 缺但命中事件 → status=answered / engine=offline / answer=确定性摘要；
    - router 缺且无事件 → status=pending_agent / answer=None。
    """
    if now is None:
        now = datetime.now(UTC)
    qlow = question.lower()
    events = [
        {
            "event_id": e.event_id,
            "title": e.title,
            "as_of": e.as_of.isoformat(),
        }
        for e in store.events_asof(now)
        if qlow in (e.title + " " + e.summary).lower()
        or any(w in (e.title + " " + e.summary).lower() for w in qlow.split())
    ]
    if router is not None:
        from oh_agents.chat import run_chat

        result = await run_chat(
            question,
            [],
            bronze=bronze,
            store=store,
            gold=gold,
            registry=registry,
            router=router,
            now=now,
        )
        return {
            "status": "answered",
            "engine": "llm",
            "answer": result["reply"],
            "events": events,
        }
    if not events:
        return {"status": "pending_agent", "engine": "offline", "answer": None, "events": []}
    eid_by_event = {p.event_id: p for p in store.ndi_all()}
    lines: list[str] = [f"库内命中 {len(events)} 个相关事件："]
    for ev in events[:5]:
        point = eid_by_event.get(ev["event_id"])
        ndi_txt = (
            f"NDI {point.ndi:.3f}（{point.language}）"
            if point is not None and point.ndi is not None
            else "NDI 弃权（样本不足）"
        )
        lines.append(f"- {ev['title']}（{ev['event_id']}）{ndi_txt}")
    lines.append("（离线模式：以上为确定性快照摘要；配置 LLM keys 后可获得完整分析。）")
    return {
        "status": "answered",
        "engine": "offline",
        "answer": "\n".join(lines),
        "events": events,
    }
