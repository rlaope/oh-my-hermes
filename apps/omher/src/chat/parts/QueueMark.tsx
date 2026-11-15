import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { t } from "../../i18n";

/** steer queue sessions: menu items that are off, each with its one-line reason (a SESSIONS agent without its own
 *  steer; a message already handed to the agent). */
export type QueueOffReasons = Partial<Record<QueueChoice, string>>;

export type QueueChoice = "now" | "steer" | "edit" | "delete";
/** Room (px) the menu keeps from the bottom of the chat's scroll box (the composer sits right under it). */
const ROOM = 16;

/** The ↵ mark before a held message (steer queue): a button that opens a small menu. Send now stops the running
 *  answer and sends this one first; Steer hands it to the running answer; Edit puts it back in the box; Delete
 *  drops it. Arrow keys move in the menu, Enter picks, Esc closes it and gives focus back to the mark. */
export function QueueMark({ onPick, busy = false, off = {} }: { onPick: (c: QueueChoice) => void; busy?: boolean; off?: QueueOffReasons }) {
  const [open, setOpen] = useState(false);
  const [up, setUp] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  // the menu opens beside the mark, on the side away from the bubbles, from the mark's top down; upward from its
  // bottom when the chat's scroll box has no room below (the composer sits right under it)
  useLayoutEffect(() => {
    if (!open) return setUp(false);
    const m = menu.current;
    const box = btn.current?.closest(".thread")?.getBoundingClientRect();
    const mark = btn.current?.getBoundingClientRect();
    if (m && box && mark) setUp(mark.top + m.offsetHeight > box.bottom - ROOM && mark.bottom - m.offsetHeight >= box.top);
  }, [open]);
  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const onDown = (e: MouseEvent) => {
      const m = menu.current;
      if (m && !m.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  const items: [QueueChoice, string, string][] = [
    ["now", t("sq.sendNow"), t("sq.sendNowTip")],
    ["steer", t("sq.steer"), t("sq.steerTip")],
    ["edit", t("sq.edit"), t("sq.editTip")],
    ["delete", t("sq.delete"), t("sq.deleteTip")],
  ];
  // every item off for the same reason (the agent has it now): that reason once, at the top
  const reasons = items.map(([c]) => off[c]);
  const oneWhy = reasons.every((r) => r && r === reasons[0]) ? reasons[0] : undefined;
  const pick = (c: QueueChoice) => {
    if (off[c]) return;
    setOpen(false);
    if (c !== "edit") btn.current?.focus();
    onPick(c);
  };
  return (
    <span className="sq-w">
      <button
        ref={btn}
        type="button"
        className={`sq-mark${open ? " on" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("sq.mark")}
        title={t("sq.mark")}
        disabled={busy}
        onClick={() => setOpen((o) => !o)}
        data-testid="queue-mark"
      >
        ↵
      </button>
      {open && (
        <div
          ref={menu}
          className={`sq-menu${up ? " up" : ""}${reasons.some(Boolean) ? " why" : ""}`}
          role="menu"
          aria-label={t("sq.mark")}
          data-testid="queue-menu"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              // the menu takes Esc, not the running answer (shortcuts.ts reads defaultPrevented)
              e.preventDefault();
              e.stopPropagation();
              setOpen(false);
              btn.current?.focus();
              return;
            }
            if (e.key === "Tab") {
              setOpen(false);
              return;
            }
            if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Home" && e.key !== "End") return;
            e.preventDefault();
            const btns = [...(menu.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
            const at = btns.indexOf(document.activeElement as HTMLButtonElement);
            const next =
              e.key === "Home" ? 0 : e.key === "End" ? btns.length - 1 : (at + (e.key === "ArrowDown" ? 1 : btns.length - 1)) % btns.length;
            btns[next]?.focus();
          }}
        >
          {oneWhy && (
            <div className="sq-why sq-why-all" data-testid="queue-why">
              {oneWhy}
            </div>
          )}
          {items.map(([c, label, tip]) => (
            <button
              key={c}
              type="button"
              role="menuitem"
              className={`sq-mi${c === "delete" ? " danger" : ""}${off[c] ? " off" : ""}`}
              title={off[c] ?? tip}
              aria-disabled={off[c] ? true : undefined}
              onClick={() => pick(c)}
              data-testid={`queue-${c}`}
            >
              {label}
              {off[c] && !oneWhy && (
                <span className="sq-why" data-testid={`queue-${c}-why`}>
                  {off[c]}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </span>
  );
}
