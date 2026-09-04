"use client";

/**
 * HelpIcon（Clean-slate Phase 1）：全站统一圆圈"？"解释图标。
 * 交互：桌面 hover/focus 打开；移动端 tap 打开/外点关闭；Esc 关闭。
 * 可访问性：≥32px 触达区、aria-label、aria-expanded、aria-describedby、键盘可达。
 * 语言跟随 UI Locale（经 useT）；解释内容来自 lib/help/registry。
 */

import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  helpDefinition,
  type HelpDefinition,
} from "@/lib/help/registry";
import { useT } from "@/lib/i18n/use-t";

function HelpPopover({
  def,
  descId,
  onClose,
}: {
  def: HelpDefinition;
  descId: string;
  onClose: () => void;
}) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      id={descId}
      role="dialog"
      aria-label={t(def.short)}
      className="absolute z-50 top-full right-0 mt-2 w-80 max-w-[90vw] rounded-lg border bg-white p-3 text-sm shadow-lg"
    >
      <p className="font-medium">{t(def.short)}</p>
      <p className="mt-2 text-muted-foreground">{t(def.method)}</p>
      <p className="mt-2 text-amber-700">{t(def.limit)}</p>
      {def.example && (
        <p className="mt-2 text-muted-foreground italic">{t(def.example)}</p>
      )}
      <p className="mt-2 text-xs text-muted-foreground/70">
        {t("help.updatedAt", { t: def.updatedAt.slice(0, 10) })}
      </p>
    </div>
  );
}

export function HelpIcon({ helpKey }: { helpKey: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [def, setDef] = useState<HelpDefinition | null>(null);
  const descId = useId();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    setDef(helpDefinition(helpKey) ?? null);
    setOpen(true);
  }, [helpKey]);

  const hide = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setOpen(false), 120);
  }, []);

  const toggle = useCallback(() => {
    setOpen((v) => {
      if (!v) setDef(helpDefinition(helpKey) ?? null);
      return !v;
    });
  }, [helpKey]);

  return (
    <span className="relative inline-flex align-middle">
      <button
        type="button"
        aria-label={t("help.icon.aria", { k: helpKey })}
        aria-describedby={open ? descId : undefined}
        aria-expanded={open}
        className="inline-flex h-8 w-8 min-w-8 min-h-8 items-center justify-center rounded-full border border-muted-foreground/40 text-xs font-semibold text-muted-foreground hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={toggle}
      >
        ?
      </button>
      {open && def && <HelpPopover def={def} descId={descId} onClose={() => setOpen(false)} />}
    </span>
  );
}
