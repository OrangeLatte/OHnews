"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { api, type SignalRow, type TodayBriefing } from "@/lib/api";

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

function SignalCard({ s, index }: { s: SignalRow; index: number }) {
  const meta = KIND_META[s.kind] ?? { label: s.kind, color: "#8b949e" };
  const evidenceId = s.evidence_ids[0];
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
      <div className="mt-3 flex items-center gap-3 pl-12">
        <MetricChips s={s} />
        <div className="ml-auto flex gap-2">
          {evidenceId && (
            <>
              <Link
                href={`/analyze/${encodeURIComponent(evidenceId)}`}
                className="rounded-md border border-border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
              >
                Compare narratives
              </Link>
              <Link
                href={`/events/${encodeURIComponent(evidenceId)}`}
                className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .today(10)
      .then(setBriefing)
      .catch((err) => setError(String(err)));
  }, []);

  if (error) return <p className="text-destructive">加载失败：{error}</p>;
  if (!briefing) return <p className="text-sm text-muted-foreground">检测变化中…</p>;

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          Daily Intelligence Briefing · {briefing.date}
        </p>
        <h1 className="mt-1 text-2xl font-semibold">
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
          briefing.signals.map((s, i) => <SignalCard key={s.signal_id} s={s} index={i} />)
        )}
      </section>
    </div>
  );
}
