"use client";

/**
 * Flow Lens：sankey 式流入图（信源 → 基线/当前窗口，带宽 ∝ 文章量，sqrt 缩放）
 * + 逐源双条增量表（保留 delta 徽标）。纯 SVG，零第三方依赖。
 */

import { useOt } from "@/components/observe/i18n-bridge";
import { DualBar } from "@/components/observe/charts";
import { Skeleton } from "@/components/ui/toast";
import type { Landscape, SourceStream } from "@/lib/landscape-api";
import { useT } from "@/lib/i18n/use-t";

const CLUSTER_HEX: Record<string, string> = {
  market: "#2563eb",
  official: "#16a34a",
  social: "#d97706",
};
const FALLBACK_HEX = "#6b7280";
const clusterColor = (c: string): string => CLUSTER_HEX[c] ?? FALLBACK_HEX;

function windowLabel(w: { start: string; end: string; n_articles: number }): string {
  return `${w.start.slice(0, 10)} → ${w.end.slice(0, 10)} · ${w.n_articles}`;
}

/** sankey 式流入图：左=信源节点，右=基线/当前两个窗口节点。 */
function SankeyFlow({
  streams,
  labelBaseline,
  labelCurrent,
}: {
  streams: SourceStream[];
  labelBaseline: string;
  labelCurrent: string;
}) {
  const TOP_N = 8;
  const sorted = [...streams].sort(
    (a, b) => Math.max(b.n_baseline, b.n_current) - Math.max(a.n_baseline, a.n_current),
  );
  const head = sorted.slice(0, TOP_N);
  const rest = sorted.slice(TOP_N);
  const restAgg: SourceStream | null =
    rest.length > 0
      ? {
          source_id: "__other__",
          label: `+${rest.length}`,
          tier: "",
          cluster: rest[0].cluster,
          n_baseline: rest.reduce((s, x) => s + x.n_baseline, 0),
          n_current: rest.reduce((s, x) => s + x.n_current, 0),
        }
      : null;
  const nodes = restAgg ? [...head, restAgg] : head;

  const vmax = Math.max(...nodes.map((n) => Math.max(n.n_baseline, n.n_current)), 1);
  const wOf = (v: number): number => (v <= 0 ? 0 : 3 + 24 * Math.sqrt(v / vmax));

  const rowH = 30;
  const svgH = Math.max(nodes.length * rowH + 60, 200);
  // 右侧两个窗口节点的纵向堆叠起点
  const baseStart = 28;
  const curStart = svgH / 2 + 22;
  const links = nodes
    .reduce<{ acc: { n: SourceStream; ySrc: number; yBase: number; yCur: number; wb: number; wc: number; color: string }[]; baseOff: number; curOff: number }>(
      (st, n, i) => {
        const wb = wOf(n.n_baseline);
        const wc = wOf(n.n_current);
        const ySrc = 24 + i * rowH + rowH / 2;
        const yBase = baseStart + st.baseOff + wb / 2;
        const yCur = curStart + st.curOff + wc / 2;
        st.acc.push({ n, ySrc, yBase, yCur, wb, wc, color: clusterColor(n.cluster) });
        return { acc: st.acc, baseOff: st.baseOff + wb + 2, curOff: st.curOff + wc + 2 };
      },
      { acc: [], baseOff: 0, curOff: 0 },
    );
  const baseH = Math.max(links.baseOff - 2, 8);
  const curH = Math.max(links.curOff - 2, 8);

  const baseTotal = streams.reduce((s, x) => s + x.n_baseline, 0);
  const curTotal = streams.reduce((s, x) => s + x.n_current, 0);

  return (
    <svg viewBox={`0 0 720 ${svgH}`} className="h-auto w-full" role="img" aria-label="source to window flow">
      {links.acc.map(({ n, ySrc, yBase, yCur, wb, wc, color }) => (
        <g key={n.source_id}>
          {wb > 0 ? (
            <path
              d={`M128,${ySrc} C360,${ySrc} 400,${yBase} 600,${yBase}`}
              fill="none"
              stroke={color}
              strokeWidth={wb}
              opacity="0.4"
              className="transition-opacity hover:opacity-80"
            >
              <title>{`${n.label} → ${labelBaseline}: ${n.n_baseline}`}</title>
            </path>
          ) : null}
          {wc > 0 ? (
            <path
              d={`M128,${ySrc} C360,${ySrc} 400,${yCur} 600,${yCur}`}
              fill="none"
              stroke={color}
              strokeWidth={wc}
              opacity="0.4"
              className="transition-opacity hover:opacity-80"
            >
              <title>{`${n.label} → ${labelCurrent}: ${n.n_current}`}</title>
            </path>
          ) : null}
        </g>
      ))}
      {nodes.map((n, i) => (
        <g key={n.source_id}>
          <rect x="122" y={24 + i * rowH + 4} width="12" height={rowH - 8} rx="3" fill={clusterColor(n.cluster)} opacity="0.85">
            <title>{n.label}</title>
          </rect>
          <text x="112" y={24 + i * rowH + rowH / 2 + 3} textAnchor="end" fontSize="11" className="fill-muted-foreground">
            {n.label.length > 14 ? `${n.label.slice(0, 13)}…` : n.label}
          </text>
        </g>
      ))}
      <rect x="600" y={baseStart} width="12" height={baseH} rx="3" className="fill-muted-foreground/50" />
      <text x="600" y={baseStart - 8} fontSize="11" className="fill-foreground" fontWeight="600">
        {labelBaseline} · {baseTotal.toLocaleString("en-US")}
      </text>
      <rect x="600" y={curStart} width="12" height={curH} rx="3" className="fill-foreground" />
      <text x="600" y={curStart - 8} fontSize="11" className="fill-foreground" fontWeight="600">
        {labelCurrent} · {curTotal.toLocaleString("en-US")}
      </text>
    </svg>
  );
}

export function FlowPanel({ landscape }: { landscape: Landscape | null }) {
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

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        {labelBaseline}: {windowLabel(landscape.baseline_window)} · {labelCurrent}:{" "}
        {windowLabel(landscape.current_window)}
      </p>
      {streams.length > 0 ? (
        <>
          <SankeyFlow streams={streams} labelBaseline={labelBaseline} labelCurrent={labelCurrent} />
          <ul className="space-y-3">
            {streams.map((s) => {
              const delta =
                s.n_baseline > 0 ? Math.round(((s.n_current - s.n_baseline) / s.n_baseline) * 100) : null;
              return (
                <li key={s.source_id} className="flex items-center gap-3 text-[13px]">
                  <span className="w-44 shrink-0 truncate" title={s.label}>
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
