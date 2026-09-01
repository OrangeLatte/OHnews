"use client";

/**
 * Briefing 页（阶段 1-d 黄金路径第一跳）：今天有什么变化 / 为什么值得看 / 数据截至何时。
 *
 * 硬验收映射：#1 十秒三问；#2 内部术语不出现在主路径（JSD/conf 等只在 Change Detail 折叠区）；
 * #7 五状态可区分（loading/empty/insufficient/stale/error）；#8 data_as_of 顶层一致展示；
 * #9 与 /today 同义入口将在本页稳定后 redirect。
 * Dashboard 双图按审计裁决移除（认知闭环优先，图表堆砌不进入主路径）。
 */

import type { components } from "@/lib/api-schema";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import {
  api,
  type BriefingResponse,
  type WatchRow,
} from "@/lib/api";
import { SIGNAL } from "@/lib/tokens";
import { track } from "@/lib/track";
import { watchStatus } from "@/lib/insight";
import { ChangeOverview } from "@/components/change-overview/change-overview";

/* ── 数据面（旧端点类型，待统一迁移至 OpenAPI 生成） ── */

/* ── 人话映射（硬验收 2：术语不出主路径） ── */

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

/* ── 页面 ── */

export default function IntelligencePage() {
  // T4：单源 /api/home——briefing/landscape/watches 一次聚合，消除并发竞态；
  // briefing_viewed 只在本页 track 一次（ChangeOverview 改受控不再上报）。
  const [home, setHome] = useState<components["schemas"]["HomePayload"] | null>(null);
  const [days, setDays] = useState(7);
  const [error, setError] = useState<string | null>(null);
  const seenRef = useRef(false);

  useEffect(() => {
    let alive = true;
    api
      .home(days)
      .then((h) => {
        if (!alive) return;
        setHome(h);
        setError(null);
        if (!seenRef.current) {
          seenRef.current = true;
          track("briefing_viewed", { freshness: h.briefing.freshness.as_of });
        }
      })
      .catch((err) => {
        if (!alive) return;
        setHome(null);
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      alive = false;
    };
  }, [days]);

  const briefing: BriefingResponse | null = home?.briefing ?? null;
  const watches = (home?.watches as unknown as WatchRow[]) ?? [];
  const changes = briefing?.changes ?? [];
  const stale = briefing?.freshness.staleness === "stale";

  return (
    <div className="grid grid-cols-1 gap-x-10 gap-y-8 lg:grid-cols-12">
      {/* ── Hero：变化总览（全宽，双窗叙事对比） ── */}
      <div className="lg:col-span-12 -mx-4 sm:-mx-6 lg:-mx-10 min-w-0">
        <ChangeOverview scene={home?.landscape ?? null} days={days} onDaysChange={setDays} />
      </div>

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

        {/* T3：变化卡唯一列表在 ChangeOverview（Hero）——此处不再重复渲染同一批 Change */}
        <div className="flex flex-col">
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

      </aside>
    </div>
  );
}
