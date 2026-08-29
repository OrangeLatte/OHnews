"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import * as echarts from "echarts";

import { api } from "@/lib/api";

/* ── Observable 风图表基座：细轴/淡网格/低饱和大地色板/线末标注 ── */

const TIER_COLORS: Record<string, string> = {
  L1: "#a9834f",
  L2: "#6f87a6",
  L3: "#7f9a7a",
  L4: "#a495b8",
  "?": "#b8b2a5",
};
const TIER_LABELS: Record<string, string> = {
  L1: "官方 L1",
  L2: "通讯社 L2",
  L3: "财经媒体 L3",
  L4: "社媒 L4",
  "?": "未分级",
};

const FRAME_COLORS: Record<string, string> = {
  loss: "#b3543f",
  gain: "#5e8a5e",
  responsibility: "#b08d3e",
  conflict: "#8a6fae",
  human_interest: "#5e83a8",
  other: "#9a948a",
};
const FRAME_LABELS: Record<string, string> = {
  loss: "损失",
  gain: "收益",
  responsibility: "责任",
  conflict: "冲突",
  human_interest: "人情味",
  other: "其他",
};

const BASE = {
  textStyle: { fontFamily: "inherit", color: "#6e675c" },
  grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
  xAxis: {
    type: "time" as const,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { fontSize: 11, color: "#8a8375" },
    splitLine: { show: false },
  },
  yAxis: {
    type: "value" as const,
    splitLine: { lineStyle: { color: "#ece5d8", width: 1 } },
    axisLabel: { fontSize: 11, color: "#8a8375" },
  },
  tooltip: {
    trigger: "axis" as const,
    backgroundColor: "#fffdf8",
    borderColor: "#d8d0c0",
    borderWidth: 1,
    textStyle: { fontSize: 12, color: "#3a352c" },
    extraCssText: "box-shadow:none;",
  },
};

function Chart({ option, height = 300 }: { option: echarts.EChartsOption; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption(option);
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [option]);
  return <div ref={ref} style={{ width: "100%", height }} />;
}

function Panel({
  title,
  subtitle,
  legend,
  children,
}: {
  title: string;
  subtitle: string;
  legend?: { label: string; color: string }[];
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-foreground/20 pt-3">
      <h2 className="font-paper text-lg">{title}</h2>
      <p className="mb-2 text-xs leading-5 text-muted-foreground">{subtitle}</p>
      {legend && (
        <div className="mb-1 flex flex-wrap gap-4">
          {legend.map((l) => (
            <span key={l.label} className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className="inline-block h-2 w-2.5" style={{ backgroundColor: l.color }} />
              {l.label}
            </span>
          ))}
        </div>
      )}
      {children}
    </section>
  );
}

/* ── 数据面 ── */

type FlowSummary = {
  daily: { date: string; tier: string; language: string; n: number }[];
  frames: { date: string; frame: string; n: number }[];
  sources: { source_id: string; n: number; tier: string; language: string; last_seen: string | null }[];
  ndi: { event_id: string; ts: string; ndi: number | null; status: string; language: string }[];
};
type TimelineResponse = {
  points: { date: string; articles: number; ndi: number | null; event_ids: string[] }[];
  events: { event_id: string; title: string; as_of: string; ndi: number | null; dominant_frame?: string | null }[];
};

const ENTITIES = [
  ["fed", "美联储"],
  ["ecb", "欧央行"],
  ["boe", "英央行"],
  ["boj", "日央行"],
  ["trump", "Trump"],
  ["china_mof", "中国财政部"],
  ["opec", "OPEC"],
] as const;

export default function DashboardPage() {
  const [flow, setFlow] = useState<FlowSummary | null>(null);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [entity, setEntity] = useState("fed");
  const [days, setDays] = useState(30);

  useEffect(() => {
    api
      .flowSummary(30)
      .then((d) => setFlow(d as unknown as FlowSummary))
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    api
      .entityTimeline(entity, days)
      .then(setTimeline)
      .catch(() => undefined);
  }, [entity, days]);

  const kpis = useMemo(() => {
    if (!flow) return null;
    const byDay = new Map<string, number>();
    for (const d of flow.daily) byDay.set(d.date, (byDay.get(d.date) ?? 0) + d.n);
    const last = [...byDay.entries()].sort(([a], [b]) => (a < b ? 1 : -1))[0];
    const active = flow.sources.filter((s) => s.n > 0).length;
    const ndiOk = flow.ndi.filter((p) => p.status === "ok" && p.ndi !== null);
    const latestNdi = ndiOk.length > 0 ? ndiOk[ndiOk.length - 1] : null;
    return {
      todayArticles: last?.[1] ?? 0,
      todayDate: last?.[0] ?? "",
      activeSources: active,
      nNdi: ndiOk.length,
      latestNdi: latestNdi?.ndi ?? null,
    };
  }, [flow]);

  /* 图1：信息流脉搏——每日文章量按层级堆叠 + NDI 线（右轴） */
  const pulseOption = useMemo<echarts.EChartsOption>(() => {
    if (!flow) return {};
    const tiers = ["L1", "L2", "L3", "L4", "?"];
    const dates = [...new Set(flow.daily.map((d) => d.date))].sort();
    const series: echarts.SeriesOption[] = tiers
      .map((t) => ({
        name: t,
        type: "line" as const,
        stack: "total",
        areaStyle: { opacity: 0.5 },
        lineStyle: { width: 0 },
        symbol: "none" as const,
        emphasis: { focus: "series" as const },
        data: dates.map((d) => [
          d,
          flow.daily.filter((x) => x.date === d && x.tier === t).reduce((a, b) => a + b.n, 0),
        ]),
      }))
      .filter((s) => flow.daily.some((d) => d.tier === s.name));
    series.push({
      name: "NDI",
      type: "line" as const,
      yAxisIndex: 1,
      data: flow.ndi
        .filter((p) => p.status === "ok" && p.ndi !== null)
        .map((p) => [p.ts.slice(0, 10), p.ndi as number]),
      lineStyle: { width: 2, color: "#8b2635" } as never,
      itemStyle: { color: "#8b2635" },
      symbol: "circle",
      symbolSize: 6,
      endLabel: {
        show: true,
        formatter: "NDI",
        color: "#8b2635",
        fontSize: 11,
        fontFamily: "Georgia",
      },
    });
    return {
      ...BASE,
      legend: { show: false },
      yAxis: [
        {
          type: "value" as const,
          splitLine: { lineStyle: { color: "#ece5d8", width: 1 } },
          axisLabel: { fontSize: 11, color: "#8a8375" },
        },
        {
          type: "value" as const,
          min: 0,
          max: 1,
          splitLine: { show: false },
          axisLabel: { fontSize: 10, color: "#8b2635", formatter: (v: number) => v.toFixed(1) },
        },
      ],
      series,
    } as echarts.EChartsOption;
  }, [flow]);

  /* 图2：框架主题流 */
  const frameOption = useMemo<echarts.EChartsOption>(() => {
    if (!flow) return {};
    const frames = ["loss", "gain", "responsibility", "conflict", "human_interest", "other"];
    const dates = [...new Set(flow.frames.map((f) => f.date))].sort();
    return {
      ...BASE,
      legend: { show: false },
      series: frames
        .map((f) => ({
          name: f,
          type: "line" as const,
          stack: "frames",
          areaStyle: { opacity: 0.55 },
          lineStyle: { width: 0 },
          symbol: "none" as const,
          data: dates.map((d) => [
            d,
            flow.frames.filter((x) => x.date === d && x.frame === f).reduce((a, b) => a + b.n, 0),
          ]),
        }))
        .filter((s) => flow.frames.some((x) => x.frame === s.name)),
    } as echarts.EChartsOption;
  }, [flow]);

  /* 图3：源贡献排行（近 30 日 Top12，横向条） */
  const sourceOption = useMemo<echarts.EChartsOption>(() => {
    if (!flow) return {};
    const top = flow.sources.slice(0, 12).reverse();
    return {
      grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true },
      xAxis: {
        type: "value" as const,
        splitLine: { lineStyle: { color: "#ece5d8" } },
        axisLabel: { fontSize: 10, color: "#8a8375" },
      },
      yAxis: {
        type: "category" as const,
        data: top.map((s) => s.source_id),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { fontSize: 11, color: "#6e675c" },
      },
      tooltip: { ...BASE.tooltip, trigger: "item" as const },
      series: [
        {
          type: "bar" as const,
          data: top.map((s) => ({
            value: s.n,
            itemStyle: { color: TIER_COLORS[s.tier] ?? TIER_COLORS["?"], opacity: 0.85, borderRadius: 1 },
          })),
          barWidth: 12,
          label: {
            show: true,
            position: "right" as const,
            fontSize: 10,
            color: "#8a8375",
          },
        },
      ],
    } as echarts.EChartsOption;
  }, [flow]);

  /* 图4：叙事时间轴（实体级，并入看板） */
  const tlOption = useMemo<echarts.EChartsOption>(() => {
    if (!timeline) return {};
    return {
      ...BASE,
      legend: { show: false },
      yAxis: [
        {
          type: "value" as const,
          splitLine: { lineStyle: { color: "#ece5d8" } },
          axisLabel: { fontSize: 10, color: "#8a8375" },
        },
        {
          type: "value" as const,
          min: 0,
          max: 1,
          splitLine: { show: false },
          axisLabel: { fontSize: 10, color: "#8b2635" },
        },
      ],
      series: [
        {
          name: "文章量",
          type: "bar" as const,
          data: timeline.points.map((p) => [p.date, p.articles]),
          itemStyle: { color: "#c9c0ae", opacity: 0.8 },
          barWidth: "70%",
        },
        {
          name: "NDI",
          type: "line" as const,
          yAxisIndex: 1,
          data: timeline.points.map((p) => [p.date, p.ndi]),
          connectNulls: true,
          lineStyle: { width: 2, color: "#8b2635" },
          itemStyle: { color: "#8b2635" },
          symbolSize: 5,
        },
        {
          name: "事件",
          type: "scatter" as const,
          data: timeline.points
            .filter((p) => p.event_ids.length > 0)
            .map((p) => [p.date, p.ndi ?? 0.05]),
          symbolSize: 12,
          itemStyle: { color: "#b08d3e", opacity: 0.9 },
        },
      ],
    } as echarts.EChartsOption;
  }, [timeline]);

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="font-paper text-3xl tracking-tight">情报看板</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          全部信息源产出与叙事分歧的一页总览 · 每张图回答一个问题
        </p>
      </header>

      {kpis && (
        <div className="grid grid-cols-2 gap-px border border-foreground/15 bg-foreground/15 md:grid-cols-4">
          {[
            { v: String(kpis.todayArticles), l: `文章量 · ${kpis.todayDate}` },
            { v: String(kpis.activeSources), l: "活跃信息源（近30日）" },
            { v: String(kpis.nNdi), l: "NDI 有效点位" },
            {
              v: kpis.latestNdi !== null ? kpis.latestNdi.toFixed(3) : "abstain",
              l: "最新叙事分歧指数",
            },
          ].map((k) => (
            <div key={k.l} className="bg-card px-5 py-4">
              <div className="font-paper text-3xl">{k.v}</div>
              <div className="paper-kicker !text-[10px]">{k.l}</div>
            </div>
          ))}
        </div>
      )}

      <Panel
        title="信息流脉搏"
        subtitle="过去 30 天全部信息源的文章产出，按可信层级分层堆叠；红线为叙事分歧指数 NDI（右轴 0-1）。层级结构是否稳定、分歧何时抬头，一眼可辨。"
        legend={[
          ...Object.entries(TIER_COLORS)
            .filter(([k]) => k !== "?")
            .map(([k, c]) => ({ label: TIER_LABELS[k], color: c })),
          { label: "NDI（右轴）", color: "#8b2635" },
        ]}
      >
        <Chart option={pulseOption} height={320} />
      </Panel>

      <Panel
        title="框架构成"
        subtitle="每日文章按五框架+其他分类堆叠（损失/收益/责任/冲突/人情味）。框架配比的变化先于情绪变化——责任框架抬头通常意味着归因争论开始。"
        legend={Object.entries(FRAME_COLORS).map(([k, c]) => ({ label: FRAME_LABELS[k], color: c }))}
      >
        <Chart option={frameOption} height={240} />
      </Panel>

      <Panel
        title="源贡献排行"
        subtitle="近 30 日产出量 Top 12 信息源，颜色为可信层级。快速识别主力源与断层——某层长期缺位时，该层视角在 NDI 中系统性缺席。"
        legend={Object.entries(TIER_COLORS)
          .filter(([k]) => k !== "?")
          .map(([k, c]) => ({ label: TIER_LABELS[k], color: c }))}
      >
        <Chart option={sourceOption} height={300} />
      </Panel>

      <Panel
        title="叙事时间轴"
        subtitle="选定实体的逐日文章量（灰柱）与 NDI（红线，右轴）；金色圆点为成事件日。观察官方叙事密度与分歧抬头的先后关系。"
      >
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {ENTITIES.map(([id, zh]) => (
            <button
              key={id}
              type="button"
              onClick={() => setEntity(id)}
              className={`border px-2.5 py-1 text-xs transition-colors ${
                entity === id
                  ? "border-foreground bg-foreground text-background"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {zh}
            </button>
          ))}
          <span className="ml-auto flex gap-1">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDays(d)}
                className={`px-2 py-1 text-xs ${
                  days === d ? "font-semibold text-foreground" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {d}d
              </button>
            ))}
          </span>
        </div>
        <Chart option={tlOption} height={260} />
        {timeline && timeline.events.length > 0 && (
          <div className="mt-2 border-t border-border/60 pt-2">
            {timeline.events.slice(0, 5).map((ev) => (
              <Link
                key={ev.event_id}
                href={`/events/${ev.event_id}`}
                className="flex items-baseline gap-3 py-1.5 text-sm hover:text-primary"
              >
                <span className="font-mono text-xs text-muted-foreground">{ev.as_of.slice(0, 10)}</span>
                <span className="flex-1 truncate">{ev.title}</span>
                {ev.dominant_frame && (
                  <span className="font-paper text-xs italic text-primary">{FRAME_LABELS[ev.dominant_frame] ?? ev.dominant_frame}</span>
                )}
                <span className="font-mono text-xs">
                  {ev.ndi !== null ? `NDI ${ev.ndi.toFixed(3)}` : "abstain"}
                </span>
              </Link>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
