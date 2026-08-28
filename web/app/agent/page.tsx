"use client";

import { useState } from "react";

import { ChatPanel } from "@/app/chat/page";
import { IntelPanel } from "@/app/intel/page";

export default function AgentPage() {
  const [tab, setTab] = useState<"chat" | "intel">("chat");
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <h1 className="text-lg font-semibold">研究 Agent</h1>
        <div className="ml-4 flex rounded-md border border-border p-0.5">
          {(
            [
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
          {tab === "chat" ? "只读工具集 + 在线检索（离线时降级聚合）" : "Scout→Cartographer→Red Team ACH→Chief Analyst"}
        </span>
      </div>
      {tab === "chat" ? <ChatPanel /> : <IntelPanel />}
    </div>
  );
}
