/**
 * 产品事件埋点（阶段 1-e）：fire-and-forget，任何失败静默（不阻塞主路径）。
 *
 * 隐私纪律：session 为客户端自生成 UUID（localStorage），不含设备指纹；
 * 不上报 API key、完整私密问题或敏感原文。
 */

const SESSION_KEY = "oh-session";

function getSession(): string {
  if (typeof window === "undefined") return "ssr";
  let sid = window.localStorage.getItem(SESSION_KEY);
  if (!sid) {
    sid = crypto.randomUUID();
    window.localStorage.setItem(SESSION_KEY, sid);
  }
  return sid;
}

export type TrackedEvent =
  | "briefing_viewed"
  | "change_opened"
  | "change_dismissed_as_noise"
  | "evidence_opened"
  | "source_opened"
  | "counter_evidence_requested"
  | "insufficient_evidence_seen"
  // 阶段 2 判断闭环
  | "investigation_started"
  | "judgment_saved"
  | "judgment_change_type";

export function track(
  event: TrackedEvent,
  opts: {
    objectId?: string;
    fromPage?: string;
    freshness?: string;
    meta?: Record<string, unknown>;
  } = {},
): void {
  const payload = {
    event,
    session: getSession(),
    object_id: opts.objectId ?? "",
    from_page: opts.fromPage ?? window.location.pathname,
    freshness: opts.freshness ?? "",
    meta: opts.meta ?? {},
  };
  try {
    void fetch("/api/track", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    // 埋点失败不影响用户主路径（纲领 §11）
  }
}
