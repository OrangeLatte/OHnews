"use client";

/**
 * 版本链（GitHub commit history 模式）：垂直列表 v1→vN + 状态徽标
 * （draft 灰斜纹 / committed 绿 / superseded 灰删除线）+ 时间戳 + 可展开 content 预览。
 * ≥2 个版本时提供「对比上一版」懒加载 diff（相邻版本对；失败诚实显示，404=归属异常不编造）。
 */

import { useState } from "react";
import { objectApi, type DiffFieldChange, type DiffRow } from "@/lib/object-api";
import type { RevisionRow } from "@/lib/object-api";
import { relTime, shortValue } from "@/components/monitors/format";
import { ToneChip, type TFunc, type Tone } from "@/components/monitors/bits";
import { ContentPreview } from "./content-preview";

export type RevisionWithContent = RevisionRow & { content?: unknown };

function RevBadge({ status, t }: { status: string; t: TFunc }) {
  if (status === "committed") return <ToneChip tone="ok">{t("archive.revCommitted")}</ToneChip>;
  if (status === "superseded") return <ToneChip tone="idle" strike>{t("archive.revSuperseded")}</ToneChip>;
  if (status === "draft") return <ToneChip tone="idle" striped>{t("archive.revDraft")}</ToneChip>;
  return <ToneChip tone="idle">{status}</ToneChip>;
}

const SECTION_FIELD_RE = /^sections\[\d+\]$/;

type SectionStatus = "added" | "removed" | "changed" | "unchanged";

/** sections[i] 语义状态：单侧缺失=added/removed，双侧在=changed/unchanged。 */
function sectionStatus(c: DiffFieldChange): SectionStatus {
  if (c.from_value == null && c.to_value != null) return "added";
  if (c.from_value != null && c.to_value == null) return "removed";
  return c.changed ? "changed" : "unchanged";
}

const SECTION_TONE: Record<SectionStatus, Tone> = {
  added: "ok",
  removed: "bad",
  changed: "warn",
  unchanged: "idle",
};

function asStringArray(v: unknown): string[] {
  return Array.isArray(v) ? v.map((x) => String(x)) : [];
}

/** R6 T4 版本 inputs 摘要（research_report content.inputs）：仅取数值字段，缺失诚实显示 —。 */
function revInputsOf(content: unknown): { docs: string; exts: string; claims: string } | null {
  if (content == null || typeof content !== "object" || Array.isArray(content)) return null;
  const inputs = (content as { inputs?: unknown }).inputs;
  if (inputs == null || typeof inputs !== "object") return null;
  const n = (k: string): string => {
    const v = (inputs as Record<string, unknown>)[k];
    return typeof v === "number" && Number.isFinite(v) ? String(v) : "—";
  };
  return { docs: n("n_documents"), exts: n("n_extractions"), claims: n("n_claims") };
}

function titleOf(v: unknown): string {
  if (v == null || typeof v !== "object") return "";
  return String((v as { title?: unknown }).title ?? "");
}

/** diff 渲染：changed 徽标 + sections 语义色列表 + evidence_refs 移除/新增 chips + 标量字段 from→to。 */
function DiffPanel({ d, t }: { d: DiffRow; t: TFunc }) {
  const changed = d.changes.some((c) => c.changed);
  const sectionRows = d.changes.filter((c) => SECTION_FIELD_RE.test(c.field));
  const evRow = d.changes.find((c) => c.field === "evidence_refs");
  const evRemoved = evRow ? asStringArray(evRow.from_value) : [];
  const evAdded = evRow ? asStringArray(evRow.to_value) : [];
  const scalars = d.changes.filter(
    (c) => c.changed && !SECTION_FIELD_RE.test(c.field) && c.field !== "evidence_refs",
  );
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {changed ? (
          <ToneChip tone="warn">▲ {t("archive.diffBadge")}</ToneChip>
        ) : (
          <ToneChip tone="idle">{t("archive.diffStatus.unchanged")}</ToneChip>
        )}
        <span className="truncate font-mono text-[10px] text-muted-foreground">
          {d.from.revision_id} → {d.to.revision_id}
        </span>
      </div>
      {sectionRows.length > 0 && (
        <ul className="space-y-1">
          {sectionRows.map((c) => {
            const st = sectionStatus(c);
            const fromTitle = titleOf(c.from_value);
            const toTitle = titleOf(c.to_value);
            return (
              <li key={c.field} className="flex flex-wrap items-center gap-1.5">
                <ToneChip tone={SECTION_TONE[st]}>{t(`archive.diffStatus.${st}`)}</ToneChip>
                <span className="font-mono text-[10px] text-muted-foreground">{c.field}</span>
                <span className="min-w-0 truncate text-xs">
                  {st === "added"
                    ? `+ ${toTitle}`
                    : st === "removed"
                      ? `− ${fromTitle}`
                      : `${fromTitle} → ${toTitle}`}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {(evRemoved.length > 0 || evAdded.length > 0) && (
        <div className="space-y-1">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            {t("monitors.evidence")}
          </p>
          <div className="flex flex-wrap gap-1">
            {evRemoved.map((id) => (
              <span
                key={`rm-${id}`}
                className="rounded-[6px] bg-[#fee2e2] px-1.5 py-0.5 text-[10px] text-[#b91c1c] dark:bg-[#dc2626]/20 dark:text-[#f87171]"
              >
                − {id}
              </span>
            ))}
            {evAdded.map((id) => (
              <span
                key={`add-${id}`}
                className="rounded-[6px] bg-[#dcfce7] px-1.5 py-0.5 text-[10px] text-[#15803d] dark:bg-[#16a34a]/20 dark:text-[#4ade80]"
              >
                + {id}
              </span>
            ))}
          </div>
        </div>
      )}
      {scalars.length > 0 && (
        <ul className="space-y-0.5 text-xs">
          {scalars.map((c) => (
            <li key={c.field} className="flex flex-wrap items-baseline gap-1">
              <span className="font-mono text-[10px] text-muted-foreground">{c.field}:</span>
              <span className="min-w-0">
                {shortValue(c.from_value)} <span className="text-muted-foreground">→</span>{" "}
                {shortValue(c.to_value)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function RevisionChain({
  revisions,
  t,
  lang,
  artifactKlass,
  artifactTitle,
  commitId,
  caseId,
}: {
  revisions: RevisionWithContent[];
  t: TFunc;
  lang: "en" | "zh";
  /** artifact 级元数据：press_edition 走报纸版式（klass/title/UserCommit）。 */
  artifactKlass?: string;
  artifactTitle?: string;
  commitId?: string;
  /** 来源 Case：透传给 ContentPreview，供证据 chips 与"来源 Case"行回链。 */
  caseId?: string;
}) {
  const [openRev, setOpenRev] = useState("");
  const [openDiff, setOpenDiff] = useState("");
  // diffs[key]："loading" | null(失败，诚实显示) | DiffRow；懒加载一次后缓存。
  const [diffs, setDiffs] = useState<Record<string, DiffRow | null | "loading">>({});

  const loadDiff = (artifactId: string, fromRev: string, toRev: string) => {
    const key = `${fromRev}->${toRev}`;
    if (diffs[key] !== undefined) return;
    setDiffs((d) => ({ ...d, [key]: "loading" }));
    objectApi
      .artifactDiff(artifactId, fromRev, toRev)
      .then((row) => setDiffs((d) => ({ ...d, [key]: row })))
      .catch(() => setDiffs((d) => ({ ...d, [key]: null })));
  };

  if (revisions.length === 0) {
    return <p className="text-xs text-muted-foreground">{t("archive.vNone")}</p>;
  }
  return (
    <ul className="relative space-y-2 border-l border-dashed border-border pl-4">
      {revisions.map((r, i) => {
        const hasPayload = r.content != null && (!(typeof r.content === "object") || Object.keys(r.content as object).length > 0);
        const revInputs = revInputsOf(r.content);
        const open = openRev === r.revision_id;
        const prev = i > 0 ? revisions[i - 1] : null;
        const diffKey = prev ? `${prev.revision_id}->${r.revision_id}` : "";
        const diffOpen = diffKey !== "" && openDiff === diffKey;
        const diff = diffKey !== "" ? diffs[diffKey] : undefined;
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
              {revInputs && (
                <span
                  className="font-mono text-[10px] text-muted-foreground"
                  title={t("archive.inputsSummary")}
                >
                  {t("case.inDocs")} {revInputs.docs} · {t("case.inExtractions")} {revInputs.exts} ·{" "}
                  {t("case.inClaims")} {revInputs.claims}
                </span>
              )}
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
            {prev && (
              <div className="mt-1">
                <button
                  type="button"
                  aria-expanded={diffOpen}
                  className="text-xs underline-offset-2 hover:underline"
                  onClick={() => {
                    setOpenDiff(diffOpen ? "" : diffKey);
                    if (!diffOpen) loadDiff(r.artifact_id, prev.revision_id, r.revision_id);
                  }}
                >
                  {t("archive.diff")} · v{i} → v{i + 1} {diffOpen ? "▾" : "▸"}
                </button>
                {diffOpen && (
                  <div className="motion-fade-in mt-2 rounded-lg border bg-card/60 p-2">
                    {diff === "loading" || diff === undefined ? (
                      <p className="text-xs text-muted-foreground">{t("common.loading")}</p>
                    ) : diff === null ? (
                      <p className="text-xs text-[#b91c1c] dark:text-[#f87171]">
                        {t("archive.diffLoadFailed")}
                      </p>
                    ) : (
                      <DiffPanel d={diff} t={t} />
                    )}
                  </div>
                )}
              </div>
            )}
            {open && (
              <div className="motion-fade-in mt-2 rounded-lg border bg-card/60 p-2">
                <ContentPreview
                  content={r.content}
                  t={t}
                  klass={artifactKlass}
                  title={artifactTitle}
                  createdAt={r.created_at}
                  commitId={commitId}
                  caseId={caseId}
                />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
