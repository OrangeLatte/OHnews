"use client";

/**
 * E3 图表组（裁决 8 新方案）：四块 2×2——G1 信息流日柱 / G2 叙事场 /
 * G3 实体分歧榜 / G4 情绪密度。窗口 1d/7d/30d/全量；数据面均为后端聚合
 * 端点（前端不拼图）；五状态显式（loading/empty/abstain/ready/error）。
 */

import { useEffect, useState } from "react";
import { ChartBase, type ChartState } from "@/components/visualizations/chart-base";
import { api } from "@/lib/api";
import { SIGNAL } from "@/lib/tokens";
import type { EChartsOption } from "echarts";

type WindowKey = "1" | "7" | "30" | "all";
const WINDOWS: Array<{ k: WindowKey; label: string; days: number }> = [
  { k: "1", label: "1 天", days: 1 },
  { k: "7", label: "7 天", days: 7 },
  { k: "30", label: "30 天", days: 30 },
  { k: "all", label: "全量", days: 120 },
];

const LANG_ZH: Record<string, string> = { zh: "中文", en: "英文", other: "其他" };
const EMO_ZH: Record<string, string> = {
  fear: "恐惧", anger: "愤怒", optimism: "乐观", uncertainty: "不确定",
  confidence: "自信", urgency: "紧迫", concern: "担忧", relief: "宽慰",
};

export function ChartGrid() {
  const [win, setWin] = useState<WindowKey>("7");
  const days = WINDOWS.find((w) => w.k === win)?.days ?? 7;

  return (
    <section aria-label="数据图表组" className="cg-section">
      <header className="cg-head">
        <p className="cg-kicker">CHART GRID · 数据图表组</p>
        <div className="cg-windows" role="group" aria-label="时间窗口">
          {WINDOWS.map((w) => (
            <button
              key={w.k}
              type="button"
              className="cg-win"
              data-active={win === w.k}
              onClick={() => setWin(w.k)}
            >
              {w.label}
            </button>
          ))}
        </div>
      </header>
      <div className="cg-grid">
        <G1 days={days} />
        <G2 days={Math.min(days, 30)} />
        <G3 />
        <G4 days={days} />
      </div>
    </section>
  );
}

function useFetch<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [state, setState] = useState<ChartState>("loading");
  useEffect(() => {
    let alive = true;
    fn()
      .then((d) => {
        if (!alive) return;
        setData(d);
        setState("ready");
      })
      .catch(() => {
        if (!alive) return;
        setData(null);
        setState("abstain");
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, state };
}

const AXIS = { axisLabel: { color: SIGNAL.muted, fontSize: 10 }, axisLine: { lineStyle: { color: "#c9c2b4" } } };

function G1({ days }: { days: number }) {
  const { data, state } = useFetch(() => api.flowDaily(days), [days]);
  if (state !== "ready" || !data) return <Panel title="信息流密度" state={state} />;
  const rows = data as Array<Record<string, number | string>>;
  if (rows.length === 0) return <Panel title="信息流密度" state="empty" />;
  const langs = ["zh", "en", "other"].filter((l) => rows.some((r) => (Number(r[l]) || 0) > 0));
  const option: EChartsOption = {
    tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: SIGNAL.muted, fontSize: 10 } },
    grid: { left: 36, right: 8, top: 24, bottom: 20, containLabel: true },
    xAxis: { type: "category", data: rows.map((r) => String(r.date)), ...AXIS },
    yAxis: { type: "value", ...AXIS, splitLine: { lineStyle: { color: "#e5e0d3" } } },
    series: langs.map((l) => ({
      name: LANG_ZH[l] ?? l,
      type: "bar" as const,
      stack: "total",
      barMaxWidth: 14,
      itemStyle: { color: l === "zh" ? SIGNAL.narrative : l === "en" ? SIGNAL.attention : SIGNAL.muted },
      data: rows.map((r) => Number(r[l]) || 0),
    })),
  };
  return <Panel title="信息流密度（按语言）" state="ready" option={option} />;
}

function G2({ days }: { days: number }) {
  const { data, state } = useFetch(() => api.changeField(days), [days]);
  if (state !== "ready" || !data) return <Panel title="叙事场" state={state} />;
  const points = (data.series ?? []) as Array<{ date: string; lanes: Record<string, Record<string, number>> }>;
  if (points.length === 0) return <Panel title="叙事场（泳道×框架）" state="empty" />;
  const laneMeta: Record<string, string> = {
    official: SIGNAL.confirmed, press: SIGNAL.narrative, market: SIGNAL.attention, social: SIGNAL.muted, unknown: "#c9c2b4",
  };
  const laneLabel: Record<string, string> = { official: "官方", press: "权威媒体", market: "市场媒体", social: "社媒", unknown: "未分级" };
  const laneTotal = (p: (typeof points)[number], lane: string) =>
    Object.values(p.lanes?.[lane] ?? {}).reduce((a: number, b: number) => a + b, 0);
  const lanes = Object.keys(laneMeta).filter((l) => points.some((p) => laneTotal(p, l) > 0));
  const option: EChartsOption = {
    tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: SIGNAL.muted, fontSize: 10 } },
    grid: { left: 36, right: 8, top: 24, bottom: 20, containLabel: true },
    xAxis: { type: "category", data: points.map((p) => p.date), ...AXIS },
    yAxis: { type: "value", ...AXIS, splitLine: { lineStyle: { color: "#e5e0d3" } } },
    series: lanes.map((l) => ({
      name: laneLabel[l],
      type: "line" as const,
      stack: "total",
      areaStyle: { opacity: 0.5 },
      symbol: "none",
      color: laneMeta[l],
      data: points.map((p) => laneTotal(p, l)),
    })),
  };
  return <Panel title="叙事场（泳道×框架堆叠）" state="ready" option={option} />;
}

function G3() {
  const { data, state } = useFetch(() => api.ndiRank(8), []);
  if (state !== "ready" || !data) return <Panel title="实体分歧榜" state={state} />;
  const rows = data as Array<{ entity: string; label: string; ndi: number; event_id: string }>;
  if (rows.length === 0) return <Panel title="实体分歧榜（NDI）" state="empty" />;
  const option: EChartsOption = {
    tooltip: { trigger: "item" },
    grid: { left: 8, right: 40, top: 8, bottom: 20, containLabel: true },
    xAxis: { type: "value", max: 1, ...AXIS },
    yAxis: { type: "category", data: rows.map((r) => r.label).reverse(), ...AXIS },
    series: [
      {
        type: "bar" as const,
        barMaxWidth: 12,
        itemStyle: { color: SIGNAL.divergence },
        label: { show: true, position: "right", color: SIGNAL.muted, fontSize: 10, formatter: (p: unknown) => String(Number((p as { value: number }).value).toFixed(2)) },
        data: rows.map((r) => r.ndi).reverse(),
      },
    ],
  };
  return <Panel title="实体分歧榜（NDI Top8，弃权不计）" state="ready" option={option} />;
}

function G4({ days }: { days: number }) {
  const { data, state } = useFetch(() => api.emotionDensity(days), [days]);
  if (state !== "ready" || !data) return <Panel title="情绪密度" state={state} />;
  const rows = data as Array<Record<string, number | string>>;
  if (rows.length === 0) return <Panel title="情绪密度（词典层）" state="empty" />;
  const keys = Object.keys(EMO_ZH).filter((k) => rows.some((r) => (Number(r[k]) || 0) > 0));
  const option: EChartsOption = {
    tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: SIGNAL.muted, fontSize: 10 } },
    grid: { left: 36, right: 8, top: 24, bottom: 20, containLabel: true },
    xAxis: { type: "category", data: rows.map((r) => String(r.date)), ...AXIS },
    yAxis: { type: "value", max: 1, ...AXIS, splitLine: { lineStyle: { color: "#e5e0d3" } } },
    series: keys.map((k) => ({
      name: EMO_ZH[k],
      type: "line" as const,
      symbol: "none",
      lineWidth: 1.5,
      data: rows.map((r) => Number(r[k]) || 0),
    })),
  };
  return <Panel title="情绪密度（词典层均值）" state="ready" option={option} />;
}

function Panel({
  title,
  state,
  option,
}: {
  title: string;
  state: ChartState;
  option?: EChartsOption;
}) {
  return (
    <div className="cg-card">
      <p className="cg-title">{title}</p>
      <ChartBase
        option={option ?? {}}
        state={state}
        height="15rem"
      />
    </div>
  );
}
