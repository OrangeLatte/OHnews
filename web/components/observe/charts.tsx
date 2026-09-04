"use client";

/**
 * OBSERVE 轻量图表（纯 SVG/div，零依赖）。
 * 所有图表只用相对量纲（归一化），不依赖外部图表库；数据缺失处断线/留白，绝不补造。
 */

import { useState } from "react";

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
}

export function MigrationBar({ label, shareBaseline, shareCurrent }: MigrationBarProps) {
  const delta = shareCurrent - shareBaseline;
  const arrow = delta > 0.005 ? "▲" : delta < -0.005 ? "▼" : "—";
  return (
    <li className="text-sm">
      <div className="flex justify-between">
        <span>{label}</span>
        <span className="text-xs text-muted-foreground">
          {pct(shareBaseline)} → {pct(shareCurrent)}{" "}
          <span className={delta > 0.005 ? "text-green-600" : delta < -0.005 ? "text-red-600" : ""}>
            {arrow} {Math.abs(Math.round(delta * 100))}pt
          </span>
        </span>
      </div>
      <div className="relative h-3 rounded bg-muted" title={`${label}: ${pct(shareBaseline)} → ${pct(shareCurrent)}`}>
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
  const n = Math.max(...series.map((s) => s.values.length), 2);
  const all = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  const max = all.length > 0 ? Math.max(...all) : 1;
  const min = all.length > 0 ? Math.min(...all) : 0;
  const span = max - min || 1;
  const pad = span * 0.1;
  const y = (v: number) => 38 - ((v - min + pad) / (span + 2 * pad)) * 36;
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = rect.width > 0 ? (e.clientX - rect.left) / rect.width : 0;
    setHover(Math.max(0, Math.min(n - 1, Math.round(frac * (n - 1)))));
  };
  const hoverX = hover === null ? 0 : (hover / (n - 1)) * 100;
  const tipTx = hover === null ? "-50%" : hover === 0 ? "0%" : hover === n - 1 ? "-100%" : "-50%";
  return (
    <div className="relative">
      <svg
        viewBox="0 0 100 40"
        preserveAspectRatio="none"
        style={{ height }}
        className="w-full"
        role="img"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {[0.25, 0.5, 0.75].map((g) => (
          <line key={g} x1="0" x2="100" y1={40 * g} y2={40 * g} className="stroke-muted" strokeWidth="0.3" />
        ))}
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
        {series.map((s) => {
          const segs: string[] = [];
          let cur: string[] = [];
          s.values.forEach((v, i) => {
            if (v === null) {
              if (cur.length > 1) segs.push(cur.join(" "));
              cur = [];
            } else {
              cur.push(`${((i / (n - 1)) * 100).toFixed(2)},${y(v).toFixed(2)}`);
            }
          });
          if (cur.length > 1) segs.push(cur.join(" "));
          return (
            <g key={s.name}>
              {segs.map((pts, i) => (
                <polyline
                  key={i}
                  points={pts}
                  fill="none"
                  className={s.color}
                  strokeWidth="1.5"
                  vectorEffect="non-scaling-stroke"
                  strokeLinejoin="round"
                />
              ))}
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <div
          className="pointer-events-none absolute top-0 z-10 min-w-28 rounded-[6px] border bg-card px-2 py-1 text-[10px] shadow-sm"
          style={{ left: `${hoverX}%`, transform: `translateX(${tipTx})` }}
          role="status"
        >
          <p className="font-medium">{dates?.[hover] ?? `#${hover + 1}`}</p>
          {series.map((s) => (
            <p key={s.name} className="flex items-center gap-1 text-muted-foreground">
              <span aria-hidden className={`inline-block h-1.5 w-1.5 rounded-full ${s.dot ?? "bg-muted-foreground"}`} />
              {s.name}: {s.values[hover] === null || s.values[hover] === undefined ? "—" : (s.values[hover] as number).toFixed(2)}
            </p>
          ))}
        </div>
      )}
      <ul className="mt-1 flex flex-wrap gap-3 text-[10px] text-muted-foreground">
        {series.map((s) => (
          <li key={s.name} className="flex items-center gap-1">
            <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${s.dot ?? "bg-muted-foreground"}`} />
            {s.name}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function MiniColumns({ values }: { values: number[] }) {
  const max = Math.max(...values, 1);
  return (
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
  );
}
