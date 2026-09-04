"use client";

/**
 * Emotion Lens：五情绪线图（均值 0-1；缺测断线，不插值补造）。
 * 增强：图例走 i18n、最新非空读数 chips、窗口标注覆盖说明。
 */

import { LineChart } from "@/components/observe/charts";
import { useOt } from "@/components/observe/i18n-bridge";
import { Skeleton } from "@/components/ui/toast";
import type { EmotionRow } from "@/lib/landscape-api";

const EMOTION_COLORS: { key: string; cls: string; dot: string }[] = [
  { key: "fear", cls: "stroke-red-500", dot: "bg-red-500" },
  { key: "anger", cls: "stroke-orange-500", dot: "bg-orange-500" },
  { key: "optimism", cls: "stroke-green-600", dot: "bg-green-600" },
  { key: "uncertainty", cls: "stroke-amber-500", dot: "bg-amber-500" },
  { key: "confidence", cls: "stroke-blue-500", dot: "bg-blue-500" },
];

export function EmotionPanel({ emotion, loading }: { emotion: EmotionRow[]; loading: boolean }) {
  const ot = useOt();
  if (loading) {
    return (
      <div aria-busy="true">
        <Skeleton className="h-[140px] rounded-[12px]" />
      </div>
    );
  }
  if (emotion.length === 0) {
    return (
      <p className="rounded-[12px] border p-3 text-[13px] text-muted-foreground">
        {ot("observe.emotion.empty", "No emotion annotation averages in this window (null when LLM annotation is missing; never fabricated).")}
      </p>
    );
  }
  const slice = emotion.slice(-30);
  // 最新一条有任一情绪读数的日期 → 最新值 chips
  const latest = [...slice].reverse().find((r) =>
    EMOTION_COLORS.some((c) => typeof r[c.key] === "number"),
  );
  const datedCount = slice.filter((r) =>
    EMOTION_COLORS.some((c) => typeof r[c.key] === "number"),
  ).length;

  return (
    <div className="space-y-2">
      <LineChart
        height={160}
        dates={slice.map((r) => r.date)}
        series={EMOTION_COLORS.map((c) => ({
          name: ot(`observe.emo.${c.key}`, c.key),
          color: c.cls,
          dot: c.dot,
          values: slice.map((r) => (typeof r[c.key] === "number" ? (r[c.key] as number) : null)),
        }))}
      />
      {latest ? (
        <div className="flex flex-wrap gap-1.5">
          {EMOTION_COLORS.map((c) => {
            const v = latest[c.key];
            return (
              <span
                key={c.key}
                className="inline-flex items-center gap-1 rounded-[6px] border px-1.5 py-0.5 text-xs"
                title={`${latest.date} · ${ot(`observe.emo.${c.key}`, c.key)}`}
              >
                <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${c.dot}`} />
                {ot(`observe.emo.${c.key}`, c.key)}
                <span className="font-semibold tabular-nums">
                  {typeof v === "number" ? v.toFixed(2) : "—"}
                </span>
              </span>
            );
          })}
        </div>
      ) : null}
      <p className="text-[10px] text-muted-foreground">
        {slice[0]?.date} → {slice.at(-1)?.date} ·{" "}
        {ot("observe.emotion.coverage", "{covered}/{total} days have readings", { covered: datedCount, total: slice.length })} ·{" "}
        {ot("observe.emotion.nullNote", "missing dates are gapped, never interpolated.")}
      </p>
    </div>
  );
}
