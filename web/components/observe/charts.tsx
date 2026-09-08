"use client";

/**
 * OBSERVE 轻量图表（纯 SVG/div，零依赖）。
 * 所有图表只用相对量纲（归一化），不依赖外部图表库；数据缺失处断线/留白，绝不补造。
 */

import { useState } from "react";
import { useOt } from "@/components/observe/i18n-bridge";

interface DualBarProps {
  baseline: number;
  current: number;
  max: number;
  labelBaseline: string;
  labelCurrent: string;
}

export function DualBar({ baseline, current, max, labelBaseline, labelCurrent }: DualBarProps) {
  const w1 = max > 0 ? (baseline / max) * 100 : 0;
  const w2 = max > 0 ? (current / max) * 100 : 0;
  return (
    <div
      className="min-w-[8rem] flex-1 space-y-0.5"
      title={`${labelBaseline}: ${baseline} · ${labelCurrent}: ${current}`}
    >
      <div className="flex items-center gap-1">
        <div className="h-1.5 w-full rounded bg-muted">
          <div className="h-1.5 rounded bg-muted-foreground/40" style={{ width: `${w1}%` }} />
        </div>
        <span className="w-8 shrink-0 text-right text-[10px] text-muted-foreground">{baseline}</span>
      </div>
      <div className="flex items-center gap-1">
        <div className="h-1.5 w-full rounded bg-muted">
          <div className="h-1.5 rounded bg-foreground" style={{ width: `${w2}%` }} />
        </div>
        <span className="w-8 shrink-0 text-right text-[10px]">{current}</span>
      </div>
      <p className="text-[10px] text-muted-foreground">
        {labelBaseline} / {labelCurrent}
      </p>
    </div>
  );
}

interface MigrationBarProps {
  label: string;
  shareBaseline: number;
  shareCurrent: number;
  /** 点击打开统一 Change Drawer（可选；P1 图表联动）。 */
  onClick?: () => void;
  /** 低样本警示（share_baseline<0.05）：虚线边框+琥珀 tint+title。 */
  lowSampleTitle?: string;
}

export function MigrationBar({ label, shareBaseline, shareCurrent, onClick, lowSampleTitle }: MigrationBarProps) {
  const delta = shareCurrent - shareBaseline;
  const arrow = delta > 0.005 ? "▲" : delta < -0.005 ? "▼" : "—";
  return (
    <li
      onClick={onClick}
      className={`text-sm ${onClick ? "cursor-pointer" : ""} ${
        lowSampleTitle ? "rounded-[8px] border border-dashed border-amber-500/70 bg-amber-500/10" : ""
      }`}
      title={lowSampleTitle ?? `${label}: ${pct(shareBaseline)} → ${pct(shareCurrent)}`}
    >
      <div className="flex justify-between">
        <span>{label}</span>
        <span className="text-xs text-muted-foreground">
          {pct(shareBaseline)} → {pct(shareCurrent)}{" "}
          <span className={delta > 0.005 ? "text-#5e7d59" : delta < -0.005 ? "text-#9c4634" : ""}>
            {arrow} {Math.abs(Math.round(delta * 100))}pt
          </span>
        </span>
      </div>
      <div className="relative h-3 rounded bg-muted">
        <div
          className="absolute top-0 h-1.5 rounded-t bg-muted-foreground/40"
          style={{ width: `${Math.round(shareBaseline * 100)}%` }}
        />
        <div
          className="absolute bottom-0 h-1.5 rounded-b bg-foreground"
          style={{ width: `${Math.round(shareCurrent * 100)}%` }}
        />
      </div>
    </li>
  );
}

function pct(x: number): string {
  return `${Math.round(x * 100)}%`;
}

export function RankBar({ value, max, title }: { value: number; max: number; title?: string }) {
  return (
    <div
      className="h-1.5 w-24 rounded bg-muted"
      title={title ?? String(Math.round((value / (max || 1)) * 100))}
    >
      <div
        className="h-1.5 rounded bg-foreground"
        style={{ width: `${max > 0 ? Math.round((value / max) * 100) : 0}%` }}
      />
    </div>
  );
}

interface LineSeries {
  name: string;
  color: string;
  /** 图例色点 class（与 color 同色系；因 Tailwind JIT 需字面量，调用方显式传入）。 */
  dot?: string;
  values: (number | null)[];
  /** 主导序列：实线+渐变面积+端点徽标；其余淡化细线。 */
  dominant?: boolean;
}

export function LineChart({
  series,
  height = 140,
  dates,
}: {
  series: LineSeries[];
  height?: number;
  dates?: string[];
}) {
  const [hover, setHover] = useState<number | null>(null);
  const ot = useOt();
  const gid = `lc-${series.map((s) => s.name).join("-").replace(/[^a-z0-9-]/gi, "")}`;
  const n = Math.max(...series.map((s) => s.values.length), 2);
  // 情绪均值语义域固定 0-1（不随窗口 min/max 缩放，避免视觉放大失真）
  const y = (v: number) => 38 - v * 36;
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = rect.width > 0 ? (e.clientX - rect.left) / rect.width : 0;
    setHover(Math.max(0, Math.min(n - 1, Math.round(frac * (n - 1)))));
  };
  const hoverX = hover === null ? 0 : (hover / (n - 1)) * 100;
  const tipTx = hover === null ? "-50%" : hover === 0 ? "0%" : hover === n - 1 ? "-100%" : "-50%";
  return (
    <div className="flex gap-1.5">
      <div aria-hidden className="relative w-7 shrink-0 select-none text-[9px] text-muted-foreground">
        <span className="absolute right-0 -translate-y-1/2" style={{ top: "5%" }}>1.0</span>
        <span className="absolute right-0 -translate-y-1/2" style={{ top: "50%" }}>0.5</span>
        <span className="absolute right-0 -translate-y-1/2" style={{ top: "95%" }}>0</span>
      </div>
      <div className="relative min-w-0 flex-1">
      <svg
        viewBox="0 0 100 40"
        preserveAspectRatio="none"
        style={{ height }}
        className="w-full"
        role="img"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {[0.25, 0.75].map((g) => (
          <line key={g} x1="0" x2="100" y1={40 * g} y2={40 * g} className="stroke-muted" strokeWidth="0.3" />
        ))}
        {/* 0.5 中性参考线（情绪均值域 0-1 的语义中线） */}
        <line x1="0" x2="100" y1="20" y2="20" className="stroke-muted" strokeWidth="0.3" strokeDasharray="1.5 1.5" />
        {hover !== null && (
          <line
            x1={hoverX}
            x2={hoverX}
            y1="0"
            y2="40"
            className="stroke-muted-foreground/50"
            strokeWidth="1"
            strokeDasharray="2 2"
            vectorEffect="non-scaling-stroke"
          />
        )}

        {[...series].sort((a, b) => Number(a.dominant ?? false) - Number(b.dominant ?? false)).map((s) => {
          // 按 null 分段（缺测断线，段内 Catmull-Rom 平滑；绝不跨缺口连线）
          const runs: [number, number][][] = [];
          let run: [number, number][] = [];
          s.values.forEach((v, i) => {
            if (v === null) {
              if (run.length > 0) runs.push(run);
              run = [];
            } else {
              run.push([(i / (n - 1)) * 100, y(v)]);
            }
          });
          if (run.length > 0) runs.push(run);
          const paths = runs.flatMap((run) =>
            run.length > 1
              ? [run.map((pt, i) => `${i === 0 ? "M" : "L"} ${pt[0].toFixed(2)} ${pt[1].toFixed(2)}`).join(" ")]
              : [],
          );
          const dominant = s.dominant === true;
          const lastRun = runs.at(-1);
          const last = lastRun?.at(-1);
          return (
            <g key={s.name}>
              {paths.map((d, i) => (
                <path
                  key={i}
                  d={d}
                  fill="none"
                  className={s.color}
                  strokeOpacity={dominant ? 1 : 0.38}
                  strokeWidth={dominant ? 2.4 : 1.2}
                  vectorEffect="non-scaling-stroke"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              ))}
              {/* 缺测日空心标记（诚实：无读数不插值，但每天有可视化呈现） */}
              {s.values.map((v, i) =>
                v === null ? (
                  <path
                    key={`gap-${i}`}
                    d={`M ${(i / (n - 1)) * 100} ${y(0)} l 0.01 0`}
                    className="stroke-muted-foreground"
                    strokeWidth="2.2"
                    strokeOpacity="0.55"
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                    strokeDasharray="0.1 2.4"
                  />
                ) : null,
              )}
              {runs.filter((r) => r.length === 1).map((r, i) => (
                <path
                  key={`sp-${i}`}
                  d={`M ${r[0][0].toFixed(3)} ${r[0][1].toFixed(3)} l 0.01 0`}
                  className={s.color.replace("stroke-", "stroke-")}
                  strokeWidth="3.2"
                  strokeOpacity={dominant ? 1 : 0.4}
                  vectorEffect="non-scaling-stroke"
                  strokeLinecap="round"
                  fill="none"
                />
              ))}
            </g>
          );
        })}
      </svg>
      {/* 主导序列右端值徽标（TradingView price label 风格） */}
      {(() => {
        const dom = series.find((s) => s.dominant);
        if (!dom || hover !== null) return null;
        let li = -1;
        for (let i = dom.values.length - 1; i >= 0; i--) {
          if (dom.values[i] !== null) { li = i; break; }
        }
        if (li < 0) return null;
        return (
          <span
            className={`pointer-events-none absolute -translate-y-1/2 rounded-[4px] px-1 py-px text-[10px] font-semibold text-white ${dom.dot ?? "bg-muted-foreground"}`}
            style={{ right: 0, top: `${(y(dom.values[li] as number) / 40) * 100}%` }}
          >
            {(dom.values[li] as number).toFixed(2)}
          </span>
        );
      })()}
      {hover !== null && (
        <div
          className="pointer-events-none absolute top-0 z-10 min-w-28 rounded-[6px] border bg-card px-2 py-1 text-[10px] shadow-sm"
          style={{ left: `${hoverX}%`, transform: `translateX(${tipTx})` }}
          role="status"
        >
          <p className="font-medium">{dates?.[hover] ?? `#${hover + 1}`}</p>
          {(() => {
            const present = series
              .map((x) => ({ s: x, v: x.values[hover] }))
              .filter((e) => typeof e.v === "number")
              .sort((a, b) => (b.v as number) - (a.v as number));
            const missing = series.length - present.length;
            return (
              <>
                {present.map(({ s, v }) => (
                  <p key={s.name} className="flex items-center gap-1">
                    <span aria-hidden className={`inline-block h-1.5 w-1.5 rounded-full ${s.dot ?? "bg-muted-foreground"}`} />
                    {s.name}
                    <b className="ml-auto pl-2 font-semibold tabular-nums">{(v as number).toFixed(2)}</b>
                  </p>
                ))}
                {missing > 0 && (
                  <p className="text-muted-foreground/70">+{missing} {ot("observe.emotion.noReading", "series without reading")}</p>
                )}
                {present.length === 0 && (
                  <p className="text-muted-foreground/70">{ot("observe.emotion.noReadingDay", "no readings on this day")}</p>
                )}
              </>
            );
          })()}
        </div>
      )}
      <ul className="mt-1 flex flex-wrap gap-3 text-[10px] text-muted-foreground">
        {series.map((s) => (
          <li key={s.name} className={`flex items-center gap-1 ${s.dominant ? "font-medium text-foreground" : ""}`}>
            <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${s.dot ?? "bg-muted-foreground"}`} />
            {s.name}
            {s.dominant ? (
              <span className="rounded-[3px] bg-muted px-1 py-px text-[9px] text-muted-foreground">
                {ot("observe.emotion.dominant", "dominant")}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      {dates && dates.length > 1 ? (
        <div aria-hidden className="mt-0.5 flex justify-between text-[9px] text-muted-foreground">
          {dates.map((d, i) => (i % 1 === 0 || i === dates.length - 1 ? (
            <span key={i}>{d.slice(5)}</span>
          ) : (
            <span key={i} className="text-transparent">·</span>
          )))}
        </div>
      ) : null}
      </div>
    </div>
  );
}

export function MiniColumns({ values, dates }: { values: number[]; dates?: string[] }) {
  const max = Math.max(...values, 1);
  return (
    <div>
    <svg
      viewBox="0 0 100 24"
      preserveAspectRatio="none"
      className="h-12 w-full"
      role="img"
      aria-label="articles per day"
    >
      {values.map((v, i) => (
        <rect
          key={i}
          x={(i / values.length) * 100}
          y={24 - (v / max) * 22}
          width={100 / values.length - 0.6}
          height={(v / max) * 22}
          className="fill-foreground/70 hover:fill-foreground"
        >
          <title>{v}</title>
        </rect>
      ))}
    </svg>
    {dates && dates.length > 1 ? (
        <div aria-hidden className="mt-0.5 flex justify-between text-[9px] text-muted-foreground">
          {dates.map((d, i) => (i % 1 === 0 || i === dates.length - 1 ? (
            <span key={i}>{d.slice(5)}</span>
          ) : (
            <span key={i} className="text-transparent">·</span>
          )))}
        </div>
      ) : null}
    </div>
  );
}
