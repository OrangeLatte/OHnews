"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { ChartGrid } from "@/components/charts/chart-grid";
import { ChangeFieldPanel } from "@/components/change-field/change-field";
import { api } from "@/lib/api";
import { divergenceLevel } from "@/lib/insight";

type EventRow = {
  event_id: string;
  title: string;
  entities: string[];
  as_of: string;
  ndi: number | null;
  ndi_status: string;
  n_sources: number;
};

type QualifiedChange = {
  change_id: string;
  kind: string;
  headline: string;
  what: string;
  why_now: string;
  strength_word: string;
  urgency: string;
  subjects: string[];
};

const KIND_ZH: Record<string, string> = {
  attention_spike: "注意力聚集",
  narrative_shift: "叙事转变",
  divergence_rise: "分歧升高",
  expectation_gap: "预期错位",
};

const STRENGTH_ZH: Record<string, string> = {
  strong: "显著变化",
  notable: "值得关注",
  minor: "轻微迹象",
  insufficient: "证据不足",
};

const INITIAL_EVENT_COUNT = 5;
const EVENT_PAGE_SIZE = 10;
const MAX_VISIBLE_EVENTS = 25;

function titleFingerprint(title: string): string {
  return title.toLowerCase().replace(/\s+/g, " ").trim();
}

/**
 * 调查工作台（T6 任务流重组）：
 * 当前问题 → 高质量变化（过 Hero Gate）→ 证据工作区 → 用户判断。
 * v1：问题=本地筛选焦点；判断=MEMORY 时间线入口（ BeliefTimeline 在 /memory）。
 */
export default function EventsPage() {
  const [events, setEvents] = useState<EventRow[] | null>(null);
  const [changes, setChanges] = useState<QualifiedChange[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [openChange, setOpenChange] = useState<string | null>(null);
  const [visibleCount, setVisibleCount] = useState(INITIAL_EVENT_COUNT);

  useEffect(() => {
    const qs = new URLSearchParams(window.location.search).get("q");
    api
      .events(30)
      .then((evts) => {
        setEvents(evts);
        if (qs) setQ(qs);
      })
      .catch((err) => setError(String(err)));
    api
      .changeLandscape(7, 5)
      .then((s) =>
        setChanges((s.qualified_changes ?? []).map((c) => ({ ...c, subjects: c.subjects ?? [] }))),
      )
      .catch(() => setChanges([])); // 高质量变化加载失败不阻塞事件区
  }, []);

  const ql = q.trim().toLowerCase();
  const ranked = events
    ? [...events]
        .filter((event) => event.n_sources > 0)
        .sort((a, b) => b.n_sources - a.n_sources)
    : [];
  const matched = ql
    ? ranked.filter(
          (e) =>
            e.title.toLowerCase().includes(ql) ||
            e.entities.some((x) => x.toLowerCase().includes(ql)),
        )
    : ranked;
  const seenTitles = new Set<string>();
  const filtered = matched.filter((event) => {
    const key = `${event.as_of.slice(0, 10)}:${titleFingerprint(event.title)}`;
    if (!key || seenTitles.has(key)) return false;
    seenTitles.add(key);
    return true;
  });
  const shownEvents = filtered.slice(0, visibleCount);

  return (
    <div className="flex flex-col gap-8">
      <header>
        <p className="paper-kicker">02 / INVESTIGATE</p>
        <h1 className="font-paper mt-1 text-3xl tracking-tight">INVESTIGATE · 调查工作台</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          从值得验证的变化出发，回到证据，形成自己的判断。
          深度工具在顶部导航与各分区入口：AI 研究对话、情报巡逻、叙事时间轴。
        </p>
      </header>
      <ChartGrid />

      {/* ① 当前问题：调查焦点 */}
      <section aria-label="当前问题">
        <p className="paper-kicker mb-2">① 当前问题</p>
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setVisibleCount(INITIAL_EVENT_COUNT);
          }}
          placeholder="你正在调查什么？（按实体或标题过滤下方事件，如 fed / tariff）"
          className="w-full max-w-xl border border-border bg-card px-3 py-2 text-sm outline-none focus:border-primary"
        />
        {ql && (
          <p className="mt-1 text-xs text-muted-foreground">
            调查焦点「{q}」——下方证据工作区已按此过滤。
          </p>
        )}
      </section>

      {/* ② 高质量变化：过 Hero Gate 的变化队列 */}
      <section aria-label="高质量变化">
        <p className="paper-kicker mb-2">② 高质量变化（已过覆盖质量门）</p>
        {changes === null ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : changes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            当前窗口没有通过质量门的变化——证据还不够说话时，系统选择弃权而非硬凑。
          </p>
        ) : (
          <div className="flex flex-col">
            {changes.map((c) => {
              const open = openChange === c.change_id;
              return (
                <div key={c.change_id} className="border-b border-border/60 py-3">
                  <button
                    type="button"
                    className="flex w-full items-baseline gap-3 text-left"
                    onClick={() => setOpenChange(open ? null : c.change_id)}
                  >
                    <span className="shrink-0 border border-border px-1.5 py-0.5 text-[11px]">
                      {KIND_ZH[c.kind] ?? c.kind}
                    </span>
                    <span className="flex-1 font-paper text-base">{c.headline}</span>
                    <span className="shrink-0 text-[11px] text-muted-foreground">
                      {STRENGTH_ZH[c.strength_word] ?? c.strength_word}
                    </span>
                  </button>
                  {open && (
                    <div className="mt-2 ml-1 flex flex-col gap-1 border-l-2 border-primary/40 pl-3">
                      <p className="text-sm">{c.what}</p>
                      <p className="text-sm text-muted-foreground">为什么是现在：{c.why_now}</p>
                      {c.subjects.length > 0 && (
                        <p className="text-xs text-muted-foreground">
                          涉及：{c.subjects.join("、")}
                        </p>
                      )}
                      <p className="mt-1 text-xs">
                        <Link href={`/changes/${c.change_id}`} className="text-primary underline">
                          打开证据链（支持 / 反对 / 缺失）→
                        </Link>
                      </p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
      <ChangeFieldPanel days={30} />

      {/* ③ 证据工作区：事件列表（调查优先级=信源数降序） */}
      <section aria-label="证据工作区">
        <p className="paper-kicker mb-2">③ 证据工作区（事件 × 来源 × 分歧）</p>
        {error && <p className="text-destructive">加载失败：{error}</p>}
        {!events && !error && <p className="text-sm text-muted-foreground">加载事件中…</p>}
        {events && filtered.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {ql ? `没有匹配「${q}」的事件。` : "近 30 天无事件（信息量不足时系统选择弃权而非硬凑）。"}
          </p>
        )}
        {events && filtered.length > 0 && (
          <div className="flex flex-col">
            {shownEvents.map((e) => {
              const lv = divergenceLevel(e.ndi);
              return (
                <Link
                  key={e.event_id}
                  href={`/events/${e.event_id}`}
                  className="flex items-baseline gap-4 border-b border-border/60 py-3 hover:bg-muted/30"
                >
                  <span className="font-mono text-xs text-muted-foreground">
                    {e.as_of.slice(0, 10)}
                  </span>
                  <span className="flex-1 truncate font-paper text-base">{e.title}</span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {e.n_sources} 源
                  </span>
                  <span className="w-36 text-right text-xs font-medium" style={{ color: lv.color }}>
                    {lv.zh}
                  </span>
                </Link>
              );
            })}
            {filtered.length > visibleCount && visibleCount < MAX_VISIBLE_EVENTS && (
              <button
                type="button"
                className="mt-3 self-start border border-border px-3 py-1.5 text-xs hover:border-primary"
                onClick={() =>
                  setVisibleCount((count) =>
                    Math.min(count + EVENT_PAGE_SIZE, MAX_VISIBLE_EVENTS, filtered.length),
                  )
                }
              >
                再显示 {Math.min(EVENT_PAGE_SIZE, filtered.length - visibleCount)} 条
              </button>
            )}
            {filtered.length > MAX_VISIBLE_EVENTS && visibleCount >= MAX_VISIBLE_EVENTS && (
              <p className="mt-3 text-xs text-muted-foreground">
                其余 {filtered.length - MAX_VISIBLE_EVENTS} 条已收起。输入更具体的问题可缩小证据范围。
              </p>
            )}
          </div>
        )}
      </section>

      {/* ④ 用户判断：认知档案入口 */}
      <section aria-label="用户判断">
        <p className="paper-kicker mb-2">④ 你的判断</p>
        <p className="text-sm text-muted-foreground">
          在任一变化的证据链页面底部保存判断（维持 / 调整 / 反转 / 不确定）。
          历史判断与变化轨迹在{" "}
          <Link href="/memory" className="text-primary underline">
            MEMORY · 认知档案
          </Link>{" "}
          查看。你的判断只属于你——系统不会改写它。
        </p>
      </section>
    </div>
  );
}
