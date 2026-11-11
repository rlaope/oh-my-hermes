import { afterEach, describe, expect, it } from "vitest";
import { buildResume, continuesItself, forBots, parseResume, RESUME_VERSION, type ResumeInput, type ResumeSnap } from "./resume";
import { allDrafts, clearDrafts, getDraft, loadDrafts, setDraft } from "./drafts";
import { createSessions } from "../sessions/sessions";
import { MockHost } from "../sessions/host";
import { createStore, type BridgeLike } from "../state/store";
import { runningLine } from "../sidebar/UpdateConfirm";
import type { SessionRec } from "../sessions/agents";

const T = 1_800_000_000_000;

const input = (over: Partial<ResumeInput> = {}): ResumeInput => ({
  bot: "kami",
  bots: ["kami", "friren"],
  view: "chat",
  session: null,
  panelOpen: true,
  panelTab: "runs",
  runsFull: true,
  runId: "run-1",
  drafts: { kami: "half a thought", friren: "", "agent:s1": "next step", "agent:s9": "gone", nobody: "x" },
  sessions: [
    { id: "s1", agent: "claude", cwd: "/w/web-app", startedAt: T, view: "chat", running: true, agentSession: "11111111-2222-4333-8444-555555555555", account: "work" },
    { id: "s2", agent: "pi", cwd: "/w/api", startedAt: T, view: "chat", running: true },
    { id: "s3", agent: "codex", cwd: "/w/old", startedAt: T, view: "chat", running: false, exitCode: 0 },
  ],
  messages: (id) => (id === "s1" ? [{ id: "m1", role: "user", text: "fix the 502s", ts: 1 }] : undefined),
  ...over,
});

describe("resume snapshot", () => {
  it("round-trips the bot, panel, Plans view, drafts and sessions", () => {
    const snap = buildResume(input(), T);
    const back = parseResume(JSON.stringify(snap))!;
    expect(back).toEqual(snap);
    expect(back).toMatchObject({ v: RESUME_VERSION, at: T, bot: "kami", view: "chat", panelOpen: true, panelTab: "runs", runsFull: true, runId: "run-1" });
    // empty drafts and drafts of chats that are gone are not kept
    expect(back.drafts).toEqual({ kami: "half a thought", "agent:s1": "next step" });
    expect(back.sessions.map((s) => [s.id, s.agent, s.cwd, s.running, s.account ?? null])).toEqual([
      ["s1", "claude", "/w/web-app", true, "work"],
      ["s2", "pi", "/w/api", true, null],
      ["s3", "codex", "/w/old", false, null],
    ]);
    expect(back.sessions[0].messages).toEqual([{ id: "m1", role: "user", text: "fix the 502s", ts: 1 }]);
  });

  it("an open session is the view; Settings is not (a restart opens the chat behind it)", () => {
    expect(buildResume(input({ view: "session", session: "s2" }), T)).toMatchObject({ view: "session", session: "s2" });
    expect(buildResume(input({ view: "settings" }), T)).toMatchObject({ view: "chat", session: null });
    // a session id that is not in the list
    expect(buildResume(input({ view: "session", session: "s7" }), T)).toMatchObject({ view: "chat", session: null });
  });

  it("ignores a missing, malformed or other-version snapshot", () => {
    const good = buildResume(input(), T);
    for (const raw of [null, "", "{", "[]", "null", '"x"', "{}"]) expect(parseResume(raw), String(raw)).toBeNull();
    expect(parseResume(JSON.stringify({ ...good, v: 0 }))).toBeNull();
    expect(parseResume(JSON.stringify({ ...good, v: RESUME_VERSION + 1 }))).toBeNull();
    expect(parseResume(JSON.stringify({ ...good, at: "yesterday" }))).toBeNull();
    expect(parseResume(JSON.stringify({ ...good, sessions: {} }))).toBeNull();
    expect(parseResume(JSON.stringify({ ...good, drafts: [] }))).toBeNull();
    expect(parseResume(JSON.stringify({ ...good, bot: 7 }))).toBeNull();
  });

  it("drops bad rows and fields, keeps the good ones", () => {
    const good = buildResume(input(), T);
    const raw = {
      ...good,
      panelTab: "nope",
      session: "s1",
      view: "session",
      sessions: [
        good.sessions[0],
        { ...good.sessions[1], agent: "bash" }, // not on the allow-list
        { ...good.sessions[2], id: "../x" },
        { ...good.sessions[2], cwd: "" },
        good.sessions[0], // the same id twice
        "junk",
        { ...good.sessions[2], view: "tty", messages: [{ id: "a", role: "system", text: "x", ts: 1 }, { id: "b", role: "assistant", text: "ok", ts: 2 }] },
      ],
      drafts: { kami: 3, friren: "hi" },
    };
    const back = parseResume(JSON.stringify(raw))!;
    expect(back.panelTab).toBe("details");
    expect(back.sessions.map((s) => s.id)).toEqual(["s1", "s3"]);
    expect(back.sessions[1]).toMatchObject({ view: "chat", messages: [{ id: "b", role: "assistant", text: "ok", ts: 2 }] });
    expect(back.drafts).toEqual({ friren: "hi" });
    expect(back).toMatchObject({ view: "session", session: "s1" });
    // a session's names are kept when they are strings of a sane length, dropped otherwise
    const named = parseResume(JSON.stringify({ ...raw, sessions: [{ ...good.sessions[0], title: "Mine", agentTitle: 7, promptTitle: "x".repeat(201) }] }))!;
    expect(named.sessions[0].title).toBe("Mine");
    expect(named.sessions[0].agentTitle).toBeUndefined();
    expect(named.sessions[0].promptTitle).toBeUndefined();
    // the open session was dropped: back to the chat
    expect(parseResume(JSON.stringify({ ...raw, session: "s2" }))).toMatchObject({ view: "chat", session: null });
  });

  it("an unknown bot takes its panel, Plans view and draft with it", () => {
    const snap = parseResume(JSON.stringify(buildResume(input(), T)))!;
    expect(forBots(snap, ["kami", "friren"])).toEqual(snap);
    const gone = forBots(snap, ["friren"]);
    expect(gone).toMatchObject({ bot: null, panelOpen: false, runsFull: false, runId: null });
    expect(gone.drafts).toEqual({ "agent:s1": "next step" });
    expect(gone.sessions).toHaveLength(3);
  });

  it("Claude Code and Codex continue by themselves; the others wait for Resume", () => {
    expect(continuesItself({ agent: "claude", view: "chat", agentSession: "u" })).toBe(true);
    expect(continuesItself({ agent: "codex", view: "chat", agentSession: "t" })).toBe(true);
    expect(continuesItself({ agent: "claude", view: "chat" })).toBe(false);
    for (const agent of ["pi", "omp", "grok", "omh"] as const) expect(continuesItself({ agent, view: "chat", agentSession: "x" })).toBe(false);
  });
});

describe("drafts", () => {
  afterEach(clearDrafts);
  it("keeps unsent text per chat; a saved draft never overwrites one typed since", () => {
    setDraft("kami", "typing");
    setDraft("friren", "x");
    setDraft("friren", "");
    expect(allDrafts()).toEqual({ kami: "typing" });
    loadDrafts({ kami: "older", "agent:s1": "saved" });
    expect(getDraft("kami")).toBe("typing");
    expect(getDraft("agent:s1")).toBe("saved");
    expect(getDraft("nobody")).toBe("");
  });
});

// ---- SESSIONS restore against the mock host ---------------------------------------------------

function quietBridge(): BridgeLike {
  return {
    connect: async () => {},
    onAny: () => () => {},
    onStatus: () => () => {},
    request: (async () => ({})) as BridgeLike["request"],
  };
}

const saved = (): ResumeSnap["sessions"] => [
  { id: "s2", agent: "claude", cwd: "/w/web-app", startedAt: T, view: "chat", running: true, agentSession: "11111111-2222-4333-8444-555555555555", account: "work", messages: [{ id: "m1", role: "user", text: "fix it", ts: 1 }] },
  { id: "s3", agent: "codex", cwd: "/w/api", startedAt: T, view: "terminal", running: true, agentSession: "codex-thread-1" },
  { id: "s4", agent: "pi", cwd: "/w/pi", startedAt: T, view: "chat", running: true, promptTitle: "Port the parser", agentTitle: "Parser port", title: "Mine" },
  { id: "s5", agent: "grok", cwd: "/w/g", startedAt: T, view: "terminal", running: true },
  { id: "s6", agent: "claude", cwd: "/w/done", startedAt: T, view: "chat", running: false, exitCode: 0, agentSession: "22222222-2222-4333-8444-555555555555" },
];

describe("sessions restore", () => {
  it("a DSH session saved by omher 0.2.4 (deepseek-bot's terminal) comes back ended with a plain line and starts nothing", async () => {
    const g: Record<string, unknown> = {};
    const store = createStore(quietBridge());
    const ss = createSessions(new MockHost(g), () => store);
    ss.restore([
      { id: "s7", agent: "dsh", cwd: "/w/bot", startedAt: T, view: "terminal", running: true, agentSession: "33333333-2222-4333-8444-555555555555" },
      { id: "s8", agent: "dsh", cwd: "/w/bot", startedAt: T, view: "chat", running: false, exitCode: 0, agentSession: "session-8c11e2bc-9f55-4bcb-a597-19ea472184e8" },
    ]);
    await new Promise((r) => setTimeout(r, 30));
    const [old, now] = ss.getState().list;
    expect(old).toMatchObject({ id: "s7", view: "chat", status: "exited", error: "This DSH session ran deepseek-bot (omher 0.2.4). DSH is DeepSeek Harness now: Restart starts it in this folder." });
    expect(old.paused).toBeUndefined();
    expect(old.agentSession).toBeUndefined();
    expect(now).toMatchObject({ id: "s8", view: "chat", status: "exited", agentSession: "session-8c11e2bc-9f55-4bcb-a597-19ea472184e8" });
    expect(((g.__omherSessionCalls ?? []) as { op: string }[]).filter((c) => c.op !== "reset")).toEqual([]);
    // Restart: the old one starts DeepSeek Harness fresh in its folder, the new one continues its harness session
    await ss.restart("s7");
    await ss.restart("s8");
    const starts = (g.__omherSessionCalls as { op: string; agent?: string; resume?: string }[]).filter((c) => c.op === "chat.start" || c.op === "start");
    expect(starts.map(({ op, agent, resume }) => ({ op, agent, resume }))).toEqual([
      { op: "chat.start", agent: "dsh", resume: undefined },
      { op: "chat.start", agent: "dsh", resume: "session-8c11e2bc-9f55-4bcb-a597-19ea472184e8" },
    ]);
  });

  it("continues Claude Code and Codex in the same folder and account, pauses the others, keeps ended ones; once only", async () => {
    const g: Record<string, unknown> = {};
    const store = createStore(quietBridge());
    const ss = createSessions(new MockHost(g), () => store);
    ss.restore(saved());
    ss.restore(saved()); // a second restore in the same page load does nothing
    await new Promise((r) => setTimeout(r, 30));
    // file housekeeping (the saved attachments of sessions that are gone) starts no program
    const calls = (g.__omherSessionCalls as { op: string; agent?: string; cwd?: string; resume?: string; account?: string }[]).filter((c) => c.op !== "reset" && !c.op.startsWith("file."));
    expect(calls.map(({ op, agent, cwd, resume, account }) => ({ op, agent, cwd, resume, account }))).toEqual([
      { op: "chat.start", agent: "claude", cwd: "/w/web-app", resume: "11111111-2222-4333-8444-555555555555", account: "work" },
      { op: "chat.start", agent: "codex", cwd: "/w/api", resume: "codex-thread-1", account: undefined },
    ]);
    const by = (id: string) => ss.getState().list.find((r) => r.id === id)!;
    expect(by("s2")).toMatchObject({ status: "running", view: "chat" });
    // a chat agent last seen in its terminal view comes back as its chat
    expect(by("s3")).toMatchObject({ status: "running", view: "chat" });
    expect(by("s4")).toMatchObject({ status: "exited", paused: true });
    expect(by("s5")).toMatchObject({ status: "exited", paused: true, view: "terminal" });
    expect(by("s6")).toMatchObject({ status: "exited", exitCode: 0 });
    expect(by("s6").paused).toBeUndefined();
    // its name comes back with it (the person's, the agent's and the first-message summary)
    expect(by("s4")).toMatchObject({ title: "Mine", agentTitle: "Parser port", promptTitle: "Port the parser" });
    expect(by("s5").title).toBeUndefined();
    // the chat shows what was said before the restart
    expect(store.getState().chats["agent:s2"].messages.map((m) => m.text)).toEqual(["fix it"]);

    // Resume starts a paused one once; a second click does nothing
    await ss.resume("s4");
    await ss.resume("s4");
    await ss.resume("s6"); // not paused: nothing
    const pi = (g.__omherSessionCalls as { op: string; agent?: string }[]).filter((c) => c.op === "chat.start" && c.agent === "pi");
    expect(pi).toHaveLength(1);
    expect(by("s4").paused).toBeUndefined();
    // new sessions get the next id, never a restored one's
    const id = ss.draft();
    expect(id).toBe("s7");
  });

  it("a New session chat that never started comes back as a draft and is never started; its unsent text too", async () => {
    const g: Record<string, unknown> = {};
    const store = createStore(quietBridge());
    const ss = createSessions(new MockHost(g), () => store);
    const id = ss.draft();
    ss.setDraft(id, { agent: "codex", cwd: "/w/api" });
    setDraft(`agent:${id}`, "half a thought");
    const r = ss.getState().list[0];
    const snap = buildResume(
      {
        bot: "kami",
        bots: ["kami"],
        view: "session",
        session: id,
        panelOpen: false,
        panelTab: "details",
        runsFull: false,
        runId: null,
        drafts: allDrafts(),
        sessions: [{ id: r.id, agent: r.agent, cwd: r.cwd, startedAt: r.startedAt, view: r.view, running: false, draft: true }],
        messages: () => undefined,
      },
      T,
    );
    const back = parseResume(JSON.stringify(snap))!;
    expect(back.sessions).toEqual([{ id, agent: "codex", cwd: "/w/api", startedAt: r.startedAt, view: "chat", running: false, draft: true }]);
    expect(back.view).toBe("session");
    expect(back.drafts[`agent:${id}`]).toBe("half a thought");
    // a hand-edited snapshot cannot make a draft run
    expect(parseResume(JSON.stringify({ ...snap, sessions: [{ ...snap.sessions[0], running: true }] }))!.sessions[0].running).toBe(false);

    const g2: Record<string, unknown> = {};
    const ss2 = createSessions(new MockHost(g2), () => createStore(quietBridge()));
    ss2.restore(back.sessions);
    await ss2.loadAgents();
    await new Promise((res) => setTimeout(res, 30));
    expect(ss2.getState().list).toEqual([expect.objectContaining({ id, status: "draft", agent: "codex", cwd: "/w/api" })]);
    expect(((g2.__omherSessionCalls as { op: string }[] | undefined) ?? []).filter((c) => c.op !== "reset" && !c.op.startsWith("file."))).toEqual([]);
    // + reuses it rather than opening a second one
    expect(ss2.draft()).toBe(id);
  });

  it("an empty saved list leaves nothing, and a later restore does nothing", async () => {
    const g: Record<string, unknown> = {};
    const store = createStore(quietBridge());
    const ss = createSessions(new MockHost(g), () => store);
    ss.restore([]);
    ss.restore(saved());
    expect(ss.getState().list).toEqual([]);
  });
});

describe("update confirm: the running line", () => {
  const rec = (id: string, agent: SessionRec["agent"], cwd: string, status: SessionRec["status"], agentSession?: string): SessionRec => ({
    id,
    agent,
    cwd,
    startedAt: T,
    status,
    view: agent === "grok" ? "terminal" : "chat",
    ...(agentSession ? { agentSession } : {}),
  });
  const mode = (r: SessionRec) => (r.agent === "grok" ? "terminal" : r.agent === "omh" ? "hermes" : "chat");
  const sp = (s: string) => s.replace(/\u00a0/g, " ");
  it("names each running session and says how it comes back", () => {
    expect(runningLine([], mode)).toBe("");
    expect(runningLine([rec("s1", "claude", "/w/x", "exited")], mode)).toBe("");
    expect(sp(runningLine([rec("s1", "claude", "/w/web-app", "running", "u"), rec("s2", "codex", "/w/api", "running", "t")], mode))).toBe(
      "2 sessions running: web-app (Claude Code), api (Codex). They resume after the restart.",
    );
    expect(sp(runningLine([rec("s1", "pi", "/w/p", "running")], mode))).toBe("1 session running: p (pi). It comes back with a Resume button.");
    expect(sp(runningLine([rec("s1", "claude", "/w/a", "running", "u"), rec("s2", "grok", "/w/g", "starting")], mode))).toBe(
      "2 sessions running: a (Claude Code), g (Grok). Claude Code and Codex resume after the restart; the others come back with a Resume button.",
    );
  });
});
