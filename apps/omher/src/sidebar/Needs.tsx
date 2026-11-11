// "Needs you": approvals and questions waiting on the person in any bot or SESSIONS chat, pinned above the BOTS list. One line
// ("2 need you · Friren: Allow rm -rf build/?", naming the newest ask); clicking it expands the list in place, pushing BOTS down (never over it, so the open bot stays in
// view): each ask with the bot's face, a type tag (Approve / Question), the ask on up to two lines, and its age. An
// item opens that bot's chat with the card scrolled into view and focused. ⌘J does the same for the next ask. Esc
// or a click outside closes the list. Past three asks the list ends on the third, whole, and a "+2 more" row shows
// the rest (then the list scrolls).
import { useEffect, useRef, useState } from "react";
import { useNow } from "../elsewhere/useNow";
import { t } from "../i18n";
import { askFrom, askText, isSessionChat, useStore, type Ask } from "../state/store";
import { SessionFace } from "../sessions/SessionFace";
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
  if (s < 10) return t("time.nowShort");
  if (s < 60) return t("unit.s", { n: s });
  if (s < 3600) return t("unit.m", { n: Math.floor(s / 60) });
  return t("unit.h", { n: Math.floor(s / 3600) });
}

/** The collapsed strip's line: the count, then who asked last and the first words of that ask, so the person
 *  knows what waits without opening the list ("2 need you · Friren: Allow rm -rf build/?"). The ask is cut at
 *  `max` characters with an ellipsis; CSS cuts again when the sidebar is narrower. */
export function stripText(n: number, who: string, ask: string, max = 32): { count: string; rest: string } {
  const flat = ask.replace(/`/g, "").replace(/\s+/g, " ").trim();
  const words = flat.length > max ? `${flat.slice(0, max - 1).trimEnd()}…` : flat;
  return { count: n === 1 ? t("needs.one") : t("needs.many", { n }), rest: ` · ${who}: ${words}` };
}

/** Asks the list shows before its "+N more" row: three two-line entries fit without cutting one. */
const SHOW = 3;

export function NeedsStrip({ asks }: { asks: Ask[] }) {
  const s = useStore();
  const [open, setOpen] = useState(false);
  const [all, setAll] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const now = useNow(asks.length > 0, 5_000);
  useEffect(() => {
    if (!open) setAll(false);
  }, [open]);
  // "+N more" leaves with the click: the focus goes to the first ask it showed
  useEffect(() => {
    if (all) ref.current?.querySelectorAll<HTMLButtonElement>(".needs-item")[SHOW]?.focus();
  }, [all]);
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
  const name = (bot: string) => askFrom(s, bot);
  const n = asks.length;
  const shown = all || n <= SHOW ? asks : asks.slice(0, SHOW);
  // asks are oldest first: the strip names the newest
  const newest = asks[n - 1];
  const line = stripText(n, name(newest.bot), askText(newest.item));
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
        <span className="needs-t" title={line.count + line.rest} data-testid="needs-line">
          {line.count}
          <span className="needs-who">{line.rest}</span>
        </span>
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
          aria-label={t("needs.list")}
          data-testid="needs-list"
        >
          {shown.map((a) => (
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
              {isSessionChat(a.bot) ? <SessionFace chatKey={a.bot} size={20} /> : <Avatar bot={a.bot} size={20} />}
              <span className="needs-m">
                <span className="needs-r1">
                  <span className="needs-b">{name(a.bot)}</span>
                  <span className="needs-tag" data-testid="needs-tag">
                    {a.item.kind === "approval" ? t("needs.approve") : t("needs.question")}
                  </span>
                  <span className="needs-age">{age(a.ts, now)}</span>
                </span>
                <span className="needs-q" title={askText(a.item)}>
                  <AskLine text={askText(a.item)} />
                </span>
              </span>
            </button>
          ))}
          {shown.length < n && (
            <button type="button" className="needs-more" onClick={() => setAll(true)} data-testid="needs-more">
              {t("needs.more", { n: n - shown.length })}
            </button>
          )}
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
    <div className="hidden-list" ref={ref} role="dialog" aria-label={t("needs.hidden")} data-testid="hidden-list">
      <div className="hidden-h">{t("needs.hidden")}</div>
      {hidden.map((b) => (
        <div key={b.name} className="hidden-row">
          <Avatar bot={b.name} size={20} />
          <span className="hidden-n">{b.display_name}</span>
          <button type="button" className="hidden-show" onClick={() => s.hideBot(b.name, false)} aria-label={t("needs.showOf", { name: b.display_name })}>
            {t("needs.show")}
          </button>
        </div>
      ))}
    </div>
  );
}
