import { useEffect, useRef, useState, type MouseEvent } from "react";
import type { Bot } from "../lib/protocol";
import { askText, liveLabel, type Ask, type Chat } from "../state/store";
import { Avatar, LiveRing, Ticker, TypingDots } from "../ui";
import { AskLine } from "./Needs";
import { busyFor, shortTime } from "../app/time";
import { useNow } from "../elsewhere/useNow";
import { fileName, splitMedia } from "../chat/parts/mediaLines";
import { listText, t } from "../i18n";
import { WORKING } from "../state/store";
import { useRestart } from "./restart";
import { RestartLine } from "./RestartLine";
import { useMates } from "./restart";

/** The live step the activity line shows ("Reading gateway.log", "Running pnpm test"); "Thinking…" until there
 *  is one ("Working…" is only the placeholder of a turn found running on open). */
const liveText = (status: string | undefined) => (status && status !== WORKING ? status : t("row.thinking"));

/** One-line preview: the live step while running, else the last assistant text. */
export function preview(bot: Bot, chat: Chat | undefined): { text: string; live: boolean; ts: number | null } {
  if (bot.status === "offline") return { text: t("row.offline"), live: false, ts: null };
  if (chat?.turn) return { text: liveText(chat.turn.status), live: true, ts: chat.turn.startedAt / 1000 };
  const items = chat?.items ?? [];
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const it = items[i];
    if (it.kind === "assistant") return { text: plain(it.text), live: false, ts: it.ts };
  }
  const last = items[items.length - 1];
  if (bot.running) return { text: liveText(""), live: true, ts: null };
  return { text: bot.description || "", live: false, ts: last ? last.ts : null };
}

/** The live step as the activity line shows it: the command or path of the latest tool in a code span. */
function LiveStep({ chat, text }: { chat: Chat | undefined; text: string }) {
  const l = chat?.turn ? liveLabel(chat.turn) : null;
  return (
    <Ticker text={text}>
      {l?.code ? (
        <>
          {l.verb} <code>{l.code}</code>
        </>
      ) : (
        text
      )}
    </Ticker>
  );
}

/** Markdown-ish text to one plain line; a file the bot sent shows as its name. */
export const plain = (raw: string) => {
  const { text, paths } = splitMedia(raw);
  return text ? flat(text) : paths.map(fileName).join(", ");
};
const flat = (t: string) =>
  t
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/[`*_>#]/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();

const MENU_W = 168;
const MENU_H = 166;

export interface RowMenu {
  pinned: boolean;
  onPin: () => void;
  onEdit: () => void;
  /** Restart that bot (Start when it is offline), through Hermes' own command; restart.ts holds what follows. */
  onRestart: () => void;
  /** The bot is offline: the row reads "Start". */
  offline?: boolean;
  /** Take the bot out of the sidebar list (the profile stays; it is offered under + again). Absent for the last
   *  listed bot: the item shows disabled, with a tooltip saying why. */
  onRemove?: () => void;
}

/** Right-click or ⋯ menu of a bot row: Pin to top, Edit bot, Restart (Start when offline), Remove from list.
 *  Nothing that would create, stop or delete a Hermes profile, no "restart all", and no "New thread" (one chat per
 *  bot). */
function Menu({ menu, onClose, name, bot, at }: { menu: RowMenu; onClose: () => void; name: string; bot: string; at: { x: number; y: number } }) {
  const ref = useRef<HTMLDivElement>(null);
  // Restart restarts the gateway process that serves this bot: say who else goes down with it, before the press
  const mates = useMates(bot);
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
  const items: [string, (() => void) | undefined][] = [
    [menu.pinned ? t("row.unpin") : t("row.pin"), menu.onPin],
    [t("row.edit"), menu.onEdit],
    [menu.offline ? t("row.start") : t("row.restart"), menu.onRestart],
    [t("row.remove"), menu.onRemove],
  ];
  return (
    <div
      ref={ref}
      className="row-menu"
      style={{ left: at.x, top: at.y }}
      role="menu"
      aria-label={t("row.actions", { name })}
      data-testid="row-menu"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
          return;
        }
        if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
        e.preventDefault();
        const btns = [...(ref.current?.querySelectorAll<HTMLButtonElement>("button:not([aria-disabled])") ?? [])];
        const at = btns.indexOf(document.activeElement as HTMLButtonElement);
        btns[(at + (e.key === "ArrowDown" ? 1 : btns.length - 1)) % btns.length]?.focus();
      }}
    >
      {items.map(([label, fn], i) =>
        i === 2 && mates.length && fn ? (
          <button key={label} type="button" role="menuitem" className="row-mi two" onClick={run(fn)} data-testid="row-restart">
            {label}
            <span className="row-mi-sub" data-testid="row-restart-with">
              {t("row.restartWith", { list: listText(mates.map((m) => m.display_name)) })}
            </span>
          </button>
        ) : (
          <button
            key={label}
            type="button"
            role="menuitem"
            className="row-mi"
            onClick={fn ? run(fn) : undefined}
            aria-disabled={!fn || undefined}
            title={!fn && i === 3 ? t("row.removeLast") : undefined}
            data-testid={i === 2 ? "row-restart" : i === 3 ? "row-remove" : undefined}
          >
            {label}
          </button>
        ),
      )}
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
  const rs = useRestart(bot.name);
  const restarting = rs.step === "restarting";
  const running = bot.running || !!chat?.turn;
  const needs = asks.length;
  const text = needs ? askText(asks[asks.length - 1].item) : p.text;
  const live = p.live && !needs;
  // the time slot: how long a busy bot has been at it ("12s", "1m"), "waiting" while an ask is open, else the time
  const busySince = running && !needs ? chat?.turn?.startedAt ?? null : null;
  const now = useNow(busySince !== null, 1_000);
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
        {/* answering: a thin rotating ring around the face; an open ask stops it (the amber dot takes over) */}
        <LiveRing on={(running && !needs) || restarting} size={34} gap={3.5} label={restarting ? t("rs.restarting") : t("row.answering")} seed={bot.name}>
          <Avatar bot={bot.name} size={34} />
        </LiveRing>
        <span className="bot-m">
          <span className="bot-r1">
            <span className="bot-n">
              {bot.display_name}
              {pinned && <span className="bot-pin" data-testid="pinned" aria-label={t("row.pinned")} title={t("row.pinned")} />}
            </span>
            {restarting ? (
              <span className="bot-t busy" data-testid="bot-time" data-restarting="true">
                {bot.status === "offline" ? t("rs.starting") : t("rs.restarting")}
              </span>
            ) : needs > 0 ? (
              <span className="bot-t wait" data-testid="bot-time">
                {t("row.waiting")}
              </span>
            ) : busySince !== null ? (
              <span className="bot-t busy" data-testid="bot-time">
                {busyFor(now - busySince)}
              </span>
            ) : (
              p.ts !== null && (
                <span className="bot-t" data-testid="bot-time">
                  {shortTime(p.ts)}
                </span>
              )
            )}
          </span>
          <span className="bot-r2">
            <span className={`bot-p${live ? " live" : ""}${needs ? " ask" : ""}`} data-testid="bot-sub">
              {needs ? <AskLine text={text} /> : live ? <LiveStep chat={chat} text={text} /> : text}
            </span>
            {live && <TypingDots size={3} testId="bot-typing" />}
            {needs > 0 ? (
              // a plain amber dot, no number: a count here would read as unread (the strip carries the count)
              <span className="needs-dot" data-testid="needs" role="status" aria-label={t("row.needsAnswer")} title={t("row.needsAnswer")} />
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
          aria-label={t("row.more", { name: bot.display_name })}
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
      {menu && at && <Menu menu={menu} at={at} name={bot.display_name} bot={bot.name} onClose={() => setAt(null)} />}
      <RestartLine bot={bot} testId={`restart-line-${bot.name}`} pop />
    </div>
  );
}
