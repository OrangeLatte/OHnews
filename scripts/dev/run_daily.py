"""日运行编排：Bronze → 事件 → analysis_graph → Gold（Phase 3 全链）。

用法：
    uv run python scripts/dev/run_daily.py [--days N] [--min-articles K]
        [--min-sources K] [--min-per-source K] [--limit K] [--llm]
        [--language zh]

默认纯统计模式（router=None，LLM 节点自动跳过）；--llm 启用官方源
LLM 补盲 + 假设生成 + 证据解释（需 DEEPSEEK_API_KEY/ZHIPU_API_KEY）。
开发态默认 min_per_source=2（测量效度验证与对外数字必须用 10）。
--language 指定 within-language 计算（裁决 F），如 zh/en；缺省为混算
（language="all"，跨语言比较未过门禁前仅作内部参考）。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from oh_agents.graph import GraphDeps, build_analysis_graph
from oh_agents.intel_pipeline import build_daily_intel
from oh_contracts.enums import SourceTier
from oh_pipeline.divergence import temperature_gap
from oh_pipeline.entities import DEFAULT_ENTITIES, EntityRegistry
from oh_pipeline.events import EventBuilder
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

ROOT = Path(__file__).resolve().parents[2]
SOURCES_YAML = ROOT / "config" / "sources.yaml"


def load_tier_map(path: Path) -> dict[str, SourceTier]:
    """sources.yaml → {source_id: SourceTier}（enabled 与否不影响 tier 归属）。"""
    with path.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    tier_map: dict[str, SourceTier] = {}
    for spec in doc.get("sources", []):
        sid = spec.get("source_id")
        tier = spec.get("tier")
        if sid and tier:
            tier_map[sid] = SourceTier(tier)
    return tier_map


def load_lang_map(path: Path) -> dict[str, str]:
    """sources.yaml → {source_id: language}（within-language 归属，裁决 F）。"""
    with path.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    lang_map: dict[str, str] = {}
    for spec in doc.get("sources", []):
        sid = spec.get("source_id")
        lang = spec.get("language")
        if sid and lang:
            lang_map[sid] = str(lang)
    return lang_map


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="事件聚合窗口（天）")
    parser.add_argument("--min-articles", type=int, default=3)
    parser.add_argument("--min-sources", type=int, default=2)
    parser.add_argument(
        "--min-per-source", type=int, default=2, help="NDI 源级样本门：开发态 2 / 对外数字 10"
    )
    parser.add_argument("--limit", type=int, default=0, help="只跑前 K 个事件（0=全部）")
    parser.add_argument("--skip", type=int, default=0, help="跳过前 K 个事件（分批跑用）")
    parser.add_argument("--llm", action="store_true", help="启用 LLM 补盲/假设/解释（需 API keys）")
    parser.add_argument(
        "--language",
        default=None,
        help="within-language 计算（zh/en，裁决 F）；缺省混算 all",
    )
    args = parser.parse_args(argv)

    bronze = ParquetBronzeWriter(ROOT / "data" / "bronze")
    records = list(bronze.iter_records())
    if not records:
        print("[EMPTY] Bronze 无数据——先运行 scripts/backfill.py", file=sys.stderr)
        return 1

    now = datetime.now(UTC)
    window_start = now - timedelta(days=args.days)
    records = [r for r in records if r.published_at is not None and r.published_at >= window_start]
    print(f"[bronze] 窗口内 {len(records)} 条（{args.days} 天）")

    built = EventBuilder().build(
        records,
        min_articles=args.min_articles,
        min_sources=args.min_sources,
    )
    if args.skip:
        built = built[args.skip :]
    if args.limit:
        built = built[: args.limit]
    if not built:
        print("[EMPTY] 无合格事件（提高窗口或放宽 --min-articles/--min-sources）")
        return 0
    print(
        f"[events] 合格事件 {len(built)} 个（门：≥{args.min_articles} 篇 × ≥{args.min_sources} 源）"
    )

    store = SqliteStore(connect(ROOT / "data" / "silver.sqlite"))
    for b in built:
        store.upsert_event(b.event)

    tier_map = load_tier_map(SOURCES_YAML)
    lang_map = load_lang_map(SOURCES_YAML)

    router = None
    llm_tagger = None
    if args.llm:
        if not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("ZHIPU_API_KEY")):
            print("[WARN] --llm 但无 API keys——降级为纯统计模式")
        else:
            from oh_agents.tagger_llm import LLMTagger
            from oh_llm.config import load_llm_config
            from oh_llm.router import ModelRouter

            cfg = load_llm_config(ROOT / "config" / "models.yaml")
            router = ModelRouter(cfg)
            llm_tagger = LLMTagger(router)
            print("[llm] LLM 补盲 + 假设生成 + 证据解释已启用")

    deps = GraphDeps(
        bronze=bronze,
        store=store,
        gold=store,
        tier_map=tier_map,
        router=router,
        llm_tagger=llm_tagger,
        lookback_days=args.days,
        min_per_source=args.min_per_source,
        lang_map=lang_map,
        languages=(args.language,) if args.language else None,
    )
    graph = build_analysis_graph(deps)
    result = asyncio.run(
        graph.ainvoke(
            {"events_input": [b.event.model_dump() for b in built], "now": now.isoformat()}
        )
    )

    points = result.get("ndi_points", [])
    ndi_ok = sum(1 for p in points if p.status == "ok")
    ndi_abstain = sum(1 for p in points if p.status == "abstain")
    hyps = result.get("hypotheses", [])
    cards = result.get("narrative_cards", [])
    print(
        f"[graph] rows via stances ndi_ok={ndi_ok} ndi_abstain={ndi_abstain} "
        f"hypotheses={len(hyps)} cards={len(cards)}"
    )

    lang_label = args.language or "all"
    print(f"\n== 事件 NDI 概览（NDI=叙事分歧指数，描述性监测；language={lang_label}）==")
    print(f"{'event_id':<28} {'articles':>8} {'sources':>7} {'NDI':>8} {'ΔT':>8}")
    for b in built:
        eid = b.event.event_id
        rows = [r for r in store.stances_asof(now) if r.event_id == eid]
        gap = temperature_gap(
            rows,
            tier_map,
            min_per_source=args.min_per_source,
            lang_map=lang_map,
            language=lang_label,
        )
        series = store.ndi_series(eid, language=lang_label)
        point = series[-1] if series else None
        ndi_s = f"{point.ndi:.3f}" if point and point.ndi is not None else "abstain"
        gap_s = f"{gap:.2f}" if isinstance(gap, float) else "-"
        print(f"{eid:<28} {b.n_articles:>8} {b.n_sources:>7} {ndi_s:>8} {gap_s:>8}")

    # —— M2 情报层：Status → Signal(IS 排序) → Narrative → Insight（RECONSTRUCTION §D）——
    intel = build_daily_intel(
        records,
        store,
        EntityRegistry(DEFAULT_ENTITIES),
        tier_map,
        as_of=now,
        lookback_days=args.days,
        min_per_source=args.min_per_source,
    )
    print(
        f"\n== M2 情报层（as_of={now:%Y-%m-%d %H:%M} UTC，engine=offline）"
        f"assessments={len(intel.assessments)} signals={len(intel.signals)} "
        f"narratives={len(intel.narratives)} insights={len(intel.insights)} =="
    )
    for s in intel.signals:
        is_s = s.metrics.get("intelligence_score")
        print(f"  [signal] {s.signal_id} {s.kind} IS={is_s}: {s.what_changed}")
    for i in intel.insights:
        print(f"  [insight] {i.headline}")
        print(f"    {i.observation}")
    for n in intel.narratives:
        print(f"  [narrative] {n.narrative_id}: {n.statement}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
