"use client";

/**
 * 新建研究 Case 弹窗：title/question 双必填校验 → POST /api/cases → 跳转详情。
 * HITL：创建即写库，表单内显式提交；失败原地提示不清空输入。
 */

import { useState } from "react";
import { objectApi, type CaseRow } from "@/lib/object-api";
import { track } from "@/lib/track";
import { newCaseId, nowIso, useTr } from "./cases-ui";

export function CaseCreateDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (c: CaseRow) => void;
}) {
  const tr = useTr();
  const [title, setTitle] = useState("");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = (): void => {
    const ti = title.trim();
    const qu = question.trim();
    if (!ti) {
      setErr(tr("cases.needTitle", "Title is required."));
      return;
    }
    if (!qu) {
      setErr(tr("cases.needQuestion", "Research question is required."));
      return;
    }
    setBusy(true);
    setErr("");
    /* title/created_by 为后端契约字段；lib 内联类型暂未声明，用非字面量对象透传。 */
    const payload = {
      case_id: newCaseId(),
      title: ti,
      question: qu,
      origin: "user",
      created_by: "user",
      created_at: nowIso(),
      updated_at: nowIso(),
    };
    objectApi
      .createCase(payload)
      .then((c) => {
        setBusy(false);
        track("case_created", { objectId: c.case_id, fromPage: "/cases" });
        onCreated(c);
      })
      .catch(() => {
        setBusy(false);
        setErr(tr("cases.createFailed", "Create failed. Check the backend and retry."));
      });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={tr("cases.new", "New research case")}
      onKeyDown={(e) => {
        if (e.key === "Escape" && !busy) onClose();
      }}
    >
      <button
        type="button"
        aria-label={tr("cases.cancel", "Cancel")}
        className="absolute inset-0 cursor-default"
        onClick={() => {
          if (!busy) onClose();
        }}
      />
      <div className="relative w-full max-w-lg rounded-xl border bg-card p-5 shadow-xl">
        <h2 className="text-sm font-semibold">{tr("cases.new", "New research case")}</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          {tr("cases.newDesc", "A case follows one question from source streams to an archived report.")}
        </p>
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!busy) submit();
          }}
        >
          <label className="block text-xs">
            <span className="font-medium">
              {tr("cases.titleField", "Title")} <span className="text-[#dc2626]">*</span>
            </span>
            <input
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={tr("cases.titlePlaceholder", "Short title, e.g. Rate-cut narrative split")}
              className="mt-1 w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-[#2563eb] focus:ring-2 focus:ring-[#2563eb]/20"
            />
          </label>
          <label className="block text-xs">
            <span className="font-medium">
              {tr("cases.questionField", "Research question")} <span className="text-[#dc2626]">*</span>
            </span>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={3}
              placeholder={tr("cases.questionPlaceholder", "What do you want to figure out?")}
              className="mt-1 w-full resize-y rounded-lg border px-3 py-2 text-sm outline-none focus:border-[#2563eb] focus:ring-2 focus:ring-[#2563eb]/20"
            />
          </label>
          {err ? <p className="text-xs text-[#dc2626]">{err}</p> : null}
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="rounded-lg border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50"
            >
              {tr("cases.cancel", "Cancel")}
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-sm text-white hover:bg-[#2563eb]/90 disabled:opacity-50"
            >
              {busy ? tr("cases.creating", "Creating…") : tr("cases.create", "Create case")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
