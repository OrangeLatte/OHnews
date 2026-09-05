"use client";

/**
 * Press Edition 编排向导（三步）：勾选 chips → title/note 表单 → Compose →
 * 草稿预览（sections 列表卡 + skipped 诚实披露）→「发布」HITL（window.confirm，
 * 文案说明 UserCommit 留痕、发布后不可变）→ 成功 toast + 新 Edition 进列表。
 */

import { useState } from "react";
import { objectApi, type WorkflowOut } from "@/lib/object-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import { HelpIcon } from "@/components/help/help-icon";
import { relTime } from "@/components/monitors/format";
import { stampId } from "@/components/monitors/format";
import { type TFunc } from "@/components/monitors/bits";
import { PressRender } from "./press-render";

export type ArchiveRowExt = {
  artifact_id: string;
  case_id: string;
  klass: string;
  title: string;
  report_type: string | null;
  current_revision_id: string;
  revision_created_at: string;
  commit_note?: string | null;
  committed_at?: string | null;
  commit_id?: string | null;
};

type Draft = {
  artifact_id: string;
  revision_id: string;
  n_sections: number;
  skipped: { artifact_id: string; reason: string }[];
  note: string;
  sections: { title: string; klass: string; content: unknown }[];
  created_at: string;
};

export function PressWizard({
  selected,
  onRemove,
  onClear,
  onPublished,
  t,
  lang,
}: {
  selected: ArchiveRowExt[];
  onRemove: (artifactId: string) => void;
  onClear: () => void;
  onPublished: () => void;
  t: TFunc;
  lang: "en" | "zh";
}) {
  const [step, setStep] = useState<"form" | "preview">("form");
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [composing, setComposing] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);

  const stepNow = selected.length === 0 ? 1 : step === "form" ? 2 : 3;

  const compose = () => {
    if (selected.length === 0) {
      toast.error(t("archive.needSelection"));
      return;
    }
    if (!title.trim()) {
      toast.error(t("archive.needTitle"));
      return;
    }
    setComposing(true);
    objectApi
      .composePressEdition({
        artifact_ids: selected.map((s) => s.artifact_id),
        title: title.trim(),
        note: note.trim() || undefined,
      })
      .then((out: WorkflowOut) => {
        const aid = out.artifact_id ?? "";
        const rid = out.revision_id ?? "";
        if (!aid || !rid) throw new Error("no draft artifact");
        return objectApi.artifactRevisions(aid).then((revs) => {
          const rev = revs.find((r) => r.revision_id === rid) as
            | (typeof revs)[number] & { content?: Record<string, unknown> }
            | undefined;
          const content = rev?.content ?? {};
          const rawSections = Array.isArray(content.sections) ? content.sections : [];
          setDraft({
            artifact_id: aid,
            revision_id: rid,
            n_sections: out.n_sections ?? rawSections.length,
            skipped: out.skipped ?? [],
            note: typeof content.note === "string" ? (content.note as string) : note.trim(),
            sections: rawSections
              .map((s) => s as { title?: unknown; klass?: unknown; content?: unknown })
              .map((s, i) => ({
                title: typeof s.title === "string" ? s.title : `#${i + 1}`,
                klass: typeof s.klass === "string" ? s.klass : "",
                content: s.content,
              })),
            created_at: rev?.created_at ?? "",
          });
          setStep("preview");
          setComposing(false);
          toast.info(
            `${t("archive.composedN", { n: out.n_sections ?? rawSections.length })}${
              (out.skipped ?? []).length > 0 ? ` · ${t("archive.skipped")} ${(out.skipped ?? []).length}` : ""
            }`,
          );
        });
      })
      .catch(() => {
        setComposing(false);
        toast.error(t("archive.composeFailed"));
      });
  };

  const publish = () => {
    if (!draft) return;
    if (!window.confirm(t("archive.confirmPublish"))) return;
    setPublishing(true);
    objectApi
      .commitRevision(draft.artifact_id, {
        revision_id: draft.revision_id,
        commit_id: stampId("cmt"),
        user_note: note.trim() || "press edition",
      })
      .then(() => {
        setPublishing(false);
        setDraft(null);
        setStep("form");
        setTitle("");
        setNote("");
        onClear();
        toast.success(t("archive.published"));
        onPublished();
      })
      .catch(() => {
        setPublishing(false);
        toast.error(t("archive.publishFailed"));
      });
  };

  return (
    <section className="space-y-3 rounded-xl border bg-card p-4" aria-label={t("archive.pressWizard")}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">{t("archive.pressWizard")}</h2>
        <HelpIcon helpKey="state.needsConfirm" />
        <ol className="ml-auto flex flex-wrap items-center gap-1 text-xs">
          {[t("archive.stepPick"), t("archive.stepForm"), t("archive.stepPreview")].map((label, i) => {
            const n = i + 1;
            const active = stepNow === n;
            return (
              <li
                key={label}
                className={`rounded-md px-1.5 py-0.5 ${
                  active ? "bg-[#dbeafe] font-medium text-[#1d4ed8] dark:bg-[#2563eb]/20 dark:text-[#93c5fd]" : "text-muted-foreground"
                }`}
              >
                {label}
              </li>
            );
          })}
        </ol>
      </div>

      <p className="text-xs text-muted-foreground">
        {t("archive.wizardDesc")} {t("archive.selectHint")}
      </p>

      {selected.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-foreground">{t("archive.selected", { n: selected.length })}:</span>
          {selected.map((s) => (
            <span
              key={s.artifact_id}
              className="inline-flex max-w-xs items-center gap-1 rounded-md border bg-secondary/60 px-1.5 py-0.5 text-xs"
            >
              <span className="truncate" title={s.title}>
                {s.title}
              </span>
              <button
                type="button"
                aria-label={`remove ${s.title}`}
                className="text-muted-foreground hover:text-destructive"
                onClick={() => onRemove(s.artifact_id)}
              >
                ×
              </button>
            </span>
          ))}
          <button type="button" className="text-xs underline-offset-2 hover:underline" onClick={onClear}>
            {t("archive.cancel")}
          </button>
        </div>
      ) : (
        <p className="rounded-lg border border-dashed px-3 py-2 text-xs text-muted-foreground">
          {t("archive.selectHint")}
        </p>
      )}

      {step === "form" ? (
        <div className="space-y-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("archive.wizardTitle")}
              maxLength={120}
            />
            <p className="self-center text-xs text-muted-foreground">{t("archive.newEditionHint")}</p>
          </div>
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t("archive.notePlaceholder")}
            rows={2}
            className="min-h-0"
          />
          <div className="flex items-center gap-2">
            <Button size="sm" disabled={composing || selected.length === 0} onClick={compose}>
              {composing ? t("archive.composing") : t("archive.composeDraft")}
            </Button>
          </div>
        </div>
      ) : (
        draft && (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              {t("archive.draftReady")}: <span className="font-mono">{draft.revision_id}</span>
              {draft.created_at ? ` · ${relTime(draft.created_at, lang)}` : ""}
            </p>
            <PressRender
              content={{ note: draft.note, sections: draft.sections }}
              title={title}
              createdAt={draft.created_at}
              t={t}
            />
            {draft.skipped.length > 0 && (
              <div className="rounded-lg border bg-[#fef3c7]/50 p-2 text-xs dark:bg-[#d97706]/10">
                <p className="font-medium text-[#b45309] dark:text-[#fbbf24]">
                  {t("archive.skipped")} ({draft.skipped.length})
                </p>
                <ul className="mt-1 space-y-0.5">
                  {draft.skipped.map((s) => (
                    <li key={s.artifact_id} className="font-mono text-muted-foreground">
                      {s.artifact_id} — {s.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                disabled={publishing}
                onClick={publish}
                title={t("archive.publish")}
              >
                {t("archive.publish")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={publishing}
                onClick={() => {
                  setDraft(null);
                  setStep("form");
                }}
              >
                {t("archive.back")}
              </Button>
            </div>
          </div>
        )
      )}

    </section>
  );
}
