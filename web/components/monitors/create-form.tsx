"use client";

/**
 * 新建监测器表单（MONITORS 创建入口）。
 * target_type 取 oh-contracts MonitorTarget 十值闭集；entity/topic 必填 target_ref；
 * trigger_conditions 标签输入（回车成 chip，可删）；window/schedule 下拉闭集；
 * 提交前 window.confirm（HITL：写操作）；monitor_id 客户端生成 mon-{uuid8}。
 * 成功/失败均 toast；失败保留表单（根因随 toast 展示）。
 */

import { useState } from "react";
import { objectApi } from "@/lib/object-api";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import type { TFunc } from "./bits";
import { newMonitorId } from "./format";

/** oh-contracts monitoring.py MonitorTarget 闭集（十值）。 */
export const MONITOR_TARGETS = [
  "case",
  "entity",
  "topic",
  "question",
  "article",
  "claim",
  "stance",
  "sentiment",
  "action",
  "element",
] as const;

const REF_REQUIRED = new Set(["entity", "topic"]);
const WINDOWS = ["1d", "7d", "30d", "90d"] as const;
const SCHEDULES = ["6h", "12h", "1d"] as const;

const inputCls =
  "mt-1 w-full rounded-md border bg-card px-2 py-1 text-[13px] text-foreground";

export function CreateForm({
  t,
  onCreated,
  onClose,
}: {
  t: TFunc;
  onCreated: (monitorId: string) => void;
  onClose: () => void;
}) {
  const [targetType, setTargetType] = useState<string>("topic");
  const [targetRef, setTargetRef] = useState("");
  const [question, setQuestion] = useState("");
  const [triggers, setTriggers] = useState<string[]>([]);
  const [triggerDraft, setTriggerDraft] = useState("");
  const [win, setWin] = useState("7d");
  const [sched, setSched] = useState("6h");
  const [notification, setNotification] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refRequired = REF_REQUIRED.has(targetType);

  const addTrigger = () => {
    const v = triggerDraft.trim();
    setTriggerDraft("");
    if (!v || triggers.includes(v)) return;
    setTriggers((prev) => [...prev, v]);
  };

  const submit = () => {
    if (busy) return;
    if (!question.trim()) {
      setError(t("monitors.create.questionRequired"));
      return;
    }
    if (refRequired && !targetRef.trim()) {
      setError(t("monitors.create.refRequired"));
      return;
    }
    if (!window.confirm(t("monitors.create.confirm"))) return;
    setError("");
    setBusy(true);
    objectApi
      .createMonitor({
        monitor_id: newMonitorId(),
        target_type: targetType,
        target_ref: targetRef.trim(),
        question: question.trim(),
        trigger_conditions: triggers,
        window: win,
        schedule: sched,
        ...(notification.trim() ? { notification: notification.trim() } : {}),
      })
      .then((r) => {
        toast.success(t("monitors.create.success"));
        onCreated(r.monitor_id);
      })
      .catch((e: unknown) => {
        setBusy(false);
        const reason = e instanceof Error ? e.message : String(e);
        toast.error(`${t("monitors.create.failed")} — ${reason}`);
      });
  };

  return (
    <div className="rounded-xl border bg-card p-4">
      <h3 className="text-sm font-semibold">{t("monitors.create.title")}</h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block text-xs text-muted-foreground">
          {t("monitors.create.targetType")}
          <select
            value={targetType}
            onChange={(e) => setTargetType(e.target.value)}
            className={inputCls}
          >
            {MONITOR_TARGETS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-muted-foreground">
          {t("monitors.create.targetRef")}
          {refRequired && <span className="text-[#b45309]"> *</span>}
          <input
            value={targetRef}
            onChange={(e) => setTargetRef(e.target.value)}
            placeholder={refRequired ? "Fed / tariff…" : ""}
            className={inputCls}
          />
        </label>
        <label className="block text-xs text-muted-foreground sm:col-span-2">
          {t("monitors.question")} <span className="text-[#b45309]">*</span>
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            className={inputCls}
          />
        </label>
        <div className="text-xs text-muted-foreground sm:col-span-2">
          {t("monitors.create.triggers")}
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {triggers.map((tc) => (
              <span
                key={tc}
                className="inline-flex items-center gap-1 rounded-md border bg-secondary/60 px-1.5 py-0.5 text-xs text-secondary-foreground"
              >
                {tc}
                <button
                  type="button"
                  aria-label={`remove ${tc}`}
                  className="text-muted-foreground hover:text-foreground"
                  onClick={() => setTriggers((prev) => prev.filter((x) => x !== tc))}
                >
                  ×
                </button>
              </span>
            ))}
            <input
              value={triggerDraft}
              onChange={(e) => setTriggerDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addTrigger();
                }
              }}
              placeholder="ndi_slope>0.5"
              className="min-w-40 flex-1 rounded-md border bg-card px-2 py-1 text-[13px] text-foreground"
            />
          </div>
        </div>
        <label className="block text-xs text-muted-foreground">
          {t("monitors.window")}
          <select value={win} onChange={(e) => setWin(e.target.value)} className={inputCls}>
            {WINDOWS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-muted-foreground">
          {t("monitors.schedule")}
          <select value={sched} onChange={(e) => setSched(e.target.value)} className={inputCls}>
            {SCHEDULES.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-muted-foreground sm:col-span-2">
          {t("monitors.create.notification")}
          <input
            value={notification}
            onChange={(e) => setNotification(e.target.value)}
            className={inputCls}
          />
        </label>
      </div>
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
      <div className="mt-3 flex gap-2">
        <Button size="sm" disabled={busy} onClick={submit}>
          {t("monitors.create.submit")}
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={onClose}>
          {t("monitors.cancel")}
        </Button>
        {busy && <span className="self-center text-xs text-muted-foreground">…</span>}
      </div>
    </div>
  );
}
