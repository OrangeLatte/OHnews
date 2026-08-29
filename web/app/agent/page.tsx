"use client";

import { useEffect, useState } from "react";

import { ChatPanel } from "@/app/chat/page";

export default function AgentPage() {
  const [apiStatus, setApiStatus] = useState<{ ok: boolean; offline?: boolean } | null>(null);
  const [sourceCount, setSourceCount] = useState<number | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(() => setApiStatus({ ok: true }))
      .catch(() => setApiStatus({ ok: false }));
    fetch("/api/sources")
      .then((r) => r.json())
      .then((d) => setSourceCount(d.n))
      .catch(() => undefined);
  }, []);

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <div className="min-w-0 flex-1">
        <div className="mb-3 flex items-baseline gap-3">
          <h1 className="font-paper text-2xl tracking-tight">研究台</h1>
          <p className="text-xs text-muted-foreground">
            与研究 Agent 对话完成检索、分析、比较与调查；重要结论可一键存入档案库
          </p>
        </div>
        <ChatPanel />
      </div>
      <aside className="w-full shrink-0 space-y-4 border-t border-foreground/15 pt-4 lg:w-72 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
        <section>
          <h2 className="paper-kicker mb-2 !text-[11px] !text-foreground">研究台配置</h2>
          <dl className="space-y-1.5 text-xs">
            <div className="flex justify-between">
              <dt className="text-muted-foreground">API 服务</dt>
              <dd>{apiStatus ? (apiStatus.ok ? "已连接" : "不可用") : "检测中…"}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">信息源</dt>
              <dd>{sourceCount ?? "—"} 个已配置</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">LLM 路由</dt>
              <dd>DeepSeek / GLM 三级</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">未配置 keys 时</dt>
              <dd>自动降级确定性聚合</dd>
            </div>
          </dl>
        </section>
        <section className="border-t border-border/60 pt-3">
          <h2 className="paper-kicker mb-2 !text-[11px] !text-foreground">后台工具</h2>
          <ul className="space-y-1 text-xs text-muted-foreground">
            <li>
              <a href="/intel" className="hover:text-foreground">情报巡逻（六角色循环）→</a>
            </li>
            <li>
              <a href="/alerts" className="hover:text-foreground">分位预警规则 →</a>
            </li>
            <li>
              <a href="/dev/monitor" className="hover:text-foreground">Dev 监控 →</a>
            </li>
          </ul>
        </section>
        <section className="border-t border-border/60 pt-3">
          <h2 className="paper-kicker mb-2 !text-[11px] !text-foreground">措辞纪律</h2>
          <p className="text-[11px] leading-5 text-muted-foreground">
            NDI = 叙事分歧指数（描述性监测，EPU 式条件变量，非收益预测器）。Agent
            输出遵循同一纪律：只读证据、引用来源、标注不确定性。
          </p>
        </section>
      </aside>
    </div>
  );
}
