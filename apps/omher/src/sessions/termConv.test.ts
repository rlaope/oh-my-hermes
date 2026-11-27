import { describe, expect, it } from "vitest";
import { GIVES_ID, learns, normDir, otherInFolder, TERM_CONTINUES, termStart, type FolderRow } from "./termConv";

const ID = "0e2c5a8e-6c1b-4f7e-9a3d-2b1c4d5e6f70";
const NEW = "11111111-2222-4333-8444-555555555555";
const make = () => NEW;

describe("termStart", () => {
  it("a new terminal gets an id omher made only where the CLI takes one", () => {
    for (const agent of ["claude", "gemini", "qwen", "grok", "copilot", "pi"]) expect(termStart({ agent }, make), agent).toEqual({ again: false, sessionId: NEW });
    for (const agent of ["codex", "agy", "omo", "omp", "opencode", "kimi", "cline", "omh", "shell"]) expect(termStart({ agent }, make), agent).toEqual({ again: false });
  });

  it("a kept id continues by each agent's own way", () => {
    for (const agent of ["claude", "codex", "agy"]) expect(termStart({ agent, agentSession: ID }, make), agent).toEqual({ again: true, resume: ID });
    for (const agent of ["gemini", "qwen", "grok"]) expect(termStart({ agent, agentSession: ID, used: true }, make), agent).toEqual({ again: true, resume: ID });
    // Copilot CLI and pi open the conversation by the same --session-id
    for (const agent of ["copilot", "pi"]) expect(termStart({ agent, agentSession: ID }, make), agent).toEqual({ again: true, sessionId: ID });
  });

  it("a Gemini CLI, Qwen Code or Grok conversation nobody used starts as a new one; a titled one continues", () => {
    for (const agent of ["gemini", "qwen", "grok"]) {
      expect(termStart({ agent, agentSession: ID }, make), agent).toEqual({ again: false, sessionId: NEW });
      expect(termStart({ agent, agentSession: ID, agentTitle: "fix the build" }, make), agent).toEqual({ again: true, resume: ID });
    }
  });

  it("an agent that cannot continue ignores a kept id (an older omher's row) and starts fresh", () => {
    for (const agent of ["opencode", "kimi", "cline", "omp", "omo"]) expect(termStart({ agent, agentSession: ID, used: true }, make), agent).toEqual({ again: false });
  });

  it("the lists agree", () => {
    expect([...TERM_CONTINUES].sort()).toEqual([...GIVES_ID, "codex", "agy"].sort());
    expect(["codex", "agy"].every(learns)).toBe(true);
    expect(["claude", "gemini", "opencode"].some(learns)).toBe(false);
  });
});

describe("one Antigravity per folder", () => {
  const row = (o: Partial<FolderRow> & { id: string }): FolderRow => ({ agent: "agy", cwd: "/w/app", terminal: true, live: true, ...o });
  const self = { id: "s1", cwd: "/w/app" };
  it("folders compare as the cache keys them", () => {
    expect(normDir("/w/app/")).toBe("/w/app");
    expect(normDir("/")).toBe("/");
    expect(normDir("C:\\Users\\Me\\App\\")).toBe(normDir("c:/users/me/app"));
    expect(normDir("/w/App")).not.toBe(normDir("/w/app"));
  });
  it("another running TERMINALS Antigravity, or a Shell row with it in front, in the same folder counts", () => {
    expect(otherInFolder("agy", self, [row({ id: "s1" })])).toBe(false);
    expect(otherInFolder("agy", self, [row({ id: "s2", cwd: "/w/app/" })])).toBe(true);
    expect(otherInFolder("agy", self, [row({ id: "s2", agent: "shell", fgAgent: "agy" })])).toBe(true);
    expect(otherInFolder("agy", { id: "s1", cwd: "C:\\W\\App" }, [row({ id: "s2", cwd: "c:/w/app/" })])).toBe(true);
  });
  it("a chat row, an ended row, another folder or another CLI does not", () => {
    expect(otherInFolder("agy", self, [row({ id: "s2", terminal: false })])).toBe(false);
    expect(otherInFolder("agy", self, [row({ id: "s2", live: false })])).toBe(false);
    expect(otherInFolder("agy", self, [row({ id: "s2", cwd: "/w/other" })])).toBe(false);
    expect(otherInFolder("agy", self, [row({ id: "s2", agent: "shell", fgAgent: "codex" })])).toBe(false);
  });
});
