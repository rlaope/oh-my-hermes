// Pure helpers of the bot page's sections (BotSections.tsx): what a profile file's state says, how full a memory
// target is, which automations and sessions are this bot's, and the chat drafts Edit puts in the composer. Nothing
// here reads or writes anything.
import type { Automation, Away, BotSoul, MemoryTarget } from "../lib/protocol";
import { fileSize } from "../chat/parts/mediaLines";
import { t } from "../i18n";

/** The largest file the bridge reads for this page (its MEMORY_FILE_BYTES). */
export const PAGE_FILE_MAX = 1 << 20;

/** Why a file shows no text, in a sentence; null when it was read. `missing` is each section's own empty state. */
export function fileProblem(f: Pick<BotSoul, "state" | "size" | "file">): string | null {
  switch (f.state) {
    case "too_big":
      return t("bp.tooBig", { file: f.file, size: fileSize(f.size ?? 0), max: fileSize(PAGE_FILE_MAX) });
    case "unreadable":
      return t("bp.unreadable", { file: f.file });
    case "link":
      return t("bp.link", { file: f.file });
    default:
      return null;
  }
}

/** A memory target's use of its limit: the share (0-100, rounded) and whether it is over (Hermes refuses adds then).
 *  A limit of 0 or below is what Hermes enforces too: nothing fits, so any entry is over it. */
export function memoryUse(m: Pick<MemoryTarget, "chars" | "limit">): { pct: number; over: boolean } {
  const over = m.chars > m.limit;
  if (m.limit <= 0) return { pct: m.chars > 0 ? 100 : 0, over };
  return { pct: Math.min(100, Math.round((m.chars / m.limit) * 100)), over };
}

/** This bot's automations, by name. */
export function botAutomations(list: readonly Automation[] | null, bot: string): Automation[] {
  return (list ?? []).filter((a) => a.bot === bot).sort((x, y) => x.name.localeCompare(y.name));
}

/** This bot's sessions elsewhere: running ones first, then the most recent. */
export function botElsewhere(away: readonly Away[] | undefined): Away[] {
  return [...(away ?? [])].sort((x, y) => Number(y.running) - Number(x.running) || y.last_active - x.last_active);
}

export type DraftKind = "soul" | "memory" | "user";

/** What Edit puts in the bot's main chat composer, for the person to finish: a request to the bot, never a write. */
export function editDraft(kind: DraftKind): string {
  return kind === "soul" ? t("bp.draftSoul") : kind === "memory" ? t("bp.draftMemory") : t("bp.draftUser");
}
