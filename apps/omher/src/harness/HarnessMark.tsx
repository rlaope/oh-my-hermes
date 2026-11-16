// A harness's official mark (`<HarnessMark id/>`), a Hermes child's mark with its model's maker as a small second
// mark (`<HarnessFace/>`), and a row of marks for everyone working on a thread (`<HarnessStack/>`, "+N" past `max`).
// Marks come from the one registry (./registry); an unknown harness gets the neutral mark, never a company's logo.
import type { CSSProperties } from "react";
import { AgentIcon } from "../ui/AgentIcon";
import { ModelIcon } from "../ui/ModelIcon";
import { t } from "../i18n";
import { harness, harnessOf, type HarnessFacts, type HarnessId } from "./registry";
import "./harness.css";

export function HarnessMark({ id, size = 14, character = false, style }: { id: HarnessId | string; size?: number; character?: boolean; style?: CSSProperties }) {
  const h = harness(id);
  const file = (character && h.character) || h.mark;
  if (!file)
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="hn-mk hn-generic" data-harness={h.id} style={style}>
        <rect x="3" y="3" width="18" height="18" rx="5" fill="none" stroke="currentColor" strokeWidth="1.6" opacity="0.6" />
        <circle cx="12" cy="12" r="2.6" fill="currentColor" opacity="0.6" />
      </svg>
    );
  return (
    <span className="hn-mk" data-harness={h.id} title={h.label} style={{ width: size, height: size, ...style }}>
      <AgentIcon id={h.label} file={file} size={size} />
    </span>
  );
}

/** The face of a working agent: its harness mark; a Hermes child also wears its model's maker mark on the corner. */
export function HarnessFace({ facts, size = 28 }: { facts: HarnessFacts; size?: number }) {
  const who = harnessOf(facts);
  const small = Math.max(10, Math.round(size * 0.46));
  return (
    <span className="hn-face" data-testid="harness-face" data-harness={who.harness} data-model-mark={who.modelMark ?? undefined} style={{ width: size, height: size }}>
      <HarnessMark id={who.harness} size={size} />
      {who.harness === "hermes" && who.modelMark && (
        <span className="hn-model" data-testid="harness-model-mark" style={{ width: small, height: small }}>
          <ModelIcon model={facts.model ?? undefined} provider={facts.provider ?? undefined} size={small - 2} />
        </span>
      )}
    </span>
  );
}

/** Everyone working on a thread, one mark each (distinct harnesses), "+N" past `max` (no "+N" with `more={false}`:
 *  the rest are named in the tooltip only). */
export function HarnessStack({ items, max = 3, size = 14, more: showMore = true }: { items: HarnessFacts[]; max?: number; size?: number; more?: boolean }) {
  const ids: HarnessId[] = [];
  for (const f of items) {
    const id = harnessOf(f).harness;
    if (!ids.includes(id)) ids.push(id);
  }
  if (!ids.length) return null;
  const shown = ids.slice(0, max);
  const more = ids.length - shown.length;
  const label = ids.map((id) => harness(id).label).join(", ");
  return (
    <span className="hn-stack" data-testid="harness-stack" aria-label={t("harness.working", { who: label })} title={label}>
      {shown.map((id) => (
        <HarnessMark key={id} id={id} size={size} />
      ))}
      {more > 0 && showMore && (
        <span className="hn-more" data-testid="harness-more">
          +{more}
        </span>
      )}
    </span>
  );
}
