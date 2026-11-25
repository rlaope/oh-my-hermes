// Reasoning levels as the bridge names them: the ones the bot's route really sends, in Hermes' order. The pill and
// controls show each level by its own name (none, minimal, low, medium, high, xhigh, max, ultra) in every language:
// they are settings values, the same words Hermes, Codex and Claude Code use, so they are never translated or renamed.
export const LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"] as const;

export const reasoningLabel = (r: string) => r;

/** The level the chat really runs at: what the route sends (Hermes' `reasoning_wire`) when Hermes says, else the
 *  pick. A saved level the route clamps (`ultra` on a Claude route sends `max`) therefore reads, and is selected, as
 *  the level sent, so a Hermes-internal step never shows as a level the route has. */
export const sentLevel = (reasoning: string, wire?: string): string => (reasoning && wire ? wire : reasoning);

/** The pill's reasoning text: the level the route sends. */
export const reasoningPill = (reasoning: string, wire?: string): string => reasoningLabel(sentLevel(reasoning, wire));

/** Segmented-control options for the levels the bot's route sends (falls back to Hermes' full ladder). */
export function levelOptions(levels?: string[]): { value: string; label: string }[] {
  const list = levels?.length ? levels : [...LEVELS];
  return list.map((value) => ({ value, label: reasoningLabel(value) }));
}
