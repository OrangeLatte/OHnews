"use client";

/**
 * 新建采集计划 stepper：① 选源（搜索 + 多选 + 已选 chips）→ ② mode/schedule →
 * ③ 确认创建。当前步高亮 + 完成步 ✓ + 可回退；创建为写操作（HITL），
 * 提交前在确认步显式列出内容。
 */

import { useMemo, useState } from "react";
import { createCollectionPlan, type CollectionPlanRow, type SourceRow } from "@/lib/landscape-api";
import { toast } from "@/components/ui/toast";
import { StepHeader, type Tr } from "./sources-ui";

const MODES: CollectionPlanRow["mode"][] = ["realtime", "scheduled", "backfill"];

const MODE_EN: Record<CollectionPlanRow["mode"], string> = {
  realtime: "Realtime",
  scheduled: "Scheduled",
  backfill: "Backfill",
};

const MODE_ZH: Record<CollectionPlanRow["mode"], string> = {
  realtime: "实时",
  scheduled: "定时",
  backfill: "回补",
};

function XIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      className="size-3"
      aria-hidden="true"
    >
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

export function PlanWizard({
  sources,
  tr,
  zh,
  onCreated,
  onCancel,
}: {
  sources: SourceRow[];
  tr: Tr;
  zh: boolean;
  onCreated: (p: CollectionPlanRow) => void;
  onCancel: () => void;
}) {
  const [step, setStep] = useState(0);
  const [picked, setPicked] = useState<string[]>([]);
  const [pickQ, setPickQ] = useState("");
  const [mode, setMode] = useState<CollectionPlanRow["mode"]>("scheduled");
  const [schedule, setSchedule] = useState("6h");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const candidates = useMemo(() => {
    const needle = pickQ.trim().toLowerCase();
    if (!needle) return sources;
    return sources.filter((s) => s.source_id.toLowerCase().includes(needle));
  }, [sources, pickQ]);

  const togglePick = (id: string): void => {
    setPicked((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const submit = (): void => {
    if (picked.length === 0) {
      setErr(tr("sources.planNeedSource", "Pick at least one source."));
      setStep(0);
      return;
    }
    setBusy(true);
    setErr("");
    createCollectionPlan({ source_ids: picked, mode, schedule: schedule.trim() })
      .then((p) => {
        setBusy(false);
        toast.success(tr("sources.planCreated", "Plan created"));
        onCreated(p);
      })
      .catch((e: unknown) => {
        setBusy(false);
        setErr(e instanceof Error ? e.message : String(e));
      });
  };

  const steps = [
    tr("sources.stepSources", "Pick sources"),
    tr("sources.stepMode", "Mode & schedule"),
    tr("sources.stepConfirm", "Confirm"),
  ];

  return (
    <div className="rounded-xl border p-4">
      <div className="flex items-center justify-between gap-2">
        <StepHeader steps={steps} current={step} onBack={(s) => setStep(s)} />
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border px-2 py-0.5 text-xs hover:bg-muted"
        >
          {tr("sources.cancel", "Cancel")}
        </button>
      </div>

      {step === 0 ? (
        <div className="mt-3 space-y-2">
          <input
            value={pickQ}
            onChange={(e) => setPickQ(e.target.value)}
            placeholder={tr("sources.pickSearch", "Search sources…")}
            aria-label={tr("sources.pickSearch", "Search sources…")}
            className="w-full rounded-lg border px-3 py-1.5 text-sm outline-none focus:border-[#2563eb]"
          />
          <div className="max-h-56 space-y-0.5 overflow-y-auto rounded-lg border p-1">
            {candidates.map((s) => (
              <label
                key={s.source_id}
                className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-xs hover:bg-muted"
              >
                <input
                  type="checkbox"
                  checked={picked.includes(s.source_id)}
                  onChange={() => togglePick(s.source_id)}
                />
                <span className="font-mono">{s.source_id}</span>
                <span className="text-muted-foreground">
                  {s.tier} · {s.kind} · {s.language.toUpperCase()}
                </span>
              </label>
            ))}
            {candidates.length === 0 ? (
              <p className="px-2 py-3 text-xs text-muted-foreground">
                {tr("sources.pickNoMatch", "No source matches this search.")}
              </p>
            ) : null}
          </div>
          {picked.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-muted-foreground">
                {tr("sources.selectedChips", "Selected ({n})", { n: picked.length })}:
              </span>
              {picked.map((id) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => togglePick(id)}
                  className="inline-flex items-center gap-1 rounded-full bg-[#2563eb]/10 px-2 py-0.5 font-mono text-[11px] text-[#2563eb] hover:bg-[#2563eb]/20"
                  title={tr("sources.removeSource", "Remove")}
                >
                  {id}
                  <XIcon />
                </button>
              ))}
            </div>
          ) : null}
          {err ? <p className="text-xs text-[#dc2626]">{err}</p> : null}
          <div className="flex justify-end">
            <button
              type="button"
              disabled={picked.length === 0}
              onClick={() => {
                setErr("");
                setStep(1);
              }}
              className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-sm text-white hover:bg-[#2563eb]/90 disabled:opacity-50"
            >
              {tr("sources.next", "Next")}
            </button>
          </div>
        </div>
      ) : null}

      {step === 1 ? (
        <div className="mt-3 space-y-3">
          <div>
            <p className="mb-1 text-xs font-medium">{tr("sources.mode", "Mode")}</p>
            <div className="flex flex-wrap gap-1">
              {MODES.map((m) => (
                <button
                  key={m}
                  type="button"
                  aria-pressed={mode === m}
                  onClick={() => setMode(m)}
                  className={`rounded-lg border px-3 py-1.5 text-xs ${
                    mode === m
                      ? "border-[#2563eb] bg-[#2563eb]/10 font-medium text-[#2563eb]"
                      : "hover:bg-muted"
                  }`}
                >
                  {zh ? MODE_ZH[m] : MODE_EN[m]}
                </button>
              ))}
            </div>
          </div>
          <label className="block text-xs">
            <span className="font-medium">{tr("sources.schedule", "Schedule")}</span>
            <input
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              placeholder="6h"
              className="mt-1 w-40 rounded-lg border px-3 py-1.5 text-sm outline-none focus:border-[#2563eb]"
            />
            <span className="ml-2 text-[11px] text-muted-foreground">
              {tr("sources.scheduleHint", "e.g. 6h / 1d / cron text")}
            </span>
          </label>
          <div className="flex justify-between">
            <button
              type="button"
              onClick={() => setStep(0)}
              className="rounded-lg border px-3 py-1.5 text-sm hover:bg-muted"
            >
              {tr("sources.stepBack", "Back")}
            </button>
            <button
              type="button"
              onClick={() => setStep(2)}
              className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-sm text-white hover:bg-[#2563eb]/90"
            >
              {tr("sources.next", "Next")}
            </button>
          </div>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="mt-3 space-y-3">
          <div className="rounded-lg bg-muted/50 p-3 text-xs">
            <p className="font-medium">{tr("sources.planSummaryTitle", "Review")}</p>
            <p className="mt-1">
              {tr("sources.planSummary", "{n} sources · {mode} · {schedule}", {
                n: picked.length,
                mode: zh ? MODE_ZH[mode] : MODE_EN[mode],
                schedule: schedule.trim() || "—",
              })}
            </p>
            <p className="mt-1 font-mono text-[11px] text-muted-foreground">
              {picked.slice(0, 12).join(", ")}
              {picked.length > 12 ? ` +${picked.length - 12}` : ""}
            </p>
          </div>
          {err ? <p className="text-xs text-[#dc2626]">{err}</p> : null}
          <div className="flex justify-between">
            <button
              type="button"
              onClick={() => setStep(1)}
              className="rounded-lg border px-3 py-1.5 text-sm hover:bg-muted"
            >
              {tr("sources.stepBack", "Back")}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={submit}
              className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-sm text-white hover:bg-[#2563eb]/90 disabled:opacity-50"
            >
              {busy ? tr("sources.creating", "Creating…") : tr("sources.create", "Create plan")}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
