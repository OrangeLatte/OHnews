"use client";

/**
 * Flow Lens：sankey 式流入图（信源 → 基线/当前窗口，带宽 ∝ 文章量，sqrt 缩放）
 * + 逐源双条增量表（保留 delta 徽标）。纯 SVG，零第三方依赖。
 */

import { useOt } from "@/components/observe/i18n-bridge";
import { isLowSample, type ChangeSelection } from "@/components/observe/change-drawer";
import { DualBar } from "@/components/observe/charts";
import { TimeChart, type TSLane, type TSSeries, type TSPoint } from "@/components/viz/TimeChart";
import { Skeleton } from "@/components/ui/toast";
import type { Landscape, SourceStream, TimeSeriesPayload } from "@/lib/landscape-api";
import { useT } from "@/lib/i18n/use-t";

function windowLabel(w: { start: string; end: string; n_articles: number }): string {
  return `${w.start.slice(0, 10)} → ${w.end.slice(0, 10)} · ${w.n_articles}`;
}

/**
 * timeseries.source_day → "流入时间带"（stacked_band）：top8 信源 + 其余聚合"其他"，
 * value=当日文章数；低样本日（当日总量<5）由调用方口径计算。缺数据返回 null（诚实不渲染）。
 */
function buildFlowLane(
  ts: TimeSeriesPayload,
  streams: SourceStream[],
  title: string,
  unit: string,
  otherLabel: string,
  emptyHint: string,
): TSLane | null {
  const rows = ts.source_day ?? [];
  if (rows.length === 0) return null;
  const labelOf = new Map(streams.map((s) => [s.source_id, s.label]));
  const perSource = new Map<string, Map<string, number>>();
  const dayTotal = new Map<string, number>();
  for (const r of rows) {
    const m = perSource.get(r.source_id) ?? new Map<string, number>();
    m.set(r.day, (m.get(r.day) ?? 0) + r.n);
    perSource.set(r.source_id, m);
    dayTotal.set(r.day, (dayTotal.get(r.day) ?? 0) + r.n);
  }
  const sum = (m: Map<string, number>): number => [...m.values()].reduce((s, v) => s + v, 0);
  const order = [...perSource.entries()].sort((a, b) => sum(b[1]) - sum(a[1]));
  const toPoints = (m: Map<string, number>): TSPoint[] => [...m].map(([day, value]) => ({ day, value }));
  const series: TSSeries[] = order.slice(0, 8).map(([sid, m]) => ({
    id: sid,
    label: labelOf.get(sid) ?? sid,
    points: toPoints(m),
  }));
  const rest = order.slice(8);
  if (rest.length > 0) {
    const agg = new Map<string, number>();
    for (const [, m] of rest) {
      for (const [d, v] of m) agg.set(d, (agg.get(d) ?? 0) + v);
    }
    series.push({ id: "__other__", label: otherLabel, points: toPoints(agg) });
  }
  return {
    id: "flow-source-day",
    title,
    kind: "stacked_band",
    series,
    unit,
    lowSampleDays: [...dayTotal].filter(([, n]) => n < 5).map(([d]) => d).sort(),
    emptyHint,
  };
}
export function FlowPanel({
  landscape,
  onOpenSource,
}: {
  landscape: Landscape | null;
  /** 信源条/节点点击 → 统一 Change Drawer（P1 图表联动）。 */
  onOpenSource: (sel: ChangeSelection) => void;
}) {
  const t = useT();
  const ot = useOt();

  if (!landscape) {
    return (
      <div className="space-y-3" aria-busy="true">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-10 rounded-[12px]" />
        ))}
      </div>
    );
  }

  const streams = landscape.source_streams;
  const max = Math.max(...streams.map((s) => Math.max(s.n_baseline, s.n_current)), 1);
  const labelBaseline = ot("observe.flow.baseline", "baseline window");
  const labelCurrent = ot("observe.flow.current", "current window");
  // 流入时间带：timeseries 缺失（后端未部署）→ 不渲染新区块（诚实降级）
  const ts = landscape.timeseries;
  const flowLane = ts
    ? buildFlowLane(
        ts,
        streams,
        ot("viz.flow.band", "Source inflow by day"),
        ot("viz.unit.articles", "articles/day"),
        ot("viz.other", "others"),
        ot("viz.flow.empty", "No per-day source counts in this payload — shown honestly empty."),
      )
    : null;

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        {labelBaseline}: {windowLabel(landscape.baseline_window)} · {labelCurrent}:{" "}
        {windowLabel(landscape.current_window)}
      </p>
      {flowLane ? (
        <section aria-label={flowLane.title}>
          <TimeChart lanes={[flowLane]} days={ts?.days ?? 30} heightPerLane={120} />
        </section>
      ) : null}
      {streams.length > 0 ? (
        <>
          
          <ul className="space-y-3">
            {streams.map((s) => {
              const delta =
                s.n_baseline > 0 ? Math.round(((s.n_current - s.n_baseline) / s.n_baseline) * 100) : null;
              const low = isLowSample(s.n_baseline, s.n_current);
              const lowLabel = ot("observe.lowSample", "Low sample (n={n}); growth may be distorted", {
                n: Math.min(s.n_baseline, s.n_current),
              });
              return (
                <li key={s.source_id}>
                  <button
                    type="button"
                    onClick={() => onOpenSource({ kind: "source_stream", stream: s })}
                    className={`flex w-full items-center gap-3 rounded-[8px] px-2 py-1 text-left text-[13px] transition-colors hover:bg-muted/60 ${
                      low ? "border border-dashed border-amber-500/70 bg-amber-500/10" : ""
                    }`}
                    title={low ? `${s.label} · ${lowLabel}` : s.label}
                  >
                    <span className="w-44 shrink-0 truncate">
                      {s.label}{" "}
                      <span className="rounded-[6px] bg-muted px-1 text-[10px] uppercase text-muted-foreground">
                        {s.tier}
                      </span>
                    </span>
                    <DualBar
                      baseline={s.n_baseline}
                      current={s.n_current}
                      max={max}
                      labelBaseline="t-2w"
                      labelCurrent="t-1w"
                    />
                    {delta === null ? (
                      <span className="w-14 shrink-0 text-right text-xs text-muted-foreground" title={ot("observe.flow.noBaseline", "baseline is 0, delta undefined")}>
                        —
                      </span>
                    ) : (
                      <span
                        className={`w-14 shrink-0 rounded-[6px] px-1 text-right text-xs tabular-nums ${
                          delta > 0
                            ? "bg-green-100 text-green-700 dark:bg-green-500/10 dark:text-green-400"
                            : delta < 0
                              ? "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-400"
                              : "text-muted-foreground"
                        }`}
                      >
                        {delta > 0 ? "▲" : delta < 0 ? "▼" : "—"} {Math.abs(delta)}%
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      ) : (
        <p className="rounded-[12px] border p-3 text-[13px] text-muted-foreground">{t("observe.noChanges")}</p>
      )}
    </div>
  );
}
