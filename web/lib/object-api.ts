"use client";

/**
 * Object API 客户端（Clean-slate 新对象库 research.sqlite 专用）。
 * 与 lib/api.ts（旧页面大包 API）完全隔离；端点见 oh_api/object_api.py。
 * 工作流运行（launch/poll）统一上报 ResearchState.activeRunId（阶段2 单一状态真源）。
 */

import { setActiveRun } from "@/lib/research-state";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`/api${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

async function patchOrDelete<T>(path: string, method: "DELETE"): Promise<T> {
  const r = await fetch(`/api${path}`, { method });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

export type CaseRow = {
  case_id: string;
  question: string;
  status: string;
  origin: string;
  context_note: string;
  created_at: string;
  updated_at: string;
  title?: string;
  created_by?: string;
  n_documents?: number;
  n_runs?: number;
};

export type SpanRow = {
  span_id: string;
  quote: string;
  char_start: number;
  char_end: number;
  polarity: string;
  document_revision_id: string;
};

export type MonitorDecisionRow = {
  update_id: string;
  monitor_id: string;
  summary: string;
  decision: string;
  decision_case_id: string;
  created_at: string;
};

export type CaseDetail = {
  case: CaseRow;
  claims: {
    claim_id: string;
    statement: string;
    kind: string;
    status: string;
    created_at: string;
    spans: SpanRow[];
  }[];
  analysis_runs: {
    run_id: string;
    kind: string;
    status: string;
    engine: string;
    error: string;
    started_at: string;
    finished_at: string;
    output_artifact_id: string | null;
    output: unknown;
  }[];
  monitor_decisions: MonitorDecisionRow[];
};

export type ExtractionRow = {
  extraction_id: string;
  document_revision_id: string;
  element_key: string;
  normalized_value: string;
  span_ids: string[];
  confidence: number;
  uncertainty_reason: string;
  human_status: string;
  spans?: { span_id: string; char_start: number; char_end: number; quote: string }[];
};

export type DocumentBody = {
  document_revision_id: string;
  document_id: string;
  source_id: string;
  body: string;
  language: string;
};

export type CaseArticleRow = {
  item_key: string;
  title: string;
  url: string;
  published_at: string;
  body: string;
};

export type ArticleDetail = {
  item_key: string;
  source_id: string;
  title: string;
  url: string;
  published_at: string;
  body: string;
  language: string;
};

export type ArchiveRow = {
  artifact_id: string;
  case_id: string;
  klass: string;
  title: string;
  report_type: string | null;
  current_revision_id: string;
  revision_created_at: string;
  commit_id?: string;
  commit_note?: string | null;
  committed_at?: string | null;
};

/** 报告输入清单（run output.inputs / revision content.inputs）：核对报告输入与页面状态一致 */
export type ReportInputs = {
  n_documents: number;
  n_extractions: number;
  n_claims: number;
  n_challenge_runs: number;
  n_compare_runs: number;
  truncated: boolean;
};

export type WorkflowOut = {
  run_id: string;
  status: string;
  engine?: string;
  artifact_id?: string;
  revision_id?: string;
  comparison_id?: string;
  translation_revision_id?: string;
  duplicate?: boolean;
  extraction_ids?: string[];
  questions?: string[];
  counter_evidence?: { span_id: string; quote: string }[];
  conflicts?: Record<string, Record<string, string>>;
  agreement?: string[];
  missing?: string[];
  blocked?: boolean;
  eligibility?: { probability?: string; comparison_mode?: string; avg_overlap?: number };
  gaps?: string[];
  summary?: string;
  n_sections?: number;
  n_elements?: number;
  skipped?: { artifact_id: string; reason: string }[];
  inputs?: ReportInputs;
};

export type LaunchOut = {
  run_id: string;
  status: string;
  reused: boolean;
  poll: string;
};

export type RunOut = {
  run_id: string;
  kind: string;
  case_id: string;
  status: string;
  error: string | null;
  input_refs: string[];
  output_artifact_id: string | null;
  output: unknown;
  token_in?: number;
  token_out?: number;
  model?: string | null;
  started_at?: string;
  finished_at?: string | null;
};

export type WorkflowRun = RunOut & { output: WorkflowOut | null };

const TERMINAL = new Set(["succeeded", "abstained", "failed", "cancelled"]);

async function pollRun(runId: string, timeoutMs = 320_000, intervalMs = 1500): Promise<WorkflowRun> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const run = await get<RunOut>(`/analysis-runs/${encodeURIComponent(runId)}`);
    if (TERMINAL.has(run.status)) {
      setActiveRun("");
      return run as WorkflowRun;
    }
    if (Date.now() > deadline) {
      setActiveRun("");
      throw new Error(`run ${runId} poll timeout`);
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

async function launch(body: Promise<LaunchOut>): Promise<WorkflowRun> {
  const { run_id } = await body;
  setActiveRun(run_id);
  return pollRun(run_id);
}

export const objectApi = {
  cases: (status?: string, includeClosed?: boolean) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (includeClosed) params.set("include_closed", "1");
    const qs = params.toString();
    return get<CaseRow[]>(`/cases${qs ? `?${qs}` : ""}`);
  },
  caseDetail: (id: string) => get<CaseDetail>(`/cases/${encodeURIComponent(id)}`),
  createCase: (body: {
    case_id: string;
    question: string;
    origin?: string;
    created_at: string;
    updated_at: string;
    title?: string;
    created_by?: string;
  }) => post<CaseRow>("/cases", body),
  closeCase: (id: string) => post<unknown>(`/cases/${encodeURIComponent(id)}/close`, {}),
  reviewExtraction: (extractionId: string, humanStatus: "confirmed" | "rejected") =>
    post<unknown>(`/extractions/${encodeURIComponent(extractionId)}/review`, {
      human_status: humanStatus,
    }),
  documentBody: (revisionId: string) =>
    get<DocumentBody>(`/documents/${encodeURIComponent(revisionId)}/body`),
  caseArticles: (sourceId: string, limit = 20) =>
    get<{ n: number; articles: CaseArticleRow[] }>(
      `/sources/${encodeURIComponent(sourceId)}/articles?limit=${limit}`,
    ),
  articleDetail: (sourceId: string, itemKey: string) =>
    get<ArticleDetail>(
      `/articles/detail?source_id=${encodeURIComponent(sourceId)}&item_key=${encodeURIComponent(itemKey)}`,
    ),
  attachDocument: (
    caseId: string,
    body: {
      document_id: string;
      document_revision_id: string;
      source_id: string;
      body: string;
      language?: string;
      canonical_url?: string;
      external_key?: string;
    },
  ) => post<{ document_revision_id: string }>(`/cases/${encodeURIComponent(caseId)}/documents`, body),
  inboxRows: (params: {
    sourceIds?: string[];
    q?: string;
    language?: string;
    days?: number;
    element?: string;
    value?: string;
    limit?: number;
  }) => {
    const p = new URLSearchParams();
    for (const s of params.sourceIds ?? []) p.append("source_id", s);
    if (params.q) p.set("q", params.q);
    if (params.language) p.set("language", params.language);
    if (params.days) p.set("days", String(params.days));
    if (params.element) p.set("element", params.element);
    if (params.value) p.set("value", params.value);
    if (params.limit) p.set("limit", String(params.limit));
    return get<{ n: number; rows: ArticleDetail[] & { cased?: boolean; dissected?: boolean }[] }>(
      `/inbox?${p.toString()}`,
    );
  },
  getRun: (runId: string) =>
    get<RunOut>(`/analysis-runs/${encodeURIComponent(runId)}`),
  cancelRun: (runId: string) =>
    post<{ run_id: string; status: string }>(
      `/analysis-runs/${encodeURIComponent(runId)}/cancel`,
      {},
    ),
  monitorRuns: (monitorId: string) =>
    get<MonitorRunRow[]>(`/monitors/${encodeURIComponent(monitorId)}/runs`),
  confirmSnapshot: (monitorId: string, body: { snapshot_at: string }) =>
    post<{ monitor_id: string; confirmed_at: string }>(
      `/monitors/${encodeURIComponent(monitorId)}/confirm-snapshot`,
      body,
    ),
  patchMonitor: (
    monitorId: string,
    body: { question?: string; trigger_conditions?: string[]; window?: string; schedule?: string; status?: string },
  ) =>
    patch<{ monitor_id: string; updated: string[] }>(
      `/monitors/${encodeURIComponent(monitorId)}`,
      body,
    ),
  deleteMonitor: (monitorId: string) =>
    patchOrDelete<{ monitor_id: string; deleted: boolean }>(`/monitors/${encodeURIComponent(monitorId)}`, "DELETE"),
  refreshSource: (sourceId: string) =>
    post<unknown>(`/sources/${encodeURIComponent(sourceId)}/refresh`, {}),
  extractions: (revisionId: string) =>
    get<ExtractionRow[]>(`/documents/${encodeURIComponent(revisionId)}/extractions`),
  dissect: (caseId: string, document_revision_id: string) =>
    launch(post<LaunchOut>(`/cases/${encodeURIComponent(caseId)}/dissect`, { document_revision_id })),
  translate: (caseId: string, document_revision_id: string, target_language = "en") =>
    launch(
      post<LaunchOut>(`/cases/${encodeURIComponent(caseId)}/translate`, {
        document_revision_id,
        target_language,
      }),
    ),
  compare: (caseId: string, document_revision_ids: string[]) =>
    launch(
      post<LaunchOut>(`/cases/${encodeURIComponent(caseId)}/compare`, { document_revision_ids }),
    ),
  report: (caseId: string, body: { report_type: string; title: string; text?: string }) =>
    launch(post<LaunchOut>(`/cases/${encodeURIComponent(caseId)}/report`, body)),
  challenge: (caseId: string, claim_id: string) =>
    launch(post<LaunchOut>(`/cases/${encodeURIComponent(caseId)}/challenge`, { claim_id })),
  createClaim: (caseId: string, body: { statement: string; kind: string; span_ids?: string[] }) =>
    post<unknown>(`/cases/${encodeURIComponent(caseId)}/claims`, body),
  archive: (klass?: string) =>
    get<ArchiveRow[]>(`/artifacts${klass ? `?klass=${encodeURIComponent(klass)}` : ""}`),
  artifactRevisions: (artifactId: string) =>
    get<RevisionRow[]>(`/artifacts/${encodeURIComponent(artifactId)}/revisions`),
  commitRevision: (
    artifactId: string,
    body: { revision_id: string; commit_id: string; user_note?: string },
  ) =>
    post<{ artifact_id: string; superseded_revision_id: string }>(
      `/artifacts/${encodeURIComponent(artifactId)}/commit`,
      body,
    ),
  composePressEdition: (body: { artifact_ids: string[]; title: string; note?: string }) =>
    post<WorkflowOut>("/press-editions", body),
  monitors: () => get<MonitorRow[]>("/monitors"),
  monitorUpdates: (monitorId: string) =>
    get<MonitorUpdateRow[]>(`/monitors/${encodeURIComponent(monitorId)}/updates`),
  reviewUpdate: (updateId: string, body: { decision: string; case_id?: string }) =>
    post<{ update_id: string; reviewed: boolean; decision: string; case_id: string }>(
      `/monitors/updates/${encodeURIComponent(updateId)}/review`,
      body,
    ),
};

export type RevisionRow = {
  revision_id: string;
  artifact_id: string;
  status: string;
  legacy: boolean;
  created_at: string;
  content?: Record<string, unknown>;
};

export type MonitorRunRow = {
  run_id: string;
  monitor_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  error: string | null;
};

export type MonitorRow = {
  monitor_id: string;
  target_type: string;
  target_ref: string;
  question: string;
  trigger_conditions: string[];
  window: string;
  schedule: string;
  status: string;
  notification: string;
  last_confirmed_snapshot_at: string | null;
  case_id: string | null;
  created_by: string;
  created_at: string;
};

export type MonitorUpdateRow = {
  update_id: string;
  monitor_id: string;
  run_id: string;
  summary: string;
  delta: Record<string, unknown>;
  evidence_refs: string[];
  suggested_case_action: string;
  reviewed: boolean;
  created_at: string;
};
