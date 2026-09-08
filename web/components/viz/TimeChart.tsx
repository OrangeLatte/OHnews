"use client";

/**
 * OH Viz v1 统一时间序列图表（TradingView Small Multiples 模式）。
 * 多 lane 共享同一 x 域（全部 series points 的 day 并集）；multiline=多线（主导层次），
 * stacked_band=自下而上堆叠带。纯 SVG+CSS 零依赖。
 * 诚实纪律：缺 day 的序列在该 x 处视为 null 断开（绝不插值）；stacked 当日总量为 0 的 day 整列缺口；
 * 低样本日（调用方计算传入）以琥珀三角标注；数据缺失一律如实留空，绝不补造。
 */

import { useId, useState } from "react";
import { useOt } from "@/components/observe/i18n-bridge";
import {
  AXIS_FONT_SIZE,
  GRID_DASH,
  GRID_STROKE,
  NEUTRAL_DASH,
  VIZ_SEMANTIC,
  seriesColor,
} from "@/components/viz/tokens";

export type TSPoint = { day: string; value: number | null };

export type TSSeries = {
  id: string;
  label: string;
  points: TSPoint[];
  color?: string;
  /** 主导序列：2.4px 实线 + 渐变面积 + 右端值徽标；其余 1.2px 淡化。 */
  dominant?: boolean;
};

export type TSLane = {
  id: string;
  title: string;
  kind: "stacked_band" | "multiline";
  series: TSSeries[];
  /** 固定值域（NDI/share 传 [0,1]）；缺省按数据自适应该 lane。 */
  yDomain?: [number, number];
  unit?: string;
  /** lane 全空时的诚实文案。 */
  emptyHint?: string;
  /** 低样本日集合（当日总量<5，调用方计算传入）：x 轴下琥珀小三角 + title。 */
  lowSampleDays?: string[];
};

export interface TimeChartProps {
  lanes: TSLane[];
  heightPerLane?: number;
  days: number;
}

// ---- 几何常量（viewBox 坐标；svg w-full h-auto 等比缩放，与 observe/* 面板一致） ----
const VB_W = 640;
const PAD_L = 34; // 左侧留给 y 轴刻度，防止数据覆盖轴标签
const PLOT_TOP = 6;
const X_AXIS_H = 16;

type LineGeom = {
  s: TSSeries;
  color: string;
  paths: string[];
  areaPath: string | null;
  last: [number, number] | null;
  singles: [number, number][];
};

type BandGeom = {
  s: TSSeries;
  color: string;
  fills: string[];
  edges: string[];
};

type Tick = { v: number; dashed: boolean };

type Prep = {
  lane: TSLane;
  maps: Map<string, Map<string, number | null>>;
  totals: Map<string, number> | null;
  empty: boolean;
  isFrac: boolean;
  yMin: number;
  yMax: number;
  ticks: Tick[];
  lines: LineGeom[] | null;
  bands: BandGeom[] | null;
  domLast: { y: number; value: number; color: string } | null;
};

/** Catmull-Rom → 三次贝塞尔平滑路径（仅段内平滑，视觉用；与 charts.tsx 同实现）。 */
function smoothSegments(pts: [number, number][]): string[] {
  const segs: string[] = [];
  let cur: [number, number][] = [];
  const flush = () => {
    if (cur.length >= 2) {
      const d: string[] = [`M ${cur[0][0].toFixed(2)} ${cur[0][1].toFixed(2)}`];
      for (let i = 0; i < cur.length - 1; i++) {
        const p0 = cur[i - 1] ?? cur[i];
        const p1 = cur[i];
        const p2 = cur[i + 1];
        const p3 = cur[i + 2] ?? p2;
        const c1x = p1[0] + (p2[0] - p0[0]) / 6;
        const c1y = p1[1] + (p2[1] - p0[1]) / 6;
        const c2x = p2[0] - (p3[0] - p1[0]) / 6;
        const c2y = p2[1] - (p3[1] - p1[1]) / 6;
        d.push(`C ${c1x.toFixed(2)} ${c1y.toFixed(2)} ${c2x.toFixed(2)} ${c2y.toFixed(2)} ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`);
      }
      segs.push(d.join(" "));
    } else if (cur.length === 1) {
      segs.push(`M ${cur[0][0].toFixed(2)} ${cur[0][1].toFixed(2)} L ${cur[0][0].toFixed(2)} ${cur[0][1].toFixed(2)}`);
    }
    cur = [];
  };
  pts.forEach((p) => cur.push(p));
  flush();
  return segs;
}

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

const fmtDay = (d: string): string => (d.length >= 10 ? d.slice(5, 10) : d);

function fmtTick(v: number): string {
  if (Number.isInteger(v)) return String(v);
  return Math.abs(v) < 1 ? v.toFixed(2) : v.toFixed(1);
}

function fmtVal(v: number, isFrac: boolean): string {
  return isFrac ? v.toFixed(2) : String(Math.round(v));
}

/** 自适应值域的 2-3 条刻度（step 取 1/2/5 × 10^k）。 */
function niceTicks(yMin: number, yMax: number): number[] {
  if (!Number.isFinite(yMin) || !Number.isFinite(yMax) || yMax <= yMin) return [];
  const rawStep = (yMax - yMin) / 2;
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const norm = rawStep / mag;
  const step = (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag;
  const out: number[] = [];
  for (let v = Math.ceil(yMin / step) * step; v <= yMax + step * 1e-6; v += step) {
    out.push(Number(v.toFixed(6)));
  }
  return out.slice(0, 3);
}

function ticksFor(yMin: number, yMax: number, fixedUnit01: boolean): Tick[] {
  // 固定 [0,1] 域：0.25/0.75 实线刻度 + 0.5 中性虚线（语义中线，不随数据缩放）
  if (fixedUnit01) {
    return [
      { v: 0.25, dashed: false },
      { v: 0.75, dashed: false },
      { v: 0.5, dashed: true },
    ];
  }
  let ticks = niceTicks(yMin, yMax).map((v) => ({ v, dashed: false }));
  if (ticks.length < 2) {
    ticks = [
      { v: yMin, dashed: false },
      { v: yMax, dashed: false },
    ];
  }
  return ticks;
}

/** points 对齐到共享 day 域：缺 day → null（诚实断开，绝不插值）。 */
function alignValues(points: TSPoint[], dayList: string[]): (number | null)[] {
  const m = new Map<string, number | null>();
  for (const p of points) m.set(p.day, p.value);
  return dayList.map((d) => (m.has(d) ? (m.get(d) ?? null) : null));
}

/** 值序列按 null 切段的连续 runs（坐标已映射到 viewBox）。 */
function lineRuns(
  vals: (number | null)[],
  xAt: (i: number) => number,
  yOf: (v: number) => number,
): [number, number][][] {
  const runs: [number, number][][] = [];
  let run: [number, number][] = [];
  vals.forEach((v, i) => {
    if (!isNum(v)) {
      if (run.length > 0) runs.push(run);
      run = [];
    } else {
      run.push([xAt(i), yOf(v)]);
    }
  });
  if (run.length > 0) runs.push(run);
  return runs;
}

function prepLane(lane: TSLane, dayList: string[], plotH: number, axisY: number): Prep {
  const nDays = dayList.length;
  const xAt = (i: number): number =>
      nDays <= 1 ? VB_W / 2 : PAD_L + (i / (nDays - 1)) * (VB_W - PAD_L - 6);

  const maps = new Map<string, Map<string, number | null>>();
  for (const s of lane.series) {
    const m = new Map<string, number | null>();
    for (const p of s.points) m.set(p.day, p.value);
    maps.set(s.id, m);
  }

  // 值域与空态判定
  let vmin = Infinity;
  let vmax = -Infinity;
  let totalMax = 0;
  const totals = new Map<string, number>();
  if (lane.kind === "stacked_band") {
    for (const d of dayList) {
      let t = 0;
      for (const s of lane.series) {
        const v = maps.get(s.id)?.get(d);
        if (isNum(v)) t += v;
      }
      totals.set(d, t);
      totalMax = Math.max(totalMax, t);
    }
  } else {
    for (const s of lane.series) {
      for (const p of s.points) {
        if (isNum(p.value)) {
          vmin = Math.min(vmin, p.value);
          vmax = Math.max(vmax, p.value);
        }
      }
    }
  }
  const empty =
    lane.series.length === 0 ||
    (lane.kind === "stacked_band" ? totalMax <= 0 : !Number.isFinite(vmax));

  const yMin = lane.yDomain ? lane.yDomain[0] : lane.kind === "stacked_band" ? 0 : Number.isFinite(vmin) ? Math.min(0, vmin) : 0;
  const yMaxRaw = lane.yDomain
    ? lane.yDomain[1]
    : lane.kind === "stacked_band"
      ? Math.max(totalMax, 1)
      : Number.isFinite(vmax)
        ? Math.max(vmax, yMin + 1)
        : 1;
  const yMax = yMaxRaw > yMin ? yMaxRaw : yMin + 1;
  const yOf = (v: number): number => PLOT_TOP + (1 - (v - yMin) / (yMax - yMin)) * plotH;
  const fixedUnit01 = lane.yDomain?.[0] === 0 && lane.yDomain?.[1] === 1;
  const ticks = ticksFor(yMin, yMax, fixedUnit01);
  const isFrac = yMax <= 1;

  // multiline：各序列 runs + 主导渐变面积（最后一段）+ 端点
  let lines: LineGeom[] | null = null;
  let domLast: Prep["domLast"] = null;
  if (lane.kind === "multiline" && !empty) {
    lines = lane.series.map((s) => {
      const color = s.color ?? seriesColor(lane.series.indexOf(s));
      const runs = lineRuns(alignValues(s.points, dayList), xAt, yOf);
      const lastRun = runs.at(-1);
      const last = lastRun?.at(-1) ?? null;
      const areaPath =
        s.dominant === true && last && lastRun && lastRun.length > 1
          ? `${smoothSegments(lastRun).join(" ")} L ${last[0].toFixed(2)} ${axisY.toFixed(2)} L ${lastRun[0][0].toFixed(2)} ${axisY.toFixed(2)} Z`
          : null;
      const lastVal = lastValueOf(s, dayList);
      if (s.dominant === true && last && isNum(lastVal)) {
        domLast = { y: last[1], value: lastVal, color };
      }
      return {
        s,
        color,
        paths: runs.flatMap(smoothSegments),
        areaPath,
        last,
        singles: runs.filter((r) => r.length === 1).map((r) => r[0]),
      };
    });
  }

  // stacked_band：总量>0 的连续 day 段内，自下而上逐序列带状路径（0 总量日整列缺口）
  let bands: BandGeom[] | null = null;
  if (lane.kind === "stacked_band" && !empty) {
    const active = dayList
      .map((d, i) => ({ d, i, t: totals.get(d) ?? 0 }))
      .filter((x) => x.t > 0);
    const runsOfDay: { a: number; b: number }[] = [];
    for (const x of active) {
      const tail = runsOfDay.at(-1);
      if (tail && tail.b === x.i - 1) tail.b = x.i;
      else runsOfDay.push({ a: x.i, b: x.i });
    }
    const zero = new Array<number>(nDays).fill(0);
    const cum: number[][] = [];
    let prev = zero;
    for (const s of lane.series) {
      const vals = alignValues(s.points, dayList);
      const next = vals.map((v, i) => prev[i] + (isNum(v) ? v : 0));
      cum.push(next);
      prev = next;
    }
    bands = lane.series.map((s, k) => {
      const color = s.color ?? seriesColor(k);
      const fills: string[] = [];
      const edges: string[] = [];
      for (const { a, b } of runsOfDay) {
        const top: string[] = [];
        for (let i = a; i <= b; i++) top.push(`${xAt(i).toFixed(2)} ${yOf(cum[k][i]).toFixed(2)}`);
        const bottom: string[] = [];
        for (let i = b; i >= a; i--) bottom.push(`${xAt(i).toFixed(2)} ${yOf(k > 0 ? cum[k - 1][i] : 0).toFixed(2)}`);
        fills.push(`M ${top.join(" L ")} L ${bottom.join(" L ")} Z`);
        edges.push(`M ${top.join(" L ")}`);
      }
      return { s, color, fills, edges };
    });
  }

  return { lane, maps, totals: lane.kind === "stacked_band" ? totals : null, empty, isFrac, yMin, yMax, ticks, lines, bands, domLast };
}

/** 主导序列在该共享 day 域上的最后一个非空值（值徽标）。 */
function lastValueOf(s: TSSeries, dayList: string[]): number | null {
  const m = new Map(s.points.map((p) => [p.day, p.value]));
  for (let i = dayList.length - 1; i >= 0; i--) {
    const v = m.get(dayList[i] as string);
    if (isNum(v)) return v;
  }
  return null;
}

export function TimeChart({ lanes, heightPerLane = 120, days }: TimeChartProps) {
  const ot = useOt();
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  // x 域 = 全部 lanes series points 的 day 并集（ISO day 字典序 = 时间序），各 lane 共享
  const seen = new Set<string>();
  for (const lane of lanes) {
    for (const s of lane.series) {
      for (const p of s.points) {
        if (p.day) seen.add(p.day);
      }
    }
  }
  const dayList = [...seen].sort();
  const nDays = dayList.length;

  const H = Math.max(heightPerLane, 64);
  const plotH = Math.max(H - PLOT_TOP - X_AXIS_H, 24);
  const axisY = PLOT_TOP + plotH;
  const xAt = (i: number): number =>
      nDays <= 1 ? VB_W / 2 : PAD_L + (i / (nDays - 1)) * (VB_W - PAD_L - 6);
  const gid = `viz${uid}`;

  const preps: Prep[] = lanes.map((lane) => prepLane(lane, dayList, plotH, axisY));
  const overallEmpty = lanes.length === 0 || nDays === 0;

  const onMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (nDays < 2) return;
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const frac = (e.clientX - rect.left) / rect.width;
    setHoverIdx(Math.max(0, Math.min(nDays - 1, Math.round(frac * (nDays - 1)))));
  };
  // 数据重拉后 day 域可能缩短：hover 索引按当前域钳制，避免 tooltip 越界
  const hi = hoverIdx === null ? null : Math.min(hoverIdx, nDays - 1);
  const hoverX =
    hi === null
      ? 0
      : 100 *
        (nDays <= 1
          ? 0.5
          : (PAD_L + (hi / (nDays - 1)) * (VB_W - PAD_L - 6)) / VB_W);
  const tipTx = hi === null ? "-50%" : hi === 0 ? "0%" : hi === nDays - 1 ? "-100%" : "-50%";

  // x 轴首/中/尾三个标签（去重：极短域时中/尾可能同位）
  // 逐日刻度（用户要求横轴以天为单位）；>20 天时隔天显示防拥挤
  const xLabelIdx =
    nDays > 20
      ? [...Array(nDays).keys()].filter((i) => i % 2 === 0 || i === nDays - 1)
      : [...Array(nDays).keys()];

  if (overallEmpty) {
    return (
      <p className="rounded-[12px] border p-3 text-[13px] text-muted-foreground">
        {ot("viz.empty", "No timeseries data in this payload — shown honestly empty, never fabricated.")}
      </p>
    );
  }

  return (
    <div
      className="relative"
      role="group"
      aria-label={`${lanes.map((l) => l.title).join(" · ")} · ${days}d`}
      onPointerMove={onMove}
      onPointerDown={onMove}
      onPointerLeave={() => setHoverIdx(null)}
    >
      {preps.map((p) => {
        const { lane } = p;
        const lowSet = new Set(lane.lowSampleDays ?? []);
        return (
          <div key={lane.id} className="mb-1">
            <div className="flex items-baseline justify-between gap-2">
              <p className="text-[11px] font-medium">{lane.title}</p>
              {lane.unit ? <span className="text-[10px] text-muted-foreground">{lane.unit}</span> : null}
            </div>
            <div className="relative">
              {p.empty ? (
                <p className="rounded-[10px] border border-dashed p-2.5 text-xs text-muted-foreground">
                  {lane.emptyHint ?? ot("viz.empty", "No timeseries data in this payload — shown honestly empty, never fabricated.")}
                </p>
              ) : (
                <>
                  <svg
                    viewBox={`0 0 ${VB_W} ${H}`}
                    className="block h-auto w-full"
                    role="img"
                    aria-label={lane.title}
                  >
                    <defs>
                      {(p.lines ?? [])
                        .filter((l) => l.s.dominant === true)
                        .map((l) => (
                          <linearGradient key={l.s.id} id={`${gid}-${lane.id}-${l.s.id}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={l.color} stopOpacity="0.28" />
                            <stop offset="100%" stopColor={l.color} stopOpacity="0" />
                          </linearGradient>
                        ))}
                    </defs>

                    {/* 网格 + 0.5 中性虚线（仅固定 [0,1] 域）+ 底轴 */}
                    {p.ticks.map((t) => (
                      <line
                        key={`tick-${t.v}`}
                        x1={PAD_L}
                        x2={VB_W - 6}
                        y1={PLOT_TOP + (1 - (t.v - p.yMin) / (p.yMax - p.yMin)) * plotH}
                        y2={PLOT_TOP + (1 - (t.v - p.yMin) / (p.yMax - p.yMin)) * plotH}
                        style={{ stroke: GRID_STROKE }}
                        strokeWidth="1"
                        strokeDasharray={t.dashed ? NEUTRAL_DASH : GRID_DASH}
                      />
                    ))}
                    {p.ticks
                      .filter((t) => !t.dashed)
                      .map((t) => (
                        <text
                          key={`lab-${t.v}`}
                          x={PAD_L - 6}
                          textAnchor="end"
                          y={PLOT_TOP + (1 - (t.v - p.yMin) / (p.yMax - p.yMin)) * plotH - 2}
                          fontSize="8"
                          className="fill-muted-foreground"
                        >
                          {fmtTick(t.v)}
                        </text>
                      ))}
                    <line x1={PAD_L} x2={VB_W - 6} y1={axisY} y2={axisY} style={{ stroke: GRID_STROKE }} strokeWidth="1" />

                    {/* stacked_band：带（fill 0.55）+ 顶边线；当日总量 0 的 day 整列缺口 */}
                    {(p.bands ?? []).map((b) => (
                      <g key={`band-${b.s.id}`}>
                        {b.fills.map((d, i) => (
                          <path key={`f-${i}`} d={d} fill={b.color} fillOpacity="0.55" stroke="none" />
                        ))}
                        {b.edges.map((d, i) => (
                          <path key={`e-${i}`} d={d} fill="none" stroke={b.color} strokeWidth="1" strokeLinejoin="round" />
                        ))}
                      </g>
                    ))}

                    {/* multiline：null 断线分段（段内 Catmull-Rom 平滑），主导层次沿用 charts.tsx 已验证规格 */}
                    {(p.lines ?? []).map((l) => (
                      <g key={`line-${l.s.id}`}>
                        {l.areaPath ? (
                          <path d={l.areaPath} fill={`url(#${gid}-${lane.id}-${l.s.id})`} stroke="none" />
                        ) : null}
                        {l.paths.map((d, i) => (
                          <path
                            key={`p-${i}`}
                            d={d}
                            fill="none"
                            stroke={l.color}
                            strokeOpacity={l.s.dominant === true ? 1 : 0.38}
                            strokeWidth={l.s.dominant === true ? 2.4 : 1.2}
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        ))}
                        {l.singles.map(([cx, cy], i) => (
                          <circle
                            key={`s-${i}`}
                            cx={cx}
                            cy={cy}
                            r="1.6"
                            fill={l.color}
                            fillOpacity={l.s.dominant === true ? 1 : 0.4}
                          />
                        ))}
                        {l.s.dominant === true && l.last ? (
                          <circle cx={l.last[0]} cy={l.last[1]} r="2.5" fill={l.color} />
                        ) : null}
                      </g>
                    ))}

                    {/* 低样本日：x 轴下琥珀小三角（title 说明口径） */}
                    {dayList.map((d, i) =>
                      lowSet.has(d) ? (
                        <polygon
                          key={`low-${d}`}
                          points={`${xAt(i) - 3.5},${axisY + 2} ${xAt(i) + 3.5},${axisY + 2} ${xAt(i)},${axisY + 7}`}
                          fill={VIZ_SEMANTIC.warn}
                        >
                          <title>{ot("viz.lowSample", "Low-sample day (total n < 5); treat readings with caution")}</title>
                        </polygon>
                      ) : null,
                    )}

                    {/* x 轴首/中/尾标签 */}
                    {xLabelIdx.map((i) => (
                      <text
                        key={`x-${i}`}
                        x={xAt(i)}
                        y={H - 4}
                        fontSize={AXIS_FONT_SIZE}
                        textAnchor={i === 0 ? "start" : i === nDays - 1 ? "end" : "middle"}
                        className="fill-muted-foreground"
                      >
                        {fmtDay(dayList[i] as string)}
                        <title>{dayList[i]}</title>
                      </text>
                    ))}
                  </svg>

                  {/* 主导序列右端值徽标（TradingView price label 风格；hover 时让位给 tooltip） */}
                  {p.domLast && hoverIdx === null ? (
                    <span
                      className="pointer-events-none absolute right-0 z-[5] -translate-y-1/2 rounded-[4px] px-1 py-px text-[10px] font-semibold text-white"
                      style={{
                        top: `${Math.max(8, Math.min(92, (p.domLast.y / H) * 100))}%`,
                        backgroundColor: p.domLast.color,
                      }}
                    >
                      {fmtVal(p.domLast.value, p.isFrac)}
                    </span>
                  ) : null}
                </>
              )}
            </div>
          </div>
        );
      })}

      {/* 全图一层十字线 + 单 tooltip：hover day + 各 lane 该 day 值（主导行加粗，stacked 附占比） */}
      {hi !== null && nDays >= 2 ? (
        <>
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-y-0 z-10 w-px bg-muted-foreground/50"
            style={{ left: `${hoverX}%` }}
          />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute top-0 z-20 max-w-64 min-w-32 rounded-[6px] border bg-card px-2 py-1 text-[10px] shadow-sm"
            style={{ left: `${hoverX}%`, transform: `translateX(${tipTx})` }}
          >
            <p className="font-medium">{dayList[hi]}</p>
            {preps.map((p) =>
              p.empty ? null : (
                <div key={p.lane.id} className="mt-0.5">
                  {preps.length > 1 ? <p className="font-medium">{p.lane.title}</p> : null}
                  {p.lane.series.map((s) => {
                    const v = p.maps.get(s.id)?.get(dayList[hi] ?? "") ?? null;
                    const total = p.totals?.get(dayList[hi] ?? "") ?? 0;
                    return (
                      <p
                        key={s.id}
                        className={`flex items-center gap-1 ${s.dominant === true ? "font-semibold" : ""} ${
                          isNum(v) ? "" : "text-muted-foreground"
                        }`}
                      >
                        <span
                          aria-hidden
                          className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
                          style={{ backgroundColor: s.color ?? seriesColor(p.lane.series.indexOf(s)) }}
                        />
                        {s.label}: {isNum(v) ? fmtVal(v, p.isFrac) : "—"}
                        {p.lane.kind === "stacked_band" && isNum(v) && total > 0 ? (
                          <span className="font-normal text-muted-foreground">({Math.round((v / total) * 100)}%)</span>
                        ) : null}
                      </p>
                    );
                  })}
                </div>
              ),
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
