import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { TermRowMark } from "./TermRowMark";
import { termCli, termMarkAgent, termStatus, termGroups, BUSY_MS, isTerminalRec, terminalAgents, type AgentInfo } from "./agents";

const html = (agent: string | null, live = false) => renderToStaticMarkup(<TermRowMark agent={agent} live={live} />);

describe("TermRowMark", () => {
  it("shows the shell icon when no CLI runs in the foreground", () => {
    expect(html(null)).toContain('data-agent="shell"');
    expect(html(null)).not.toContain("hn-mk");
  });
  it.each([
    ["claude", "claude"],
    ["codex", "codex"],
    ["grok", "grok"],
    ["opencode", "opencode"],
    ["gemini", "gemini"],
    ["omh", "omh"],
    ["pi", "pi"],
    ["omp", "omp"],
    ["omo", "omo"],
  ])("a fake fgAgent %s draws that CLI's official mark", (fg, id) => {
    const out = html(fg);
    expect(out).toContain(`data-agent="${id}"`);
    expect(out).toContain(`data-harness="${id}"`);
  });
  it("an unknown foreground program gets the neutral mark, never a company logo", () => {
    expect(html("htop")).toContain('data-harness="generic"');
  });
  it("live adds the ring, idle has none", () => {
    expect(html("claude", true)).toContain('class="trm live"');
    expect(html("claude", false)).toContain('class="trm"');
  });
});

describe("terminal rows", () => {
  it("the mark follows fgAgent, then the session's own agent, then the shell", () => {
    expect(termMarkAgent({ agent: "shell", fgAgent: "codex" })).toBe("codex");
    expect(termMarkAgent({ agent: "claude", fgAgent: null })).toBe("claude");
    expect(termMarkAgent({ agent: "shell", fgAgent: null })).toBeNull();
    expect(termCli({ agent: "shell", fgAgent: null })).toBe("shell");
    expect(termCli({ agent: "shell", fgAgent: "claude" })).toBe("claude");
  });
  it("status: spinner while output flows, nothing idle, check on 0, x otherwise", () => {
    const now = 100_000;
    expect(termStatus({ status: "running", lastOut: now - 500 }, undefined, now)).toBe("busy");
    expect(termStatus({ status: "running", lastOut: now - BUSY_MS - 1 }, undefined, now)).toBeNull();
    expect(termStatus({ status: "exited", exitCode: 0 }, undefined, now)).toBe("ok");
    expect(termStatus({ status: "exited", exitCode: 2 }, undefined, now)).toBe("err");
    expect(termStatus({ status: "exited", exitCode: null }, undefined, now)).toBeNull();
    expect(termStatus({ status: "failed" }, undefined, now)).toBe("err");
    expect(termStatus({ status: "running" }, "bell", now)).toBe("bell");
  });
  it("groups by folder in first-seen order", () => {
    const g = termGroups([{ cwd: "/a" }, { cwd: "/b" }, { cwd: "/a" }]);
    expect(g.map((x) => [x.cwd, x.rows.length])).toEqual([["/a", 2], ["/b", 1]]);
  });
  it("only terminal sessions are listed: a saved chat-mode session is not", () => {
    expect(isTerminalRec(null, { agent: "claude", open: "terminal", status: "running" })).toBe(true);
    expect(isTerminalRec(null, { agent: "shell", status: "running" })).toBe(true);
    expect(isTerminalRec(null, { agent: "grok", status: "exited" })).toBe(true);
    expect(isTerminalRec(null, { agent: "claude", status: "exited" })).toBe(false);
    expect(isTerminalRec(null, { agent: "omh", status: "running" })).toBe(false);
    expect(isTerminalRec(null, { agent: "claude", status: "draft" })).toBe(false);
  });
  it("the + menu offers only agents with a terminal view", () => {
    const info = (id: string, via?: "hermes"): AgentInfo => ({ id, label: id, path: `/bin/${id}`, ...(via ? { via } : {}) });
    const ids = terminalAgents([info("claude"), info("dsh"), info("codex"), info("grok"), info("omh", "hermes")], []).shown.map((a) => a.id);
    expect(ids).toEqual(["claude", "codex", "grok"]);
  });
});
