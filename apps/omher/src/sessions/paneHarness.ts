// What a TERMINALS pane (or a SESSIONS row) runs, for the right panel: the harness in front and where its own records
// are. A Shell row with `claude` typed in it is Claude Code (its `fgAgent`, and the conversation id the shell named,
// `fgSession`); an agent row is its agent (`agentSession`). Nothing is guessed: a CLI the shell does not report, or a
// conversation it has not named yet, leaves the field empty.
import { CLI_AGENTS, type CliAgent } from "../lib/runs";
import { isShell, type SessionRec } from "./agents";

export interface PaneHarness {
  /** The harness program in front (`claude`, `codex`, `grok`…), or null for a plain shell. */
  cli: string | null;
  /** It runs inside a Shell row (typed there), not as the row's own agent. */
  inShell: boolean;
  /** The CLI whose own records omher reads (`runs.cli`), when it is one of those. */
  runAgent: CliAgent | null;
  /** That CLI's conversation id, once known. */
  session: string | null;
  /** The Plans graph's run id (`<agent>:<conversation id>`), when both are known. */
  runId: string | null;
  /** Claude Code or Codex with a known conversation: its title (and Claude Code's model) come from `cli.title`. */
  titled: { agent: "claude" | "codex"; session: string } | null;
}

export function paneHarness(rec: Pick<SessionRec, "agent" | "agentSession" | "fgAgent" | "fgSession">): PaneHarness {
  const inShell = isShell(rec.agent);
  const cli = inShell ? (rec.fgAgent ?? null) : rec.agent;
  // a Shell row's conversation id belongs to the CLI in its front only (setSessionFg clears it when that CLI leaves)
  const session = (inShell ? (rec.fgAgent ? rec.fgSession : undefined) : rec.agentSession) ?? null;
  const runAgent = cli && (CLI_AGENTS as string[]).includes(cli) ? (cli as CliAgent) : null;
  return {
    cli,
    inShell,
    runAgent,
    session,
    runId: runAgent && session ? `${runAgent}:${session}` : null,
    titled: session && (cli === "claude" || cli === "codex") ? { agent: cli, session } : null,
  };
}
