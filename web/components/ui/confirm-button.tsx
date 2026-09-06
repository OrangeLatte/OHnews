"use client";

import { useEffect, useState, type ReactNode } from "react";

/**
 * 两击式确认按钮（HITL 写操作确认门的非阻塞实现）。
 *
 * 背景：window.confirm 是同步阻塞调用——自动化环境（Playwright/未处理 dialog）下
 * 会挂死整个页面 JS 主线程，表现为"点击超时、标签页失去响应、console 零报错"。
 * 本组件用两击模式替代：第一次点击进入 armed 态（按钮变为确认文案+警示样式，
 * resetMs 后自动回退），第二次点击才真正执行 onConfirm。确认语义等价（两段显式
 * 确认），但永不阻塞主线程、自动化可编程。
 */
export function ConfirmButton({
  onConfirm,
  children,
  confirmLabel,
  className = "",
  armedClassName = "",
  disabled = false,
  title,
  resetMs = 5000,
}: {
  onConfirm: () => void;
  /** 首态文案（原按钮内容） */
  children: ReactNode;
  /** armed 态文案（原 window.confirm 的问句，语义一致） */
  confirmLabel: string;
  className?: string;
  /** armed 态追加的警示样式（如红色描边） */
  armedClassName?: string;
  disabled?: boolean;
  title?: string;
  resetMs?: number;
}) {
  const [armed, setArmed] = useState(false);

  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), resetMs);
    return () => clearTimeout(t);
  }, [armed, resetMs]);

  return (
    <button
      type="button"
      disabled={disabled}
      title={title}
      aria-pressed={armed}
      className={`${className} ${armed ? armedClassName : ""}`.trim()}
      onClick={() => {
        if (armed) {
          setArmed(false);
          onConfirm();
        } else {
          setArmed(true);
        }
      }}
    >
      {armed ? confirmLabel : children}
    </button>
  );
}
