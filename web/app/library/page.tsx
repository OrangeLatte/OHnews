"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type LibraryItem } from "@/lib/api";

const TYPE_META: Record<string, { label: string; color: string }> = {
  analysis: { label: "分析", color: "#58a6ff" },
  event: { label: "事件", color: "#d29922" },
  note: { label: "笔记", color: "#3fb950" },
};

const TYPES = ["analysis", "event", "note"] as const;

function payloadLines(item: LibraryItem): string[] {
  const p = item.payload ?? {};
  if (item.item_type === "analysis") {
    const ev = Array.isArray(p.evidence) ? (p.evidence as string[]) : [];
    return [
      String(p.observation ?? ""),
      String(p.interpretation ?? ""),
      ...(ev.length ? [`证据源：${ev.join("、")}`] : []),
      p.alternative ? `备选解释：${String(p.alternative)}` : "",
      p.uncertainty ? `不确定性：${String(p.uncertainty)}` : "",
    ].filter(Boolean);
  }
  if (item.item_type === "event") {
    return [
      p.event_id ? `事件 ${String(p.event_id)}` : "",
      p.ndi != null ? `NDI ${String(p.ndi)}` : "NDI abstain",
    ].filter(Boolean);
  }
  return String(p.text ?? "").split("\n").filter(Boolean);
}

export default function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [noteText, setNoteText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(() => {
    api
      .library(filter === "all" ? undefined : filter)
      .then((r) => setItems(r.items))
      .catch((err) => setError(String(err)));
  }, [filter]);

  useEffect(load, [load]);

  const remove = async (id: string) => {
    await api.libraryRemove(id);
    load();
  };

  const addNote = async () => {
    if (!noteText.trim()) return;
    try {
      await api.libraryAdd({
        item_type: "note",
        title: noteText.trim().split("\n")[0].slice(0, 40),
        payload: { text: noteText.trim() },
      });
      setNoteText("");
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      load();
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="font-paper text-3xl tracking-tight">研究档案库</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        沉淀研究对象：Agent 分析结论、收藏事件、手写笔记（REMEMBER）。
      </p>

      <div className="mt-6 flex items-center gap-2">
        {(["all", ...TYPES] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setFilter(t)}
            className={`rounded-full border px-3 py-1 text-xs transition-colors ${
              filter === t
                ? "border-foreground bg-foreground text-background"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            {t === "all" ? "全部" : TYPE_META[t].label}
          </button>
        ))}
      </div>

      <div className="mt-4 flex gap-2">
        <input
          value={noteText}
          onChange={(e) => setNoteText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addNote()}
          placeholder="写一条研究笔记，Enter 保存…"
          className="flex-1 rounded-md border border-border bg-transparent px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
        />
        <button
          type="button"
          onClick={addNote}
          className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:bg-primary/90"
        >
          {saved ? "已保存" : "存入"}
        </button>
      </div>

      {error && <p className="mt-4 text-sm text-red-500">{error}</p>}

      {items === null ? (
        <p className="mt-8 text-sm text-muted-foreground">加载中…</p>
      ) : items.length === 0 ? (
        <p className="mt-8 text-sm text-muted-foreground">
          档案库为空。在分析师页运行研究后保存结论，或收藏事件。
        </p>
      ) : (
        <div className="mt-6 flex flex-col gap-3">
          {items.map((it) => {
            const meta = TYPE_META[it.item_type] ?? TYPE_META.note;
            return (
              <div key={it.item_id} className="rounded-md border border-border/60 p-4">
                <div className="flex items-center gap-2">
                  <span
                    className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                    style={{ backgroundColor: `${meta.color}22`, color: meta.color }}
                  >
                    {meta.label}
                  </span>
                  <span className="flex-1 truncate text-sm font-medium">{it.title}</span>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {it.created_at.slice(0, 16).replace("T", " ")}
                  </span>
                  <button
                    type="button"
                    onClick={() => remove(it.item_id)}
                    className="text-xs text-muted-foreground hover:text-red-500"
                  >
                    删除
                  </button>
                </div>
                {it.ref_id && (
                  <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                    {it.ref_kind}: {it.ref_id}
                  </p>
                )}
                <div className="mt-2 flex flex-col gap-1">
                  {payloadLines(it).map((line, idx) => (
                    <p key={idx} className="text-sm text-foreground/90">
                      {line}
                    </p>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
