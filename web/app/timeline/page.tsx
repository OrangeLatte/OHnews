"use client";

import { useEffect, useMemo, useState } from "react";
import * as echarts from "echarts";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type TimelineResponse } from "@/lib/api";
import { SIGNAL } from "@/lib/tokens";
import { ChartBase } from "@/components/visualizations/chart-base";

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
  const option = useMemo<echarts.EChartsOption>(() => {
    const dates = data.points.map((p) => p.date.slice(5));
    const eventDays = data.points
      .map((p, i) => ({ i, n: p.n_events, ids: p.event_ids }))
      .filter((x) => x.n > 0);
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { data: ["文章量", "NDI", "事件"], textStyle: { color: SIGNAL.muted } },
      grid: { left: 48, right: 52, top: 40, bottom: 32 },
      xAxis: { type: "category", data: dates },
      yAxis: [
        { type: "value", name: "文章", nameTextStyle: { color: SIGNAL.muted } },
        { type: "value", name: "NDI", min: 0, max: 1, nameTextStyle: { color: SIGNAL.muted } },
      ],
      series: [
        {
          name: "文章量",
          type: "bar",
          data: data.points.map((p) => p.articles),
          itemStyle: { color: SIGNAL.muted, opacity: 0.55 },
          barMaxWidth: 18,
        },
        {
          name: "NDI",
          type: "line",
          yAxisIndex: 1,
          data: data.points.map((p) => p.ndi),
          connectNulls: true,
          lineStyle: { width: 2, color: SIGNAL.divergence },
          itemStyle: { color: SIGNAL.divergence },
        },
        {
          name: "事件",
          type: "scatter",
          data: eventDays.map((x) => ({
            value: [x.i, x.n],
            eventIds: x.ids,
            symbolSize: 10 + x.n * 4,
            itemStyle: { color: SIGNAL.attention },
          })),
        },
      ],
    };
  }, [data]);

  return (
    <ChartBase
      option={option}
      height="20rem"
      state={data.points.length ? "ready" : "empty"}
      onSeriesClick={(p) => {
        const ids = (p.data as { eventIds?: string[] })?.eventIds;
        if (ids && ids.length > 0) onPickEvent(ids[0]);
      }}
    />
  );
}

export default function TimelinePage() {
  const router = useRouter();
  const [entity, setEntity] = useState("fed");
  const [days, setDays] = useState(30);
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .entityTimeline(entity, days)
      .then((d) => {
        if (alive) setData(d);
      })
      .catch((err) => {
        if (alive) setError(String(err));
      });
    return () => {
      alive = false;
    };
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
        <h1 className="font-paper text-2xl tracking-tight">叙事时间轴</h1>
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
              <TimelineChart data={data} onPickEvent={(id) => router.push(`/events/${id}`)} />
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
              {data.events.map((ev, i) => {
                const prev = data.events[i + 1];
                const shift =
                  prev && ev.dominant_frame && prev.dominant_frame && ev.dominant_frame !== prev.dominant_frame
                    ? `${prev.dominant_frame} → ${ev.dominant_frame}`
                    : null;
                return (
                  <Link
                    key={ev.event_id}
                    href={`/events/${ev.event_id}`}
                    className="flex items-baseline gap-3 py-2 text-sm hover:text-foreground"
                  >
                    <span className="font-mono text-xs text-muted-foreground">
                      {ev.as_of.slice(0, 10)}
                    </span>
                    <span className="flex-1 truncate">{ev.title}</span>
                    {shift && (
                      <span className="font-paper text-xs italic text-primary">{shift}</span>
                    )}
                    <span className="font-mono text-xs">
                      NDI {ev.ndi !== null ? ev.ndi.toFixed(3) : "abstain"}
                    </span>
                  </Link>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
