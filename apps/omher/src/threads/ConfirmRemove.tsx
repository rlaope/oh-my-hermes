// The small confirm under a thread row's x. Cancel (or Escape, or a press outside) sends nothing; the second
// button stops the thread when it runs and archives it in Hermes (hidden, messages kept, restorable).
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { t } from "../i18n";

const W = 236;

export function ConfirmRemove({ at, running, onCancel, onConfirm }: { at: DOMRect; running: boolean; onCancel: () => void; onConfirm: () => Promise<void> }) {
  const ref = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLButtonElement>("[data-default]")?.focus();
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onCancel();
    };
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("mousedown", onDown);
      if (back && document.contains(back)) back.focus();
    };
  }, [onCancel]);
  const left = Math.max(6, Math.min(at.right - W, window.innerWidth - W - 6));
  const top = Math.min(at.bottom + 4, window.innerHeight - 96);
  return createPortal(
    <div
      ref={ref}
      className="th-confirm"
      role="alertdialog"
      aria-modal="false"
      aria-label={running ? t("thread.removeRunning") : t("thread.removeAsk")}
      style={{ left, top, width: W }}
      data-testid="thread-confirm"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          onCancel();
        }
      }}
    >
      <p>{running ? t("thread.removeRunning") : t("thread.removeAsk")}</p>
      <div className="th-confirm-b">
        <button type="button" onClick={onCancel} data-default data-testid="thread-cancel">
          {t("thread.cancel")}
        </button>
        <button
          type="button"
          className="danger"
          disabled={busy}
          data-testid="thread-confirm-remove"
          onClick={async () => {
            setBusy(true);
            await onConfirm();
          }}
        >
          {running ? t("thread.stopRemove") : t("thread.removeYes")}
        </button>
      </div>
    </div>,
    document.body,
  );
}
