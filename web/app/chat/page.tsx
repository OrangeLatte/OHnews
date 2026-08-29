"use client";

import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";

type Msg = { role: string; content: string; ts?: string; tools_used?: string[] };

type ChatResp = {
  thread_id: string;
  reply: string;
  citations: string[];
  tools_used: string[];
  rounds: number;
  offline: boolean;
};

// Research Plan：工具调用→用户可理解的研究动作（✓ 已完成步骤）
const TOOL_STEPS: Record<string, string> = {
  query_events: "检索相关事件",
  search_entities: "匹配追踪实体",
  get_ndi: "调取分歧读数",
  retrieve_evidence: "抽取证据链",
  fetch_online: "在线检索补充",
  draft_brief: "汇编研究摘要",
};

function ResearchPlan({ tools }: { tools: string[] }) {
  const steps = tools.map((t) => TOOL_STEPS[t] ?? t);
  if (steps.length === 0) return null;
  return (
    <div className="mt-2 border-t border-border/50 pt-2">
      <p className="paper-kicker mb-1">Research Plan</p>
      {steps.map((s, i) => (
        <p key={i} className="text-xs leading-5 text-muted-foreground">
          ✓ {s}
        </p>
      ))}
    </div>
  );
}

export function ChatPanel({
  prefill,
  autoSend = false,
}: {
  prefill?: string;
  autoSend?: boolean;
}) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [threadId, setThreadId] = useState<string | undefined>(undefined);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const autoSent = useRef(false);

  // 预填（Ask Analyst / Suggested Tasks）：填入输入框，autoSend 时直接发送
  useEffect(() => {
    if (!prefill) return;
    setInput(prefill);
    if (autoSend && !autoSent.current) {
      autoSent.current = true;
      void submit(prefill);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill, autoSend]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function loadThread(id: string) {
    try {
      const msgs = await api.chatMessages(id);
      setMessages(msgs);
      setThreadId(id);
    } catch (err) {
      setError(String(err));
    }
  }

  async function submit(message: string) {
    if (!message || loading) return;
    setMessages((m) => [...m, { role: "user", content: message }]);
    setLoading(true);
    setError(null);
    try {
      const r: ChatResp = await api.chat(message, threadId);
      setThreadId(r.thread_id);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: r.reply, tools_used: r.tools_used },
      ]);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  function send() {
    const message = input.trim();
    if (!message) return;
    setInput("");
    void submit(message);
  }

  async function showThreads() {
    try {
      const threads = await api.chatThreads();
      if (threads.length > 0) await loadThread(threads[0].thread_id);
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">情报对话（多轮 · 工具调用 · 只读纪律）</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={showThreads}>
            最近会话
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setMessages([]);
              setThreadId(undefined);
            }}
          >
            新会话
          </Button>
        </div>
      </div>

      <Card className="flex min-h-[55vh] flex-col">
        <CardContent className="flex flex-1 flex-col gap-3 overflow-y-auto py-4">
          {messages.length === 0 && (
            <p className="text-sm text-muted-foreground">
              向情报研究员提问：事件 / NDI / 证据链 / 在线检索 / 制作晨报。
              例：「美联储最近的叙事分歧如何？帮我做一份晨报」
            </p>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              className={
                m.role === "user"
                  ? "self-end max-w-[85%] bg-primary/10 px-3 py-2 text-sm whitespace-pre-wrap"
                  : "self-start max-w-[92%] bg-muted px-3 py-2 text-sm whitespace-pre-wrap"
              }
            >
              {m.content}
              {m.role === "assistant" && m.tools_used && m.tools_used.length > 0 && (
                <ResearchPlan tools={m.tools_used} />
              )}
            </div>
          ))}
          {loading && <p className="text-sm text-muted-foreground">研究员思考中…</p>}
          <div ref={bottomRef} />
        </CardContent>
      </Card>

      {error && <p className="text-destructive text-sm">{error}</p>}

      <Textarea
        rows={2}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        placeholder="提问…（Enter 发送，Shift+Enter 换行）"
      />
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {threadId && <Badge variant="outline">thread: {threadId}</Badge>}
        </div>
        <Button onClick={send} disabled={loading || !input.trim()}>
          发送
        </Button>
      </div>
    </div>
  );
}

export default ChatPanel;
