// ArrowUp/ArrowDown in the composer walk the person's earlier prompts of the open chat, like a shell's history.
// Only the box changes: the history is the chat's own rows, never edited here.

/** What the box shows while walking: `at` indexes the prompt shown (oldest first), `draft` is what was typed
 *  before the first ArrowUp. `null` = the person's own text, not a recalled one. */
export type Recall = { at: number; draft: string } | null;
export type Step = { recall: Recall; text: string };

/** The fields of a chat row `promptsOf` reads (store `MessageItem`). */
type Row = { kind: string; text?: string; held?: boolean; autoSteer?: boolean; steerUnknown?: boolean; wait?: string };

/** The person's prompts of a chat, oldest first, as the bubble shows them (typed text, not the hoisted `/skill`
 *  wire form); a prompt sent twice in a row is one entry, as in a shell. */
export function promptsOf(items: readonly Row[] | undefined): string[] {
  const out: string[] = [];
  for (const i of items ?? []) {
    if (i.kind !== "user" || !i.text?.trim()) continue; // a files-only send has no words to recall
    // only what was sent: a held row still waits in omher's queue (edited there), a dropped one never reached the
    // agent. A failed send and a steer whose answer never came stay: the person typed them and may send them again,
    // as a shell keeps a command that failed. One being steered into the running turn reads as sent, so it is
    // history at once; refused, it waits like any held row and leaves the history again.
    if ((i.held && !i.autoSteer && !i.steerUnknown) || i.wait === "dropped") continue;
    if (out[out.length - 1] !== i.text) out.push(i.text);
  }
  return out;
}

/** ArrowUp: the next older prompt; null when there is none (the key then moves the caret as usual). */
export function older(history: readonly string[], recall: Recall, draft: string): Step | null {
  // the chat can reload under a walk: never step past its end
  const at = Math.min(recall ? recall.at : history.length, history.length) - 1;
  if (at < 0) return null;
  return { recall: { at, draft: recall ? recall.draft : draft }, text: history[at] };
}

/** ArrowDown: the next newer prompt, and past the newest the draft typed before the walk began. */
export function newer(history: readonly string[], recall: Recall): Step | null {
  if (!recall) return null;
  const at = recall.at + 1;
  return at < history.length ? { recall: { at, draft: recall.draft }, text: history[at] } : { recall: null, text: recall.draft };
}

/** The caret sits on the box's first (last) line: there an arrow has no line to move to, so it walks the history. */
export const onFirstLine = (text: string, caret: number) => !text.slice(0, caret).includes("\n");
export const onLastLine = (text: string, caret: number) => !text.slice(caret).includes("\n");
