"use client";

/**
 * Agent Bridge：Signal/Drawer 等任意页面位置 → 全局 Agent Dock 的模块级桥。
 * 用模块状态而非 window CustomEvent：调用方在任何时刻（含 Dock 未水合时）
 * 调 openAgent 都会把请求留在桥上，Dock 挂载后消费——无水合时机竞态，
 * 重复调用只更新请求（不创建线程；线程仅在实际发送消息时创建）。
 */

export type AgentRequest = {
  message: string;
  change_id?: string;
  subject?: string;
  window?: string;
  jsd?: number | null;
  warnings?: number;
};

type BridgeState = {
  /** Dock 应展开的请求序号（每次 openAgent 递增） */
  seq: number;
  request: AgentRequest | null;
};

let state: BridgeState = { seq: 0, request: null };
const listeners = new Set<() => void>();

function notify(): void {
  for (const cb of listeners) cb();
}

export function subscribeAgentBridge(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function getAgentBridge(): BridgeState {
  return state;
}

/** 打开全局 Agent 并预填上下文；重复点击仅覆盖请求（seq 递增），Dock 按 seq 幂等消费，不创建线程 */
export function openAgent(req: AgentRequest): void {
  state = { seq: state.seq + 1, request: req };
  notify();
}
