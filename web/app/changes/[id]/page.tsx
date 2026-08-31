"use client";

/**
 * Change Detail（阶段 1-d 黄金路径第二跳）：ChangeDossier + Evidence Drawer。
 *
 * 硬验收映射：#3 三次操作到原文（卡→本页→引文外链）；#4 支持/反对/缺失三桶+Gap；
 * #7 五状态可区分（加载/无证据/证据不足/过期/错误）；#2 术语仅按需展开（TechnicalAnnex）。
 */

import Link from "next/link";
import { use, useEffect, useRef, useState } from "react";

import {
  api,
  type ChangeDossier,
  type CoverageSummary,
  type DataFreshness,
  type EvidenceBucket,
  type EvidenceCitation,
  type EvidenceGap,
} from "@/lib/api";
import { SIGNAL } from "@/lib/tokens";
import { track } from "@/lib/track";

const KIND_ZH: Record<string, string> = {
  attention_spike: "关注升温",
  narrative_shift: "叙事转变",
  divergence_rise: "分歧扩大",
  expectation_gap: "预期错位",
};

const STATUS_ZH: Record<string, { zh: string; color: string }> = {
  confirmed: { zh: "已证实", color: SIGNAL.confirmed },
  contested: { zh: "存争议", color: SIGNAL.divergence },
  developing: { zh: "进展中", color: SIGNAL.attention },
  unverified: { zh: "未证实", color: SIGNAL.muted },
};

const STALENESS_ZH: Record<string, string> = {
  fresh: "数据新鲜",
  aging: "数据开始变旧",
  stale: "数据已过期",
};

const GAP_REASON_ZH: Record<string, string> = {
  no_primary_source: "暂无官方一手来源",
  single_cluster: "来源集中于单一阵营",
  time_gap: "关键时段缺少报道",
  source_silent: "相关方保持沉默",
};

const BUCKETS: { key: EvidenceBucket; zh: string }[] = [
  { key: "supporting", zh: "支持" },
  { key: "contradicting", zh: "反对" },
  { key: "context", zh: "上下文" },
];

function fmtOpt(x: number | null | undefined): string {
  return x === null || x === undefined ? "不可测" : x.toFixed(2);
}

function FreshnessLine({ f }: { f: DataFreshness }) {
  const stale = f.staleness === "stale";
  return (
    <span
      className="paper-kicker"
      style={{ color: stale ? SIGNAL.warning : SIGNAL.muted }}
      title={`覆盖 ${f.coverage_start ?? "?"} 至 ${f.as_of}`}
    >
      数据截至 {f.as_of.slice(0, 16).replace("T", " ")} UTC ·{" "}
      {STALENESS_ZH[f.staleness] ?? f.staleness}
    </span>
  );
}

function CoverageLine({ c }: { c: CoverageSummary }) {
  return (
    <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
      {c.note}（独立来源 {c.n_independent_sources} 个，官方一手 {c.n_primary_sources} 个
      {c.time_span_days > 0 ? `，跨度 ${c.time_span_days} 天` : ""}
      {(c.languages ?? []).length ? `，${(c.languages ?? []).join(" + ")} 语料` : ""}）。
    </p>
  );
}

function CitationCard({ c }: { c: EvidenceCitation }) {
  const when = c.published_at ? c.published_at.slice(0, 10) : null;
  return (
    <li className="border-b border-foreground/10 py-3">
      <p className="text-[14px] leading-relaxed">{c.quote}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
        <span className="font-paper">{c.source_id}</span>
        <span>{c.source_tier}</span>
        {when && <span>{when}</span>}
        {c.url && (
          <a
            href={c.url}
            target="_blank"
            rel="noreferrer"
            onClick={() => track("source_opened", { objectId: c.item_key })}
            className="underline underline-offset-2 hover:text-foreground"
          >
            查看原文 ↗
          </a>
        )}
      </div>
    </li>
  );
}

function GapList({ gaps }: { gaps: EvidenceGap[] }) {
  if (!gaps.length) return null;
  return (
    <div
      className="mt-5 border border-dashed p-3"
      style={{ borderColor: SIGNAL.warning }}
    >
      <p className="paper-kicker" style={{ color: SIGNAL.warning }}>
        缺失的证据
      </p>
      <ul className="mt-2 space-y-1.5 text-[13px] leading-relaxed">
        {gaps.map((g) => (
          <li key={g.gap_id}>
            {g.expectation}
            {g.reason in GAP_REASON_ZH && (
              <span className="text-muted-foreground">
                （{GAP_REASON_ZH[g.reason]}）
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Drawer({ d, changeId }: { d: ChangeDossier; changeId: string }) {
  const [bucket, setBucket] = useState<EvidenceBucket>("supporting");
  const items = (d.evidence[bucket] as EvidenceCitation[] | undefined) ?? [];
  const empty =
    (((d.evidence.supporting ?? []).length +
      (d.evidence.contradicting ?? []).length +
      (d.evidence.context ?? []).length) === 0);
  const pickBucket = (key: EvidenceBucket) => {
    setBucket(key);
    track("evidence_opened", { objectId: changeId, meta: { bucket: key } });
    if (key === "contradicting") {
      track("counter_evidence_requested", { objectId: changeId });
    }
  };
  const seenRef = useRef(false);
  useEffect(() => {
    if (empty && !seenRef.current) {
      seenRef.current = true;
      track("insufficient_evidence_seen", { objectId: changeId });
    }
  }, [empty, changeId]);
  return (
    <div>
      <div className="flex gap-4 border-b border-foreground/20 text-[13px]">
        {BUCKETS.map((b) => {
          const n = (d.evidence[b.key] as EvidenceCitation[]).length;
          const active = b.key === bucket;
          return (
            <button
              key={b.key}
              type="button"
              onClick={() => pickBucket(b.key)}
              className="pb-1.5"
              style={{
                borderBottom: active
                  ? `2px solid ${SIGNAL.divergence}`
                  : "2px solid transparent",
                color: active ? SIGNAL.divergence : undefined,
              }}
            >
              {b.zh}
              <span className="ml-1 text-muted-foreground">{n}</span>
            </button>
          );
        })}
      </div>
      {empty ? (
        <p className="py-6 text-[14px] text-muted-foreground">
          暂无可引用的证据条目（该变化可能来自少量报道，尚未形成可追溯的证据链）。
        </p>
      ) : items.length === 0 ? (
        <p className="py-6 text-[14px] text-muted-foreground">
          此桶暂无条目——不代表没有相反证据，只是现有语料中未观测到。
        </p>
      ) : (
        <ul>
          {items.map((c) => (
            <CitationCard key={c.item_key} c={c} />
          ))}
        </ul>
      )}
      <GapList gaps={d.evidence.gaps ?? []} />
    </div>
  );
}

function Coverage({ c }: { c: CoverageSummary }) {
  return (
    <section className="mt-8">
      <h2 className="font-paper text-base">证据覆盖情况</h2>
      <CoverageLine c={c} />
    </section>
  );
}

export default function ChangeDetailPage({
  params,
}: PageProps<"/changes/[id]">) {
  const { id } = use(params);
  const [dossier, setDossier] = useState<ChangeDossier | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    api
      .changeDossier(id)
      .then((d) => {
        if (!alive) return;
        setDossier(d);
        setLoading(false);
        track("change_opened", {
          objectId: id,
          freshness: d.freshness.as_of,
        });
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "加载失败");
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [id]);

  if (loading) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-16">
        <p className="text-muted-foreground">正在加载变化详情…</p>
      </main>
    );
  }
  if (error || !dossier) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-16">
        <p style={{ color: SIGNAL.warning }}>
          {error ?? "未找到该变化"}——
          <Link href="/" className="underline underline-offset-2">
            返回今日简报
          </Link>
        </p>
      </main>
    );
  }

  const status = STATUS_ZH[dossier.status] ?? STATUS_ZH.unverified;
  return (
    <main className="mx-auto max-w-3xl px-4 pb-20">
      <div className="border-b border-foreground/20 py-3">
        <Link href="/" className="paper-kicker hover:text-foreground">
          ← 返回今日简报
        </Link>
      </div>

      <header className="pt-6">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="paper-kicker">
            {KIND_ZH[dossier.kind] ?? dossier.kind}
          </span>
          <span
            className="inline-flex items-center gap-1.5 text-[13px]"
            style={{ color: status.color }}
          >
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: status.color }}
            />
            {status.zh}
          </span>
        </div>
        <h1 className="mt-2 font-paper text-3xl leading-tight">
          {dossier.headline}
        </h1>
        <div className="mt-2">
          <FreshnessLine f={dossier.freshness} />
        </div>
        {(dossier.subjects ?? []).length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {(dossier.subjects ?? []).map((s) => (
              <span
                key={`${s.kind}-${s.id}`}
                className="border border-foreground/20 px-2 py-0.5 text-[12px]"
              >
                {s.label}
              </span>
            ))}
          </div>
        )}
      </header>

      <section className="mt-6 space-y-3">
        <p className="text-[15px] leading-relaxed">{dossier.what}</p>
        <p className="text-[15px] leading-relaxed text-muted-foreground">
          {dossier.why_now}
        </p>
      </section>

      <Coverage c={dossier.coverage} />

      <section className="mt-8">
        <h2 className="font-paper text-base">证据</h2>
        <div className="mt-3">
          <Drawer d={dossier} changeId={id} />
        </div>
      </section>

      {dossier.technical && (
        <details className="mt-10 border-t border-foreground/20 pt-3">
          <summary className="paper-kicker cursor-pointer select-none">
            技术指标（面向进阶读者）
          </summary>
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-[13px] sm:grid-cols-3">
            {[
              ["信号 ID", dossier.technical.signal_id],
              ["引擎", dossier.technical.engine],
              ["叙事分歧指数", fmtOpt(dossier.technical.ndi)],
              ["框架分布距离", fmtOpt(dossier.technical.jsd)],
              ["官方-市场温差", fmtOpt(dossier.technical.temperature_gap)],
              [
                "智能分",
                dossier.technical.intelligence_score == null
                  ? "不可测"
                  : String(dossier.technical.intelligence_score),
              ],
            ].map(([k, v]) => (
              <div key={k as string} className="flex justify-between gap-2">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="text-right">{v}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-2 text-[12px] text-muted-foreground">
            叙事分歧指数（NDI）为描述性监测指标，不构成方向性判断。
          </p>
        </details>
      )}
    </main>
  );
}
