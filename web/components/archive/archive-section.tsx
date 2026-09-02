"use client";

/**
 * Phase D：MEMORY 三档案库（元素/研究/交叉分析）+ 档案报纸。
 * 确认式存档语义：条目由 02 页用户显式确认写入；此处只读+删除+报纸组合。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { SIGNAL } from "@/lib/tokens";

type Item = {
  archive_id: string;
  kind: string;
  title: string;
  ref_kind: string;
  ref_id: string;
  payload: Record<string, unknown>;
  note: string;
  created_at: string;
};
type Paper = {
  paper_id: string;
  title: string;
  item_ids?: string[];
  foreword: string;
  created_at: string;
};

const KIND_TABS = [
  { k: "", zh: "全部" },
  { k: "dissection", zh: "元素档案" },
  { k: "report", zh: "研究档案" },
  { k: "cross_analysis", zh: "交叉分析" },
];

export function ArchiveSection() {
  const [tab, setTab] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [papers, setPapers] = useState<Paper[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(
    (k: string) => {
      api
        .archiveList(k || undefined)
        .then((d) => {
          if (!alive.current) return;
          setItems((d.items ?? []) as Item[]);
          setCounts((d.counts ?? {}) as Record<string, number>);
        })
        .catch(() => undefined);
      api
        .archivePapers()
        .then((ps) => {
          if (alive.current) setPapers(ps as Paper[]);
        })
        .catch(() => undefined);
    },
    [],
  );

  useEffect(() => {
    load(tab);
  }, [tab, load]);

  const makePaper = useCallback(() => {
    setBusy(true);
    setNote("");
    api
      .paperCreate({ kind: tab || undefined })
      .then((p) => {
        setNote(`已生成《${p.title}》（${(p.item_ids ?? []).length} 条）`);
        load(tab);
      })
      .catch(() => setNote("报纸生成失败——可能没有可用的档案条目"))
      .finally(() => setBusy(false));
  }, [tab, load]);

  const del = useCallback(
    (id: string) => {
      api.archiveDelete(id).then(() => load(tab)).catch(() => undefined);
    },
    [tab, load],
  );

  return (
    <section aria-label="三档案库" className="as-section">
      <div className="as-tabs" role="tablist" aria-label="档案库分类">
        {KIND_TABS.map((t) => (
          <button
            key={t.k}
            type="button"
            role="tab"
            aria-selected={tab === t.k}
            className="as-tab"
            onClick={() => setTab(t.k)}
          >
            {t.zh}
            {t.k && counts[t.k] !== undefined ? ` (${counts[t.k]})` : ""}
          </button>
        ))}
        <button type="button" className="as-paper-btn" disabled={busy} onClick={makePaper}>
          组合档案报纸
        </button>
      </div>
      {note && <p className="as-note">{note}</p>}
      {items.length === 0 && (
        <p className="as-empty">
          暂无档案——在 02 页对拆解或报告点击「存入档案」后会出现（系统不会自动存档）。
        </p>
      )}
      <ul className="as-list">
        {items.map((it) => (
          <li key={it.archive_id} className="as-item">
            <div>
              <strong className="as-title">{it.title}</strong>
              <span className="as-meta">
                {it.kind} · {it.created_at.slice(0, 10)}
                {it.note ? ` · ${it.note}` : ""}
              </span>
            </div>
            <button type="button" className="as-del" onClick={() => del(it.archive_id)}>
              删除
            </button>
          </li>
        ))}
      </ul>
      {papers.length > 0 && (
        <div className="as-papers">
          <h4 className="as-papers-title">档案报纸</h4>
          {papers.map((p) => (
            <article key={p.paper_id} className="as-paper">
              <strong>{p.title}</strong>
              <p className="as-foreword">{p.foreword}</p>
              <span className="as-meta">{(p.item_ids ?? []).length} 条 · {p.created_at.slice(0, 10)}</span>
            </article>
          ))}
        </div>
      )}
      <style jsx>{`
        .as-section { border-top: 1px solid var(--border); padding: 1rem 0; display: grid; gap: 0.7rem; }
        .as-tabs { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
        .as-tab { border: 1px solid var(--border); background: transparent; font-size: 0.8rem; padding: 0.3rem 0.7rem; cursor: pointer; }
        .as-tab[aria-selected="true"] { border-color: ${SIGNAL.narrative}; color: ${SIGNAL.narrative}; }
        .as-paper-btn { margin-left: auto; border: 1px solid ${SIGNAL.narrative}; color: ${SIGNAL.narrative}; background: transparent; font-size: 0.8rem; padding: 0.3rem 0.7rem; cursor: pointer; }
        .as-paper-btn:disabled { opacity: 0.5; }
        .as-note { font-size: 0.8rem; color: ${SIGNAL.confirmed}; }
        .as-empty { font-size: 0.82rem; color: var(--muted-foreground); }
        .as-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.45rem; }
        .as-item { display: flex; justify-content: space-between; align-items: baseline; gap: 0.6rem; border-bottom: 1px dotted var(--border); padding-bottom: 0.35rem; }
        .as-title { font-family: var(--font-newspaper); font-size: 0.9rem; }
        .as-meta { font-size: 0.72rem; color: var(--muted-foreground); margin-left: 0.5rem; }
        .as-del { border: none; background: none; font-size: 0.75rem; color: var(--muted-foreground); cursor: pointer; }
        .as-del:hover { color: ${SIGNAL.divergence}; }
        .as-papers { display: grid; gap: 0.5rem; border-top: 1px dashed var(--border); padding-top: 0.6rem; }
        .as-papers-title { font-size: 0.85rem; margin: 0; }
        .as-paper { border: 1px solid var(--border); padding: 0.6rem 0.8rem; display: grid; gap: 0.3rem; font-family: var(--font-newspaper); }
        .as-foreword { font-size: 0.8rem; margin: 0; color: var(--muted-foreground); }
      `}</style>
    </section>
  );
}
