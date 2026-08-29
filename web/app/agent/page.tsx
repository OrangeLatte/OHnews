"use client";

import { useEffect, useState } from "react";

import { ChatPanel } from "@/app/chat/page";
import { IntelPanel } from "@/app/intel/page";
import { IntentPanel } from "@/app/agent/intent-panel";

export default function AgentPage() {
  const [tab, setTab] = useState<"intent" | "chat" | "intel">("intent");

  useEffect(() => {
    // URL 带 intent 参数（Today 卡「Ask Analyst」）时落在分析师 tab
    const sp = new URLSearchParams(window.location.search);
    if (sp.get("intent")) setTab("intent");
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <h1 className="text-lg font-semibold">研究 Agent</h1>
        <div className="ml-4 flex rounded-md border border-border p-0.5">
          {(
            [
              ["intent", "分析师"],
              ["chat", "研究对话"],
              ["intel", "情报巡逻"],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setTab(k)}
              className={`rounded px-3 py-1 text-sm transition-colors ${
                tab === k ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-muted-foreground">
          {tab === "intent"
            ? "Intent → ContextPacket → 五层 Artifact"
            : tab === "chat"
              ? "只读工具集 + 在线检索（离线时降级聚合）"
              : "Scout→Cartographer→Red Team ACH→Chief Analyst"}
        </span>
      </div>
      {tab === "intent" ? <IntentPanel /> : tab === "chat" ? <ChatPanel /> : <IntelPanel />}
    </div>
  );
}
