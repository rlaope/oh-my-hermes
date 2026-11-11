// The working controls of a SESSIONS chat, as pure helpers: the permission modes an agent offers (Claude Code's own,
// Codex's per-turn approval + sandbox presets; never one that skips approvals or lifts the sandbox), the reasoning
// levels it reported, the commands and skills it reported for the `/` menu, and how full its context is.
//
// Events the adapters (src-tauri/src/agent_chat.rs, and the ACP adapter) send for these:
//   session.info      { mode?, effort? }                                   the mode / effort now in force
//   session.efforts   { levels: string[] }                                 the reasoning levels it takes
//   session.commands  { commands: [{name, description, hint, kind: "command"|"skill", prefix: "/"|"$"}] }
//                     (parsed and matched in src/chat/parts/commands.ts, the composer's `/` menu)
//   session.usage     { used, max }                                        context tokens in use and the window
//   message.queued / message.taken / message.dropped { id }                a message sent while a turn ran
import type { AgentId } from "./agents";
import { t, type Key } from "../i18n";

/** One permission mode a person can pick, by agent. The values are what the shell accepts (`modes_for`). */
export const MODES: Partial<Record<AgentId, readonly string[]>> = {
  claude: ["default", "plan", "acceptEdits"],
  codex: ["read-only", "ask", "auto"],
};

const MODE_LABEL: Record<string, Key> = {
  default: "ctl.mode.ask",
  plan: "ctl.mode.plan",
  acceptEdits: "ctl.mode.acceptEdits",
  "read-only": "ctl.mode.readOnly",
  ask: "ctl.mode.ask",
  auto: "ctl.mode.auto",
};
const MODE_HINT: Record<string, Key> = {
  default: "ctl.hint.claudeAsk",
  plan: "ctl.hint.plan",
  acceptEdits: "ctl.hint.acceptEdits",
  "read-only": "ctl.hint.readOnly",
  ask: "ctl.hint.codexAsk",
  auto: "ctl.hint.auto",
};

export const modesOf = (agent: AgentId): readonly string[] => MODES[agent] ?? [];
/** The mode's name as the composer row shows it; a mode the agent runs that omher does not offer reads "Agent's own". */
export const modeLabel = (mode: string | undefined): string => (mode && MODE_LABEL[mode] ? t(MODE_LABEL[mode]) : t("ctl.mode.own"));
export const modeHint = (mode: string): string => (MODE_HINT[mode] ? t(MODE_HINT[mode]) : "");

const LEVEL_LABEL: Record<string, Key> = {
  none: "lvl.none",
  off: "lvl.none",
  minimal: "ctl.lvl.minimal",
  low: "lvl.low",
  medium: "lvl.medium",
  high: "lvl.high",
  xhigh: "ctl.lvl.xhigh",
  max: "lvl.xhigh",
  ultra: "ctl.lvl.ultra",
};

/** A reasoning level as the agent names it, in the person's words. The bot chat calls `xhigh` "Max"; an agent that
 *  also has a `max` above `xhigh` gets "Extra high" for `xhigh` so the two never read the same. */
export function levelLabel(level: string, levels: readonly string[] = []): string {
  if (level === "xhigh" && !levels.includes("max")) return t("lvl.xhigh");
  const k = LEVEL_LABEL[level];
  return k ? t(k) : level ? level[0].toUpperCase() + level.slice(1) : "";
}

export const levelOptions = (levels: readonly string[]) => levels.map((value) => ({ value, label: levelLabel(value, levels) }));

/** How full the context is, as the agent counted it: "38k / 200k · 19%". Null when it said nothing usable. */
export function usageText(u: { used: number; max: number } | undefined): { text: string; pct: number } | null {
  if (!u || !(u.max > 0) || !(u.used >= 0)) return null;
  const pct = Math.min(100, Math.round((u.used / u.max) * 100));
  return { text: t("ctl.context", { used: tokens(u.used), max: tokens(u.max), pct }), pct };
}

/** 950 -> "950", 41250 -> "41k", 1000000 -> "1M", 1250000 -> "1.3M". */
export function tokens(n: number): string {
  if (n < 1000) return String(Math.round(n));
  if (n < 1_000_000) return `${Math.round(n / 1000)}k`;
  const m = n / 1_000_000;
  return `${Number.isInteger(Math.round(m * 10) / 10) ? Math.round(m) : (Math.round(m * 10) / 10).toFixed(1)}M`;
}
