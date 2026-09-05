"use client";

/**
 * Landscape API 客户端：OBSERVE / SOURCES 空间只读数据。
 * 复用旧只读端点（change-landscape / ndi / emotion / sources），M9 切流前这些端点保持稳定。
 */

import { objectApi } from "@/lib/object-api";

export type TimeWindow = {
  start: string;
  end: string;
  n_articles: number;
  n_sources: number;
};

/** 变化支持证据（bronze 检索 top≤3；空列表=诚实无命中）。 */
export type EvidenceArticle = {
  item_key: string;
  source_id: string;
  title: string;
  url: string;
  published_at: string | null;
  language?: string;
};

export type QualifiedChange = {
  change_id: string;
  kind: string;
  headline: string;
  what: string;
  why_now: string;
  strength_word: string;
  urgency: string;
  subjects: string[];
  at: string | null;
  /** 旧载荷缺省 → undefined（诚实降级为既有"暂无"文案）。 */
  evidence_articles?: EvidenceArticle[];
};

export type QualityWarning = {
  code: string;
  message: string;
};

export type SourceStream = {
  source_id: string;
  label: string;
  tier: string;
  cluster: string;
  n_baseline: number;
  n_current: number;
  /** 增长百分点（后端口径：n_baseline<5 → null）；旧载荷缺省 → undefined。 */
  growth?: number | null;
  /** 后端低样本标记（仅 baseline<5）；旧载荷缺省 → undefined（回退本地口径）。 */
  low_baseline?: boolean;
};

export type NarrativeStream = {
  frame: string;
  label: string;
  share_baseline: number;
  share_current: number;
  n_baseline: number;
  n_current: number;
  /** 后端低样本标记（仅 baseline<5）；旧载荷缺省 → undefined。 */
  low_baseline?: boolean;
};

export type Freshness = {
  as_of: string;
  coverage_start: string | null;
  coverage_end: string | null;
  staleness: string;
  note: string;
};

export type Landscape = {
  scene_id: string;
  generated_at: string;
  baseline_window: TimeWindow;
  current_window: TimeWindow;
  source_streams: SourceStream[];
  narrative_streams: NarrativeStream[];
  qualified_changes: QualifiedChange[];
  quality_warnings: QualityWarning[];
  freshness?: Freshness;
};

export type NdiRankRow = {
  entity: string;
  label?: string;
  ndi: number;
  /** 兼容旧端点；当前实现返回 n_sources。 */
  n?: number;
  n_sources?: number;
};

export type EmotionRow = {
  date: string;
  [emotion: string]: number | string;
};

export type SourceRow = {
  source_id: string;
  kind: string;
  tier: string;
  language: string;
  enabled: boolean;
  n_7d: number;
  n_30d: number;
  last_seen: string | null;
};

export type SourcesQuery = {
  tier?: string;
  language?: string;
  q?: string;
  enabled?: boolean;
};

export async function fetchLandscape(days: number): Promise<Landscape> {
  const r = await fetch(`/api/change-landscape?days=${days}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`change-landscape: HTTP ${r.status}`);
  return r.json();
}

export async function fetchNdiRank(limit = 8): Promise<NdiRankRow[]> {
  const r = await fetch(`/api/ndi/rank?limit=${limit}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`ndi/rank: HTTP ${r.status}`);
  return r.json();
}

export async function fetchEmotion(days: number): Promise<EmotionRow[]> {
  const r = await fetch(`/api/annotations/emotion?days=${days}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`annotations/emotion: HTTP ${r.status}`);
  return r.json();
}

export async function fetchSources(query: SourcesQuery): Promise<{ n: number; sources: SourceRow[] }> {
  const p = new URLSearchParams();
  if (query.tier) p.set("tier", query.tier);
  if (query.language) p.set("language", query.language);
  if (query.q) p.set("q", query.q);
  if (query.enabled !== undefined) p.set("enabled", String(query.enabled));
  const qs = p.toString();
  const r = await fetch(`/api/sources${qs ? `?${qs}` : ""}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`sources: HTTP ${r.status}`);
  return r.json();
}

/** OBSERVE 底部窄条：Monitor 总数 + 未复核更新数（走新对象 API）。 */
export async function fetchMonitorStrip(): Promise<{
  total: number;
  pending: number;
}> {
  const monitors = await objectApi.monitors();
  const total = monitors.length;
  let pending = 0;
  for (const m of monitors) {
    const updates = await objectApi.monitorUpdates(m.monitor_id);
    pending += updates.filter((u) => !u.reviewed).length;
  }
  return { total, pending };
}

// ---------- Sources 运行中心 + 扩展向导 ----------

export interface CollectionPlanRow {
  plan_id: string;
  source_ids: string[];
  mode: "realtime" | "scheduled" | "backfill";
  schedule: string;
  time_range: string;
  enabled: boolean;
  created_by: "user" | "agent";
  created_at: string;
}

export interface CollectionRunRow {
  run_id: string;
  plan_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  items_collected: number;
  last_error: string;
  started_at: string;
  finished_at: string;
}

export interface SourceSuggestion {
  source_id: string;
  adapter: string;
  tier: string;
  language: string;
  params: { url: string };
}

export async function postJson<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = (await r.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

export function suggestSource(url: string): Promise<{
  url: string;
  suggestion: SourceSuggestion;
  rationale: string;
}> {
  return postJson("/api/sources/suggest", { url });
}

export function registerSource(s: SourceSuggestion): Promise<{ ok: boolean; source_id: string }> {
  // POST /api/sources 契约：url 在顶层（不是 params.url）
  return postJson("/api/sources", { ...s, url: s.params.url });
}

export function fetchCollectionPlans(): Promise<CollectionPlanRow[]> {
  return fetch("/api/collection/plans", { cache: "no-store" }).then((r) => {
    if (!r.ok) throw new Error(`collection/plans: HTTP ${r.status}`);
    return r.json() as Promise<CollectionPlanRow[]>;
  });
}

export function fetchCollectionRuns(planId?: string): Promise<CollectionRunRow[]> {
  const qs = planId ? `?plan_id=${encodeURIComponent(planId)}` : "";
  return fetch(`/api/collection/runs${qs}`, { cache: "no-store" }).then((r) => {
    if (!r.ok) throw new Error(`collection/runs: HTTP ${r.status}`);
    return r.json() as Promise<CollectionRunRow[]>;
  });
}

export function createCollectionPlan(body: {
  source_ids: string[];
  mode: CollectionPlanRow["mode"];
  schedule: string;
}): Promise<CollectionPlanRow> {
  return postJson("/api/collection/plans", body);
}

export function enableCollectionPlan(planId: string, enabled: boolean): Promise<unknown> {
  return postJson(`/api/collection/plans/${planId}/enable`, { enabled });
}

// ---------- Entities Lens（实体清单 + 实体级时间轴，复用旧只读端点） ----------

export type EntityRow = {
  entity_id: string;
  aliases: string[];
  parent_id: string | null;
};

export type TimelinePoint = {
  date: string;
  articles: number;
  n_events: number;
  ndi: number | null;
  official_rows: number;
  market_rows: number;
};

export type EntityEventCard = {
  event_id: string;
  title: string;
  as_of: string;
  ndi: number | null;
  dominant_frame: string | null;
};

export type EntityTimeline = {
  entity_id: string;
  days: number;
  language: string;
  points: TimelinePoint[];
  events: EntityEventCard[];
};

export async function fetchEntities(): Promise<EntityRow[]> {
  const r = await fetch("/api/entities", { cache: "no-store" });
  if (!r.ok) throw new Error(`entities: HTTP ${r.status}`);
  const body = (await r.json()) as { entities: EntityRow[] };
  return body.entities;
}

export async function fetchEntityTimeline(
  entityId: string,
  days: number
): Promise<EntityTimeline> {
  const r = await fetch(`/api/timeline/${entityId}?days=${days}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`timeline/${entityId}: HTTP ${r.status}`);
  return r.json();
}
