"use client";

import { Suspense, useEffect, useState } from "react";
import React from "react";

import { ChatPanel } from "@/app/chat/page";
import KeySetup from "@/app/agent/key-setup";
import { IntentPanel } from "@/app/agent/intent-panel";
import type { AgentInvokeResponse } from "@/lib/api";
import { api } from "@/lib/api";

const TASKS: { no: string; title: string; q: string }[] = [
  {
    no: "01",
    title: "Explain an event",
    q: "解读美联储最近的事件：发生了什么变化，为什么值得关注？",
  },
  {
    no: "02",
    title: "Compare narratives",
    q: "比较官方信源与市场媒体对当前事件的叙事差异，用证据支撑。",
  },
  {
    no: "03",
    title: "Investigate divergence",
    q: "为什么官方信源和市场信源对同一事件出现解释分歧？",
  },
  {
    no: "04",
    title: "Track an entity",
    q: "过去 30 天，NVIDIA 周围的叙事是如何演变的？",
  },
  {
    no: "05",
    title: "Historical comparison",
    q: "找出与当前叙事转变类似的历史模式。",
  },
];

const TARGET_KINDS = ["event", "entity", "signal", "topic"] as const;

type Structured = {
  targetKind: string;
  targetId: string;
  result: AgentInvokeResponse | null;
  loading: boolean;
  error: string | null;
};

function StructuredResearch({
  st,
  setSt,
}: {
  st: Structured;
  setSt: (fn: (s: Structured) => Structured) => void;
}) {
  async function run(intent: string) {
    if (!st.targetId.trim()) {
      setSt((s) => ({ ...s, error: "需要 target_id（事件/实体/信号 id）" }));
      return;
    }
    setSt((s) => ({ ...s, loading: true, error: null }));
    try {
      const r = await api.agentInvoke({
        intent,
        target_kind: st.targetKind,
        target_id: st.targetId.trim(),
      });
      setSt((s) => ({ ...s, result: r, loading: false }));
    } catch (err) {
      setSt((s) => ({ ...s, error: String(err), loading: false }));
    }
  }
  const a = st.result?.artifact;
  return (
    <div className="flex flex-col gap-3 rounded border border-border bg-card p-4">
      <p className="paper-kicker">Structured research · 结构化研究</p>
      <div className="flex gap-2">
        <select
          value={st.targetKind}
          onChange={(e) => setSt((s) => ({ ...s, targetKind: e.target.value }))}
          className="border border-border bg-background px-2 py-1 text-xs"
        >
          {TARGET_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <input
          value={st.targetId}
          onChange={(e) => setSt((s) => ({ ...s, targetId: e.target.value }))}
          placeholder="event / entity id"
          className="flex-1 border border-border bg-background px-2 py-1 font-mono text-xs"
        />
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => run("start_investigation")}
          disabled={st.loading}
          className="bg-primary px-3 py-1.5 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
        >
          {st.loading ? "研究中…" : "生成结构化研究"}
        </button>
        <button
          type="button"
          onClick={() => run("challenge")}
          disabled={st.loading}
          className="border border-primary/40 px-3 py-1.5 text-xs text-primary hover:bg-primary/5 disabled:opacity-60"
        >
          对抗验证
        </button>
      </div>
      {st.error && <p className="text-xs text-destructive">{st.error}</p>}
      {a && (
        <div className="flex flex-col gap-2 border-t border-border/60 pt-2 text-sm leading-6">
          <div>
            <p className="paper-kicker">Key judgment</p>
            <p className="font-paper">{a.interpretation}</p>
          </div>
          <div>
            <p className="paper-kicker">Confidence · {a.engine}</p>
            <p className="text-xs text-muted-foreground">
              {a.engine === "llm"
                ? "High（模型增强，schema 后校验）"
                : "Medium（确定性数据，无 LLM）"}
            </p>
          </div>
          <div>
            <p className="paper-kicker">What changed</p>
            <p className="text-xs leading-5">{a.observation}</p>
          </div>
          {a.alternative && (
            <div>
              <p className="paper-kicker">Competing explanations</p>
              {a.alternative.split("；").map((ln, i) => (
                <p key={i} className="text-xs leading-5">
                  {ln}
                </p>
              ))}
            </div>
          )}
          {a.evidence.length > 0 && (
            <div>
              <p className="paper-kicker">Evidence</p>
              <div className="flex flex-wrap gap-1">
                {a.evidence.map((e) => (
                  <span key={e} className="bg-muted px-1.5 py-0.5 font-mono text-[10px]">
                    {e}
                  </span>
                ))}
              </div>
            </div>
          )}
          {a.uncertainty && (
            <div>
              <p className="paper-kicker">Open questions</p>
              <p className="text-xs leading-5 text-muted-foreground">{a.uncertainty}</p>
            </div>
          )}
          <div>
            <p className="paper-kicker">Next investigation</p>
            <div className="flex flex-wrap gap-2 text-xs">
              <a className="text-primary hover:underline" href="/events">
                浏览事件 →
              </a>
              <a className="text-primary hover:underline" href="/library">
                存入档案 →
              </a>
            </div>
          </div>
        </div>
      )}
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">完整意图面板（五类意图 + Artifact 明细）</summary>
        <div className="mt-2">
          <IntentPanel />
        </div>
      </details>
    </div>
  );
}

export default function ResearchPage({
  searchParams,
}: PageProps<"/research">) {
  const sp = React.use(searchParams);
  const q = typeof sp.q === "string" ? sp.q : undefined;
  const event = typeof sp.event === "string" ? sp.event : undefined;
  const [prefill, setPrefill] = useState<string | undefined>(undefined);
  const [autoSend, setAutoSend] = useState(false);
  const [st, setSt] = useState<Structured>({
    targetKind: "event",
    targetId: event ?? "",
    result: null,
    loading: false,
    error: null,
  });

  useEffect(() => {
    if (q) {
      setPrefill(q);
      setAutoSend(true);
    }
  }, [q]);

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
      <section className="flex flex-col gap-4 lg:col-span-8">
        <header>
          <p className="paper-kicker">05 / Research</p>
          <h1 className="font-paper text-3xl tracking-tight">研究一个</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            围绕事件、叙事、实体、趋势或历史模式提问；Agent
            展示研究过程（只读工具纪律），可另生成结构化判断。
          </p>
        </header>
        <ChatPanel prefill={prefill} autoSend={autoSend} />
      </section>
      <aside className="flex flex-col gap-4 lg:col-span-4">
        <div className="flex flex-col gap-2">
          <p className="paper-kicker">Suggested research tasks</p>
          {TASKS.map((t) => (
            <button
              key={t.no}
              type="button"
              onClick={() => {
                setSt((s) => ({ ...s, targetId: "" }));
                setPrefill(t.q);
                setAutoSend(true);
              }}
              className="border border-border bg-card px-3 py-2 text-left hover:border-primary/40"
            >
              <span className="font-paper mr-2 text-lg text-muted-foreground/40">{t.no}</span>
              <span className="text-sm font-medium">{t.title}</span>
              <p className="mt-0.5 text-xs leading-5 text-muted-foreground">{t.q}</p>
            </button>
          ))}
        </div>
        <StructuredResearch st={st} setSt={setSt} />
        <KeySetup />
      </aside>
    </div>
  );
}
