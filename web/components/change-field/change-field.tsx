"use client";

/**
 * Narrative Change Field（T8）：每日×泳道×框架堆叠面积。
 * 数据面 /api/change-field（后端拼图）；本组件只做 option 映射。
 */

import { useEffect, useState } from "react";
import { ChartBase } from "@/components/visualizations/chart-base";
import type { EChartsOption } from "echarts";
import { api } from "@/lib/api";
import { SIGNAL } from "@/lib/tokens";
import { track } from "@/lib/track";

type FieldPayload = Awaited<ReturnType<typeof api.changeField>>;
type QChange = NonNullable<FieldPayload["changes"]>[number];
type Point = NonNullable<FieldPayload["series"]>[number];

function laneTotal(p: Point, lane: string): number {
  const m = p.lanes?.[lane];
  if (!m) return 0;
  let t = 0;
  for (const v of Object.values(m)) t += v;
  return t;
}

const LANE_META: Record<string, { label: string; color: string }> = {
  official: { label: "官方", color: SIGNAL.confirmed },
  press: { label: "权威媒体", color: SIGNAL.narrative },
  market: { label: "市场媒体", color: SIGNAL.attention },
  social: { label: "社媒", color: SIGNAL.muted },
  unknown: { label: "未分级", color: "#c9c2b4" },
};

export function ChangeFieldPanel({ days = 30 }: { days?: number }) {
  const [data, setData] = useState<FieldPayload | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .changeField(days)
      .then((d) => {
        if (alive) setData(d);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [days]);

  if (failed) return null; // 静默让位：调查台主任务是事件列表
  if (!data) {
    return (
      <section className="cf-section" aria-label="叙事场" aria-busy="true">
        <p className="cf-kicker">NARRATIVE CHANGE FIELD · 叙事场</p>
        <p className="cf-note">正在按日汇聚四路信息流…</p>
      </section>
    );
  }
  const points = data.series ?? [];
  const changes = data.changes ?? [];
  if (points.length === 0) {
    return (
      <section className="cf-section" aria-label="叙事场">
        <p className="cf-kicker">NARRATIVE CHANGE FIELD · 叙事场</p>
        <p className="cf-note">窗口内暂无标注数据（样本不足或语料未覆盖）。</p>
      </section>
    );
  }

  const dates = points.map((p) => p.date);
  const lanes = Object.keys(LANE_META).filter((lane) =>
    points.some((p) => laneTotal(p, lane) > 0),
  );
  const option: EChartsOption = {
    tooltip: {
      trigger: "axis",
      formatter: (raw: unknown) => {
        const params = raw as Array<{ axisValue: string; seriesName: string; value: number }>;
        const day = params[0]?.axisValue;
        const point = points.find((p) => p.date === day);
        const lines = (params ?? []).map(
          (q) => `${LANE_META[q.seriesName]?.label ?? q.seriesName}：${q.value} 篇`,
        );
        if (point) {
          const detail = Object.entries(point.lanes ?? {})
            .map(
              ([lane, frames]) =>
                `${LANE_META[lane]?.label ?? lane}：${Object.entries(frames ?? {})
                  .sort((a, b) => b[1] - a[1])
                  .map(([f, n]) => `${f} ${n}`)
                  .join(" / ")}`,
            )
            .join("<br/>");
          if (detail) lines.push(detail);
        }
        return `${day}<br/>${lines.join("<br/>")}`;
      },
    },
    legend: { top: 0, textStyle: { color: SIGNAL.muted, fontSize: 11 } },
    grid: { left: 40, right: 12, top: 28, bottom: 24 },
    xAxis: { type: "category", data: dates, axisLabel: { color: SIGNAL.muted } },
    yAxis: {
      type: "value",
      name: "标注条数",
      nameTextStyle: { color: SIGNAL.muted },
      axisLabel: { color: SIGNAL.muted },
      splitLine: { lineStyle: { color: "#e5e0d3" } },
    },
    series: lanes.map((lane) => ({
      name: lane,
      type: "line" as const,
      stack: "total",
      areaStyle: { opacity: 0.55 },
      lineStyle: { width: 1 },
      symbol: "none",
      emphasis: { focus: "series" },
      data: points.map((p) => laneTotal(p, lane)),
      color: LANE_META[lane].color,
    })),
  };

  return (
    <section className="cf-section" aria-label="叙事场：按日泳道堆叠">
      <p className="cf-kicker">NARRATIVE CHANGE FIELD · 叙事场（近 {data.days} 天）</p>
      <p className="cf-note">
        每日标注条数按来源分级堆叠；悬停查看当日各泳道框架构成。数据截至{" "}
        {data.freshness.as_of}（UTC）。
      </p>
      <div className="cf-body">
        <div className="cf-chart">
          <ChartBase option={option} state="ready" height="18rem" />
        </div>
        <aside className="cf-side" aria-label="合格变化点">
          <p className="cf-side-title">场内变化点</p>
          {changes.length === 0 && <p className="cf-note">窗口内暂无过质量门的变化。</p>}
          {changes.map((c: QChange) => (
            <div key={c.change_id} className="cf-change">
              <button
                type="button"
                className="cf-change-head"
                onClick={() => {
                  const next = open === c.change_id ? null : c.change_id;
                  setOpen(next);
                  if (next) {
                    track("change_opened", { objectId: c.change_id, fromPage: "/investigate#field" });
                  }
                }}
              >
                {c.headline}
              </button>
              {open === c.change_id && (
                <div className="cf-change-body">
                  <p>{c.what}</p>
                  <p className="cf-why">{c.why_now}</p>
                  <a href={`/changes/${c.change_id}`} className="cf-link">
                    打开证据链 →
                  </a>
                </div>
              )}
            </div>
          ))}
        </aside>
      </div>
    </section>
  );
}
