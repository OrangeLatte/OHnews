"use client";

/**
 * ResearchState（阶段2 Agent OS，规格 4.2）：全局单一状态真源。
 * 模块级 state + listeners Set + useSyncExternalStore 订阅；
 * Agent Dock 五标签 / Case Workspace / 工作流启动方统一读写，
 * 禁止页面级重复不可追踪状态。SSR：getServerSnapshot 返回同一初始对象。
 */

import { useSyncExternalStore } from "react";

export type PendingArtifact = {
  artifact_id: string;
  revision_id: string;
  title: string;
};

export type ResearchState = {
  caseId: string;
  question: string;
  activeDocumentIds: string[];
  activeRevisionIds: string[];
  planRunId: string;
  activeRunId: string;
  pendingArtifacts: PendingArtifact[];
  errors: string[];
};

const INITIAL: ResearchState = {
  caseId: "",
  question: "",
  activeDocumentIds: [],
  activeRevisionIds: [],
  planRunId: "",
  activeRunId: "",
  pendingArtifacts: [],
  errors: [],
};

let state: ResearchState = INITIAL;
const listeners = new Set<() => void>();

function notify(): void {
  for (const cb of listeners) cb();
}

function update(patch: Partial<ResearchState>): void {
  state = { ...state, ...patch };
  notify();
}

export function subscribeResearchState(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function getResearchStateSnapshot(): ResearchState {
  return state;
}

export function getResearchStateServerSnapshot(): ResearchState {
  return INITIAL;
}

export function useResearchState(): ResearchState {
  return useSyncExternalStore(
    subscribeResearchState,
    getResearchStateSnapshot,
    getResearchStateServerSnapshot,
  );
}

export function setCaseContext(caseId: string, question: string): void {
  update({ caseId, question });
}

export function setActiveDocs(docIds: string[], revisionIds: string[]): void {
  update({ activeDocumentIds: docIds, activeRevisionIds: revisionIds });
}

export function setActiveRun(runId: string): void {
  update({ activeRunId: runId });
}

export function setPlanRun(runId: string): void {
  update({ planRunId: runId });
}

export function setPendingArtifacts(arts: PendingArtifact[]): void {
  update({ pendingArtifacts: arts });
}

export function pushError(msg: string): void {
  // 截断保留最近 20 条，避免长会话无限增长
  update({ errors: [...state.errors.slice(-19), msg] });
}

export function clearErrors(): void {
  update({ errors: [] });
}
