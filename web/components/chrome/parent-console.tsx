"use client";

/**
 * E2 总控台（07 parent agent 需求 c/d）：会话汇总 + 拆解队列 + 供应商状态。
 * 确定性汇总 /api/agent/parent/brief（不跑 LLM）。
 */

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Brief = Awaited<ReturnType<typeof api.parentBrief>>;

const KIND_ZH: Record<string, string> = {
  dissection: "拆解",
  tracking: "跟踪",
  memory: "档案",
  parent: "总控",
};
const PROV_ZH: Record<string, string> = {
  deepseek: "DeepSeek",
  zhipu: "智谱",
  tavily: "Tavily",
};

export function ParentConsole() {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .parentBrief()
      .then((b) => {
        if (alive) setBrief(b);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (failed || !brief) return null;
  const sessions = Object.entries(brief.sessions_by_kind ?? {}).filter(([, n]) => n > 0);

  return (
    <section aria-label="总控台" className="pc-card">
      <p className="pc-title">总控台 · AGENTS</p>
      <div className="pc-provs" role="list">
        {Object.entries(brief.providers ?? {}).map(([k, ok]) => (
          <span key={k} role="listitem" className="pc-prov">
            <i className={ok ? "pc-dot ok" : "pc-dot off"} aria-hidden />
            {PROV_ZH[k] ?? k}
          </span>
        ))}
      </div>
      <ul className="pc-rows">
        <li>
          会话：{sessions.length === 0 && "暂无"}
          {sessions.map(([k, n]) => (
            <span key={k} className="pc-session">
              {KIND_ZH[k] ?? k} ×{n}
            </span>
          ))}
        </li>
        <li>拆解队列待处理：{brief.queue_pending} 篇</li>
        {(brief.suggestions ?? []).map((t) => (
          <li key={t} className="pc-tip">
            {t}
          </li>
        ))}
      </ul>
      <a className="pc-link" href="/settings/developer">
        打开开发者台 →
      </a>
      <style jsx>{`
        .pc-card {
          border: 1px solid var(--border);
          padding: 0.8rem 0.9rem;
          display: grid;
          gap: 0.45rem;
        }
        .pc-title {
          font-size: 0.68rem;
          letter-spacing: 0.14em;
          color: var(--muted-foreground);
          margin: 0;
        }
        .pc-provs {
          display: flex;
          gap: 0.7rem;
          flex-wrap: wrap;
          font-size: 0.78rem;
        }
        .pc-prov {
          display: inline-flex;
          align-items: center;
          gap: 0.3rem;
        }
        .pc-dot {
          width: 0.5rem;
          height: 0.5rem;
          border-radius: 9999px;
          display: inline-block;
        }
        .pc-dot.ok {
          background: var(--color-ok, #5e8a5e);
        }
        .pc-dot.off {
          background: var(--color-signal-muted, #8a8378);
          opacity: 0.6;
        }
        .pc-rows {
          margin: 0;
          padding: 0;
          list-style: none;
          font-size: 0.8rem;
          display: grid;
          gap: 0.25rem;
        }
        .pc-session {
          margin-left: 0.4rem;
          color: var(--muted-foreground);
        }
        .pc-tip {
          color: var(--muted-foreground);
        }
        .pc-link {
          font-size: 0.78rem;
          color: var(--color-signal-divergence, #8b2635);
        }
      `}</style>
    </section>
  );
}
