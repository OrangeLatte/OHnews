"use client";

/**
 * 轻量全局 toast：模块级 store + useSyncExternalStore 订阅。
 * success/error/info 三态，4s 自动消退，支持手动关闭。
 */

import { useSyncExternalStore } from "react";

export type ToastKind = "success" | "error" | "info";
export type ToastItem = { id: number; kind: ToastKind; text: string };

let items: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

const emit = () => listeners.forEach((l) => l());

const push = (kind: ToastKind, text: string) => {
  const item: ToastItem = { id: nextId++, kind, text };
  items = [...items, item];
  emit();
  setTimeout(() => dismiss(item.id), 4000);
};

export const dismiss = (id: number) => {
  items = items.filter((i) => i.id !== id);
  emit();
};

export const toast = {
  success: (text: string) => push("success", text),
  error: (text: string) => push("error", text),
  info: (text: string) => push("info", text),
};

const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => listeners.delete(cb);
};

const getSnapshot = () => items;

const KIND_STYLE: Record<ToastKind, string> = {
  success: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  error: "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300",
  info: "border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-300",
};

export function ToastViewport() {
  const list = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  if (list.length === 0) return null;
  return (
    <div
      className="pointer-events-none fixed bottom-4 right-4 z-50 flex max-w-sm flex-col gap-2"
      role="status"
      aria-live="polite"
    >
      {list.map((i) => (
        <div
          key={i.id}
          className={`motion-scale-in pointer-events-auto flex items-start gap-2 rounded-md border px-3 py-2 text-xs shadow-sm ${KIND_STYLE[i.kind]}`}
        >
          <span className="flex-1">{i.text}</span>
          <button
            type="button"
            onClick={() => dismiss(i.id)}
            aria-label="×"
            className="opacity-60 hover:opacity-100"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

/** 骨架屏：加载态占位（animate-pulse 灰块）。 */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-muted ${className}`} aria-hidden="true" />;
}
