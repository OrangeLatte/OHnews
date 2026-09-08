"use client";

/**
 * 扩展向导三步 stepper：① URL 输入 + 校验 → ② 建议预览（id/adapter/tier/language
 * + rationale，tier 可改）→ ③ 确认注册。409 冲突给友好提示（去目录搜索确认）。
 * suggest 是启发式只读；register 才是写操作（HITL 确认步）。
 */

import { useState } from "react";
import { HelpIcon } from "@/components/help/help-icon";
import {
  registerSource,
  suggestSource,
  type SourceSuggestion,
} from "@/lib/landscape-api";
import { toast } from "@/components/ui/toast";
import { StepHeader, validHttpUrl, useTr } from "./sources-ui";

const TIERS = ["L1", "L2", "L3", "L4"];

export function ExtendWizard({ onRegistered }: { onRegistered: () => void }) {
  const tr = useTr();
  const [step, setStep] = useState(0);
  const [url, setUrl] = useState("");
  const [draft, setDraft] = useState<SourceSuggestion | null>(null);
  const [rationale, setRationale] = useState("");
  const [preview, setPreview] = useState<Record<string, string> | null>(null);
  const [agentMeta, setAgentMeta] = useState<{ engine?: string; status?: string; model?: string; confidence?: number; error?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const steps = [
    tr("sources.wizardStepUrl", "Paste URL"),
    tr("sources.wizardStepReview", "Review suggestion"),
    tr("sources.wizardStepRegister", "Register"),
  ];

  const reset = (): void => {
    setStep(0);
    setDraft(null);
    setRationale("");
    setAgentMeta(null);
    setErr("");
  };

  const analyze = (): void => {
    const u = url.trim();
    if (!validHttpUrl(u)) {
      setErr(tr("sources.wizardUrlInvalid", "Enter a valid http(s) URL."));
      return;
    }
    setBusy(true);
    setErr("");
    suggestSource(u)
      .then((res) => {
        setDraft(res.suggestion);
        setRationale(res.rationale);
        setPreview(res.preview ?? null);
        setAgentMeta({
          engine: res.engine,
          status: res.agent_status,
          model: res.model_hint,
          confidence: res.confidence,
          error: res.agent_error,
        });
        setBusy(false);
        setStep(1);
      })
      .catch((e: unknown) => {
        setBusy(false);
        setErr(e instanceof Error ? e.message : String(e));
      });
  };

  const register = (): void => {
    if (!draft) return;
    setBusy(true);
    setErr("");
    registerSource(draft)
      .then(() => {
        setBusy(false);
        toast.success(tr("sources.wizardRegistered", "Registered: {id}", { id: draft.source_id }));
        reset();
        setUrl("");
        onRegistered();
      })
      .catch((e: unknown) => {
        setBusy(false);
        const msg = e instanceof Error ? e.message : String(e);
        setErr(
          msg.includes("409")
            ? tr(
                "sources.wizardConflict",
                "This source is already registered (409). Search the directory above to confirm.",
              )
            : msg,
        );
      });
  };

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-base font-semibold">
          {tr("sources.wizardTitle", "Extend wizard (URL → suggestion → confirm)")}
        </h2>
        <HelpIcon helpKey="agent.hitl" />
      </div>

      <div className="rounded-xl border p-4">
        <StepHeader steps={steps} current={step} onBack={step === 2 ? (s) => setStep(s) : undefined} />

        {step === 0 ? (
          <div className="mt-3 space-y-2">
            <div className="flex flex-wrap gap-2">
              <input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://example.com/rss.xml"
                aria-label={tr("sources.wizardUrl", "Paste source URL")}
                className="min-w-64 flex-1 rounded-lg border px-3 py-1.5 text-sm outline-none focus:border-[#2563eb]"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !busy) analyze();
                }}
              />
              <button
                type="button"
                onClick={analyze}
                disabled={busy}
                className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-sm text-white hover:bg-[#2563eb]/90 disabled:opacity-50"
              >
                {busy ? tr("sources.analyzing", "Analyzing…") : tr("sources.wizardStart", "Analyze URL")}
              </button>
            </div>
            <p className="text-[11px] text-muted-foreground">
              {tr(
                "sources.wizardUrlHint",
                "The Agent proposes a source profile from the URL; rule fallback is disclosed. Nothing is registered until you confirm.",
              )}
            </p>
            {err ? <p className="text-xs text-[#dc2626]">{err}</p> : null}
          </div>
        ) : null}

        {step === 1 && draft ? (
          <div className="mt-3 space-y-3">
            <div className="grid gap-2 rounded-lg bg-muted/50 p-3 text-xs sm:grid-cols-2">
              <p>
                <span className="text-muted-foreground">{tr("sources.id", "Source")}: </span>
                <span className="font-mono font-semibold">{draft.source_id}</span>
              </p>
              <p>
                <span className="text-muted-foreground">{tr("sources.wizardAdapter", "Adapter")}: </span>
                <span className="rounded-md bg-[#dbeafe] px-1.5 py-0.5 font-mono text-[11px] text-[#2563eb]">
                  {draft.adapter}
                </span>
              </p>
              <p>
                <span className="text-muted-foreground">{tr("sources.language", "Language")}: </span>
                <span className="uppercase">{draft.language}</span>
              </p>
              <label className="flex items-center gap-2">
                <span className="text-muted-foreground">{tr("sources.tier", "Tier")}:</span>
                <select
                  value={draft.tier}
                  onChange={(e) => setDraft({ ...draft, tier: e.target.value })}
                  className="rounded-md border px-2 py-0.5 text-xs"
                  aria-label={tr("sources.tier", "Tier")}
                >
                  {TIERS.map((x) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {rationale ? (
              <p className="text-xs text-muted-foreground">
                <span className="font-medium">{tr("sources.wizardRationale", "Why this suggestion")}: </span>
                {rationale}
              </p>
            ) : null}
            {agentMeta ? (
              <p className="text-[11px] text-muted-foreground">
                {agentMeta.engine === "llm"
                  ? `Agent analysis · ${agentMeta.model ?? "model"}${typeof agentMeta.confidence === "number" ? ` · confidence ${(agentMeta.confidence * 100).toFixed(0)}%` : ""}`
                  : `Rule fallback · ${agentMeta.error ?? "Agent result unavailable"}`}
              </p>
            ) : null}
            {preview ? (
              <ul className="space-y-1 rounded-lg border border-dashed bg-muted/30 p-3 text-xs text-muted-foreground">
                {Object.entries(preview).map(([k, v]) => (
                  <li key={k}>{v}</li>
                ))}
              </ul>
            ) : null}
            {err ? <p className="text-xs text-[#dc2626]">{err}</p> : null}
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

        {step === 2 && draft ? (
          <div className="mt-3 space-y-3">
            <div className="rounded-lg bg-muted/50 p-3 text-xs">
              <p className="font-medium">{tr("sources.wizardConfirmTitle", "Confirm registration")}</p>
              <p className="mt-1">
                <span className="font-mono">{draft.source_id}</span> · {draft.adapter} ·{" "}
                {draft.tier} · {draft.language.toUpperCase()}
              </p>
              <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                {draft.params.url}
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
                onClick={register}
                className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-sm text-white hover:bg-[#2563eb]/90 disabled:opacity-50"
              >
                {busy ? tr("sources.registering", "Registering…") : tr("sources.register", "Confirm register")}
              </button>
            </div>
          </div>
        ) : null}

        {step === 1 && !draft ? (
          <p className="mt-3 text-xs text-muted-foreground">
            {tr("sources.wizardNoSuggestion", "No suggestion yet. Go back and analyze a URL first.")}
          </p>
        ) : null}
      </div>
    </section>
  );
}
