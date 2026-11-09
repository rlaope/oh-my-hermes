// "Needs you": approvals and questions waiting on the person in any bot, pinned above the BOTS list. One line
// ("2 need you"); clicking it expands the list in place, pushing BOTS down (never over it, so the open bot stays in
// view): each ask with the bot's face, a type tag (Approve / Question), the ask on up to two lines, and its age. An
// item opens that bot's chat with the card scrolled into view and focused. ⌘J does the same for the next ask. Esc
// or a click outside closes the list.
import { useEffect, useRef, useState } from "react";
import { useNow } from "../elsewhere/useNow";
import { askText, useStore, type Ask } from "../state/store";
import { Avatar, ChevronDown } from "../ui";

/** An ask as one plain line, with `code` spans set in mono instead of showing raw backticks. */
export function AskLine({ text }: { text: string }) {
  const parts = text.split("`");
  if (parts.length < 3 || parts.length % 2 === 0) return <>{text}</>;
  return <>{parts.map((p, i) => (i % 2 ? <code key={i}>{p}</code> : p))}</>;
}

/** "now", "40s", "3m", "2h". */
export function age(ts: number, nowMs: number): string {
  const s = Math.max(0, Math.floor(nowMs / 1000 - ts));
  if (s < 10) return "now";
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h`;
}

export function NeedsStrip({ asks }: { asks: Ask[] }) {
  const s = useStore();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const now = useNow(asks.length > 0, 5_000);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  useEffect(() => {
    if (!asks.length) setOpen(false);
  }, [asks.length]);
  if (!asks.length) return null;
  const name = (bot: string) => s.bots.find((b) => b.name === bot)?.display_name ?? bot;
  const n = asks.length;
  return (
    <div
      className={`needs-w${open ? " open" : ""}`}
      ref={ref}
      onKeyDown={(e) => {
        if (e.key !== "Escape" || !open) return;
        e.preventDefault();
        setOpen(false);
        ref.current?.querySelector<HTMLButtonElement>(".needs-strip")?.focus();
      }}
    >
      <button
        type="button"
        className="needs-strip"
        data-testid="needs-strip"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="needs-ic" aria-hidden="true" />
        <span className="needs-t">{n === 1 ? "1 needs you" : `${n} need you`}</span>
        <span className="needs-k" aria-hidden="true">
          {/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘J" : "Ctrl+J"}
        </span>
        <span className="needs-chev" aria-hidden="true">
          <ChevronDown size={10} />
        </span>
      </button>
      {open && (
        <div
          className="needs-list"
          role="list"
          aria-label="Waiting for your answer"
          data-testid="needs-list"
        >
          {asks.map((a) => (
            <button
              key={`${a.bot}:${a.item.id}`}
              type="button"
              role="listitem"
              className="needs-item"
              data-testid="needs-item"
              onClick={() => {
                setOpen(false);
                void s.jumpToAsk(a.bot, a.item.id);
              }}
            >
              <Avatar bot={a.bot} size={20} />
              <span className="needs-m">
                <span className="needs-r1">
                  <span className="needs-b">{name(a.bot)}</span>
                  <span className="needs-tag" data-testid="needs-tag">
                    {a.item.kind === "approval" ? "Approve" : "Question"}
                  </span>
                  <span className="needs-age">{age(a.ts, now)}</span>
                </span>
                <span className="needs-q" title={askText(a.item)}>
                  <AskLine text={askText(a.item)} />
                </span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Bots hidden from the sidebar, each with Show. Opened from a row menu's "Show hidden…". */
export function HiddenList({ onClose }: { onClose: () => void }) {
  const s = useStore();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onClose]);
  const hidden = s.ui.hidden.map((n) => s.bots.find((b) => b.name === n)).filter((b) => !!b);
  useEffect(() => {
    if (!hidden.length) onClose();
  }, [hidden.length, onClose]);
  return (
    <div className="hidden-list" ref={ref} role="dialog" aria-label="Hidden bots" data-testid="hidden-list">
      <div className="hidden-h">Hidden bots</div>
      {hidden.map((b) => (
        <div key={b.name} className="hidden-row">
          <Avatar bot={b.name} size={20} />
          <span className="hidden-n">{b.display_name}</span>
          <button type="button" className="hidden-show" onClick={() => s.hideBot(b.name, false)} aria-label={`Show ${b.display_name}`}>
            Show
          </button>
        </div>
      ))}
    </div>
  );
}
