"use client";

/**
 * Revision content 预览：press_edition 渲染 note + sections 列表；
 * research_report 等渲染 summary/正文文本；其余 JSON 如实展示（截断）。
 * 不做任何臆造格式化——字段缺失即显示缺失。
 */

import { STRIPES, type TFunc } from "@/components/monitors/bits";
import { klassLabel } from "@/lib/i18n/labels";
import { EvidenceRefChips } from "./evidence-refs";
import { PressRender } from "./press-render";

function textify(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.map((x) => textify(x)).filter(Boolean).join("\n");
  if (typeof v === "object") {
    const d = v as Record<string, unknown>;
    for (const key of ["summary", "text", "body", "answer", "report"]) {
      if (typeof d[key] === "string") return d[key] as string;
    }
    try {
      return JSON.stringify(v, null, 2);
    } catch {
      return String(v);
    }
  }
  return String(v);
}

function cap(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

type SectionItem = {
  artifact_id?: unknown;
  title?: unknown;
  klass?: unknown;
  content?: unknown;
  /** 研究报告分节形状 {title, body, evidence_refs}：完整正文（不只章节标题）。 */
  body?: unknown;
  evidence_refs?: unknown;
};

export function ContentPreview({
  content,
  t,
  klass,
  title,
  createdAt,
  commitId,
  caseId,
}: {
  content: unknown;
  t: TFunc;
  /** artifact klass：press_edition 且为标准 {note, sections} 形状时走报纸版式渲染。 */
  klass?: string;
  /** artifact 级元数据透传给 PressRender（标题/日期/UserCommit 留痕）。 */
  title?: string;
  createdAt?: string;
  commitId?: string;
  /** 来源 Case：证据 chips 回链与"来源 Case"链接行；缺失则诚实降级为纯文本。 */
  caseId?: string;
}) {
  if (content == null) {
    return <p className="text-xs text-muted-foreground">{t("archive.contentNone")}</p>;
  }
  const dict =
    typeof content === "object" && !Array.isArray(content)
      ? (content as Record<string, unknown>)
      : null;
  if (dict && Object.keys(dict).length === 0) {
    return <p className="text-xs text-muted-foreground">{t("archive.contentNone")}</p>;
  }
  if (klass === "press_edition" && dict && Array.isArray(dict.sections)) {
    return (
      <PressRender
        content={content}
        t={t}
        title={title}
        createdAt={createdAt}
        commitId={commitId}
        caseId={caseId}
      />
    );
  }

  const note = dict && typeof dict.note === "string" ? (dict.note as string) : "";
  const rawSections = dict && Array.isArray(dict.sections) ? (dict.sections as SectionItem[]) : [];

  return (
    <div className="space-y-2">
      {caseId ? (
        <p className="text-[11px] text-muted-foreground">
          {t("archive.sourceCase")}{" "}
          <a
            href={`/cases/${encodeURIComponent(caseId)}`}
            className="underline underline-offset-2 hover:text-foreground"
          >
            {caseId}
          </a>
        </p>
      ) : null}
      {note && (
        <p className="whitespace-pre-wrap border-l-2 border-border pl-2 text-xs italic text-muted-foreground">
          {t("archive.noteLabel")}: {cap(note, 600)}
        </p>
      )}
      {rawSections.length > 0 ? (
        <ul className="space-y-2">
          {rawSections.map((s, i) => {
            const title = typeof s.title === "string" ? s.title : (typeof s.artifact_id === "string" ? s.artifact_id : `#${i + 1}`);
            const klass = typeof s.klass === "string" ? s.klass : "";
            // 报告分节 {title, body, evidence_refs} 无 content 字段：body 即完整正文
            // （纯字符串不截断——硬验收要求读到完整正文）；嵌套对象仍走 JSON 兜底截断。
            const rawBody = s.content ?? s.body;
            const bodyText = textify(rawBody);
            const body = typeof rawBody === "string" ? bodyText : cap(bodyText, 400);
            const refs = Array.isArray(s.evidence_refs)
              ? s.evidence_refs.map((x) => String(x)).filter(Boolean)
              : [];
            return (
              <li key={`${title}-${i}`} className="rounded-lg border bg-muted/30 p-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-mono text-[10px] text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>
                  <span className="text-[13px] font-medium">{title}</span>
                  {klass && (
                    <span className={`${STRIPES} rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground`}>
                      {klassLabel(t, klass)}
                    </span>
                  )}
                </div>
                {body && <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">{body}</p>}
                <EvidenceRefChips refs={refs} caseId={caseId} t={t} />
              </li>
            );
          })}
        </ul>
      ) : (
        (() => {
          const fallback = cap(textify(content), 1200);
          if (!fallback || fallback === "{}") {
            return <p className="text-xs text-muted-foreground">{t("archive.contentNone")}</p>;
          }
          const looksJson = fallback.trimStart().startsWith("{") || fallback.trimStart().startsWith("[");
          return looksJson ? (
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-muted/50 p-2 font-mono text-xs leading-relaxed">
              {fallback}
            </pre>
          ) : (
            <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{fallback}</p>
          );
        })()
      )}
    </div>
  );
}
