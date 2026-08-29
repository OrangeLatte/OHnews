"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { api, type EvidenceRow, type SignalRow, type TodayBriefing } from "@/lib/api";

const KIND_META: Record<string, { label: string; color: string }> = {
  attention_spike: { label: "Attention Spike", color: "#f0b429" },
  narrative_shift: { label: "Narrative Shift", color: "#bc8cff" },
  ndi_alert: { label: "Narrative Divergence", color: "#e5534b" },
  expectation_gap: { label: "Expectation Gap", color: "#d29922" },
};

const SIGNAL_METRIC_LABELS: Record<string, string> = {
  z: "z-score",
  jsd: "JSD",
  ndi: "NDI",
  delta: "Δ",
  gap: "ΔT",
};

function MetricChips({ s }: { s: SignalRow }) {
  const chips = Object.entries(s.metrics)
    .filter(([k]) => SIGNAL_METRIC_LABELS[k])
    .slice(0, 3);
  return (
    <div className="flex gap-2 font-mono text-[11px] text-muted-foreground">
      {chips.map(([k, v]) => (
        <span key={k} className="rounded border border-border/70 px-1.5 py-0.5">
          {SIGNAL_METRIC_LABELS[k]} {v}
        </span>
      ))}
      <span className="rounded border border-border/70 px-1.5 py-0.5">
        conf {s.confidence.toFixed(2)}
      </span>
    </div>
  );
}

function InlineEvidence({ rows }: { rows: EvidenceRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="mt-3 border-l-2 border-primary/30 pl-3">
      <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        Evidence preview
      </h3>
      {rows.slice(0, 3).map((e, i) => (
        <p key={i} className="mb-1 font-paper text-sm leading-6">
          <span className="mr-2 font-mono text-[10px] uppercase text-muted-foreground">
            {e.source_id}·{e.frame}
          </span>
          “{e.quote.length > 120 ? `${e.quote.slice(0, 120)}…` : e.quote}”
        </p>
      ))}
    </div>
  );
}

function SignalCard({
  s,
  index,
  evidence,
}: {
  s: SignalRow;
  index: number;
  evidence: EvidenceRow[];
}) {
  const meta = KIND_META[s.kind] ?? { label: s.kind, color: "#8b949e" };
  const evidenceId = s.evidence_ids[0];
  // attention_spike 无事件关联，Ask Analyst 以实体为 target；其余以事件为 target
  const hasEventTarget = Boolean(evidenceId);
  const askHref = hasEventTarget
    ? `/agent?intent=explain_signal&target_kind=signal&target_id=${encodeURIComponent(s.signal_id)}`
    : `/agent?intent=explain_signal&target_kind=entity&target_id=${encodeURIComponent(s.entity_id)}`;
  return (
    <article className="border-b border-border/60 py-6 first:pt-2 last:border-b-0">
      <div className="mb-2 flex items-baseline gap-3">
        <span className="font-serif text-3xl font-semibold text-muted-foreground/40">
          {String(index + 1).padStart(2, "0")}
        </span>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span
              className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white"
              style={{ backgroundColor: meta.color }}
            >
              {meta.label}
            </span>
            <h2 className="text-lg font-semibold leading-tight">{s.title}</h2>
          </div>
        </div>
        <div className="text-right">
          <div className="font-mono text-xl font-semibold">{Math.round(s.strength)}</div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
            strength
          </div>
        </div>
      </div>
      <div className="mb-1 flex gap-10 pl-12">
        <div className="flex-1">
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            What changed
          </h3>
          <p className="text-sm leading-6">{s.what_changed}</p>
        </div>
        {s.why_it_matters && (
          <div className="flex-1">
            <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Why it matters
            </h3>
            <p className="text-sm leading-6 text-muted-foreground">{s.why_it_matters}</p>
          </div>
        )}
      </div>
      {evidence.length > 0 && (
        <div className="pl-12">
          <InlineEvidence rows={evidence} />
        </div>
      )}
      <div className="mt-3 flex items-center gap-3 pl-12">
        <MetricChips s={s} />
        <div className="ml-auto flex gap-2">
          <Link
            href={askHref}
            className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Ask Analyst
          </Link>
          {hasEventTarget && (
            <>
              <Link
                href={`/analyze/${encodeURIComponent(evidenceId)}`}
                className="rounded-md border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
              >
                Compare narratives
              </Link>
              <Link
                href={`/events/${encodeURIComponent(evidenceId)}`}
                className="rounded-md border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
              >
                Show evidence
              </Link>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

export default function TodayPage() {
  const [briefing, setBriefing] = useState<TodayBriefing | null>(null);
  const [evidenceMap, setEvidenceMap] = useState<Record<string, EvidenceRow[]>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .today(10)
      .then((b) => {
        setBriefing(b);
        // R1：事件类 Signal 内联证据预览（并行拉取，静默失败不阻断）
        for (const s of b.signals) {
          const eid = s.evidence_ids[0];
          if (!eid || evidenceMap[eid]) continue;
          api
            .eventEvidence(eid)
            .then((rows) =>
              setEvidenceMap((m) => ({ ...m, [eid]: rows.slice(0, 3) })),
            )
            .catch(() => undefined);
        }
      })
      .catch((err) => setError(String(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) return <p className="text-destructive">加载失败：{error}</p>;
  if (!briefing) return <p className="text-sm text-muted-foreground">检测变化中…</p>;

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          Daily Intelligence Briefing · {briefing.date}
        </p>
        <h1 className="font-paper mt-1 text-3xl tracking-tight">
          {briefing.total > 0
            ? `${briefing.total} meaningful changes detected`
            : "今日无显著变化检出"}
        </h1>
        <p className="mt-1 text-xs text-muted-foreground">
          系统持续观察 → 检测变化 → 压缩为最重要的 Signal；点击下钻比较叙事或查看证据。
        </p>
      </header>
      <section>
        {briefing.signals.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            暂无越过检测阈值的 Signal（信息量不足时系统选择弃权而非硬凑数字）。
          </p>
        ) : (
          briefing.signals.map((s, i) => {
            const eid = s.evidence_ids[0];
            return (
              <SignalCard
                key={s.signal_id}
                s={s}
                index={i}
                evidence={eid ? (evidenceMap[eid] ?? []) : []}
              />
            );
          })
        )}
      </section>
    </div>
  );
}
