"use client";

/**
 * 未复核 MonitorUpdate 卡：summary + delta 关键值 + evidence_refs + HITL 三按钮组。
 * 主操作实色（建候选 Case）/ 次操作描边（加入已有 Case，展开下拉）/ 危险红描边（忽略）。
 */

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ConfirmButton } from "@/components/ui/confirm-button";
import type { CaseRow, MonitorUpdateRow } from "@/lib/object-api";
import { relTime } from "./format";
import { type TFunc, ToneChip } from "./bits";

function fmtDelta(v: unknown): string {
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/** Update 审核状态三态 → 徽标色调（unreviewed 琥珀 / accepted 绿 / ignored 灰）。 */
function reviewTone(status: "unreviewed" | "accepted" | "ignored"): "warn" | "ok" | "idle" {
  if (status === "accepted") return "ok";
  if (status === "ignored") return "idle";
  return "warn";
}

export function UpdateCard({
  u,
  cases,
  joinCaseId,
  onJoinCaseChange,
  onDecide,
  busy,
  t,
  lang,
}: {
  u: MonitorUpdateRow;
  cases: CaseRow[];
  joinCaseId: string;
  onJoinCaseChange: (updateId: string, caseId: string) => void;
  onDecide: (u: MonitorUpdateRow, decision: "new_case" | "join_case" | "ignore") => void;
  busy: boolean;
  t: TFunc;
  lang: "en" | "zh";
}) {
  const [picking, setPicking] = useState(false);
  const [analysis, setAnalysis] = useState<{
    engine: string;
    status: string;
    model_hint?: string;
    error?: string;
    analysis: {
      executive_summary: string;
      what_changed: string[];
      evidence_assessment: string[];
      uncertainties: string[];
      recommended_review: string;
    };
  } | null>(null);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const deltaEntries = Object.entries(u.delta ?? {});
  const reviewStatus = u.review_status ?? "unreviewed";
  const decided = reviewStatus !== "unreviewed";
  const generateAnalysis = async (): Promise<void> => {
    setAnalysisBusy(true);
    try {
      const response = await fetch(`/api/monitors/updates/${encodeURIComponent(u.update_id)}/analysis`, {
        method: "POST",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setAnalysis((await response.json()) as typeof analysis);
    } catch (error) {
      setAnalysis({
        engine: "offline",
        status: "error",
        error: error instanceof Error ? error.message : String(error),
        analysis: {
          executive_summary: "Analysis could not be loaded.",
          what_changed: [],
          evidence_assessment: [],
          uncertainties: [],
          recommended_review: "Review the source evidence before deciding.",
        },
      });
    } finally {
      setAnalysisBusy(false);
    }
  };

  return (
    <li className="rounded-xl border bg-card p-3">
      <p className="text-[13px] leading-relaxed">{u.summary}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <ToneChip tone={reviewTone(reviewStatus)}>{t(`monitors.reviewStatus.${reviewStatus}`)}</ToneChip>
        {reviewStatus === "accepted" && u.decision_case_id && (
          <Link
            href={`/cases/${encodeURIComponent(u.decision_case_id)}`}
            className="font-mono text-xs underline text-muted-foreground hover:text-foreground"
          >
            {u.decision_case_id}
          </Link>
        )}
      </div>
      {deltaEntries.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-medium text-muted-foreground">{t("monitors.delta")}</p>
          <dl className="mt-1 grid gap-x-4 gap-y-0.5 sm:grid-cols-2">
            {deltaEntries.map(([k, v]) => (
              <div key={k} className="flex min-w-0 gap-1 text-xs">
                <dt className="shrink-0 font-medium text-muted-foreground">{k}</dt>
                <dd className="truncate font-mono" title={fmtDelta(v)}>
                  {fmtDelta(v)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span>{relTime(u.created_at, lang)}</span>
        <span>
          · {t("monitors.suggested")}: <span className="font-mono">{u.suggested_case_action}</span>
        </span>
      </p>
      {u.evidence_refs.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {u.evidence_refs.map((ref) => (
            <span
              key={ref}
              className="max-w-full truncate rounded-md border bg-muted/60 px-1.5 py-0.5 font-mono text-xs text-muted-foreground"
              title={ref}
            >
              {ref}
            </span>
          ))}
        </div>
      )}
      <div className="mt-3 rounded-lg border bg-muted/20 p-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-medium">{lang === "zh" ? "Agent 增量分析" : "Agent increment analysis"}</p>
          <Button size="sm" variant="outline" disabled={analysisBusy} onClick={() => void generateAnalysis()}>
            {analysisBusy
              ? lang === "zh"
                ? "分析中…"
                : "Analyzing…"
              : analysis
                ? lang === "zh"
                  ? "重新分析"
                  : "Regenerate"
                : lang === "zh"
                  ? "生成分析"
                  : "Generate analysis"}
          </Button>
        </div>
        {analysis ? (
          <div className="mt-2 space-y-2 text-xs">
            <p className="leading-relaxed">{analysis.analysis.executive_summary}</p>
            <p className="text-[11px] text-muted-foreground">
              {analysis.engine === "llm"
                ? `LLM · ${analysis.model_hint ?? "model"}`
                : `${lang === "zh" ? "规则降级（模型未产出）" : "Rule fallback (model did not produce output)"}${analysis.error ? ` · ${analysis.error}` : ""}`}
            </p>
            {[
              [lang === "zh" ? "变化" : "Changes", analysis.analysis.what_changed],
              [lang === "zh" ? "证据评估" : "Evidence assessment", analysis.analysis.evidence_assessment],
              [lang === "zh" ? "不确定性" : "Uncertainties", analysis.analysis.uncertainties],
            ].map(([title, rows]) =>
              Array.isArray(rows) && rows.length > 0 ? (
                <div key={String(title)}>
                  <p className="font-medium text-muted-foreground">{title}</p>
                  <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-muted-foreground">
                    {rows.map((row) => <li key={row}>{row}</li>)}
                  </ul>
                </div>
              ) : null,
            )}
            <p className="rounded-md border border-dashed p-1.5 text-muted-foreground">
              {analysis.analysis.recommended_review}
            </p>
          </div>
        ) : null}
      </div>
      {!decided && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <ConfirmButton
            onConfirm={() => onDecide(u, "new_case")}
            confirmLabel={t("monitors.confirmNewCase")}
            disabled={busy}
            className="inline-flex h-8 items-center justify-center gap-2 whitespace-nowrap rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            armedClassName="bg-amber-600 hover:bg-amber-700"
            title={t("monitors.acceptNew")}
          >
            {t("monitors.acceptNew")}
          </ConfirmButton>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            aria-expanded={picking}
            onClick={() => setPicking((v) => !v)}
          >
            {t("monitors.joinCase")}
          </Button>
          <ConfirmButton
            onConfirm={() => onDecide(u, "ignore")}
            confirmLabel={t("monitors.confirmIgnore")}
            disabled={busy}
            className="inline-flex h-8 items-center justify-center gap-2 whitespace-nowrap rounded-md border px-3 text-xs font-medium hover:bg-accent border-[#dc2626]/60 text-[#b91c1c] hover:bg-[#fee2e2] hover:text-[#b91c1c] dark:border-[#dc2626]/50 dark:text-[#f87171] dark:hover:bg-[#dc2626]/15 dark:hover:text-[#f87171]"
            armedClassName="bg-[#dc2626] text-white hover:bg-[#b91c1c]"
          >
            {t("monitors.ignore")}
          </ConfirmButton>
          {busy && <span className="text-xs text-muted-foreground">{t("monitors.reviewing")}</span>}
        </div>
      )}
      {decided && (
        <p className="mt-3 text-xs text-muted-foreground">{t("monitors.allReviewed")}</p>
      )}
      {picking && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border bg-muted/40 p-2">
          <select
            className="h-8 min-w-56 rounded-md border bg-background px-2 text-xs"
            value={joinCaseId}
            onChange={(e) => onJoinCaseChange(u.update_id, e.target.value)}
          >
            <option value="">{t("monitors.pickCase")}</option>
            {cases.map((c) => (
              <option key={c.case_id} value={c.case_id}>
                {c.case_id} · {c.question.slice(0, 32)}
              </option>
            ))}
          </select>
          <ConfirmButton
            onConfirm={() => {
              setPicking(false);
              onDecide(u, "join_case");
            }}
            confirmLabel={t("monitors.confirmJoinCase")}
            disabled={busy || !joinCaseId}
            className="inline-flex h-8 items-center justify-center gap-2 whitespace-nowrap rounded-md border px-3 text-xs font-medium hover:bg-accent"
            armedClassName="bg-amber-600 text-white hover:bg-amber-700"
          >
            {t("monitors.joinCase")}
          </ConfirmButton>
        </div>
      )}
    </li>
  );
}
