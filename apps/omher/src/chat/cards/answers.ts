// Interview answers in the shape Hermes' clarify tool reads back (tools/clarify_tool.py `_clean_answer`).

/** The person's pick for one question: chosen labels plus an optional "Other" text. */
export interface Pick {
  chosen: string[];
  other: string;
}
export const EMPTY: Pick = { chosen: [], other: "" };

/** What Hermes reads back for a question: the label (or the typed text), a JSON array of labels for a
 *  multi-select question, or null when skipped. */
export function answerOf(q: Pick, multi: boolean): string | null {
  const other = q.other.trim();
  if (multi) {
    const all = [...q.chosen, ...(other ? [other] : [])];
    return all.length ? JSON.stringify(all) : null;
  }
  if (other) return other;
  return q.chosen[0] ?? null;
}
