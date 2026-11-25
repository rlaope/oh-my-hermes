// "Needs you": approvals and questions waiting on the person in any bot or SESSIONS chat, pinned above the BOTS list. One line
// ("2 need you · Friren and Hermes": the count, then who waits, in the list's order; the asks themselves are in the list and
// would never fit the sidebar's width, ⌘J is in the tooltip); clicking it expands the list in place, pushing BOTS down (never over it, so the open bot stays in
// view): each ask with the bot's face, a type tag (Approve / Question), the ask on up to two lines, and its age. An
// item opens that bot's chat with the card scrolled into view and focused. ⌘J does the same for the next ask. Esc
// or a click outside closes the list. Past three asks the list ends on the third, whole, and a "+2 more" row shows
// the rest (then the list scrolls).
// A thread whose pull request is open with failing checks is listed too, after the asks, with its own reason
// ("checks failing on #12", tag Checks); its item opens the thread. It is a display only: the thread's own state is
// untouched, and ⌘J still steps through the asks alone. It leaves when the checks pass or the PR is merged or closed.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNow } from "../elsewhere/useNow";
import { t } from "../i18n";
import { askFrom, askText, isSessionChat, useStore, type Ask } from "../state/store";
import { SessionFace } from "../sessions/SessionFace";
import { Avatar, ChevronDown } from "../ui";
import type { FailingThread } from "../threads/prs";

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

/** The collapsed strip's line: the count, then who waits, each name once and in the order the list shows them
 *  ("2 need you · Friren, Hermes"); past two names the rest is a count ("Friren, Hermes +2"), so the line fits the
 *  sidebar. The asks' own words stay in the list: in the strip's width they never showed. */
export function stripText(n: number, who: string[]): { count: string; rest: string } {
  const names = [...new Set(who.filter(Boolean))];
  const shown = names.slice(0, 2).join(t("needs.sep")) + (names.length > 2 ? ` +${names.length - 2}` : "");
  return { count: n === 1 ? t("needs.one") : t("needs.many", { n }), rest: names.length ? ` · ${shown}` : "" };
}

/** The strip's words with each " · " held to the word after it in one unbreakable box: where the sidebar cuts the
 *  line, the ellipsis then never follows a lone separator ("web-app ·…"). The text stays the same. */
export function glued(text: string): ReactNode[] {
  return text.split(" · ").flatMap((part, i) => {
    if (i === 0) return [part];
    const [, word, rest] = /^(\S*)([\s\S]*)$/.exec(part)!;
    return [" ", <span key={i} className="needs-sep">{`· ${word}`}</span>, rest];
  });
}

/** Asks the list shows before its "+N more" row: three two-line entries fit without cutting one. */
const SHOW = 3;

/** A failing pull request's line in the strip and the list: "checks failing on #12". */
export const prReason = (f: Pick<FailingThread, "pr">) => t("needs.prFailing", { n: f.pr.number });

/** Who a failing pull request's entry names: the thread's title, else the bot's name. */
export function prWho(s: { threads: Record<string, { thread: string; title: string }[]> }, f: Pick<FailingThread, "bot" | "thread">, botName: string): string {
  return (s.threads[f.bot] ?? []).find((r) => r.thread === f.thread)?.title || botName;
}

export function NeedsStrip({ asks, prs = [] }: { asks: Ask[]; prs?: FailingThread[] }) {
  const s = useStore();
  const [open, setOpen] = useState(false);
  const [all, setAll] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const now = useNow(asks.length > 0, 5_000);
  const total = asks.length + prs.length;
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
    if (!total) setOpen(false);
  }, [total]);
  if (!total) return null;
  const name = (bot: string) => askFrom(s, bot);
  const n = total;
  const shown = all || asks.length <= SHOW ? asks : asks.slice(0, SHOW);
  const shownPrs = all || asks.length + prs.length <= SHOW ? prs : prs.slice(0, Math.max(0, SHOW - shown.length));
  // who waits, in the list's order (asks oldest first, then the failing pull requests)
  const line = stripText(n, [...asks.map((a) => name(a.bot)), ...prs.map((f) => prWho(s, f, name(f.bot)))]);
  const key = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘J" : "Ctrl+J";
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
        title={`${line.count}${line.rest} (${key})`}
        aria-keyshortcuts={key === "⌘J" ? "Meta+J" : "Control+J"}
      >
        <span className="needs-ic" aria-hidden="true" />
        <span className="needs-t" data-testid="needs-line">
          {line.count}
          <span className="needs-who">{glued(line.rest)}</span>
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
          {shownPrs.map((f) => (
            <button
              key={`pr:${f.bot}:${f.thread}`}
              type="button"
              role="listitem"
              className="needs-item"
              data-testid="needs-pr"
              data-thread={f.thread}
              onClick={() => {
                setOpen(false);
                void s.openThread(f.bot, f.thread);
              }}
            >
              <Avatar bot={f.bot} size={20} />
              <span className="needs-m">
                <span className="needs-r1">
                  <span className="needs-b">{prWho(s, f, name(f.bot))}</span>
                  <span className="needs-tag needs-tag-pr" data-testid="needs-tag">
                    {t("needs.checks")}
                  </span>
                </span>
                <span className="needs-q" title={prReason(f)}>
                  {prReason(f)}
                </span>
              </span>
            </button>
          ))}
          {shown.length + shownPrs.length < n && (
            <button type="button" className="needs-more" onClick={() => setAll(true)} data-testid="needs-more">
              {t("needs.more", { n: n - shown.length - shownPrs.length })}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
