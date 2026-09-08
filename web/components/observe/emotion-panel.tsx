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
  { key: "fear", cls: "stroke-[#b3543f]", dot: "bg-[#b3543f]" },
  { key: "anger", cls: "stroke-[#c07a4a]", dot: "bg-[#c07a4a]" },
  { key: "optimism", cls: "stroke-[#6f8f6a]", dot: "bg-[#6f8f6a]" },
  { key: "uncertainty", cls: "stroke-[#b08d3f]", dot: "bg-[#b08d3f]" },
  { key: "confidence", cls: "stroke-[#5e83a8]", dot: "bg-[#5e83a8]" },
  { key: "urgency", cls: "stroke-[#a05a78]", dot: "bg-[#a05a78]" },
  { key: "concern", cls: "stroke-[#8a6fae]", dot: "bg-[#8a6fae]" },
  { key: "relief", cls: "stroke-[#5e9c94]", dot: "bg-[#5e9c94]" },
];

export function EmotionPanel({
  emotion,
  loading,
  onOpenEmotion,
}: {
  emotion: EmotionRow[];
  loading: boolean;
  /** 情绪线最新点（chips）点击 → 统一 Change Drawer（P1 图表联动）。 */
  onOpenEmotion: (emotionKey: string, value: number, date: string) => void;
}) {
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
  // 主导情绪 = 窗口内有读数日期的均值最高者（仅作视觉主层次，不改变任何数据值）
  const means = EMOTION_COLORS.map((c) => {
    const vals = slice.map((r) => r[c.key]).filter((v): v is number => typeof v === "number");
    return { key: c.key, mean: vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : -1 };
  }).sort((a, b) => b.mean - a.mean);
  const dominantKey = means[0]?.mean > 0 ? means[0].key : null;
  // 最新一条有任一情绪读数的日期 → 最新值 chips
  const latest = [...slice].reverse().find((r) =>
    EMOTION_COLORS.some((c) => typeof r[c.key] === "number"),
  );
  const datedCount = slice.filter((r) =>
    EMOTION_COLORS.some((c) => typeof r[c.key] === "number"),
  ).length;

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">{ot("observe.emotion.desc", "Emotion temperature · daily article-level annotation density")}</p>
      <LineChart
        height={180}
        dates={slice.map((r) => r.date)}
        series={EMOTION_COLORS.map((c) => ({
          name: ot(`observe.emo.${c.key}`, c.key),
          color: c.cls,
          dot: c.dot,
          values: slice.map((r) => (typeof r[c.key] === "number" ? (r[c.key] as number) : null)),
          dominant: c.key === dominantKey,
        }))}
      />
      {latest ? (
        <div className="flex flex-wrap gap-1.5">
          {EMOTION_COLORS.map((c) => {
            const v = latest[c.key];
            const hasValue = typeof v === "number";
            return (
              <button
                key={c.key}
                type="button"
                disabled={!hasValue}
                onClick={() => onOpenEmotion(c.key, v as number, latest.date)}
                className="inline-flex items-center gap-1 rounded-[6px] border px-1.5 py-0.5 text-xs transition-colors enabled:cursor-pointer enabled:hover:bg-muted/60 disabled:cursor-default disabled:opacity-60"
                title={
                  hasValue
                    ? `${latest.date} · ${ot(`observe.emo.${c.key}`, c.key)} · ${ot("observe.drawer.clickHint", "Click to open the change detail drawer")}`
                    : `${latest.date} · ${ot(`observe.emo.${c.key}`, c.key)}`
                }
              >
                <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${c.dot}`} />
                {ot(`observe.emo.${c.key}`, c.key)}
                <span className="font-semibold tabular-nums">{hasValue ? (v as number).toFixed(2) : "—"}</span>
              </button>
            );
          })}
        </div>
      ) : null}
      <p className="text-[10px] text-muted-foreground">
        {slice[0]?.date} → {slice.at(-1)?.date} ·{" "}
        {ot("observe.emotion.coverage", "{covered}/{total} days have readings", { covered: datedCount, total: slice.length })}
        {datedCount < slice.length
          ? ` · ${ot("observe.emotion.nullNote", "missing dates are gapped, never interpolated.")}`
          : ` · ${ot("observe.emotion.carryNote", "missing dates carried forward from last reading.")}`}
      </p>
    </div>
  );
}
