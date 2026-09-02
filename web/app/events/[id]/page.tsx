"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { ASSESS_STATUS as ASSESS, SIGNAL } from "@/lib/tokens";
import { AgentDock } from "@/components/agent/agent-dock";
import { DissectionPanel } from "@/components/dissection/dissection-panel";
import { QueueSection } from "@/components/dissection/queue-section";
import { ReportSection } from "@/components/dissection/report-section";

import {
  api,
  type AnatomyData,
  type AssessmentRow,
  type EvidenceRow,
  type NdiPoint,
  type SpectrumDoc,
} from "@/lib/api";
import { divergenceLevel, divergenceTrend, FRAME_ZH } from "@/lib/insight";

type EventMeta = {
  event_id: string;
  title: string;
  entities: string[];
  as_of: string;
  ndi: number | null;
  ndi_status: string;
  n_sources: number;
  assessment?: AssessmentRow | null;
};

const TIER_GROUP: Record<string, { label: string; zh: string; order: number }> = {
  L1: { label: "Primary", zh: "官方声明", order: 0 },
  L2: { label: "Secondary", zh: "通讯社与权威媒体", order: 1 },
  L3: { label: "Market", zh: "市场媒体", order: 2 },
  L4: { label: "Social", zh: "社媒讨论", order: 3 },
};

const LANG_ZH: Record<string, string> = { zh: "中文语料", en: "英文语料" };

/* M2 评估层四态（EventAssessment.status）用户语言映射 */
const ASSESS_STATUS_ZH: Record<string, { zh: string; color: string }> = {
  confirmed: { zh: "已证实", color: ASSESS.confirmed },
  contested: { zh: "存争议", color: ASSESS.contested },
  developing: { zh: "进展中", color: ASSESS.developing },
  unverified: { zh: "未证实", color: ASSESS.unverified },
};

const STRENGTH_ZH: Record<string, string> = {
  strong: "证据充分",
  moderate: "证据中等",
  limited: "证据有限",
  insufficient: "证据不足",
};

function SectionHead({ no, en, zh }: { no: string; en: string; zh: string }) {
  return (
    <div className="mt-8 flex items-baseline gap-3 border-b border-foreground/20 pb-1">
      <span className="font-serif text-sm text-muted-foreground">{no}</span>
      <h2 className="font-paper text-lg tracking-tight">{en}</h2>
      <span className="paper-kicker">{zh}</span>
    </div>
  );
}

function statusOf(meta: EventMeta | null): { label: string; color: string } {
  if (!meta) return { label: "…", color: SIGNAL.muted };
  /* 优先用 M2 评估层四态（有评估时），否则回退 NDI 状态推断 */
  if (meta.assessment) {
    const s = ASSESS_STATUS_ZH[meta.assessment.status] ?? { zh: meta.assessment.status, color: SIGNAL.muted };
    return { label: `${s.zh} · ${meta.assessment.status}`, color: s.color };
  }
  if (meta.ndi_status === "ok") return { label: "Developing · 发展中", color: SIGNAL.divergence };
  return { label: "Emerging · 新出现", color: SIGNAL.attention };
}

export default function EventDetailPage({ params }: PageProps<"/events/[id]">) {
  const { id } = use(params);
  const [meta, setMeta] = useState<EventMeta | null>(null);
  const [ndi, setNdi] = useState<NdiPoint[] | null>(null);
  const [evidence, setEvidence] = useState<EvidenceRow[]>([]);
  const [spectrum, setSpectrum] = useState<SpectrumDoc[]>([]);
  const [anatomy, setAnatomy] = useState<AnatomyData | null>(null);
  const [tierMap, setTierMap] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.eventDetail(id),
      api.eventNdi(id),
      api.eventEvidence(id),
      api.eventSpectrum(id),
      api.eventAnatomy(id),
      fetch(`/api/sources`).then((r) => r.json()),
    ])
      .then(([meta, n, e, sp, an, srcs]) => {
        setMeta(meta);
        setNdi(n);
        setEvidence(e);
        setSpectrum(sp);
        setAnatomy(an);
        const tm: Record<string, string> = {};
        for (const s of (srcs as { sources: { source_id: string; tier: string }[] }).sources)
          tm[s.source_id] = s.tier;
        setTierMap(tm);
      })
      .catch((err) => setError(String(err)));
  }, [id]);

  if (error) return <p className="text-destructive">加载失败：{error}</p>;
  if (!meta) return <p className="text-sm text-muted-foreground">加载事件中…</p>;

  const latestOk = ndi?.filter((p) => p.status === "ok" && p.ndi !== null) ?? [];
  const lastPoint = latestOk[latestOk.length - 1] ?? null;
  /* 趋势对比只在同一语言语料内进行——跨语言 NDI 点的差值无意义 */
  const prevPoint = lastPoint
    ? ([...latestOk]
        .reverse()
        .find((p) => p.language === lastPoint.language && p.ts !== lastPoint.ts) ?? null)
    : null;
  const lv = divergenceLevel(lastPoint ? (lastPoint.ndi as number) : null);
  const trend = divergenceTrend(lastPoint && prevPoint ? (lastPoint.ndi as number) - (prevPoint.ndi as number) : null);
  const status = statusOf(meta);

  const grouped: Record<string, EvidenceRow[]> = {};
  for (const row of evidence) {
    const tier = tierMap[row.source_id] ?? "L3";
    (grouped[tier] ??= []).push(row);
  }
  const tiers = Object.keys(grouped).sort(
    (a, b) => (TIER_GROUP[a]?.order ?? 9) - (TIER_GROUP[b]?.order ?? 9),
  );

  const askQuestions = [
    `为什么不同来源对「${meta.entities[0] ?? "该事件"}」的解释出现分歧？`,
    "过去类似情况下发生了什么？",
    "哪些信源正在推动当前叙事？",
    "这个变化是短期关注还是持续趋势？",
  ];

  return (
    <>
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
      <article className="lg:col-span-8">
        <header className="border-b border-foreground/20 pb-4">
          <p className="paper-kicker">02 / INVESTIGATE · {id}</p>
          <h1 className="font-paper mt-2 text-3xl leading-tight tracking-tight">{meta.title}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <span className="font-medium" style={{ color: status.color }}>
              STATUS {status.label}
            </span>
            <span>{meta.as_of.slice(0, 10)}</span>
            <span>{meta.n_sources} 个信源共同报道</span>
            {meta.entities.map((e) => (
              <Link key={e} href={`/events?q=${e}`} className="border border-border px-1.5 py-0.5 font-mono text-[11px] hover:border-primary">
                {e}
              </Link>
            ))}
          </div>
        </header>

        <SectionHead no="01" en="What happened" zh="发生了什么" />
        <p className="font-paper mt-3 text-base leading-7">
          在最近一次监测窗口内，{meta.n_sources} 个不同层级的信源共同报道了与{" "}
          {meta.entities.join("、") || "该主题"}相关的变化。系统将其聚合为一个事件，并持续追踪各方解释的差异。
        </p>

        <SectionHead no="02" en="Why it matters" zh="为什么重要" />
        <p className="mt-3 text-sm leading-7">
          {meta.n_sources >= 3
            ? `跨层级信源的共同覆盖意味着这不是单一来源的孤立报道。`
            : "目前覆盖信源较少，事件仍处早期。"}
          {lv.rank >= 2
            ? `同时，不同信源群体对它的解释已经出现明显分歧（${lv.zh}）——分歧本身往往比事件更值得注意。`
            : lv.rank === 1
              ? "各信源的解释开始出现差异，值得继续观察。"
              : "目前各信源解释基本一致，或数据尚不足以判断。"}
        </p>

        <SectionHead no="03" en="What changed" zh="发生了什么变化" />
        <div className="mt-3 flex items-baseline gap-4">
          <span className="font-paper text-3xl" style={{ color: lv.color }}>
            {lv.zh}
          </span>
          <span className="text-sm text-muted-foreground">叙事分歧 {trend}</span>
          {lastPoint && (
            <span className="border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground">
              {LANG_ZH[lastPoint.language] ?? `语料 ${lastPoint.language}`}
            </span>
          )}
        </div>
        <details className="mt-2 text-xs text-muted-foreground">
          <summary className="cursor-pointer">技术指标（方法论层）</summary>
          <p className="mt-1 font-mono">
            NDI {lastPoint ? (lastPoint.ndi as number).toFixed(3) : "—"} ·
            信源数{" "}
            {lastPoint?.n_sources ?? "—"} · 语料 {lastPoint?.language ?? "—"} ·{" "}
            弃权语义：样本不足时不产出数值
          </p>
        </details>

        {/* 评估层：状态、置信度、证据强度与后续观察。 */}
        {meta.assessment && (
          <div className="mt-4 border border-border/60 p-3">
            <div className="flex flex-wrap items-baseline gap-3 text-xs">
              <span className="font-medium" style={{ color: ASSESS_STATUS_ZH[meta.assessment.status]?.color }}>
                ● {ASSESS_STATUS_ZH[meta.assessment.status]?.zh ?? meta.assessment.status}
              </span>
              <span className="text-muted-foreground">
                置信 {meta.assessment.confidence.toFixed(2)}
              </span>
              <span className="text-muted-foreground">
                {STRENGTH_ZH[meta.assessment.evidence_strength] ?? meta.assessment.evidence_strength} ·{" "}
                {meta.assessment.n_independent_sources} 独立源（官方 {meta.assessment.n_primary_sources}）
              </span>
              <span className="ml-auto border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                {meta.assessment.engine}
              </span>
            </div>
            <p className="mt-2 font-paper text-sm leading-6">{meta.assessment.observation}</p>
            {meta.assessment.what_to_watch_next && (
              <p className="mt-1 text-xs text-muted-foreground">
                观察：{meta.assessment.what_to_watch_next}
              </p>
            )}
          </div>
        )}

        <SectionHead no="04" en="Who disagrees" zh="谁和谁存在分歧" />
        {(anatomy?.entity_opposition ?? []).length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">暂无主体级对立数据。</p>
        ) : (
          <div className="mt-3 flex flex-col gap-3">
            {anatomy!.entity_opposition.map((o) => (
              <div key={o.entity_id} className="border border-border/60 p-3">
                <div className="flex items-baseline justify-between text-sm">
                  <span className="font-medium">{o.entity_id}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    官方 {o.n_official} 行 · 市场 {o.n_market} 行 · 态度差 Δ{o.gap.toFixed(2)}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-3 gap-4 text-xs">
                  {(["supportive", "neutral", "critical"] as const).map((k) => (
                    <div key={k}>
                      <p className="paper-kicker">{k}</p>
                      <p className="mt-1 font-mono">
                        官方 {Math.round((o.official[k] ?? 0) * 100)}% vs 市场{" "}
                        {Math.round((o.market[k] ?? 0) * 100)}%
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        <SectionHead no="05" en="How narratives differ" zh="叙事地图" />
        {(anatomy?.cluster_pairs ?? []).length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">
            信源簇样本不足，暂无法绘制叙事距离（弃权而非硬凑）。
          </p>
        ) : (
          <div className="mt-3 flex flex-col gap-3">
            {anatomy!.cluster_pairs.map((p) => {
              const dist = Math.min(1, p.jsd);
              return (
                <div key={`${p.a}-${p.b}`}>
                  <div className="flex items-baseline justify-between text-xs">
                    <span className="font-medium">
                      {p.a} {p.official_vs_market ? "（官方）" : ""} ↔ {p.b}{" "}
                      {p.official_vs_market ? "（市场）" : ""}
                    </span>
                    <span className="font-mono text-muted-foreground">
                      解释距离 {Math.round(dist * 100)}%
                    </span>
                  </div>
                  <div className="mt-1 h-2 w-full bg-muted">
                    <div
                      className="h-2"
                      style={{ width: `${dist * 100}%`, backgroundColor: SIGNAL.divergence }}
                    />
                  </div>
                </div>
              );
            })}
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">各信源簇的框架构成</summary>
              {Object.entries(anatomy!.clusters).map(([tier, dist]) => {
                const top = Object.entries(dist).sort((a, b) => b[1] - a[1])[0];
                return (
                  <p key={tier} className="mt-1 font-mono">
                    {tier} 主导框架：{FRAME_ZH[top[0]] ?? top[0]}（{Math.round(top[1] * 100)}%）
                  </p>
                );
              })}
            </details>
          </div>
        )}

        <SectionHead no="06" en="Evidence" zh="证据（按信源层级）" />
        {tiers.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">暂无证据行。</p>
        ) : (
          <div className="mt-3 flex flex-col gap-5">
            {tiers.map((tier) => {
              const g = TIER_GROUP[tier] ?? { label: tier, zh: tier, order: 9 };
              return (
                <div key={tier}>
                  <p className="paper-kicker">
                    {g.label} · {g.zh}（{grouped[tier].length}）
                  </p>
                  {grouped[tier].slice(0, 4).map((row, i) => (
                    <p key={i} className="mt-1 font-paper text-sm leading-6">
                      <span className="mr-2 font-mono text-[10px] uppercase text-muted-foreground">
                        {row.source_id} · {FRAME_ZH[row.frame] ?? row.frame}
                      </span>
                      “{row.quote.length > 140 ? `${row.quote.slice(0, 140)}…` : row.quote}”
                    </p>
                  ))}
                </div>
              );
            })}
            <details>
              <summary className="cursor-pointer text-xs text-muted-foreground">
                句级叙事光谱（{spectrum.length} 篇文章逐句框架染色）
              </summary>
              <div className="mt-2 flex flex-col gap-2">
                {spectrum.slice(0, 5).map((d) => (
                  <p key={d.item_key} className="text-xs leading-6 text-muted-foreground">
                    <span className="font-mono">{d.source_id}</span>：{d.sentences.slice(0, 6).map((s) => s.text).join("")}
                  </p>
                ))}
              </div>
            </details>
            <QueueSection />
            <DissectionPanel itemKeys={[...new Set(evidence.map((r) => r.item_key))]} />
            <ReportSection itemKeys={[...new Set(evidence.map((r) => r.item_key))]} />
          </div>
        )}

        <SectionHead no="07" en="Ask the analyst" zh="下一步研究" />
        <div className="mt-3 flex flex-col gap-2">
          {askQuestions.map((q) => (
            <Link
              key={q}
              href={`/research?q=${encodeURIComponent(q)}&event=${encodeURIComponent(id)}`}
              className="border border-border/60 px-3 py-2 text-sm hover:border-primary"
            >
              {q}
            </Link>
          ))}
        </div>
      </article>

      <aside className="lg:col-span-4">
        <div className="border border-border/60 p-4 lg:sticky lg:top-6">
          <p className="paper-kicker">EVENT SUMMARY</p>
          <p className="mt-2 font-paper text-sm leading-6">
            {meta.n_sources} 源 · 分歧状态「{lv.zh}」{trend} ·{" "}
            {anatomy?.cluster_pairs.length ?? 0} 组信源簇距离可比较
          </p>
          <div className="mt-3 border-t border-border/60 pt-3">
            <p className="paper-kicker">YOUR NEXT STEPS</p>
            <ul className="mt-2 flex flex-col gap-1 text-xs text-muted-foreground">
              <li>→ 点击预设问题进入研究台</li>
              <li>→ 在研究台保存结论到档案库</li>
              <li>→ 在订阅中心追踪相关实体</li>
            </ul>
          </div>
        </div>
      </aside>
    </div>
    <AgentDock agentKind="dissection" title="拆解助手" position="right" />
    </>
  );
}
