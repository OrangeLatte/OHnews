"use client";

/**
 * 统一 Change Drawer（OBSERVE 图表联动 P1）：变化候选卡 / 旁路卡 / Sankey 信源节点 /
 * 叙事流带 / 棒棒糖实体行 / 情绪最新点 / 实体星座节点——点击打开同一右侧 Drawer。
 * 六段：是什么 / 基线对比 / 来源推动 / 支持-反对-缺失 / 覆盖与不确定性 / 行动。
 * 诚实纪律：数据缺失显示"暂无"，不编造。
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useOt } from "@/components/observe/i18n-bridge";
import type {
  EvidenceArticle,
  Landscape,
  NarrativeStream,
  QualifiedChange,
  SourceStream,
} from "@/lib/landscape-api";
import { useLocale, useT } from "@/lib/i18n/use-t";
import { relTime } from "@/components/monitors/format";

/** Drawer 可选中的数据点（discriminated union，全部来自 change-landscape 载荷）。 */
export type ChangeSelection =
  | { kind: "change"; change: QualifiedChange }
  | { kind: "source_stream"; stream: SourceStream }
  | { kind: "narrative"; stream: NarrativeStream }
  | {
      kind: "entity";
      entity: string;
      label?: string;
      ndi?: number | null;
      nSources?: number | null;
    }
  | { kind: "emotion"; emotionKey: string; value: number; date: string };

/** 低样本判据：n_baseline<5 或 n_current<5（P1 验收口径）。 */
export function isLowSample(nBaseline: number, nCurrent: number): boolean {
  return nBaseline < 5 || nCurrent < 5;
}

/** 叙事流带低样本判据：基线份额 < 0.05（P1 验收口径）。 */
export function isLowShare(shareBaseline: number): boolean {
  return shareBaseline < 0.05;
}

/** 增长率口径：后端 growth 优先；旧载荷无字段回退本地计算（基线 0 → null）。 */
function streamDelta(s: SourceStream): number | null {
  if (s.growth !== undefined) return s.growth;
  return s.n_baseline > 0 ? Math.round(((s.n_current - s.n_baseline) / s.n_baseline) * 100) : null;
}

/** 后端扣发增长（growth=null）或低样本无字段回退 → true：显示低样本警示而非爆炸百分比。 */
function growthWithheld(s: SourceStream): boolean {
  if (s.growth !== undefined) return s.growth === null;
  return s.low_baseline ?? isLowSample(s.n_baseline, s.n_current);
}

/** 低样本扣发增长徽标（title = 完整口径说明）。 */
function GrowthChip({ label }: { label: string }) {
  return (
    <span
      title={label}
      className="rounded-[6px] bg-amber-100 px-1 text-[10px] text-amber-700 dark:bg-amber-500/10 dark:text-amber-400"
    >
      n&lt;5
    </span>
  );
}

/** Case 预选主词（Inbox 搜索预填）；取不到时返回空串。 */
export function drawerSubject(sel: ChangeSelection): string {
  switch (sel.kind) {
    case "change":
      return sel.change.subjects[0] ?? sel.change.headline;
    case "source_stream":
      return sel.stream.source_id;
    case "narrative":
      return sel.stream.label || sel.stream.frame;
    case "entity":
      return sel.label ?? sel.entity;
    case "emotion":
      return sel.emotionKey;
  }
}

/**
 * Case 预选实体（Inbox facet chip 用）：变化卡取主词 subjects[0]，实体卡取实体 id；
 * 信源流/叙事/情绪不携带实体，返回空串（诚实：不臆造实体）。
 */
export function drawerEntity(sel: ChangeSelection): string {
  switch (sel.kind) {
    case "change":
      return sel.change.subjects[0] ?? "";
    case "entity":
      return sel.entity;
    default:
      return "";
  }
}

function fmtInt(n: number): string {
  return n.toLocaleString("en-US");
}

function dayOf(iso: string): string {
  return iso.slice(0, 10);
}

function DeltaTag({ delta }: { delta: number | null }) {
  if (delta === null) return <span className="text-muted-foreground">—</span>;
  const up = delta > 0;
  const flat = delta === 0;
  return (
    <span
      className={`rounded-[6px] px-1 tabular-nums ${
        up
          ? "bg-green-100 text-green-700 dark:bg-green-500/10 dark:text-green-400"
          : flat
            ? "text-muted-foreground"
            : "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-400"
      }`}
    >
      {flat ? "—" : up ? "▲" : "▼"} {Math.abs(delta)}%
    </span>
  );
}

function DrawerSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1">
      <h3 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</h3>
      {children}
    </section>
  );
}

function NoneYet({ text }: { text: string }) {
  return <p className="text-[13px] text-muted-foreground">{text}</p>;
}

function WindowLine({ label, w }: { label: string; w: { start: string; end: string; n_articles: number } }) {
  return (
    <p className="text-[13px]">
      <span className="text-muted-foreground">{label}: </span>
      <span className="tabular-nums">
        {dayOf(w.start)} → {dayOf(w.end)} · {fmtInt(w.n_articles)}
      </span>
    </p>
  );
}

function SourceDeltaRow({
  s,
  lowLabel,
  withheldLabel,
}: {
  s: SourceStream;
  lowLabel: string;
  withheldLabel: string;
}) {
  // 低样本口径对齐后端：仅 baseline<5（low_baseline 字段）；旧载荷缺省回退本地口径。
  const low = s.low_baseline ?? isLowSample(s.n_baseline, s.n_current);
  return (
    <li
      className={`flex items-center justify-between gap-2 rounded-[6px] px-1.5 py-0.5 text-xs ${
        low ? "border border-dashed border-amber-500/70 bg-amber-500/10" : ""
      }`}
      title={low ? lowLabel : undefined}
    >
      <span className="min-w-0 truncate">{s.label}</span>
      <span className="flex shrink-0 items-center gap-1 tabular-nums text-muted-foreground">
        {fmtInt(s.n_baseline)} → {fmtInt(s.n_current)}
        {growthWithheld(s) && low ? (
          <GrowthChip label={withheldLabel} />
        ) : (
          <DeltaTag delta={streamDelta(s)} />
        )}
      </span>
    </li>
  );
}

/** 支持证据引用卡：标题 + 信源 + 相对时间 + 原文外链（诚实纪律：不编造标题）。 */
function EvidenceCard({ a, openLabel, lang }: { a: EvidenceArticle; openLabel: string; lang: "en" | "zh" }) {
  return (
    <li className="rounded-[6px] border p-1.5">
      <a
        href={a.url}
        target="_blank"
        rel="noreferrer"
        aria-label={openLabel}
        className="block space-y-0.5"
      >
        <span className="line-clamp-2 block text-[13px] font-medium hover:underline">
          {a.title || a.item_key}
        </span>
        <span className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
          <span className="font-mono">{a.source_id}</span>
          <span>· {relTime(a.published_at, lang)}</span>
          <span aria-hidden="true">↗</span>
        </span>
      </a>
    </li>
  );
}

export function ChangeDrawer({
  selection,
  landscape,
  chips,
  onClose,
  onCreateCase,
  onOpenEntityTimeline,
}: {
  selection: ChangeSelection | null;
  landscape: Landscape | null;
  chips: { label: string }[];
  onClose: () => void;
  /** 创建 Case：页面层负责 Inbox 预选 + 跳转。 */
  onCreateCase: (sel: ChangeSelection) => void;
  /** 实体型选中时的"查看时间线"下钻。 */
  onOpenEntityTimeline: (entity: string) => void;
}) {
  const t = useT();
  const ot = useOt();
  const router = useRouter();
  const { locale } = useLocale();
  const lang: "en" | "zh" = locale.startsWith("zh") ? "zh" : "en";

  useEffect(() => {
    if (!selection) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selection, onClose]);

  if (!selection) return null;

  const none = ot("observe.drawer.none", "None yet");
  const base = landscape?.baseline_window ?? null;
  const cur = landscape?.current_window ?? null;
  const freshness = landscape?.freshness ?? null;
  const warnings = landscape?.quality_warnings ?? [];
  // 支持证据：仅 change 型携带；undefined=旧载荷未含键（诚实降级），[] =检索无命中。
  const evidence = selection.kind === "change" ? (selection.change.evidence_articles ?? null) : null;
  const withheldLabel = ot(
    "observe.drawer.lowBaseGrowth",
    "Low baseline (n<5) — growth withheld",
  );

  const title =
    selection.kind === "change"
      ? selection.change.headline
      : selection.kind === "source_stream"
        ? selection.stream.label
        : selection.kind === "narrative"
          ? selection.stream.label || selection.stream.frame
          : selection.kind === "entity"
            ? (selection.label ?? selection.entity)
            : t(`observe.emo.${selection.emotionKey}`);

  const badge =
    selection.kind === "change"
      ? selection.change.kind
      : selection.kind === "source_stream"
        ? selection.stream.tier || selection.stream.source_id
        : selection.kind === "narrative"
          ? ot("observe.drawer.badgeNarrative", "Narrative frame")
          : selection.kind === "entity"
            ? ot("observe.drawer.badgeEntity", "Entity")
            : ot("observe.drawer.badgeEmotion", "Emotion");

  // ③ 来源推动：按增量（n_current - n_baseline）降序 top-5
  const topSources = [...(landscape?.source_streams ?? [])]
    .sort((a, b) => b.n_current - b.n_baseline - (a.n_current - a.n_baseline))
    .slice(0, 5);

  // ④ 缺失上下文（按类型诚实列出；无则"暂无"）
  const missing: string[] = [];
  if (selection.kind === "change") {
    if (!selection.change.at) missing.push(ot("observe.drawer.missingAt", "Occurrence time not labeled"));
    if (!selection.change.why_now) missing.push(ot("observe.queue.whyNow", "why now"));
  }
  if (selection.kind === "narrative" && selection.stream.n_baseline === 0) {
    missing.push(
      ot(
        "observe.narrative.noBaseline",
        "no narrative annotation in the baseline window — single-state view shown honestly, no interpolation.",
      ),
    );
  }

  return (
    <>
      <div className="motion-fade-in fixed inset-0 z-30 bg-foreground/25" onClick={onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={t("observe.drawer.title")}
        onClick={(e) => e.stopPropagation()}
        className="motion-slide-up fixed right-0 top-0 z-40 flex h-full w-[420px] max-w-[92vw] flex-col gap-3 overflow-y-auto border-l bg-card p-4 shadow-2xl"
      >
        {/* ① 这是什么 */}
        <header className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <span className="inline-flex items-center gap-1.5">
              <span className="rounded-[6px] bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-500/15 dark:text-blue-300">
                {badge}
              </span>
              {selection.kind === "change" && selection.change.at ? (
                <span className="text-[10px] text-muted-foreground">{selection.change.at.slice(0, 10)}</span>
              ) : null}
            </span>
            <h2 className="mt-1 break-words text-sm font-semibold">{title}</h2>
            {selection.kind === "change" ? (
              <p className="mt-0.5 text-[13px] text-muted-foreground">{selection.change.what}</p>
            ) : null}
            {selection.kind === "change" && selection.change.subjects.length > 0 ? (
              <p className="mt-1 flex flex-wrap gap-1">
                {selection.change.subjects.map((s) => (
                  <span key={s} className="rounded-[6px] border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    {s}
                  </span>
                ))}
              </p>
            ) : null}
            {selection.kind === "change" ? (
              <p className="mt-1 text-[11px] text-muted-foreground">
                {selection.change.strength_word} · {selection.change.urgency}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("observe.drawer.close")}
            className="shrink-0 rounded-[6px] border px-1.5 py-0.5 text-xs hover:bg-muted/60"
          >
            ✕
          </button>
        </header>

        {/* 当前筛选 chips（只列真正作用于本图数据的窗口筛选） */}
        {chips.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5" aria-label={t("observe.drawer.filters")}>
            {chips.map((c) => (
              <span key={c.label} className="rounded-[6px] border bg-muted/50 px-2 py-0.5 text-xs">
                {c.label}
              </span>
            ))}
          </div>
        ) : null}

        {/* ② 与哪个基线比 */}
        <DrawerSection label={t("observe.drawer.baseline")}>
          {base && cur ? (
            <div className="space-y-0.5">
              <WindowLine label={ot("observe.flow.baseline", "baseline window")} w={base} />
              <WindowLine label={ot("observe.flow.current", "current window")} w={cur} />
              {selection.kind === "source_stream" ? (
                <p className="tabular-nums">
                  {fmtInt(selection.stream.n_baseline)} → {fmtInt(selection.stream.n_current)}
                  {growthWithheld(selection.stream) &&
                  (selection.stream.low_baseline ?? isLowSample(selection.stream.n_baseline, selection.stream.n_current)) ? (
                    <span className="ml-1 align-middle">
                      <GrowthChip label={withheldLabel} />
                    </span>
                  ) : streamDelta(selection.stream) !== null ? (
                    <span className="text-muted-foreground">
                      {" "}
                      ({streamDelta(selection.stream)! > 0 ? "+" : ""}
                      {streamDelta(selection.stream)}%)
                    </span>
                  ) : null}
                </p>
              ) : null}
              {selection.kind === "narrative" ? (
                <p className="tabular-nums">
                  {(selection.stream.share_baseline * 100).toFixed(1)}% →{" "}
                  {(selection.stream.share_current * 100).toFixed(1)}% ·{" "}
                  {selection.stream.n_baseline} → {selection.stream.n_current}
                  {selection.stream.low_baseline ? (
                    <span className="ml-1 align-middle">
                      <GrowthChip
                        label={ot("observe.lowSample", "Low sample (n={n}); growth may be distorted", {
                          n: 5,
                        })}
                      />
                    </span>
                  ) : null}
                </p>
              ) : null}
              {selection.kind === "entity" ? (
                <p className="tabular-nums">
                  NDI {selection.ndi === null || selection.ndi === undefined ? "—" : selection.ndi.toFixed(2)}
                  {selection.nSources != null ? ` · n=${selection.nSources}` : ""}
                  <span className="ml-1 text-xs text-muted-foreground">{t("observe.drawer.ndiNoBase")}</span>
                </p>
              ) : null}
              {selection.kind === "emotion" ? (
                <p className="tabular-nums">
                  {selection.value.toFixed(2)} @ {selection.date}
                  <span className="ml-1 text-xs text-muted-foreground">{t("observe.drawer.emotionNoBase")}</span>
                </p>
              ) : null}
            </div>
          ) : (
            <NoneYet text={none} />
          )}
        </DrawerSection>

        {/* ③ 哪些来源推动 */}
        <DrawerSection label={t("observe.drawer.sources")}>
          {topSources.length > 0 ? (
            <ul className="space-y-1">
              {topSources.map((s) => (
                <SourceDeltaRow
                  key={s.source_id}
                  s={s}
                  lowLabel={ot("observe.lowSample", "Low sample (n={n}); growth may be distorted", {
                    n: Math.min(s.n_baseline, s.n_current),
                  })}
                  withheldLabel={withheldLabel}
                />
              ))}
            </ul>
          ) : (
            <NoneYet text={none} />
          )}
        </DrawerSection>

        {/* ④ 支持 / 反对 / 缺失上下文 */}
        <DrawerSection label={t("observe.drawer.context")}>
          <div className="space-y-1 text-[13px]">
            <p>
              <span className="text-muted-foreground">{t("observe.drawer.supporting")}: </span>
              {!evidence || evidence.length === 0 ? <span>{none}</span> : null}
            </p>
            {evidence && evidence.length > 0 ? (
              <ul className="space-y-1">
                {evidence.map((a) => (
                  <EvidenceCard
                    key={`${a.source_id}-${a.item_key}`}
                    a={a}
                    openLabel={ot("observe.drawer.evidenceOpen", "Open source article")}
                    lang={lang}
                  />
                ))}
              </ul>
            ) : null}
            <p>
              <span className="text-muted-foreground">{t("observe.drawer.opposing")}: </span>
              {none}
            </p>
            <div>
              <span className="text-muted-foreground">{t("observe.drawer.missing")}: </span>
              {missing.length > 0 ? (
                <ul className="ml-4 list-disc space-y-0.5">
                  {missing.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              ) : (
                <span>{none}</span>
              )}
            </div>
          </div>
          {selection.kind === "change" && evidence === null ? (
            <p className="rounded-[6px] border border-dashed p-1.5 text-[11px] text-muted-foreground">
              {t("observe.drawer.noPerChangeEvidence")}
            </p>
          ) : null}
        </DrawerSection>

        {/* ⑤ 数据覆盖与不确定性 */}
        <DrawerSection label={t("observe.drawer.coverage")}>
          <div className="space-y-1 text-[13px]">
            <p className="flex items-center gap-1.5">
              <span className="text-muted-foreground">{ot("observe.quality.freshness", "Freshness")}: </span>
              {freshness ? (
                <>
                  <span className="font-medium">{ot(`observe.fresh.${freshness.staleness}`, freshness.staleness)}</span>
                  {freshness.coverage_end ? (
                    <span className="tabular-nums text-muted-foreground">
                      · {t("observe.dataAsOf")} {dayOf(freshness.coverage_end)} UTC
                    </span>
                  ) : null}
                </>
              ) : (
                "—"
              )}
            </p>
            {freshness?.note ? <p className="text-[11px] text-muted-foreground">{freshness.note}</p> : null}
            {warnings.length > 0 ? (
              <ul className="space-y-1 rounded-[6px] border border-amber-300 bg-amber-100 p-1.5 text-[11px] text-amber-800 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-300">
                {warnings.slice(0, 3).map((w, i) => (
                  <li key={`${w.code}-${i}`}>
                    ⚠ <span className="opacity-70">{w.code}</span>: {w.message}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground">
                {t("observe.abstainBand")}: {none}
              </p>
            )}
          </div>
        </DrawerSection>

        {/* ⑥ 行动 */}
        <div className="mt-auto flex flex-wrap gap-2 border-t pt-3">
          <button
            type="button"
            onClick={() => onCreateCase(selection)}
            className="rounded-[6px] bg-foreground px-2.5 py-1 text-xs font-medium text-background transition-opacity hover:opacity-85"
          >
            {t("observe.drawer.createCase")}
          </button>
          <button
            type="button"
            onClick={() => router.push("/monitors?create=1")}
            className="rounded-[6px] border px-2.5 py-1 text-xs transition-colors hover:bg-muted/60"
          >
            {t("observe.drawer.createMonitor")}
          </button>
          {selection.kind === "entity" ? (
            <button
              type="button"
              onClick={() => onOpenEntityTimeline(selection.entity)}
              className="rounded-[6px] border px-2.5 py-1 text-xs transition-colors hover:bg-muted/60"
            >
              {t("observe.drawer.openTimeline")} →
            </button>
          ) : null}
        </div>
      </aside>
    </>
  );
}
