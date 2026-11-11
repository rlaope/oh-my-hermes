// Reasoning levels as the bridge names them, and the short labels the pill and controls show.
export const LEVELS = ["none", "low", "medium", "high", "xhigh"] as const;

import { t, type Key } from "../../i18n";

const LABEL: Record<string, Key> = { none: "lvl.none", low: "lvl.low", medium: "lvl.medium", high: "lvl.high", xhigh: "lvl.xhigh" };

export const reasoningLabel = (r: string) => (LABEL[r] ? t(LABEL[r]) : r ? r[0].toUpperCase() + r.slice(1) : "");

/** Segmented-control options for the levels a bot offers (falls back to the five v0.1 levels). */
export function levelOptions(levels?: string[]): { value: string; label: string }[] {
  const list = levels?.length ? levels : [...LEVELS];
  return list.map((value) => ({ value, label: reasoningLabel(value) }));
}
