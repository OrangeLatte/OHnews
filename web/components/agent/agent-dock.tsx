"use client";

/**
 * AgentDock（A4）：通用 agent 侧栏——可折叠 + 位置可调（左/右/下）。
 * 卡片协议见 dock-cards.tsx；会话创建与补充输入走 /api/agent/sessions。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { DockCard, type AgentCard } from "@/components/agent/dock-cards";
import { api } from "@/lib/api";

export type DockPosition = "left" | "right" | "bottom";

type SessionInfo = { thread_id: string; agent_kind: string; title: string };

export function AgentDock({
  agentKind,
  title,
  cards = [],
  position = "right",
}: {
  agentKind: "dissection" | "tracking" | "memory" | "parent";
  title: string;
  cards?: AgentCard[];
  position?: DockPosition;
}) {
  const [open, setOpen] = useState(false);
  const [thread, setThread] = useState<SessionInfo | null>(null);
  const [draft, setDraft] = useState("");
  const [echo, setEcho] = useState<string[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  const ensureSession = useCallback(async (): Promise<SessionInfo | null> => {
    if (thread) return thread;
    try {
      const created = (await api.agentSessionCreate(agentKind, title)) as unknown as SessionInfo;
      setThread(created);
      return created;
    } catch {
      return null;
    }
  }, [agentKind, thread, title]);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text) return;
    const s = await ensureSession();
    if (!s) return;
    try {
      await api.agentSessionInput(s.thread_id, text);
      setEcho((prev) => [...prev, text]);
      setDraft("");
    } catch {
      /* 静默：输入失败不阻塞主路径 */
    }
  }, [draft, ensureSession]);

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ block: "nearest" });
  }, [cards.length, echo.length, open]);

  return (
    <aside className={`ag-dock ag-${position}`} data-open={open} aria-label={title}>
      <button
        type="button"
        className="ag-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? "收起" : title}
      </button>
      {open && (
        <div className="ag-body">
          <p className="ag-head">{title}</p>
          <div className="ag-cards">
            {cards.length === 0 && echo.length === 0 && (
              <p className="ag-empty">代理尚未开始运行——你的补充会在运行时被吸收。</p>
            )}
            {cards.map((c, i) => (
              <DockCard key={`${c.kind}-${i}`} card={c} />
            ))}
            {echo.map((t, i) => (
              <DockCard key={`echo-${i}`} card={{ kind: "user_gate_echo", text: t }} />
            ))}
            <div ref={bottomRef} />
          </div>
          <form
            className="ag-input"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="随时补充信息或调整方向…"
              aria-label="补充信息"
            />
            <button type="submit" disabled={!draft.trim()}>
              发送
            </button>
          </form>
        </div>
      )}
    </aside>
  );
}
