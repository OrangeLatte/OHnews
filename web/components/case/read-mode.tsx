"use client";

/**
 * READ 模式：原文多色标注 + 元素卡复核联动。
 * 新增：元素筛选 chips（联动正文高亮过滤）、文内关键词黄色 mark、
 * 复核过滤 toggle、元素卡排序（置信度/元素序）。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnnotatedText, type AnnoSpan } from "@/components/case/annotated-text";
import { HelpIcon } from "@/components/help/help-icon";
import { Skeleton, toast } from "@/components/ui/toast";
import { objectApi, type ExtractionRow } from "@/lib/object-api";
import { useT } from "@/lib/i18n/use-t";
import {
  ElementChip,
  EmptyHint,
  ModeHeader,
  elementColor,
  elementHelpKey,
  elementOrderIndex,
  reviewPillClass,
  stampId,
  type DocRow,
  type SourceOption,
  docLabel,
} from "@/components/case/case-shared";
import { elementEdge } from "@/lib/element-tokens";

const MAX_KEYWORD_MARKS = 400;

type ReviewFilter = "all" | "unreviewed" | "confirmed" | "rejected";
type SortKey = "element" | "confidence";

/** 关键词命中处合成为伪元素 span（黄 mark；与元素色块重叠时元素优先）。 */
function keywordSpans(text: string, keyword: string): AnnoSpan[] {
  const kw = keyword.trim();
  if (kw.length === 0) return [];
  const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(escaped, "gi");
  const out: AnnoSpan[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null && out.length < MAX_KEYWORD_MARKS) {
    if (m[0].length > 0) out.push({ char_start: m.index, char_end: m.index + m[0].length, element_key: "keyword" });
    if (m.index === re.lastIndex) re.lastIndex += 1;
  }
  return out;
}

type Props = {
  caseId: string;
  docs: DocRow[];
  sources: SourceOption[];
  activeDoc: string | null;
  setActiveDoc: (rid: string) => void;
  ex: Record<string, ExtractionRow[]>;
  bodies: Record<string, string>;
  /** P1-9 提取精确锚点：ext- 证据 chip 深链 ?span= → 挂载后定位正文该字符范围。 */
  initialSpan?: string;
  busy: boolean;
  dissecting: string | null;
  onDissect: (rid: string) => void;
  onReview: (extractionId: string, status: "confirmed" | "rejected") => void;
  reloadDocs: () => Promise<DocRow[]>;
};

export default function ReadMode({
  caseId,
  docs,
  sources,
  activeDoc,
  setActiveDoc,
  ex,
  bodies,
  initialSpan,
  busy,
  dissecting,
  onDissect,
  onReview,
  reloadDocs,
}: Props) {
  const t = useT();
  const [srcSel, setSrcSel] = useState("");
  const [articles, setArticles] = useState<{ item_key: string; title: string; published_at: string }[]>([]);
  const [articlesLoading, setArticlesLoading] = useState(false);
  const [manualText, setManualText] = useState("");
  const [elementFilter, setElementFilter] = useState<string | null>(null);
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
  const [sortBy, setSortBy] = useState<SortKey>("element");
  const [keyword, setKeyword] = useState("");
  const [activeEl, setActiveEl] = useState<string | null>(null);
  const [flashSpanId, setFlashSpanId] = useState<string | null>(null);
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const textWrapRef = useRef<HTMLDivElement | null>(null);

  // P1-9：?span= 深链定位。mark 渲染依赖文档与拆解数据到位，轮询 querySelector（上限 2s），
  // 命中即滚入视口；纯 DOM 操作无 setState，SSR 首帧一致。
  useEffect(() => {
    if (!initialSpan) return;
    let tries = 0;
    const timer = window.setInterval(() => {
      tries += 1;
      const mark = textWrapRef.current?.querySelector<HTMLElement>(
        `[data-span-id="${CSS.escape(initialSpan)}"]`,
      );
      if (mark) {
        mark.scrollIntoView({ behavior: "smooth", block: "center" });
        window.clearInterval(timer);
      } else if (tries >= 10) {
        window.clearInterval(timer);
      }
    }, 200);
    return () => window.clearInterval(timer);
  }, [initialSpan]);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const activeRow = docs.find((d) => d.document_revision_id === activeDoc) ?? null;
  const activeExtractions = useMemo(
    () => (activeDoc ? (ex[activeDoc] ?? []) : []),
    [activeDoc, ex],
  );
  const bodyText = activeDoc ? (bodies[activeDoc] ?? "") : "";

  const elementCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of activeExtractions) m.set(e.element_key, (m.get(e.element_key) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => elementOrderIndex(a[0]) - elementOrderIndex(b[0]));
  }, [activeExtractions]);

  const reviewCounts = useMemo(() => {
    const c = { unreviewed: 0, confirmed: 0, rejected: 0 };
    for (const e of activeExtractions) {
      if (e.human_status === "confirmed") c.confirmed += 1;
      else if (e.human_status === "rejected") c.rejected += 1;
      else c.unreviewed += 1;
    }
    return c;
  }, [activeExtractions]);

  const visibleExtractions = useMemo(() => {
    let rows = activeExtractions;
    if (elementFilter) rows = rows.filter((e) => e.element_key === elementFilter);
    if (reviewFilter !== "all") rows = rows.filter((e) => e.human_status === reviewFilter);
    return [...rows].sort((a, b) =>
      sortBy === "confidence"
        ? b.confidence - a.confidence
        : elementOrderIndex(a.element_key) - elementOrderIndex(b.element_key),
    );
  }, [activeExtractions, elementFilter, reviewFilter, sortBy]);

  const textSpans = useMemo<AnnoSpan[]>(() => {
    const rows = elementFilter
      ? activeExtractions.filter((e) => e.element_key === elementFilter)
      : activeExtractions;
    const spans: AnnoSpan[] = [];
    for (const e of rows) {
      for (const s of e.spans ?? []) {
        // span_id/extraction_id 透传：Show in text 按 data-span-id 精确定位，
        // 重叠归属按选中元素优先（与元素卡同一数据源，杜绝错色错位）。
        spans.push({
          span_id: s.span_id,
          char_start: s.char_start,
          char_end: s.char_end,
          element_key: e.element_key,
          extraction_id: e.extraction_id,
        });
      }
    }
    return keyword ? [...spans, ...keywordSpans(bodyText, keyword)] : spans;
  }, [activeExtractions, bodyText, elementFilter, keyword]);

  const loadArticles = (sid: string) => {
    setSrcSel(sid);
    if (!sid) {
      setArticles([]);
      return;
    }
    setArticlesLoading(true);
    objectApi
      .caseArticles(sid, 20)
      .then((r) => setArticles(r.articles ?? []))
      .catch(() => setArticles([]))
      .finally(() => setArticlesLoading(false));
  };

  const activateDoc = (rid: string) => {
    setActiveDoc(rid);
    setElementFilter(null);
    setActiveEl(null);
    setFlashSpanId(null);
  };

  const focusExtraction = useCallback((extractionId: string) => {
    setActiveEl(extractionId);
    cardRefs.current[extractionId]?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  /** Show in text：按 span_id 定位正文 data-span-id mark（非序号猜测），
   * 滚动 + 闪炼正确 mark；无 span 的元素不给按钮（inferred 不伪装高亮）。 */
  const showInText = useCallback((row: ExtractionRow) => {
    const first = (row.spans ?? []).find((s) => s.char_end > s.char_start && s.char_start >= 0);
    if (!first) return;
    setActiveEl(row.extraction_id);
    setFlashSpanId(first.span_id);
    const host = textWrapRef.current;
    if (host) {
      const mark = host.querySelector<HTMLElement>(`[data-span-id="${CSS.escape(first.span_id)}"]`);
      mark?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    if (flashTimer.current) clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlashSpanId(null), 2000);
  }, []);

  const onSpanClick = (elementKey: string) => {
    const hit = visibleExtractions.find((e) => e.element_key === elementKey);
    if (!hit) return;
    focusExtraction(hit.extraction_id);
  };

  const pickArticle = (itemKey: string) => {
    if (!srcSel) return;
    objectApi
      .articleDetail(srcSel, itemKey)
      .then((det) =>
        objectApi.attachDocument(caseId, {
          document_id: stampId("doc-"),
          document_revision_id: stampId("rev-"),
          source_id: srcSel,
          body: det.body ?? "",
        }),
      )
      .then(() => reloadDocs())
      .then((rows) => {
        if (rows.length > 0) setActiveDoc(rows[rows.length - 1].document_revision_id);
        toast.success(t("case.attached"));
      })
      .catch(() => toast.error(t("case.loadFailed")));
  };

  const attachManual = () => {
    if (!manualText.trim()) return;
    const body = manualText;
    objectApi
      .attachDocument(caseId, {
        document_id: stampId("doc-"),
        document_revision_id: stampId("rev-"),
        source_id: "manual",
        body,
      })
      .then(() => reloadDocs())
      .then((rows) => {
        setManualText("");
        if (rows.length > 0) setActiveDoc(rows[rows.length - 1].document_revision_id);
        toast.success(t("case.attached"));
      })
      .catch(() => toast.error(t("case.loadFailed")));
  };

  const dissectingActive = activeDoc !== null && dissecting === activeDoc;

  return (
    <div className="space-y-3">
      <ModeHeader title={t("case.modeTitle.read")} helpKey="help.mode.read" />

      <details className="rounded-xl border p-3" open={docs.length === 0}>
        <summary className="cursor-pointer text-[13px] font-medium">{t("case.pickSource")}</summary>
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={srcSel}
              onChange={(e) => loadArticles(e.target.value)}
              aria-label={t("case.pickSource")}
              className="rounded-md border bg-transparent px-2 py-1 text-xs"
            >
              <option value="">{t("case.pickSourceOption")}</option>
              {sources.map((s) => (
                <option key={s.source_id} value={s.source_id}>
                  {s.source_id} ({s.tier}/{s.language})
                </option>
              ))}
            </select>
            {articlesLoading ? <span className="text-xs text-muted-foreground">{t("case.loading")}</span> : null}
          </div>
          {articles.length > 0 ? (
            <ul className="max-h-56 space-y-1 overflow-y-auto">
              {articles.map((a) => (
                <li
                  key={a.item_key}
                  className="flex items-center justify-between gap-2 rounded-md border px-2 py-1 text-[13px]"
                >
                  <span className="min-w-0 flex-1 truncate" title={a.title}>
                    {a.title || a.item_key}
                    <span className="ml-2 text-xs text-muted-foreground">{a.published_at?.slice(0, 10)}</span>
                  </span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => pickArticle(a.item_key)}
                    className="shrink-0 rounded-md border px-2 py-0.5 text-xs hover:bg-muted disabled:opacity-50"
                  >
                    {t("case.pickArticle")}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <details>
            <summary className="cursor-pointer text-xs text-muted-foreground">{t("case.manualPaste")}</summary>
            <textarea
              value={manualText}
              onChange={(e) => setManualText(e.target.value)}
              rows={4}
              placeholder={t("case.attachBody")}
              aria-label={t("case.attachBody")}
              className="mt-2 w-full rounded-md border bg-transparent px-2 py-1 text-xs"
            />
            <button
              type="button"
              disabled={busy || !manualText.trim()}
              onClick={attachManual}
              className="mt-1 rounded-md border px-2 py-1 text-xs disabled:opacity-50"
            >
              {t("case.attach")}
            </button>
          </details>
        </div>
      </details>

      {docs.length === 0 ? (
        <EmptyHint text={t("case.gotoObserve")} action={t("case.gotoObserveAction")} href="/observe" />
      ) : (
        <>
          <div className="flex flex-wrap gap-1" role="tablist" aria-label={t("case.docTab")}>
            {docs.map((d) => (
              <button
                key={d.document_revision_id}
                type="button"
                role="tab"
                aria-selected={activeDoc === d.document_revision_id}
                onClick={() => activateDoc(d.document_revision_id)}
                className={`rounded-md border px-2 py-1 text-xs ${activeDoc === d.document_revision_id ? "border-foreground font-medium" : "text-muted-foreground hover:text-foreground"}`}
              >
                {docLabel(d)}
                <span className="ml-1 opacity-60">{d.language}</span>
              </button>
            ))}
          </div>

          {activeRow ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <section className="min-w-0 rounded-xl border p-3">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-muted-foreground">
                    {activeRow.source_id} · {activeRow.language} · {(activeRow.published_at || activeRow.fetched_at).slice(0, 10)}
                  </p>
                  <div className="flex items-center gap-2">
                    <input
                      value={keyword}
                      onChange={(e) => setKeyword(e.target.value)}
                      placeholder={t("case.keywordPlaceholder")}
                      aria-label={t("case.keywordHighlight")}
                      className="w-36 rounded-md border bg-transparent px-2 py-1 text-xs"
                    />
                    <button
                      type="button"
                      disabled={busy || dissecting !== null}
                      onClick={() => onDissect(activeRow.document_revision_id)}
                      className="rounded-md border px-2 py-1 text-xs font-medium hover:bg-muted disabled:opacity-50"
                    >
                      {dissecting === activeRow.document_revision_id ? t("case.dissecting") : t("case.dissect")}
                    </button>
                  </div>
                </div>
                {dissectingActive ? (
                  <div className="space-y-2 py-6" aria-live="polite">
                    <p className="text-center text-xs text-muted-foreground">{t("case.dissectProgress")}</p>
                    <div className="mx-auto h-1 w-2/3 overflow-hidden rounded bg-muted">
                      <div className="h-full w-1/3 animate-[pulse_1.2s_ease-in-out_infinite] bg-sky-500" />
                    </div>
                  </div>
                ) : bodyText ? (
                  <div ref={textWrapRef} className="max-h-[28rem] overflow-y-auto text-[13px] leading-7">
                    <AnnotatedText
                      text={bodyText}
                      spans={textSpans}
                      onSpanClick={onSpanClick}
                      highlightSpanId={flashSpanId}
                      activeExtractionId={activeEl}
                    />
                  </div>
                ) : (
                  <Skeleton className="h-32 w-full" />
                )}
              </section>

              <section className="min-w-0 space-y-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  {elementCounts.map(([k, n]) => (
                    <button
                      key={k}
                      type="button"
                      onClick={() => setElementFilter((p) => (p === k ? null : k))}
                      aria-pressed={elementFilter === k}
                      className={`rounded-md border px-1.5 py-0.5 text-[11px] ${elementFilter === k ? "border-foreground font-semibold" : "border-transparent text-muted-foreground hover:border-muted-foreground/40"}`}
                    >
                      <span className="inline-flex items-center gap-1">
                        <span
                          aria-hidden
                          className="inline-block h-2 w-2 rounded-sm"
                          style={{
                            backgroundColor: elementColor(k),
                            border: `1px solid ${elementEdge(k)}`,
                          }}
                        />
                        {k}
                        <span className="opacity-60">{n}</span>
                      </span>
                    </button>
                  ))}
                  {elementCounts.length === 0 ? (
                    <span className="text-xs text-muted-foreground">{t("case.notDissected")}</span>
                  ) : null}
                </div>

                <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                  <span className="text-muted-foreground">{t("case.reviewFilter")}:</span>
                  {(
                    [
                      ["all", t("case.filterAll"), activeExtractions.length],
                      ["unreviewed", t("case.reviewPending"), reviewCounts.unreviewed],
                      ["confirmed", t("case.reviewOk"), reviewCounts.confirmed],
                      ["rejected", t("case.reviewNo"), reviewCounts.rejected],
                    ] as const
                  ).map(([key, label, n]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setReviewFilter(key)}
                      aria-pressed={reviewFilter === key}
                      className={`rounded-md border px-1.5 py-0.5 ${reviewFilter === key ? "border-foreground font-medium" : "text-muted-foreground hover:text-foreground"}`}
                    >
                      {label} <span className="opacity-60">{n}</span>
                    </button>
                  ))}
                  <span className="ml-2 text-muted-foreground">{t("case.sortBy")}:</span>
                  {(
                    [
                      ["element", t("case.sortElement")],
                      ["confidence", t("case.sortConfidence")],
                    ] as const
                  ).map(([key, label]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setSortBy(key)}
                      aria-pressed={sortBy === key}
                      className={`rounded-md border px-1.5 py-0.5 ${sortBy === key ? "border-foreground font-medium" : "text-muted-foreground hover:text-foreground"}`}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                <div className="max-h-[26rem] space-y-1.5 overflow-y-auto pr-1">
                  {visibleExtractions.map((e) => {
                    const help = elementHelpKey(e.element_key);
                    const isActive = activeEl === e.extraction_id;
                    return (
                      <div
                        key={e.extraction_id}
                        ref={(el) => {
                          cardRefs.current[e.extraction_id] = el;
                        }}
                        className={`rounded-lg border p-2 text-xs leading-5 ${isActive ? "ring-2 ring-sky-500" : ""}`}
                      >
                        <div className="flex items-start gap-2">
                          <ElementChip elementKey={e.element_key} />
                          {(!e.spans || e.spans.length === 0) &&
                          e.uncertainty_reason.includes("span_anchor_failed") ? (
                            <span
                              className="shrink-0 rounded border border-dashed px-1 py-0.5 text-[10px] text-muted-foreground"
                              title={t("case.spanLegendInferred")}
                            >
                              {t("case.inferredBadge")}
                            </span>
                          ) : null}
                          <span className="min-w-0 flex-1">
                            {e.normalized_value}
                            <span className="ml-2 whitespace-nowrap text-muted-foreground">
                              {t("case.confidence")} {(e.confidence * 100).toFixed(0)}%
                            </span>
                            {e.spans && e.spans.length > 0 ? (
                              <button
                                type="button"
                                onClick={() => showInText(e)}
                                className="ml-2 underline decoration-dotted"
                              >
                                {t("case.showInText")}
                              </button>
                            ) : null}
                          </span>
                          <span className={`shrink-0 rounded px-1 py-0.5 ${reviewPillClass(e.human_status)}`}>
                            {e.human_status === "confirmed"
                              ? t("case.reviewOk")
                              : e.human_status === "rejected"
                                ? t("case.reviewNo")
                                : t("case.reviewPending")}
                          </span>
                          <span className="flex shrink-0 gap-1">
                            <button
                              type="button"
                              onClick={() => onReview(e.extraction_id, "confirmed")}
                              title={t("case.reviewConfirm")}
                              aria-label={t("case.reviewConfirm")}
                              className="rounded border px-1.5 py-0.5 hover:bg-emerald-500/10"
                            >
                              ✓
                            </button>
                            <button
                              type="button"
                              onClick={() => onReview(e.extraction_id, "rejected")}
                              title={t("case.reviewReject")}
                              aria-label={t("case.reviewReject")}
                              className="rounded border px-1.5 py-0.5 hover:bg-red-500/10"
                            >
                              ✗
                            </button>
                          </span>
                          {help ? <HelpIcon helpKey={help} /> : null}
                        </div>
                        {e.uncertainty_reason ? (
                          <p className="mt-1 pl-1 text-[11px] italic text-muted-foreground">
                            {t("case.uncertainty")}: {e.uncertainty_reason}
                          </p>
                        ) : null}
                      </div>
                    );
                  })}
                  {visibleExtractions.length === 0 && activeExtractions.length > 0 ? (
                    <p className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
                      {t("case.noMatch")}
                    </p>
                  ) : null}
                  {activeExtractions.length === 0 ? (
                    <p className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
                      {t("case.notDissected")}
                    </p>
                  ) : null}
                </div>
              </section>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
