// A TERMINALS Shell row where the person ran Claude Code, Codex or oh-my-hermes: what is kept of that CLI so that
// after omher restarts the row's fresh shell puts it back (rule 11). Only the CLI (one of these three ids) and, for
// Claude Code and Codex, its conversation id (a UUID) are kept with the row; the one line typed after the restart is
// built from a fixed program name and that checked UUID, never from saved text.
import type { SavedSession } from "../app/resume";
import { isShell } from "./agents";

/** The foreground CLIs a Shell row brings back. */
export type FgCli = "claude" | "codex" | "omh";
export const isFgCli = (v: unknown): v is FgCli => v === "claude" || v === "codex" || v === "omh";
/** The CLIs whose conversation a Shell row learns (`claudeConversation`, `codexConversation`). */
export const fgHasId = (cli: FgCli): cli is "claude" | "codex" => cli !== "omh";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
/** `8-4-4-4-12` hex digits, nothing else (as the shell's `is_uuid`). */
export const isUuid = (v: unknown): v is string => typeof v === "string" && UUID.test(v);

/** The line (without its Enter) that puts `cli` back in a fresh shell: `claude --resume <id>`, `codex resume <id>` or
 *  `omh`; null when Claude Code or Codex has no id that is a UUID. */
export function fgLine(cli: FgCli, id?: string): string | null {
  if (cli === "omh") return "omh";
  if (!isUuid(id)) return null;
  return cli === "claude" ? `claude --resume ${id}` : `codex resume ${id}`;
}

/** What a saved row's fresh shell types once it is ready after a restart: the line for a Shell row that was running
 *  with one of these CLIs in front (and, for Claude Code and Codex, its conversation id); null for any other row (it
 *  comes back as before: a Shell row that was running comes back paused, and types nothing). */
export function restoreLine(s: Pick<SavedSession, "agent" | "running" | "fgCli" | "fgSession">): string | null {
  if (!isShell(s.agent) || !s.running || !isFgCli(s.fgCli)) return null;
  return fgLine(s.fgCli, s.fgSession);
}
