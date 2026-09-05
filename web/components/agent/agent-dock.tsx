"use client";

/**
 * AgentDock（A4 → 阶段2 Agent OS）：五标签 Chat / Plan / Runs / Artifacts / System，
 * 左/右/下停靠 + 折叠 + 全屏 Control Center（expanded，规格 4.3 四形态）。
 * Chat 标签 = 核心对话 Agent：会话管理（/api/agent/threads）+ 指挥发送（/api/chat，
 * 自动携带 Case 上下文）+ 执行反馈卡片流（chat-cards.tsx）+ HITL 内联审批。
 * 旧 DockCard 卡片协议仍用于父层注入的运行事件；消息九类型协议（规格 4.4）
 * message_type 缺省按 answer 渲染。
 */

import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { AgentPanel } from "@/components/agent/agent-panel";
import { AgentPlan } from "@/components/agent/agent-plan";
import { AgentRuns } from "@/components/agent/agent-runs";
import { AgentArtifacts } from "@/components/agent/agent-artifacts";
import { DockCard, type AgentCard } from "@/components/agent/dock-cards";
import {
  CardList,
  nowIso,
  relTime,
  type CardData,
} from "@/components/agent/chat-cards";
import { useT } from "@/lib/i18n/use-t";
import {
  clearErrors,
  setActiveRun,
  useResearchState,
} from "@/lib/research-state";

export type DockPosition = "left" | "right" | "bottom";

/** 消息九类型（规格 4.4）；后端未带 message_type 字段时按 answer 处理。 */
export type MessageType =
  | "answer"
  | "plan"
  | "tool_call"
  | "progress"
  | "artifact"
  | "challenge"
  | "hitl_request"
  | "abstention"
  | "error";

export type ChatMessage = { text: string; message_type?: MessageType };

const NINE_TYPES: readonly string[] = [
  "answer",
  "plan",
  "tool_call",
  "progress",
  "artifact",
  "challenge",
  "hitl_request",
  "abstention",
  "error",
];

/** Chat 会话条目：本地发送 + 服务端历史（GET /api/chat/{id}/messages）统一形状。 */
export type ChatEntry = {
  role: "user" | "assistant";
  text: string;
  message_type?: MessageType;
  cards?: CardData[];
};

type ThreadRow = {
  thread_id: string;
  title?: string;
  case_id?: string | null;
  created_at?: string;
};

type ChatReply = {
  thread_id?: string;
  reply?: unknown;
  offline?: boolean;
  cards?: unknown[];
};

const TYPE_CLS: Record<MessageType, string> = {
  answer: "bg-muted text-muted-foreground",
  plan: "bg-muted text-muted-foreground",
  tool_call: "bg-muted text-muted-foreground",
  progress: "bg-muted text-muted-foreground",
  hitl_request: "bg-muted text-muted-foreground",
  artifact: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  challenge: "bg-purple-500/15 text-purple-700 dark:text-purple-300",
  abstention: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  error: "bg-red-500/15 text-red-700 dark:text-red-300",
};

const TABS = ["chat", "plan", "runs", "artifacts", "system"] as const;
type DockTab = (typeof TABS)[number];

/** 位置切换三选（dock header ⬅⬇➡）：写 localStorage "ag-position"，下次加载读取。 */
const POSITION_CHOICES: readonly DockPosition[] = ["left", "bottom", "right"];
const POSITION_GLYPH: Record<DockPosition, string> = { left: "⬅", bottom: "⬇", right: "➡" };

/** 组件作用域禁 Date.now/random：id 与时间戳生成收敛在模块级函数。 */
function newThreadId(): string {
  return `th-${Math.random().toString(36).slice(2, 10)}`;
}

function asMessageType(v: unknown): MessageType | undefined {
  return typeof v === "string" && NINE_TYPES.includes(v) ? (v as MessageType) : undefined;
}

function textOf(v: unknown): string {
  if (typeof v === "string") return v;
  if (v === null || v === undefined) return "";
  return String(v);
}

/** 历史消息（{role, content, ts, message_type}）→ ChatEntry；非数组诚实返回空。 */
function mapHistory(rows: unknown): ChatEntry[] {
  if (!Array.isArray(rows)) return [];
  return rows.map((raw) => {
    const r = (raw ?? {}) as Record<string, unknown>;
    return {
      role: r.role === "user" ? ("user" as const) : ("assistant" as const),
      text: textOf(r.content),
      message_type: asMessageType(r.message_type),
    };
  });
}

/** 响应 cards 中首个 progress.run_id（联动 Runs 标签 setActiveRun）。 */
function findProgressRunId(cards?: CardData[]): string {
  for (const c of cards ?? []) {
    if (c && c.type === "progress" && typeof c.run_id === "string" && c.run_id) return c.run_id;
  }
  return "";
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
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

function EntryCard({ entry, youLabel, agentLabel, onConfirm }: { entry: ChatEntry; youLabel: string; agentLabel: string; onConfirm?: (msg: string) => void }) {
  const mt: MessageType = entry.message_type ?? "answer";
  return (
    <div className={`ag-card ${entry.role === "user" ? "ag-echo" : ""}`}>
      <p className="mb-1 flex items-center gap-1.5">
        <span className={`rounded px-1 py-0.5 text-[10px] font-medium ${TYPE_CLS[mt]}`}>{mt}</span>
        <span className="text-[10px] text-muted-foreground">
          {entry.role === "user" ? youLabel : agentLabel}
        </span>
      </p>
      {entry.text ? <p className="whitespace-pre-wrap break-words">{entry.text}</p> : null}
      <CardList cards={entry.cards} onConfirm={onConfirm} />
    </div>
  );
}

/** System 标签 = ResearchState 错误条 + AgentPanel 六区（模型状态/用量/HITL/runs/工具/Threads）。 */
function SystemTab() {
  const t = useT();
  const { errors } = useResearchState();
  return (
    <div className="space-y-2">
      {errors.length > 0 ? (
        <div className="rounded border border-red-500/40 bg-red-500/5 p-2" role="alert">
          <p className="font-medium text-red-700 dark:text-red-300">
            {t("agentErrors.title")} ({errors.length})
          </p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {errors.map((e, i) => (
              <li key={`${i}-${e.slice(0, 16)}`} className="break-all">
                {e}
              </li>
            ))}
          </ul>
          <button type="button" onClick={clearErrors} className="mt-1 rounded border px-1.5 py-0.5">
            {t("agentErrors.clear")}
          </button>
        </div>
      ) : null}
      <AgentPanel />
    </div>
  );
}

/**
 * Chat 标签（核心对话 Agent）：
 * - 会话条：GET /api/agent/threads 列表 + 新建会话（POST 全量 AgentThread 契约体）
 * - 切换会话：GET /api/chat/{id}/messages 拉历史（真实端点）；无历史诚实空态
 * - 发送：POST /api/chat {message, thread_id, case_id?} → reply + cards 卡片流
 * - cards 含 progress.run_id → setActiveRun 联动 Runs 标签
 */
function ChatTab({
  threadId,
  onThreadChange,
  entries,
  setEntries,
  draft,
  setDraft,
  legacyMessages,
  legacyCards,
}: {
  threadId: string;
  onThreadChange: (id: string) => void;
  entries: ChatEntry[];
  setEntries: Dispatch<SetStateAction<ChatEntry[]>>;
  draft: string;
  setDraft: (v: string) => void;
  legacyMessages: ChatMessage[];
  legacyCards: AgentCard[];
}) {
  const t = useT();
  const { caseId } = useResearchState();
  const [threads, setThreads] = useState<ThreadRow[]>([]);
  const [threadsErr, setThreadsErr] = useState("");
  const [sending, setSending] = useState(false);
  const [tick, setTick] = useState(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/agent/threads?limit=20", { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`agent/threads: HTTP ${r.status}`);
        return r.json();
      })
      .then((list: unknown) => {
        if (alive) setThreads(Array.isArray(list) ? (list as ThreadRow[]) : []);
      })
      .catch((e: unknown) => {
        if (alive) setThreadsErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [tick]);

  useEffect(() => {
    if (!threadId) return;
    let alive = true;
    fetch(`/api/chat/${encodeURIComponent(threadId)}/messages`, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((rows: unknown) => {
        if (alive) setEntries(mapHistory(rows));
      })
      .catch(() => {
        if (alive) setEntries([]);
      });
    return () => {
      alive = false;
    };
  }, [threadId, setEntries]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "nearest" });
  }, [entries.length, legacyMessages.length, legacyCards.length]);

  /** 新建会话：后端契约 = AgentThread 全量体（thread_id/created_at 必填，非仅 title）。 */
  const createThread = (title: string): Promise<string> => {
    const tid = newThreadId();
    return postJson<{ thread_id: string }>("/api/agent/threads", {
      thread_id: tid,
      title,
      created_at: nowIso(),
      ...(caseId ? { case_id: caseId } : {}),
    }).then(() => {
      setThreads((prev) => [
        { thread_id: tid, title, created_at: nowIso(), case_id: caseId || null },
        ...prev,
      ]);
      return tid;
    });
  };

  const newThread = (): void => {
    if (sending) return;
    createThread(t("chat.newThreadDefault"))
      .then((tid) => {
        onThreadChange(tid);
        setEntries([]);
        setThreadsErr("");
      })
      .catch((e: unknown) => {
        setThreadsErr(e instanceof Error ? e.message : String(e));
      });
  };

  const send = (): void => {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    const ensureThread = threadId
      ? Promise.resolve(threadId)
      : createThread(text.slice(0, 48)).then((tid) => {
          onThreadChange(tid);
          return tid;
        });
    ensureThread
      .then((tid) => {
        setEntries((prev) => [...prev, { role: "user", text }]);
        setDraft("");
        return postJson<ChatReply>("/api/chat", {
          message: text,
          thread_id: tid,
          ...(caseId ? { case_id: caseId } : {}),
        }).then((res) => {
          const cards = Array.isArray(res.cards) ? (res.cards as CardData[]) : undefined;
          setEntries((prev) => [
            ...prev,
            {
              role: "assistant",
              text: textOf(res.reply),
              message_type: res.offline ? "abstention" : "answer",
              cards,
            },
          ]);
          const runId = findProgressRunId(cards);
          if (runId) setActiveRun(runId);
        });
      })
      .catch((e: unknown) => {
        setEntries((prev) => [
          ...prev,
          {
            role: "assistant",
            text: `${t("chat.sendFailed")}: ${e instanceof Error ? e.message : String(e)}`,
            message_type: "error",
          },
        ]);
      })
      .finally(() => setSending(false));
  };

  /** P0-1 确认执行：confirm_action 卡上用户显式确认后回发（服务端 confirmed 通道 bypass 预览门）。 */
  const confirmSend = (msg: string): void => {
    if (sending || !msg) return;
    setSending(true);
    const ensureThread = threadId
      ? Promise.resolve(threadId)
      : createThread(msg.slice(0, 48)).then((tid) => {
          onThreadChange(tid);
          return tid;
        });
    ensureThread
      .then((tid) => {
        setEntries((prev) => [...prev, { role: "user", text: msg }]);
        return postJson<ChatReply>("/api/chat", {
          message: msg,
          thread_id: tid,
          confirmed_action: { message: msg, params: {} },
          ...(caseId ? { case_id: caseId } : {}),
        }).then((res) => {
          const cards = Array.isArray(res.cards) ? (res.cards as CardData[]) : undefined;
          setEntries((prev) => [
            ...prev,
            {
              role: "assistant",
              text: textOf(res.reply),
              message_type: res.offline ? "abstention" : "answer",
              cards,
            },
          ]);
          const runId = findProgressRunId(cards);
          if (runId) setActiveRun(runId);
        });
      })
      .catch((e: unknown) => {
        setEntries((prev) => [
          ...prev,
          {
            role: "assistant",
            text: `${t("chat.sendFailed")}: ${e instanceof Error ? e.message : String(e)}`,
            message_type: "error",
          },
        ]);
      })
      .finally(() => setSending(false));
  };

  return (
    <>
      {/* 会话管理条 */}
      <div className="flex flex-wrap items-center gap-1 pb-1 text-[10px]">
        <span className="text-muted-foreground">{t("chat.threads")}:</span>
        {threads.map((th) => (
          <button
            key={th.thread_id}
            type="button"
            aria-pressed={th.thread_id === threadId}
            title={`${th.title || th.thread_id}${th.created_at ? ` · ${relTime(th.created_at, t)}` : ""}`}
            onClick={() => {
              if (th.thread_id === threadId) {
                onThreadChange("");
                setEntries([]);
              } else {
                onThreadChange(th.thread_id);
              }
            }}
            className={`ag-mini max-w-32 truncate ${th.thread_id === threadId ? "bg-foreground text-background" : ""}`}
          >
            {th.title || th.thread_id}
          </button>
        ))}
        <button type="button" onClick={newThread} className="ag-mini">
          + {t("chat.newThread")}
        </button>
        <button type="button" onClick={() => setTick((n) => n + 1)} className="ag-mini">
          ↻
        </button>
      </div>
      {threadsErr ? <p className="ag-empty break-all text-red-600">{threadsErr}</p> : null}

      <div className="ag-cards">
        {entries.length === 0 && legacyMessages.length === 0 && legacyCards.length === 0 && (
          <p className="ag-empty">
            {threadId ? t("chat.historyNone") : t("agentChat.empty")}
          </p>
        )}
        {legacyMessages.map((m, i) => {
          const mt: MessageType = m.message_type ?? "answer";
          return (
            <div key={`msg-${i}`} className="ag-card">
              <p className="mb-1">
                <span className={`rounded px-1 py-0.5 text-[10px] font-medium ${TYPE_CLS[mt]}`}>
                  {mt}
                </span>
              </p>
              <p className="whitespace-pre-wrap break-words">{m.text}</p>
            </div>
          );
        })}
        {legacyCards.map((c, i) => (
          <DockCard key={`${c.kind}-${i}`} card={c} />
        ))}
        {entries.map((e, i) => (
          <EntryCard
            key={`entry-${i}`}
            entry={e}
            youLabel={t("chat.you")}
            agentLabel={t("chat.agent")}
            onConfirm={confirmSend}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      <form
        className="ag-input"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("agentChat.placeholder")}
          aria-label={t("agentChat.aria")}
          disabled={sending}
        />
        <button type="submit" disabled={!draft.trim() || sending}>
          {sending ? t("chat.sending") : t("agentChat.send")}
        </button>
      </form>
      {caseId ? (
        <p className="pt-1 text-[10px] text-muted-foreground">
          {t("chat.caseContext")}: <span className="font-mono">{caseId}</span>
        </p>
      ) : null}
    </>
  );
}

export function AgentDock({
  title,
  cards = [],
  messages = [],
  position = "right",
}: {
  agentKind: "dissection" | "tracking" | "memory" | "parent";
  title: string;
  cards?: AgentCard[];
  messages?: ChatMessage[];
  position?: DockPosition;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<DockTab>("chat");
  const [draft, setDraft] = useState("");
  const [chatThreadId, setChatThreadId] = useState("");
  const [chatEntries, setChatEntries] = useState<ChatEntry[]>([]);
  const [width, setWidth] = useState(() => {
    if (typeof window === "undefined") return 26;
    const v = Number(window.localStorage.getItem("ag-width"));
    return v >= 18 && v <= 60 ? v : 26;
  });
  // 停靠位置持久化：SSR 首帧用 prop 默认值，挂载后 setTimeout(0) 异步读 localStorage
  // （同步/惰性读取会导致 SSR 与客户端首帧不一致 → hydration mismatch，monitors 页教训）
  const [pos, setPos] = useState<DockPosition>(position);
  useEffect(() => {
    const t = setTimeout(() => {
      const v = window.localStorage.getItem("ag-position");
      if (v === "left" || v === "right" || v === "bottom") setPos(v);
    }, 0);
    return () => clearTimeout(t);
  }, []);

  const switchPosition = useCallback((p: DockPosition) => {
    setPos(p);
    window.localStorage.setItem("ag-position", p);
  }, []);

  const startResize = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = width;
    const side = pos === "left" ? "right" : "left";
    const move = (ev: PointerEvent) => {
      const delta = side === "left" ? startX - ev.clientX : ev.clientX - startX;
      const next = Math.min(60, Math.max(18, startW + delta / 16));
      setWidth(next);
    };
    const up = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      const delta = side === "left" ? startX - ev.clientX : ev.clientX - startX;
      const final = Math.min(60, Math.max(18, startW + delta / 16));
      window.localStorage.setItem("ag-width", String(final));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <aside
      className={`ag-dock ag-${pos} ${expanded ? "ag-expanded" : ""}`}
      data-open={open}
      data-expanded={expanded}
      aria-label={title}
    >
      <button
        type="button"
        className="ag-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? t("agentDock.collapse") : title}
      </button>
      {open && (
        <div
          className="ag-body"
          style={expanded ? undefined : ({ "--ag-w": `${width}rem` } as React.CSSProperties)}
        >
          <div
            className="ag-resize"
            data-side={pos === "left" ? "right" : "left"}
            onPointerDown={startResize}
            aria-hidden
          />
          <p className="ag-head flex items-center justify-between gap-2">
            <span>{title}</span>
            <span className="flex items-center gap-1">
              <span role="group" aria-label={t("agentDock.position")} className="flex items-center gap-0.5">
                {POSITION_CHOICES.map((p) => (
                  <button
                    key={p}
                    type="button"
                    aria-pressed={pos === p}
                    aria-label={`${t("agentDock.position")}: ${p}`}
                    title={`${t("agentDock.position")}: ${p}`}
                    onClick={() => switchPosition(p)}
                    className="ag-mini"
                    style={
                      pos === p
                        ? { background: "var(--foreground)", color: "var(--background)" }
                        : undefined
                    }
                  >
                    {POSITION_GLYPH[p]}
                  </button>
                ))}
              </span>
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                aria-label={expanded ? t("agent.collapse") : t("agent.expand")}
                aria-pressed={expanded}
                title={expanded ? t("agent.collapse") : t("agent.expand")}
                className="ag-mini"
              >
                ⛶
              </button>
            </span>
          </p>
          <div className="ag-tabs flex flex-wrap gap-1 pb-2" role="tablist" aria-label={title}>
            {TABS.map((k) => (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={tab === k}
                onClick={() => setTab(k)}
                className={`rounded border px-2 py-0.5 text-xs ${
                  tab === k ? "bg-foreground text-background" : ""
                }`}
              >
                {t(`agentTab.${k}`)}
              </button>
            ))}
          </div>
          {tab === "system" ? (
            <SystemTab />
          ) : tab === "plan" ? (
            <AgentPlan />
          ) : tab === "runs" ? (
            <AgentRuns />
          ) : tab === "artifacts" ? (
            <AgentArtifacts />
          ) : (
            <ChatTab
              threadId={chatThreadId}
              onThreadChange={setChatThreadId}
              entries={chatEntries}
              setEntries={setChatEntries}
              draft={draft}
              setDraft={setDraft}
              legacyMessages={messages}
              legacyCards={cards}
            />
          )}
        </div>
      )}
    </aside>
  );
}
