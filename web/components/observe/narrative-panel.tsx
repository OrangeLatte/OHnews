"use client";

/**
 * Narrative Lens：河流/冲积图（基线态 → 当前态框架份额流带，纯 SVG）
 * + 明细迁移条（保留精确数字）。基线无标注时诚实降级为单柱，不插值。
 */

import { MigrationBar } from "@/components/observe/charts";
import { isLowShare, type ChangeSelection } from "@/components/observe/change-drawer";
import { TimeChart, type TSLane, type TSSeries, type TSPoint } from "@/components/viz/TimeChart";
import { useOt } from "@/components/observe/i18n-bridge";
import { Skeleton } from "@/components/ui/toast";
import type { Landscape, NarrativeStream, TimeSeriesPayload } from "@/lib/landscape-api";
import { useT } from "@/lib/i18n/use-t";

const FRAME_HEX: Record<string, string> = {
  gain: "#6f8f6a",
  loss: "#b08d3f",
  conflict: "#b3543f",
  human_interest: "#a05a78",
  responsibility: "#5e83a8",
  other: "#6b7280",
};
const FALLBACK = ["#5e83a8", "#6f8f6a", "#b08d3f", "#8a6fae", "#5e9c94", "#a05a78", "#6b7280"];
const frameColor = (frame: string, i: number): string =>
  FRAME_HEX[frame] ?? FALLBACK[i % FALLBACK.length];


/**
 * timeseries.frame_day → "框架份额时间带"（stacked_band，yDomain [0,1]）：
 * 色板与下方冲积图 frameColor 同源（跨图同框架同色）；低样本日=当日各框架 n 之和<5。
 * 缺数据返回 null（诚实不渲染）。
 */
function buildFrameLane(
  ts: TimeSeriesPayload,
  streams: NarrativeStream[],
  title: string,
  unit: string,
  emptyHint: string,
): TSLane | null {
  const rows = ts.frame_day ?? [];
  if (rows.length === 0) return null;
  const labelOf = new Map(streams.map((n) => [n.frame, n.label || n.frame]));
  const perFrame = new Map<string, Map<string, TSPoint>>();
  const dayN = new Map<string, number>();
  for (const r of rows) {
    const m = perFrame.get(r.frame) ?? new Map<string, TSPoint>();
    m.set(r.day, { day: r.day, value: r.share });
    perFrame.set(r.frame, m);
    dayN.set(r.day, (dayN.get(r.day) ?? 0) + r.n);
  }
  // 按窗口总份额降序 → 堆叠自下而上按序稳定
  const order = [...perFrame.entries()]
    .map(([frame, m]) => ({
      frame,
      total: [...m.values()].reduce((s, p) => s + (p.value ?? 0), 0),
      m,
    }))
    .sort((a, b) => b.total - a.total);
  const series: TSSeries[] = order.map(({ frame, m }, i) => ({
    id: frame,
    label: labelOf.get(frame) ?? frame,
    points: [...m.values()],
    color: frameColor(frame, i),
  }));
  return {
    id: "narrative-frame-day",
    title,
    kind: "stacked_band",
    series,
    yDomain: [0, 1],
    unit,
    lowSampleDays: [...dayN].filter(([, n]) => n < 5).map(([d]) => d).sort(),
    emptyHint,
  };
}

export function NarrativePanel({
  landscape,
  onOpenNarrative,
}: {
  landscape: Landscape | null;
  /** 流带/迁移条点击 → 统一 Change Drawer（P1 图表联动）。 */
  onOpenNarrative: (sel: ChangeSelection) => void;
}) {
  const t = useT();
  const ot = useOt();
  if (!landscape) {
    return (
      <div className="space-y-3" aria-busy="true">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-12 rounded-[12px]" />
        ))}
      </div>
    );
  }
  if (landscape.narrative_streams.length === 0) {
    return (
      <p className="rounded-[12px] border p-3 text-[13px] text-muted-foreground">{t("observe.noChanges")}</p>
    );
  }
  const baseTotal = landscape.narrative_streams.reduce((s, n) => s + n.share_baseline, 0);
  // 框架份额时间带：timeseries 缺失（后端未部署）→ 不渲染新区块（诚实降级）
  const ts = landscape.timeseries;
  const frameLane = ts
    ? buildFrameLane(
        ts,
        landscape.narrative_streams,
        ot("viz.narrative.band", "Frame share by day"),
        ot("viz.unit.share", "share"),
        ot("viz.narrative.empty", "No per-day frame shares in this payload — shown honestly empty."),
      )
    : null;
  return (
    <div className="space-y-4">
      {frameLane ? (
        <section aria-label={frameLane.title}>
          <TimeChart lanes={[frameLane]} days={ts?.days ?? 30} heightPerLane={120} />
        </section>
      ) : null}
      
      {baseTotal <= 0.005 ? (
        <p className="rounded-[12px] border border-dashed p-2 text-xs text-muted-foreground">
          {ot(
            "observe.narrative.noBaseline",
            "no narrative annotation in the baseline window — single-state view shown honestly, no interpolation.",
          )}
        </p>
      ) : null}
      <ul className="space-y-3">
        {landscape.narrative_streams.map((n) => (
          <MigrationBar
            key={n.frame}
            label={n.label || n.frame}
            shareBaseline={n.share_baseline}
            shareCurrent={n.share_current}
            onClick={() => onOpenNarrative({ kind: "narrative", stream: n })}
            lowSampleTitle={
              isLowShare(n.share_baseline)
                ? ot("observe.lowSample", "Low sample (n={n}); growth may be distorted", { n: n.n_baseline })
                : undefined
            }
          />
        ))}
      </ul>
    </div>
  );
}
