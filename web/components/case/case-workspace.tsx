"use client";

/**
 * Case Workspace（02 CASES 研究工作台，TradingView 级重构）：
 * READ 原文多色标注+元素卡复核 / MAP 元素×文档编码矩阵 / COMPARE 跨源 diff 表 /
 * REPORT 七类报告+HITL 归档 / HISTORY 运行时间线+Claims。
 * 快捷键 1-5 切换模式；?mode= 经 useSyncExternalStore 以 URL 为唯一真源。
 * 数据流：workspace 持有 detail/docs/ex/bodies 缓存；各模式为纯展示+局部交互。
 */

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Skeleton, toast } from "@/components/ui/toast";
import { HelpIcon } from "@/components/help/help-icon";
import {
  objectApi,
  type CaseDetail,
  type ExtractionRow,
  type WorkflowOut,
} from "@/lib/object-api";
import { readAnalysisLocale } from "@/lib/analysis-locale";
import { useT } from "@/lib/i18n/use-t";
import {
  pushError,
  setActiveDocs,
  setCaseContext,
  setPendingArtifacts,
} from "@/lib/research-state";
import {
  MODES,
  type DocRow,
  type Mode,
  type SourceOption,
} from "@/components/case/case-shared";
import ReadMode from "@/components/case/read-mode";
import ElementMatrix from "@/components/case/element-matrix";
import CompareView from "@/components/case/compare-view";
import ReportView from "@/components/case/report-view";
import HistoryView from "@/components/case/history-view";

// ---------- URL ?mode= 外部源（popstate + replaceState 后手动 notify） ----------
const urlListeners = new Set<() => void>();
let urlCache: { href: string; mode: Mode | null } = { href: "", mode: null };

function readModeFromUrl(): Mode | null {
  const m = new URLSearchParams(window.location.search).get("mode");
  return m !== null && (MODES as readonly string[]).includes(m) ? (m as Mode) : null;
}

function subscribeUrl(cb: () => void): () => void {
  urlListeners.add(cb);
  window.addEventListener("popstate", cb);
  return () => {
    urlListeners.delete(cb);
    window.removeEventListener("popstate", cb);
  };
}

function getUrlMode(): Mode | null {
  const href = window.location.href;
  if (urlCache.href !== href) urlCache = { href, mode: readModeFromUrl() };
  return urlCache.mode;
}

const getServerUrlMode = (): Mode | null => null;

function notifyUrl(): void {
  for (const cb of urlListeners) cb();
}

export default function CaseWorkspace({ caseId }: { caseId: string }) {
  const t = useT();
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [loadTick, setLoadTick] = useState(0);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [sources, setSources] = useState<SourceOption[]>([]);
  const [ex, setEx] = useState<Record<string, ExtractionRow[]>>({});
  const [bodies, setBodies] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [activeDoc, setActiveDoc] = useState<string | null>(null);
  const [dissecting, setDissecting] = useState<string | null>(null);
  const [cmpOut, setCmpOut] = useState<WorkflowOut | null>(null);
  const [reportOut, setReportOut] = useState<WorkflowOut | null>(null);

  const urlMode = useSyncExternalStore(subscribeUrl, getUrlMode, getServerUrlMode);
  const currentMode: Mode = urlMode ?? "read";

  const switchMode = useCallback((m: Mode) => {
    window.history.replaceState(null, "", `?mode=${m}`);
    notifyUrl();
  }, []);

  // 快捷键 1-5 切换模式（输入焦点时跳过）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName ?? "";
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      const idx = Number(e.key) - 1;
      if (idx >= 0 && idx < MODES.length) switchMode(MODES[idx]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [switchMode]);

  // 惰性加载缓存：ref 去重（effect 体内不做同步 setState）
  const loadedBodies = useRef<Set<string>>(new Set());
  const loadedEx = useRef<Set<string>>(new Set());
  const exInflight = useRef<Set<string>>(new Set());

  const ensureBody = useCallback((rid: string) => {
    if (loadedBodies.current.has(rid)) return;
    loadedBodies.current.add(rid);
    objectApi
      .documentBody(rid)
      .then((b) => setBodies((q) => ({ ...q, [rid]: b.body ?? "" })))
      .catch(() => {
        loadedBodies.current.delete(rid);
        setBodies((q) => ({ ...q, [rid]: "" }));
      });
  }, []);

  const ensureAllEx = useCallback((rids: string[]) => {
    for (const rid of rids) {
      if (loadedEx.current.has(rid) || exInflight.current.has(rid)) continue;
      exInflight.current.add(rid);
      objectApi
        .extractions(rid)
        .then((rows) => {
          loadedEx.current.add(rid);
          setEx((q) => ({ ...q, [rid]: rows }));
        })
        .catch(() => {
          exInflight.current.delete(rid);
        });
    }
  }, []);

  // 激活文档时惰性取正文与提取
  useEffect(() => {
    if (!activeDoc) return;
    ensureBody(activeDoc);
    ensureAllEx([activeDoc]);
  }, [activeDoc, ensureBody, ensureAllEx]);

  const reloadDocs = useCallback((): Promise<DocRow[]> => {
    return fetch(`/api/cases/${encodeURIComponent(caseId)}/documents`)
      .then((r) => r.json())
      .then((rows: unknown) => {
        const list = Array.isArray(rows) ? (rows as DocRow[]) : [];
        setDocs(list);
        return list;
      });
  }, [caseId]);

  const refreshDetail = useCallback(() => {
    objectApi
      .caseDetail(caseId)
      .then((d) => setDetail(d))
      .catch(() => null);
  }, [caseId]);

  // 首次/重试加载：detail + docs + 源目录；默认激活第一个文档
  useEffect(() => {
    let alive = true;
    Promise.all([
      objectApi.caseDetail(caseId),
      fetch(`/api/cases/${encodeURIComponent(caseId)}/documents`).then((r) => r.json()),
      fetch("/api/sources?enabled=1").then((r) => r.json()),
    ])
      .then(([d, rows, src]) => {
        if (!alive) return;
        setDetail(d);
        const list = Array.isArray(rows) ? (rows as DocRow[]) : [];
        setDocs(list);
        setSources(Array.isArray(src?.sources) ? (src.sources as SourceOption[]) : []);
        if (list.length > 0) setActiveDoc(list[0].document_revision_id);
        // ResearchState 接线（阶段2 单一状态真源）：Case 上下文 + 激活文档 + report 草稿产物
        setCaseContext(caseId, d.case.question);
        setActiveDocs(
          list.map((r) => r.document_id),
          list.map((r) => r.document_revision_id),
        );
        setPendingArtifacts(
          d.analysis_runs
            .filter(
              (r) => r.kind === "report" && r.status === "succeeded" && r.output_artifact_id,
            )
            .map((r) => {
              const out = (r.output ?? {}) as {
                artifact_id?: string;
                revision_id?: string;
                title?: string;
              };
              return {
                artifact_id: r.output_artifact_id ?? out.artifact_id ?? "",
                revision_id: out.revision_id ?? "",
                title: out.title ?? d.case.question,
              };
            })
            .filter((a) => a.artifact_id !== "" && a.revision_id !== ""),
        );
      })
      .catch(() => {
        if (!alive) return;
        setLoadError(true);
        pushError(`${caseId}: ${t("case.loadFailed")}`);
        toast.error(t("case.loadFailed"));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [caseId, loadTick, t]);

  const retryLoad = () => {
    setLoadError(false);
    setLoading(true);
    setLoadTick((n) => n + 1);
  };

  const runDissect = (rid: string) => {
    setBusy(true);
    setDissecting(rid);
    const analysisLocale = readAnalysisLocale();
    objectApi
      .dissect(caseId, rid, analysisLocale || undefined)
      .then((out) => objectApi.extractions(rid).then((rows) => ({ out, rows })))
      .then(({ out, rows }) => {
        loadedEx.current.add(rid);
        setEx((p) => ({ ...p, [rid]: rows }));
        const status = out.output?.status ?? out.status;
        if (status === "succeeded") {
          toast.success(`${t("case.dissectDone")} · n=${out.output?.n_elements ?? rows.length}`);
        } else {
          toast.info(`${t("case.status")}: ${status}${out.error ? ` · ${out.error}` : ""}`);
        }
      })
      .catch((err: unknown) =>
        toast.error(err instanceof Error ? err.message : t("case.loadFailed")),
      )
      .finally(() => {
        setBusy(false);
        setDissecting(null);
      });
  };

  const reviewExtraction = (extractionId: string, status: "confirmed" | "rejected") => {
    objectApi
      .reviewExtraction(extractionId, status)
      .then(() => {
        setEx((p) => {
          const next: Record<string, ExtractionRow[]> = {};
          for (const [rid, rows] of Object.entries(p)) {
            next[rid] = rows.map((r) =>
              r.extraction_id === extractionId ? { ...r, human_status: status } : r,
            );
          }
          return next;
        });
        toast.success(t("case.reviewed"));
      })
      .catch(() => toast.error(t("case.loadFailed")));
  };

  const modeLabels = useMemo<Record<Mode, string>>(
    () => ({
      read: t("case.modeTitle.read"),
      map: t("case.modeTitle.map"),
      compare: t("case.modeTitle.compare"),
      report: t("case.modeTitle.report"),
      history: t("case.modeTitle.history"),
    }),
    [t],
  );

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-7 w-2/3" />
        <Skeleton className="h-5 w-1/3" />
        <div className="flex gap-2">
          {MODES.map((m) => (
            <Skeleton key={m} className="h-8 w-20" />
          ))}
        </div>
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (loadError && !detail) {
    return (
      <div className="space-y-3 rounded-xl border border-red-500/40 bg-red-500/5 p-4">
        <p className="text-sm font-medium text-red-700 dark:text-red-300">{t("case.loadFailed")}</p>
        <p className="text-xs text-muted-foreground">GET /api/cases/{caseId}</p>
        <button
          type="button"
          onClick={retryLoad}
          className="rounded-md border px-2 py-1 text-xs font-medium hover:bg-muted"
        >
          {t("case.retry")}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {busy ? (
        <div className="fixed inset-x-0 top-0 z-40 h-0.5 overflow-hidden" role="progressbar" aria-label={t("case.running")}>
          <div className="h-full w-1/3 animate-[pulse_1s_ease-in-out_infinite] bg-sky-500" />
        </div>
      ) : null}

      <header className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">{detail?.case.question ?? caseId}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="rounded bg-muted px-1.5 py-0.5 font-mono">{caseId}</span>
            <span className="rounded bg-sky-500/10 px-1.5 py-0.5 text-sky-700 dark:text-sky-300">
              {detail?.case.status}
            </span>
            <span>{detail?.case.origin}</span>
            <span>
              {docs.length} {t("case.documents")}
            </span>
          </p>
        </div>
        <p className="hidden text-xs text-muted-foreground lg:block">{t("case.keyHint")}</p>
      </header>

      {/* 模式导航：sticky 横条；<lg 单行横向滚动不换行，lg+ 换行平铺 */}
      <nav
        className="sticky top-0 z-30 flex flex-nowrap items-center gap-1 overflow-x-auto whitespace-nowrap border-b bg-background lg:flex-wrap lg:overflow-x-visible lg:whitespace-normal"
        aria-label={t("case.modes")}
      >
        {MODES.map((m, i) => (
          <button
            key={m}
            type="button"
            onClick={() => switchMode(m)}
            className={`shrink-0 px-3 py-1.5 text-sm ${currentMode === m ? "border-b-2 border-foreground font-medium" : "text-muted-foreground hover:text-foreground"}`}
            aria-pressed={currentMode === m}
            title={`${i + 1}`}
          >
            {modeLabels[m]}
          </button>
        ))}
        <span className="shrink-0">
          <HelpIcon helpKey={`help.mode.${currentMode}`} />
        </span>
      </nav>

      {currentMode === "read" ? (
        <ReadMode
          caseId={caseId}
          docs={docs}
          sources={sources}
          activeDoc={activeDoc}
          setActiveDoc={setActiveDoc}
          ex={ex}
          bodies={bodies}
          busy={busy}
          dissecting={dissecting}
          onDissect={runDissect}
          onReview={reviewExtraction}
          reloadDocs={reloadDocs}
        />
      ) : null}

      {currentMode === "map" ? (
        <ElementMatrix docs={docs} busy={busy} dissecting={dissecting} onDissect={runDissect} />
      ) : null}

      {currentMode === "compare" ? (
        <CompareView
          caseId={caseId}
          docs={docs}
          ex={ex}
          ensureAllEx={ensureAllEx}
          busy={busy}
          setBusy={setBusy}
          cmpOut={cmpOut}
          setCmpOut={setCmpOut}
        />
      ) : null}

      {currentMode === "report" ? (
        <ReportView
          caseId={caseId}
          caseQuestion={detail?.case.question ?? ""}
          busy={busy}
          setBusy={setBusy}
          reportOut={reportOut}
          setReportOut={setReportOut}
          historyRuns={detail?.analysis_runs}
        />
      ) : null}

      {currentMode === "history" ? (
        <HistoryView
          caseId={caseId}
          detail={detail}
          busy={busy}
          setBusy={setBusy}
          refreshDetail={refreshDetail}
        />
      ) : null}
    </div>
  );
}
