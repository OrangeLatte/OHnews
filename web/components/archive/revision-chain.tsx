"use client";

/**
 * 版本链（GitHub commit history 模式）：垂直列表 v1→vN + 状态徽标
 * （draft 灰斜纹 / committed 绿 / superseded 灰删除线）+ 时间戳 + 可展开 content 预览。
 */

import { useState } from "react";
import type { RevisionRow } from "@/lib/object-api";
import { relTime } from "@/components/monitors/format";
import { ToneChip, type TFunc } from "@/components/monitors/bits";
import { ContentPreview } from "./content-preview";

export type RevisionWithContent = RevisionRow & { content?: unknown };

function RevBadge({ status, t }: { status: string; t: TFunc }) {
  if (status === "committed") return <ToneChip tone="ok">{t("archive.revCommitted")}</ToneChip>;
  if (status === "superseded") return <ToneChip tone="idle" strike>{t("archive.revSuperseded")}</ToneChip>;
  if (status === "draft") return <ToneChip tone="idle" striped>{t("archive.revDraft")}</ToneChip>;
  return <ToneChip tone="idle">{status}</ToneChip>;
}

export function RevisionChain({
  revisions,
  t,
  lang,
}: {
  revisions: RevisionWithContent[];
  t: TFunc;
  lang: "en" | "zh";
}) {
  const [openRev, setOpenRev] = useState("");
  if (revisions.length === 0) {
    return <p className="text-xs text-muted-foreground">{t("archive.vNone")}</p>;
  }
  return (
    <ul className="relative space-y-2 border-l border-dashed border-border pl-4">
      {revisions.map((r, i) => {
        const hasPayload = r.content != null && (!(typeof r.content === "object") || Object.keys(r.content as object).length > 0);
        const open = openRev === r.revision_id;
        return (
          <li key={r.revision_id} className="relative">
            <span
              className="absolute -left-[21px] top-2 inline-flex h-2.5 w-2.5 rounded-full bg-muted-foreground/50"
              aria-hidden="true"
            />
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-secondary px-1.5 py-0.5 font-mono text-[10px] font-semibold text-secondary-foreground">
                v{i + 1}
              </span>
              <RevBadge status={r.status} t={t} />
              <span className="font-mono text-xs text-muted-foreground">{r.revision_id}</span>
              <span className="text-xs text-muted-foreground">· {relTime(r.created_at, lang)}</span>
              {r.legacy && <span className="text-xs text-muted-foreground">· legacy</span>}
              {hasPayload && (
                <button
                  type="button"
                  aria-expanded={open}
                  className="ml-auto text-xs underline-offset-2 hover:underline"
                  onClick={() => setOpenRev(open ? "" : r.revision_id)}
                >
                  {t("archive.content")} {open ? "▾" : "▸"}
                </button>
              )}
            </div>
            {open && (
              <div className="mt-2 rounded-lg border bg-card/60 p-2">
                <ContentPreview content={r.content} t={t} />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
