/** OH!News API 客户端（浏览器侧 fetch，经 next rewrites 代理到 oh-api） */

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
  detected_at: string;
  as_of: string;
};

export type TodayBriefing = {
  date: string;
  total: number;
  signals: SignalRow[];
};

export type WatchRow = {
  watch_id: string;
  type: string;
  query: string;
  created_at: string;
  last_checked_at: string | null;
  last_summary: Record<string, unknown> | null;
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
  eventEvidence: (id: string) =>
    get<EvidenceRow[]>(`/events/${encodeURIComponent(id)}/evidence`),
  today: (top = 10) => get<TodayBriefing>(`/today?top=${top}`),
  watches: () => get<{ watches: WatchRow[] }>("/watches"),
  watchAdd: (type: string, query: string) =>
    post<WatchRow>("/watches", { type, query }),
  watchRemove: (id: string) => del<{ removed: string }>(`/watches/${id}`),
  watchRefresh: (id: string, minPerSource = 10) =>
    post<WatchRow>(`/watches/${id}/refresh?min_per_source=${minPerSource}`, {}),
  eventSpectrum: (id: string) =>
    get<SpectrumDoc[]>(`/events/${encodeURIComponent(id)}/spectrum`),
  eventAnatomy: (id: string) =>
    get<AnatomyData>(`/events/${encodeURIComponent(id)}/anatomy`),
  entitiesList: () =>
    get<{
      entities: { entity_id: string; aliases: string[]; parent_id: string | null }[];
    }>("/entities"),
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
    post<{ answer: string; confidence: string; citations: string[]; tool_calls: string[] }>(
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
};
