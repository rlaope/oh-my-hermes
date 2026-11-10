import { describe, expect, it } from "vitest";
import {
  AGENTS,
  folderName,
  isAgentId,
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
  it("is the fixed list of six, in menu order, matching the Rust allow-list", () => {
    expect(AGENTS.map((a) => a.id)).toEqual(["claude", "codex", "omh", "pi", "omp", "grok"]);
    expect(AGENTS.map((a) => a.label)).toEqual(["Claude Code", "Codex", "oh-my-hermes", "pi", "oh-my-pi", "Grok"]);
    for (const a of AGENTS) expect(a.program).toBe(a.id);
  });

  it("opens claude, codex, pi and omp as chats, omh as a Hermes chat, grok as a terminal (same as the Rust list)", () => {
    expect(AGENTS.map((a) => [a.id, a.mode])).toEqual([
      ["claude", "chat"],
      ["codex", "chat"],
      ["omh", "hermes"],
      ["pi", "chat"],
      ["omp", "chat"],
      ["grok", "terminal"],
    ]);
    // the Terminal toggle says whether the terminal view continues the conversation or starts fresh
    expect(terminalNote("claude")).toMatch(/continuing this conversation/);
    expect(terminalNote("codex")).toMatch(/starts Codex fresh/);
    expect(terminalNote("omh")).toMatch(/new terminal/);
  });

  it("accepts only those ids", () => {
    for (const id of ["claude", "codex", "omh", "pi", "omp", "grok"]) expect(isAgentId(id)).toBe(true);
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
    expect(rowModel(base)).toEqual({ title: "app", sub: "Claude Code", live: true, needsYou: false, ts: 1_700_000_000 });
    expect(rowModel({ ...base, status: "starting" })).toMatchObject({ sub: "Claude Code · Starting…", live: true });
    expect(rowModel({ ...base, status: "exited", exitCode: 0 })).toMatchObject({ sub: "Claude Code · Ended", live: false });
    expect(rowModel({ ...base, status: "exited", exitCode: null }).sub).toBe("Claude Code · Ended");
    expect(rowModel({ ...base, agent: "codex", status: "exited", exitCode: 2 }).sub).toBe("Codex · Ended · exit 2");
    expect(rowModel({ ...base, agent: "omp", status: "failed" }).sub).toBe("oh-my-pi · Could not start");
  });

  it("row model of a chat: live only while a turn runs, Needs you while an approval waits", () => {
    const chat: SessionRec = { id: "s2", agent: "codex", cwd: "/w/api", startedAt: 1, status: "running", view: "chat" };
    expect(rowModel(chat, { turn: false, needsYou: false })).toMatchObject({ live: false, needsYou: false, sub: "Codex" });
    expect(rowModel(chat, { turn: true, needsYou: false })).toMatchObject({ live: true, sub: "Codex" });
    expect(rowModel(chat, { turn: true, needsYou: true })).toMatchObject({ live: true, needsYou: true, sub: "Codex · Needs you" });
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
    expect(ev.pop()).toEqual({ event: "turn.end", outcome: "interrupted" });
    await host.chatClose(id);
    await expect(host.chatInput(id, { kind: "send", text: "x" })).rejects.toThrow();
    const ops = (g.__omherSessionCalls as { op: string; input?: unknown }[]).map((c) => c.op);
    expect(ops[0]).toBe("chat.start");
    expect(ops.filter((o) => o === "chat.close")).toHaveLength(1);
    expect(ops.filter((o) => o === "start")).toHaveLength(0); // a chat never starts a terminal
  });

  it("reports claude, codex and omh installed and pi, omp, grok missing", async () => {
    const list = await new MockHost({}).agents();
    expect(list.filter((a) => a.path).map((a) => a.id)).toEqual(["claude", "codex", "omh"]);
    expect(list.filter((a) => !a.path).map((a) => a.id)).toEqual(["pi", "omp", "grok"]);
    expect(list.map((a) => a.mode)).toEqual(["chat", "chat", "hermes", "chat", "chat", "terminal"]);
  });
});
