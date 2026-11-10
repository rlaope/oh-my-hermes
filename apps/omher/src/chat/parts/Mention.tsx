import { createContext, useContext, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { t } from "../../i18n";
import { codeRanges } from "./skillTokens";
import { findMentions, type Mention } from "./mentions";

/** What a mention needs from the app: the name lookup, the bot whose chat is open (its own mentions do nothing)
 * and how to open a bot's chat. Markdown and user bubbles read it; without a provider nothing is a mention. */
export interface Mentions {
  resolve: (name: string) => string | null;
  /** The display name for a bot slug, for the tooltip. */
  nameOf: (bot: string) => string;
  current: string | null;
  open: (bot: string) => void;
}

export const MentionContext = createContext<Mentions | null>(null);
export const useMentions = () => useContext(MentionContext);

/** `@name` as an inline control that opens that bot's chat (click, Enter or Space). A mention of the open chat's
 * own bot looks the same but is inert. Never inside a form, and the keys stop here, so nothing is sent. */
export function MentionLink({ bot, children }: { bot: string; children: ReactNode }) {
  const m = useMentions();
  if (!m) return <>{children}</>;
  if (bot === m.current) {
    return (
      <span className="mention self" data-testid="mention" data-bot={bot}>
        {children}
      </span>
    );
  }
  const go = (e: MouseEvent | KeyboardEvent) => {
    e.preventDefault();
    e.stopPropagation();
    m.open(bot);
  };
  return (
    <span
      className="mention"
      role="link"
      tabIndex={0}
      title={t("mention.open", { bot: m.nameOf(bot) })}
      data-testid="mention"
      data-bot={bot}
      onClick={go}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") go(e);
      }}
    >
      {children}
    </span>
  );
}

/** Plain text (a user bubble) with each mention drawn, never inside inline code or a fenced block. */
export function withMentions(text: string, m: Mentions | null, key = "m"): ReactNode[] {
  const found: Mention[] = m ? findMentions(text, m.resolve, codeRanges(text)) : [];
  if (!found.length) return [text];
  const out: ReactNode[] = [];
  let at = 0;
  found.forEach((x, i) => {
    out.push(text.slice(at, x.start));
    out.push(
      <MentionLink key={`${key}${i}`} bot={x.bot}>
        {text.slice(x.start, x.end)}
      </MentionLink>,
    );
    at = x.end;
  });
  out.push(text.slice(at));
  return out;
}
