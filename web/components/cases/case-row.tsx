"use client";

/**
 * 研究案例富行：标题 14px semibold + question 截断 + 元数据行（状态色点·origin·相对时间·id chip），
 * 右侧相对时间对齐；hover 显示行内操作（打开/关闭，关闭走 HITL confirm）。
 * 行高 ≥44px；键盘选中态由父级传入。
 */

import type { Ref } from "react";
import type { CaseRow } from "@/lib/object-api";
import { ConfirmButton } from "@/components/ui/confirm-button";
import {
  OriginIcon,
  STATUS_BADGE,
  STATUS_DOT,
  originLabel,
  relTime,
  statusLabel,
} from "./cases-ui";

export type CaseListItem = CaseRow & { title?: string; created_by?: string };

export const ClosableStatuses = new Set(["candidate", "active", "needs_attention", "suspended"]);

export function CaseRowItem({
  c,
  selected,
  zh,
  openLabel,
  closeLabel,
  closeConfirmLabel,
  onOpen,
  onClose,
  rowRef,
}: {
  c: CaseListItem;
  selected: boolean;
  zh: boolean;
  openLabel: string;
  closeLabel: string;
  closeConfirmLabel: string;
  onOpen: (c: CaseListItem) => void;
  onClose: (c: CaseListItem) => void;
  rowRef?: Ref<HTMLDivElement>;
}) {
  const title = (c.title || c.question || c.case_id).trim() || c.case_id;
  const showQuestion = Boolean(c.title && c.question && c.title.trim() !== c.question.trim());
  const closable = ClosableStatuses.has(c.status);

  return (
    <div
      ref={rowRef}
      role="option"
      aria-selected={selected}
      onClick={() => onOpen(c)}
      className={`group min-h-[64px] cursor-pointer rounded-xl border px-3 py-2 transition-colors ${
        selected
          ? "border-[#2563eb] bg-[#2563eb]/5"
          : "border-transparent hover:border-black/10 hover:bg-muted/60"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[14px] font-semibold">{title}</span>
        <span className="shrink-0 text-xs text-muted-foreground" title={c.updated_at}>
          {relTime(c.updated_at, zh)}
        </span>
        <span className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 aria-selected:opacity-100">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onOpen(c);
            }}
            className="rounded-md border px-1.5 py-0.5 text-[11px] hover:bg-muted"
          >
            {openLabel}
          </button>
          {closable ? (
            <span
              onClick={(e) => {
                e.stopPropagation();
              }}
            >
              <ConfirmButton
                onConfirm={() => onClose(c)}
                confirmLabel={closeConfirmLabel}
                className="rounded-md border px-1.5 py-0.5 text-[11px] text-muted-foreground hover:border-[#dc2626]/40 hover:bg-[#fee2e2] hover:text-[#dc2626]"
                armedClassName="border-[#dc2626] bg-[#fee2e2] text-[#b91c1c]"
              >
                {closeLabel}
              </ConfirmButton>
            </span>
          ) : null}
        </span>
      </div>
      {showQuestion ? (
        <p className="mt-0.5 truncate text-[13px] text-muted-foreground">{c.question}</p>
      ) : null}
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span
          className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium ${
            STATUS_BADGE[c.status] ?? "bg-zinc-100 text-[#6b7280]"
          }`}
        >
          <span className={`size-1.5 rounded-full ${STATUS_DOT[c.status] ?? "bg-[#6b7280]"}`} aria-hidden="true" />
          {statusLabel(c.status, zh)}
        </span>
        <span className="inline-flex items-center gap-1">
          <OriginIcon origin={c.origin} />
          {originLabel(c.origin, zh)}
        </span>
        <span aria-hidden="true">·</span>
        <span className="font-mono text-[10px]">{c.case_id}</span>
      </div>
    </div>
  );
}
