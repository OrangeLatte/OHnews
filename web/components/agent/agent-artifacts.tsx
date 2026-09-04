"use client";

/**
 * AgentDock Artifacts 标签（规格 4.3）：draft 优先（ResearchState.pendingArtifacts，
 * 待 UserCommit）+ 已归档产物（objectApi.archive，只列 committed）。
 */

import { useEffect, useState } from "react";
import { objectApi, type ArchiveRow } from "@/lib/object-api";
import { useT } from "@/lib/i18n/use-t";
import { useResearchState } from "@/lib/research-state";

export function AgentArtifacts() {
  const t = useT();
  const { pendingArtifacts } = useResearchState();
  const [rows, setRows] = useState<ArchiveRow[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    objectApi
      .archive()
      .then((list) => {
        if (alive) setRows(list);
      })
      .catch((e: unknown) => {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="space-y-2 text-xs">
      <p className="font-medium">{t("agentArtifacts.title")}</p>
      <p className="text-muted-foreground">{t("agentArtifacts.hint")}</p>

      {err ? <p className="break-all text-red-600">{err}</p> : null}

      {pendingArtifacts.length > 0 ? (
        <ul className="space-y-1">
          {pendingArtifacts.map((a) => (
            <li
              key={`${a.artifact_id}-${a.revision_id}`}
              className="rounded border border-amber-500/50 bg-amber-50 p-1.5 dark:bg-amber-950"
            >
              <p className="flex items-center gap-1">
                <span className="rounded bg-amber-500 px-1 font-mono text-[10px] text-white">
                  {t("agentArtifacts.draft")}
                </span>
                <span className="truncate font-medium">{a.title || a.artifact_id}</span>
              </p>
              <p className="truncate font-mono text-[10px] text-muted-foreground">
                {a.artifact_id} · {a.revision_id}
              </p>
            </li>
          ))}
        </ul>
      ) : null}

      {rows.length === 0 ? (
        <p className="text-muted-foreground">{t("agentArtifacts.empty")}</p>
      ) : (
        <ul className="space-y-1">
          {rows.map((r) => (
            <li key={r.artifact_id} className="rounded border p-1.5">
              <p className="flex items-center gap-1">
                <span className="rounded bg-muted px-1 font-mono text-[10px]">{r.klass}</span>
                <span className="truncate font-medium">{r.title || r.artifact_id}</span>
              </p>
              <p className="truncate text-[10px] text-muted-foreground">
                {r.case_id || "—"} ·{" "}
                {(r.committed_at ?? r.revision_created_at).slice(0, 16).replace("T", " ")}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
