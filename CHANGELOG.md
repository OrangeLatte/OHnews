# Changelog

All notable changes to OH!News are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is semver.

## [0.4.0] - 2026-09-18

### Added

- **One-command demo start.** `bash scripts/dev/demo_up.sh` downloads the demo bundle
  (~7 MB, a real two-week EN+ZH corpus with cases, anchors and watch history), restores it
  to `data/`, and starts API + Web — end-to-end without any LLM API key. `--docker` variant
  included.
- `scripts/dev/demo_snapshot.py` — export a self-consistent demo bundle (per-DB
  `VACUUM INTO` + bronze parquet, integrity-checked, secrets excluded).
- `scripts/dev/demo_restore.py` — restore a bundle into `data/` with overwrite protection.
- `CHANGELOG.md` (this file).

### Changed

- README restructured as a product page: concrete one-line positioning, demo GIF on the
  first screen, aggregator/ChatGPT comparison table, demo-data quickstart moved up.
  Architecture and AI internals moved below the fold.
- Known limitations condensed; roadmap table added.
- Repository description and topics re-aimed at news analysis / media bias / OSINT /
  evidence-based research / self-hosted.

## [0.3.0] - 2026-09-09 (tag `v0.3.0-gdelt-backfill`)

### Added

- GDELT backfill pipeline for wide-window corpus construction.
- AI design-notes section in README (three-tier routing, structured extraction,
  deterministic verifiers, dual-engine fallback, LangGraph HITL, cost discipline).

### Fixed

- Detection anchor unified (`detection_anchor`) so detail pages no longer 404 under
  cross-day data delay.
- Detect step skips signals for entity-less events instead of emitting `?` noise signals.
- EN-mode UI no longer leaks Chinese copy from the backend (`lang` parameter gap).

## [0.2.0] - 2026-09-05

### Added

- Workflow hardening: tracking units migrated to monitors, scheduled refresh,
  morning-brief generation.
- I18n audit tooling and cross-language gating for dictionary translations.

## [0.1.0] - 2026-09-03

### Added

- Initial research build (M1–M6): cognitive loop across NOW / INVESTIGATE / WATCH / MEMORY,
  bronze parquet + silver SQLite storage, NDI with bootstrap CIs and abstention,
  18-type anchored dissection with deterministic span verification, belief snapshots,
  Next.js newspaper UI, FastAPI facade.

[0.4.0]: https://github.com/OrangeLatte/OHnews/compare/v0.3.0-gdelt-backfill...HEAD
[0.3.0]: https://github.com/OrangeLatte/OHnews/compare/599e3f1...v0.3.0-gdelt-backfill
[0.2.0]: https://github.com/OrangeLatte/OHnews/commits/?since=2026-09-05&until=2026-09-09
[0.1.0]: https://github.com/OrangeLatte/OHnews/commits/?until=2026-09-03
