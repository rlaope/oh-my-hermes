// What the Automations and Plugins pages share: the "say it in words" box addressed to one bot, the on/off
// switch, the page header and its error line, and the time words both pages use.
import { useState, type ReactNode, type RefObject } from "react";
import "./pages.css";
import type { Bot } from "../lib/protocol";
import { hhmm } from "../app/time";
import { lang, t } from "../i18n";
import { ArrowUp, Avatar, ChevronDown, Popover } from "../ui";

/** The bot chip: its face and name; a click lists every bot to pick from. */
export function BotChip({
  bots,
  bot,
  onPick,
  label,
  testId,
  wide,
}: {
  bots: Bot[];
  bot: Bot | undefined;
  onPick: (name: string) => void;
  /** What the chip says; the bot's name when not given. */
  label?: string;
  testId: string;
  wide?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <span className="pg-chipwrap">
      <button
        type="button"
        className={`pg-botchip${wide ? " wide" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t("ask.pickBot")}
        onClick={() => setOpen((o) => !o)}
        data-testid={testId}
      >
        {bot && <Avatar bot={bot.name} size={18} />}
        <span className="pg-botchip-n">{label ?? bot?.display_name ?? t("ask.pickBot")}</span>
        <ChevronDown />
      </button>
      <Popover open={open} onClose={() => setOpen(false)} align="left" width={200} label={t("ask.pickBot")}>
        <div role="listbox" className="pg-botlist">
          {bots.map((b) => (
            <button
              key={b.name}
              type="button"
              role="option"
              aria-selected={b.name === bot?.name}
              className={b.name === bot?.name ? "on" : undefined}
              onClick={() => {
                onPick(b.name);
                setOpen(false);
              }}
              data-testid={`${testId}-${b.name}`}
            >
              <Avatar bot={b.name} size={18} />
              <span>{b.display_name}</span>
            </button>
          ))}
        </div>
      </Popover>
    </span>
  );
}

/** One line addressed to a bot: the text goes to that bot's main chat as a normal message (`chat.send`). */
export function AskBox({
  bots,
  bot,
  onBot,
  value,
  onChange,
  placeholder,
  onSend,
  inputRef,
}: {
  bots: Bot[];
  bot: Bot | undefined;
  onBot: (name: string) => void;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  onSend: () => void;
  inputRef?: RefObject<HTMLInputElement | null>;
}) {
  const ready = !!bot && value.trim().length > 0;
  return (
    <div className={`pg-ask${ready ? " has" : ""}`} data-testid="ask">
      <BotChip bots={bots} bot={bot} onPick={onBot} testId="ask-bot" />
      <input
        ref={inputRef}
        className="pg-ask-in"
        value={value}
        placeholder={placeholder}
        aria-label={bot ? t("ask.to", { bot: bot.display_name }) : t("ask.pickBot")}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.nativeEvent.isComposing && ready) {
            e.preventDefault();
            onSend();
          }
        }}
        data-testid="ask-input"
      />
      <button
        type="button"
        className="pg-send"
        disabled={!ready}
        aria-label={bot ? t("ask.send", { bot: bot.display_name }) : t("ask.pickBot")}
        onClick={onSend}
        data-testid="ask-send"
      >
        <ArrowUp />
      </button>
    </div>
  );
}

/** On/off: on is a light track with a white knob on the right, off a dark outlined track. */
export function Toggle({
  on,
  label,
  onChange,
  disabled,
  testId,
}: {
  on: boolean;
  label: string;
  onChange: (on: boolean) => void;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className="pg-tog"
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!on);
      }}
      data-testid={testId}
    >
      <span />
    </button>
  );
}

export function PageHead({ title, sub, right }: { title: string; sub: string; right?: ReactNode }) {
  return (
    <header className="head pg-head" data-testid="header">
      <span className="head-title">{title}</span>
      <span className="pg-sub">{sub}</span>
      {right && <div className="head-right">{right}</div>}
    </header>
  );
}

/** The one-line error of a page action: a bot that is offline gets the short line, anything else Hermes' text. */
export function errorLine(e: unknown, botName: string): string {
  const err = (typeof e === "object" && e ? e : {}) as { code?: string; message?: string };
  if (err.code === "bot_offline") return t("page.offline", { bot: botName });
  return t("page.failed", { error: err.message ?? String(e) });
}

/** Seconds since epoch for a time Hermes stored as epoch seconds or ISO text; null when there is none. */
export function toSec(v: number | string | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return v;
  const ms = Date.parse(v);
  return Number.isNaN(ms) ? null : ms / 1000;
}

const dayStart = (ms: number) => {
  const d = new Date(ms);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
};

/** A coming time: "in 14 min", "in 5 h", "tomorrow 09:00", "in 6 days" (in the UI language). */
export function nextWords(ts: number, nowMs = Date.now()): string {
  const ms = ts * 1000 - nowMs;
  if (ms < 60_000) return t("time.now");
  const min = Math.round(ms / 60_000);
  if (min < 60) return t("time.inMin", { n: min });
  const days = Math.round((dayStart(ts * 1000) - dayStart(nowMs)) / 86_400_000);
  if (days <= 0) return t("time.inHours", { n: Math.round(min / 60) });
  if (days === 1) return t("time.tomorrow", { at: hhmm(new Date(ts * 1000)) });
  return t("time.inDays", { n: days });
}

/** A past time: "09:00" today, else the date and time as the UI language writes them. */
export function atWords(ts: number, nowMs = Date.now()): string {
  const d = new Date(ts * 1000);
  if (dayStart(d.getTime()) === dayStart(nowMs)) return hhmm(d);
  return `${d.toLocaleDateString(lang(), { month: "short", day: "numeric" })} ${hhmm(d)}`;
}

/** A date alone ("Nov 3", "11월 3일"). */
export const dateWords = (ts: number) => new Date(ts * 1000).toLocaleDateString(lang(), { month: "short", day: "numeric" });
