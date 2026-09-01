"use client";

/**
 * Briefing 页（阶段 1-d 黄金路径第一跳）：今天有什么变化 / 为什么值得看 / 数据截至何时。
 *
 * 硬验收映射：#1 十秒三问；#2 内部术语不出现在主路径（JSD/conf 等只在 Change Detail 折叠区）；
 * #7 五状态可区分（loading/empty/insufficient/stale/error）；#8 data_as_of 顶层一致展示；
 * #9 与 /today 同义入口将在本页稳定后 redirect。
 * Dashboard 双图按审计裁决移除（认知闭环优先，图表堆砌不进入主路径）。
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  api,
  type BriefingResponse,
  type ChangeBrief,
} from "@/lib/api";
import { SIGNAL } from "@/lib/tokens";
import { track } from "@/lib/track";
import { divergenceLevel, watchStatus } from "@/lib/insight";

/* ── 数据面（旧端点类型，待统一迁移至 OpenAPI 生成） ── */

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

/* ── 人话映射（硬验收 2：术语不出主路径） ── */

const KIND_ZH: Record<string, string> = {
  attention_spike: "关注升温",
  narrative_shift: "叙事转变",
  divergence_rise: "分歧扩大",
  expectation_gap: "预期错位",
};

const STRENGTH_ZH: Record<string, { zh: string; color: string }> = {
  strong: { zh: "显著变化", color: SIGNAL.divergence },
  notable: { zh: "值得关注", color: SIGNAL.warning },
  minor: { zh: "轻微迹象", color: SIGNAL.muted },
  insufficient: { zh: "证据不足", color: SIGNAL.muted },
};

const URGENCY_ZH: Record<string, string> = {
  high: "今天",
  medium: "48 小时内",
  low: "本周内",
};

const STALENESS_ZH: Record<string, string> = {
  fresh: "数据新鲜",
  aging: "数据开始变旧",
  stale: "数据已过期",
};

/* ── 小件 ── */

function SectionHead({
  no,
  title,
  zh,
  question,
}: {
  no: string;
  title: string;
  zh: string;
  question: string;
}) {
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

function FreshnessLine({ b }: { b: BriefingResponse }) {
  const f = b.freshness;
  const stale = f.staleness === "stale";
  return (
    <p
      className="paper-kicker mt-1"
      style={{ color: stale ? SIGNAL.warning : undefined }}
      title={`覆盖 ${f.coverage_start ?? "?"} 至 ${f.as_of}`}
    >
      数据截至 {f.as_of.slice(0, 16).replace("T", " ")} UTC ·{" "}
      {STALENESS_ZH[f.staleness] ?? f.staleness}
      {stale ? "——结论请谨慎对待" : ""}
    </p>
  );
}

function ChangeCard({ c, i }: { c: ChangeBrief; i: number }) {
  const strength = STRENGTH_ZH[c.strength_word] ?? STRENGTH_ZH.minor;
  const dismiss = () => track("change_dismissed_as_noise", { objectId: c.change_id });
  return (
    <article className="border-b border-border/60 py-5 first:pt-1">
      <div className="flex items-baseline gap-3">
        <span className="font-paper text-3xl font-semibold text-muted-foreground/35">
          {String(i + 1).padStart(2, "0")}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="paper-kicker">{KIND_ZH[c.kind] ?? c.kind}</span>
            <span
              className="inline-flex items-center gap-1.5 text-[12px]"
              style={{ color: strength.color }}
            >
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{ background: strength.color }}
              />
              {strength.zh}
            </span>
            <span className="text-[12px] text-muted-foreground">
              建议 {URGENCY_ZH[c.urgency] ?? c.urgency}查看
            </span>
          </div>
          <h2 className="mt-1 font-paper text-xl leading-tight">
            <Link href={`/changes/${encodeURIComponent(c.change_id)}`} className="hover:text-primary">
              {c.headline}
            </Link>
          </h2>
          <p className="mt-1.5 text-sm leading-6">{c.what}</p>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">{c.why_now}</p>
          {(c.subjects ?? []).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(c.subjects ?? []).map((s) => (
                <span
                  key={`${s.kind}-${s.id}`}
                  className="border border-foreground/20 px-1.5 py-0.5 text-[11px] text-muted-foreground"
                >
                  {s.label}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-stretch gap-1.5">
          <Link
            href={`/changes/${encodeURIComponent(c.change_id)}`}
            className="border border-foreground/60 px-3 py-1.5 text-center text-xs font-medium hover:bg-foreground hover:text-background"
          >
            看证据 →
          </Link>
          <button
            type="button"
            onClick={dismiss}
            className="px-3 py-1 text-center text-[11px] text-muted-foreground hover:text-foreground"
          >
            不重要
          </button>
        </div>
      </div>
    </article>
  );
}

/* ── 页面 ── */

export default function IntelligencePage() {
  const [briefing, setBriefing] = useState<BriefingResponse | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [watches, setWatches] = useState<WatchRow[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    let alive = true;
    Promise.all([api.briefing(), api.events(7), api.watches()])
      .then(([b, e, w]) => {
        if (!alive) return;
        setBriefing(b);
        setEvents(e as unknown as EventRow[]);
        setWatches(((w as { watches: WatchRow[] }).watches) ?? []);
        setError(null);
        track("briefing_viewed", { freshness: b.freshness.as_of });
      })
      .catch((err) => {
        if (!alive) return;
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      alive = false;
    };
  }, []);

  const askHref = (question: string) =>
    `/research?q=${encodeURIComponent(question)}`;
  const changes = briefing?.changes ?? [];
  const stale = briefing?.freshness.staleness === "stale";

  return (
    <div className="grid grid-cols-1 gap-x-10 gap-y-8 lg:grid-cols-12">
      {/* ── Main 8 栏：Briefing ── */}
      <div className="lg:col-span-8 min-w-0">
        <header className="mb-4">
          <p className="paper-kicker">Today&apos;s Briefing</p>
          <h1 className="font-paper mt-1 text-3xl tracking-tight">
            {briefing === null
              ? "正在扫描信息流…"
              : changes.length > 0
                ? `今天有 ${changes.length} 件值得注意的变化`
                : "今天没有值得看的变化"}
          </h1>
          {briefing && <FreshnessLine b={briefing} />}
          {error && (
            <p className="mt-1 text-sm" style={{ color: SIGNAL.warning }}>
              数据加载失败（{error}）——请稍后重试。
            </p>
          )}
        </header>

        <div className="flex flex-col">
          {changes.map((c, i) => (
            <ChangeCard key={c.change_id} c={c} i={i} />
          ))}
          {briefing && changes.length === 0 && (
            <p className="text-sm leading-6 text-muted-foreground">
              当前信息量不足以支撑任何值得注意的变化判断——系统选择弃权而非硬凑数字。
              {briefing.freshness.note}
            </p>
          )}
          {stale && (
            <p className="mt-3 border border-dashed p-3 text-sm" style={{ borderColor: SIGNAL.warning }}>
              数据已过期（采集可能中断）——以下结论基于最后一次成功采集的窗口。
            </p>
          )}
        </div>
      </div>

      {/* ── Sidebar 4 栏 ── */}
      <aside className="flex flex-col gap-8 lg:col-span-4 min-w-0">
        <section>
          <SectionHead
            no="§1"
            title="Active events"
            zh="进行中的事件"
            question="Question：现在有哪些事件在演化？"
          />
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
          <Link href="/investigate" className="mt-1 inline-block text-xs text-muted-foreground hover:text-primary">
            全部事件 →
          </Link>
        </section>

        <section>
          <SectionHead
            no="§2"
            title="Your watchlist"
            zh="关注状态"
            question="Question：我关注的东西最近有什么变化？"
          />
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
          <SectionHead
            no="§3"
            title="Ask the analyst"
            zh="问分析师"
            question="Agent 从问题出发，产出可归档的研究结论"
          />
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
