"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type TimelineResponse } from "@/lib/api";

const GROUPS: { label: string; ids: string[] }[] = [
  { label: "央行", ids: ["fed", "fomc", "pboc", "ecb", "boj", "boe", "rba_au", "boc_ca"] },
  { label: "政府", ids: ["white_house", "us_treasury", "ustr", "sec", "china_mof", "pboc_gov"] },
  { label: "公司与人物", ids: ["powell", "musk", "nvidia", "tesla", "apple", "microsoft", "google", "openai", "trump"] },
];

const DAYS_OPTIONS = [7, 30, 90];

function TimelineChart({
  data,
  onPickEvent,
}: {
  data: TimelineResponse;
  onPickEvent: (eventId: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const dates = data.points.map((p) => p.date.slice(5));
    const chart = echarts.init(ref.current);
    const eventDays = data.points
      .map((p, i) => ({ i, n: p.n_events, ids: p.event_ids }))
      .filter((x) => x.n > 0);
    const eventIds: string[] = [];
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { data: ["文章量", "NDI", "事件"], textStyle: { color: "#9ca3af" } },
      grid: { left: 48, right: 52, top: 40, bottom: 32 },
      xAxis: { type: "category", data: dates, axisLabel: { color: "#9ca3af" } },
      yAxis: [
        { type: "value", name: "文章", axisLabel: { color: "#9ca3af" }, nameTextStyle: { color: "#9ca3af" } },
        { type: "value", name: "NDI", min: 0, max: 1, axisLabel: { color: "#9ca3af" }, nameTextStyle: { color: "#9ca3af" } },
      ],
      series: [
        {
          name: "文章量",
          type: "bar",
          data: data.points.map((p) => p.articles),
          itemStyle: { color: "#8b949e", opacity: 0.55 },
          barMaxWidth: 18,
        },
        {
          name: "NDI",
          type: "line",
          yAxisIndex: 1,
          data: data.points.map((p) => p.ndi),
          connectNulls: true,
          lineStyle: { width: 2, color: "#3fb950" },
          itemStyle: { color: "#3fb950" },
        },
        {
          name: "事件",
          type: "scatter",
          data: eventDays.map((x) => ({
            value: [x.i, x.n],
            eventIds: x.ids,
            symbolSize: 10 + x.n * 4,
            itemStyle: { color: "#f0b429" },
          })),
        },
      ],
    });
    chart.on("click", (p) => {
      const ids = (p.data as { eventIds?: string[] })?.eventIds;
      if (ids && ids.length > 0) onPickEvent(ids[0]);
    });
    void eventIds;
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [data, onPickEvent]);

  return <div ref={ref} className="h-80 w-full" />;
}

export default function TimelinePage() {
  const [entity, setEntity] = useState("fed");
  const [days, setDays] = useState(30);
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    api
      .entityTimeline(entity, days)
      .then(setData)
      .catch((err) => setError(String(err)));
  }, [entity, days]);

  const knownIds = useMemo(() => new Set(GROUPS.flatMap((g) => g.ids)), []);
  const groups = useMemo(() => {
    if (knownIds.has(entity)) return GROUPS;
    return [...GROUPS, { label: "其他", ids: [entity] }];
  }, [entity, knownIds]);

  const nEvents = data?.events.length ?? 0;
  const nArticles = data ? data.points.reduce((s, p) => s + p.articles, 0) : 0;
  const ndiPoints = data ? data.points.filter((p) => p.ndi !== null).length : 0;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">叙事时间轴</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          实体级生命周期：文章量 × 事件 × NDI（描述性指数，非预测器）。点事件标记下钻证据链。
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {groups.map((g) => (
          <div key={g.label} className="flex items-center gap-1">
            <span className="mr-1 text-xs text-muted-foreground">{g.label}</span>
            {g.ids.map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => setEntity(id)}
                className={
                  "rounded-full border px-2.5 py-1 font-mono text-xs transition " +
                  (id === entity
                    ? "border-foreground bg-foreground text-background"
                    : "border-border text-muted-foreground hover:text-foreground")
                }
              >
                {id}
              </button>
            ))}
          </div>
        ))}
        <div className="ml-auto flex gap-1">
          {DAYS_OPTIONS.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={
                "rounded-full border px-2.5 py-1 text-xs " +
                (d === days
                  ? "border-foreground bg-foreground text-background"
                  : "border-border text-muted-foreground hover:text-foreground")
              }
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-destructive text-sm">{error}</p>}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-baseline gap-3 text-base">
            <span className="font-mono">{entity}</span>
            <span className="text-xs font-normal text-muted-foreground">
              {nArticles} 篇文章 · {nEvents} 个事件 · {ndiPoints} 个 NDI 点位
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data ? (
            data.points.some((p) => p.articles > 0 || p.n_events > 0) ? (
              <TimelineChart data={data} onPickEvent={(id) => (window.location.href = `/events/${id}`)} />
            ) : (
              <p className="text-sm text-muted-foreground">
                窗口内无该实体的文章或事件——可尝试扩大时间范围。
              </p>
            )
          ) : (
            <p className="text-sm text-muted-foreground">加载中…</p>
          )}
        </CardContent>
      </Card>

      {data && data.events.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">事件清单（点击进入证据链）</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col divide-y divide-border/60">
              {data.events.map((ev) => (
                <Link
                  key={ev.event_id}
                  href={`/events/${ev.event_id}`}
                  className="flex items-baseline gap-3 py-2 text-sm hover:text-foreground"
                >
                  <span className="font-mono text-xs text-muted-foreground">
                    {ev.as_of.slice(0, 10)}
                  </span>
                  <span className="flex-1 truncate">{ev.title}</span>
                  <span className="font-mono text-xs">
                    NDI {ev.ndi !== null ? ev.ndi.toFixed(3) : "abstain"}
                  </span>
                </Link>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
