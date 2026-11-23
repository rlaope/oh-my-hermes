import { t } from "../../i18n";

// Reasoning levels as the bridge names them: the ones the connected Hermes accepts, in Hermes' order. The pill and
// controls show each level by its own name (none, minimal, low, medium, high, xhigh, max, ultra) in every language:
// they are settings values, the same words Hermes, Codex and Claude Code use, so they are never translated or renamed.
export const LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"] as const;

export const reasoningLabel = (r: string) => r;

/** The level the route sends instead of the pick, when Hermes says it clamps it (`reasoning_wire`), else "". Hermes'
 *  own pickers say "ultra (sends max on this route)", so a Hermes-internal step never reads as a level the route has. */
export const sentInstead = (reasoning: string, wire?: string): string =>
  wire && reasoning && wire !== reasoning ? wire : "";

/** The pill's reasoning text: the level, plus what the route sends when that differs ("ultra · sends max"). */
export function reasoningPill(reasoning: string, wire?: string): string {
  const sent = sentInstead(reasoning, wire);
  return sent ? t("mp.pillSends", { level: reasoningLabel(reasoning), sent }) : reasoningLabel(reasoning);
}

/** Segmented-control options for the levels a bot offers (falls back to Hermes' full ladder). */
export function levelOptions(levels?: string[]): { value: string; label: string }[] {
  const list = levels?.length ? levels : [...LEVELS];
  return list.map((value) => ({ value, label: reasoningLabel(value) }));
}
