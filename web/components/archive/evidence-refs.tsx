"use client";

/**
 * 证据引用 chips（P0-C 证据回链）：点击跳回 Case 对应上下文。
 * rev- 前缀 = document_revision_id（原文正文版本）→ READ 模式并自动选中该文档（?doc=）；
 * 其余 id（claim- / run- / ext- / cmp- 等）→ HISTORY 模式（诚实：到达对象集合，不假装定位片段）。
 * 无 case_id 时降级为纯文本 chip，title 说明无法回链——不编造链接。
 */

import type { TFunc } from "@/components/monitors/bits";

const REV_PREFIX = "rev-";

export function EvidenceRefChips({
  refs,
  caseId,
  t,
}: {
  refs: string[];
  caseId?: string;
  t: TFunc;
}) {
  if (refs.length === 0) return null;
  return (
    <p className="mt-1 flex flex-wrap items-center gap-1">
      <span className="text-[10px] text-muted-foreground">{t("archive.evidenceRefs")}</span>
      {refs.map((ref, i) => {
        if (!caseId) {
          return (
            <span
              key={`${ref}-${i}`}
              title={t("archive.noCaseLink")}
              className="rounded border bg-muted/40 px-1 py-0.5 font-mono text-[10px] text-muted-foreground"
            >
              {ref}
            </span>
          );
        }
        const toDoc = ref.startsWith(REV_PREFIX);
        const href = toDoc
          ? `/cases/${encodeURIComponent(caseId)}?mode=read&doc=${encodeURIComponent(ref)}`
          : `/cases/${encodeURIComponent(caseId)}?mode=history`;
        return (
          <a
            key={`${ref}-${i}`}
            href={href}
            title={toDoc ? t("archive.refOpenDoc") : t("archive.refOpenHistory")}
            className="rounded border bg-muted/40 px-1 py-0.5 font-mono text-[10px] text-muted-foreground underline decoration-dotted underline-offset-2 hover:bg-accent hover:text-foreground"
          >
            {ref}
          </a>
        );
      })}
    </p>
  );
}
