import type { ReactNode, Ref } from "react";
import { t } from "../../i18n";
import { useMentions, withMentions } from "./Mention";
import type { Skill } from "../../lib/protocol";
import type { AgentCommand } from "./commands";
import { sentTokens, type SkillToken } from "./skillTokens";
import { withLinks } from "./LinkChip";
import "./skills.css";

/** The `./` picker above the composer: one row per skill (name as a monospace pill, one-line description).
 * Keys stay in the textarea (the composer moves `active`); a row takes the mouse without taking focus. */
export function SkillPicker({
  items,
  active,
  onPick,
  onHover,
  popRef,
}: {
  items: Skill[];
  active: number;
  onPick: (s: Skill) => void;
  onHover: (i: number) => void;
  popRef: Ref<HTMLDivElement>;
}) {
  return (
    <div className="sk-pop" ref={popRef} role="listbox" aria-label={t("skills.label")} data-testid="skill-picker">
      {items.length ? (
        items.map((s, i) => (
          <div
            key={s.name}
            role="option"
            aria-selected={i === active}
            className={`sk-row${i === active ? " on" : ""}`}
            data-testid="skill-option"
            data-name={s.name}
            title={s.description || s.name}
            onMouseDown={(e) => e.preventDefault()}
            onMouseMove={() => i !== active && onHover(i)}
            onClick={() => onPick(s)}
          >
            <code className="sk-pill">{s.name}</code>
            {s.description && <span className="sk-d">{s.description}</span>}
          </div>
        ))
      ) : (
        <div className="sk-none" data-testid="skill-none">
          {t("skills.none")}
        </div>
      )}
    </div>
  );
}

/** The `/` menu of a SESSIONS chat: the commands and skills its agent reported, as wide as the composer: the name in
 * plain monospace text with its prefix, what it takes, and its one-line description; a skill carries a "skill" mark in
 * the accent colour, so skills stand apart from commands at a glance. At most MENU_MAX rows; the last line says how
 * many more match. Keys stay in the textarea, as for skills. */
export function CommandPicker({
  items,
  more,
  active,
  onPick,
  onHover,
  popRef,
}: {
  items: AgentCommand[];
  more: number;
  active: number;
  onPick: (c: AgentCommand) => void;
  onHover: (i: number) => void;
  popRef: Ref<HTMLDivElement>;
}) {
  return (
    <div className="sk-pop" ref={popRef} role="listbox" aria-label={t("ctl.commands")} data-testid="command-picker">
      {items.length ? (
        items.map((c, i) => (
          <div
            key={`${c.prefix}${c.name}`}
            role="option"
            aria-selected={i === active}
            className={`sk-row${i === active ? " on" : ""}`}
            data-testid="command-option"
            data-name={c.name}
            data-kind={c.kind}
            title={c.description || c.name}
            onMouseDown={(e) => e.preventDefault()}
            onMouseMove={() => i !== active && onHover(i)}
            onClick={() => onPick(c)}
          >
            <span className="sk-name" data-testid="command-name">
              {c.prefix}
              {c.name}
            </span>
            {c.hint && <span className="sk-hint">{c.hint}</span>}
            {c.description && <span className="sk-d">{c.description}</span>}
            {c.kind === "skill" && (
              <span className="sk-kind" data-testid="command-skill">
                {t("ctl.skill")}
              </span>
            )}
          </div>
        ))
      ) : (
        <div className="sk-none" data-testid="command-none">
          {t("ctl.noCommand")}
        </div>
      )}
      {more > 0 && (
        <div className="sk-none" data-testid="command-more">
          {t("ctl.more", { n: more })}
        </div>
      )}
    </div>
  );
}

/** What the composer's mirror layer draws under the textarea: the same text, transparent, with each token's
 * gray pill and a zero-width mark at `anchor` (where the `./` being typed starts) to place the picker. */
export function mirrorText(text: string, tokens: SkillToken[], anchor: number | null, anchorRef: Ref<HTMLSpanElement>): ReactNode[] {
  const out: ReactNode[] = [];
  let at = 0;
  let marked = anchor === null;
  const upTo = (to: number) => {
    if (!marked && anchor! <= to) {
      out.push(text.slice(at, anchor!), <span key="anchor" ref={anchorRef} />);
      at = anchor!;
      marked = true;
    }
    out.push(text.slice(at, to));
    at = to;
  };
  tokens.forEach((tok, i) => {
    upTo(tok.start);
    out.push(
      <mark key={i} className="cm-tok">
        {text.slice(tok.start, tok.end)}
      </mark>,
    );
    at = tok.end;
  });
  upTo(text.length);
  out.push(" "); // a trailing line break still makes a line, as it does in the textarea
  return out;
}

/** A sent message as the person typed it, each skill token drawn as a monospace pill, each URL as a link chip and
 * each bot mention as a mention. */
export function SkillText({ text, sent }: { text: string; sent?: string }) {
  const tokens = sentTokens(text, sent);
  const m = useMentions();
  // links first, then mentions in the text between them (an `@` inside a URL is never a mention)
  const plain = (s: string, key: string): ReactNode[] =>
    withLinks(s, `${key}l`).flatMap((n, j) => (typeof n === "string" ? withMentions(n, m, `${key}m${j}-`) : [n]));
  if (!tokens.length) return <>{plain(text, "a")}</>;
  const out: ReactNode[] = [];
  let at = 0;
  tokens.forEach((tok, i) => {
    out.push(...plain(text.slice(at, tok.start), `t${i}`));
    out.push(
      <code key={i} className="sk-pill" data-testid="bubble-skill">
        {text.slice(tok.start, tok.end)}
      </code>,
    );
    at = tok.end;
  });
  out.push(...plain(text.slice(at), "z"));
  return <>{out}</>;
}
