// How a TERMINALS agent's own conversation is tied to its row, so that it comes back by itself after omher restarts
// (an update, a quit and reopen) and on Restart. Each agent's way is from its own CLI's help or docs; the shell
// (src-tauri/src/sessions.rs `terminal_args`) checks every id is a UUID and refuses any other agent.
//
// - an id omher makes and gives at the start (`--session-id <uuid>`, [`GIVES_ID`]): Claude Code, Gemini CLI, Qwen Code,
//   Grok, Copilot CLI and pi. Claude Code, Gemini CLI, Qwen Code and Grok continue it with `--resume <id>`; Copilot CLI
//   and pi with the same `--session-id <id>`, which opens that conversation ([`OPENS_BY_ID`]).
// - an id learned once the CLI runs, by asking the shell about the row's own pty ([`LEARNS`]): Codex (the rollout it
//   holds open; `codex resume <id>`) and Antigravity (its workspace cache for the row's folder; `agy --conversation`).
// - none: OpenCode, Kimi Code, Cline, oh-my-pi and OmO make their ids themselves and keep them where omher cannot tell
//   one terminal's from another's, so they come back paused and Resume starts a new conversation.
import type { AgentId } from "./agents";

/** TERMINALS agents omher starts under a conversation id it makes (`--session-id`, the shell's `TERM_GIVES_ID`). */
export const GIVES_ID: readonly AgentId[] = ["claude", "gemini", "qwen", "grok", "copilot", "pi"];
/** Of those, the ones whose `--session-id` opens the conversation when it is there: they continue by it. */
export const OPENS_BY_ID: readonly AgentId[] = ["copilot", "pi"];
/** Of those, the ones that write a conversation only on its first message and refuse a `--resume` of one they never
 *  wrote: one nobody used starts as a new one instead. (Claude Code has its own look first: sessions.ts `convState`.) */
export const FRESH_IF_UNUSED: readonly AgentId[] = ["gemini", "qwen", "grok"];
/** TERMINALS agents whose conversation id omher learns after they start (sessions.ts `findTermId`). */
export type Learner = "codex" | "agy";
export const LEARNS: readonly Learner[] = ["codex", "agy"];
export const learns = (a: AgentId): a is Learner => (LEARNS as readonly AgentId[]).includes(a);
/** Antigravity keeps one id per folder: a row learns it only while no other Antigravity runs in a TERMINALS row in
 *  that folder ([`otherInFolder`]). */
export const ONE_PER_FOLDER: readonly AgentId[] = ["agy"];

/** A folder as the CLI's cache keys it, for comparing two of them: no trailing separator; a Windows path (a drive
 *  letter or a backslash) with backslashes and in one case, as Windows compares names. Links are not resolved here (the
 *  shell also tries the resolved path; a row whose folder is a link to another row's may still be asked). */
export function normDir(p: string): string {
  const s = p.replace(/[\\/]+$/, "") || p.slice(0, 1);
  return /^[A-Za-z]:/.test(s) || s.includes("\\") ? s.replace(/\//g, "\\").toLowerCase() : s;
}

/** A TERMINALS row as [`otherInFolder`] reads it: its own agent, the CLI in its foreground (a Shell row's), the folder
 *  it runs in, whether it is a terminal row and whether its program runs. */
export interface FolderRow {
  id: string;
  agent: AgentId;
  fgAgent?: string | null;
  cwd: string;
  terminal: boolean;
  live: boolean;
}

/** Whether another TERMINALS row than `self` runs `agent` in `self`'s folder: a row of that agent, or a Shell row with
 *  that CLI in front (both write the same per-folder cache). Chat rows do not count. */
export function otherInFolder(agent: AgentId, self: { id: string; cwd: string }, rows: readonly FolderRow[]): boolean {
  const here = normDir(self.cwd);
  return rows.some((o) => o.id !== self.id && o.terminal && o.live && (o.agent === agent || o.fgAgent === agent) && normDir(o.cwd) === here);
}
/** TERMINALS agents that continue their own conversation after omher restarts. */
export const TERM_CONTINUES: readonly AgentId[] = [...new Set<AgentId>([...GIVES_ID, ...LEARNS])];

/** What a TERMINALS row's CLI starts with: `again` it continues the row's conversation (`resume`: by the agent's resume
 *  flag; `sessionId` of an agent that opens by it), or it starts a new one (`sessionId`: an id `make` made, for an agent
 *  omher gives one; none for the rest). */
export function termStart(
  r: { agent: AgentId; agentSession?: string; used?: boolean; agentTitle?: string },
  make: () => string,
): { again: boolean; resume?: string; sessionId?: string } {
  const has = !!r.agentSession && TERM_CONTINUES.includes(r.agent);
  const unused = FRESH_IF_UNUSED.includes(r.agent) && !(r.used || r.agentTitle);
  if (has && !unused) return OPENS_BY_ID.includes(r.agent) ? { again: true, sessionId: r.agentSession } : { again: true, resume: r.agentSession };
  return GIVES_ID.includes(r.agent) ? { again: false, sessionId: make() } : { again: false };
}
/** TERMINALS agents that reopen their own dropped session after omher restarts with no id from omher: oh-my-hermes
 *  (`omh`) is told its row's link (`OMHER_TERMINAL_LINK`, rule 11) and reopens the session it dropped under that
 *  terminal by itself (OMH's auto-resume), so it needs no conversation id. */
export const TERM_REOPENS: readonly AgentId[] = ["omh"];
/** Whether a TERMINALS session that was running when omher closed starts again by itself after the restart. */
export const termComesBack = (s: { agent: AgentId; agentSession?: string }): boolean =>
  TERM_REOPENS.includes(s.agent) || (!!s.agentSession && TERM_CONTINUES.includes(s.agent));
