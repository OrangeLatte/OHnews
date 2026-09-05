"use client";

/**
 * 研究收件箱（Inbox）：bronze 全库检索 → 多选 → 新建研究 Case（一次建 Case + 逐篇 attach）。
 * 认知流程：发现变化 → 检索证据 → 建案 → LLM 拆解。cased 文章默认过滤（toggle 可显示）。
 * 过滤状态由页面持有（左栏 facet + 顶部 chips 共享），本组件只负责结果表与建案流程。
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useOt } from "@/components/observe/i18n-bridge";
import { relParts } from "@/components/observe/rel-time";
import { StatusDot } from "@/components/observe/status-dots";
import { Skeleton, toast } from "@/components/ui/toast";
import type { SourceRow } from "@/lib/landscape-api";
import { useT } from "@/lib/i18n/use-t";

/** item_key（含 :/ 等字符）→ URL 安全 id：非字母数字折叠为短 hash。 */
function stableId(itemKey: string): string {
  let h = 5381;
  for (let i = 0; i < itemKey.length; i += 1) {
    h = ((h << 5) + h + itemKey.charCodeAt(i)) >>> 0;
  }
  const tail = itemKey.slice(-18).replace(/[^a-zA-Z0-9_-]/g, "");
  return `${tail || "k"}${h.toString(36)}`;
}

export type InboxFilters = {
  q: string;
  qInput: string;
  lang: string;
  element: string;
  value: string;
  valueInput: string;
  includeCased: boolean;
  selSources: string[];
};

export type InboxFilterHandlers = {
  onQInput: (v: string) => void;
  onQCommit: () => void;
  onValueInput: (v: string) => void;
  onValueCommit: () => void;
  onElementChange: (v: string) => void;
  onToggleSource: (sourceId: string) => void;
  onToggleIncludeCased: () => void;
  onClearFilters: () => void;
};

type InboxRow = {
  item_key: string;
  source_id: string;
  title: string;
  url: string;
  language: string;
  published_at: string;
  body_preview: string;
  cased: boolean;
  dissected: boolean;
};

const INBOX_LIMIT = 50;
const ELEMENT_KEYS = [
  "actor",
  "action",
  "target",
  "stakeholder",
  "context",
  "timeline",
  "intent",
  "tone",
  "diction",
  "perspective",
] as const;

/** 模块级 ID 生成（保持与 /cases 页一致的 case-{ts36} 约定；隔离 Date.now 的 render 纯度检查）。 */
function newCaseId(): string {
  return `case-${Date.now().toString(36)}`;
}

/** bronze body 含 HTML 标签：仅展示层去标签（attach 仍发送原文全文）。 */
function stripHtml(s: string): string {
  return s
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;|&amp;|&lt;|&gt;|&quot;|&#39;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

async function errText(r: Response): Promise<string> {
  const j = (await r.json().catch(() => null)) as { detail?: string } | null;
  return j?.detail ?? `HTTP ${r.status}`;
}

async function loadFullBody(row: InboxRow): Promise<{ body: string; full: boolean }> {
  try {
    const r = await fetch(
      `/api/articles/detail?source_id=${encodeURIComponent(row.source_id)}&item_key=${encodeURIComponent(row.item_key)}`,
      { cache: "no-store" },
    );
    if (!r.ok) throw new Error(String(r.status));
    const d = (await r.json()) as { body?: string };
    if (d.body && d.body.length > 0) return { body: d.body, full: true };
    return { body: row.body_preview, full: false };
  } catch {
    return { body: row.body_preview, full: false };
  }
}

export function InboxPanel({
  sources,
  sourcesErr,
  days,
  filters,
  handlers,
}: {
  sources: SourceRow[];
  sourcesErr: string;
  days: number;
  filters: InboxFilters;
  handlers: InboxFilterHandlers;
}) {
  const t = useT();
  const ot = useOt();
  const router = useRouter();

  const { q, qInput, lang, element, value, valueInput, includeCased, selSources } = filters;
  const filterKey = useMemo(
    () => JSON.stringify([q, lang, element, value, days, selSources]),
    [q, lang, element, value, days, selSources],
  );
  const hasFilter = q !== "" || lang !== "" || element !== "" || selSources.length > 0;

  const [wrap, setWrap] = useState<{ key: string; n: number; rows: InboxRow[] } | null>(null);
  const [err, setErr] = useState("");
  const [tick, setTick] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [caseTitle, setCaseTitle] = useState("");
  const [caseQuestion, setCaseQuestion] = useState("");
  const [creating, setCreating] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [lastCreated, setLastCreated] = useState<{ caseId: string; n: number } | null>(null);

  useEffect(() => {
    let alive = true;
    const p = new URLSearchParams();
    for (const s of selSources) p.append("source_id", s);
    if (q) p.set("q", q);
    if (lang) p.set("language", lang);
    if (days > 0) p.set("days", String(days));
    if (element) {
      p.set("element", element);
      if (value) p.set("value", value);
    }
    p.set("limit", String(INBOX_LIMIT));
    fetch(`/api/inbox?${p.toString()}`, { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`inbox: ${await errText(r)}`);
        const data = (await r.json()) as { n: number; rows: InboxRow[] };
        if (alive) {
          setWrap({ key: filterKey, n: data.n, rows: data.rows });
          setErr("");
          setChecked((prev) => {
            const keys = new Set(data.rows.map((x) => x.item_key));
            const next = new Set([...prev].filter((k) => keys.has(k)));
            return next.size === prev.size ? prev : next;
          });
        }
      })
      .catch((e: unknown) => {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [filterKey, q, lang, element, value, days, selSources, tick]);

  const stale = wrap === null || wrap.key !== filterKey;
  const visibleRows = useMemo(
    () => (wrap === null ? [] : wrap.rows.filter((r) => includeCased || !r.cased)),
    [wrap, includeCased],
  );
  const hiddenCased = wrap === null ? 0 : wrap.rows.length - visibleRows.length;
  const checkedRows = visibleRows.filter((r) => checked.has(r.item_key));

  const toggleCheck = (itemKey: string): void => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(itemKey)) next.delete(itemKey);
      else next.add(itemKey);
      return next;
    });
  };

  const allVisibleChecked = visibleRows.length > 0 && checkedRows.length === visibleRows.length;

  const createCase = async (): Promise<void> => {
    const question = caseQuestion.trim();
    if (!question) {
      toast.error(ot("observe.inbox.needQuestion", "Please fill in the research question first."));
      return;
    }
    const items = checkedRows.filter((r) => !r.cased);
    if (items.length === 0) {
      toast.error(
        ot(
          "observe.inbox.allCased",
          "Selected articles are already in a case. Toggle \"show cased\" to review them.",
        ),
      );
      return;
    }
    setCreating(true);
    setProgress({ done: 0, total: items.length });
    try {
      const now = new Date().toISOString();
      const caseId = newCaseId();
      const res = await fetch("/api/cases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // 契约（OpenAPI ResearchCase, additionalProperties=false）：无 title 字段，可选标题入 context_note
        body: JSON.stringify({
          case_id: caseId,
          question,
          context_note: caseTitle.trim(),
          origin: "observe",
          created_by: "user",
          created_at: now,
          updated_at: now,
        }),
      });
      if (!res.ok) throw new Error(`cases: ${await errText(res)}`);

      let failed = 0;
      let previewUsed = 0;
      let firstFail = "";
      for (const row of items) {
        try {
          const full = await loadFullBody(row);
          if (!full.full) previewUsed += 1;
          const ar = await fetch(`/api/cases/${encodeURIComponent(caseId)}/documents`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              document_id: `doc-${stableId(row.item_key)}`,
              document_revision_id: `rev-${stableId(row.item_key)}-r1`,
              source_id: row.source_id,
              body: full.body,
              canonical_url: row.url,
              content_hash: "",
              language: row.language,
              published_at: row.published_at,
              external_key: row.item_key,
              title: row.title || "",
            }),
          });
          if (!ar.ok) throw new Error(await errText(ar));
        } catch (e: unknown) {
          failed += 1;
          if (!firstFail) firstFail = e instanceof Error ? e.message : String(e);
        }
        setProgress((p) => ({ ...p, done: p.done + 1 }));
      }

      if (failed === 0) {
        toast.success(
          ot("observe.inbox.caseCreatedToast", "Case created: {id} ({n} docs attached)", {
            id: caseId,
            n: items.length,
          }),
        );
        setLastCreated({ caseId, n: items.length });
        setChecked(new Set());
        setCaseTitle("");
        setCaseQuestion("");
        setTick((x) => x + 1);
        // 验收标准：建案成功必须可感知且可继续——直接跳转（后退可回 Inbox，来源不丢）
        router.push(`/cases/${caseId}`);
        return;
      }
      toast.error(
        `${ot("observe.inbox.casePartialToast", "Case created, but {failed} attach failed", { failed })}${firstFail ? ` — ${firstFail}` : ""}`,
      );
      if (previewUsed > 0) {
        toast.info(
          ot("observe.inbox.previewFallback", "{n} article(s) attached with preview body (full text unavailable)", {
            n: previewUsed,
          }),
        );
      }
      setLastCreated({ caseId, n: items.length - failed });
      setChecked(new Set());
      setCaseTitle("");
      setCaseQuestion("");
      setTick((x) => x + 1);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  };

  const rel = (iso: string): string => {
    const p = relParts(iso);
    return p ? ot(`observe.rel.${p.unit}`, `{v}${p.unit}`, { v: p.value }) : iso.slice(0, 10);
  };

  return (
    <div className="space-y-4 pb-24">
      {lastCreated ? (
        <div className="flex flex-wrap items-center gap-2 rounded-[12px] border border-green-600/30 bg-green-100 px-3 py-2 text-[13px] text-green-800 dark:bg-green-500/10 dark:text-green-300">
          ✓ {ot("observe.inbox.caseCreatedBanner", "Research Case created ({n} docs attached)", { n: lastCreated.n })}
          <a
            className="underline underline-offset-2"
            href={`/cases/${encodeURIComponent(lastCreated.caseId)}`}
          >
            {ot("observe.inbox.openCase", "Open Case →")}
          </a>
          <button
            type="button"
            aria-label="×"
            className="ml-auto opacity-60 hover:opacity-100"
            onClick={() => setLastCreated(null)}
          >
            ×
          </button>
        </div>
      ) : null}

      {/* 信源多选 chips（与左栏目录树同一状态） */}
      <div>
        <p className="mb-1 text-xs text-muted-foreground">{ot("observe.inbox.sources", "Sources")}</p>
        {sourcesErr ? (
          <p className="text-xs text-red-600">{sourcesErr}</p>
        ) : (
          <div className="flex max-h-24 flex-wrap gap-1 overflow-y-auto pr-1">
            {sources.length === 0 ? (
              <Skeleton className="h-6 w-40 rounded-[6px]" />
            ) : (
              sources.map((s) => {
                const on = selSources.includes(s.source_id);
                return (
                  <button
                    key={s.source_id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => handlers.onToggleSource(s.source_id)}
                    className={`rounded-[6px] border px-2 py-0.5 text-xs transition-colors ${
                      on ? "bg-foreground text-background" : "hover:bg-muted/60"
                    }`}
                    title={`n_7d=${s.n_7d}`}
                  >
                    {s.source_id}
                  </button>
                );
              })
            )}
          </div>
        )}
      </div>

      {/* 高频过滤：关键词 + 元素 + cased toggle + 图例 */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={qInput}
          onChange={(e) => handlers.onQInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handlers.onQCommit();
          }}
          onBlur={() => handlers.onQCommit()}
          placeholder={ot("observe.inbox.searchPh", "keyword in title + body…")}
          className="h-8 w-64 rounded-[6px] border bg-card px-2 text-[13px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
          aria-label={ot("observe.inbox.searchPh", "keyword in title + body…")}
        />
        <select
          value={element}
          onChange={(e) => handlers.onElementChange(e.target.value)}
          className="h-8 rounded-[6px] border bg-card px-1.5 text-[13px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
          aria-label={ot("observe.inbox.element", "18-element filter")}
        >
          <option value="">{ot("observe.inbox.elementAll", "element: all")}</option>
          {ELEMENT_KEYS.map((k) => (
            <option key={k} value={k}>
              {t(`element.${k}`)}
            </option>
          ))}
        </select>
        {element ? (
          <input
            type="text"
            value={valueInput}
            onChange={(e) => handlers.onValueInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handlers.onValueCommit();
            }}
            onBlur={() => handlers.onValueCommit()}
            placeholder={ot("observe.inbox.valuePh", "element value…")}
            className="h-8 w-44 rounded-[6px] border bg-card px-2 text-[13px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
            aria-label={ot("observe.inbox.valuePh", "element value…")}
          />
        ) : null}
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={includeCased}
            onChange={() => handlers.onToggleIncludeCased()}
            className="accent-foreground"
          />
          {ot("observe.inbox.showCased", "show cased")}
        </label>
        <span className="ml-auto flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <StatusDot tone="ok" />
            {ot("observe.inbox.legendCased", "cased")}
          </span>
          <span className="flex items-center gap-1">
            <StatusDot tone="info" />
            {ot("observe.inbox.legendDissected", "dissected")}
          </span>
          <span className="flex items-center gap-1">
            <StatusDot tone="gap" />
            {ot("observe.inbox.legendRaw", "inbox")}
          </span>
        </span>
      </div>

      {err ? (
        <p className="flex items-center gap-2 text-[13px] text-red-600">
          {err}
          <button
            type="button"
            onClick={() => setTick((x) => x + 1)}
            className="rounded-[6px] border px-2 py-0.5 text-xs hover:bg-muted"
          >
            {ot("observe.retry", "Retry")}
          </button>
        </p>
      ) : null}

      {/* 结果表：标题行 + 元数据行（44px 行高），时间右对齐，点击展开预览 */}
      {stale ? (
        <ul className="space-y-1" aria-busy="true">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
            <li key={i}>
              <Skeleton className="h-[44px] rounded-[6px]" />
            </li>
          ))}
        </ul>
      ) : visibleRows.length === 0 ? (
        <div className="rounded-[12px] border border-dashed p-6 text-center text-[13px] text-muted-foreground">
          {hasFilter ? (
            <>
              <p>{ot("observe.inbox.emptyFiltered", "No articles match the current filters.")}</p>
              <button
                type="button"
                onClick={() => handlers.onClearFilters()}
                className="mt-2 rounded-[6px] border px-3 py-1 text-xs transition-colors hover:bg-muted"
              >
                {ot("observe.inbox.clearFilters", "Clear filters")}
              </button>
            </>
          ) : (
            <>
              <p>
                {ot(
                  "observe.inbox.emptyHonest",
                  "Inbox is empty for this window — no collected articles match (never fabricated).",
                )}
              </p>
              <p className="mt-1 text-xs">
                {ot(
                  "observe.inbox.emptyNext",
                  "Next: widen the window in the left rail, or add sources in Sources hub.",
                )}
              </p>
              <a
                className="mt-2 inline-block rounded-[6px] border px-3 py-1 text-xs transition-colors hover:bg-muted"
                href="/sources"
              >
                {ot("observe.inbox.goSources", "Go to Sources →")}
              </a>
            </>
          )}
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={allVisibleChecked}
                onChange={() =>
                  setChecked((prev) => {
                    if (allVisibleChecked) {
                      const next = new Set(prev);
                      for (const r of visibleRows) next.delete(r.item_key);
                      return next;
                    }
                    const next = new Set(prev);
                    for (const r of visibleRows) next.add(r.item_key);
                    return next;
                  })
                }
                aria-label={ot("observe.inbox.selectAll", "select all visible")}
                className="accent-foreground"
              />
              {ot("observe.inbox.count", "{shown} shown · {total} total", {
                shown: visibleRows.length,
                total: wrap === null ? 0 : wrap.n,
              })}
            </span>
            {hiddenCased > 0 ? (
              <span>{ot("observe.inbox.hiddenCased", "{n} cased hidden", { n: hiddenCased })}</span>
            ) : null}
          </div>
          <ul className="divide-y rounded-[12px] border">
            {visibleRows.map((r) => {
              const open = expanded === r.item_key;
              return (
                <li key={r.item_key}>
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => setExpanded(open ? null : r.item_key)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setExpanded(open ? null : r.item_key);
                      }
                    }}
                    className="flex min-h-[44px] cursor-pointer items-center gap-2 px-2 py-1.5 transition-colors hover:bg-muted/50"
                  >
                    <input
                      type="checkbox"
                      checked={checked.has(r.item_key)}
                      onClick={(e) => e.stopPropagation()}
                      onChange={() => toggleCheck(r.item_key)}
                      aria-label={ot("observe.inbox.selectRow", "select {title}", { title: r.title })}
                      className="accent-foreground"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold leading-5" title={r.title}>
                        {r.title}
                      </p>
                      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <span className="max-w-40 truncate">{r.source_id}</span>
                        <span aria-hidden>·</span>
                        {r.language ? (
                          <span className="rounded-[6px] bg-muted px-1 uppercase">{r.language}</span>
                        ) : (
                          <span title={ot("observe.inbox.langUnknown", "language unannotated")}>—</span>
                        )}
                        <span aria-hidden>·</span>
                        {r.cased ? (
                          <span className="flex items-center gap-1" title={ot("observe.inbox.legendCased", "cased")}>
                            <StatusDot tone="ok" />
                          </span>
                        ) : null}
                        {r.dissected ? (
                          <span className="flex items-center gap-1" title={ot("observe.inbox.legendDissected", "dissected")}>
                            <StatusDot tone="info" />
                          </span>
                        ) : null}
                        {!r.cased && !r.dissected ? <StatusDot tone="gap" /> : null}
                      </p>
                    </div>
                    <time className="shrink-0 text-xs tabular-nums text-muted-foreground" dateTime={r.published_at}>
                      {rel(r.published_at)}
                    </time>
                    <span aria-hidden className="w-4 shrink-0 text-center text-xs text-muted-foreground">
                      {open ? "▲" : "▼"}
                    </span>
                  </div>
                  {open ? (
                    <div className="space-y-1.5 bg-muted/30 px-9 py-2 text-[13px]">
                      <p className="line-clamp-4 whitespace-pre-wrap text-muted-foreground">{stripHtml(r.body_preview)}</p>
                      <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <span>{r.published_at.slice(0, 16).replace("T", " ")} UTC</span>
                        {r.url ? (
                          <a
                            href={r.url}
                            target="_blank"
                            rel="noreferrer"
                            className="underline underline-offset-2 hover:text-foreground"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {ot("observe.inbox.openOriginal", "open original ↗")}
                          </a>
                        ) : null}
                      </p>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {/* 批量操作浮动条：多选后底部升起 */}
      {checkedRows.length > 0 ? (
        <div
          role="dialog"
          aria-label={ot("observe.inbox.batchBar", "batch actions")}
          className="fixed bottom-6 left-1/2 z-40 w-[min(44rem,92vw)] -translate-x-1/2 rounded-[12px] border bg-card p-3 shadow-lg"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-[6px] bg-foreground px-2 py-0.5 text-xs font-semibold text-background">
              {ot("observe.inbox.selected", "{n} selected", { n: checkedRows.length })}
            </span>
            <input
              type="text"
              value={caseTitle}
              onChange={(e) => setCaseTitle(e.target.value)}
              placeholder={ot("observe.inbox.caseTitlePh", "Case title (optional)")}
              className="h-8 w-44 rounded-[6px] border bg-background px-2 text-[13px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
              aria-label={ot("observe.inbox.caseTitlePh", "Case title (optional)")}
            />
            <input
              type="text"
              value={caseQuestion}
              onChange={(e) => setCaseQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !creating) void createCase();
              }}
              placeholder={ot("observe.inbox.caseQuestionPh", "research question (required)")}
              className="h-8 min-w-48 flex-1 rounded-[6px] border bg-background px-2 text-[13px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
              aria-label={ot("observe.inbox.caseQuestionPh", "research question (required)")}
            />
            <button
              type="button"
              disabled={creating}
              onClick={() => void createCase()}
              className="h-8 shrink-0 rounded-[6px] bg-foreground px-3 text-[13px] font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {creating
                ? ot("observe.inbox.attaching", "attaching {done}/{total}…", progress)
                : ot("observe.inbox.createCase", "Create research Case")}
            </button>
            <button
              type="button"
              disabled={creating}
              onClick={() => setChecked(new Set())}
              className="h-8 shrink-0 rounded-[6px] border px-2 text-[13px] text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
            >
              {ot("observe.inbox.cancel", "Cancel")}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
