"use client";

/**
 * Divergence Lens：NDI 棒棒糖图（轨道+杆+语义色头点）；点击实体仍下钻 Entities 时间线。
 * 色语义：低=绿 / 中=琥珀 / 高=冲突红（ndiTone）。
 */

import { useOt } from "@/components/observe/i18n-bridge";
import { ndiTone } from "@/components/observe/rel-time";
import { TimeChart, type TSLane, type TSSeries, type TSPoint } from "@/components/viz/TimeChart";
import { Skeleton } from "@/components/ui/toast";
import type { Landscape, NdiRankRow, TimeSeriesPayload } from "@/lib/landscape-api";

const TONE_HEX: Record<string, string> = {
  ok: "#6f8f6a",
  warn: "#b08d3f",
  conflict: "#b3543f",
  gap: "#6b7280",
};

const NDI_LANE_TOP_N = 8;

/**
 * timeseries.ndi_day → "NDI 时间线"（multiline，yDomain [0,1]）：
 * 按"最新 NDI"降序取 top8（与棒棒糖榜 top8 口径一致），首位（最新 NDI 最高）为 dominant；
 * 低样本日=当日各实体 n_sources 之和<5。缺数据返回 null（诚实不渲染）。
 */
function buildNdiLane(
  ts: TimeSeriesPayload,
  ndi: NdiRankRow[],
  title: string,
  emptyHint: string,
): TSLane | null {
  const rows = ts.ndi_day ?? [];
  if (rows.length === 0) return null;
  // 日历全集 = 窗口内全部有数据的日（source/frame/ndi 并集）：NDI 缺测日也占位（null 断线），
  // 保证横轴以日为维度连续呈现，绝不因 NDI 弃权日压缩 x 域。
  const calendar = new Set<string>();
  for (const r of ts.source_day ?? []) calendar.add(r.day);
  for (const r of ts.frame_day ?? []) calendar.add(r.day);
  for (const r of rows) calendar.add(r.day);
  const dayList = [...calendar].sort();
  const labelOf = new Map(ndi.map((r) => [r.entity, r.label ?? r.entity]));
  const perEntity = new Map<string, Map<string, { ndi: number; n: number }>>();
  const dayN = new Map<string, number>();
  for (const r of rows) {
    const m = perEntity.get(r.entity_id) ?? new Map<string, { ndi: number; n: number }>();
    m.set(r.day, { ndi: r.ndi, n: r.n_sources });
    perEntity.set(r.entity_id, m);
    dayN.set(r.day, (dayN.get(r.day) ?? 0) + r.n_sources);
  }
  // 最新读数 = 该实体最大 day 的 NDI（day 为 ISO 日期，字典序=时间序）
  const latestOf = (m: Map<string, { ndi: number; n: number }>): number => {
    let bestDay = "";
    let best = -Infinity;
    for (const [d, v] of m) {
      if (d > bestDay) {
        bestDay = d;
        best = v.ndi;
      }
    }
    return best;
  };
  const order = [...perEntity.entries()]
    .map(([eid, m]) => ({ eid, m, latest: latestOf(m) }))
    .sort((a, b) => b.latest - a.latest);
  const series: TSSeries[] = order.slice(0, NDI_LANE_TOP_N).map(({ eid, m }, i) => ({
    id: eid,
    label: labelOf.get(eid) ?? eid,
    points: dayList.map((day): TSPoint => {
      const v = m.get(day);
      return { day, value: v ? v.ndi : null };
    }),
    dominant: i === 0,
  }));
  return {
    id: "divergence-ndi-day",
    title,
    kind: "multiline",
    series,
    yDomain: [0, 1],
    unit: "NDI",
    lowSampleDays: [...dayN].filter(([, n]) => n < 5).map(([d]) => d).sort(),
    emptyHint,
  };
}

export function DivergencePanel({
  ndi,
  landscape,
  loading,
  warnings = 0,
  onOpenDrawer,
}: {
  ndi: NdiRankRow[];
  /** landscape 透传（供 timeseries.ndi_day 时间线）；缺省/后端未部署 → 不渲染时间区块。 */
  landscape?: Landscape | null;
  loading: boolean;
  /** 质量门弃权带条数（后端诚实弃权：样本不足/覆盖缺口），0 = 本窗口无弃权。 */
  warnings?: number;
  /** 棒棒糖实体行点击 → 统一 Change Drawer（P1 图表联动）。 */
  onOpenDrawer: (entity: string, label?: string, ndi?: number | null, nSources?: number | null) => void;
}) {
  const ot = useOt();
  if (loading) {
    return (
      <div className="space-y-3" aria-busy="true">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-7 rounded-[12px]" />
        ))}
      </div>
    );
  }
  if (ndi.length === 0) {
    return (
      <p className="rounded-[12px] border p-3 text-[13px] text-muted-foreground">
        {ot("observe.divergence.empty", "No NDI ranking in this window (abstained when sample is insufficient).")}
      </p>
    );
  }
  // NDI 时间线：timeseries 缺失（后端未部署）→ 不渲染新区块（诚实降级）
  const ts = landscape?.timeseries;
  // 弃权语义说明：NDI 仅在官方与市场双簇样本都达标时才可测（设计真源 §H）；
  // 其余日期系统弃权——横轴逐日呈现但曲线断线留白，不插值补造。
  const ndiOkDays = new Set((ts?.ndi_day ?? []).map((r) => r.day)).size;
  const calDays = new Set([
    ...(ts?.source_day ?? []).map((r) => r.day),
    ...(ts?.frame_day ?? []).map((r) => r.day),
  ]).size;
  const abstainNote =
    ts && calDays > 0
      ? `NDI 可测 ${ndiOkDays}/${calDays} 天——其余日期官方与市场双簇样本不足，系统弃权（不编造数值）。`
      : null;
  const ndiLane = ts
    ? buildNdiLane(
        ts,
        ndi,
        ot("viz.divergence.timeline", "Entity NDI timeline"),
        ot("viz.divergence.empty", "No per-day NDI readings in this payload — shown honestly empty."),
      )
    : null;
  return (
    <div className="space-y-2">
      {abstainNote && (
        <p className="mb-2 text-[11px] text-muted-foreground">{abstainNote}</p>
      )}
      {ndiLane ? (
        <section aria-label={ndiLane.title} className="mb-3">
          <TimeChart lanes={[ndiLane]} days={ts?.days ?? 30} heightPerLane={120} />
        </section>
      ) : null}
      <p
        className={`rounded-[10px] border px-3 py-1.5 text-[11px] ${
          warnings > 0 ? "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400" : "border-border text-muted-foreground"
        }`}
        title={ot(
          "observe.divergence.abstainTitle",
          "Abstention count = quality-gate warnings in this window (backend abstains honestly on insufficient sample / coverage gaps; it never fabricates readings).",
        )}
      >
        {ot("observe.divergence.abstainRate", "Abstentions")}: {warnings}
        {warnings > 0
          ? ` · ${ot("observe.divergence.abstainNote", "backend withheld readings for insufficient sample")}`
          : ` · ${ot("observe.divergence.abstainNone", "no abstention in this window")}`}
      </p>
      <ul className="space-y-1">
        {ndi.map((r) => {
          const tone = ndiTone(r.ndi);
          return (
            <li key={r.entity}>
              <button
                type="button"
                onClick={() => onOpenDrawer(r.entity, r.label, r.ndi, r.n_sources ?? r.n ?? null)}
                className="flex w-full items-center gap-2 rounded-[8px] px-2 py-1 text-left text-[13px] transition-colors hover:bg-muted/60"
                title={ot("observe.drawer.clickHint", "Click to open the change detail drawer")}
              >
                <span aria-hidden className="inline-block size-2 shrink-0 rounded-full" style={{ backgroundColor: TONE_HEX[tone] }} />
                <span className="min-w-0 flex-1 truncate">{r.label ?? r.entity}</span>
                <span className="shrink-0 text-xs tabular-nums font-semibold">{r.ndi.toFixed(2)}</span>
                <span
                  className="w-8 shrink-0 text-right text-[10px] text-muted-foreground"
                  title={ot("observe.divergence.nHint", "n = contributing sources for this entity's NDI reading; — means the payload omitted the count.")}
                >
                  n={r.n_sources ?? r.n ?? "—"}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="flex flex-wrap gap-3 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: TONE_HEX.ok }} />
          {ot("observe.tone.low", "low")}
        </span>
        <span className="flex items-center gap-1">
          <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: TONE_HEX.warn }} />
          {ot("observe.tone.mid", "moderate")}
        </span>
        <span className="flex items-center gap-1">
          <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: TONE_HEX.conflict }} />
          {ot("observe.tone.high", "high")}
        </span>
      </p>
    </div>
  );
}
