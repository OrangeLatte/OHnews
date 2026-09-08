# OH!News — Cognitive-Loop Intelligence Terminal (non-commercial)

OH!News turns a multilingual financial news stream into a **narrative-divergence monitor** and walks the user through a complete cognitive loop:

> **Discover what changed → Verify the evidence → Form your own judgment → Keep tracking it.**

Four entries: **NOW** (`/observe`) · **INVESTIGATE** (`/cases`) · **WATCH** (`/watch`) · **MEMORY** (`/archive`).

> **Wording discipline (hard rule)**: NDI (Narrative Divergence Index) is a *descriptive* monitoring metric (EPU-style conditional variable) — **not a return predictor**. The words "forecast / timing / buy / sell" are banned project-wide. Every conclusion ships with an evidence chain (claim → source quote + provenance + PIT time).

## What you get

| Layer | What it does |
|---|---|
| `oh-sources` | 8 adapters (rss / gdelt / fred / json_api / html / browser / reddit_cdp …) → Bronze parquet partitions |
| `oh-pipeline` | event clustering, stance tagging, NDI (Jeffreys-smoothed JSD + bootstrap CI), hero quality gate, narrative change field |
| `oh-storage` | SQLite stores: silver (events/stances/NDI/annotations/dissections), research (cases/extractions/evidence spans), tracking, archive, beliefs, product events |
| `oh-agents` | langgraph agents: 18-element **article dissection** (chunked, concurrent, span-anchored), 6-type **research reports**, **tracking/alerts** unified units, **archives & agent paper**, cross-language translator ("linguist prompt workflow"), parent console |
| `oh-api` | FastAPI facade: /api/observe stack, /api/cases, /api/tracking, /api/archive, /api/agent/*, briefing & change-landscape aggregations |
| `oh-llm` | three-tier model router (io/execute/strategic) with JSON-mode guard, candidate fallback, concurrency limiter |
| `web` | Next.js 16 + React 19 newspaper-style light UI, 21-language i18n (incl. RTL), "ⓘ" term tooltips, ChartBase/SVG viz with abstention states |

## Quick start

```bash
# backend (FastAPI, port 8787)
uv run python scripts/dev/serve.py --port 8787

# frontend (Next.js dev, port 3001)
cd web && npx next dev -p 3001

# collect + annotate (cron-friendly; auto-runs dictionary annotation after collection)
uv run python scripts/dev/cron_collect.py --days 1
uv run python scripts/dev/run_daily.py --days 15   # pipeline: events → stances → NDI
```

LLM keys (DeepSeek / Zhipu / Tavily) are set at `/settings/developer` and stored in `data/runtime_keys.json` (chmod 600). Without keys every LLM feature **degrades honestly** (dictionary/offline engine, labelled as such).

## Demo

The repository ships in **demo state**: 15 days of data, two full-length sources (English: `guardian_world`, Chinese: `wallstreetcn`), and two seeded end-to-end cases (inbox → case study → tracking → memory archive).

- English walkthrough: [`docs/demo_en/`](docs/demo_en/) (10 screenshots, UI in English)
- 中文演示：[`docs/demo_zh/`](docs/demo_zh/)（10 张截图，界面为中文）

## Tests & quality gates

```bash
uv run ruff check packages && uv run pytest -q        # backend (600+ tests)
cd web && npx tsc --noEmit && npx eslint .            # frontend
```

## Documentation

- Architecture & data-model source of truth: [`docs/RECONSTRUCTION.md`](docs/RECONSTRUCTION.md) (+ `ARCHITECTURE_MAP.md`, `archi.svg`)
- Superseded specs & planning records were moved to `../OHnews_backup_20260909/docs_migrated/` with notes (`MIGRATION_NOTES.md`); the pre-prune full data backup lives in the same folder.

## License / scope

Non-commercial research use only. No trading advice; no user judgments are ever overwritten by the system; deterministic metrics are never edited by agents.
