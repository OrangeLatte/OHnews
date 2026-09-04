"use client";

/**
 * CASES 空间：研究案例列表（富行）+ 状态 facet（计数徽标）+ 搜索 + 排序 +
 * j/k/Enter 键盘流 + 新建弹窗（title/question 双必填）+ 关闭（HITL）。
 * 数据：GET /api/cases?include_closed=1 一次取全量，facet/搜索/排序全部客户端计算，
 * 计数徽标与列表永远同源（无筛选-列表不一致问题）。
 */

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { HelpIcon } from "@/components/help/help-icon";
import { objectApi, type CaseRow } from "@/lib/object-api";
import { useLocale, useT } from "@/lib/i18n/use-t";
import { Skeleton, toast } from "@/components/ui/toast";
import { track } from "@/lib/track";
import { CaseCreateDialog } from "@/components/cases/case-create-dialog";
import { CaseRowItem, type CaseListItem } from "@/components/cases/case-row";
import { useTr } from "@/components/cases/cases-ui";

type StatusFilter = "" | "active" | "candidate" | "needs_attention" | "closed";
type SortKey = "updated" | "created" | "title";

const STATUS_FILTERS: StatusFilter[] = ["", "active", "candidate", "needs_attention", "closed"];

export default function CasesPage() {
  const t = useT();
  const tr = useTr();
  const { locale } = useLocale();
  const zh = locale.startsWith("zh");
  const router = useRouter();

  const [rows, setRows] = useState<CaseListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<StatusFilter>("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<SortKey>("updated");
  const [sel, setSel] = useState(0);
  const [creating, setCreating] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    let alive = true;
    objectApi
      .cases(undefined, true)
      .then((r: CaseRow[]) => {
        if (!alive) return;
        setRows(r as CaseListItem[]);
        setErr("");
      })
      .catch(() => {
        if (alive) setErr(t("case.loadFailed"));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [t]);

  const searched = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((c) =>
      `${c.title ?? ""} ${c.question} ${c.case_id}`.toLowerCase().includes(needle),
    );
  }, [rows, q]);

  const counts = useMemo(() => {
    const c: Record<StatusFilter, number> = { "": searched.length, active: 0, candidate: 0, needs_attention: 0, closed: 0 };
    for (const row of searched) {
      if (row.status in c) c[row.status as Exclude<StatusFilter, "">] += 1;
    }
    return c;
  }, [searched]);

  const filtered = useMemo(() => {
    const list = tab ? searched.filter((c) => c.status === tab) : searched;
    const sorted = [...list];
    if (sort === "title") {
      sorted.sort((a, b) =>
        (a.title || a.question).localeCompare(b.title || b.question, zh ? "zh" : "en"),
      );
    } else {
      const key = sort === "updated" ? "updated_at" : "created_at";
      sorted.sort((a, b) => Date.parse(b[key]) - Date.parse(a[key]));
    }
    return sorted;
  }, [searched, tab, sort, zh]);

  const selIdx = filtered.length === 0 ? -1 : Math.min(sel, filtered.length - 1);

  useEffect(() => {
    rowRefs.current[selIdx]?.scrollIntoView({ block: "nearest" });
  }, [selIdx]);

  const openCase = (c: CaseListItem): void => {
    router.push(`/cases/${encodeURIComponent(c.case_id)}`);
  };

  const closeCase = (c: CaseListItem): void => {
    if (!window.confirm(t("case.confirmClose", { id: c.case_id }))) return;
    objectApi
      .closeCase(c.case_id)
      .then(() => {
        track("case_closed", { objectId: c.case_id, fromPage: "/cases" });
        toast.success(t("case.closeOk"));
        setRows((prev) =>
          prev.map((x) => (x.case_id === c.case_id ? { ...x, status: "closed" } : x)),
        );
      })
      .catch(() => {
        toast.error(t("case.loadFailed"));
      });
  };

  const clearFilters = (): void => {
    setTab("");
    setQ("");
  };

  const hasFilters = tab !== "" || q.trim() !== "";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">{t("nav.cases")}</h1>
          <HelpIcon helpKey="state.empty" />
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden text-xs text-muted-foreground sm:inline">
            {tr("cases.selectedHint", "j/k move · Enter open")}
          </span>
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#2563eb]/90"
          >
            {tr("cases.new", "New research case")}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={tr("cases.search", "Search title or question…")}
          aria-label={tr("cases.search", "Search title or question…")}
          className="w-64 rounded-lg border px-3 py-1.5 text-sm outline-none focus:border-[#2563eb] focus:ring-2 focus:ring-[#2563eb]/20"
        />
        <div role="tablist" aria-label={t("case.filterCases")} className="flex flex-wrap gap-1">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f || "all"}
              type="button"
              role="tab"
              aria-selected={tab === f}
              onClick={() => setTab(f)}
              className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition-colors ${
                tab === f
                  ? "border-[#2563eb] bg-[#2563eb]/10 font-medium text-[#2563eb]"
                  : "border-black/10 hover:bg-muted"
              }`}
            >
              {f === ""
                ? tr("cases.tabAll", "All")
                : f === "active"
                  ? tr("cases.tabActive", "Active")
                  : f === "candidate"
                    ? tr("cases.tabCandidate", "Candidate")
                    : f === "needs_attention"
                      ? tr("cases.tabNeedsAttention", "Needs attention")
                      : tr("cases.tabClosed", "Closed")}
              <span
                className={`rounded-full px-1.5 text-[10px] ${
                  tab === f ? "bg-[#2563eb] text-white" : "bg-muted text-muted-foreground"
                }`}
              >
                {counts[f]}
              </span>
            </button>
          ))}
        </div>
        <label className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
          {tr("cases.sort", "Sort")}
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            className="rounded-md border px-2 py-1 text-xs"
            aria-label={tr("cases.sort", "Sort")}
          >
            <option value="updated">{tr("cases.sortUpdated", "Last updated")}</option>
            <option value="created">{tr("cases.sortCreated", "Created")}</option>
            <option value="title">{tr("cases.sortTitle", "Title")}</option>
          </select>
        </label>
      </div>

      {err ? (
        <p className="text-sm text-[#dc2626]">{err}</p>
      ) : loading ? (
        <div className="space-y-2" aria-label={t("case.loading")}>
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-xl" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        rows.length === 0 ? (
          <div className="rounded-xl border border-dashed p-8 text-center">
            <p className="text-sm font-medium">{t("case.empty")}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {tr(
                "cases.emptyHint",
                "No research cases yet. Discover articles in the OBSERVE inbox, then start a case from a change candidate.",
              )}
            </p>
            <Link
              href="/observe"
              className="mt-4 inline-block rounded-lg border px-3 py-1.5 text-sm hover:bg-muted"
            >
              {tr("cases.goObserve", "Go to OBSERVE")}
            </Link>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed p-8 text-center">
            <p className="text-sm text-muted-foreground">
              {tr("cases.filteredEmpty", "No cases match the current filters.")}
            </p>
            <button
              type="button"
              onClick={clearFilters}
              className="mt-3 rounded-lg border px-3 py-1.5 text-sm hover:bg-muted"
            >
              {tr("cases.clearFilters", "Clear filters")}
            </button>
          </div>
        )
      ) : (
        <div
          ref={listRef}
          role="listbox"
          aria-label={t("nav.cases")}
          tabIndex={0}
          onKeyDown={(e) => {
            if (creating) return;
            if (e.key === "j" || e.key === "k") {
              e.preventDefault();
              setSel((prev) => {
                const cur = filtered.length === 0 ? -1 : Math.min(prev, filtered.length - 1);
                if (cur < 0) return 0;
                const next = e.key === "j" ? Math.min(cur + 1, filtered.length - 1) : Math.max(cur - 1, 0);
                return next;
              });
            } else if (e.key === "Enter") {
              e.preventDefault();
              const c = filtered[selIdx];
              if (c) openCase(c);
            }
          }}
          className="space-y-1 outline-none"
        >
          {filtered.map((c, i) => (
            <CaseRowItem
              key={c.case_id}
              c={c}
              selected={i === selIdx}
              zh={zh}
              openLabel={tr("cases.openCase", "Open")}
              closeLabel={t("case.closeCase")}
              onOpen={openCase}
              onClose={closeCase}
              rowRef={(el) => {
                rowRefs.current[i] = el;
              }}
            />
          ))}
        </div>
      )}

      {!err && !loading && filtered.length > 0 ? (
        <p className="text-xs text-muted-foreground">
          {tr("cases.showCount", "{n} of {total} cases", { n: filtered.length, total: rows.length })}
          {hasFilters ? (
            <>
              {" · "}
              <button
                type="button"
                onClick={clearFilters}
                className="underline hover:text-foreground"
              >
                {tr("cases.clearFiltersAction", "Clear filters")}
              </button>
            </>
          ) : null}
        </p>
      ) : null}

      {creating ? (
        <CaseCreateDialog
          onClose={() => setCreating(false)}
          onCreated={(c) => {
            setCreating(false);
            router.push(`/cases/${encodeURIComponent(c.case_id)}`);
          }}
        />
      ) : null}
    </div>
  );
}
