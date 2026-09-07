"use client";

/**
 * HelpIcon（Clean-slate Phase 1）：全站统一圆圈"？"解释图标。
 * 交互：桌面 hover/focus 打开；点击固定（pinned，鼠标移开仍显示）；Esc/外点/再点关闭。
 * 可访问性：≥32px 触达区、aria-label、aria-expanded、aria-describedby、键盘可达。
 * 语言跟随 UI Locale（经 useT）；解释内容来自 lib/help/registry。
 */

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import {
  helpDefinition,
  type HelpDefinition,
} from "@/lib/help/registry";
import { useT } from "@/lib/i18n/use-t";

/**
 * 弹层经 Portal 渲染到 body：外层容器可能是 <p> 等只能含 phrasing 内容的元素，
 * inline 渲染 div/p 会产生非法 DOM 嵌套与 hydration error（第十一轮验收 P0-1）。
 */
function HelpPopover({
  def,
  descId,
  onClose,
  anchor,
  triggerRef,
}: {
  def: HelpDefinition;
  descId: string;
  onClose: () => void;
  anchor: { top: number; left: number } | null;
  triggerRef: RefObject<HTMLButtonElement | null>;
}) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    function onDown(e: MouseEvent) {
      const node = e.target as Node;
      if (ref.current?.contains(node)) return;
      if (triggerRef.current?.contains(node)) return;
      onClose();
    }
    function onScroll() {
      onClose();
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", onScroll);
    };
  }, [onClose, triggerRef]);

  if (anchor === null) return null;
  const style: React.CSSProperties = {
    position: "fixed",
    top: Math.max(8, anchor.top),
    left: anchor.left,
    zIndex: 60,
  };

  return createPortal(
    <div
      ref={ref}
      id={descId}
      role="dialog"
      aria-label={t(def.short)}
      style={style}
      className="w-80 max-w-[90vw] rounded-lg border bg-white p-3 text-sm shadow-lg"
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
    </div>,
    document.body,
  );
}

export function HelpIcon({ helpKey }: { helpKey: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const pinnedRef = useRef(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(
    null,
  );

  const computeAnchor = useCallback(() => {
    const r = btnRef.current?.getBoundingClientRect();
    if (!r) return;
    // 弹层 320px 宽；优先右对齐触发器，右缘溢出时左移。
    const left = Math.min(
      Math.max(8, r.right - 320),
      Math.max(8, window.innerWidth - 328),
    );
    setAnchor({ top: r.bottom + 8, left });
  }, []);

  const setPin = useCallback((v: boolean) => {
    pinnedRef.current = v;
    setPinned(v);
  }, []);
  const closeAll = useCallback(() => {
    pinnedRef.current = false;
    setPinned(false);
    setOpen(false);
  }, []);
  const [def, setDef] = useState<HelpDefinition | null>(null);
  const descId = useId();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    setDef(helpDefinition(helpKey) ?? null);
    computeAnchor();
    setOpen(true);
  }, [helpKey, computeAnchor]);

  const hide = useCallback(() => {
    if (pinnedRef.current) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setOpen(false), 120);
  }, []);

  const toggle = useCallback(() => {
    setOpen((v) => {
      const next = !v;
      setPin(next);
      if (next) {
        setDef(helpDefinition(helpKey) ?? null);
        computeAnchor();
      }
      return next;
    });
  }, [helpKey, setPin, computeAnchor]);

  return (
    <span className="relative inline-flex align-middle">
      <button
        ref={btnRef}
        type="button"
        aria-label={t("help.icon.aria", { k: helpKey })}
        aria-describedby={open ? descId : undefined}
        aria-expanded={open}
        aria-pressed={pinned}
        className="inline-flex h-8 w-8 min-w-8 min-h-8 items-center justify-center rounded-full border border-muted-foreground/40 text-xs font-semibold text-muted-foreground hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={toggle}
      >
        ?
      </button>
      {open &&
        def &&
        anchor !== null && (
          <HelpPopover
            def={def}
            descId={descId}
            onClose={closeAll}
            anchor={anchor}
            triggerRef={btnRef}
          />
        )}
    </span>
  );
}
