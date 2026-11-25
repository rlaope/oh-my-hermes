import { describe, expect, it } from "vitest";
import { fgLine, isUuid, restoreLine } from "./fgResume";
import { parseResume, RESUME_VERSION, type SavedSession } from "../app/resume";

const ID = "5d0f3c2a-9b1e-4c7d-8a6f-0e1d2c3b4a59";
const T = 1_800_000_000_000;

/** One saved row as the snapshot holds it, read back through parseResume (what a restart sees). */
const back = (row: Record<string, unknown>): SavedSession => {
  const snap = { v: RESUME_VERSION, at: T, bot: null, view: "chat", session: null, panelOpen: false, panelTab: "details", runsFull: false, runId: null, drafts: {}, sessions: [{ id: "s1", cwd: "/w/app", startedAt: T, view: "terminal", ...row }] };
  return parseResume(JSON.stringify(snap))!.sessions[0];
};

describe("the line a Shell row's fresh shell types", () => {
  it("is a fixed program name and a checked UUID, nothing else", () => {
    expect(fgLine("claude", ID)).toBe(`claude --resume ${ID}`);
    expect(fgLine("codex", ID)).toBe(`codex resume ${ID}`);
    expect(fgLine("omh")).toBe("omh");
    // oh-my-hermes takes no id from omher, whatever was saved
    expect(fgLine("omh", ID)).toBe("omh");
  });

  it("refuses anything that is not a UUID", () => {
    for (const bad of [undefined, "", "abc", `${ID} --dangerously-skip-permissions`, `${ID}\r`, `${ID};rm -rf ~`, `$(id)`, ID.slice(1), `${ID}0`, ID.replace(/-/g, ""), " " + ID]) {
      expect(fgLine("claude", bad), String(bad)).toBeNull();
      expect(fgLine("codex", bad), String(bad)).toBeNull();
    }
    expect(isUuid(ID.toUpperCase())).toBe(true);
    expect(isUuid(42)).toBe(false);
  });
});

describe("what a saved row comes back as after a restart", () => {
  it("a Shell row with Claude Code and its id types `claude --resume <id>`", () => {
    expect(restoreLine(back({ agent: "shell", running: true, fgCli: "claude", fgSession: ID }))).toBe(`claude --resume ${ID}`);
  });

  it("a Shell row with Codex and its id types `codex resume <id>`", () => {
    expect(restoreLine(back({ agent: "shell", running: true, fgCli: "codex", fgSession: ID }))).toBe(`codex resume ${ID}`);
  });

  it("a Shell row with oh-my-hermes types `omh`", () => {
    expect(restoreLine(back({ agent: "shell", running: true, fgCli: "omh" }))).toBe("omh");
  });

  it("a Shell row whose Claude Code or Codex had no id yet types nothing (it comes back paused)", () => {
    expect(restoreLine(back({ agent: "shell", running: true, fgCli: "claude" }))).toBeNull();
    expect(restoreLine(back({ agent: "shell", running: true, fgCli: "codex" }))).toBeNull();
    // a saved id that is not a UUID is not read
    const odd = back({ agent: "shell", running: true, fgCli: "claude", fgSession: "../x" });
    expect(odd.fgSession).toBeUndefined();
    expect(restoreLine(odd)).toBeNull();
  });

  it("a plain Shell row types nothing", () => {
    expect(restoreLine(back({ agent: "shell", running: true }))).toBeNull();
  });

  it("data saved before these fields existed loads and types nothing", () => {
    const old = back({ agent: "shell", running: true, shell: "unix:/bin/zsh" });
    expect(old).toMatchObject({ id: "s1", agent: "shell", running: true });
    expect(old.fgCli).toBeUndefined();
    expect(old.fgSession).toBeUndefined();
    expect(restoreLine(old)).toBeNull();
  });

  it("only a running Shell row with one of the three CLIs keeps them", () => {
    // ended: nothing is put back
    expect(back({ agent: "shell", running: false, fgCli: "claude", fgSession: ID }).fgCli).toBeUndefined();
    // another CLI than these three, or a row that is not a Shell row
    expect(back({ agent: "shell", running: true, fgCli: "gemini" }).fgCli).toBeUndefined();
    expect(back({ agent: "claude", running: true, fgCli: "claude", fgSession: ID }).fgCli).toBeUndefined();
    expect(restoreLine({ agent: "claude", running: true, fgCli: "claude", fgSession: ID })).toBeNull();
    // an id saved for oh-my-hermes is not kept
    expect(back({ agent: "shell", running: true, fgCli: "omh", fgSession: ID }).fgSession).toBeUndefined();
    // an upper-case id is kept as the lower-case one the shell names
    expect(back({ agent: "shell", running: true, fgCli: "codex", fgSession: ID.toUpperCase() }).fgSession).toBe(ID);
  });
});
