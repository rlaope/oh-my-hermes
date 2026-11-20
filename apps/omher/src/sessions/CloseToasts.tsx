// The undo toasts of closed TERMINALS rows (closeGrace.ts): bottom right, the newest on top, at most GRACE_SHOWN. Each
// says "<name> closed", counts its seconds down (one 1 s tick) and has Undo. ⌘Z (macOS) or Ctrl+Shift+Z (elsewhere)
// undoes the newest while one shows; plain Ctrl+Z stays the terminal program's, and a text field keeps its own undo.
import { useEffect, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { t } from "../i18n";
import { isMac } from "../app/shortcuts";
import { getSessions } from "./sessions";
import { GRACE_SHOWN, isUndoKey } from "./closeGrace";

/** Focus in a text field of the app (not a terminal): ⌘Z / Ctrl+Shift+Z there is the field's own undo or redo. */
const inTextField = (el: Element | null): boolean =>
  !!el && (el.matches?.("input, [contenteditable], [contenteditable] *") || (el.tagName === "TEXTAREA" && !el.classList.contains("xterm-helper-textarea")));

export function CloseToasts() {
  const s = getSessions();
  const list = useSyncExternalStore(s.onClosing, s.closing, s.closing);
  // one tick a second re-renders the countdown; the seconds are read from the clock at render
  const [, setTick] = useState(0);
  const any = list.length > 0;
  useEffect(() => {
    if (!any) return;
    const tick = setInterval(() => setTick((n) => n + 1), 1000);
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || !isUndoKey(e, isMac()) || inTextField(document.activeElement)) return;
      if (!getSessions().undoClose()) return;
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      clearInterval(tick);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [any]);
  if (!any || typeof document === "undefined") return null;
  const now = Date.now();
  return createPortal(
    <div className="ss-toasts" role="status" aria-live="polite" data-testid="close-toasts">
      {list.slice(0, GRACE_SHOWN).map((g) => {
        const left = Math.min(Math.ceil((g.until - g.closedAt) / 1000), Math.max(1, Math.ceil((g.until - now) / 1000)));
        return (
          <div key={g.id} className="ss-toast" data-testid={`close-toast-${g.id}`}>
            <span className="ss-toast-t" title={g.name}>
              {t("ss.closedToast", { name: g.name })}
            </span>
            <span className="ss-toast-s" data-testid="close-toast-left">
              {t("ss.closedLeft", { n: left })}
            </span>
            <button type="button" className="ss-toast-undo" onClick={() => getSessions().undoClose(g.id)} data-testid="close-toast-undo">
              {t("ss.undo")}
            </button>
          </div>
        );
      })}
    </div>,
    document.body,
  );
}
