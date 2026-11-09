import { useEffect, useRef, useState, type MouseEvent } from "react";
import type { Bot } from "../lib/protocol";
import { askText, type Ask, type Chat } from "../state/store";
import { Avatar } from "../ui";
import { AskLine } from "./Needs";
import { shortTime } from "../app/time";

/** One-line preview: live turn status while running, else the last assistant text. */
export function preview(bot: Bot, chat: Chat | undefined): { text: string; live: boolean; ts: number | null } {
  if (bot.status === "offline") return { text: "Not connected", live: false, ts: null };
  if (chat?.turn) return { text: chat.turn.status || "Working…", live: true, ts: chat.turn.startedAt / 1000 };
  const items = chat?.items ?? [];
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const it = items[i];
    if (it.kind === "assistant") return { text: plain(it.text), live: false, ts: it.ts };
  }
  const last = items[items.length - 1];
  if (bot.running) return { text: "Working…", live: true, ts: null };
  return { text: bot.description || "", live: false, ts: last ? last.ts : null };
}

/** Markdown-ish text to one plain line. */
export const plain = (t: string) =>
  t
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/[`*_>#]/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();

const MENU_W = 168;
const MENU_H = 120;

export interface RowMenu {
  pinned: boolean;
  onPin: () => void;
  onEdit: () => void;
  onHide: () => void;
  /** Present when some bots are hidden: opens the list of them. */
  onShowHidden?: () => void;
}

/** Right-click or ⋯ menu of a bot row: Pin to top, Edit bot, Hide from sidebar, Show hidden… Nothing that would
 *  create or delete a Hermes profile, and no "New thread" (one chat per bot). */
function Menu({ menu, onClose, name, at }: { menu: RowMenu; onClose: () => void; name: string; at: { x: number; y: number } }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const onDown = (e: globalThis.MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onClose]);
  const run = (fn: () => void) => () => {
    onClose();
    fn();
  };
  const items: [string, () => void][] = [
    [menu.pinned ? "Unpin" : "Pin to top", menu.onPin],
    ["Edit bot", menu.onEdit],
    ["Hide from sidebar", menu.onHide],
    ...(menu.onShowHidden ? ([["Show hidden…", menu.onShowHidden]] as [string, () => void][]) : []),
  ];
  return (
    <div
      ref={ref}
      className="row-menu"
      style={{ left: at.x, top: at.y }}
      role="menu"
      aria-label={`${name} actions`}
      data-testid="row-menu"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
          return;
        }
        if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
        e.preventDefault();
        const btns = [...(ref.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
        const at = btns.indexOf(document.activeElement as HTMLButtonElement);
        btns[(at + (e.key === "ArrowDown" ? 1 : btns.length - 1)) % btns.length]?.focus();
      }}
    >
      {items.map(([label, fn], i) => (
        <button key={label} type="button" role="menuitem" className={`row-mi${i === 3 ? " sep" : ""}`} onClick={run(fn)}>
          {label}
        </button>
      ))}
    </div>
  );
}

export function BotRow({
  bot,
  chat,
  unread,
  active,
  asks = [],
  pinned = false,
  menu,
  onSelect,
}: {
  bot: Bot;
  chat: Chat | undefined;
  unread: number;
  active: boolean;
  /** Approvals and questions of this bot still waiting on the person. */
  asks?: Ask[];
  pinned?: boolean;
  menu?: RowMenu;
  onSelect: () => void;
}) {
  // The menu is fixed to the window (the bot list scrolls and would clip it): opened at the pointer on a
  // right-click, under the ⋯ button otherwise, kept inside the sidebar's width and the window's height.
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);
  const open = at !== null;
  const wrap = useRef<HTMLDivElement>(null);
  const place = (x: number, y: number) => {
    const side = wrap.current?.closest(".side")?.getBoundingClientRect();
    const right = (side?.right ?? window.innerWidth) - 6;
    setAt({ x: Math.max(6, Math.min(x, right - MENU_W)), y: Math.min(y, window.innerHeight - MENU_H - 6) });
  };
  const p = preview(bot, chat);
  const running = bot.running || !!chat?.turn;
  const needs = asks.length;
  const text = needs ? askText(asks[asks.length - 1].item) : p.text;
  const onContext = (e: MouseEvent) => {
    if (!menu) return;
    e.preventDefault();
    place(e.clientX, e.clientY);
  };
  return (
    <div ref={wrap} className={`bot-w${open ? " menu-open" : ""}`} onContextMenu={onContext}>
      <button
        type="button"
        className={`bot${active ? " active" : ""}${unread && !needs ? " unread" : ""}${needs ? " needs" : ""}`}
        onClick={onSelect}
        aria-current={active ? "true" : undefined}
        data-testid={`bot-${bot.name}`}
      >
        <Avatar bot={bot.name} size={34} />
        {running && <span className="live-dot" data-testid="live-dot" aria-label="running" />}
        <span className="bot-m">
          <span className="bot-r1">
            <span className="bot-n">
              {bot.display_name}
              {pinned && <span className="bot-pin" data-testid="pinned" aria-label="Pinned" title="Pinned" />}
            </span>
            {p.ts !== null && !needs && <span className="bot-t">{shortTime(p.ts)}</span>}
            {needs > 0 && <span className="bot-t">{shortTime(asks[asks.length - 1].ts)}</span>}
          </span>
          <span className="bot-r2">
            <span className={`bot-p${p.live && !needs ? " live" : ""}${needs ? " ask" : ""}`} data-testid="bot-sub">
              {needs ? <AskLine text={text} /> : text}
            </span>
            {needs > 0 ? (
              // a plain amber dot, no number: a count here would read as unread (the strip carries the count)
              <span className="needs-dot" data-testid="needs" role="status" aria-label="Needs your answer" title="Needs your answer" />
            ) : (
              unread > 0 && (
                <span className="badge" data-testid="unread">
                  {unread}
                </span>
              )
            )}
          </span>
        </span>
      </button>
      {menu && (
        <button
          type="button"
          className="bot-more"
          aria-label={`More for ${bot.display_name}`}
          aria-haspopup="menu"
          aria-expanded={open}
          data-testid={`bot-more-${bot.name}`}
          onClick={(e) => {
            if (open) return setAt(null);
            const r = e.currentTarget.getBoundingClientRect();
            const row = wrap.current?.getBoundingClientRect();
            place(r.right - MENU_W, (row?.bottom ?? r.bottom) + 2);
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <circle cx="5" cy="12" r="1.8" />
            <circle cx="12" cy="12" r="1.8" />
            <circle cx="19" cy="12" r="1.8" />
          </svg>
        </button>
      )}
      {menu && at && <Menu menu={menu} at={at} name={bot.display_name} onClose={() => setAt(null)} />}
    </div>
  );
}
