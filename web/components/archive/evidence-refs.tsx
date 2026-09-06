"use client";

/**
 * 证据引用 chips（P0-C 证据回链 → R6 类型化深链）：按 id 前缀分流到对应上下文，
 * 每类 chip 带类型后缀徽标（禁止裸跳）：
 * rev-       → READ 模式并自动选中该文档（?doc=）            [原文]
 * ext-       → HISTORY 模式（元素提取所在 Case 运行集合）     [元素]
 * claim-     → HISTORY 模式并高亮该主张卡（?claim=）         [主张]
 * cmp-       → COMPARE 模式（恢复最近/?run= 指定比较结果）    [比较]
 * mrun-/mon- → /monitors?open=<id> 自动选中该监测器          [监测]
 * 其余未知前缀 → HISTORY 模式（诚实 fallback，不假装定位片段）。
 * 无 case_id 时降级为纯文本 chip，title 说明无法回链——不编造链接。
 */

import type { TFunc } from "@/components/monitors/bits";

type RefKind = "rev" | "ext" | "claim" | "cmp" | "monitor" | "unknown";

function refKindOf(ref: string): RefKind {
  if (ref.startsWith("rev-")) return "rev";
  if (ref.startsWith("ext-")) return "ext";
  if (ref.startsWith("claim-")) return "claim";
  if (ref.startsWith("cmp-")) return "cmp";
  if (ref.startsWith("mrun-") || ref.startsWith("mon-")) return "monitor";
  return "unknown";
}

/** 类型徽标键：unknown 无徽标（诚实 fallback，仅 title 说明去向）。 */
const KIND_BADGE_KEY: Record<RefKind, string> = {
  rev: "archive.refDoc",
  ext: "archive.refExt",
  claim: "archive.refClaim",
  cmp: "archive.refCompare",
  monitor: "archive.refMonitor",
  unknown: "",
};

function hrefOf(kind: RefKind, ref: string, caseId: string): string {
  const base = `/cases/${encodeURIComponent(caseId)}`;
  switch (kind) {
    case "rev":
      return `${base}?mode=read&doc=${encodeURIComponent(ref)}`;
    case "claim":
      return `${base}?mode=history&claim=${encodeURIComponent(ref)}`;
    case "cmp":
      return `${base}?mode=compare`;
    case "monitor":
      return `/monitors?open=${encodeURIComponent(ref)}`;
    default:
      return `${base}?mode=history`;
  }
}

function titleOf(kind: RefKind, t: TFunc): string {
  if (kind === "rev") return t("archive.refOpenDoc");
  if (kind === "unknown" || kind === "ext") return t("archive.refOpenHistory");
  return t(KIND_BADGE_KEY[kind]);
}

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
        const kind = refKindOf(ref);
        const badgeKey = KIND_BADGE_KEY[kind];
        return (
          <a
            key={`${ref}-${i}`}
            href={hrefOf(kind, ref, caseId)}
            title={titleOf(kind, t)}
            className="inline-flex items-center gap-1 rounded border bg-muted/40 px-1 py-0.5 font-mono text-[10px] text-muted-foreground underline decoration-dotted underline-offset-2 hover:bg-accent hover:text-foreground"
          >
            {ref}
            {badgeKey ? (
              <span className="no-underline rounded bg-foreground/10 px-1 font-sans">
                {t(badgeKey)}
              </span>
            ) : null}
          </a>
        );
      })}
    </p>
  );
}
