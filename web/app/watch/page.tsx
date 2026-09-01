"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { watchStatus } from "@/lib/insight";
import AlertsSection from "@/app/watch/alerts-section";

import { api, type SignalRow, type WatchRow } from "@/lib/api";
import { track } from "@/lib/track";

type WatchUpdateRow = Awaited<ReturnType<typeof api.watchUpdate>>;

const TYPE_META: Record<string, { label: string; hint: string; color: string }> = {
  entity: { label: "实体", hint: "实体 id（如 fed / ecb / trump）", color: "#58a6ff" },
  topic: { label: "主题", hint: "关键词，逗号分隔（如 衰退,关税）", color: "#d29922" },
  question: { label: "问题", hint: "研究问题句（系统将自动检索并回答）", color: "#bc8cff" },
};

function summaryLines(w: WatchRow): string[] {
  const s = w.last_summary as Record<string, unknown> | null;
  if (!s) return ["尚未刷新"];
  const lines: string[] = [];
  if (s.kind === "entity") {
    lines.push(`${s.n_signals} 个相关 Signal · ${s.n_events} 个关联事件`);
    const sigs = (s.signals as SignalRow[]) ?? [];
    for (const g of sigs.slice(0, 3))
      lines.push(`· [${g.kind}] ${g.title}（strength ${Math.round(g.strength)}）`);
    const evs = (s.events as { event_id: string; title: string }[]) ?? [];
    for (const e of evs.slice(0, 3)) lines.push(`· 事件 ${e.event_id}：${e.title}`);
    const alerts = (s.alerts as { event_title: string; ndi: number; baseline: number }[]) ?? [];
    if (alerts.length)
      for (const a of alerts)
        lines.push(`⚠ 预警：${a.event_title}（NDI ${a.ndi.toFixed(2)} > 基线 ${a.baseline.toFixed(2)}）`);
    else if ((s.n_alert_rules as number) === 0)
      lines.push("（该实体暂无预警规则，可在后台 /alerts 配置分位阈值）");
  } else if (s.kind === "topic") {
    lines.push(`近 7 日 ${s.n_articles} 篇文章命中「${(s.terms as string[]).join(" / ")}」`);
    const tops = (s.top_sources as { source_id: string; n: number }[]) ?? [];
    if (tops.length)
      lines.push(`主要来源：${tops.map((t) => `${t.source_id}(${t.n})`).join("、")}`);
    lines.push(`${s.n_events} 个关联事件`);
  } else {
    // question：Investigator 已接入——answered（llm/offline）渲染回答，pending_agent 待 keys
    const status = s.status as string;
    const answer = s.answer as string | null;
    if (status === "answered" && answer) {
      const engine = s.engine === "llm" ? "Agent 回答" : "确定性摘要（未配置 keys）";
      lines.push(`已回答（${engine}）· 匹配 ${s.n_matched_events} 个事件`);
      for (const ln of answer.split("\n")) if (ln.trim()) lines.push(ln);
    } else {
      lines.push(`问题已记录 · 匹配 ${s.n_matched_events} 个事件 · 暂无可命中数据或未配置 keys`);
    }
    const evs = (s.events as { event_id: string; title: string }[]) ?? [];
    for (const e of evs.slice(0, 3)) lines.push(`· 事件 ${e.event_id}：${e.title}`);
  }
  return lines;
}

export default function WatchPage() {
  const [watches, setWatches] = useState<WatchRow[]>([]);
  const [type, setType] = useState("entity");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [updates, setUpdates] = useState<Record<string, WatchUpdateRow | null>>({});

  const load = useCallback(() => {
    api.watches().then((r) => setWatches(r.watches)).catch((e) => setError(String(e)));
  }, []);
  useEffect(load, [load]);

  async function add() {
    if (!query.trim()) return;
    setBusy("add");
    try {
      await api.watchAdd(type, query);
      track("watch_created", { objectId: query.trim(), fromPage: "/watch" });
      setQuery("");
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function refresh(id: string) {
    setBusy(id);
    try {
      await api.watchRefresh(id);
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  // 阶段 3：查看更新 = 只读计算；复核 = 用户显式动作才推进基线
  async function toggleUpdate(id: string) {
    if (updates[id]) {
      setUpdates((m) => ({ ...m, [id]: null }));
      return;
    }
    setBusy(id);
    try {
      const u = await api.watchUpdate(id);
      setUpdates((m) => ({ ...m, [id]: u }));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function review(id: string) {
    setBusy(id);
    try {
      await api.watchReview(id);
      track("watch_update_reviewed", { objectId: id, fromPage: "/watch" });
      setUpdates((m) => ({ ...m, [id]: null }));
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h2 className="font-paper text-xl">我的订阅</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          订阅实体、主题与研究问题——系统在你关心的方向上持续监测变化。
          分位数预警规则与触发记录在页面下方。
          信息源管理已移至 <Link href="/settings/developer" className="underline">开发者设置</Link>。
        </p>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-3 pt-4">
          <div className="flex gap-2">
            {(Object.keys(TYPE_META) as string[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setType(t)}
                className={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                  type === t
                    ? "border-transparent text-white"
                    : "border-border text-muted-foreground hover:text-foreground"
                }`}
                style={type === t ? { backgroundColor: TYPE_META[t].color } : undefined}
              >
                {TYPE_META[t].label}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={TYPE_META[type].hint}
              onKeyDown={(e) => e.key === "Enter" && add()}
            />
            <Button onClick={add} disabled={busy === "add"}>
              {busy === "add" ? "添加中…" : "订阅"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && <p className="text-destructive">{error}</p>}

      <div className="flex flex-col gap-3">
        {watches.length === 0 ? (
          <div className="rounded border border-border bg-card px-4 py-8 text-center">
            <p className="font-paper text-lg">你的情报雷达还是空的</p>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted-foreground">
              订阅实体（如 fed、nvidia）、主题（如「关税、降息」）或研究问题后，系统会在每次刷新时汇报它们的状态：安静、发展中、关注度骤增或叙事分歧。订阅将成为你的个人情报雷达。
            </p>
            <div className="mt-3 flex justify-center gap-2 text-xs">
              <Link href="/investigate" className="text-primary hover:underline">
                先看看有什么事件 →
              </Link>
            </div>
          </div>
        ) : (
          (["entity", "topic", "question"] as const).map((group) => {
            const items = watches.filter((w) => w.type === group);
            if (items.length === 0) return null;
            const gmeta = TYPE_META[group];
            return (
              <div key={group} className="flex flex-col gap-2">
                <p className="paper-kicker mt-2 border-b border-border pb-1">
                  {group === "entity"
                    ? "Tracked entities · 追踪实体"
                    : group === "topic"
                      ? "Tracked topics · 追踪主题"
                      : "Research questions · 研究问题"}
                  （{items.length}）
                </p>
                {items.map((w) => {
                  const meta = gmeta;
                  const status = watchStatus(w.last_summary as Record<string, unknown> | null);
                  return (
              <Card key={w.watch_id}>
                <CardHeader className="pb-2">
                  <div className="flex items-center gap-2">
                    <Badge
                      variant="outline"
                      className="text-[10px]"
                      style={{ borderColor: meta.color, color: meta.color }}
                    >
                      {meta.label}
                    </Badge>
                    <CardTitle className="flex-1 font-mono text-sm">{w.query}</CardTitle>
                    <span
                      className="text-[10px] font-semibold uppercase tracking-wide"
                      style={{ color: status.color }}
                    >
                      ● {status.label}
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy === w.watch_id}
                      onClick={() => toggleUpdate(w.watch_id)}
                    >
                      {updates[w.watch_id] ? "收起" : busy === w.watch_id ? "…" : "查看更新"}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy === w.watch_id}
                      onClick={() => refresh(w.watch_id)}
                    >
                      {busy === w.watch_id ? "…" : "刷新"}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-muted-foreground"
                      onClick={() => api.watchRemove(w.watch_id).then(load)}
                    >
                      删除
                    </Button>
                  </div>
                  {w.last_checked_at && (
                    <p className="text-xs text-muted-foreground">
                      最近刷新 {w.last_checked_at.replace("T", " ").slice(0, 16)}
                    </p>
                  )}
                </CardHeader>
                <CardContent className="pt-0">
                  <ul className="space-y-1 text-sm">
                    {summaryLines(w).map((line, i) => (
                      <li key={i} className={i === 0 ? "text-foreground" : "text-muted-foreground"}>
                        {line}
                      </li>
                    ))}
                  </ul>
                  {updates[w.watch_id] && (
                    <div className="mt-3 rounded border border-dashed border-border bg-muted/30 px-3 py-3">
                      <p className="font-paper text-sm text-foreground">
                        {updates[w.watch_id]!.summary}
                      </p>
                      {updates[w.watch_id]!.review_hint && (
                        <p className="mt-1 text-xs" style={{ color: "#b08d3f" }}>
                          ⚠ {updates[w.watch_id]!.review_hint}
                        </p>
                      )}
                      {updates[w.watch_id]!.note && (
                        <p className="mt-1 text-xs text-muted-foreground">{updates[w.watch_id]!.note}</p>
                      )}
                      {(updates[w.watch_id]!.new_changes ?? []).length > 0 && (
                        <ul className="mt-2 space-y-1">
                          {(updates[w.watch_id]!.new_changes ?? []).map((c) => (
                            <li key={c.change_id} className="text-sm">
                              <Link href={`/changes/${c.change_id}`} className="hover:underline">
                                {c.headline}
                              </Link>
                              <span className="ml-2 text-xs text-muted-foreground">
                                {c.strength_word === "strong"
                                  ? "显著变化"
                                  : c.strength_word === "notable"
                                    ? "值得关注"
                                    : c.strength_word === "minor"
                                      ? "轻微迹象"
                                      : "证据不足"}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                      <div className="mt-3 flex items-center gap-2">
                        <Button size="sm" variant="outline" onClick={() => review(w.watch_id)}>
                          标记已复核
                        </Button>
                        <span className="text-xs text-muted-foreground">
                          {updates[w.watch_id]!.since
                            ? `基线：${updates[w.watch_id]!.since!.replace("T", " ").slice(0, 16)}`
                            : "无基线——全部视为新变化"}
                        </span>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
                );
              })}
            </div>
          );
        })
        )}
      </div>
      <AlertsSection />
    </div>
  );
}
