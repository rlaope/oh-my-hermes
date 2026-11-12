import { describe, expect, it } from "vitest";
import {
  AGENTS,
  folderName,
  INSTALL,
  isAgentId,
  missingNote,
  parentPath,
  parseRecent,
  pushRecent,
  RECENT_MAX,
  recentFolders,
  rowModel,
  terminalNote,
  tildePath,
  type Recent,
  type SessionRec,
} from "./agents";
import { MockHost } from "./host";

describe("session agents", () => {
  it("is the fixed list of nine, in menu order, matching the Rust allow-list", () => {
    expect(AGENTS.map((a) => a.id)).toEqual(["claude", "codex", "omo", "dsh", "omh", "pi", "omp", "grok", "opencode"]);
    expect(AGENTS.map((a) => a.label)).toEqual(["Claude Code", "Codex", "OmO", "DSH", "oh-my-hermes", "pi", "oh-my-pi", "Grok", "OpenCode"]);
    for (const a of AGENTS) expect(a.program).toBe(a.id);
  });

  it("opens claude, codex, omo, dsh, pi, omp and opencode as chats, omh as a Hermes chat, grok as a terminal (same as the Rust list)", () => {
    expect(AGENTS.map((a) => [a.id, a.mode])).toEqual([
      ["claude", "chat"],
      ["codex", "chat"],
      ["omo", "chat"],
      ["dsh", "chat"],
      ["omh", "hermes"],
      ["pi", "chat"],
      ["omp", "chat"],
      ["grok", "terminal"],
      ["opencode", "chat"],
    ]);
    // the Terminal toggle says whether the terminal view continues the conversation or starts fresh
    expect(terminalNote("claude")).toMatch(/continuing this conversation/);
    expect(terminalNote("codex")).toMatch(/starts Codex fresh/);
    expect(terminalNote("omh")).toMatch(/new terminal/);
  });

  it("accepts only those ids", () => {
    for (const id of ["claude", "codex", "omo", "dsh", "omh", "pi", "omp", "grok", "opencode"]) expect(isAgentId(id)).toBe(true);
    for (const bad of ["", "sh", "/bin/sh", "claude --yolo", "Claude", " claude", null, 1, {}]) expect(isAgentId(bad)).toBe(false);
  });

  it("names folders on macOS and Windows", () => {
    expect(folderName("/Users/k/code/oh-my-hermes")).toBe("oh-my-hermes");
    expect(folderName("/Users/k/code/x/")).toBe("x");
    expect(folderName("C:\\Users\\k\\proj")).toBe("proj");
    expect(folderName("C:\\")).toBe("C:\\");
    expect(folderName("/")).toBe("/");
    expect(tildePath("/Users/k/code", "/Users/k")).toBe("~/code");
    expect(tildePath("/Users/kim/code", "/Users/k")).toBe("/Users/kim/code");
    expect(tildePath("/Users/k", "/Users/k/")).toBe("~");
    expect(parentPath("~/code/x")).toBe("~/code");
    expect(parentPath("/x")).toBe("/");
    expect(parentPath("C:\\Users\\k\\proj")).toBe("C:\\Users\\k");
    expect(parentPath("x")).toBe("");
  });

  it("row model: folder as the title, agent and state below, live while running", () => {
    const base: SessionRec = { id: "s1", agent: "claude", cwd: "/Users/k/app", startedAt: 1_700_000_000_000, status: "running", view: "terminal" };
    expect(rowModel(base)).toEqual({ title: "app", titleSource: "folder", folder: "app", sub: "Claude Code", live: true, needsYou: false, mark: null, over: false, ts: 1_700_000_000 });
    expect(rowModel({ ...base, status: "starting" })).toMatchObject({ sub: "Claude Code · Starting…", live: true });
    expect(rowModel({ ...base, status: "exited", exitCode: 0 })).toMatchObject({ sub: "Claude Code · Ended", live: false });
    expect(rowModel({ ...base, status: "exited", exitCode: null }).sub).toBe("Claude Code · Ended");
    expect(rowModel({ ...base, agent: "codex", status: "exited", exitCode: 2 }).sub).toBe("Codex · Ended · exit 2");
    expect(rowModel({ ...base, agent: "omp", status: "failed" }).sub).toBe("oh-my-pi · Could not start");
  });

  it("row model: two folders of the same name show their parent, a unique name stays alone", () => {
    const at = (id: string, cwd: string): SessionRec => ({ id, agent: "claude", cwd, startedAt: 1, status: "running", view: "chat" });
    const cwds = ["/Users/k/work/web-app", "/Users/k/oss/web-app", "/Users/k/notes", "/Users/k/work/web-app"];
    const ctx = { cwds, home: "/Users/k" };
    expect(rowModel(at("a", cwds[0]), undefined, ctx)).toMatchObject({ title: "web-app", where: "~/work" });
    expect(rowModel(at("b", cwds[1]), undefined, ctx)).toMatchObject({ title: "web-app", where: "~/oss" });
    expect(rowModel(at("c", cwds[2]), undefined, ctx).where).toBeUndefined();
    // two sessions in the very same folder are not a clash of names
    expect(rowModel(at("d", "/Users/k/notes"), undefined, { cwds: ["/Users/k/notes", "/Users/k/notes"], home: "/Users/k" }).where).toBeUndefined();
    expect(rowModel(at("e", "C:\\a\\api"), undefined, { cwds: ["C:\\a\\api", "C:\\b\\api"], home: null }).where).toBe("C:\\a");
    expect(rowModel(at("f", cwds[0])).where).toBeUndefined();
  });

  it("row model: a named session shows its name on line 1 and the folder before the agent on line 2", () => {
    const base: SessionRec = { id: "s1", agent: "claude", cwd: "/Users/k/web-app", startedAt: 1, status: "running", view: "chat" };
    // first message summary
    expect(rowModel({ ...base, promptTitle: "Fix the login redirect" })).toMatchObject({
      title: "Fix the login redirect",
      titleSource: "prompt",
      folder: "web-app",
      sub: "web-app · Claude Code",
    });
    // the agent's own title wins over the summary, the person's name over both
    expect(rowModel({ ...base, promptTitle: "Fix the login redirect", agentTitle: "OAuth redirect loop" }).title).toBe("OAuth redirect loop");
    expect(rowModel({ ...base, promptTitle: "a", agentTitle: "b", title: "Mine" })).toMatchObject({ title: "Mine", titleSource: "person" });
    // blank names do not count
    expect(rowModel({ ...base, title: "  ", agentTitle: "", promptTitle: "x" })).toMatchObject({ title: "x", titleSource: "prompt" });
    // the state follows the agent
    expect(rowModel({ ...base, promptTitle: "Fix it", status: "exited", exitCode: 0 }).sub).toBe("web-app · Claude Code · Ended");
    expect(rowModel({ ...base, agentTitle: "t", status: "starting" }).sub).toBe("web-app · Claude Code · Starting…");
    // a clash of folder names: the parent goes with the folder on line 2, not after the name
    const ctx = { cwds: ["/Users/k/work/web-app", "/Users/k/oss/web-app"], home: "/Users/k" };
    const named = rowModel({ ...base, cwd: "/Users/k/work/web-app", agentTitle: "OAuth fix" }, undefined, ctx);
    expect(named).toMatchObject({ title: "OAuth fix", sub: "web-app · ~/work · Claude Code" });
    expect(named.where).toBeUndefined();
    // while the name is still the folder, the parent stays after it and line 2 is the agent alone
    expect(rowModel({ ...base, cwd: "/Users/k/oss/web-app" }, undefined, ctx)).toMatchObject({ title: "web-app", where: "~/oss", sub: "Claude Code" });
  });

  it("a missing agent's tooltip carries its install line, as text", () => {
    expect(missingNote("claude")).toBe("claude was not found on this computer · install: npm i -g @anthropic-ai/claude-code");
    expect(missingNote("codex")).toContain("npm i -g @openai/codex");
    expect(missingNote("codex")).toContain("bundled in the ChatGPT app is found too");
    // as each product's own docs give it: pi's npm package moved (the old one is deprecated), oh-my-pi's npm build
    // needs Bun (its installer does not), Grok has a one-line installer
    expect(missingNote("pi")).toBe("pi was not found on this computer · install: npm i -g --ignore-scripts @earendil-works/pi-coding-agent");
    expect(missingNote("omp")).toBe("omp was not found on this computer · install: curl -fsSL https://omp.sh/install | sh");
    expect(missingNote("grok")).toBe("grok was not found on this computer · install: curl -fsSL https://x.ai/cli/install.sh | bash");
    for (const a of AGENTS) expect(missingNote(a.id)).not.toMatch(/mariozechner|see .* docs|npm i -g @oh-my-pi/);
    // OpenCode's own docs (opencode.ai/v1/docs): the npm package is opencode-ai, its program `opencode`
    expect(missingNote("opencode")).toBe("opencode was not found on this computer · install: npm install -g opencode-ai");
    expect(Object.keys(INSTALL).sort()).toEqual(AGENTS.map((a) => a.id).sort());
  });

  it("row model of a chat: live only while a turn runs, needsYou while an approval waits (the line stays the agent)", () => {
    const chat: SessionRec = { id: "s2", agent: "codex", cwd: "/w/api", startedAt: 1, status: "running", view: "chat" };
    expect(rowModel(chat, { turn: false, needsYou: false })).toMatchObject({ live: false, needsYou: false, sub: "Codex" });
    expect(rowModel(chat, { turn: true, needsYou: false })).toMatchObject({ live: true, sub: "Codex" });
    expect(rowModel(chat, { turn: true, needsYou: true })).toMatchObject({ live: true, needsYou: true, sub: "Codex" });
    // an ended session never asks for anything
    expect(rowModel({ ...chat, status: "exited", exitCode: 0 }, { turn: true, needsYou: true })).toMatchObject({ live: false, needsYou: false, sub: "Codex · Ended" });
  });

  it("recent launches: newest first, one entry per folder, capped, malformed entries dropped", () => {
    let r = pushRecent([], { agent: "claude", cwd: "/a", at: 1 });
    r = pushRecent(r, { agent: "codex", cwd: "/b", at: 2 });
    r = pushRecent(r, { agent: "codex", cwd: "/a", at: 3 });
    expect(r.map((x) => `${x.agent}:${x.cwd}:${x.at}`)).toEqual(["codex:/a:3", "codex:/b:2"]);
    for (let i = 0; i < 10; i += 1) r = pushRecent(r, { agent: "omh", cwd: `/f${i}`, at: 10 + i });
    expect(r).toHaveLength(RECENT_MAX);
    expect(RECENT_MAX).toBe(5);
    expect(parseRecent(JSON.stringify(r))).toEqual(r);
    expect(parseRecent("not json")).toEqual([]);
    expect(parseRecent(JSON.stringify({ agent: "claude" }))).toEqual([]);
    expect(parseRecent(JSON.stringify([{ agent: "sh", cwd: "/", at: 1 }, { agent: "pi", cwd: "", at: 1 }, { agent: "pi", cwd: "/x", at: 2 }]))).toEqual([
      { agent: "pi", cwd: "/x", at: 2 },
    ]);
  });

  it("recent folders for the menu: distinct, newest first, at most 5, whichever agent used them", () => {
    const at = (cwd: string, t: number, agent: Recent["agent"] = "claude"): Recent => ({ agent, cwd, at: t });
    expect(recentFolders([])).toEqual([]);
    // a list saved by an older build: the same folder under two agents, not in time order
    expect(recentFolders([at("/a", 1), at("/b", 3, "codex"), at("/a", 2, "grok")])).toEqual(["/b", "/a"]);
    const many = Array.from({ length: 8 }, (_, i) => at(`/f${i}`, i));
    expect(recentFolders(many)).toEqual(["/f7", "/f6", "/f5", "/f4", "/f3"]);
  });
});

describe("mock session host", () => {
  it("prints a banner, echoes typing, answers a line and ends on exit", async () => {
    const g: Record<string, unknown> = {};
    const host = new MockHost(g);
    let out = "";
    let code: number | null | undefined;
    const id = await host.start("claude", "/Users/you/app", 80, 24, (d) => (out += d), (c) => (code = c));
    await new Promise((r) => setTimeout(r, 60));
    expect(out).toContain("Claude Code");
    expect(out).toContain("(mock)");
    await host.write(id, "hi\r");
    expect(out).toContain("you said:\x1b[0m hi");
    await host.write(id, "exit\r");
    await new Promise((r) => setTimeout(r, 30));
    expect(code).toBe(0);
    await expect(host.write(id, "x")).rejects.toThrow();
    expect((g.__omherSessionCalls as { op: string }[]).map((c) => c.op)).toEqual(["start", "write", "write", "write"]);
  });

  it("a mock chat agent: info, a turn with a tool and an answer, approval round trip, interrupt, exit", async () => {
    const g: Record<string, unknown> = {};
    const host = new MockHost(g);
    const ev: { event: string; [k: string]: unknown }[] = [];
    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const id = await host.chatStart("claude", "/w/app", (e) => ev.push(e));
    await wait(40);
    expect(ev.find((e) => e.event === "session.info")).toMatchObject({ model: "Opus 5.5" });
    await host.chatInput(id, { kind: "send", text: "hi" });
    await wait(900);
    expect(ev.map((e) => e.event)).toEqual(expect.arrayContaining(["turn.start", "tool.start", "tool.end", "delta", "message", "turn.end"]));
    expect(ev.find((e) => e.event === "message")?.text).toBe("(mock Claude Code) You said: hi");
    ev.length = 0;
    await host.chatInput(id, { kind: "send", text: "/approve" });
    await wait(200);
    const card = ev.find((e) => e.event === "approval.request")!;
    expect(card).toMatchObject({ command: "rm -rf ./build", choices: ["deny", "once", "session"] });
    await expect(host.chatInput(id, { kind: "approve", request_id: "nope", choice: "once" })).rejects.toThrow();
    await host.chatInput(id, { kind: "approve", request_id: String(card.request_id), choice: "session" });
    await wait(700);
    expect(ev.filter((e) => e.event === "message").pop()?.text).toContain("allowed for this session");
    await host.chatInput(id, { kind: "send", text: "/slow" });
    await host.chatInput(id, { kind: "interrupt" });
    await wait(60);
    // the turn ends, then (an agent that reports it) how full the context is
    expect(ev.filter((e) => e.event === "turn.end").pop()).toEqual({ event: "turn.end", outcome: "interrupted" });
    await host.chatClose(id);
    await expect(host.chatInput(id, { kind: "send", text: "x" })).rejects.toThrow();
    const ops = (g.__omherSessionCalls as { op: string; input?: unknown }[]).map((c) => c.op);
    expect(ops[0]).toBe("chat.start");
    expect(ops.filter((o) => o === "chat.close")).toHaveLength(1);
    expect(ops.filter((o) => o === "start")).toHaveLength(0); // a chat never starts a terminal
  });

  it("reports claude, codex and omh installed and omo, dsh, pi, omp, grok, opencode missing", async () => {
    const list = await new MockHost({}).agents();
    expect(list.filter((a) => a.path).map((a) => a.id)).toEqual(["claude", "codex", "omh"]);
    expect(list.filter((a) => !a.path).map((a) => a.id)).toEqual(["omo", "dsh", "pi", "omp", "grok", "opencode"]);
    expect(list.map((a) => a.mode)).toEqual(["chat", "chat", "chat", "chat", "hermes", "chat", "chat", "terminal", "chat"]);
  });
});
