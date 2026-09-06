"use client";

/**
 * Press Edition 报纸版式渲染（P1-10）：题头（serif 大标题 + 日期 + 编者按）→
 * CSS 多栏正文（栏间规则线 + 分栏内 article 块）→ 底部不可变声明。
 * 诚实纪律：section content 只渲染可读字段（string / {sections:[{title,body,evidence_refs}]} /
 * 常见文本字段 / JSON 兜底），读不到的字段跳过，不编造。
 */

import { STRIPES, type TFunc } from "@/components/monitors/bits";
import { klassLabel } from "@/lib/i18n/labels";
import { EvidenceRefChips } from "./evidence-refs";

type EditionSection = {
  artifact_id?: unknown;
  title?: unknown;
  klass?: unknown;
  content?: unknown;
};

const TEXT_KEYS = ["body", "text", "summary", "answer", "report"] as const;
const REF_KEYS = ["title", "id", "ref", "source", "url"] as const;

function refText(r: unknown): string {
  if (typeof r === "string") return r;
  if (typeof r === "object" && r != null) {
    const d = r as Record<string, unknown>;
    for (const k of REF_KEYS) {
      if (typeof d[k] === "string") return d[k] as string;
    }
    try {
      return JSON.stringify(r);
    } catch {
      return "";
    }
  }
  return r == null ? "" : String(r);
}

/** evidence_refs 尾部小字 mono chips（有才渲染）；case_id 存在时点击回链。 */
function RefChips({ refs, caseId, t }: { refs: unknown[]; caseId?: string; t: TFunc }) {
  const chips = refs.map(refText).filter(Boolean);
  return <EvidenceRefChips refs={chips} caseId={caseId} t={t} />;
}

/** 单个 section 的 content 渲染：string / 子 sections / 常见文本字段 / JSON 兜底。 */
function SectionBody({ content, caseId, t }: { content: unknown; caseId?: string; t: TFunc }) {
  if (content == null || content === "") return null;
  if (typeof content === "string") {
    return <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{content}</p>;
  }
  if (typeof content !== "object") {
    return <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{String(content)}</p>;
  }
  const d = content as Record<string, unknown>;
  if (Array.isArray(d.sections)) {
    return (
      <div className="space-y-2">
        {(d.sections as unknown[]).map((sub, i) => {
          const sd = (sub ?? {}) as Record<string, unknown>;
          const st = typeof sd.title === "string" ? sd.title : "";
          const body = typeof sd.body === "string" ? sd.body : "";
          const refs = Array.isArray(sd.evidence_refs) ? (sd.evidence_refs as unknown[]) : [];
          if (!st && !body && refs.length === 0) return null;
          return (
            <div key={i} className="border-t border-dashed border-border pt-1 first:border-t-0 first:pt-0">
              {st && <h5 className="font-paper text-[13px] font-semibold leading-snug">{st}</h5>}
              {body && <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{body}</p>}
              {refs.length > 0 && <RefChips refs={refs} caseId={caseId} t={t} />}
            </div>
          );
        })}
      </div>
    );
  }
  for (const key of TEXT_KEYS) {
    if (typeof d[key] === "string") {
      return <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{d[key] as string}</p>;
    }
  }
  let json = "";
  try {
    json = JSON.stringify(content, null, 2);
  } catch {
    json = "";
  }
  if (json !== "" && json !== "{}") {
    return (
      <pre className="break-words whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-muted-foreground">
        {json}
      </pre>
    );
  }
  return null;
}

/** 正文"文章块"：序号 + serif 标题 + klass 徽标 + 细横线 + 内容。 */
function PressArticle({
  section,
  index,
  t,
  caseId,
}: {
  section: EditionSection;
  index: number;
  t: TFunc;
  caseId?: string;
}) {
  const rawTitle = typeof section.title === "string" ? section.title : "";
  const rawId = typeof section.artifact_id === "string" ? section.artifact_id : "";
  const title = rawTitle || rawId;
  const klass = typeof section.klass === "string" ? section.klass : "";
  if (!title && !klass && section.content == null) return null;
  return (
    <article className="mb-5 break-inside-avoid">
      <p className="font-mono text-[10px] text-muted-foreground">{String(index + 1).padStart(2, "0")}</p>
      {title && <h4 className="mt-0.5 font-paper text-[15px] font-bold leading-snug">{title}</h4>}
      {klass && (
        <span
          className={`${STRIPES} mt-1 inline-block rounded border border-border bg-muted/40 px-1.5 py-0.5 text-[10px] text-muted-foreground`}
        >
          {klassLabel(t, klass)}
        </span>
      )}
      <div className="mt-1.5 border-t border-border pt-1.5">
        <SectionBody content={section.content} caseId={caseId} t={t} />
      </div>
    </article>
  );
}

export function PressRender({
  content,
  t,
  title,
  createdAt,
  commitId,
  caseId,
}: {
  content: unknown;
  t: TFunc;
  /** 版面标题（artifact title）；缺失则不渲染题头标题，不编造。 */
  title?: string;
  /** 版面时间（ISO 字符串），只展示日期段。 */
  createdAt?: string;
  /** UserCommit id，存在则底部留痕。 */
  commitId?: string;
  /** 来源 Case：证据 chips 回链；缺失则 chips 为纯文本（诚实降级）。 */
  caseId?: string;
}) {
  const dict =
    typeof content === "object" && content != null && !Array.isArray(content)
      ? (content as Record<string, unknown>)
      : null;
  const note = dict && typeof dict.note === "string" ? dict.note : "";
  const rawSections = dict && Array.isArray(dict.sections) ? (dict.sections as EditionSection[]) : [];
  const date = createdAt && createdAt.length >= 10 ? createdAt.slice(0, 10) : "";

  return (
    <article className="rounded-lg border bg-card/70 p-4 sm:p-5">
      <header>
        <p className="paper-kicker">
          {t("archive.klass.press_edition")}
          {date ? ` · ${date}` : ""}
        </p>
        {title ? <h3 className="mt-1 font-paper text-2xl font-bold leading-tight tracking-tight">{title}</h3> : null}
        <div className="paper-rule mt-2" aria-hidden="true" />
        {note ? (
          <p className="mt-2 whitespace-pre-wrap font-paper text-[13px] italic leading-relaxed text-muted-foreground">
            <span className="font-semibold not-italic">{t("archive.editionNote")} · </span>
            {note}
          </p>
        ) : null}
      </header>
      {rawSections.length > 0 ? (
        <div className="mt-3 columns-1 gap-8 [column-rule:1px_solid_var(--border)] md:columns-2 lg:columns-3">
          {rawSections.map((s, i) => (
            <PressArticle
              key={typeof s.artifact_id === "string" ? s.artifact_id : i}
              section={s}
              index={i}
              t={t}
              caseId={caseId}
            />
          ))}
        </div>
      ) : (
        <p className="mt-3 text-xs text-muted-foreground">{t("archive.contentNone")}</p>
      )}
      <footer className="mt-2 border-t border-border pt-1.5 text-[10px] text-muted-foreground">
        {t("archive.immutable")}
        {commitId ? <span className="ml-1.5 font-mono">· UserCommit {commitId}</span> : null}
      </footer>
    </article>
  );
}
