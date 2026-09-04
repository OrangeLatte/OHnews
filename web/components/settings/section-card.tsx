"use client";

/**
 * SETTINGS 区块卡：标题 + 右侧状态灯 + HelpIcon；区块间 24px、卡片 12px 圆角。
 */

import type { ReactNode } from "react";
import { HelpIcon } from "@/components/help/help-icon";
import { StatusDot, type Tone } from "@/components/monitors/bits";

export function SectionCard({
  title,
  tone,
  pulse = false,
  helpKey,
  actions,
  children,
}: {
  title: string;
  tone: Tone;
  pulse?: boolean;
  helpKey?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusDot tone={tone} pulse={pulse} />
        <h2 className="text-sm font-semibold">{title}</h2>
        {helpKey && <HelpIcon helpKey={helpKey} />}
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  );
}
