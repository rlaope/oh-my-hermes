import type { Bot } from "../lib/protocol";
import type { Chat } from "../state/store";
import { Avatar } from "../ui";
import { shortTime } from "../app/time";
import { fileName, splitMedia } from "../chat/parts/mediaLines";

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

/** Markdown-ish text to one plain line; a file the bot sent shows as its name. */
const plain = (raw: string) => {
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

export function BotRow({
  bot,
  chat,
  unread,
  active,
  onSelect,
}: {
  bot: Bot;
  chat: Chat | undefined;
  unread: number;
  active: boolean;
  onSelect: () => void;
}) {
  const p = preview(bot, chat);
  const running = bot.running || !!chat?.turn;
  return (
    <button
      type="button"
      className={`bot${active ? " active" : ""}${unread ? " unread" : ""}`}
      onClick={onSelect}
      aria-current={active ? "true" : undefined}
      data-testid={`bot-${bot.name}`}
    >
      <Avatar bot={bot.name} size={34} />
      {running && <span className="live-dot" data-testid="live-dot" aria-label="running" />}
      <span className="bot-m">
        <span className="bot-r1">
          <span className="bot-n">{bot.display_name}</span>
          {p.ts !== null && <span className="bot-t">{shortTime(p.ts)}</span>}
        </span>
        <span className="bot-r2">
          <span className={`bot-p${p.live ? " live" : ""}`}>{p.text}</span>
          {unread > 0 && (
            <span className="badge" data-testid="unread">
              {unread}
            </span>
          )}
        </span>
      </span>
    </button>
  );
}
