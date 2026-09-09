"""Orange Hourglass 场景聚合（阶段 1.5-c）。

把两窗 bronze 覆盖、stance 框架份额、过质量门变化与引文
聚合为单一 ChangeLandscape——前端只渲染不拼图。
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import UTC, datetime, timedelta

from oh_api.briefing import (
    _corpus_lang,
    bucket_evidence,
    build_briefing_with_signals,
    data_freshness,
)
from oh_api.search import search_bronze
from oh_contracts.briefing import BriefingResponse, EvidenceCitation, EvidenceSet
from oh_contracts.change_landscape import (
    ChangeEvidenceArticle,
    ChangeFieldPayload,
    ChangeFieldPoint,
    ChangeLandscape,
    EffectiveFilters,
    EvidenceFlag,
    EvidenceSourceCount,
    FrameDayPoint,
    LandscapeSample,
    NarrativeStream,
    NdiDayPoint,
    QualifiedChange,
    QualityWarning,
    SourceDayPoint,
    SourceStream,
    TimeSeries,
    TimeWindow,
)
from oh_contracts.enums import SourceTier
from oh_contracts.schemas import BronzeRecord, NDIPoint
from oh_contracts.signals import Signal
from oh_pipeline.entities import EntityRegistry
from oh_storage.protocols import SilverStore

_FRAME_ZH: dict[str, str] = {
    "loss": "损失",
    "gain": "收益",
    "responsibility": "责任",
    "conflict": "冲突",
    "human_interest": "人情",
    "other": "其他",
}

_FRAME_EN: dict[str, str] = {
    "loss": "Loss",
    "gain": "Gain",
    "responsibility": "Responsibility",
    "conflict": "Conflict",
    "human_interest": "Human stories",
    "other": "Other",
}

_MAX_SOURCE_STREAMS = 12
_MAX_QUALIFIED = 5
_MAX_EVIDENCE_REFS = 20
_LOW_COVERAGE_FLOOR = 5
# T2：基线窗计数低于该阈值时比率/份额迁移读数不可信（与前端 isLowSample 口径一致）
_MIN_BASELINE_FOR_GROWTH = 5
# T1：每变化最多附 3 条证据文章；主题词上限（控线性扫描成本）
_MAX_EVIDENCE_ARTICLES = 3
_MAX_TOPIC_TERMS = 5
# T9 timeseries：Small Multiples 裁剪上限（其余信源由前端聚合"其他"）
_MAX_TS_SOURCES = 8
_MAX_TS_FRAMES = 6
_MAX_TS_ENTITIES = 8

_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{1,}")
_TOPIC_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "not",
        "but",
        "its",
        "their",
        "will",
        "would",
        "could",
        "new",
        "says",
        "said",
        "after",
        "over",
        "amid",
        "into",
        "more",
        "than",
        "about",
        "percent",
        "per",
        "cent",
        "vs",
    }
)


def _iso_window(now: datetime, days: int) -> tuple[datetime, datetime, datetime]:
    """返回 (baseline_start, window_start, now)：两等长窗。"""
    window_start = now - timedelta(days=days)
    baseline_start = now - timedelta(days=2 * days)
    return baseline_start, window_start, now


def _split_window(
    records: list[BronzeRecord],
    lo: datetime,
    hi: datetime,
) -> list[BronzeRecord]:
    """published_at ∈ [lo, hi) 的记录（无 published_at 的不进窗，PIT 同规）。"""
    out = []
    for r in records:
        ts = r.published_at
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if lo <= ts < hi:
            out.append(r)
    return out


def _tier_cluster(tier: SourceTier | None) -> str:
    return "official" if tier is SourceTier.OFFICIAL else "market"


def _growth(base_n: int, cur_n: int) -> tuple[float | None, bool]:
    """T2 低基数诚实弃权：n_baseline < 5 时比率读数不可信 → (None, True)。

    Returns:
        (growth 百分点数或 None, low_baseline 标记)；如 2→87 的 4250% 不再产出。
    """
    low = base_n < _MIN_BASELINE_FOR_GROWTH
    growth = None if low else round((cur_n - base_n) / base_n * 100, 1)
    return growth, low


def _source_streams(
    base: list[BronzeRecord],
    cur: list[BronzeRecord],
    tier_map: dict[str, SourceTier],
) -> list[SourceStream]:
    base_n = Counter(r.source_id for r in base)
    cur_n = Counter(r.source_id for r in cur)
    ranked = sorted(
        set(base_n) | set(cur_n),
        key=lambda s: (-(cur_n.get(s, 0) + base_n.get(s, 0)), s),
    )[:_MAX_SOURCE_STREAMS]
    out = []
    for s in ranked:
        growth, low = _growth(base_n.get(s, 0), cur_n.get(s, 0))
        out.append(
            SourceStream(
                source_id=s,
                label=s,
                tier=tier_map.get(s).value if s in tier_map else "",
                cluster=_tier_cluster(tier_map.get(s)),
                n_baseline=base_n.get(s, 0),
                n_current=cur_n.get(s, 0),
                growth=growth,
                low_baseline=low,
            )
        )
    return out


def _share(counts: Counter[str]) -> dict[str, float]:
    total = sum(counts.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in counts.items()}


def _narrative_streams(
    rows: list,
    lo_cur: datetime,
    lo_base: datetime,
    now: datetime,
    tier_map: dict[str, SourceTier],
    lang: str = "zh",
) -> list[NarrativeStream]:
    """两窗框架份额流带（stance 行 ts 分窗；cluster_split=官方 vs 市场份额）。

    T2 可比性校正：同时输出共同来源 cohort（两窗都出现的源）内的校正份额
    adjusted_share_*——未校正 share_* 会被「来源结构变化」污染（如基线 14 源
    vs 当前 48 源，冲突份额下降可能只是新源稀释）。cohort <2 源时 adjusted=None。
    """
    base_frames: Counter[str] = Counter()
    cur_frames: Counter[str] = Counter()
    base_cluster: dict[str, Counter[str]] = {}
    cur_cluster: dict[str, Counter[str]] = {}
    base_frames_c: Counter[str] = Counter()
    cur_frames_c: Counter[str] = Counter()
    base_sources: set[str] = set()
    cur_sources: set[str] = set()
    for r in rows:
        ts = r.ts if r.ts.tzinfo else r.ts.replace(tzinfo=UTC)
        if ts > now:
            continue
        frame = r.frame.value if hasattr(r.frame, "value") else str(r.frame)
        if frame not in _FRAME_ZH:
            frame = "other"
        cluster = _tier_cluster(tier_map.get(r.source_id))
        if ts >= lo_cur:
            cur_frames[frame] += 1
            cur_cluster.setdefault(frame, Counter())[cluster] += 1
            cur_sources.add(r.source_id)
        elif ts >= lo_base:
            base_frames[frame] += 1
            base_cluster.setdefault(frame, Counter())[cluster] += 1
            base_sources.add(r.source_id)
    cohort = base_sources & cur_sources
    cohort_ok = len(cohort) >= 2
    for r in rows:
        if not cohort_ok or r.source_id not in cohort:
            continue
        ts = r.ts if r.ts.tzinfo else r.ts.replace(tzinfo=UTC)
        if ts > now:
            continue
        frame = r.frame.value if hasattr(r.frame, "value") else str(r.frame)
        if frame not in _FRAME_ZH:
            frame = "other"
        if ts >= lo_cur:
            cur_frames_c[frame] += 1
        elif ts >= lo_base:
            base_frames_c[frame] += 1
    base_share = _share(base_frames)
    cur_share = _share(cur_frames)
    base_share_c = _share(base_frames_c)
    cur_share_c = _share(cur_frames_c)
    frames = sorted(set(base_share) | set(cur_share), key=lambda f: (-(cur_share.get(f, 0.0)), f))
    return [
        NarrativeStream(
            frame=f,  # type: ignore[arg-type]
            label=_FRAME_ZH[f] if lang == "zh" else _FRAME_EN.get(f, f),
            share_baseline=round(base_share.get(f, 0.0), 4),
            share_current=round(cur_share.get(f, 0.0), 4),
            n_baseline=base_frames.get(f, 0),
            n_current=cur_frames.get(f, 0),
            cluster_split_baseline={
                k: round(v, 4) for k, v in _share(base_cluster.get(f, Counter())).items()
            },
            cluster_split_current={
                k: round(v, 4) for k, v in _share(cur_cluster.get(f, Counter())).items()
            },
            adjusted_share_baseline=(round(base_share_c.get(f, 0.0), 4) if cohort_ok else None),
            adjusted_share_current=(round(cur_share_c.get(f, 0.0), 4) if cohort_ok else None),
            n_cohort_sources=len(cohort),
            low_baseline=base_frames.get(f, 0) < _MIN_BASELINE_FOR_GROWTH,
        )
        for f in frames
    ]


def _hero_gate(
    ev: EvidenceSet,
    sig: Signal,
    registry: EntityRegistry,
) -> list[str]:
    """Hero Eligibility Gate（阶段 1.5-d）：变化进 Hero 区的硬门。

    判定（全部满足才过门）：
    1. ≥2 独立来源（source_id 去重；source_id 即媒体源，去重即非同媒体）。
    2. 实体相关性：至少一条引文 quote/title 命中主体别名
       （_relevant_quote 切取保证 + gate 显式断言双保险）。
    3. 引文 HTML 已清洗（quote 无 "<"）。
    过期显式（staleness）由 quality_warnings 承担，不在本门拦截。
    """
    cites = [*(ev.supporting or []), *(ev.contradicting or []), *(ev.context or [])]
    if not cites:
        return ["无任何可展示引文"]
    reasons: list[str] = []
    n_sources = len({c.source_id for c in cites})
    if n_sources < 2:
        reasons.append(f"独立来源仅 {n_sources} 个（Hero 区要求 ≥2）")
    spec = registry.get(sig.entity_id)
    aliases = list(spec.aliases) if spec else []
    if aliases and not any(
        any(a.lower() in f"{c.title}{c.quote}".lower() for a in aliases) for c in cites
    ):
        reasons.append("引文未命中主体别名（实体相关性不足）")
    if any("<" in c.quote for c in cites):
        reasons.append("引文含未清洗 HTML")
    return reasons


def _topic_terms(subjects: list[str], headline: str, what: str) -> list[str]:
    """变化 → 主题词表（T1，无 LLM）：subjects 优先，headline/what 补拉丁词。

    subjects 为实体人话标签（如「美联储」），CJK 走子串匹配、拉丁串走
    search_bronze 的空白分词 AND；headline/what 为中文模板句，仅提取其中
    可能出现的拉丁 token（名词性词组，如 "Fed"/"CPI"），停用词剔除。
    """
    terms: list[str] = []
    for s in subjects:
        s = s.strip()
        if len(s) >= 2:
            terms.append(s)
    for text in (headline, what):
        for tok in _LATIN_TOKEN_RE.findall(text or ""):
            low = tok.strip(".-").casefold()
            if len(low) >= 3 and low not in _TOPIC_STOPWORDS:
                terms.append(low)
    seen: set[str] = set()
    return [t for t in terms if not (t in seen or seen.add(t))][:_MAX_TOPIC_TERMS]


def _evidence_articles(
    subjects: list[str],
    headline: str,
    what: str,
    *,
    cur_records: list[BronzeRecord],
    base_records: list[BronzeRecord],
    bronze_by_key: dict[str, BronzeRecord],
    limit: int = _MAX_EVIDENCE_ARTICLES,
) -> list[ChangeEvidenceArticle]:
    """逐变化证据文章（T1）：主题词 bronze 检索，当前窗口内优先。

    诚实纪律：无主题词或检索无命中 → 空列表（前端已处理空态），不编造。
    """
    out: list[ChangeEvidenceArticle] = []
    seen: set[str] = set()
    terms = _topic_terms(subjects, headline, what)
    for scope in (cur_records, base_records):
        for term in terms:
            if len(out) >= limit:
                return out
            for hit in search_bronze(scope, term, limit=limit):
                key = str(hit["item_key"])
                if key in seen:
                    continue
                seen.add(key)
                rec = bronze_by_key.get(key)
                out.append(
                    ChangeEvidenceArticle(
                        item_key=key,
                        source_id=str(hit["source_id"]),
                        title=str(hit["title"] or ""),
                        published_at=hit["published_at"],
                        language=str((rec.normalized.get("language") if rec else "") or ""),
                    )
                )
    return out


def _evidence_coverage(
    articles: list[ChangeEvidenceArticle],
) -> tuple[list[EvidenceSourceCount], EvidenceFlag]:
    """实体证据覆盖口径（P0-1）：按信源聚合命中数 + 覆盖等级。

    sufficient=≥2 篇实体证据；single_source=恰 1 篇；none=0 篇。
    纪律：质量门通过 ≠ 实体证据充分，逐变化披露不冒充。
    """
    counts: dict[str, int] = {}
    for a in articles:
        counts[a.source_id] = counts.get(a.source_id, 0) + 1
    breakdown = [EvidenceSourceCount(source_id=k, n=v) for k, v in sorted(counts.items())]
    total = len(articles)
    if total >= 2:
        flag = EvidenceFlag.SUFFICIENT
    elif total == 1:
        flag = EvidenceFlag.SINGLE_SOURCE
    else:
        flag = EvidenceFlag.NONE
    return breakdown, flag


def _qualified_changes(
    briefing: BriefingResponse,
    signals: list[Signal],
    *,
    bronze_by_key: dict[str, BronzeRecord],
    cur_records: list[BronzeRecord],
    base_records: list[BronzeRecord],
    store: SilverStore,
    tier_map: dict[str, SourceTier],
    registry: EntityRegistry,
    now: datetime,
    lang: str = "zh",
) -> tuple[list[QualifiedChange], list[EvidenceCitation], int]:
    """腰部 Change Point + 证据引用（supporting 桶前 2 条/变化）+ Gate 拦截计数。

    changes 与 signals 同序（同一次 detect_signals 产出），zip 配对回查证据链。
    每个 change 先组装证据再过 Hero Gate（1.5-d），未过门不进入腰部。
    T1：每个合格变化附 evidence_articles（主题词 bronze 检索 top-3，
    当前窗口内优先；无命中为空列表，不编造）。
    """
    changes: list[QualifiedChange] = []
    refs: dict[str, EvidenceCitation] = {}
    gated_out = 0
    for b, sig in zip(briefing.changes[:_MAX_QUALIFIED], signals, strict=False):
        try:
            ev = bucket_evidence(
                sig,
                bronze_by_key=bronze_by_key,
                store=store,
                tier_map=tier_map,
                as_of=now,
                registry=registry,
                lang=lang,
            )
        except (KeyError, ValueError):
            gated_out += 1
            continue
        if _hero_gate(ev, sig, registry):
            gated_out += 1
            continue
        subject_labels = [s.label for s in (b.subjects or [])]
        _articles = _evidence_articles(
            subject_labels,
            b.headline,
            b.what,
            cur_records=cur_records,
            base_records=base_records,
            bronze_by_key=bronze_by_key,
        )
        _breakdown, _flag = _evidence_coverage(_articles)
        changes.append(
            QualifiedChange(
                change_id=b.change_id,
                kind=b.kind,
                headline=b.headline,
                what=b.what,
                why_now=b.why_now,
                strength_word=b.strength_word,
                urgency=b.urgency,
                subjects=subject_labels,
                evidence_articles=_articles,
                evidence_source_breakdown=_breakdown,
                evidence_flag=_flag,
                metrics={
                    k: float(v) for k, v in sig.metrics.items() if isinstance(v, (int, float))
                },
            )
        )
        for c in (ev.supporting or ev.context or [])[:2]:
            if c.item_key not in refs:
                refs[c.item_key] = c
    return changes, list(refs.values())[:_MAX_EVIDENCE_REFS], gated_out


def _composition_shift_warning(narr: list[NarrativeStream]) -> QualityWarning | None:
    """T2 来源可比性校正：raw 迁移主要由来源结构变化驱动时降级提示。

    判定：任一框架 |raw Δ|≥0.10 且（cohort<2 不可校正 或 |adjusted Δ| < 0.5·|raw Δ|）
    → 提示「框架迁移可能反映来源结构变化而非真实叙事转变」，校正口径见 adjusted 字段。
    """
    for n in narr:
        raw_delta = abs(n.share_current - n.share_baseline)
        if raw_delta < 0.10:
            continue
        if (
            n.adjusted_share_baseline is None
            or n.adjusted_share_current is None
            or abs(n.adjusted_share_current - n.adjusted_share_baseline) < 0.5 * raw_delta
        ):
            coh = (
                f"{n.n_cohort_sources} 个共同来源"
                if n.n_cohort_sources >= 2
                else "共同来源不足 2 个"
            )
            return QualityWarning(
                code="source_composition_shift",
                message=(
                    f"两窗来源构成不同，未校正对比可能高估框架迁移（如「{n.label}」"
                    f"原始 {n.share_baseline:.0%}→{n.share_current:.0%}）；"
                    f"校正口径（{coh}）显示变化更温和——解读以校正份额为准"
                ),
            )
    return None


def _warnings(
    cur: TimeWindow,
    streams: list[SourceStream],
    changes: list[QualifiedChange],
    freshness_staleness: str,
    gated_out: int = 0,
    narr: list[NarrativeStream] | None = None,
    lang: str = "zh",
) -> list[QualityWarning]:
    out: list[QualityWarning] = []
    if cur.n_articles == 0:
        out.append(QualityWarning(code="window_empty", message="当前窗口内没有可展示的文章覆盖"))
        return out
    if cur.n_articles < _LOW_COVERAGE_FLOOR:
        out.append(
            QualityWarning(
                code="low_coverage",
                message=(
                    f"当前窗口仅 {cur.n_articles} 篇文章，覆盖不足"
                    if lang == "zh"
                    else f"Only {cur.n_articles} articles in the window; too few"
                ),
            )
        )
    if streams:
        top = max(streams, key=lambda s: s.n_current)
        if cur.n_sources >= 2 and top.n_current > cur.n_articles * 0.5:
            out.append(
                QualityWarning(
                    code="single_source_dominant",
                    message=(
                        f"「{top.label}」占当前窗口覆盖过半，观点可能单一"
                        if lang == "zh"
                        else f"'{top.label}' dominates current coverage; views may be one-sided"
                    ),
                )
            )
    if freshness_staleness == "stale":
        out.append(
            QualityWarning(
                code="stale_data",
                message=(
                    "数据已明显过期，请谨慎解读时间对比"
                    if lang == "zh"
                    else "Data is clearly stale; interpret time comparisons with caution"
                ),
            )
        )
    if gated_out > 0:
        out.append(
            QualityWarning(
                code="gate_insufficient_coverage",
                message=(
                    f"{gated_out} 个变化因覆盖不足未进入主视图"
                    if lang == "zh"
                    else f"{gated_out} changes hidden for low coverage (quality gate)"
                ),
            )
        )
    if not changes:
        out.append(
            QualityWarning(
                code="no_qualified_changes",
                message=(
                    "窗口内没有通过质量门的变化，腰部为空"
                    if lang == "zh"
                    else "No change passed the quality gate; the middle band is empty"
                ),
            )
        )
    if narr is not None:
        comp = _composition_shift_warning(narr)
        if comp is not None:
            out.append(comp)
    return out


def _utc_day(ts: datetime) -> str:
    """UTC 日期桶键（YYYY-MM-DD）；naive 视为 UTC（与 _split_window 同规）。"""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).date().isoformat()


def _timeseries(
    cur_records: list[BronzeRecord],
    rows: list,
    ndi_points: list[NDIPoint],
    *,
    lo: datetime,
    hi: datetime,
    days: int,
) -> TimeSeries | None:
    """按天分桶时间序列（T9）：current 同窗 ×（信源计数/框架份额/NDI 读数）。

    分桶窗 [lo, hi) 复用 current_window 切分（检测锚定后 det_now），
    day = published_at/ts 的 UTC 日期。诚实纪律：
    - published_at 为 None 的记录不计入（PIT 同规）；
    - NDI abstain 点（ndi=None）无读数，不产出；
    - 三序列全空 → None（不返回空结构假装有数据）。
    share 分母 = 当日全部框架计数（含未入选 top6 框架，单日归一诚实）。
    """
    # 信源×日计数（窗口总量 top8）
    sd_counts: Counter[tuple[str, str]] = Counter()
    for r in cur_records:
        if r.published_at is None:
            continue
        sd_counts[(r.source_id, _utc_day(r.published_at))] += 1
    sd_tot: Counter[str] = Counter()
    for (s, _d), n in sd_counts.items():
        sd_tot[s] += n
    top_srcs = sorted(sd_tot, key=lambda s: (-sd_tot[s], s))[:_MAX_TS_SOURCES]
    sd_by_src: dict[str, list[tuple[str, int]]] = {}
    for (s, d), n in sd_counts.items():
        sd_by_src.setdefault(s, []).append((d, n))
    source_day = [
        SourceDayPoint(source_id=s, day=d, n=n)
        for s in top_srcs
        for d, n in sorted(sd_by_src.get(s, []))
    ]

    # 框架×日计数 + 当日总数（归一分母）
    fd_counts: Counter[tuple[str, str]] = Counter()
    day_tot: Counter[str] = Counter()
    for r in rows:
        ts = r.ts if r.ts.tzinfo else r.ts.replace(tzinfo=UTC)
        if not lo <= ts < hi:
            continue
        frame = r.frame.value if hasattr(r.frame, "value") else str(r.frame)
        if frame not in _FRAME_ZH:
            frame = "other"
        d = ts.date().isoformat()
        fd_counts[(frame, d)] += 1
        day_tot[d] += 1
    fd_tot: Counter[str] = Counter()
    for (f, _d), n in fd_counts.items():
        fd_tot[f] += n
    top_frames = sorted(fd_tot, key=lambda f: (-fd_tot[f], f))[:_MAX_TS_FRAMES]
    fd_by_frame: dict[str, list[tuple[str, int]]] = {}
    for (f, d), n in fd_counts.items():
        fd_by_frame.setdefault(f, []).append((d, n))
    frame_day = [
        FrameDayPoint(frame=f, day=d, share=round(n / day_tot[d], 4), n=n)  # type: ignore[arg-type]
        for f in top_frames
        for d, n in sorted(fd_by_frame.get(f, []))
    ]

    # NDI×日：仅窗口内 ok 点；实体 rank = 窗口内最新 NDI 降序（同 ts 取 ndi 大者）
    nd_by_ent: dict[str, list[tuple[str, float, int]]] = {}
    latest: dict[str, tuple[datetime, float]] = {}
    for p in ndi_points:
        ts = p.ts if p.ts.tzinfo else p.ts.replace(tzinfo=UTC)
        if not lo <= ts < hi or p.ndi is None:
            continue
        nd_by_ent.setdefault(p.event_id, []).append((ts.date().isoformat(), p.ndi, p.n_sources))
        cur = latest.get(p.event_id)
        if cur is None or (ts, p.ndi) > cur:
            latest[p.event_id] = (ts, p.ndi)
    top_ents = sorted(latest, key=lambda e: (-latest[e][1], e))[:_MAX_TS_ENTITIES]
    ndi_day = [
        NdiDayPoint(entity_id=e, day=d, ndi=ndi, n_sources=ns)
        for e in top_ents
        for d, ndi, ns in sorted(nd_by_ent.get(e, []))
    ]

    all_days = [p.day for p in (*source_day, *frame_day, *ndi_day)]
    if not all_days:
        return None
    return TimeSeries(
        days=days,
        day_start=min(all_days),
        source_day=source_day,
        frame_day=frame_day,
        ndi_day=ndi_day,
    )


def build_change_landscape(
    *,
    bronze_iter,
    store: SilverStore,
    registry: EntityRegistry,
    tier_map: dict[str, SourceTier],
    now: datetime,
    days: int = 7,
    min_per_source: int = 10,
    top: int = 5,
    briefing_result: tuple[BriefingResponse, list[Signal]] | None = None,
    source_ids: tuple[str, ...] | list[str] = (),
    language: str | None = None,
    lang_by_source: dict[str, str] | None = None,
    lang: str | None = None,
) -> ChangeLandscape:
    """变化场场景唯一聚合入口（后端拼图，前端渲染）。

    source_ids/language 筛选在 bronze 记录层预过滤——两窗/检测/证据
    全部作用于同一过滤后数据集（筛选语义对全视图闭合）。
    effective_filters/sample/computed_at 回显实际口径供前端展示。

    v2（T2 待做）：两窗需按共同来源 cohort 校正可比性，raw 与
    composition-adjusted 双口径并列，避免把来源结构变化误读为叙事迁移。
    """
    records = list(bronze_iter)
    if source_ids or language:
        _sid = {s for s in source_ids if s}
        records = [
            r
            for r in records
            if (not _sid or r.source_id in _sid)
            and (not language or (r.normalized.get("language") or "") == language)
        ]
    # 数据末梢锚定：采集断流时（now 距最新数据 >1d），检测与窗口锚点跟随数据
    # 覆盖期，避免检测尾窗空转导致信号恒零；数据过时事实仍由 freshness
    # 警告如实承担（staleness 以真实 now 计算，不因锚定而被掩盖）。
    # 锚点取各数据面（bronze 正文 / silver stances）最旧的尾——检测窗口
    # 必须落在每个数据面的覆盖期内，否则慢面（stances 通常滞后 bronze）
    # 的 recent 窗为空、信号恒零。
    _pubs = [r.published_at for r in records if r.published_at]
    _stance_tail = max((r.ts for r in store.stances_asof(now)), default=None)
    _tails = [t for t in (max(_pubs) if _pubs else None, _stance_tail) if t]
    det_now = now
    if _tails and (now - min(_tails)) > timedelta(days=1):
        det_now = min(_tails)
    d = max(1, days)
    lo_base, lo_cur, _ = _iso_window(det_now, d)
    base = _split_window(records, lo_base, lo_cur)
    cur = _split_window(records, lo_cur, det_now)

    baseline_w = TimeWindow(
        start=lo_base.isoformat(),
        end=lo_cur.isoformat(),
        n_articles=len(base),
        n_sources=len({r.source_id for r in base}),
    )
    current_w = TimeWindow(
        start=lo_cur.isoformat(),
        end=det_now.isoformat(),
        n_articles=len(cur),
        n_sources=len({r.source_id for r in cur}),
    )
    streams = _source_streams(base, cur, tier_map)
    rows = store.stances_asof(det_now)
    corpus_lang = lang or _corpus_lang(records, lang_by_source)
    narr = _narrative_streams(rows, lo_cur, lo_base, det_now, tier_map, corpus_lang)
    timeseries = _timeseries(cur, rows, store.ndi_all(), lo=lo_cur, hi=det_now, days=d)

    corpus_lang = lang or _corpus_lang(records, lang_by_source)
    freshness = data_freshness(records, now=now, lookback_days=max(1, days), lang=corpus_lang)
    if briefing_result is None:
        briefing, signals = build_briefing_with_signals(
            bronze_iter=iter(records),
            store=store,
            registry=registry,
            tier_map=tier_map,
            now=det_now,
            days=max(1, days),
            top=top,
            min_per_source=min_per_source,
            lang=corpus_lang,
        )
    else:
        briefing, signals = briefing_result
    bronze_by_key = {r.item_key: r for r in records}
    changes, refs, gated_out = _qualified_changes(
        briefing,
        signals,
        bronze_by_key=bronze_by_key,
        cur_records=cur,
        base_records=base,
        store=store,
        tier_map=tier_map,
        registry=registry,
        now=det_now,
        lang=corpus_lang,
    )
    warnings = _warnings(
        current_w, streams, changes, freshness.staleness, gated_out, narr, corpus_lang
    )

    seed = f"{baseline_w.start}|{current_w.end}"
    scene_id = f"hg-{now:%Y%m%d}-{hashlib.sha1(seed.encode()).hexdigest()[:8]}"
    return ChangeLandscape(
        scene_id=scene_id,
        generated_at=now.isoformat(),
        baseline_window=baseline_w,
        current_window=current_w,
        source_streams=streams,
        narrative_streams=narr,
        qualified_changes=changes,
        evidence_refs=refs,
        freshness=freshness,
        quality_warnings=warnings,
        effective_filters=(
            EffectiveFilters(
                source_ids=list(source_ids),
                language=language,
            )
            if (source_ids or language)
            else None
        ),
        sample=LandscapeSample(
            baseline=baseline_w.n_articles,
            current=current_w.n_articles,
        ),
        timeseries=timeseries,
        computed_at=now.isoformat(),
    )


_LANE_BY_TIER: dict[str, str] = {
    "L1": "official",
    "L2": "press",
    "L3": "market",
    "L4": "social",
}


def build_change_field(
    *,
    records: list,
    rows: list,
    tier_map: dict[str, SourceTier],
    now: datetime,
    days: int = 30,
    changes: list[QualifiedChange] | None = None,
    lang: str = "zh",
) -> ChangeFieldPayload:
    """叙事场时序（T8）：每日×泳道(tier 簇)×框架计数矩阵。

    数据源 = stance 行（frame 已知）；未登记 tier 的源归 unknown 泳道。
    series 按日期升序，仅包含有数据的日期。
    """
    d = max(1, min(days, 90))
    lo = now - timedelta(days=d)
    buckets: dict[str, dict[str, Counter[str]]] = {}
    for r in rows:
        ts = r.ts if hasattr(r, "ts") else None
        if ts is None or ts > now or ts < lo:
            continue
        day = ts.date().isoformat()
        tier = tier_map.get(r.source_id)
        lane = _LANE_BY_TIER.get(str(tier) if tier else "", "unknown")
        lane_map = buckets.setdefault(day, {})
        lane_map.setdefault(lane, Counter())[str(r.frame)] += 1
    # 逐日连续化（T8 v2）：窗口内每天输出点位，缺测日 lanes 为空（前端占位），
    # 保证横轴以天为维度且与日历对齐（m2587 反馈：每天都要有数据可视化呈现）。
    cal_days = {(lo + timedelta(days=i)).date().isoformat() for i in range(d + 1)}
    all_days = sorted(set(buckets) | cal_days)
    series = [
        ChangeFieldPoint(
            date=day,
            lanes={k: dict(c) for k, c in buckets.get(day, {}).items()},
        )
        for day in all_days
    ]
    return ChangeFieldPayload(
        days=d,
        series=series,
        changes=list(changes or []),
        freshness=data_freshness(records, now=now, lookback_days=d, lang=lang),
    )
