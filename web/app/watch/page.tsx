"use client";

/**
 * 03 WATCH · 跟踪预警（C3 统一模型）
 * 单元四类（entity/topic/question/element）× 两模式（track 持续追踪 / alert 超限提醒）。
 * 语义：查看 ≠ 复核——只有点「标记已复核」才推进认知基线（last_checked_at）。
 */

import { useCallback, useEffect, useState } from "react";
import AlertsSection from "@/app/watch/alerts-section";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { SIGNAL } from "@/lib/tokens";
import { track } from "@/lib/track";

type Unit = Awaited<ReturnType<typeof api.trackingList>>["units"][number];
type UnitUpdate = Awaited<ReturnType<typeof api.trackingUpdate>>;

const KIND_ZH: Record<string, string> = {
  entity: "实体",
  topic: "主题",
  question: "研究问题",
  element: "文章元素",
};
const MODE_ZH: Record<string, string> = { track: "持续追踪", alert: "超限提醒" };

export default function WatchPage() {
  const [units, setUnits] = useState<Unit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [updates, setUpdates] = useState<Record<string, UnitUpdate | null>>({});
  const [kind, setKind] = useState("entity");
  const [mode, setMode] = useState("track");
  const [query, setQuery] = useState("");
  const [label, setLabel] = useState("");
  const [threshold, setThreshold] = useState("0.7");

  const load = useCallback(() => {
    api
      .trackingList()
      .then((r) => setUnits(r.units ?? []))
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function add() {
    if (!query.trim()) return;
    setBusy("add");
    try {
      await api.trackingAdd({
        kind,
        query: query.trim(),
        mode,
        label: label.trim(),
        threshold: mode === "alert" ? Number(threshold) || undefined : undefined,
      });
      track("watch_created", { objectId: query.trim(), fromPage: "/watch" });
      setQuery("");
      setLabel("");
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function toggleUpdate(id: string) {
    if (updates[id]) {
      setUpdates((p) => ({ ...p, [id]: null }));
      return;
    }
    setBusy(id);
    try {
      const u = await api.trackingUpdate(id);
      setUpdates((p) => ({ ...p, [id]: u }));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function review(id: string) {
    setBusy(id);
    try {
      await api.trackingReview(id);
      track("watch_update_reviewed", { objectId: id, fromPage: "/watch" });
      setUpdates((p) => ({ ...p, [id]: null }));
      load();
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <p className="paper-kicker mb-1">03 / WATCH</p>
      <h1 className="font-paper text-2xl">关注与追踪</h1>
      <p className="mt-2 text-sm text-[var(--muted-foreground)]">
        订阅实体、主题、研究问题或文章元素——系统在你关心的方向上持续追踪变化，
        或在超出阈值时提醒你。分位数预警规则在页面下方。
      </p>

      {error && <p className="mt-3 text-sm" style={{ color: SIGNAL.divergence }}>{error}</p>}

      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="font-paper text-base">新建跟踪单元</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="flex flex-wrap gap-2">
            <select
              aria-label="单元类型"
              className="border border-[var(--border)] bg-transparent px-2 py-1 text-sm"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
            >
              {Object.entries(KIND_ZH).map(([k, zh]) => (
                <option key={k} value={k}>
                  {zh}
                </option>
              ))}
            </select>
            <select
              aria-label="模式"
              className="border border-[var(--border)] bg-transparent px-2 py-1 text-sm"
              value={mode}
              onChange={(e) => setMode(e.target.value)}
            >
              {Object.entries(MODE_ZH).map(([k, zh]) => (
                <option key={k} value={k}>
                  {zh}
                </option>
              ))}
            </select>
            {kind === "element" && (
              <span className="self-center text-xs text-[var(--muted-foreground)]">
                元素格式 element_key:value（如 tone:optimism）
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              aria-label="跟踪对象"
              className="min-w-0 flex-1 border border-[var(--border)] bg-transparent px-2 py-1 text-sm"
              placeholder={kind === "entity" ? "实体（如 fed）" : kind === "element" ? "tone:optimism" : "关键词或问题"}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <input
              aria-label="备注名（可选）"
              className="min-w-0 flex-1 border border-[var(--border)] bg-transparent px-2 py-1 text-sm"
              placeholder="备注名（可选）"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
            {mode === "alert" && (
              <input
                aria-label="阈值"
                className="w-20 border border-[var(--border)] bg-transparent px-2 py-1 text-sm"
                title="触发阈值 0–1"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
              />
            )}
            <button
              type="button"
              className="border border-[var(--border)] px-3 py-1 text-sm hover:border-[var(--foreground)] disabled:opacity-50"
              disabled={busy === "add" || !query.trim()}
              onClick={add}
            >
              订阅
            </button>
          </div>
        </CardContent>
      </Card>

      <div className="mt-6 grid gap-4">
        {units.length === 0 && (
          <p className="text-sm text-[var(--muted-foreground)]">
            暂无跟踪单元——用上方表单创建第一个。
          </p>
        )}
        {units.map((u) => (
          <Card key={u.unit_id}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle className="font-paper text-base">
                {u.label || u.query}
                <span className="ml-2 align-middle">
                  <Badge variant="outline">{KIND_ZH[u.kind] ?? u.kind}</Badge>{" "}
                  <Badge variant={u.mode === "alert" ? "destructive" : "secondary"}>
                    {MODE_ZH[u.mode] ?? u.mode}
                  </Badge>
                </span>
              </CardTitle>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="text-xs underline-offset-2 hover:underline"
                  onClick={() => toggleUpdate(u.unit_id)}
                  disabled={busy === u.unit_id}
                >
                  {updates[u.unit_id] ? "收起更新" : "查看更新"}
                </button>
                <button
                  type="button"
                  className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  onClick={() => api.trackingDelete(u.unit_id).then(load)}
                >
                  删除
                </button>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-[var(--muted-foreground)]">
                {u.mode === "alert"
                  ? `阈值 ${(u.threshold ?? 0).toFixed(2)} · `
                  : ""}
                {u.last_checked_at
                  ? `上次复核 ${new Date(u.last_checked_at).toLocaleString("zh-CN")}`
                  : "尚无复核记录（无基线——全部视为新）"}
              </p>
              {updates[u.unit_id] && (
                <div className="mt-3 border-t border-dotted border-[var(--border)] pt-3 text-sm">
                  <p>{updates[u.unit_id]!.summary}</p>
                  {updates[u.unit_id]!.review_hint && (
                    <p className="mt-1" style={{ color: SIGNAL.attention }}>
                      ⚠ {updates[u.unit_id]!.review_hint}
                    </p>
                  )}
                  {(updates[u.unit_id]!.new_changes ?? []).length > 0 && (
                    <ul className="mt-2 grid gap-1">
                      {(updates[u.unit_id]!.new_changes as Array<{ change_id?: string; headline?: string }>).map((c) => (
                        <li key={c.change_id}>
                          <a className="underline-offset-2 hover:underline" href={`/changes/${c.change_id}`}>
                            {c.headline}
                          </a>
                        </li>
                      ))}
                    </ul>
                  )}
                  <button
                    type="button"
                    className="mt-3 border border-[var(--border)] px-3 py-1 text-xs hover:border-[var(--foreground)]"
                    onClick={() => review(u.unit_id)}
                    disabled={busy === u.unit_id}
                  >
                    标记已复核
                  </button>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="mt-10">
        <AlertsSection />
      </div>
    </main>
  );
}
