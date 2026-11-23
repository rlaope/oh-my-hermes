// Reasoning levels as the bridge names them: the ones the connected Hermes accepts, in Hermes' order. The pill and
// controls show each level by its own name (none, minimal, low, medium, high, xhigh, max, ultra) in every language:
// they are settings values, the same words Hermes, Codex and Claude Code use, so they are never translated or renamed.
export const LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"] as const;

export const reasoningLabel = (r: string) => r;

/** Segmented-control options for the levels a bot offers (falls back to Hermes' full ladder). */
export function levelOptions(levels?: string[]): { value: string; label: string }[] {
  const list = levels?.length ? levels : [...LEVELS];
  return list.map((value) => ({ value, label: reasoningLabel(value) }));
}
