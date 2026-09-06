"use client";

/**
 * WATCH · 信源管理工作区（自 app/sources/page.tsx 原样抽入）：
 * 顶部统计条（总数/启用/7d 活跃/stale）+ 双区布局
 * （左 facet 树 tier/kind/language/健康/启用，右可排序结果表，行展开 + 立即采集）。
 * 数据：GET /api/sources 全量一次取回，facet 计数与表格同源客户端计算；
 * 运行中心与扩展向导为独立区块（24px 间距）。
 */

import { useEffect, useMemo, useState } from "react";
import { HelpIcon } from "@/components/help/help-icon";
import {
  fetchSources,
  type SourceRow,
} from "@/lib/landscape-api";
import { useT, useLocale } from "@/lib/i18n/use-t";
import { Skeleton, toast } from "@/components/ui/toast";
import { SourceFacets, EMPTY_FACETS, sourceMatches, type FacetGroup, type Facets } from "@/components/sources/source-facets";
import { SourceTable, type SortDir, type SortKey } from "@/components/sources/source-table";
import { RunCenter } from "@/components/sources/run-center";
import { ExtendWizard } from "@/components/sources/extend-wizard";
import { healthOf, useTr } from "@/components/sources/sources-ui";
import { TIER_HINT_KEYS, TIER_LEGEND } from "@/lib/sources-meta";

async function triggerRefresh(sourceId: string): Promise<void> {
  const r = await fetch(`/api/sources/${encodeURIComponent(sourceId)}/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!r.ok) throw new Error(`refresh: HTTP ${r.status}`);
}

export function SourcesWorkspace() {
  const t = useT();
  const tr = useTr();
  const { locale } = useLocale();
  const zh = locale.startsWith("zh");

  const [rows, setRows] = useState<SourceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [facets, setFacets] = useState<Facets>(EMPTY_FACETS);
  const [sortKey, setSortKey] = useState<SortKey>("n_7d");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [refreshingId, setRefreshingId] = useState("");
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let alive = true;
    fetchSources({})
      .then((res) => {
        if (alive) {
          setRows(res.sources);
          setErr("");
        }
      })
      .catch((e: unknown) => {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [reloadToken]);

  const reload = (): void => {
    setLoading(true);
    setReloadToken((n) => n + 1);
  };

  const filtered = useMemo(
    () => rows.filter((s) => sourceMatches(s, facets, q)),
    [rows, facets, q],
  );

  const sorted = useMemo(() => {
    const list = [...filtered];
    const dir = sortDir === "asc" ? 1 : -1;
    list.sort((a, b) => {
      switch (sortKey) {
        case "n_7d":
          return (a.n_7d - b.n_7d) * dir;
        case "n_30d":
          return (a.n_30d - b.n_30d) * dir;
        case "last_seen":
          return (a.last_seen ?? "").localeCompare(b.last_seen ?? "") * dir;
        default:
          return String(a[sortKey]).localeCompare(String(b[sortKey])) * dir;
      }
    });
    return list;
  }, [filtered, sortKey, sortDir]);

  const stats = useMemo(() => {
    let enabled = 0;
    let active7 = 0;
    let stale = 0;
    for (const s of rows) {
      if (s.enabled) enabled += 1;
      if (s.n_7d > 0) active7 += 1;
      if (healthOf(s) === "red") stale += 1;
    }
    return { total: rows.length, enabled, active7, stale };
  }, [rows]);

  const onFacet = (group: FacetGroup, value: string): void => {
    setFacets((prev) => ({ ...prev, [group]: value }));
  };

  const onSort = (key: SortKey): void => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "n_7d" || key === "n_30d" || key === "last_seen" ? "desc" : "asc");
    }
  };

  const onRefreshSource = (s: SourceRow): void => {
    if (!window.confirm(tr("sources.refreshConfirm", "Trigger collection for {id} now?", { id: s.source_id }))) {
      return;
    }
    setRefreshingId(s.source_id);
    triggerRefresh(s.source_id)
      .then(() => {
        toast.success(tr("sources.refreshOk", "Collection triggered"));
      })
      .catch(() => {
        toast.error(tr("sources.refreshFailed", "Trigger failed"));
      })
      .finally(() => {
        setRefreshingId("");
      });
  };

  const hasFilters =
    q.trim() !== "" ||
    facets.tier !== "" ||
    facets.kind !== "" ||
    facets.language !== "" ||
    facets.health !== "" ||
    facets.enabled !== "";

  const clearAll = (): void => {
    setQ("");
    setFacets(EMPTY_FACETS);
  };

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">{t("nav.sources")}</h1>
          <HelpIcon helpKey="state.stale" />
        </div>

        <div className="flex flex-wrap gap-2" aria-label={tr("sources.statsBar", "Directory stats")}>
          <div className="min-w-32 flex-1 rounded-xl border p-3">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
              {tr("sources.statsTotal", "Total sources")}
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums">{stats.total}</p>
          </div>
          <div className="min-w-32 flex-1 rounded-xl border p-3">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
              {tr("sources.statsEnabled", "Enabled")}
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums text-[#16a34a]">{stats.enabled}</p>
          </div>
          <div className="min-w-32 flex-1 rounded-xl border p-3">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
              {tr("sources.statsActive7d", "Active (7d)")}
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums text-[#2563eb]">{stats.active7}</p>
          </div>
          <div className="min-w-32 flex-1 rounded-xl border p-3">
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
              {tr("sources.statsStale", "Stale")}
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums text-[#dc2626]">{stats.stale}</p>
          </div>
        </div>

        {err ? <p className="text-sm text-[#dc2626]">{err}</p> : null}

        {loading ? (
          <div className="space-y-2" aria-label={tr("sources.loading", "Loading…")}>
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-11 w-full rounded-lg" />
            ))}
          </div>
        ) : (
          <div className="grid items-start gap-6 lg:grid-cols-[240px_1fr]">
            <SourceFacets
              rows={rows}
              facets={facets}
              q={q}
              tr={tr}
              zh={zh}
              onFacet={onFacet}
              onClear={clearAll}
            />
            <div className="space-y-3">
              {/* tier 图例：L1-L4 语义说明（四色点 + 文案） */}
              <div
                className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground"
                aria-label={t("sources.tierLegend")}
              >
                {TIER_LEGEND.map(({ tier, dot }) => (
                  <span key={tier} className="inline-flex items-center gap-1.5">
                    <span aria-hidden className={`size-2 shrink-0 rounded-full ${dot}`} />
                    <span className="font-medium text-foreground/80">{tier}</span>
                    <span>{t(TIER_HINT_KEYS[tier])}</span>
                  </span>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder={t("sources.search")}
                  aria-label={t("sources.search")}
                  className="w-64 rounded-lg border px-3 py-1.5 text-sm outline-none focus:border-[#2563eb] focus:ring-2 focus:ring-[#2563eb]/20"
                />
                <span className="text-xs text-muted-foreground">
                  {tr("sources.resultCount", "{n} of {total} sources", {
                    n: sorted.length,
                    total: rows.length,
                  })}
                </span>
                {hasFilters ? (
                  <button
                    type="button"
                    onClick={clearAll}
                    className="text-xs text-[#2563eb] hover:underline"
                  >
                    {tr("sources.clearFacets", "Clear")}
                  </button>
                ) : null}
              </div>

              {sorted.length === 0 ? (
                rows.length === 0 ? (
                  <div className="rounded-xl border border-dashed p-8 text-center">
                    <p className="text-sm text-muted-foreground">{t("sources.empty")}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {tr(
                        "sources.emptyHint",
                        "No sources registered yet. Use the extend wizard below to add your first source.",
                      )}
                    </p>
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed p-8 text-center">
                    <p className="text-sm text-muted-foreground">
                      {tr("sources.filteredEmpty", "No sources match current filters.")}
                    </p>
                    <button
                      type="button"
                      onClick={clearAll}
                      className="mt-3 rounded-lg border px-3 py-1.5 text-sm hover:bg-muted"
                    >
                      {tr("sources.clearFacets", "Clear")}
                    </button>
                  </div>
                )
              ) : (
                <SourceTable
                  rows={sorted}
                  tr={tr}
                  zh={zh}
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onSort={onSort}
                  refreshingId={refreshingId}
                  onRefresh={onRefreshSource}
                />
              )}
            </div>
          </div>
        )}
      </div>

      <RunCenter sources={rows} reloadToken={reloadToken} />
      <ExtendWizard onRegistered={reload} />
    </div>
  );
}
