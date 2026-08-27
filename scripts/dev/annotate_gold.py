"""gold set 标注委员会运行器（裁决 B 的 LLM 化标注）。

用法：
  # 离线演练（确定性伪输出，验证全流程，不调 API、不花钱）
  uv run python scripts/dev/annotate_gold.py --dry-run

  # 真实标注（需 export DEEPSEEK_API_KEY 与 ZHIPU_API_KEY）
  export DEEPSEEK_API_KEY=... ZHIPU_API_KEY=...
  uv run python scripts/dev/annotate_gold.py --live --limit 30

  # 从 Bronze 真实文章扩句后标注
  uv run python scripts/dev/annotate_gold.py --live --expand 120

方法论声明：基准 = 模型共识（DeepSeek V4 Flash + GLM-5.3-Flash 标注，
GLM-5.3 裁决），非人工标注；结果须如实披露一致率与 α。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import re
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "oh-llm" / "src"))

from oh_contracts.enums import Tier  # noqa: E402
from oh_llm.committee import (  # noqa: E402
    AnnotationCommittee,
    AnnotationResult,
    FrameDist,
)
from oh_llm.config import ModelRef, load_llm_config  # noqa: E402
from oh_llm.router import ModelRouter  # noqa: E402

SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*")

_WEAK = {"loss": 0.05, "responsibility": 0.05, "human_interest": 0.05, "other": 0.05}
_LOSS_HEAVY = {"loss": 0.7, "conflict": 0.1, "gain": 0.05, **_WEAK}
_GAIN_HEAVY = {"gain": 0.7, "conflict": 0.1, "loss": 0.05, **_WEAK}
_OTHER_HEAVY = {
    "other": 0.5,
    "loss": 0.1,
    "gain": 0.1,
    "responsibility": 0.1,
    "conflict": 0.1,
    "human_interest": 0.1,
}


class DeterministicRouter:
    """--dry-run：按句子 hash 确定性分流（偶=一致/奇=分歧），零 API 调用。"""

    def __init__(self) -> None:
        self.calls: list[Tier] = []

    async def invoke(self, tier, system, user, schema):  # noqa: ANN001, ARG002
        self.calls.append(tier)
        h = int(hashlib.sha256(user.encode("utf-8")).hexdigest(), 16)
        if tier == Tier.STRATEGIC:
            dist = _OTHER_HEAVY
        elif h % 2 == 0:
            dist = _LOSS_HEAVY
        else:
            dist = _GAIN_HEAVY
        return FrameDist.from_any(dist), ModelRef("dryrun", f"model-{tier.value}")


def load_seed_texts(path: Path) -> list[tuple[str, str]]:
    """种子句池：[(item_id, text)]，id 取前 12 位 hash。"""
    items: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        text = json.loads(line)["text"].strip()
        item_id = "seed-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        items.append((item_id, text))
    return items


def expand_from_bronze(bronze_root: Path, n: int, seed: int = 42) -> list[tuple[str, str]]:
    """从 Bronze 真实文章抽句：含实体别名的 10-120 字句子，随机采样 n 条。"""
    from oh_pipeline.entities import EntityRegistry
    from oh_storage.bronze_parquet import ParquetBronzeWriter

    registry = EntityRegistry()
    pool: list[str] = []
    for rec in ParquetBronzeWriter(bronze_root).iter_records():
        body = str(rec.normalized.get("body") or "")
        for sent in SENT_SPLIT.split(body):
            sent = sent.strip()
            if 10 <= len(sent) <= 120 and registry.match(sent):
                pool.append(sent)
    pool = list(dict.fromkeys(pool))
    random.Random(seed).shuffle(pool)
    out = []
    for sent in pool[:n]:
        item_id = "bronze-" + hashlib.sha256(sent.encode("utf-8")).hexdigest()[:12]
        out.append((item_id, sent))
    return out


async def run(args: argparse.Namespace) -> int:
    seeds_path = ROOT / "config" / "gold_set" / "seed_zh.jsonl"
    items = load_seed_texts(seeds_path)
    if args.expand:
        items += expand_from_bronze(ROOT / "data" / "bronze", args.expand)
    if args.skip or args.limit:
        end = args.skip + args.limit if args.limit else None
        items = items[args.skip : end]
    if not items:
        print("句池为空", file=sys.stderr)
        return 1

    if args.dry_run:
        router = DeterministicRouter()
    else:
        import os

        missing = [env for env in ("DEEPSEEK_API_KEY", "ZHIPU_API_KEY") if not os.environ.get(env)]
        if missing:
            print(f"缺少环境变量: {missing}；先 export 或改用 --dry-run", file=sys.stderr)
            return 2
        router = ModelRouter(load_llm_config(ROOT / "config" / "models.yaml"))

    committee = AnnotationCommittee(router)
    results: list[AnnotationResult] = []
    for idx, (item_id, text) in enumerate(items, 1):
        try:
            res = await committee.annotate_frame(item_id, text)
        except RuntimeError as exc:
            print(f"[{idx}/{len(items)}] FAIL {item_id}: {exc}", file=sys.stderr)
            continue
        results.append(res)
        tag = "AGREE" if res.agreed else "JUDGE"
        top = max(res.final, key=res.final.get)
        print(f"[{idx}/{len(items)}] {tag} {top.value}={res.final[top]:.2f} {text[:36]}")

    if not results:
        print("无成功标注", file=sys.stderr)
        return 1

    labels_a = [max(r.label_a, key=r.label_a.get).value for r in results]
    labels_b = [max(r.label_b, key=r.label_b.get).value for r in results]
    alpha = float(__import__("oh_llm").committee.krippendorff_alpha_nominal(labels_a, labels_b))
    agreed = sum(1 for r in results if r.agreed)
    report = {
        "n_items": len(results),
        "agreed": agreed,
        "judge_used": len(results) - agreed,
        "agreement_rate": round(agreed / len(results), 4),
        "krippendorff_alpha_nominal": round(alpha, 4),
        "annotators": sorted({m for r in results for m in r.annotators}),
        "judges": sorted({r.judge for r in results if r.judge}),
        "mode": "dry-run" if args.dry_run else "live",
        "honesty_note": "基准 = 模型共识（非人工标注）；α 为标注员间一致性（nominal, argmax）",
    }
    print("\n== 汇报 ==")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.out:
        out_path = ROOT / args.out
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for r in results:
                row = asdict(r)
                row["label_a"] = {k.value: v for k, v in r.label_a.items()}
                row["label_b"] = {k.value: v for k, v in r.label_b.items()}
                row["final"] = {k.value: v for k, v in r.final.items()}
                row["verdict"] = {k.value: v for k, v in r.verdict.items()} if r.verdict else None
                row["status"] = "committee_v0"
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"\n已写出 {out_path}（{len(results)} 条）")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="离线演练（确定性伪输出）")
    ap.add_argument("--live", action="store_true", help="真实调用（需 API keys）")
    ap.add_argument("--limit", type=int, default=0, help="限制标注条数（0=全部）")
    ap.add_argument("--skip", type=int, default=0, help="跳过前 N 条（分批断点跑）")
    ap.add_argument("--expand", type=int, default=0, help="从 Bronze 扩充句子数")
    ap.add_argument("--out", default="config/gold_set/annotated_zh.jsonl")
    args = ap.parse_args()
    if not args.dry_run and not args.live:
        ap.error("必须指定 --dry-run 或 --live")
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
