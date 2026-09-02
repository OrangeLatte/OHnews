/** OH!News API 客户端（浏览器侧 fetch，经 next rewrites 代理到 oh-api） */

/**
 * 阶段 1-c 类型真源：产品契约类型从 FastAPI OpenAPI 生成（npm run generate:api），
 * Pydantic 是唯一契约真源；本文件手写类型仅限旧端点，新增端点一律走 schema。
 */
import type { components } from "@/lib/api-schema";

export type BriefingResponse = components["schemas"]["BriefingResponse"];
export type DataFreshness = components["schemas"]["DataFreshness"];
export type ChangeBrief = components["schemas"]["ChangeBrief"];
export type ChangeDossier = components["schemas"]["ChangeDossier"];
export type EvidenceCitation = components["schemas"]["EvidenceCitation"];
export type EvidenceGap = components["schemas"]["EvidenceGap"];
export type EvidenceSet = components["schemas"]["EvidenceSet"];
export type CoverageSummary = components["schemas"]["CoverageSummary"];
export type ChangeLandscape = components["schemas"]["ChangeLandscape"];
export type SubjectRef = components["schemas"]["SubjectRef"];
// 阶段 2 判断闭环
export type BeliefSnapshot = components["schemas"]["BeliefSnapshot"];
export type BeliefCreate = components["schemas"]["BeliefCreate"];
export type EvidenceBucket = "supporting" | "contradicting" | "context";

export type EventRow = {
  event_id: string;
  title: string;
  entities: string[];
  as_of: string;
  ndi: number | null;
  ndi_status: string;
  n_sources: number;
};

export type NdiPoint = {
  ts: string;
  ndi: number | null;
  ci_low: number | null;
  ci_high: number | null;
  n_sources: number;
  status: string;
  language: string;
};

/** GET /api/events/{id} 单事件详情（R0：详情页不再拉全量列表） */
export type AssessmentRow = {
  event_id: string;
  status: "confirmed" | "contested" | "developing" | "unverified";
  confidence: number;
  evidence_strength: "strong" | "moderate" | "limited" | "insufficient";
  n_independent_sources: number;
  n_primary_sources: number;
  observation: string;
  interpretation: string | null;
  alternative_explanation: string | null;
  what_to_watch_next: string | null;
  engine: string;
};

export type EventDetailRow = {
  event_id: string;
  title: string;
  summary: string;
  entities: string[];
  as_of: string;
  first_seen: string | null;
  ndi: number | null;
  ndi_status: string;
  n_sources: number;
  assessment: AssessmentRow | null;
};

export type EvidenceRow = {
  source_id: string;
  entity_id: string;
  frame: string;
  stance: string;
  confidence: number;
  engine: string;
  ts: string;
  item_key: string;
  quote: string;
};

export type SpectrumSpan = {
  start: number;
  end: number;
  // entity span
  entity_id?: string;
  text?: string;
  // action span
  domain?: string;
  direction?: string;
};

export type SpectrumSentence = {
  i: number;
  text: string;
  frame: string | null;
  stance: string | null;
  hits: Record<string, number>;
  keywords: string[];
  spans?: SpectrumSpan[];
};

export type SpectrumDoc = {
  item_key: string;
  source_id: string;
  title: string;
  published_at: string;
  sentences: SpectrumSentence[];
};

export type TimelinePoint = {
  date: string;
  articles: number;
  n_events: number;
  event_ids: string[];
  ndi: number | null;
  official_rows: number;
  market_rows: number;
};

export type TimelineEventCard = {
  event_id: string;
  title: string;
  as_of: string;
  ndi: number | null;
  dominant_frame?: string | null;
};

export type TimelineResponse = {
  entity_id: string;
  days: number;
  language: string;
  points: TimelinePoint[];
  events: TimelineEventCard[];
};

export type AnatomyData = {
  event_id: string;
  ndi: { ndi: number | null; ts: string; n_sources: number } | null;
  clusters: Record<string, Record<string, number>>;
  cluster_pairs: {
    a: string;
    b: string;
    jsd: number;
    n_a: number;
    n_b: number;
    official_vs_market: boolean;
  }[];
  entity_opposition: {
    entity_id: string;
    official: Record<string, number>;
    market: Record<string, number>;
    n_official: number;
    n_market: number;
    gap: number;
  }[];
};

export type DecisionRow = {
  decision_id: string;
  event_id: string | null;
  ndi_at_decision: number | null;
  decision: string;
  created_at: string;
  outcome: string | null;
};

export type EvidenceByKeyRow = {
  item_key: string;
  source_id: string;
  title: string;
  url: string;
  published_at: string;
  quote: string;
};

export type SignalRow = {
  signal_id: string;
  kind: string;
  entity_id: string;
  title: string;
  what_changed: string;
  why_it_matters: string | null;
  metrics: Record<string, number>;
  strength: number;
  confidence: number;
  evidence_ids: string[];
  // evidence_ids 的语义：item_key=原始文章反查（POST /evidence/by_keys）；
  // event_id=事件证据链（GET /events/{id}/evidence）。narrative_shift 为 item_key。
  evidence_kind: "item_key" | "event_id";
  detected_at: string;
  as_of: string;
};

export type TodayBriefing = {
  date: string;
  total: number;
  signals: SignalRow[];
};

export type AgentArtifact = {
  kind: string;
  target_id: string;
  intent: string;
  observation: string;
  interpretation: string;
  evidence: string[];
  alternative: string | null;
  uncertainty: string | null;
  engine: string;
  created_at: string;
};

export type AgentPacket = {
  intent: string;
  target_kind: string;
  target_id: string;
  entity_id: string | null;
  signal: Record<string, unknown> | null;
  event: Record<string, unknown> | null;
  ndi_points: { ts: string; ndi: number | null; status: string }[];
  stances: { source_id: string; entity_id: string; frame: string; stance: string; confidence: number }[];
  evidence_ids: string[];
  notes: string | null;
};

export type AgentInvokeResponse = {
  offline: boolean;
  packet: AgentPacket;
  artifact?: AgentArtifact;
  reply?: string;
  citations?: string[];
  tools_used?: string[];
  rounds?: number;
};

export type WatchRow = {
  watch_id: string;
  type: string;
  query: string;
  created_at: string;
  last_checked_at: string | null;
  last_summary: Record<string, unknown> | null;
};

export type LibraryItem = {
  item_id: string;
  item_type: string;
  title: string;
  ref_kind: string | null;
  ref_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export type StatusInfo = {
  events: number;
  stances: number;
  ndi_points: number;
  ndi_ok: number;
  ndi_abstain: number;
  bronze_records: number;
};

export type LogFile = { file: string; mtime: string; size: number };

export type IntelReport = {
  report_id: string;
  created_at: string;
  scope: string;
  engine: string;
  summary: string;
  scout_findings: {
    kind: string;
    target: string;
    score: number;
    detail: string;
  }[];
  network: {
    nodes: { id: string; strength: number; degree: number; top_neighbors: string[] }[];
    edges: { source: string; target: string; weight: number; latest_event_at: string }[];
  };
  ach: {
    evidence: string[];
    hypotheses: {
      hypothesis: string;
      note: string | null;
      cells: { evidence: string; score: number | null }[];
    }[];
    conclusion_index: number;
  } | null;
  key_judgments: {
    judgment: string;
    probability: number;
    term: string;
    drivers: string[];
  }[];
};

export type AlertRule = {
  rule_id: string;
  entity_id: string;
  percentile: number;
  window_days: number;
  created_at: string;
};

export type AlertHit = {
  rule_id: string;
  entity_id: string;
  event_id: string;
  event_title: string;
  ndi: number;
  baseline: number;
  triggered_at: string;
};

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

async function del<T>(path: string): Promise<T> {
  const r = await fetch(`/api${path}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

export const api = {
  status: () => get<StatusInfo>("/status"),
  events: (days = 7) => get<EventRow[]>(`/events?days=${days}`),
  eventNdi: (id: string) => get<NdiPoint[]>(`/events/${encodeURIComponent(id)}/ndi`),
  eventDetail: (id: string) => get<EventDetailRow>(`/events/${encodeURIComponent(id)}`),
  eventEvidence: (id: string) =>
    get<EvidenceRow[]>(`/events/${encodeURIComponent(id)}/evidence`),
  evidenceByKeys: (itemKeys: string[]) =>
    post<EvidenceByKeyRow[]>("/evidence/by_keys", { item_keys: itemKeys }),
  today: (top = 10) => get<TodayBriefing>(`/today?top=${top}`),
  agentInvoke: (body: {
    intent: string;
    target_kind: string;
    target_id: string;
    message?: string;
  }) => post<AgentInvokeResponse>("/agent/invoke", body),
  watches: () => get<{ watches: WatchRow[] }>("/watches"),
  watchAdd: (type: string, query: string) =>
    post<WatchRow>("/watches", { type, query }),
  watchRemove: (id: string) => del<{ removed: string }>(`/watches/${id}`),
  library: (itemType?: string) =>
    get<{ items: LibraryItem[] }>(
      `/library${itemType ? `?item_type=${encodeURIComponent(itemType)}` : ""}`,
    ),
  libraryAdd: (body: {
    item_type: string;
    title: string;
    payload: Record<string, unknown>;
    ref_kind?: string;
    ref_id?: string;
  }) => post<LibraryItem>("/library", body),
  libraryRemove: (id: string) => del<{ removed: string }>(`/library/${id}`),
  watchRefresh: (id: string, minPerSource = 10) =>
    post<WatchRow>(`/watches/${id}/refresh?min_per_source=${minPerSource}`, {}),
  watchUpdate: (id: string) =>
    get<components["schemas"]["WatchUpdate"]>(`/watches/${encodeURIComponent(id)}/update`),
  watchReview: (id: string) =>
    post<components["schemas"]["WatchReview"]>(`/watches/${encodeURIComponent(id)}/review`, {}),
  home: (days = 7, top = 5) =>
    get<components["schemas"]["HomePayload"]>(`/home?days=${days}&top=${top}`),
  agentSessionCreate: (kind: string, title: string) =>
    post<{ thread_id: string; kind: string }>("/agent/sessions", { kind, title }),
  agentSessionInput: (threadId: string, text: string, kind = "info") =>
    post<{ queued: boolean }>(`/agent/sessions/${encodeURIComponent(threadId)}/inputs`, {
      kind,
      text,
    }),
  changeField: (days = 30) =>
    get<components["schemas"]["ChangeFieldPayload"]>(`/change-field?days=${days}`),
  changeLandscape: (days = 7, top = 5) =>
    get<components["schemas"]["ChangeLandscape"]>(`/change-landscape?days=${days}&top=${top}`),
  eventSpectrum: (id: string) =>
    get<SpectrumDoc[]>(`/events/${encodeURIComponent(id)}/spectrum`),
  eventAnatomy: (id: string) =>
    get<AnatomyData>(`/events/${encodeURIComponent(id)}/anatomy`),
  entitiesList: () =>
    get<{
      entities: { entity_id: string; aliases: string[]; parent_id: string | null }[];
    }>("/entities"),
  flowSummary: (days = 30) => get<Record<string, unknown>>(`/flow/summary?days=${days}`),
  entityTimeline: (entityId: string, days = 30, language = "any") =>
    get<TimelineResponse>(
      `/timeline/${encodeURIComponent(entityId)}?days=${days}&language=${language}`,
    ),
  intelRun: () =>
    post<IntelReport>("/intel/run", {}),
  intelLatest: () => get<IntelReport>("/intel/latest"),
  intelReports: (n = 10) =>
    get<{ report_id: string; created_at: string; scope: string; engine: string; summary: string }[]>(
      `/intel/reports?n=${n}`,
    ),
  brief: (watchlist: string, top = 5) =>
    get<{ text: string; items: number }>(
      `/brief?watchlist=${encodeURIComponent(watchlist)}&top=${top}`
    ),
  research: (question: string) =>
    post<{ answer: string; confidence: number; citations: string[]; tool_calls: string[] }>(
      "/research",
      { question }
    ),
  chat: (message: string, threadId?: string) =>
    post<{
      thread_id: string;
      reply: string;
      citations: string[];
      tools_used: string[];
      rounds: number;
      offline: boolean;
    }>("/chat", { message, thread_id: threadId }),
  chatThreads: () =>
    get<{ thread_id: string; n: number; last: string }[]>("/chat/threads"),
  chatMessages: (threadId: string) =>
    get<{ role: string; content: string; ts: string }[]>(
      `/chat/${encodeURIComponent(threadId)}/messages`
    ),
  decisions: (entityId: string) =>
    get<DecisionRow[]>(`/decisions?entity_id=${encodeURIComponent(entityId)}`),
  addDecision: (entityId: string, decision: string, eventId?: string) =>
    post<{ decision_id: string }>("/decisions", {
      entity_id: entityId,
      decision,
      event_id: eventId || null,
    }),
  resolveDecision: (id: string, outcome: string) =>
    post<{ decision_id: string; resolved: string }>(
      `/decisions/${encodeURIComponent(id)}/resolve`,
      { outcome }
    ),
  devLogs: () => get<{ logs_dir: string; files: LogFile[] }>("/dev/logs"),
  devLogPreview: (name: string) =>
    get<{ file: string; lines: string[] }>(
      `/dev/logs/${encodeURIComponent(name)}`
    ),
  alertRules: () => get<AlertRule[]>("/alerts/rules"),
  addAlertRule: (entityId: string, percentile: number, windowDays = 90) =>
    post<{ rule_id: string }>("/alerts/rules", {
      entity_id: entityId,
      percentile,
      window_days: windowDays,
    }),
  deleteAlertRule: (ruleId: string) =>
    fetch(`/api/alerts/rules/${encodeURIComponent(ruleId)}`, {
      method: "DELETE",
    }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json() as Promise<{ deleted: string }>;
    }),
  alertHits: (limit = 50) => get<AlertHit[]>(`/alerts/hits?limit=${limit}`),
  alertCheck: () =>
    post<{ triggered: number; hits: AlertHit[] }>("/alerts/check", {}),
  // —— 阶段 1 黄金路径（类型真源 = OpenAPI 生成） ——
  briefing: (days = 3, top = 5) =>
    get<BriefingResponse>(`/briefing?days=${days}&top=${top}`),
  changeDossier: (changeId: string) =>
    get<ChangeDossier>(`/changes/${encodeURIComponent(changeId)}`),
  changeEvidence: (changeId: string, bucket: EvidenceBucket) =>
    get<EvidenceCitation[]>(
      `/changes/${encodeURIComponent(changeId)}/evidence?bucket=${bucket}`
    ),
  // —— 阶段 2 判断闭环（类型真源 = OpenAPI 生成） ——
  saveBelief: (body: BeliefCreate) => post<BeliefSnapshot>("/beliefs", body),
  beliefsForChange: (changeId: string) =>
    get<BeliefSnapshot[]>(`/beliefs?change_id=${encodeURIComponent(changeId)}`),
  beliefsTimeline: (subjectId: string) =>
    get<BeliefSnapshot[]>(
      `/beliefs/timeline?subject_id=${encodeURIComponent(subjectId)}`
    ),
};
