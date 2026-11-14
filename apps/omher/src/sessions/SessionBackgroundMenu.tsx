import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { openNewSessionMenu } from "./newMenu";

/** A background-only entry to the existing + chooser. Opening either menu starts nothing. */
export function SessionBackgroundMenu({ at, onClose }: { at: { x: number; y: number; focus: HTMLElement }; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ x: at.x, y: at.y });
  useLayoutEffect(() => {
    const fit = () => {
      const el = ref.current;
      if (!el) return;
      const right = Math.min(innerWidth, el.closest(".side")?.getBoundingClientRect().right ?? innerWidth);
      setPosition({ x: Math.max(6, Math.min(at.x, right - el.offsetWidth - 6)), y: Math.max(6, Math.min(at.y, innerHeight - el.offsetHeight - 6)) });
    };
    fit();
    addEventListener("resize", fit);
    return () => removeEventListener("resize", fit);
  }, [at]);
  useEffect(() => {
    ref.current?.querySelector("button")?.focus({ preventScroll: true });
    const outside = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    document.addEventListener("pointerdown", outside, true);
    return () => document.removeEventListener("pointerdown", outside, true);
  }, [onClose]);
  const dismiss = () => {
    onClose();
    at.focus.focus({ preventScroll: true });
  };
  return (
    <div
      ref={ref}
      className="row-menu"
      role="menu"
      aria-label={t("sessions.new")}
      data-testid="sessions-context-menu"
      style={{ left: position.x, top: position.y, maxWidth: "calc(100vw - 12px)" }}
      onContextMenu={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === "Escape" || e.key === "Tab") {
          if (e.key === "Escape") e.preventDefault();
          e.stopPropagation();
          dismiss();
        } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
          e.preventDefault();
          ref.current?.querySelector("button")?.focus();
        }
      }}
    >
      <button
        type="button"
        role="menuitem"
        className="row-mi"
        onClick={() => {
          onClose();
          openNewSessionMenu();
        }}
      >
        {t("sessions.new")}
      </button>
    </div>
  );
}
