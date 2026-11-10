// The Update button's confirm: a small dialog over the app that says omher will restart and that chats, panels and
// sessions pick up where they were, names the sessions that are running, and installs only on "Update and restart".
// Keyboard: focus starts on the primary button, Tab and Shift+Tab stay inside, Esc or Cancel closes and gives the
// focus back to the Update button.
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { t } from "../i18n";
import { agentDef, folderName, type SessionRec } from "../sessions/agents";
import { continuesItself } from "../app/resume";

/** The running-sessions line, or "" when none runs. */
export function runningLine(list: readonly SessionRec[], modeOf: (r: SessionRec) => string): string {
  const live = list.filter((r) => r.status === "running" || r.status === "starting");
  if (!live.length) return "";
  // each "folder (Agent)" stays on one line
  const names = live.map((r) => `${folderName(r.cwd)} (${agentDef(r.agent).label})`.replace(/ /g, "\u00a0")).join(", ");
  const head = live.length === 1 ? t("update.running1", { list: names }) : t("update.runningN", { n: live.length, list: names });
  const auto = live.filter((r) => modeOf(r) === "chat" && continuesItself(r)).length;
  const one = live.length === 1;
  const then =
    auto === live.length
      ? t(one ? "update.thenAuto1" : "update.thenAuto")
      : auto === 0
        ? t(one ? "update.thenManual1" : "update.thenManual")
        : t("update.thenMixed");
  return `${head} ${then}`;
}

const FOCUSABLE = "button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex='-1'])";

export function UpdateConfirm({
  version,
  running,
  onCancel,
  onConfirm,
}: {
  version: string;
  running: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const primary = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    primary.current?.focus();
  }, []);
  // keep the focus inside while it is open (a click outside the box does not move it out), and take Esc and Tab
  // at the document, so they work even after a click on the dialog's text left the focus on the page
  const cancel = useRef(onCancel);
  cancel.current = onCancel;
  useEffect(() => {
    const onFocus = (e: FocusEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) primary.current?.focus();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        cancel.current();
        return;
      }
      if (e.key !== "Tab" || !box.current) return;
      const els = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (!els.length) return;
      const first = els[0];
      const last = els[els.length - 1];
      const at = document.activeElement;
      const inside = !!at && box.current.contains(at);
      if (e.shiftKey && (at === first || !inside)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (at === last || !inside)) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("focusin", onFocus);
    // capture: ahead of the app's own Esc (stop the running answer) and any popover under the veil
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("focusin", onFocus);
      document.removeEventListener("keydown", onKey, true);
    };
  }, []);
  return createPortal(
    <div className="upd-veil" data-testid="update-veil" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div
        ref={box}
        className="upd-dlg"
        role="dialog"
        aria-modal="true"
        aria-labelledby="upd-dlg-t"
        aria-describedby="upd-dlg-b"
        data-testid="update-confirm"
      >
        <h2 id="upd-dlg-t" className="upd-dlg-t">
          {t("update.title", { version })}
        </h2>
        <div id="upd-dlg-b" className="upd-dlg-b">
          <p>{t("update.body")}</p>
          {running && <p data-testid="update-running">{running}</p>}
        </div>
        <div className="upd-dlg-f">
          <button type="button" className="upd-dlg-btn" onClick={onCancel} data-testid="update-cancel">
            {t("update.cancel")}
          </button>
          <button ref={primary} type="button" className="upd-dlg-btn primary" onClick={onConfirm} data-testid="update-go">
            {t("update.confirm")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
