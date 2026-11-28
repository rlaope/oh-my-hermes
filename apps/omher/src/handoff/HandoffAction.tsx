// "Hand to bot" on a finished answer (BOUNDARY rule 56): a quiet button in the answer's action column, beside copy and
// read aloud, and one suggestion chip per other bot the answer names with `@name`. Either opens the small popover: the
// other bots, an optional note, and Hand over, which starts a thread in the picked bot through the store's one
// `startTaskThread` (thread.create, then chat.send) and leaves the person where they are. Nothing is sent by the
// button, a chip or a mention by itself: only Hand over sends. Escape or a press outside closes it.
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { selectSidebarBots, useStore, type AppState } from "../state/store";
import type { Bot } from "../lib/protocol";
import { t } from "../i18n";
import { composing } from "../lib/ime";
import { Avatar } from "../ui";
import { GOAL_CHARS } from "../handover/message";
import { useMentions } from "../chat/parts/Mention";
import { findMentions } from "../chat/parts/mentions";
import { codeRanges } from "../chat/parts/skillTokens";
import { handoffMessage, handoffTitle } from "./message";
import "../handover/handover.css";
import "./handoff.css";

/** The bots an answer of `from` can be handed to: the sidebar's other bots that are not offline. A bot on another
 *  computer is one of them (its bridge takes `thread.create` and a thread's `chat.send`, rule 31). */
export const handoffBots = (s: AppState, from: string): Bot[] => selectSidebarBots(s).filter((b) => b.name !== from && b.status !== "offline");

const HandIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 12h12" />
    <path d="m12 6 6 6-6 6" />
    <path d="M20 5v14" />
  </svg>
);

type Open = { pick: string | null; back: HTMLElement | null };

/** The action of one answer `id` of chat `chat`, from bot `from`: its button (inside the bubble, in the action column)
 *  and what goes under the bubble (the mention chips, and the popover while open). None without `from`. */
export function useHandoff(chat: string, id: string | undefined, from: string | undefined, text: string): { button: ReactNode; under: ReactNode } {
  const [open, setOpen] = useState<Open | null>(null);
  const m = useMentions();
  if (!id || !from || !text.trim()) return { button: null, under: null };
  const named = m ? [...new Set(findMentions(text, m.resolve, codeRanges(text)).map((x) => x.bot))].filter((b) => b !== from) : [];
  const label = t("handoff.action");
  const button = (
    <button
      type="button"
      className={`copy-btn msg-hand${open ? " on" : ""}`}
      aria-label={label}
      title={label}
      aria-haspopup="dialog"
      aria-expanded={!!open}
      onClick={(e) => {
        e.stopPropagation();
        setOpen(open ? null : { pick: null, back: e.currentTarget });
      }}
      data-testid="handoff-action"
    >
      <HandIcon />
    </button>
  );
  const under = (
    <>
      {named.length > 0 && <HandoffChips from={from} named={named} onPick={(pick, back) => setOpen({ pick, back })} />}
      {open && <HandoffPopover chat={chat} id={id} from={from} text={text} open={open} onClose={() => setOpen(null)} />}
    </>
  );
  return { button, under };
}

/** One quiet chip per named bot that can take the answer: "Hand this to <bot>". It only opens the popover. */
function HandoffChips({ from, named, onPick }: { from: string; named: string[]; onPick: (bot: string, back: HTMLElement) => void }) {
  const s = useStore();
  const bots = handoffBots(s, from).filter((b) => named.includes(b.name));
  if (!bots.length) return null;
  return (
    <div className="hf-chips" data-testid="handoff-chips">
      {bots.map((b) => (
        <button key={b.name} type="button" className="agent-chip hf-chip" onClick={(e) => onPick(b.name, e.currentTarget)} data-testid="handoff-chip" data-to={b.name}>
          <Avatar bot={b.name} size={14} />
          <span className="agent-chip-t">{t("handoff.chip", { bot: b.display_name })}</span>
        </button>
      ))}
    </div>
  );
}

const W = 300;

function HandoffPopover({ chat, id, from, text, open, onClose }: { chat: string; id: string; from: string; text: string; open: Open; onClose: () => void }) {
  const s = useStore();
  const bots = handoffBots(s, from);
  const [pick, setPick] = useState<string | null>(open.pick && bots.some((b) => b.name === open.pick) ? open.pick : (bots[0]?.name ?? null));
  const to = bots.find((b) => b.name === pick) ?? null;
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const how = useRef<"own" | "outside" | null>(null);
  const close = useRef(onClose);
  close.current = onClose;

  // below the button or chip that opened it (above it when there is no room), inside the window
  useLayoutEffect(() => {
    const r = open.back?.getBoundingClientRect();
    const el = ref.current;
    if (!r || !el) return;
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    const left = Math.max(6, Math.min(r.right - w, window.innerWidth - w - 6));
    const below = r.bottom + 6;
    const top = below + h <= window.innerHeight - 6 ? below : Math.max(6, r.top - h - 6);
    setPos({ left, top });
  }, [open.back, bots.length]);

  // the picked bot takes the keyboard; a press outside closes; Escape, Cancel or a hand over gives it back
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[role="option"][aria-selected="true"], [data-testid="handoff-note"]')?.focus();
    const onDown = (e: MouseEvent) => {
      if (!ref.current || ref.current.contains(e.target as Node) || open.back?.contains(e.target as Node)) return;
      how.current = "outside";
      close.current();
    };
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("mousedown", onDown);
      if (how.current === "own" && open.back?.isConnected) open.back.focus();
    };
  }, [open.back]);
  const done = () => {
    how.current = "own";
    onClose();
  };

  const send = async () => {
    if (!to || busy) return;
    setBusy(true);
    const name = s.bots.find((b) => b.name === from)?.display_name || from;
    const facts = { from: name, note, answer: text };
    await s.startTaskThread(to.name, handoffTitle(facts), handoffMessage(facts), { chat, message: id });
    setBusy(false);
    done();
  };

  /** Arrow keys move the pick (and the keyboard) in the list; Enter hands over. */
  const onList = (e: KeyboardEvent) => {
    const i = bots.findIndex((b) => b.name === pick);
    const go = (n: number) => {
      e.preventDefault();
      const b = bots[(n + bots.length) % bots.length];
      setPick(b.name);
      ref.current?.querySelector<HTMLElement>(`[role="option"][data-bot="${CSS.escape(b.name)}"]`)?.focus();
    };
    if (e.key === "ArrowDown") go(i + 1);
    else if (e.key === "ArrowUp") go(i - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(bots.length - 1);
    else if (e.key === "Enter") {
      e.preventDefault();
      void send();
    }
  };

  return createPortal(
    <div
      ref={ref}
      className="ho-card hf-pop"
      role="dialog"
      aria-label={t("handoff.title")}
      style={{ left: pos?.left ?? -9999, top: pos?.top ?? 0, width: W }}
      data-testid="handoff-popover"
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key !== "Escape") return;
        e.preventDefault();
        e.stopPropagation();
        done();
      }}
    >
      <div className="ho-head">
        <b>{t("handoff.title")}</b>
      </div>
      {bots.length ? (
        <div role="listbox" aria-label={t("handoff.to")} className="pg-botlist hf-list" onKeyDown={onList}>
          {bots.map((b) => (
            <button
              key={b.name}
              type="button"
              role="option"
              aria-selected={b.name === pick}
              tabIndex={b.name === pick ? 0 : -1}
              className={b.name === pick ? "on" : undefined}
              onClick={() => setPick(b.name)}
              data-testid="handoff-bot"
              data-bot={b.name}
            >
              <Avatar bot={b.name} size={18} />
              <span className="hf-name">{b.display_name}</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="ho-prev ho-wait" data-testid="handoff-none">
          {t("handoff.none")}
        </div>
      )}
      <label className="ho-goal">
        <span>{t("handoff.note")}</span>
        <input
          type="text"
          value={note}
          maxLength={GOAL_CHARS}
          placeholder={t("handoff.noteHint")}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !composing(e)) {
              e.preventDefault();
              void send();
            }
          }}
          data-testid="handoff-note"
        />
      </label>
      <p className="ho-note">{to ? t("handoff.what", { bot: to.display_name }) : t("handoff.none")}</p>
      <div className="ho-b">
        <button type="button" onClick={done} data-testid="handoff-cancel">
          {t("hand.cancel")}
        </button>
        <button type="button" className="primary" disabled={!to || busy} onClick={() => void send()} data-testid="handoff-confirm">
          {t("handoff.send")}
        </button>
      </div>
    </div>,
    document.body,
  );
}
