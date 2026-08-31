"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { PAPER_THEME } from "@/lib/tokens";

/**
 * 全站唯一 ECharts 封装（R5b）：
 * - PAPER_THEME 主题注入（textStyle 全局 + axis 样式逐轴合并，用户显式配置优先）
 * - ResizeObserver 容器级自适应
 * - loading/empty/abstain/ready 四态（空态与弃权语义分离，弃权 = 样本门未过）
 * - onSeriesClick 统一点击回调（cbRef 模式，回调变更不重建实例）
 */

export type ChartState = "loading" | "empty" | "abstain" | "ready";

const STATE_TEXT: Record<Exclude<ChartState, "ready">, string> = {
  loading: "加载中…",
  empty: "窗口内数据不足",
  abstain: "样本不足，保守弃权",
};

const PAPER_AXIS = PAPER_THEME.axis;

/** 将报纸风 axis 样式注入 option 的每个 xAxis/yAxis（用户显式配置逐键优先）。 */
function applyPaperAxis(option: echarts.EChartsOption): echarts.EChartsOption {
  const out = { ...option, ...PAPER_THEME } as Record<string, unknown>;
  const asObj = (x: unknown): Record<string, unknown> =>
    x && typeof x === "object" ? (x as Record<string, unknown>) : {};
  const mergeAxis = (raw: unknown): Record<string, unknown> => {
    const a = asObj(raw);
    return {
      ...a,
      axisLine: { ...PAPER_AXIS.axisLine, ...asObj(a.axisLine) },
      axisLabel: { ...PAPER_AXIS.axisLabel, ...asObj(a.axisLabel) },
      splitLine: { ...PAPER_AXIS.splitLine, ...asObj(a.splitLine) },
    };
  };
  for (const key of ["xAxis", "yAxis"]) {
    const val = out[key] as unknown;
    if (!val) continue;
    const arr = Array.isArray(val) ? val : [val];
    out[key] = arr.map((a) => mergeAxis(a as Record<string, unknown>));
  }
  return out as echarts.EChartsOption;
}

export function ChartBase({
  option,
  height = "38vh",
  state = "ready",
  onSeriesClick,
}: {
  option: echarts.EChartsOption;
  height?: string | number;
  state?: ChartState;
  onSeriesClick?: (params: echarts.ECElementEvent) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const cbRef = useRef(onSeriesClick);

  useEffect(() => {
    cbRef.current = onSeriesClick;
  }, [onSeriesClick]);

  useEffect(() => {
    if (state !== "ready" || !ref.current) return;
    const el = ref.current;
    const chart = echarts.init(el);
    chartRef.current = chart;
    chart.on("click", (params: echarts.ECElementEvent) => cbRef.current?.(params));
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, [state]);

  useEffect(() => {
    const chart = chartRef.current;
    if (state !== "ready" || !chart) return;
    chart.setOption(applyPaperAxis(option), true);
  }, [option, state]);

  if (state !== "ready") {
    return (
      <div
        className="flex w-full items-center justify-center border border-dashed border-border/60 text-xs text-muted-foreground"
        style={{ height }}
      >
        {STATE_TEXT[state]}
      </div>
    );
  }
  return <div ref={ref} style={{ width: "100%", height }} />;
}
