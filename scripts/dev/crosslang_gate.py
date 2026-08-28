"""Phase 7 跨语言门禁 CLI（裁决 F：null 集管理 + D₀ 估计 + 四条件 gate 报告）。

用法：
    # 登记 null 事件（无实质分歧的常规事件：例行数据发布/符合预期决议）
    uv run python scripts/dev/crosslang_gate.py \
        --register-null ev-fed-20260827 --entity fed \
        --reason "例行决议，结果符合预期" [--notes "..."]

    # 为已登记 null 事件计算跨语言原始距离（两语言官方簇 JS 距离）
    uv run python scripts/dev/crosslang_gate.py --compute

    # 输出四条件 gate 报告（默认行为）
    uv run python scripts/dev/crosslang_gate.py

措辞纪律：gate 未解锁（unlocked=False）时，跨语言数字仅为内部参考，
禁止对外宣传跨语言比较（README 已写死）。
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml
from oh_contracts.enums import SourceTier
from oh_pipeline.crosslang import (
    cross_language_distance,
    estimate_baseline,
    evaluate_gate,
)
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

ROOT = Path(__file__).resolve().parents[2]
SOURCES_YAML = ROOT / "config" / "sources.yaml"
SILVER_DB = ROOT / "data" / "silver.sqlite"


def _load_maps() -> tuple[dict[str, SourceTier], dict[str, str]]:
    with SOURCES_YAML.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    tier_map: dict[str, SourceTier] = {}
    lang_map: dict[str, str] = {}
    for spec in doc.get("sources", []):
        sid = spec.get("source_id")
        if not sid:
            continue
        if spec.get("tier"):
            tier_map[sid] = SourceTier(spec["tier"])
        if spec.get("language"):
            lang_map[sid] = str(spec["language"])
    return tier_map, lang_map


def _register_null(args: argparse.Namespace, store: SqliteStore) -> int:
    store.register_null_event(
        args.register_null,
        args.entity,
        args.reason,
        datetime.now(UTC),
        notes=args.notes or "",
    )
    print(f"[null] 已登记 {args.register_null}（entity={args.entity}）")
    return 0


def _compute(args: argparse.Namespace, store: SqliteStore, now: datetime) -> int:
    tier_map, lang_map = _load_maps()
    pending = [r for r in store.null_events() if r["distance"] is None]
    if not pending:
        print("[compute] 无待计算 null 事件")
        return 0
    all_rows = store.stances_asof(now)
    by_event: dict[str, list] = {}
    for r in all_rows:
        by_event.setdefault(r.event_id, []).append(r)
    ok = skip = 0
    for rec in pending:
        event_id = str(rec["event_id"])
        rows = by_event.get(event_id, [])
        dist = cross_language_distance(
            rows,
            tier_map,
            lang_map,
            args.lang_a,
            args.lang_b,
            min_per_source=args.min_per_source,
        )
        if dist is None:
            print(f"[skip] {event_id}: 官方簇样本不足（zh/en 至少一方无合格源）")
            skip += 1
            continue
        store.set_null_distance(event_id, dist)
        print(f"[ok] {event_id}: raw D_cross = {dist:.4f}")
        ok += 1
    print(f"[compute] 完成：{ok} 计算 / {skip} 跳过")
    return 0


def _gate(args: argparse.Namespace, store: SqliteStore, now: datetime) -> int:
    baseline = estimate_baseline(store.null_distances())
    report = evaluate_gate(
        zh_first_ts=store.ndi_first_ts("zh"),
        en_first_ts=store.ndi_first_ts("en"),
        now=now,
        baseline=baseline,
        min_days=args.min_days,
    )
    print("=== Phase 7 跨语言门禁（裁决 F）===")
    for c in report.conditions:
        print(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name} —— {c.detail}")
    b = report.baseline
    print(
        f"  D₀ 基线：n={b.n_null} mean={b.mean:.4f} std={b.std:.4f} "
        f"τ95={b.tau:.4f} converged={b.converged}"
    )
    state = "UNLOCKED（允许跨语言告警语义）" if report.unlocked else "LOCKED（跨语言仅内部参考）"
    print(f"  状态：{state}")
    return 0 if report.unlocked else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register-null", metavar="EVENT_ID", help="登记 null 事件")
    parser.add_argument("--entity", default="", help="null 事件实体（与 --register-null 同用）")
    parser.add_argument("--reason", default="", help="null 判定理由（必填语义）")
    parser.add_argument("--notes", default="")
    parser.add_argument("--compute", action="store_true", help="计算待算 null 事件距离")
    parser.add_argument("--lang-a", default="zh")
    parser.add_argument("--lang-b", default="en")
    parser.add_argument("--min-per-source", type=int, default=2)
    parser.add_argument("--min-days", type=int, default=28)
    args = parser.parse_args(argv)

    store = SqliteStore(connect(SILVER_DB))
    now = datetime.now(UTC)
    if args.register_null:
        if not args.entity or not args.reason:
            parser.error("--register-null 需要 --entity 与 --reason")
        return _register_null(args, store)
    if args.compute:
        return _compute(args, store, now)
    return _gate(args, store, now)


if __name__ == "__main__":
    sys.exit(main())
