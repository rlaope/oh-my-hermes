// Reasoning levels as the bridge names them, and the short labels the pill and controls show.
export const LEVELS = ["none", "low", "medium", "high", "xhigh"] as const;

const LABEL: Record<string, string> = { none: "Off", low: "Low", medium: "Med", high: "High", xhigh: "Max" };

export const reasoningLabel = (r: string) => LABEL[r] ?? (r ? r[0].toUpperCase() + r.slice(1) : "");

/** Segmented-control options for the levels a bot offers (falls back to the five v0.1 levels). */
export function levelOptions(levels?: string[]): { value: string; label: string }[] {
  const list = levels?.length ? levels : [...LEVELS];
  return list.map((value) => ({ value, label: reasoningLabel(value) }));
}
