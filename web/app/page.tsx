"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as echarts from "echarts";

import { api } from "@/lib/api";
import { attentionPhrase, divergenceLevel, signalKindMeta, watchStatus } from "@/lib/insight";

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

function Chart({
  option,
  height = 300,
  onSeriesClick,
}: {
  option: echarts.EChartsOption;
  height?: number;
  onSeriesClick?: (params: echarts.ECElementEvent) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const cbRef = useRef(onSeriesClick);
  useEffect(() => {
    cbRef.current = onSeriesClick;
  }, [onSeriesClick]);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption(option);
    if (cbRef.current) {
      chart.on("click", (params: echarts.ECElementEvent) => cbRef.current?.(params));
    }
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
  event_links: { event_id: string; entity: string; title: string; as_of: string }[];
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

/* ── 数据面 ── */

type TodayResp = {
  date: string;
  total: number;
  signals: {
    signal_id: string;
    kind: string;
    entity_id: string;
    title: string;
    what_changed: string;
    why_it_matters: string | null;
    strength: number;
    confidence: number;
    metrics: Record<string, number>;
    evidence_ids: string[];
  }[];
};
type EventRow = {
  event_id: string;
  title: string;
  entities: string[];
  as_of: string;
  ndi: number | null;
  ndi_status: string;
  n_sources: number;
};
type WatchRow = {
  watch_id: string;
  type: string;
  query: string;
  last_summary: Record<string, unknown> | null;
};

/* ── 小件 ── */

function Chip({ children, color }: { children: React.ReactNode; color?: string }) {
  return (
    <span
      className="border px-1.5 py-0.5 font-mono text-[11px]"
      style={color ? { color, borderColor: `${color}55` } : undefined}
    >
      {children}
    </span>
  );
}

function SectionHead({ no, title, zh, question }: { no: string; title: string; zh: string; question: string }) {
  return (
    <div className="mb-3 border-t border-foreground/40 pt-3">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[11px] text-muted-foreground">{no}</span>
        <h2 className="font-paper text-xl">{title}</h2>
        <span className="text-sm text-muted-foreground">{zh}</span>
      </div>
      <p className="paper-kicker mt-0.5">{question}</p>
    </div>
  );
}

/* ── 页面 ── */

export default function IntelligencePage() {
  const [today, setToday] = useState<TodayResp | null>(null);
  const [flow, setFlow] = useState<FlowSummary | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [watches, setWatches] = useState<WatchRow[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    Promise.all([
      fetch("/api/today?top=5").then((r) => r.json()),
      api.flowSummary(14),
      api.events(7),
      api.watches(),
    ])
      .then(([t, f, e, w]) => {
        setToday(t as TodayResp);
        setFlow(f as unknown as FlowSummary);
        setEvents(e as unknown as EventRow[]);
        setWatches(((w as { watches: WatchRow[] }).watches) ?? []);
      })
      .catch((err) => setError(String(err)));
  }, []);

  /* Narrative Shifts：近 7 天 vs 前 7 天框架总量差（Question: 哪个叙事在上升/消失？） */
  const shifts = useMemo(() => {
    if (!flow) return [];
    const dayTotals: Record<string, Record<string, number>> = {};
    for (const f of flow.frames) {
      dayTotals[f.date] = dayTotals[f.date] ?? {};
      dayTotals[f.date][f.frame] = (dayTotals[f.date][f.frame] ?? 0) + f.n;
    }
    const dates = Object.keys(dayTotals).sort();
    const cutoff = new Date(dates[dates.length - 1] ?? "1970-01-01");
    cutoff.setUTCDate(cutoff.getUTCDate() - 6);
    const cutPrev = new Date(cutoff);
    cutPrev.setUTCDate(cutPrev.getUTCDate() - 7);
    const cur: Record<string, number> = {};
    const prev: Record<string, number> = {};
    for (const [d, fr] of Object.entries(dayTotals)) {
      const t = new Date(d);
      const target = t >= cutoff ? cur : t >= cutPrev ? prev : null;
      if (!target) continue;
      for (const [k, v] of Object.entries(fr)) target[k] = (target[k] ?? 0) + v;
    }
    return Object.keys(FRAME_COLORS)
      .map((frame) => {
        const c = cur[frame] ?? 0;
        const p = prev[frame] ?? 0;
        const delta = c - p;
        const pct = p > 0 ? Math.round((delta / p) * 100) : c > 0 ? 100 : 0;
        return { frame, cur: c, prev: p, delta, pct };
      })
      .filter((s) => s.cur + s.prev > 0)
      .sort((a, b) => b.delta - a.delta);
  }, [flow]);

  /* Attention × Divergence（Question: 关注何时激增？分歧何时出现？Action: 点击事件下钻） */
  const timelineOption = useMemo<echarts.EChartsOption>(() => {
    if (!flow) return {};
    const dayN: Record<string, number> = {};
    for (const r of flow.daily) dayN[r.date] = (dayN[r.date] ?? 0) + r.n;
    const dates = Object.keys(dayN).sort();
    void 0;
    const bars = dates.map((d) => [d, dayN[d]]);
    const ndiLine = flow.ndi
      .filter((p) => p.status === "ok" && p.ndi !== null)
      .map((p) => [p.ts.slice(0, 10), p.ndi as number])
      .sort((a, b) => (a[0] < b[0] ? -1 : 1));
    const marks = Object.values(
      flow.event_links.reduce<Record<string, { coord: string; title: string; eventId: string }>>(
        (acc: Record<string, { coord: string; title: string; eventId: string }>, l: { as_of: string; title: string; event_id: string }) => {
          const d = l.as_of.slice(0, 10);
          if (!acc[d]) acc[d] = { coord: d, title: l.title, eventId: l.event_id };
          return acc;
        },
        {},
      ),
    );
    return {
      ...BASE,
      legend: {
        data: ["信息关注度", "叙事分歧"],
        top: 0,
        right: 0,
        itemWidth: 14,
        itemHeight: 8,
        textStyle: { fontSize: 11, color: "#6e675c" },
      },
      xAxis: { ...BASE.xAxis, type: "category" as const },
      yAxis: [
        { ...BASE.yAxis, name: "文章量", nameTextStyle: { fontSize: 10, color: "#8a8375" } },
        {
          type: "value" as const,
          min: 0,
          max: 1,
          position: "right" as const,
          splitLine: { show: false },
          axisLabel: { fontSize: 11, color: "#8a8375" },
        },
      ],
      series: [
        {
          name: "信息关注度",
          type: "bar",
          data: bars,
          itemStyle: { color: "#c9beac", borderRadius: 1 },
          barMaxWidth: 18,
          markLine: {
            symbol: "none",
            silent: false,
            lineStyle: { color: "#a34a2a", type: "dashed" as const, width: 1 },
            label: {
              show: true,
              position: "insideEndTop" as const,
              fontSize: 10,
              color: "#a34a2a",
              formatter: (p: { name?: string }) =>
                ((p.name ?? "")).length > 12 ? `${(p.name ?? "").slice(0, 12)}…` : (p.name ?? ""),
            },
            data: marks.map((m: { coord: string; title: string; eventId: string }) => ({
              xAxis: m.coord,
              name: m.title,
              eventId: m.eventId,
            })),
          },
        },
        {
          name: "叙事分歧",
          type: "line",
          yAxisIndex: 1,
          data: ndiLine,
          smooth: false,
          step: "end" as const,
          lineStyle: { color: "#8b2635", width: 2 },
          itemStyle: { color: "#8b2635" },
          symbolSize: 6,
          endLabel: {
            show: true,
            fontSize: 10,
            color: "#8b2635",
            formatter: () => "分歧",
          },
        },
      ],
    } as echarts.EChartsOption;
  }, [flow]);

  /* Narrative Shifts 双向条 */
  const shiftOption = useMemo<echarts.EChartsOption>(() => {
    if (!shifts.length) return {};
    return {
      ...BASE,
      grid: { left: 8, right: 40, top: 8, bottom: 8, containLabel: true },
      xAxis: { type: "value" as const, splitLine: { show: false }, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false } },
      yAxis: {
        type: "category" as const,
        data: shifts.map((s) => FRAME_LABELS[s.frame]),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { fontSize: 12, color: "#3a352c" },
        splitLine: { show: false },
      },
      series: [
        {
          type: "bar",
          data: shifts.map((s) => ({
            value: s.delta,
            itemStyle: { color: s.delta >= 0 ? "#5e8a5e" : "#b3543f", borderRadius: 1 },
          })),
          label: {
            show: true,
            position: "right" as const,
            fontSize: 11,
            color: "#6e675c",
            formatter: (p: { value: number }) =>
              p.value >= 0 ? `+${p.value}` : `${p.value}`,
          },
        },
      ],
    } as echarts.EChartsOption;
  }, [shifts]);

  if (error) return <p className="text-destructive">加载失败：{error}</p>;

  const signals = today?.signals ?? [];
  const askHref = (question: string) => `/research?q=${encodeURIComponent(question)}`;

  return (
    <div className="grid gap-x-10 gap-y-8 lg:grid-cols-12">
      {/* ── Main 8 栏 ── */}
      <div className="lg:col-span-8">
        <header className="mb-4">
          <p className="paper-kicker">Today&apos;s Intelligence · {today?.date ?? "…"}</p>
          <h1 className="font-paper mt-1 text-3xl tracking-tight">
            {today
              ? today.total > 0
                ? `系统发现 ${today.total} 个值得关注的变化`
                : "今日无显著变化检出"
              : "正在扫描信息流…"}
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            每天系统从全部信息源中筛出真正发生变化的对象，压缩为最重要的信号；点击 Explore 进入事件与证据。
          </p>
        </header>

        <div className="flex flex-col">
          {signals.map((s, i) => {
            const eid = s.evidence_ids[0];
            const exploreHref = eid
              ? `/events/${encodeURIComponent(eid)}`
              : `/events?q=${encodeURIComponent(s.entity_id)}`;
            const z = s.metrics["z"];
            return (
              <article key={s.signal_id} className="border-b border-border/60 py-5 first:pt-1">
                <div className="flex items-baseline gap-3">
                  <span className="font-paper text-3xl font-semibold text-muted-foreground/35">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Chip color={signalKindMeta(s.kind).color}>
                        {signalKindMeta(s.kind).label} · {signalKindMeta(s.kind).zh}
                      </Chip>
                      <h2 className="font-paper text-lg leading-tight">{s.title}</h2>
                    </div>
                    <p className="mt-1.5 text-sm leading-6">{s.what_changed}</p>
                    {s.why_it_matters && (
                      <p className="mt-1 text-sm leading-6 text-muted-foreground">{s.why_it_matters}</p>
                    )}
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <span className="font-paper text-2xl">{Math.round(s.strength)}</span>
                      <span className="paper-kicker">/100 强度</span>
                      {z !== undefined && <Chip>{attentionPhrase(z)}</Chip>}
                      <Chip>conf {s.confidence.toFixed(2)}</Chip>
                      {eid && <Chip>证据事件 {eid}</Chip>}
                    </div>
                  </div>
                  <Link
                    href={exploreHref}
                    className="shrink-0 border border-foreground/60 px-3 py-1.5 text-xs font-medium hover:bg-foreground hover:text-background"
                  >
                    Explore →
                  </Link>
                </div>
              </article>
            );
          })}
          {today && signals.length === 0 && (
            <p className="text-sm text-muted-foreground">
              信息量不足以支撑任何结论时，系统选择弃权而非硬凑数字——这是刻意设计。
            </p>
          )}
        </div>

        {/* Attention × Divergence */}
        <div className="mt-8">
          <SectionHead
            no="§2"
            title="What is changing"
            zh="注意力 × 分歧时间轴"
            question="Question：关注何时激增？分歧何时出现？｜Action：点击虚线事件标记下钻"
          />
          {flow && (
            <Chart
              option={timelineOption}
              height={280}
              onSeriesClick={(params) => {
                if ((params.dataType as string) === "markLine") {
                  const data = params.data as { eventId?: string };
                  if (data.eventId) router.push(`/events/${encodeURIComponent(data.eventId)}`);
                }
              }}
            />
          )}
          {!flow && <p className="text-sm text-muted-foreground">加载中…</p>}
        </div>

        {/* Narrative Shifts */}
        <div className="mt-8">
          <SectionHead
            no="§3"
            title="Narrative shifts"
            zh="叙事迁移（近 7 天 vs 前 7 天）"
            question="Question：哪个叙事在上升、哪个在消失？｜Action：进入事件页查看证据"
          />
          {shifts.length > 0 ? <Chart option={shiftOption} height={170} /> : (
            <p className="text-sm text-muted-foreground">窗口内框架数据不足。</p>
          )}
          <div className="mt-1 flex flex-wrap gap-3">
            {shifts.slice(0, 3).map((s) => (
              <span key={s.frame} className="text-[11px] text-muted-foreground">
                {FRAME_LABELS[s.frame]}：{s.prev}→{s.cur} 篇（{s.delta >= 0 ? "+" : ""}{s.delta}）
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* ── Sidebar 4 栏 ── */}
      <aside className="flex flex-col gap-8 lg:col-span-4">
        <section>
          <SectionHead no="§4" title="Active events" zh="进行中的事件" question="Question：现在有哪些事件在演化？" />
          <div className="flex flex-col">
            {events.slice(0, 6).map((e) => {
              const lv = divergenceLevel(e.ndi_status === "ok" ? e.ndi : null);
              return (
                <Link
                  key={e.event_id}
                  href={`/events/${e.event_id}`}
                  className="border-b border-border/50 py-2 text-sm hover:text-primary"
                >
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-[11px] text-muted-foreground">{e.as_of.slice(5, 10)}</span>
                    <span className="min-w-0 flex-1 truncate">{e.title}</span>
                  </div>
                  <div className="mt-0.5 pl-8">
                    <span className="text-[11px]" style={{ color: lv.color }}>
                      ● {lv.zh}
                    </span>
                    <span className="ml-2 text-[11px] text-muted-foreground">{e.n_sources} 源</span>
                  </div>
                </Link>
              );
            })}
            {events.length === 0 && <p className="text-sm text-muted-foreground">近 7 日无成组事件。</p>}
          </div>
          <Link href="/events" className="mt-1 inline-block text-xs text-muted-foreground hover:text-primary">
            全部事件 →
          </Link>
        </section>

        <section>
          <SectionHead no="§5" title="Your watchlist" zh="关注状态" question="Question：我关注的东西最近有什么变化？" />
          <div className="flex flex-col gap-1.5">
            {watches.slice(0, 6).map((w) => {
              const st = watchStatus(w.last_summary);
              return (
                <Link key={w.watch_id} href="/watch" className="flex items-baseline gap-2 text-sm hover:text-primary">
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: st.color }} />
                  <span className="min-w-0 flex-1 truncate">{w.query}</span>
                  <span className="text-[11px]" style={{ color: st.color }}>
                    {st.zh}
                  </span>
                </Link>
              );
            })}
            {watches.length === 0 && (
              <p className="text-sm text-muted-foreground">
                尚无订阅——在 <Link href="/watch" className="underline">Watchlist</Link> 添加实体/主题/问题。
              </p>
            )}
          </div>
        </section>

        <section>
          <SectionHead no="§6" title="Ask the analyst" zh="问分析师" question="Agent 从问题出发，产出可归档的研究结论" />
          <form
            onSubmit={(ev) => {
              ev.preventDefault();
              if (q.trim()) router.push(askHref(q.trim()));
            }}
          >
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Why is the Fed narrative changing?"
              className="w-full border border-border bg-card px-3 py-2 text-sm outline-none focus:border-foreground"
            />
          </form>
          <div className="mt-2 flex flex-col gap-1">
            {["为什么市场预期和官方表态出现偏离？", "哪些信源正在推动当前叙事？", "这个变化是短期噪声还是持续趋势？"].map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => router.push(askHref(s))}
                className="text-left text-xs text-muted-foreground hover:text-primary"
              >
                · {s}
              </button>
            ))}
          </div>
        </section>
      </aside>
    </div>
  );
}
