"use client";

/**
 * B2 研究报告区：基于拆解结果的六型报告生成与列表。
 * 用户点型 → POST /api/agent/report → 报告卡渲染（engine 徽章诚实降级）。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { SIGNAL } from "@/lib/tokens";
import { track } from "@/lib/track";

const ARCHIVED = new Set<string>();

type Report = Awaited<ReturnType<typeof api.reportsForItem>>[number];

const KINDS = ["truth", "intent", "causal", "narrative", "trend", "summary"] as const;
const KIND_ZH: Record<string, string> = {
  truth: "真实性核查",
  intent: "意图与动机",
  causal: "归因与因果",
  narrative: "叙事与框架",
  trend: "动态趋势",
  summary: "综合摘要",
};

export function ReportSection({ itemKeys }: { itemKeys: string[] }) {
  const [itemKey, setItemKey] = useState("");
  const [reports, setReports] = useState<Report[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const pick = useCallback((k: string) => {
    setItemKey(k);
    setReports([]);
    setError("");
    api
      .reportsForItem(k)
      .then((rs) => {
        if (alive.current) setReports(rs);
      })
      .catch(() => undefined);
  }, []);

  const generate = useCallback(
    (kind: string) => {
      if (!itemKey || busy) return;
      setBusy(true);
      setError("");
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 110_000);
      api
        .reportGenerate(itemKey, kind, ctrl.signal)
        .then((r) => {
          if (alive.current) setReports((prev) => [...prev.filter((x) => x.report_id !== r.report_id), r]);
          track("evidence_opened", { objectId: kind, fromPage: "/events#report" });
        })
        .catch(() => {
          if (alive.current) setError("报告生成未完成——可稍后重试（超时或模型不可用）");
        })
        .finally(() => {
          clearTimeout(timer);
          if (alive.current) setBusy(false);
        });
    },
    [itemKey, busy],
  );

  if (itemKeys.length === 0) return null;
  const short = (k: string) => {
    const m = k.match(/^src:([^:]+)/);
    return m ? m[1] : k.slice(0, 24);
  };

  return (
    <section aria-label="研究报告" className="rs-section">
      <div className="rs-row">
        <select
          aria-label="选择文章生成报告"
          className="rs-select"
          value={itemKey}
          onChange={(e) => pick(e.target.value)}
        >
          <option value="">选择文章生成研究报告…</option>
          {itemKeys.map((k) => (
            <option key={k} value={k}>
              {short(k)}
            </option>
          ))}
        </select>
      </div>
      {itemKey && (
        <div className="rs-kinds" role="group" aria-label="报告类型">
          {KINDS.map((k) => (
            <button
              key={k}
              type="button"
              className="rs-kind"
              disabled={busy}
              onClick={() => generate(k)}
            >
              {KIND_ZH[k]}
            </button>
          ))}
          {busy && <span className="rs-note">生成中（约需 1–2 分钟，超时自动降级）…</span>}
        </div>
      )}
      {error && <p className="rs-error">{error}</p>}
      {note && <p className="rs-note-ok">{note}</p>}
      {reports.map((r) => (
        <article key={r.report_id} className="rs-card">
          <header className="rs-head">
            <strong>{r.title}</strong>
            <span className="rs-meta">
              {KIND_ZH[r.kind] ?? r.kind}
              {r.engine === "offline" && " · 词典降级（模型不可用）"}
              {r.engine === "llm" && r.model_hint ? ` · ${r.model_hint}` : ""}
            </span>
          </header>
          {(r.sections ?? []).map((sec) => (
            <div key={sec.title} className="rs-sec">
              <h4>{sec.title}</h4>
              <p>{sec.body}</p>
            </div>
          ))}
          <button
            type="button"
            className="rs-save"
            disabled={ARCHIVED.has(r.report_id)}
            onClick={() => {
              api
                .archiveSave({
                  kind: "report",
                  title: r.title,
                  ref_kind: "report",
                  ref_id: r.report_id,
                  payload: r as unknown as Record<string, unknown>,
                  note: "来自研究报告区",
                })
                .then(() => {
                  ARCHIVED.add(r.report_id);
                  track("evidence_opened", { objectId: r.report_id, fromPage: "/events#archive" });
                  setNote("已存入研究档案（MEMORY 可查看）");
                })
                .catch(() => setNote("存档失败——请稍后重试"));
            }}
          >
            {ARCHIVED.has(r.report_id) ? "已存入档案" : "存入研究档案"}
          </button>
        </article>
      ))}
      <style jsx>{`
        .rs-section { border-top: 1px solid var(--border); padding: 0.9rem 0; display: grid; gap: 0.6rem; }
        .rs-row { display: flex; }
        .rs-select { max-width: 100%; font-size: 0.85rem; border: 1px solid var(--border); background: transparent; padding: 0.3rem; }
        .rs-kinds { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
        .rs-kind { border: 1px solid var(--border); background: transparent; font-size: 0.78rem; padding: 0.25rem 0.55rem; cursor: pointer; }
        .rs-kind:hover:not(:disabled) { border-color: ${SIGNAL.narrative}; color: ${SIGNAL.narrative}; }
        .rs-kind:disabled { opacity: 0.5; cursor: wait; }
        .rs-note { font-size: 0.75rem; color: var(--muted-foreground); }
        .rs-error { font-size: 0.8rem; color: ${SIGNAL.divergence}; }
        .rs-note-ok { font-size: 0.8rem; color: ${SIGNAL.confirmed}; }
        .rs-save { border: 1px solid var(--border); background: transparent; font-size: 0.78rem; padding: 0.25rem 0.55rem; cursor: pointer; width: fit-content; }
        .rs-save:hover:not(:disabled) { border-color: ${SIGNAL.narrative}; color: ${SIGNAL.narrative}; }
        .rs-save:disabled { opacity: 0.6; cursor: default; }
        .rs-card { border: 1px solid var(--border); padding: 0.7rem 0.9rem; display: grid; gap: 0.5rem; }
        .rs-head { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: baseline; justify-content: space-between; font-family: var(--font-newspaper); }
        .rs-meta { font-size: 0.72rem; color: var(--muted-foreground); }
        .rs-sec h4 { font-size: 0.82rem; margin: 0 0 0.15rem; }
        .rs-sec p { font-size: 0.82rem; margin: 0; color: var(--muted-foreground); white-space: pre-wrap; }
      `}</style>
    </section>
  );
}
