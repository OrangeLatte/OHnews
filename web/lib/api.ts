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

export type DecisionRow = {
  decision_id: string;
  event_id: string | null;
  ndi_at_decision: number | null;
  decision: string;
  created_at: string;
  outcome: string | null;
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

export const api = {
  status: () => get<StatusInfo>("/status"),
  events: (days = 7) => get<EventRow[]>(`/events?days=${days}`),
  eventNdi: (id: string) => get<NdiPoint[]>(`/events/${encodeURIComponent(id)}/ndi`),
  eventEvidence: (id: string) =>
    get<EvidenceRow[]>(`/events/${encodeURIComponent(id)}/evidence`),
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
