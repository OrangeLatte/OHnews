"use client";

/**
 * REPORT 模式：7 类型报告卡选择 → run → 草稿预览（revisions draft content.sections）
 * → 版本列表（v1/v2 状态色）→ 「确认并归档」HITL commit（window.confirm；422 needChallenge 处理）。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { HelpIcon } from "@/components/help/help-icon";
import { Skeleton, toast } from "@/components/ui/toast";
import { objectApi, type ReportInputs, type RevisionRow, type WorkflowOut } from "@/lib/object-api";
import { readAnalysisLocale } from "@/lib/analysis-locale";
import { useT } from "@/lib/i18n/use-t";
import { revStatusLabel, runStatusLabel } from "@/lib/i18n/labels";
import { ModeHeader, StatusPill, FriendlyErrorBox, stampId } from "@/components/case/case-shared";

const REPORT_TYPES = [
  "veracity",
  "intent",
  "attribution",
  "narrative",
  "trend",
  "structured_summary",
  "econ_financial",
] as const;
type ReportType = (typeof REPORT_TYPES)[number];

type Section = {
  title?: string;
  body?: string;
  evidence_refs?: string[];
};

/** 后端 revisions content（lib 类型未含本地扩展字段）。 */
type RevisionWithContent = RevisionRow & {
  content?: {
    sections?: Section[];
    engine?: string;
    model_hint?: string;
    inputs?: ReportInputs;
    /** P0-C 版本元数据：修订溯源 / 反馈原文 / Prompt 版本 / 报告类型 */
    revised_from?: string;
    feedback?: string;
    prompt_version?: string;
    report_type?: string;
  };
};

type Props = {
  caseId: string;
  caseQuestion: string;
  busy: boolean;
  setBusy: (v: boolean) => void;
  reportOut: WorkflowOut | null;
  setReportOut: (out: WorkflowOut | null) => void;
  /** detail.analysis_runs：刷新/换会话后从最近成功 report run 恢复历史草稿预览 */
  historyRuns?: {
    run_id?: string;
    kind: string;
    status: string;
    output?: unknown;
  }[];
};

const revPill = (status: string): string =>
  status === "committed"
    ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
    : status === "superseded"
      ? "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300"
      : "bg-amber-500/10 text-amber-700 dark:text-amber-300";

export default function ReportView({
  caseId,
  caseQuestion,
  busy,
  setBusy,
  reportOut,
  setReportOut,
  historyRuns,
}: Props) {
  const t = useT();
  const [reportType, setReportType] = useState<ReportType>("structured_summary");
  const [revisions, setRevisions] = useState<RevisionWithContent[] | null>(null);
  const [selectedRevId, setSelectedRevId] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [needChallenge, setNeedChallenge] = useState(false);
  // REPORT 运行中提示：busy 为工作台级共享态（commit 等也置位），run 本身用独立标记
  const [reportRunning, setReportRunning] = useState(false);
  // T3 反馈修订：草稿反馈输入 → 新版本追加（旧草稿不动）
  const [feedback, setFeedback] = useState("");

  // 会话内结果优先；无则从 HISTORY runs 恢复最近成功的 report 产物（刷新后不丢草稿）
  const effectiveOut = useMemo<WorkflowOut | null>(() => {
    if (reportOut) return reportOut;
    const hit = (historyRuns ?? []).find(
      (x: unknown) => {
        const r = x as { kind?: string; status?: string; output?: WorkflowOut | null };
        return r.kind === "report" && r.status === "succeeded" && !!r.output?.artifact_id;
      },
    ) as { output?: WorkflowOut | null } | undefined;
    return hit?.output ?? null;
  }, [reportOut, historyRuns]);
  const artifactId = effectiveOut?.artifact_id ?? null;
  const effectiveRevId = effectiveOut?.revision_id ?? null;
  const revLoading = artifactId !== null && revisions === null;

  // 版本 → 源 run 状态映射（T4 归档门前端显式化：后端 422 同源判定）
  const runStatusById = useMemo(() => {
    const m = new Map<string, string>();
    for (const x of historyRuns ?? []) {
      const r = x as { run_id?: string; status?: string };
      if (r.run_id && r.status) m.set(r.run_id, r.status);
    }
    return m;
  }, [historyRuns]);

  const loadRevisions = useCallback((aid: string, preferRev?: string | null) => {
    let alive = true;
    objectApi
      .artifactRevisions(aid)
      .then((rows) => {
        if (!alive) return;
        const sorted = ([...rows] as RevisionWithContent[]).sort((a, b) =>
          a.created_at.localeCompare(b.created_at),
        );
        setRevisions(sorted);
        const wanted =
          (preferRev ? sorted.find((r) => r.revision_id === preferRev) : undefined) ??
          [...sorted].reverse().find((r) => r.status === "draft") ??
          sorted[sorted.length - 1];
        setSelectedRevId(wanted?.revision_id ?? null);
      })
      .catch(() => {
        if (alive) setRevisions([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!artifactId) return;
    return loadRevisions(artifactId, effectiveRevId ?? null);
  }, [artifactId, loadRevisions, effectiveRevId]);

  const runReport = () => {
    setBusy(true);
    setRunError(null);
    setNeedChallenge(false);
    setReportRunning(true);
    const analysisLocale = readAnalysisLocale();
    objectApi
      .report(caseId, {
        report_type: reportType,
        title: `${caseQuestion || caseId} · ${reportType}`,
        ...(analysisLocale ? { analysis_locale: analysisLocale } : {}),
      })
      .then((r) => {
        if (r.status === "failed" || !r.output) {
          setReportOut(null);
          const msg = r.error || r.status;
          setRunError(msg);
          toast.error(`${t("case.runError")}: ${msg}`);
          return;
        }
        setReportOut(r.output);
        if (r.output.status === "succeeded") toast.success(t("case.reportDone"));
        else toast.info(`${t("case.status")}: ${r.output.status}`);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : t("case.loadFailed");
        setRunError(msg);
        toast.error(msg);
      })
      .finally(() => {
        setBusy(false);
        setReportRunning(false);
      });
  };

  const selectedRev = revisions?.find((r) => r.revision_id === selectedRevId) ?? null;

  // T4：草稿对应 run 非 succeeded → 禁归档（含 effectiveOut 历史恢复路径判定）
  const archiveBlocked = useMemo(() => {
    if (!selectedRev || selectedRev.status !== "draft") return false;
    const src = selectedRev.run_id ? runStatusById.get(selectedRev.run_id) : undefined;
    if (src) return src !== "succeeded";
    if (selectedRev.revision_id === effectiveRevId && effectiveOut) {
      return effectiveOut.status !== "succeeded";
    }
    return false;
  }, [selectedRev, runStatusById, effectiveRevId, effectiveOut]);

  /** T3 反馈修订：反馈注入 → 新 run → 新版本追加到同一 artifact（旧草稿不动）。 */
  const reviseReport = () => {
    const text = feedback.trim();
    if (!text) return;
    // 修订跟随当前草稿的报告类型（content.report_type 缺省回退当前选择卡）
    const revType = selectedRev?.content?.report_type ?? reportType;
    setBusy(true);
    setRunError(null);
    setNeedChallenge(false);
    setReportRunning(true);
    const analysisLocale = readAnalysisLocale();
    objectApi
      .report(caseId, {
        report_type: revType,
        title: `${caseQuestion || caseId} · ${revType}`,
        feedback: text,
        ...(analysisLocale ? { analysis_locale: analysisLocale } : {}),
      })
      .then((r) => {
        if (r.status === "failed" || !r.output) {
          const msg = r.error || r.status;
          setRunError(msg);
          toast.error(`${t("case.runError")}: ${msg}`);
          return;
        }
        setReportOut(r.output);
        setFeedback("");
        if (r.output.status === "succeeded") toast.success(t("case.reviseDone"));
        else toast.info(`${t("case.status")}: ${r.output.status}`);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : t("case.loadFailed");
        setRunError(msg);
        toast.error(msg);
      })
      .finally(() => {
        setBusy(false);
        setReportRunning(false);
      });
  };

  const commitDraft = () => {
    if (!artifactId || !selectedRev || selectedRev.status !== "draft") return;
    if (!window.confirm(t("case.confirmCommit"))) return;
    setBusy(true);
    fetch(`/api/artifacts/${encodeURIComponent(artifactId)}/commit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        commit_id: stampId("cmt"),
        revision_id: selectedRev.revision_id,
        user_note: "user confirmed",
      }),
    })
      .then((r) => {
        if (r.ok) {
          toast.success(t("case.committed"));
          setNeedChallenge(false);
          loadRevisions(artifactId, null);
        } else if (r.status === 422) {
          setNeedChallenge(true);
          toast.error(t("case.needChallenge"));
        } else {
          toast.error(`${t("case.loadFailed")} HTTP ${r.status}`);
        }
      })
      .catch(() => toast.error(t("case.loadFailed")))
      .finally(() => setBusy(false));
  };

  const sections: Section[] = Array.isArray(selectedRev?.content?.sections)
    ? (selectedRev!.content!.sections as Section[])
    : [];
  const inputs: ReportInputs | null =
    selectedRev?.content?.inputs ?? effectiveOut?.inputs ?? null;

  return (
    <div className="space-y-3">
      <ModeHeader title={t("case.modeTitle.report")} helpKey="help.mode.report">
        <span className="text-xs text-muted-foreground">{t("case.reportPickHint")}</span>
      </ModeHeader>

      {/* 7 类型选择卡 */}
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {REPORT_TYPES.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setReportType(k)}
            aria-pressed={reportType === k}
            className={`rounded-xl border p-2.5 text-left ${reportType === k ? "border-sky-500 bg-sky-500/5 ring-1 ring-sky-500" : "hover:bg-muted"}`}
          >
            <p className="text-[13px] font-semibold">{t(`case.reportType.${k}`)}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{t(`case.reportDesc.${k}`)}</p>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={runReport}
          className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-50"
        >
          {t("case.draftReport")}
        </button>
        {reportOut ? (
          <>
            <StatusPill status={reportOut.status} label={runStatusLabel(t, reportOut.status)} />
            {reportOut.engine ? (
              <span className="text-xs text-muted-foreground">engine: {reportOut.engine}</span>
            ) : null}
            {reportOut.revision_id ? (
              <span className="font-mono text-[11px] text-muted-foreground">{reportOut.revision_id}</span>
            ) : null}
          </>
        ) : null}
        <HelpIcon helpKey="state.needsConfirm" />
      </div>

      {reportRunning ? (
        <p
          className="flex items-center gap-2 rounded-xl border border-sky-500/40 bg-sky-500/5 p-3 text-xs text-sky-700 dark:text-sky-300"
          aria-live="polite"
        >
          <span aria-hidden className="inline-flex items-center gap-0.5">
            <span className="size-1 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
            <span className="size-1 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
            <span className="size-1 animate-bounce rounded-full bg-current" />
          </span>
          {t("case.reportRunning")}
        </p>
      ) : null}

      {runError ? <FriendlyErrorBox raw={runError} className="rounded-xl border border-red-500/40 bg-red-500/5 p-3 text-xs text-red-700 dark:text-red-300" /> : null}
      {!runError && reportOut && (reportOut.status === "abstained" || reportOut.status === "failed") ? (
        <p className="flex items-center gap-1 rounded-xl border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-700 dark:text-amber-300">
          {t("case.abstainedHint")}
          <HelpIcon helpKey="state.abstained" />
        </p>
      ) : null}

      {needChallenge ? (
        <p className="rounded-xl border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-700 dark:text-amber-300">
          {t("case.needChallengeInline")}
        </p>
      ) : null}

      {/* 草稿预览 + 版本列表 */}
      {artifactId ? (
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
          <section className="rounded-xl border p-3">
            <p className="mb-2 text-[13px] font-semibold">{t("case.reportDraft")}</p>
            {inputs ? (
              <p className="mb-2 rounded-lg border bg-muted/30 px-2 py-1.5 text-[11px] text-muted-foreground">
                <span className="font-medium text-foreground/80">{t("case.reportInputs")}</span>
                {" · "}
                {t("case.inDocs")} {inputs.n_documents} · {t("case.inExtractions")}{" "}
                {inputs.n_extractions} · {t("case.inClaims")} {inputs.n_claims} ·{" "}
                {t("case.inChallenges")} {inputs.n_challenge_runs} · {t("case.inCompares")}{" "}
                {inputs.n_compare_runs}
                {inputs.truncated ? ` · ${t("case.inputsTruncated")}` : null}
              </p>
            ) : null}
            {revLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="h-16 w-full" />
              </div>
            ) : selectedRev ? (
              <>
                {sections.length === 0 ? (
                  <p className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
                    {t("case.reportEmptyBody")}
                  </p>
                ) : (
                  <article className="space-y-3">
                    {sections.map((s, i) => (
                      <div key={`sec-${i}`}>
                        {s.title ? <h3 className="text-[13px] font-semibold">{s.title}</h3> : null}
                        {s.body ? (
                          <p className="mt-1 whitespace-pre-wrap text-[13px] leading-6 text-foreground/90">{s.body}</p>
                        ) : null}
                        {s.evidence_refs?.length ? (
                          <p className="mt-1 flex flex-wrap items-center gap-1">
                            <span className="text-[10px] text-muted-foreground">
                              {t("case.evidenceRefs")}
                            </span>
                            {s.evidence_refs.map((ref) => (
                              <span
                                key={ref}
                                className="rounded bg-muted px-1 py-0.5 font-mono text-[10px] text-muted-foreground"
                              >
                                {ref}
                              </span>
                            ))}
                          </p>
                        ) : null}
                      </div>
                    ))}
                  </article>
                )}
                <p className="mt-3 flex flex-wrap items-center gap-2 border-t pt-2 text-[11px] text-muted-foreground">
                  <span className="font-mono">{selectedRev.revision_id}</span>
                  <span className={`rounded px-1 py-0.5 ${revPill(selectedRev.status)}`}>{revStatusLabel(t, selectedRev.status)}</span>
                  <span>{selectedRev.created_at?.slice(0, 19).replace("T", " ")}</span>
                  {selectedRev.content?.engine ? <span>engine: {selectedRev.content.engine}</span> : null}
                  {selectedRev.content?.model_hint ? <span>{selectedRev.content.model_hint}</span> : null}
                  {selectedRev.content?.prompt_version ? <span>prompt: {selectedRev.content.prompt_version}</span> : null}
                  {selectedRev.content?.revised_from ? (
                    <span className="font-mono">
                      {t("case.revisedFrom")}: {selectedRev.content.revised_from}
                    </span>
                  ) : null}
                  {selectedRev.content?.feedback ? (
                    <span className="max-w-[26rem] truncate" title={selectedRev.content.feedback}>
                      {t("case.feedbackLabel")}: {selectedRev.content.feedback}
                    </span>
                  ) : null}
                </p>
                {selectedRev ? (
                  <div className="mt-3 space-y-2">
                    <textarea
                      value={feedback}
                      onChange={(e) => setFeedback(e.target.value)}
                      placeholder={t("case.reportFeedbackPlaceholder")}
                      rows={2}
                      className="w-full rounded-lg border bg-background px-2 py-1.5 text-xs placeholder:text-muted-foreground"
                    />
                    <button
                      type="button"
                      disabled={busy || !feedback.trim()}
                      onClick={reviseReport}
                      className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-50"
                    >
                      {t("case.reviseFromFeedback")}
                    </button>
                  </div>
                ) : null}
                {selectedRev?.status === "draft" && archiveBlocked ? (
                  <p className="mt-3 rounded-xl border border-amber-500/40 bg-amber-500/5 p-2.5 text-xs text-amber-700 dark:text-amber-300">
                    {t("case.abstainedNoArchive")}
                  </p>
                ) : null}
                {selectedRev?.status === "draft" ? (
                  <button
                    type="button"
                    disabled={busy || archiveBlocked}
                    onClick={commitDraft}
                    className="mt-3 rounded-md border border-emerald-600/50 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-500/10 disabled:opacity-50 dark:text-emerald-300"
                  >
                    {t("case.commitAndArchive")}
                  </button>
                ) : null}
              </>
            ) : (
              <p className="text-xs text-muted-foreground">{t("case.reportEmptyBody")}</p>
            )}
          </section>

          <section className="rounded-xl border p-3">
            <p className="mb-2 text-[13px] font-semibold">{t("case.versions")}</p>
            {revLoading ? (
              <Skeleton className="h-16 w-full" />
            ) : (
              <ul className="space-y-1">
                {(revisions ?? []).map((r, i) => (
                  <li key={r.revision_id}>
                    <button
                      type="button"
                      onClick={() => setSelectedRevId(r.revision_id)}
                      className={`flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-xs ${selectedRevId === r.revision_id ? "border-foreground" : "hover:bg-muted"}`}
                    >
                      <span className="font-mono">v{i + 1}</span>
                      <span className={`rounded px-1 py-0.5 ${revPill(r.status)}`}>{revStatusLabel(t, r.status)}</span>
                      <span className="ml-auto text-[11px] text-muted-foreground">{r.created_at?.slice(0, 10)}</span>
                    </button>
                  </li>
                ))}
                {(revisions ?? []).length === 0 ? (
                  <li className="text-xs text-muted-foreground">{t("case.reportEmptyBody")}</li>
                ) : null}
              </ul>
            )}
          </section>
        </div>
      ) : reportOut ? null : (
        <p className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">{t("case.reportEmpty")}</p>
      )}
    </div>
  );
}
