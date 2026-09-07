"use client";

/**
 * Agent System 深化区块（System tab 配置层，全部只读）：
 * - 工具清单：5 个 Case 工作流工具（语义对照 oh_agents/case_workflows.py W1/W3/W4/W5/W7）
 * - 中间件链：chat_graph 单轮 resolve_intent → context_injector → hitl_gate → 写操作确认门（P0-1）
 * - ResearchState 只读快照：caseId / 活跃文档数 / 活动 Run / 计划 Run / 待产物 / 错误数
 * - Prompt 版本：静态标注版本号（非内容哈希）
 * - 逐模型状态：/api/keys provider 级 configured 布尔 + /api/llm/health 的 EXECUTE tier 延迟
 * 诚实纪律：/api/keys 无 model 字段则不显示 model 列；ready 仅代表连通性检查通过。
 */

import { useEffect, useState } from "react";
import { useT } from "@/lib/i18n/use-t";
import { useResearchState } from "@/lib/research-state";

/** 工具名 → i18n 描述键后缀。 */
const TOOLS = [
  ["DissectDocument", "dissect"],
  ["CompareSources", "compare"],
  ["BuildReport", "report"],
  ["ChallengeClaim", "challenge"],
  ["ComposePressEdition", "press"],
] as const;

/** 中间件链步骤 → i18n 键后缀 + chat.py 内部函数名（title 展示）。 */
const CHAIN = [
  ["intent", "resolve_intent"],
  ["context", "context_injector"],
  ["hitl", "hitl_gate"],
  ["confirm", "confirm_gate"],
] as const;

type KeysStatus = { deepseek?: boolean; zhipu?: boolean; tavily?: boolean; llm_ready?: boolean };

type LlmHealth = { ready?: boolean; detail?: string; latency_ms?: number; checked_at?: string };

export function AgentSystemExtra() {
  const t = useT();
  const rs = useResearchState();
  const [keys, setKeys] = useState<KeysStatus | null>(null);
  const [health, setHealth] = useState<LlmHealth | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    Promise.all([
      fetch("/api/keys", { cache: "no-store" }).then((r) => {
        if (!r.ok) throw new Error(`keys: HTTP ${r.status}`);
        return r.json() as Promise<KeysStatus>;
      }),
      fetch("/api/llm/health", { cache: "no-store" }).then((r) => {
        if (!r.ok) throw new Error(`llm/health: HTTP ${r.status}`);
        return r.json() as Promise<LlmHealth>;
      }),
    ])
      .then(([k, h]) => {
        if (alive) {
          setKeys(k);
          setHealth(h);
        }
      })
      .catch((e: unknown) => {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  const providers: { id: string; on: boolean | undefined }[] = keys
    ? [
        { id: "deepseek", on: keys.deepseek },
        { id: "zhipu", on: keys.zhipu },
        { id: "tavily", on: keys.tavily },
      ]
    : [];

  return (
    <section className="space-y-3 rounded border p-2" aria-label={t("agentSys.title")}>
      <p className="font-medium">{t("agentSys.title")}</p>
      {err ? <p className="break-all text-red-600">{err}</p> : null}

      {/* 工具清单（静态 5 工具，全只读语义） */}
      <div>
        <p className="mb-1 font-medium">{t("agentSys.tools")}</p>
        <ul className="space-y-0.5 text-muted-foreground">
          {TOOLS.map(([name, key]) => (
            <li key={name}>
              <span className="font-mono text-foreground">{name}</span> · {t(`agentSys.tool.${key}`)}
            </li>
          ))}
        </ul>
      </div>

      {/* 中间件链（意图路由 → 上下文注入 → HITL 闸门 → 写操作确认门） */}
      <div>
        <p className="mb-1 font-medium">{t("agentSys.middleware")}</p>
        <ol className="flex flex-wrap items-center gap-1">
          {CHAIN.map(([key, fn], i) => (
            <li key={key} className="flex items-center gap-1">
              {i > 0 ? (
                <span aria-hidden className="text-muted-foreground">
                  →
                </span>
              ) : null}
              <span className="rounded border px-1 py-0.5" title={fn}>
                {t(`agentSys.mw.${key}`)}
              </span>
            </li>
          ))}
        </ol>
      </div>

      {/* ResearchState 只读快照（空值诚实显示 —，不提供修改入口） */}
      <div>
        <p className="mb-1 font-medium">{t("agentSys.researchState")}</p>
        <p className="break-all text-muted-foreground">
          {t("agentSys.rs.summary", {
            case: rs.caseId || "—",
            docs: rs.activeDocumentIds.length,
            active: rs.activeRunId || "—",
            plan: rs.planRunId || "—",
            arts: rs.pendingArtifacts.length,
            errs: rs.errors.length,
          })}
        </p>
          {rs.agentContext ? (
            <p className="mt-1 break-all text-xs tabular-nums text-muted-foreground">
              {t("agentSys.rs.change", {
                change: rs.agentContext.change_id || "—",
                subject: rs.agentContext.subject || "—",
                window: rs.agentContext.window || "—",
                jsd: rs.agentContext.jsd == null ? "—" : rs.agentContext.jsd.toFixed(3),
                warns: rs.agentContext.warnings ?? 0,
              })}
            </p>
          ) : null}
      </div>

      {/* Prompt 版本（静态标注：版本号非哈希） */}
      <div>
        <p className="mb-1 font-medium">{t("agentSys.promptVersion")}</p>
        <p className="break-all text-muted-foreground">{t("agentSys.promptVersionValue")}</p>
      </div>

      {/* 逐模型状态：provider configured 布尔 + EXECUTE tier 连通性 */}
      <div>
        <p className="mb-1 font-medium">{t("agentSys.models")}</p>
        {keys === null && !err ? (
          <p className="text-muted-foreground">…</p>
        ) : (
          <ul className="space-y-0.5 text-muted-foreground">
            {providers.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-2">
                <span className="font-mono">{p.id}</span>
                <span>{p.on ? "✓" : t("agentSys.modelOff")}</span>
              </li>
            ))}
            <li className="flex items-start justify-between gap-2">
              <span className="font-mono">EXECUTE tier</span>
              <span className="break-all text-right">
                {health
                  ? `${health.ready ? "✓" : "✗"} · ${health.latency_ms ?? "—"}ms${
                      health.detail ? ` · ${health.detail}` : ""
                    }`
                  : "…"}
              </span>
            </li>
          </ul>
        )}
        {/* 诚实矛盾注解：ready=连通性检查通过，与运行期 TimeoutError 不矛盾 */}
        <p className="mt-1 text-[11px] text-muted-foreground">{t("agentSys.readyCaveat")}</p>
      </div>
    </section>
  );
}
