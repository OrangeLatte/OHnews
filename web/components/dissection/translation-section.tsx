"use client";

/**
 * E1 跨语言整合区：翻译学家工作流——生成翻译副本（独立表，原文不变）。
 * 降级诚实：offline/失败显示原因，不冒充译文。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { SIGNAL } from "@/lib/tokens";

type Translation = Awaited<ReturnType<typeof api.translationOf>>;

export function TranslationSection({ itemKeys }: { itemKeys: string[] }) {
  const [itemKey, setItemKey] = useState("");
  const [tr, setTr] = useState<Translation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const pick = useCallback((k: string) => {
    setItemKey(k);
    setTr(null);
    setError("");
    if (k) {
      api
        .translationOf(k, "en")
        .then((t) => {
          if (alive.current) setTr(t);
        })
        .catch(() => undefined);
    }
  }, []);

  const run = useCallback(() => {
    if (!itemKey || busy) return;
    setBusy(true);
    setError("");
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 110_000);
    api
      .translateArticle(itemKey, "en", ctrl.signal)
      .then((t) => {
        if (alive.current) setTr(t);
      })
      .catch(() => {
        if (alive.current) setError("翻译未完成——可稍后重试（超时或模型不可用）");
      })
      .finally(() => {
        clearTimeout(timer);
        if (alive.current) setBusy(false);
      });
  }, [itemKey, busy]);

  if (itemKeys.length === 0) return null;
  const short = (k: string) => {
    const m = k.match(/^src:([^:]+)/);
    return m ? m[1] : k.slice(0, 24);
  };
  const degraded = tr && tr.engine === "offline";

  return (
    <section aria-label="跨语言副本" className="ts-section">
      <div className="ts-row">
        <select
          aria-label="选择文章生成翻译副本"
          className="ts-select"
          value={itemKey}
          onChange={(e) => pick(e.target.value)}
        >
          <option value="">选择文章生成英文副本…</option>
          {itemKeys.map((k) => (
            <option key={k} value={k}>
              {short(k)}
            </option>
          ))}
        </select>
        <button type="button" className="ts-run" disabled={!itemKey || busy} onClick={run}>
          生成英文副本
        </button>
      </div>
      {busy && <p className="ts-note">翻译中（约需 1–2 分钟，超时自动降级）…</p>}
      {error && <p className="ts-error">{error}</p>}
      {tr && (
        <article className="ts-card">
          <header className="ts-head">
            <strong>{tr.title_translated || "（无标题译文）"}</strong>
            <span className="ts-meta">
              en 副本
              {degraded
                ? " · 词典降级（未生成译文）"
                : ` · ${tr.engine}${tr.model_hint ? ` ${tr.model_hint}` : ""}`}
            </span>
          </header>
          {tr.body_translated && <p className="ts-body">{tr.body_translated}</p>}
          {(tr.term_notes ?? []).length > 0 && (
            <ul className="ts-notes">
              {(tr.term_notes ?? []).map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
        </article>
      )}
      <style jsx>{`
        .ts-section { border-top: 1px solid var(--border); padding: 0.9rem 0; display: grid; gap: 0.6rem; }
        .ts-row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
        .ts-select { max-width: 70%; font-size: 0.85rem; border: 1px solid var(--border); background: transparent; padding: 0.3rem; }
        .ts-run { border: 1px solid var(--border); background: transparent; font-size: 0.8rem; padding: 0.3rem 0.7rem; cursor: pointer; }
        .ts-run:hover:not(:disabled) { border-color: ${SIGNAL.narrative}; color: ${SIGNAL.narrative}; }
        .ts-run:disabled { opacity: 0.5; cursor: not-allowed; }
        .ts-note, .ts-error { font-size: 0.78rem; }
        .ts-error { color: ${SIGNAL.divergence}; }
        .ts-card { border: 1px solid var(--border); padding: 0.7rem 0.9rem; display: grid; gap: 0.4rem; }
        .ts-head { display: flex; flex-wrap: wrap; gap: 0.5rem; justify-content: space-between; align-items: baseline; font-family: var(--font-newspaper); }
        .ts-meta { font-size: 0.72rem; color: var(--muted-foreground); }
        .ts-body { font-size: 0.82rem; margin: 0; color: var(--muted-foreground); white-space: pre-wrap; }
        .ts-notes { margin: 0; padding-left: 1.1rem; font-size: 0.75rem; color: var(--muted-foreground); }
      `}</style>
    </section>
  );
}
