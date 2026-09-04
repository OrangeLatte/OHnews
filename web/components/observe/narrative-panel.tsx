"use client";

/**
 * Narrative Lens：河流/冲积图（基线态 → 当前态框架份额流带，纯 SVG）
 * + 明细迁移条（保留精确数字）。基线无标注时诚实降级为单柱，不插值。
 */

import { MigrationBar } from "@/components/observe/charts";
import { useOt } from "@/components/observe/i18n-bridge";
import { Skeleton } from "@/components/ui/toast";
import type { Landscape, NarrativeStream } from "@/lib/landscape-api";
import { useT } from "@/lib/i18n/use-t";

const FRAME_HEX: Record<string, string> = {
  gain: "#16a34a",
  loss: "#d97706",
  conflict: "#dc2626",
  human_interest: "#db2777",
  responsibility: "#2563eb",
  other: "#6b7280",
};
const FALLBACK = ["#2563eb", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#6b7280"];
const frameColor = (frame: string, i: number): string =>
  FRAME_HEX[frame] ?? FALLBACK[i % FALLBACK.length];

/** 双态冲积图：左柱=基线份额，右柱=当前份额，中间流带连接同一框架。 */
function NarrativeRiver({ streams }: { streams: NarrativeStream[] }) {
  const H = 240;
  const y0 = 24;
  const gap = 3;
  const lx = 110;
  const rx = 504;
  const barW = 26;

  const baseTotal = streams.reduce((s, n) => s + n.share_baseline, 0);
  const curTotal = streams.reduce((s, n) => s + n.share_current, 0);
  const hasBase = baseTotal > 0.005;

  const scale = (share: number, total: number): number =>
    total > 0.005 ? (share / total) * (H - (streams.length - 1) * gap) : 0;

  const segs = streams.reduce<{ acc: { n: NarrativeStream; yB: number; hB: number; yC: number; hC: number; color: string }[]; baseOff: number; curOff: number }>(
    (st, n, i) => {
      const hB = scale(n.share_baseline, baseTotal);
      const hC = scale(n.share_current, curTotal);
      st.acc.push({
        n,
        yB: y0 + st.baseOff, hB,
        yC: y0 + st.curOff, hC,
        color: frameColor(n.frame, i),
      });
      return { acc: st.acc, baseOff: st.baseOff + hB + gap, curOff: st.curOff + hC + gap };
    },
    { acc: [], baseOff: 0, curOff: 0 },
  ).acc;
  return (
    <svg viewBox="0 0 640 300" className="h-auto w-full" role="img" aria-label="narrative frame shares">
      {segs.map(({ n, yB, hB, yC, hC, color }) => (
        <g key={n.frame}>
          {hasBase && hC > 0.5 && hB > 0.5 ? (
            <path
              d={`M${lx + barW},${yB} C320,${yB} 320,${yC} ${rx},${yC} L${rx},${yC + hC} C320,${yC + hC} 320,${yB + hB} ${lx + barW},${yB + hB} Z`}
              fill={color}
              opacity="0.28"
              className="transition-opacity hover:opacity-60"
            >
              <title>{`${n.label || n.frame}: ${(n.share_baseline * 100).toFixed(1)}% → ${(n.share_current * 100).toFixed(1)}%`}</title>
            </path>
          ) : null}
          {hasBase && hB > 0.5 ? (
            <rect x={lx} y={yB} width={barW} height={hB} rx="3" fill={color} opacity="0.75">
              <title>{`${n.label || n.frame} · ${ot0(n.share_baseline)}`}</title>
            </rect>
          ) : null}
          {hC > 0.5 ? (
            <rect x={rx} y={yC} width={barW} height={hC} rx="3" fill={color} opacity="0.9">
              <title>{`${n.label || n.frame} · ${ot0(n.share_current)}`}</title>
            </rect>
          ) : null}
          {hasBase && hB > 12 ? (
            <text x={lx - 8} y={yB + hB / 2 + 3} textAnchor="end" fontSize="11" className="fill-muted-foreground">
              {`${n.label || n.frame} ${(n.share_baseline * 100).toFixed(0)}%`}
            </text>
          ) : null}
          {hC > 12 ? (
            <text x={rx + barW + 8} y={yC + hC / 2 + 3} fontSize="11" className="fill-foreground">
              {`${n.label || n.frame} ${(n.share_current * 100).toFixed(0)}%`}
            </text>
          ) : null}
        </g>
      ))}
      <text x={lx + barW / 2} y={y0 - 8} textAnchor="middle" fontSize="10" className="fill-muted-foreground">
        {hasBase ? "t-2w" : "—"}
      </text>
      <text x={rx + barW / 2} y={y0 - 8} textAnchor="middle" fontSize="10" className="fill-muted-foreground">
        t-1w
      </text>
    </svg>
  );
}

function ot0(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}

export function NarrativePanel({ landscape }: { landscape: Landscape | null }) {
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
  return (
    <div className="space-y-4">
      <NarrativeRiver streams={landscape.narrative_streams} />
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
          />
        ))}
      </ul>
    </div>
  );
}
