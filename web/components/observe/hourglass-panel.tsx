"use client";

/**
 * Hourglass Change Field（OBSERVE 首屏主视觉，Signal tab）：
 * 上段=过去信息状态（信源流入带）→ 中段腰=质量门（合格变化数+门通过率）→
 * 下段=当前分歧/情绪/叙事/实体汇聚 → 最重要变化候选卡。
 * 纯 SVG + CSS 动画（零第三方依赖）；缺数据处诚实空态，不编造。
 */

import { HelpIcon } from "@/components/help/help-icon";
import { useOt } from "@/components/observe/i18n-bridge";
import { ndiTone } from "@/components/observe/rel-time";
import { Skeleton, toast } from "@/components/ui/toast";
import type { EmotionRow, Landscape, NdiRankRow, SourceRow } from "@/lib/landscape-api";
import { useT } from "@/lib/i18n/use-t";
import type { ObserveMode } from "@/components/observe/url-state";

const BAND_COLORS = ["#2563eb", "#16a34a", "#d97706", "#7c3aed", "#0891b2"];
const TONE_HEX: Record<string, string> = {
  ok: "#16a34a",
  warn: "#d97706",
  conflict: "#dc2626",
  gap: "#6b7280",
};
const EMO_DOT: Record<string, string> = {
  fear: "#ef4444",
  anger: "#f97316",
  optimism: "#16a34a",
  uncertainty: "#d97706",
  confidence: "#3b82f6",
};

type BypassCard = {
  lens: ObserveMode;
  dot: string;
  label: string;
  main: string;
  sub: string;
};

function fmtInt(n: number): string {
  return n.toLocaleString("en-US");
}

/** 质量门通过率：合格变化 / 当前窗口文章（密度口径；分母 0 时弃权显示 —）。 */
function passRate(qualified: number, currentArticles: number): number | null {
  if (currentArticles <= 0) return null;
  return qualified / currentArticles;
}

function HourglassSVG({
  streams,
  baselineArticles,
  currentArticles,
  nCurrentSources,
  qualifiedCount,
  rate,
  topNdi,
  dominantEmotion,
  topNarrativeShift,
  ndiEntityCount,
  windowLabel,
  labels,
}: {
  streams: { label: string; n_baseline: number; n_current: number }[];
  baselineArticles: number;
  currentArticles: number;
  nCurrentSources: number;
  qualifiedCount: number;
  rate: number | null;
  topNdi: NdiRankRow[];
  dominantEmotion: { key: string; value: number; date: string } | null;
  topNarrativeShift: { label: string; delta: number } | null;
  ndiEntityCount: number;
  windowLabel: string;
  labels: {
    past: string;
    now: string;
    gate: string;
    qualified: string;
    passRate: string;
    gateStages: string;
    divergence: string;
    emotion: string;
    narrative: string;
    entities: string;
    toCards: string;
    emptyStreams: string;
    rateFormula: string;
  };
}) {
  const vals = streams.map((s) => Math.max(s.n_baseline, s.n_current));
  const sum = vals.reduce((a, b) => a + b, 0);
  const hasStreams = sum > 0;

  // 上段流入带：顶边（收窄在舱壁内）→ 腰部收束（宽度 ∝ sqrt 占比，避免极端偏斜）
  const bands = streams
    .reduce<{ acc: { s: typeof streams[number]; w: number; xTop: number; xWaist: number; color: string }[]; cursor: number }>(
      (st, s, i) => {
        const v = Math.max(s.n_baseline, s.n_current);
        const w = v > 0 ? 2.5 + 19 * Math.sqrt(v / (sum || 1)) : 0;
        const xTop = 96 + (i / Math.max(streams.length - 1, 1)) * 128;
        const xWaist = Math.min(Math.max(st.cursor + w / 2, 136), 184);
        st.acc.push({ s, w, xTop, xWaist, color: BAND_COLORS[i % BAND_COLORS.length] });
        return { acc: st.acc, cursor: st.cursor + w + 3 };
      },
      { acc: [], cursor: 138 },
    )
    .acc;

  const rateText =
    rate === null ? "—" : `${(rate * 100).toFixed(rate < 0.01 ? 2 : 1)}%`;
  const tone0 = topNdi.length > 0 ? ndiTone(topNdi[0].ndi) : "gap";
  const shiftColor =
    topNarrativeShift && topNarrativeShift.delta > 0.005
      ? "#16a34a"
      : topNarrativeShift && topNarrativeShift.delta < -0.005
        ? "#dc2626"
        : "#6b7280";

  return (
    <svg
      viewBox="0 0 320 470"
      className="mx-auto h-auto w-full max-w-[350px]"
      role="img"
      aria-label={labels.gate}
    >
      <style>{`
        @keyframes hg-dash { to { stroke-dashoffset: -72; } }
        .hg-band { stroke-dasharray: 11 15; animation: hg-dash 2.6s linear infinite; }
        @keyframes hg-drop { 0% { cy: 44px; opacity: 0; } 10% { opacity: .85; } 90% { opacity: .85; } 100% { cy: 424px; opacity: 0; } }
        .hg-particle { animation: hg-drop 3.4s linear infinite; }
        @media (prefers-reduced-motion: reduce) { .hg-band, .hg-particle { animation: none; } }
      `}</style>

      {/* 顶行：过去窗口 */}
      <text x="10" y="16" className="fill-muted-foreground" fontSize="10">
        {labels.past} · {windowLabel}
      </text>
      <text x="310" y="16" textAnchor="end" className="fill-foreground" fontSize="10" fontWeight="600">
        {fmtInt(baselineArticles)}
      </text>

      {/* 上段舱体 */}
      <path
        d="M48,34 L272,34 L208,186 L112,186 Z"
        className="fill-muted/40 stroke-border"
        strokeWidth="1"
      />
      {hasStreams ? (
        bands.map(
          ({ s, w, xTop, xWaist, color }) =>
            w > 0 ? (
              <path
                key={s.label}
                d={`M${xTop},34 C${xTop},110 ${xWaist},150 ${xWaist},192`}
                fill="none"
                stroke={color}
                strokeWidth={w}
                strokeLinecap="round"
                opacity="0.7"
                className="hg-band"
              >
                <title>{`${s.label}: base ${s.n_baseline} · current ${s.n_current}`}</title>
              </path>
            ) : null,
        )
      ) : (
        <text x="160" y="115" textAnchor="middle" className="fill-muted-foreground" fontSize="10">
          {labels.emptyStreams}
        </text>
      )}

      {/* 中段腰：质量门（标签置于门框左侧空白区，避免与流带重叠） */}
      <text x="106" y="224" textAnchor="end" className="fill-muted-foreground" fontSize="9" letterSpacing="0.5">
        {labels.gate}
      </text>
      <rect
        x="112"
        y="192"
        width="96"
        height="56"
        rx="12"
        className="fill-card"
        stroke="#2563eb"
        strokeWidth="2"
      >
        <title>{`${labels.gateStages} · ${labels.rateFormula}`}</title>
      </rect>
      <text x="160" y="216" textAnchor="middle" className="fill-foreground" fontSize="19" fontWeight="700">
        {qualifiedCount}
      </text>
      <text x="160" y="231" textAnchor="middle" className="fill-muted-foreground" fontSize="9">
        {labels.passRate} {rateText}
      </text>
      <text x="160" y="242" textAnchor="middle" className="fill-muted-foreground" fontSize="8">
        {labels.qualified}
      </text>

      {/* 下段舱体：当前汇聚 */}
      <path
        d="M112,252 L208,252 L272,396 L48,396 Z"
        className="fill-muted/40 stroke-border"
        strokeWidth="1"
      />
      {/* 分歧行 */}
      <g>
        <title>{topNdi.map((r) => `${r.label ?? r.entity}: ${r.ndi.toFixed(2)}`).join(" · ") || labels.divergence}</title>
        <circle cx="98" cy="294" r="3.5" fill={TONE_HEX[tone0]} />
        <text x="108" y="297" className="fill-muted-foreground" fontSize="9">
          {labels.divergence}
        </text>
        <text x="212" y="297" textAnchor="end" className="fill-foreground" fontSize="9" fontWeight="600">
          {topNdi.length > 0
            ? `${(topNdi[0].label ?? topNdi[0].entity).slice(0, 10)} ${topNdi[0].ndi.toFixed(2)}`
            : "—"}
        </text>
      </g>
      {/* 情绪行 */}
      <g>
        <title>{dominantEmotion ? `${dominantEmotion.key} ${dominantEmotion.value.toFixed(2)} @ ${dominantEmotion.date}` : labels.emotion}</title>
        <circle cx="98" cy="314" r="3.5" fill={dominantEmotion ? EMO_DOT[dominantEmotion.key] ?? "#6b7280" : "#6b7280"} />
        <text x="108" y="317" className="fill-muted-foreground" fontSize="9">
          {labels.emotion}
        </text>
        <text x="212" y="317" textAnchor="end" className="fill-foreground" fontSize="9" fontWeight="600">
          {dominantEmotion ? `${dominantEmotion.key.slice(0, 11)} ${dominantEmotion.value.toFixed(2)}` : "—"}
        </text>
      </g>
      {/* 叙事迁移行 */}
      <g>
        <title>{topNarrativeShift ? `${topNarrativeShift.label} ${(topNarrativeShift.delta * 100).toFixed(1)}pt` : labels.narrative}</title>
        <circle cx="98" cy="334" r="3.5" fill={shiftColor} />
        <text x="108" y="337" className="fill-muted-foreground" fontSize="9">
          {labels.narrative}
        </text>
        <text x="212" y="337" textAnchor="end" fill={shiftColor} fontSize="9" fontWeight="600">
          {topNarrativeShift
            ? `${topNarrativeShift.label.slice(0, 8)} ${topNarrativeShift.delta > 0.005 ? "▲" : topNarrativeShift.delta < -0.005 ? "▼" : "—"}${Math.abs(Math.round(topNarrativeShift.delta * 100))}pt`
            : "—"}
        </text>
      </g>
      {/* 实体行 */}
      <g>
        <title>{labels.entities}</title>
        <circle cx="98" cy="354" r="3.5" fill="#2563eb" />
        <text x="108" y="357" className="fill-muted-foreground" fontSize="9">
          {labels.entities}
        </text>
        <text x="212" y="357" textAnchor="end" className="fill-foreground" fontSize="9" fontWeight="600">
          {ndiEntityCount > 0 ? `${ndiEntityCount}` : "—"}
        </text>
      </g>

      {/* 流出嘴 + 指向变化卡 */}
      <path d="M148,396 L172,396 L166,412 L154,412 Z" className="fill-muted-foreground/50" />
      <line x1="160" y1="412" x2="160" y2="422" className="stroke-muted-foreground" strokeWidth="1.5" />
      <path d="M155,421 L165,421 L160,428 Z" className="fill-foreground" />
      <text x="160" y="440" textAnchor="middle" className="fill-muted-foreground" fontSize="9">
        {labels.toCards}
      </text>
      <circle cx="160" cy="44" r="2.5" fill="#2563eb" className="hg-particle" />

      {/* 底行：当前窗口 */}
      <text x="10" y="462" className="fill-muted-foreground" fontSize="10">
        {labels.now} · {windowLabel}
      </text>
      <text x="310" y="462" textAnchor="end" className="fill-foreground" fontSize="10" fontWeight="600">
        {fmtInt(currentArticles)} · {nCurrentSources}
      </text>
    </svg>
  );
}

export function HourglassPanel({
  landscape,
  ndi,
  emotion,
  sources,
  windowLabel,
  onDrill,
}: {
  landscape: Landscape | null;
  ndi: NdiRankRow[];
  emotion: EmotionRow[];
  sources: SourceRow[] | null;
  windowLabel: string;
  onDrill: (target: ObserveMode) => void;
}) {
  const t = useT();
  const ot = useOt();

  if (!landscape) {
    return (
      <div className="space-y-3" aria-busy="true">
        <div className="grid gap-3 lg:grid-cols-[350px_1fr]">
          <Skeleton className="h-[500px] rounded-[12px]" />
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-24 rounded-[12px]" />
            ))}
          </div>
        </div>
        <Skeleton className="h-20 rounded-[12px]" />
      </div>
    );
  }

  const cur = landscape.current_window;
  const base = landscape.baseline_window;
  const qualified = landscape.qualified_changes;
  const rate = passRate(qualified.length, cur.n_articles);

  // 上段流入带：按峰值取前 5 个信源流
  const topStreams = [...landscape.source_streams]
    .sort((a, b) => Math.max(b.n_baseline, b.n_current) - Math.max(a.n_baseline, a.n_current))
    .slice(0, 5);

  // 下段汇聚指标
  const topNdi = [...ndi].sort((a, b) => b.ndi - a.ndi).slice(0, 3);
  const topNarrativeShift = [...landscape.narrative_streams]
    .map((n) => ({ label: n.label || n.frame, delta: n.share_current - n.share_baseline }))
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))[0];

  const EMOTION_KEYS = ["fear", "anger", "optimism", "uncertainty", "confidence"];
  let dominantEmotion: { key: string; value: number; date: string } | null = null;
  for (let i = emotion.length - 1; i >= 0 && !dominantEmotion; i -= 1) {
    const row = emotion[i];
    let best: { key: string; value: number } | null = null;
    for (const k of EMOTION_KEYS) {
      const v = row[k];
      if (typeof v === "number" && (best === null || v > best.value)) best = { key: k, value: v };
    }
    if (best) dominantEmotion = { ...best, date: row.date };
  }

  // 数据质量：语言覆盖（注册信源目录口径）、叙事标注覆盖
  const langAll = sources
    ? [...new Set(sources.filter((s) => s.n_7d > 0 || s.enabled).map((s) => s.language))]
    : null;
  const langCover =
    langAll && langAll.length > 3
      ? [...langAll.slice(0, 3), `+${langAll.length - 3}`]
      : langAll;
  const narrativeAnnotated = landscape.narrative_streams.reduce((s, n) => s + n.n_current, 0);
  const annotCover = cur.n_articles > 0 ? narrativeAnnotated / cur.n_articles : null;
  const staleness = landscape.freshness?.staleness ?? null;
  const staleTone: keyof typeof TONE_HEX =
    staleness === "fresh" ? "ok" : staleness === "aging" ? "warn" : staleness === "stale" ? "conflict" : "gap";
  const fmtMD = (iso: string): string => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;
  const range =
    landscape.freshness?.coverage_start && landscape.freshness?.coverage_end
      ? `${fmtMD(landscape.freshness.coverage_start)}→${fmtMD(landscape.freshness.coverage_end)}`
      : `${fmtMD(base.start)}→${fmtMD(cur.end)}`;

  // 旁路观察（未过质量门，不作为合格变化）：叙事迁移 / 分歧峰值 / 情绪主导
  const bypass: BypassCard[] = [];
  if (topNarrativeShift && Math.abs(topNarrativeShift.delta) > 0.005) {
    const nShift = [...landscape.narrative_streams].sort(
      (a, b) =>
        Math.abs(b.share_current - b.share_baseline) - Math.abs(a.share_current - a.share_baseline),
    )[0];
    if (nShift) {
      bypass.push({
        lens: "narrative",
        dot: "#2563eb",
        label: ot("observe.hero.bypassNarrative", "Largest narrative shift"),
        main: nShift.label || nShift.frame,
        sub: `${(nShift.share_baseline * 100).toFixed(1)}% → ${(nShift.share_current * 100).toFixed(1)}%`,
      });
    }
  }
  if (topNdi.length > 0) {
    bypass.push({
      lens: "divergence",
      dot: TONE_HEX[ndiTone(topNdi[0].ndi)],
      label: ot("observe.hero.bypassDivergence", "Highest narrative divergence (NDI)"),
      main: topNdi[0].label ?? topNdi[0].entity,
      sub: `NDI ${topNdi[0].ndi.toFixed(2)} · n=${topNdi[0].n_sources ?? topNdi[0].n ?? "—"}`,
    });
  }
  if (dominantEmotion) {
    bypass.push({
      lens: "emotion",
      dot: EMO_DOT[dominantEmotion.key] ?? "#6b7280",
      label: ot("observe.hero.bypassEmotion", "Dominant emotion (latest dated reading)"),
      main: dominantEmotion.key,
      sub: `${dominantEmotion.value.toFixed(2)} @ ${dominantEmotion.date}`,
    });
  }

  const hgLabels = {
    past: ot("observe.hg.past", "PAST inflow"),
    now: ot("observe.hg.now", "NOW field"),
    gate: ot("observe.hg.gate", "Quality gate"),
    qualified: ot("observe.hg.qualified", "qualified changes"),
    passRate: ot("observe.hg.passRate", "pass rate"),
    gateStages: ot(
      "observe.hg.gateStages",
      "change detection → evidence filtering → noise removal → uncertainty control",
    ),
    rateFormula: ot(
      "observe.hg.rateFormula",
      "pass rate = qualified changes / current-window articles (density; abstains when window is empty)",
    ),
    divergence: ot("observe.hg.divergence", "Divergence"),
    emotion: ot("observe.hg.emotion", "Emotion"),
    narrative: ot("observe.hg.narrative", "Narrative"),
    entities: ot("observe.hg.entities", "Entities on NDI board"),
    toCards: ot("observe.hg.toCards", "top change candidates"),
    emptyStreams: ot("observe.hg.emptyStreams", "no source-stream coverage in this window"),
  };

  const qualityCells: { label: string; value: string; title?: string }[] = [
    {
      label: ot("observe.quality.sample", "Sample"),
      value: `${fmtInt(base.n_articles)}+${fmtInt(cur.n_articles)}`,
      title: ot("observe.quality.sampleTip", "baseline-window articles + current-window articles"),
    },
    {
      label: ot("observe.quality.sources", "Sources"),
      value: `${cur.n_sources} (${ot("observe.quality.baseShort", "base")} ${base.n_sources})`,
    },
    {
      label: ot("observe.quality.langs", "Languages"),
      value: langCover && langCover.length > 0 ? langCover.join("·") : "—",
      title: ot("observe.quality.langsTip", "languages of registered sources (registry-level)"),
    },
    {
      label: ot("observe.quality.range", "Range"),
      value: range,
      title: ot("observe.quality.rangeTip", "UTC coverage window reported by the pipeline"),
    },
    {
      label: ot("observe.quality.annot", "Annotated"),
      value: annotCover === null ? "—" : `${(annotCover * 100).toFixed(0)}%`,
      title: ot(
        "observe.quality.annotTip",
        "current-window articles assigned to a narrative frame; low share = many unannotated",
      ),
    },
    {
      label: ot("observe.quality.freshness", "Freshness"),
      value: staleness
        ? ot(`observe.fresh.${staleness}`, staleness)
        : "—",
      title: landscape.freshness?.note ?? undefined,
    },
  ];

  return (
    <div className="space-y-4">
      {/* 首屏标题行：一句话结论 + 新鲜度 + Agent 占位 */}
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">{ot("observe.hero.title", "What changed now")}</h2>
        <HelpIcon helpKey="metric.abstain" />
        {staleness ? (
          <span
            className="inline-flex items-center gap-1 rounded-[6px] border px-1.5 py-0.5 text-xs"
            title={landscape.freshness?.note ?? undefined}
          >
            <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: TONE_HEX[staleTone] }} />
            {qualityCells[5].value}
          </span>
        ) : null}
        <span className="ml-auto flex items-center gap-2">
          <button
            type="button"
            disabled
            title={ot("observe.hero.agentTip", "Agent entry placeholder — Agent workspace returns in Phase 2")}
            className="rounded-[6px] border border-dashed px-2 py-0.5 text-xs text-muted-foreground"
          >
            {ot("observe.hero.agent", "Ask Agent · Phase 2")}
          </button>
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[350px_1fr]">
        <HourglassSVG
          streams={topStreams}
          baselineArticles={base.n_articles}
          currentArticles={cur.n_articles}
          nCurrentSources={cur.n_sources}
          qualifiedCount={qualified.length}
          rate={rate}
          topNdi={topNdi}
          dominantEmotion={dominantEmotion}
          topNarrativeShift={topNarrativeShift ?? null}
          ndiEntityCount={ndi.length}
          windowLabel={windowLabel}
          labels={hgLabels}
        />

        {/* 最重要变化候选卡 / 旁路观察 + 数据质量面板（同列，首屏一视口） */}
        <div className="space-y-4">
          {qualified.length > 0 ? (
            <>
              <p className="text-xs text-muted-foreground">
                {ot("observe.hero.topChanges", "Top change candidates (passed the quality gate)")}
              </p>
              <ul className="space-y-2">
                {qualified.slice(0, 5).map((c) => (
                  <li key={c.change_id}>
                    <button
                      type="button"
                      onClick={() =>
                        toast.info(
                          ot(
                            "observe.queue.hint",
                            "Case flow: search related coverage in Inbox → multi-select → create a research Case (abstain when evidence is insufficient).",
                          ),
                        )
                      }
                      className="w-full rounded-[12px] border border-l-4 border-l-blue-600 p-3 text-left text-[13px] transition-colors hover:bg-muted/60"
                      title={ot("observe.queue.clickHint", "click for case-creation flow hint")}
                    >
                      <span className="flex items-center gap-2">
                        <span className="rounded-[6px] bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-500/15 dark:text-blue-300">
                          {c.kind}
                        </span>
                        {c.at ? (
                          <span className="text-[10px] text-muted-foreground">{c.at.slice(0, 10)}</span>
                        ) : null}
                      </span>
                      <p className="mt-1 text-sm font-semibold">{c.headline}</p>
                      <p className="mt-0.5 text-muted-foreground">{c.what}</p>
                      {c.why_now ? (
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {ot("observe.queue.whyNow", "why now")}: {c.why_now}
                        </p>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">
                {ot(
                  "observe.hero.bypassTitle",
                  "No change passed the quality gate in this window — side-channel observations below (not qualified changes):",
                )}
              </p>
              <ul className="space-y-2">
                {bypass.map((b) => (
                  <li key={b.lens}>
                    <button
                      type="button"
                      onClick={() => onDrill(b.lens)}
                      className="w-full rounded-[12px] border border-l-4 p-3 text-left transition-colors hover:bg-muted/60"
                      style={{ borderLeftColor: b.dot }}
                      title={ot("observe.hero.bypassClick", "click to inspect in the matching lens")}
                    >
                      <p className="text-xs text-muted-foreground">{b.label}</p>
                      <p className="mt-0.5 text-sm font-semibold">{b.main}</p>
                      <p className="text-[13px] text-muted-foreground">{b.sub}</p>
                    </button>
                  </li>
                ))}
                {bypass.length === 0 ? (
                  <li className="rounded-[12px] border border-dashed p-3 text-[13px] text-muted-foreground">
                    {t("observe.noChanges")}
                  </li>
                ) : null}
              </ul>
            </>
          )}

          {/* 数据质量面板（右列底部，首屏一视口） */}
          <section aria-label={ot("observe.quality.title", "Data quality")}>
        <h3 className="mb-1 text-xs font-semibold text-muted-foreground">
          {ot("observe.quality.title", "Data quality")}
        </h3>
        <div className="grid grid-cols-2 gap-2 rounded-[12px] border p-2 sm:grid-cols-3 lg:grid-cols-6">
          {qualityCells.map((c) => (
            <div key={c.label} className="min-w-0 px-1" title={c.title}>
              <p className="truncate text-[10px] uppercase tracking-wide text-muted-foreground">{c.label}</p>
              <p className="truncate text-[13px] font-semibold tabular-nums" title={c.value}>
                {c.value}
              </p>
            </div>
          ))}
        </div>
        {landscape.quality_warnings.length > 0 ? (
          <ul className="mt-2 space-y-1 rounded-[12px] border border-amber-300 bg-amber-100 p-2 text-xs text-amber-800 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-300">
            {landscape.quality_warnings.map((w, i) => (
              <li key={`${w.code}-${i}`}>
                ⚠ {t("observe.abstainBand")}: {w.message}
              </li>
            ))}
          </ul>
        ) : null}
          </section>
        </div>
      </div>
    </div>
  );
}
