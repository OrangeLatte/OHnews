"use client";

/**
 * Chat 卡片组件库（阶段2 Agent OS）：渲染后端 chat 响应的 cards 数组
 * （{"type": "...", ...data}，数据形状以后端为准，字段一律弱类型诚实读取）。
 * 七类卡：tool_call / progress / artifact / hitl / runs_summary / observe_summary / case；
 * 未知 type 诚实渲染原始 JSON（不崩、不编造）。
 * HITL 卡内联 Approve/Reject → POST /api/hitl/{id}/decide body {status}
 * （契约真源 oh_api.object_api.HITLDecideIn，非 instruction 假设的 decision 字段）。
 */

import { useState } from "react";
import Link from "next/link";
import { useT } from "@/lib/i18n/use-t";
import { runKindLabel, runStatusLabel } from "@/lib/i18n/labels";

/** 后端 chat 响应卡片：type 判别 + 任意负载（网络数据不做强类型假设）。 */
export type CardData = { type: string } & Record<string, unknown>;

type TFn = (key: string, params?: Record<string, string | number>) => string;

/** 组件作用域禁 Date.now：相对时间/时间戳只出现在模块级函数中。 */
export function relTime(iso: string, t: TFn): string {
  const then = Date.parse(iso);
  if (!iso || Number.isNaN(then)) return iso || "—";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return t("observe.rel.s", { v: secs });
  const mins = Math.floor(secs / 60);
  if (mins < 60) return t("observe.rel.m", { v: mins });
  const hours = Math.floor(mins / 60);
  if (hours < 24) return t("observe.rel.h", { v: hours });
  const days = Math.floor(hours / 24);
  if (days < 31) return t("observe.rel.d", { v: days });
  return t("observe.rel.mo", { v: Math.floor(days / 30) });
}

function nowIso(): string {
  return new Date().toISOString();
}

/** 弱字段诚实读取（后端字段缺失/类型漂移时不崩）。 */
function str(v: unknown): string {
  if (typeof v === "string") return v;
  if (v === null || v === undefined) return "";
  return String(v);
}

/** 状态色点：running 蓝 / succeeded 绿 / failed 红 / abstained·awaiting 琥珀。 */
const STATUS_DOT: Record<string, string> = {
  running: "bg-blue-500",
  queued: "bg-muted-foreground/40",
  succeeded: "bg-green-500",
  failed: "bg-red-500",
  abstained: "bg-amber-500",
  awaiting_hitl: "bg-amber-500",
  cancelled: "bg-muted-foreground/40",
};

const STATUS_TEXT: Record<string, string> = {
  running: "text-blue-600 dark:text-blue-400",
  succeeded: "text-green-600 dark:text-green-400",
  failed: "text-red-600 dark:text-red-400",
  abstained: "text-amber-600 dark:text-amber-400",
  awaiting_hitl: "text-amber-600 dark:text-amber-400",
};

function StatusDot({ status }: { status: string }) {
  return (
    <span
      aria-hidden
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[status] ?? "bg-muted-foreground/40"}`}
    />
  );
}

function CardTitle({ label, extra }: { label: string; extra?: string }) {
  return (
    <p className="flex items-center gap-1.5">
      <span className="rounded bg-muted px-1 py-0.5 text-[10px] font-medium">{label}</span>
      {extra ? <span className="truncate text-muted-foreground">{extra}</span> : null}
    </p>
  );
}

function ToolCallCardView({ card, t }: { card: CardData; t: TFn }) {
  const tool = str(card.tool) || "—";
  const status = str(card.status);
  const detail = str(card.detail);
  return (
    <div className="ag-card ag-tool">
      <CardTitle label={t("chat.card.tool_call")} extra={tool} />
      <p className="mt-1 flex items-center gap-1.5 text-xs">
        <StatusDot status={status} />
        <span className={STATUS_TEXT[status] ?? "text-muted-foreground"}>
          {status ? runStatusLabel(t, status) : "—"}
        </span>
      </p>
      {detail ? <p className="mt-1 break-words text-muted-foreground">{detail}</p> : null}
    </div>
  );
}

function ProgressCardView({ card, t }: { card: CardData; t: TFn }) {
  const runId = str(card.run_id);
  const kind = str(card.kind);
  const status = str(card.status);
  return (
    <div className="ag-card ag-node" data-status={status}>
      <CardTitle label={t("chat.card.progress")} extra={kind ? runKindLabel(t, kind) : "—"} />
      <p className="mt-1 flex items-center gap-1.5 text-xs">
        <StatusDot status={status} />
        <span className={STATUS_TEXT[status] ?? "text-muted-foreground"}>
          {status ? runStatusLabel(t, status) : "—"}
        </span>
        {runId ? <span className="truncate font-mono text-[10px] text-muted-foreground">{runId}</span> : null}
      </p>
    </div>
  );
}

function ArtifactCardView({ card, t }: { card: CardData; t: TFn }) {
  const artifactId = str(card.artifact_id);
  const revisionId = str(card.revision_id);
  const [copied, setCopied] = useState(false);
  const copy = (): void => {
    if (!artifactId) return;
    navigator.clipboard
      .writeText(artifactId)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {
        /* 剪贴板不可用时静默：id 仍以文本展示 */
      });
  };
  return (
    <div className="ag-card">
      <CardTitle label={t("chat.card.artifact")} />
      <p className="mt-1 break-all font-mono text-xs">
        <button type="button" onClick={copy} className="underline decoration-dotted" title={t("chat.copyId")}>
          {artifactId || "—"}
        </button>
        {copied ? <span className="ml-1 text-green-600 dark:text-green-400">{t("chat.copied")}</span> : null}
      </p>
      {revisionId ? (
        <p className="mt-0.5 break-all font-mono text-[10px] text-muted-foreground">{revisionId}</p>
      ) : null}
    </div>
  );
}

type HitlState = "idle" | "sending" | "approved" | "rejected" | "error";

async function decideHitl(hitlId: string, status: "approved" | "rejected"): Promise<void> {
  const r = await fetch(`/api/hitl/${encodeURIComponent(hitlId)}/decide`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!r.ok) {
    const detail = (await r.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `HTTP ${r.status}`);
  }
}

function HitlCardView({ card, t }: { card: CardData; t: TFn }) {
  const hitlId = str(card.hitl_id);
  const summary = str(card.summary);
  const [state, setState] = useState<HitlState>("idle");
  const [errMsg, setErrMsg] = useState("");
  const decide = (status: "approved" | "rejected"): void => {
    if (!hitlId || state === "sending") return;
    setState("sending");
    setErrMsg("");
    decideHitl(hitlId, status)
      .then(() => setState(status))
      .catch((e: unknown) => {
        setState("error");
        setErrMsg(e instanceof Error ? e.message : String(e));
      });
  };
  const decided = state === "approved" || state === "rejected";
  return (
    <div className="ag-card ag-confirm" role="alertdialog" aria-label={summary || hitlId}>
      <CardTitle label={t("chat.card.hitl")} />
      {summary ? <p className="mt-1 break-words text-xs">{summary}</p> : null}
      <p className="mt-0.5 break-all font-mono text-[10px] text-muted-foreground">{hitlId}</p>
      {decided ? (
        <p className="mt-1 text-xs">
          {state === "approved" ? t("chat.hitlApproved") : t("chat.hitlRejected")}
        </p>
      ) : (
        <div className="ag-confirm-row">
          <button
            type="button"
            className="ag-mini ag-ok"
            disabled={state === "sending" || !hitlId}
            onClick={() => decide("approved")}
          >
            {t("agentPanel.approve")}
          </button>
          <button
            type="button"
            className="ag-mini"
            disabled={state === "sending" || !hitlId}
            onClick={() => decide("rejected")}
          >
            {t("agentPanel.reject")}
          </button>
        </div>
      )}
      {state === "error" ? <p className="mt-1 break-all text-xs text-red-600">{errMsg}</p> : null}
    </div>
  );
}

function RunsSummaryCardView({ card, t }: { card: CardData; t: TFn }) {
  const runs = Array.isArray(card.runs) ? card.runs : [];
  return (
    <div className="ag-card">
      <CardTitle label={t("chat.card.runs_summary")} extra={`(${runs.length})`} />
      {runs.length === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">{t("agentRuns.empty")}</p>
      ) : (
        <ul className="mt-1 space-y-0.5">
          {runs.map((raw, i) => {
            const r = (raw ?? {}) as Record<string, unknown>;
            const status = str(r.status);
            return (
              <li key={str(r.run_id) || `run-${i}`} className="flex items-center gap-1.5 text-xs">
                <StatusDot status={status} />
                <span className="truncate">
                  {str(r.kind) ? runKindLabel(t, str(r.kind)) : "—"}
                </span>
                <span className={STATUS_TEXT[status] ?? "text-muted-foreground"}>
                  {status ? runStatusLabel(t, status) : "—"}
                </span>
                <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                  {relTime(str(r.started_at), t)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** 观察摘要卡：字段形状未定，诚实逐键渲染（对象/数组折叠为 JSON 文本）。 */
function ObserveSummaryCardView({ card, t }: { card: CardData; t: TFn }) {
  const entries = Object.entries(card).filter(([k]) => k !== "type");
  return (
    <div className="ag-card">
      <CardTitle label={t("chat.card.observe_summary")} />
      {entries.length === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">—</p>
      ) : (
        <ul className="mt-1 space-y-0.5 text-xs">
          {entries.map(([k, v]) => (
            <li key={k} className="break-words">
              <span className="text-muted-foreground">{k}: </span>
              {typeof v === "string" || typeof v === "number" || typeof v === "boolean"
                ? String(v)
                : JSON.stringify(v)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CaseCardView({ card, t }: { card: CardData; t: TFn }) {
  const caseId = str(card.case_id);
  const question = str(card.question);
  if (!caseId) return <UnknownCardView card={card} t={t} />;
  return (
    <div className="ag-card">
      <CardTitle label={t("chat.card.case")} extra={caseId} />
      {question ? <p className="mt-1 break-words text-xs">{question}</p> : null}
      <Link
        href={`/cases/${encodeURIComponent(caseId)}`}
        className="mt-1 inline-block text-xs underline decoration-dotted"
      >
        {t("cases.openCase")} →
      </Link>
    </div>
  );
}

/** 未知 type：诚实渲染原始 JSON，不崩、不编造语义。 */
function UnknownCardView({ card, t }: { card: CardData; t: TFn }) {
  return (
    <div className="ag-card">
      <CardTitle label={t("chat.unknownCard")} extra={card.type} />
      <pre className="mt-1 max-h-40 overflow-auto break-all whitespace-pre-wrap text-[10px] text-muted-foreground">
        {JSON.stringify(card, null, 2)}
      </pre>
    </div>
  );
}

/** 写操作预览卡：确认后由 AgentDock 回发 confirmed_action 执行；取消仅本地消失。 */
function ConfirmActionCardView({
  card,
  t,
  onConfirm,
}: {
  card: CardData;
  t: TFn;
  onConfirm?: (message: string) => void;
}) {
  const [dismissed, setDismissed] = useState(false);
  const [busy, setBusy] = useState(false);
  const changes = Array.isArray(card.changes) ? (card.changes as string[]) : [];
  if (dismissed) return null;
  if (card.needs_confirmation === false) {
    return (
      <div className="ag-card border-amber-500/40 bg-amber-500/10">
        <CardTitle label={t("chat.readOnlyBadge")} />
      </div>
    );
  }
  return (
    <div className="ag-card border-amber-500/40 bg-amber-500/5">
      <CardTitle label={t("chat.card.confirmAction")} extra={typeof card.intent === "string" ? card.intent : undefined} />
      <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
        {changes.map((c) => (
          <li key={c}>· {c}</li>
        ))}
      </ul>
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            const msg = typeof card.message === "string" ? card.message : "";
            if (!msg || !onConfirm) return;
            setBusy(true);
            onConfirm(msg);
          }}
          className="rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground disabled:opacity-60"
        >
          {busy ? "…" : t("chat.confirmExec")}
        </button>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          className="rounded-md border px-2.5 py-1 text-xs"
        >
          {t("chat.confirmCancel")}
        </button>
      </div>
    </div>
  );
}

export function ChatCardView({
  card,
  onConfirm,
}: {
  card: CardData;
  onConfirm?: (message: string) => void;
}) {
  const t = useT();
  switch (card.type) {
    case "tool_call":
      return <ToolCallCardView card={card} t={t} />;
    case "progress":
      return <ProgressCardView card={card} t={t} />;
    case "artifact":
      return <ArtifactCardView card={card} t={t} />;
    case "hitl":
      return <HitlCardView card={card} t={t} />;
    case "runs_summary":
      return <RunsSummaryCardView card={card} t={t} />;
    case "observe_summary":
      return <ObserveSummaryCardView card={card} t={t} />;
    case "case":
      return <CaseCardView card={card} t={t} />;
    case "confirm_action":
      return <ConfirmActionCardView card={card} t={t} onConfirm={onConfirm} />;
    default:
      return <UnknownCardView card={card} t={t} />;
  }
}

/** 卡片流：cards 缺省/空时渲染 null（消息正文照常显示）。 */
export function CardList({
  cards,
  onConfirm,
}: {
  cards?: CardData[];
  onConfirm?: (message: string) => void;
}) {
  if (!cards || cards.length === 0) return null;
  return (
    <div className="mt-1 space-y-1">
      {cards.map((c, i) => (
        <ChatCardView key={`${c.type}-${i}`} card={c} onConfirm={onConfirm} />
      ))}
    </div>
  );
}

export { nowIso };
