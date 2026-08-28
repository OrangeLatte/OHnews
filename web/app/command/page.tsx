"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import * as echarts from "echarts";

import { EChart } from "@/components/echart";

type FlowSummary = {
  generated_at: string;
  days: number;
  daily: { date: string; tier: string; language: string; n: number }[];
  frames: { date: string; frame: string; n: number }[];
  sources: { source_id: string; n: number; language: string; tier: string }[];
  ndi: {
    event_id: string;
    ts: string;
    ndi: number | null;
    n_sources: number;
    status: string;
    language: string;
    low_confidence: boolean;
  }[];
  event_links: { event_id: string; entity: string; title: string; as_of: string }[];
};

const FRAME_COLORS: Record<string, string> = {
  loss: "#e5534b",
  gain: "#3fb950",
  responsibility: "#d29922",
  conflict: "#bc8cff",
  human_interest: "#58a6ff",
  other: "#8b949e",
};

const TIER_CATEGORIES = [
  { name: "L1 官方", itemStyle: { color: "#f0b429" } },
  { name: "L2 通讯社", itemStyle: { color: "#58a6ff" } },
  { name: "L3 财经媒体", itemStyle: { color: "#3fb950" } },
  { name: "L4 社媒", itemStyle: { color: "#bc8cff" } },
  { name: "未分级", itemStyle: { color: "#8b949e" } },
];

const AXIS = {
  axisLine: { lineStyle: { color: "#30363d" } },
  axisLabel: { color: "#8b949e" },
  splitLine: { lineStyle: { color: "#1b2129" } },
};

function tierIndex(tier: string): number {
  const i = ["L1", "L2", "L3", "L4"].indexOf(tier);
  return i >= 0 ? i : 4;
}

export default function CommandPage() {
  const [flow, setFlow] = useState<FlowSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    fetch("/api/flow/summary?days=30")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setFlow)
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [load]);

  const frameOption = useMemo<echarts.EChartsOption>(() => {
    if (!flow) return {};
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", axisPointer: { type: "line" } },
      legend: { bottom: 0, textStyle: { color: "#8b949e" }, itemWidth: 12 },
      singleAxis: {
        type: "time",
        top: 20,
        bottom: 50,
        axisLabel: { color: "#8b949e" },
        axisLine: { lineStyle: { color: "#30363d" } },
      },
      series: [
        {
          type: "themeRiver",
          emphasis: { focus: "series" },
          data: (() => {
            const days = [...new Set(flow.frames.map((f) => f.date))].sort();
            const order = Object.keys(FRAME_COLORS);
            const by = new Map(flow.frames.map((f) => [`${f.date}|${f.frame}`, f.n] as const));
            const out: [string, number, string][] = [];
            for (const d of days) {
              for (const fr of order) {
                out.push([d, by.get(`${d}|${fr}`) ?? 0, fr]);
              }
            }
            return out;
          })(),
          label: { show: false },
          color: Object.keys(FRAME_COLORS).map((k) => FRAME_COLORS[k]),
        },
      ],
    };
  }, [flow]);

  const galaxyOption = useMemo<echarts.EChartsOption>(() => {
    if (!flow) return {};
    return {
      backgroundColor: "transparent",
      tooltip: {
        formatter: (params: unknown) => {
          const p = params as { name: string; value: number };
          return `${p.name}<br/>近 30 天 ${p.value} 条`;
        },
      },
      legend: {
        bottom: 0,
        data: TIER_CATEGORIES.map((c) => c.name),
        textStyle: { color: "#8b949e" },
      },
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          force: { repulsion: 140, gravity: 0.06, friction: 0.2 },
          categories: TIER_CATEGORIES,
          itemStyle: { shadowBlur: 14, shadowColor: "rgba(88,166,255,0.35)" },
          label: { show: false },
          emphasis: { label: { show: true, color: "#c9d1d9", fontSize: 11 } },
          data: flow.sources.map((s) => ({
            name: s.source_id,
            value: s.n,
            symbolSize: 8 + Math.sqrt(s.n) * 3.2,
            category: tierIndex(s.tier),
            itemStyle: { color: TIER_CATEGORIES[tierIndex(s.tier)].itemStyle.color },
          })),
        },
      ],
    };
  }, [flow]);

  const ecgOption = useMemo<echarts.EChartsOption>(() => {
    if (!flow) return {};
    const sorted = [...flow.ndi].sort((a, b) => a.ts.localeCompare(b.ts));
    const okSeries = sorted.map((p, i) =>
      p.status === "ok" && p.ndi !== null ? [i, p.ndi] : [i, null],
    );
    const abstainSeries = sorted
      .map((p, i) => (p.status !== "ok" || p.ndi === null ? [i, 0.02] : null))
      .filter((v): v is [number, number] => v !== null);
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        formatter: (ps: unknown) => {
          const list = ps as { name: string; value: number; seriesName: string }[];
          return list
            .map(
              (p) =>
                `${p.seriesName}: ${p.value?.toFixed?.(3) ?? "—"}<br/>${p.name}`,
            )
            .join("<br/>");
        },
      },
      grid: { left: 44, right: 16, top: 30, bottom: 46 },
      dataZoom: [{ type: "slider", height: 18, bottom: 8, borderColor: "#30363d" }],
      xAxis: {
        type: "category",
        data: sorted.map((p) => p.ts.replace("T", " ").slice(5, 16)),
        ...AXIS,
      },
      yAxis: { type: "value", min: 0, max: 1, ...AXIS },
      series: [
        {
          name: "NDI (ok)",
          type: "line",
          data: okSeries,
          connectNulls: false,
          step: "end",
          lineStyle: { width: 1.6, color: "#3fb950" },
          itemStyle: { color: "#3fb950" },
          symbolSize: 5,
          areaStyle: { color: "rgba(63,185,80,0.08)" },
        },
        {
          name: "弃权",
          type: "scatter",
          symbol: "pin",
          symbolSize: 8,
          itemStyle: { color: "#4a5158" },
          data: abstainSeries,
          tooltip: { show: false },
        },
      ],
    };
  }, [flow]);

  const chainOption = useMemo<echarts.EChartsOption>(() => {
    if (!flow) return {};
    const entities = [...new Set(flow.event_links.map((l) => l.entity))];
    const nodeSet = new Map<string, { name: string; itemStyle: { color: string }; symbolSize: number; value?: number }>();
    for (const l of flow.event_links) {
      nodeSet.set(l.event_id, {
        name: l.event_id,
        symbolSize: 22,
        itemStyle: { color: "#58a6ff" },
        value: 1,
      });
    }
    for (const e of entities) {
      const deg = flow.event_links.filter((l) => l.entity === e).length;
      nodeSet.set(`ent:${e}`, {
        name: e,
        symbolSize: 14 + deg * 5,
        itemStyle: { color: "#f0b429" },
        value: deg,
      });
    }
    return {
      backgroundColor: "transparent",
      tooltip: {
        formatter: (params: unknown) => {
          const p = params as { name: string; dataType?: string; value: number };
          return p.dataType === "edge" ? "" : `${p.name}（度 ${p.value ?? 0}）`;
        },
      },
      legend: { bottom: 0, textStyle: { color: "#8b949e" }, show: false },
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          force: { repulsion: 260, gravity: 0.12, edgeLength: 90 },
          label: {
            show: true,
            color: "#c9d1d9",
            fontSize: 9,
            formatter: (params: unknown) => {
              const p = params as { name: string };
              return p.name.replace("ent:", "").slice(0, 18);
            },
          },
          emphasis: { label: { show: true, fontSize: 11 } },
          lineStyle: { color: "#30363d", width: 0.8, curveness: 0.1 },
          data: [...nodeSet.values()],
          links: flow.event_links.map((l) => ({
            source: l.event_id,
            target: `ent:${l.entity}`,
          })),
        },
      ],
    };
  }, [flow]);

  const tickerItems = useMemo(() => {
    if (!flow) return [];
    return flow.ndi
      .filter((p) => p.status === "ok" && p.ndi !== null)
      .sort((a, b) => b.ts.localeCompare(a.ts))
      .slice(0, 8)
      .map(
        (p) =>
          `${p.event_id.replace(/^ev-/, "")} NDI ${p.ndi!.toFixed(3)} (${p.language}${p.low_confidence ? "·低置信" : ""}, ${p.n_sources} 源)`,
      );
  }, [flow]);

  return (
    <div className="command-root min-h-screen bg-[#070b14] p-4 text-[#c9d1d9]">
      <style>{`
        @keyframes command-marquee { 0% { transform: translateX(0); } 100% { transform: translateX(-50%); } }
        .command-marquee { display: inline-block; white-space: nowrap; animation: command-marquee 40s linear infinite; }
      `}</style>

      <div className="mb-3 flex items-center justify-between border-b border-[#1b2129] pb-3">
        <div>
          <h1 className="text-lg font-semibold tracking-[0.35em] text-[#58a6ff]">
            OH!NEWS · COMMAND
          </h1>
          <p className="text-xs text-[#8b949e]">
            信息流指挥舱（NDI 为描述性监测指数，非收益预测器）
            {flow && ` · 更新于 ${flow.generated_at.replace("T", " ").slice(0, 19)}`}
          </p>
        </div>
        <div className="overflow-hidden max-w-[55%] text-xs text-[#f0b429]">
          {tickerItems.length > 0 && (
            <span className="command-marquee">
              {tickerItems.join("　◆　")}　◆　
              {tickerItems.join("　◆　")}
            </span>
          )}
        </div>
      </div>

      {error && <p className="text-sm text-[#e5534b]">API 不可达：{error}</p>}
      {!flow && !error && (
        <p className="text-sm text-[#8b949e]">加载信息流中…</p>
      )}

      {flow && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <Panel title="叙事框架主题河流（stance 流量 × 时间）" subtitle="loss / gain / responsibility / conflict / human_interest">
            <EChart option={frameOption} height="40vh" />
          </Panel>
          <Panel title="源星系（节点=信息源，大小=近 30 天量级，色=层级）" subtitle="拖拽漫游 · hover 查看详情">
            <EChart option={galaxyOption} height="40vh" />
          </Panel>
          <Panel title="NDI 心电（全事件点位，时间正序）" subtitle="绿色=有效 · 灰标=弃权（样本门拒绝）">
            <EChart option={ecgOption} height="40vh" />
          </Panel>
          <Panel title="事件链路网络（事件 × 实体二部图）" subtitle="节点大小=关联度 · 拖拽漫游">
            <EChart option={chainOption} height="40vh" />
          </Panel>
        </div>
      )}
    </div>
  );
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border border-[#1b2129] bg-[#0d1117]/80 p-3">
      <div className="mb-1 flex items-baseline justify-between">
        <h2 className="text-sm font-medium text-[#c9d1d9]">{title}</h2>
        <span className="text-[11px] text-[#8b949e]">{subtitle}</span>
      </div>
      {children}
    </section>
  );
}
