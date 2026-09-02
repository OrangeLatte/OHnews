"use client";

/**
 * B0 拆解建议区：系统按可靠性×时效×相关性打分推荐值得拆解的文章，
 * 用户确认后进入拆解队列（token 成本闸门——不盲目全量拆解）。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { SIGNAL } from "@/lib/tokens";
import { track } from "@/lib/track";

type Suggestion = {
  item_key: string;
  score: number;
  reasons?: string[];
};

export function QueueSection() {
  const [items, setItems] = useState<Suggestion[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [note, setNote] = useState("");
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .dissectSuggestions(3)
      .then((xs) => {
        if (!cancelled) setItems(xs);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const decide = useCallback(
    async (itemKey: string, action: "accept" | "dismiss") => {
      try {
        await api.queueDecide(itemKey, action);
        if (alive.current) {
          setItems((prev) => (prev ? prev.filter((x) => x.item_key !== itemKey) : prev));
          setNote(action === "accept" ? "已加入拆解队列" : "已忽略该建议");
        }
        track("evidence_opened", { objectId: itemKey, fromPage: "/events#suggest" });
      } catch {
        if (alive.current) setNote("操作失败，请稍后重试");
      }
    },
    [],
  );

  if (failed || items === null) return null;
  if (items.length === 0) {
    return (
      <p className="qs-empty">当前没有新的拆解建议——推荐列表会随新语料自动更新。</p>
    );
  }
  const short = (k: string) => {
    const m = k.match(/^src:([^:]+)/);
    return m ? m[1] : k.slice(0, 24);
  };

  return (
    <section aria-label="拆解建议" className="qs-section">
      <p className="qs-title">值得拆解的文章（按来源可靠性与相关性推荐）</p>
      {note && <p className="qs-note">{note}</p>}
      {items.map((s) => (
        <div key={s.item_key} className="qs-card">
          <div className="qs-main">
            <span className="qs-src">{short(s.item_key)}</span>
            <span className="qs-score">匹配度 {(s.score * 100).toFixed(0)}</span>
          </div>
          <div className="qs-reasons">
            {(s.reasons ?? []).map((r) => (
              <span key={r} className="qs-chip">
                {r}
              </span>
            ))}
          </div>
          <div className="qs-actions">
            <button type="button" className="qs-btn" onClick={() => decide(s.item_key, "accept")}>
              加入拆解队列
            </button>
            <button type="button" className="qs-btn qs-skip" onClick={() => decide(s.item_key, "dismiss")}>
              忽略
            </button>
          </div>
        </div>
      ))}
      <style jsx>{`
        .qs-section { border-top: 1px solid var(--border); padding: 0.9rem 0; display: grid; gap: 0.5rem; }
        .qs-title { font-size: 0.8rem; color: var(--muted-foreground); margin: 0; }
        .qs-note { font-size: 0.78rem; color: ${SIGNAL.confirmed}; margin: 0; }
        .qs-empty { font-size: 0.8rem; color: var(--muted-foreground); }
        .qs-card { border: 1px solid var(--border); padding: 0.55rem 0.75rem; display: grid; gap: 0.4rem; }
        .qs-main { display: flex; justify-content: space-between; gap: 0.5rem; }
        .qs-src { font-family: var(--font-newspaper); font-size: 0.85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .qs-score { font-size: 0.75rem; color: ${SIGNAL.narrative}; white-space: nowrap; }
        .qs-reasons { display: flex; flex-wrap: wrap; gap: 0.3rem; }
        .qs-chip { font-size: 0.7rem; border: 1px solid var(--border); padding: 0.05rem 0.4rem; color: var(--muted-foreground); }
        .qs-actions { display: flex; gap: 0.5rem; }
        .qs-btn { border: 1px solid var(--border); background: transparent; font-size: 0.75rem; padding: 0.2rem 0.55rem; cursor: pointer; }
        .qs-btn:hover { border-color: ${SIGNAL.narrative}; color: ${SIGNAL.narrative}; }
        .qs-skip { color: var(--muted-foreground); }
      `}</style>
    </section>
  );
}
