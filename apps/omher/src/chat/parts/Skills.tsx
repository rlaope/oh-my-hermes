import type { ReactNode, Ref } from "react";
import { t } from "../../i18n";
import { useMentions, withMentions } from "./Mention";
import type { Skill } from "../../lib/protocol";
import { sentTokens, type SkillToken } from "./skillTokens";
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

/** A sent message as the person typed it, each skill token drawn as a monospace pill and each bot mention as a
 * mention. */
export function SkillText({ text, sent }: { text: string; sent?: string }) {
  const tokens = sentTokens(text, sent);
  const m = useMentions();
  if (!tokens.length) return <>{withMentions(text, m)}</>;
  const out: ReactNode[] = [];
  let at = 0;
  tokens.forEach((tok, i) => {
    out.push(...withMentions(text.slice(at, tok.start), m, `m${i}-`));
    out.push(
      <code key={i} className="sk-pill" data-testid="bubble-skill">
        {text.slice(tok.start, tok.end)}
      </code>,
    );
    at = tok.end;
  });
  out.push(...withMentions(text.slice(at), m, "mz-"));
  return <>{out}</>;
}
