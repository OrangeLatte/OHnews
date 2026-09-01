"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface MetricsResponse {
  counters: Record<string, number>;
  evidence_drill_rate: number | null;
  judgment_rate: number | null;
  watch_review_rate: number | null;
  time_to_first_change_median_sec: number | null;
  n_sessions: number;
  data_window: { first_ts: string | null; last_ts: string | null };
}

/** 事件闭集中文映射（顺序即账本闭集顺序；新增事件需在后端 _TRACKED_EVENTS 同步）。 */
const EVENT_ZH: Readonly<Record<string, string>> = {
  briefing_viewed: "简报浏览",
  change_opened: "变化打开",
  change_dismissed_as_noise: "忽略为噪声",
  evidence_opened: "证据打开",
  source_opened: "原文打开",
  counter_evidence_requested: "请求反证",
  insufficient_evidence_seen: "证据不足提示",
  investigation_started: "调查开始",
  judgment_saved: "判断保存",
  judgment_change_type: "判断变更类型",
  watch_created: "订阅创建",
  watch_update_reviewed: "订阅复核",
};

const EVENT_ORDER: readonly string[] = Object.keys(EVENT_ZH);

function fmtSeconds(v: number | null): string {
  return v === null ? "暂无样本" : `约 ${v} 秒`;
}

function fmtPercent(v: number | null): string {
  return v === null ? "暂无样本" : `${(v * 100).toFixed(1)}%`;
}

function fmtWindow(ts: string | null): string {
  return ts === null ? "—" : ts.slice(0, 16).replace("T", " ");
}

async function fetchMetrics(): Promise<MetricsResponse> {
  const r = await fetch("/api/metrics", { cache: "no-store" });
  if (!r.ok) throw new Error(`/api/metrics: HTTP ${r.status}`);
  return (await r.json()) as MetricsResponse;
}

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card className="border-black/10">
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="font-paper text-4xl tracking-tight">{value}</p>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

export default function MetricsSection() {
  const [data, setData] = useState<MetricsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    fetchMetrics()
      .then((d) => {
        setData(d);
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(String(err));
        setLoading(false);
      });
  }, []);

  const refresh = useCallback(() => {
    setLoading(true);
    load();
  }, [load]);

  useEffect(() => {
    load();
  }, [load]);

  const empty = data !== null && data.n_sessions === 0;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold">埋点指标看板</h2>
        {data && !empty && <Badge variant="outline">会话 {data.n_sessions}</Badge>}
        <Button size="sm" variant="outline" onClick={refresh} disabled={loading}>
          刷新
        </Button>
        <p className="ml-auto text-xs text-muted-foreground">
          数据窗口 {fmtWindow(data?.data_window.first_ts ?? null)} →{" "}
          {fmtWindow(data?.data_window.last_ts ?? null)}（UTC）
        </p>
      </div>

      {loading && <p className="text-sm text-muted-foreground">加载中…</p>}
      {error && <p className="text-sm text-destructive">指标加载失败：{error}</p>}
      {empty && (
        <p className="text-sm text-muted-foreground">
          暂无埋点数据——主路径使用后这里会出现指标。
        </p>
      )}

      {data && !empty && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              label="Time to First Change"
              value={fmtSeconds(data.time_to_first_change_median_sec)}
              hint="首次简报→首个变化 中位秒"
            />
            <MetricCard
              label="证据下钻率"
              value={fmtPercent(data.evidence_drill_rate)}
              hint="证据打开 / 变化打开"
            />
            <MetricCard
              label="判断保存率"
              value={fmtPercent(data.judgment_rate)}
              hint="判断保存 / 变化打开"
            />
            <MetricCard
              label="Watch 复核率"
              value={fmtPercent(data.watch_review_rate)}
              hint="订阅复核 / 订阅创建"
            />
          </div>

          <Card className="border-black/10">
            <CardHeader>
              <CardTitle className="text-base">事件计数（主路径闭集 12 项）</CardTitle>
            </CardHeader>
            <CardContent>
              <table className="w-full text-sm">
                <tbody>
                  {EVENT_ORDER.map((event) => (
                    <tr key={event} className="border-b border-black/10 last:border-b-0">
                      <td className="py-1.5 pr-4">{EVENT_ZH[event]}</td>
                      <td className="py-1.5 pr-4 font-mono text-xs text-muted-foreground">
                        {event}
                      </td>
                      <td className="py-1.5 text-right font-paper text-lg tabular-nums">
                        {data.counters[event] ?? 0}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
