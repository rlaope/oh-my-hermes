// Reasoning levels as the bridge names them. The pill and controls show each level by its own name (none, low,
// medium, high, xhigh, max) in every language: they are settings values, the same words Hermes, Codex and Claude Code
// use, so they are never translated or renamed.
export const LEVELS = ["none", "low", "medium", "high", "xhigh"] as const;

export const reasoningLabel = (r: string) => r;

/** Segmented-control options for the levels a bot offers (falls back to the five v0.1 levels). */
export function levelOptions(levels?: string[]): { value: string; label: string }[] {
  const list = levels?.length ? levels : [...LEVELS];
  return list.map((value) => ({ value, label: reasoningLabel(value) }));
}
