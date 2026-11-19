import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { openNewSessionMenu } from "./newMenu";
import { useStore } from "../state/store";
import { useSessions } from "./sessions";
import { isTerminalRec } from "./agents";
import { openSplitPicker } from "./SplitView";

/** A background-only entry to the existing + chooser, and, while a TERMINALS session is open, "Split right with…"
 *  (the picker of the other TERMINALS sessions to show beside it). Opening either menu starts nothing. */
export function SessionBackgroundMenu({ at, onClose }: { at: { x: number; y: number; focus: HTMLElement }; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const ui = useStore().ui;
  const ss = useSessions();
  const open = ui.view === "session" ? ss.list.find((r) => r.id === ui.session) : undefined;
  const canSplit = !!open && isTerminalRec(ss.agents, open);
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
          const items = [...(ref.current?.querySelectorAll<HTMLElement>("button") ?? [])];
          const at = items.indexOf(document.activeElement as HTMLElement);
          const to = e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : (at + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
          items[to]?.focus();
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
      {canSplit && (
        <button
          type="button"
          role="menuitem"
          className="row-mi"
          data-testid="session-split-with"
          onClick={() => {
            onClose();
            openSplitPicker(open.id);
          }}
        >
          {t("split.with")}
        </button>
      )}
    </div>
  );
}
