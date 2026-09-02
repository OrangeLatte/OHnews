"use client";

/**
 * AgentDock 卡片协议（A4）：六类卡渲染，数据由会话事件流（Phase B 接入）驱动。
 * confirm 卡的决策回调由父层注入；其余卡片纯展示。
 */

export type AgentCard =
  | { kind: "node_progress"; node: string; status: "running" | "done" | "retry"; seq: number }
  | { kind: "tool_call"; tool: string; args: string; result: string; ms: number }
  | { kind: "checkpoint"; node: string; tokens: number; at: string; canFork: boolean }
  | { kind: "confirm"; action: string; detail?: string; onConfirm: (ok: boolean) => void }
  | { kind: "user_gate_echo"; text: string; scope?: string }
  | { kind: "report"; title: string; sections: { heading: string; body: string }[]; refs?: string[] };

const NODE_ZH: Record<string, string> = {
  running: "运行中",
  done: "已完成",
  retry: "重试中",
};

export function DockCard({ card }: { card: AgentCard }) {
  switch (card.kind) {
    case "node_progress":
      return (
        <div className="ag-card ag-node" data-status={card.status}>
          <span className="ag-node-dot" aria-hidden />
          <span className="ag-node-name">{card.node}</span>
          <span className="ag-node-status">{NODE_ZH[card.status]}</span>
        </div>
      );
    case "tool_call":
      return (
        <details className="ag-card ag-tool">
          <summary>
            工具 <b>{card.tool}</b> · {card.ms}ms
          </summary>
          <p className="ag-tool-args">{card.args}</p>
          <p className="ag-tool-result">{card.result}</p>
        </details>
      );
    case "checkpoint":
      return (
        <div className="ag-card ag-checkpoint">
          <span>
            检查点 {card.node} · {card.tokens} tokens
          </span>
          <button type="button" className="ag-mini" disabled={!card.canFork}>
            从此重跑
          </button>
        </div>
      );
    case "confirm":
      return (
        <div className="ag-card ag-confirm" role="alertdialog" aria-label={card.action}>
          <p className="ag-confirm-title">{card.action}</p>
          {card.detail && <p className="ag-confirm-detail">{card.detail}</p>}
          <div className="ag-confirm-row">
            <button type="button" className="ag-mini ag-ok" onClick={() => card.onConfirm(true)}>
              确认
            </button>
            <button type="button" className="ag-mini" onClick={() => card.onConfirm(false)}>
              取消
            </button>
          </div>
        </div>
      );
    case "user_gate_echo":
      return (
        <div className="ag-card ag-echo">
          <p>已采纳你的补充：{card.text}</p>
          {card.scope && <p className="ag-echo-scope">影响范围：{card.scope}</p>}
        </div>
      );
    case "report":
      return (
        <div className="ag-card ag-report">
          <p className="ag-report-title">{card.title}</p>
          {card.sections.map((sec) => (
            <details key={sec.heading} className="ag-report-sec">
              <summary>{sec.heading}</summary>
              <p>{sec.body}</p>
            </details>
          ))}
          {card.refs && card.refs.length > 0 && (
            <p className="ag-report-refs">{card.refs.join(" · ")}</p>
          )}
        </div>
      );
    default:
      return null;
  }
}
