"use client";

/**
 * Divergence Lens：NDI 棒棒糖图（轨道+杆+语义色头点）；点击实体仍下钻 Entities 时间线。
 * 色语义：低=绿 / 中=琥珀 / 高=冲突红（ndiTone）。
 */

import { useOt } from "@/components/observe/i18n-bridge";
import { ndiTone } from "@/components/observe/rel-time";
import { Skeleton } from "@/components/ui/toast";
import type { NdiRankRow } from "@/lib/landscape-api";

const TONE_HEX: Record<string, string> = {
  ok: "#16a34a",
  warn: "#d97706",
  conflict: "#dc2626",
  gap: "#6b7280",
};

export function DivergencePanel({
  ndi,
  loading,
  onOpenEntity,
}: {
  ndi: NdiRankRow[];
  loading: boolean;
  onOpenEntity: (entity: string) => void;
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
  const max = Math.max(...ndi.map((r) => r.ndi), 0.01);
  const x0 = 160;
  const x1 = 560;
  const rowH = 36;
  const h = ndi.length * rowH + 14;
  return (
    <div className="space-y-2">
      <svg viewBox={`0 0 640 ${h}`} className="h-auto w-full" role="img" aria-label="NDI ranking">
        {ndi.map((r, i) => {
          const cy = 20 + i * rowH;
          const len = Math.round((r.ndi / max) * (x1 - x0));
          const tone = ndiTone(r.ndi);
          return (
            <g
              key={r.entity}
              className="cursor-pointer"
              onClick={() => onOpenEntity(r.entity)}
            >
              <title>{ot("observe.divergence.openEntity", "Open timeline of {entity}", { entity: r.entity })}</title>
              <rect x="0" y={cy - rowH / 2 + 2} width="640" height={rowH - 4} className="fill-transparent hover:fill-muted/60" rx="6" />
              <text x={x0 - 12} y={cy + 4} textAnchor="end" fontSize="12" className="fill-foreground">
                {(r.label ?? r.entity).length > 16 ? `${(r.label ?? r.entity).slice(0, 15)}…` : r.label ?? r.entity}
              </text>
              <line x1={x0} y1={cy} x2={x1} y2={cy} className="stroke-muted" strokeWidth="6" strokeLinecap="round" />
              <line x1={x0} y1={cy} x2={x0 + len} y2={cy} className="stroke-muted-foreground/70" strokeWidth="2" />
              <circle cx={x0 + len} cy={cy} r="8" fill={TONE_HEX[tone]} className="stroke-card" strokeWidth="2">
                <title>{`NDI ${r.ndi.toFixed(2)}`}</title>
              </circle>
              <text x={x0 + len + 14} y={cy + 4} fontSize="12" fontWeight="600" className="fill-foreground">
                {r.ndi.toFixed(2)}
              </text>
              <text x={632} y={cy + 4} textAnchor="end" fontSize="10" className="fill-muted-foreground">
                n={r.n_sources ?? r.n ?? "—"}
              </text>
            </g>
          );
        })}
      </svg>
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
