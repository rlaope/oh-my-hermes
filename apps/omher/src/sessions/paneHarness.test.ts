import { describe, expect, it } from "vitest";
import { paneHarness } from "./paneHarness";
import { sessionRunId } from "./SessionPlans";

const SID = "11111111-2222-4333-8444-555555555555";

describe("paneHarness: the harness a pane runs and where its records are", () => {
  it("a Shell row with Claude Code typed in it is Claude Code, its run found by the conversation the shell named", () => {
    const h = paneHarness({ agent: "shell", fgAgent: "claude", fgSession: SID });
    expect(h).toEqual({ cli: "claude", inShell: true, runAgent: "claude", session: SID, runId: `claude:${SID}`, titled: { agent: "claude", session: SID } });
  });

  it("before the shell names the conversation: the harness, no run and no title read", () => {
    expect(paneHarness({ agent: "shell", fgAgent: "claude" })).toMatchObject({ cli: "claude", runId: null, titled: null });
  });

  it("codex in a shell reads the same way; grok and pi have no conversation id from the shell", () => {
    expect(paneHarness({ agent: "shell", fgAgent: "codex", fgSession: SID })).toMatchObject({ runId: `codex:${SID}`, titled: { agent: "codex", session: SID } });
    expect(paneHarness({ agent: "shell", fgAgent: "grok" })).toMatchObject({ cli: "grok", runAgent: "grok", runId: null, titled: null });
  });

  it("a conversation id kept after its CLI left the front is not used, and a plain shell is no harness", () => {
    expect(paneHarness({ agent: "shell", fgAgent: null, fgSession: SID })).toEqual({ cli: null, inShell: true, runAgent: null, session: null, runId: null, titled: null });
  });

  it("an agent row is its agent, with its own session id", () => {
    expect(paneHarness({ agent: "claude", agentSession: SID })).toMatchObject({ cli: "claude", inShell: false, runId: `claude:${SID}` });
    expect(paneHarness({ agent: "opencode", agentSession: SID })).toMatchObject({ cli: "opencode", runAgent: null, runId: null, titled: null });
  });
});

describe("sessionRunId: the Plans run of a pane", () => {
  it("a Shell row running Claude Code finds that conversation's run (it found none before)", () => {
    expect(sessionRunId({ agent: "shell", fgAgent: "claude", fgSession: SID })).toBe(`claude:${SID}`);
    expect(sessionRunId({ agent: "claude", agentSession: SID })).toBe(`claude:${SID}`);
    expect(sessionRunId({ agent: "shell", fgAgent: null })).toBeNull();
  });
});
