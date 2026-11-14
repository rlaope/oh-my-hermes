// Two tiers and the generic ACP agents as data: the + menu lists Claude Code, Codex and OmO first, then the other
// built-ins, then the generic Agent Client Protocol agents the shell describes; each generic agent's install and
// sign-in lines come from that description and are 0.2.8's word for word; and a session of Kilo Code (no longer
// offered) saved before this comes back ended with one plain line, its chat as it was, and nothing starts.
import { describe, expect, it } from "vitest";
import { acpRow, agentDef, AGENTS, continues, installLine, isGone, menuOrder, menuParts, missingNote, parseAcpRow, parseRecent, registerAcp, type AcpRow, type AgentInfo } from "./agents";
import { MockHost, type MockCall } from "./host";
import { createSessions } from "./sessions";
import { createStore, type BridgeLike } from "../state/store";
import { parseResume, RESUME_VERSION } from "../app/resume";
import shellList from "./mockAcpAgents.json";
import { t } from "../i18n";

const ACP: AcpRow[] = shellList;
const ids = (l: AgentInfo[]) => l.map((a) => a.id);
const info = (installed: string[]): AgentInfo[] => [
  ...AGENTS.map((a) => ({ id: a.id, label: a.label, mode: a.mode, path: installed.includes(a.id) ? `/bin/${a.id}` : null })),
  ...ACP.map((r) => ({ id: r.id, label: r.label, mode: "chat" as const, path: installed.includes(r.id) ? `/bin/${r.id}` : null, acp: r })),
];

describe("the + menu's tiers", () => {
  it("lists Claude Code, Codex and OmO first, then the other built-ins, then the generic ACP agents", () => {
    // the built-ins in any order (the tier decides, not where a row came); the generic agents in the shell's order
    const all = info([]);
    const shuffled = [...all.filter((a) => a.acp), ...all.filter((a) => !a.acp).reverse()];
    expect(ids(menuOrder(shuffled, []))).toEqual(["claude", "codex", "omo", "dsh", "omh", "pi", "omp", "grok", "opencode", "gemini", "qwen", "kimi", "copilot", "cline"]);
    // installed first as before, by tier inside: OmO installed with pi and Gemini CLI comes before both
    expect(ids(menuParts(info(["gemini", "pi", "omo"]), []).shown)).toEqual(["omo", "pi", "gemini"]);
    // the last one used still goes on top
    expect(ids(menuParts(info(["gemini", "pi", "omo"]), [{ agent: "gemini", cwd: "/a", at: 1 }]).shown)).toEqual(["gemini", "omo", "pi"]);
    expect(ids(menuParts(info(["gemini", "pi", "omo"]), []).more).slice(0, 3)).toEqual(["claude", "codex", "dsh"]);
  });

  it("offers only what the shell offers: no Kilo Code, no row the shell did not describe", () => {
    const withKilo: AgentInfo[] = [...info([]), { id: "kilo", label: "Kilo Code", mode: "chat", path: "/bin/kilo" }];
    expect(ids(menuOrder(withKilo, []))).not.toContain("kilo");
    // a malformed row is not an agent
    const bad: AgentInfo[] = [{ id: "evil", label: "Evil", mode: "chat", path: "/bin/evil", acp: { ...ACP[0], id: "evil", args: "--yolo" } as unknown as AcpRow }];
    expect(ids(menuOrder(bad, []))).toEqual([]);
    expect(parseAcpRow({ ...ACP[0], id: "claude" })).toBeNull();
    expect(parseAcpRow({ ...ACP[0], id: "../x" })).toBeNull();
    expect(parseAcpRow(ACP[0])).toEqual(ACP[0]);
  });
});

describe("the generic ACP agents come from the shell's rows", () => {
  it("their install, sign-in and missing lines are 0.2.8's", () => {
    registerAcp(info([]));
    expect(ACP.map((r) => r.id)).toEqual(["gemini", "qwen", "kimi", "copilot", "cline"]);
    // 0.2.8's INSTALL lines and acp_chat.rs logins, word for word
    expect(ACP.map((r) => installLine(r.id))).toEqual([
      "npm install -g @google/gemini-cli",
      "npm install -g @qwen-code/qwen-code@latest",
      "npm install -g @moonshot-ai/kimi-code",
      "npm install -g @github/copilot",
      "npm install -g cline",
    ]);
    expect(ACP.map((r) => acpRow(r.id)!.login)).toEqual(["gemini", "qwen", "kimi login", "copilot login", "cline auth"]);
    expect(ACP.map((r) => agentDef(r.id).label)).toEqual(["Gemini CLI", "Qwen Code", "Kimi Code", "Copilot CLI", "Cline"]);
    expect(missingNote("gemini")).toBe("gemini was not found on this computer · install: npm install -g @google/gemini-cli");
    expect(missingNote("kimi")).toBe("kimi was not found on this computer · install: npm install -g @moonshot-ai/kimi-code");
    for (const r of ACP) expect(continues(r.id), r.id).toBe(true);
  });

  it("the signed-out line names each row's own sign-in command (mock host, as acp_chat.rs words it)", async () => {
    const g: Record<string, unknown> = { __omherMockAgents: ["claude", "kimi"] };
    const host = new MockHost(g);
    registerAcp(await host.agents());
    const events: { event: string; [k: string]: unknown }[] = [];
    await host.chatStart("kimi", "/w", (e) => events.push(e));
    await new Promise((r) => setTimeout(r, 80));
    expect(events.find((e) => e.event === "session.error")).toMatchObject({ kind: "signed_out", login: "kimi login", message: "Kimi Code is not signed in. Run `kimi login` in a terminal and sign in." });
  });
});

describe("a saved Kilo Code session", () => {
  const bridge: BridgeLike = { connect: async () => undefined, onAny: () => () => {}, onStatus: () => () => {}, request: (async () => ({})) as BridgeLike["request"] };
  const raw = JSON.stringify({
    v: RESUME_VERSION,
    at: 1,
    bot: null,
    view: "session",
    session: "s3",
    panelOpen: false,
    panelTab: "details",
    runsFull: false,
    runId: null,
    drafts: {},
    sessions: [
      { id: "s3", agent: "kilo", cwd: "/w/app", startedAt: 1, view: "chat", running: true, agentSession: "ses_e2d9961a8ffe6pwTlM4aAUbsu1", title: "fix login", messages: [{ id: "m1", role: "user", text: "fix the login", ts: 2 }] },
      { id: "s4", agent: "kilo", cwd: "/w/old", startedAt: 1, view: "chat", running: false, draft: true },
    ],
  });

  it("parses, comes back ended with one plain line and no Restart, and nothing starts", async () => {
    const snap = parseResume(raw)!;
    expect(snap.sessions.map((s) => s.agent)).toEqual(["kilo", "kilo"]);
    expect(isGone("kilo")).toBe(true);
    const storage = new Map<string, string>();
    (globalThis as { localStorage?: unknown }).localStorage = { getItem: (k: string) => storage.get(k) ?? null, setItem: (k: string, v: string) => void storage.set(k, v), removeItem: (k: string) => void storage.delete(k) };
    const g: Record<string, unknown> = { __omherMockAgents: ["claude"] };
    const store = createStore(bridge);
    const ss = createSessions(new MockHost(g), () => store);
    ss.restore(snap.sessions);
    await new Promise((r) => setTimeout(r, 60));
    const [ended, draft] = [ss.getState().list.find((r) => r.id === "s3")!, ss.getState().list.find((r) => r.id === "s4")!];
    expect(ended).toMatchObject({ agent: "kilo", status: "exited", title: "fix login" });
    expect(ended.paused).toBeUndefined();
    // its chat comes back as it was
    const chat = store.getState().chats[ss.chatKey("s3")!]!;
    expect(chat.items.some((i) => i.kind === "user" && (i as { text: string }).text === "fix the login")).toBe(true);
    // the never-started draft is a draft on the usual agent, same folder
    expect(draft).toMatchObject({ status: "draft", agent: "claude", cwd: "/w/old" });
    // the one line it shows (SessionView's Ended), named as before
    expect(agentDef("kilo").label).toBe("Kilo Code");
    expect(t("ss.gone", { agent: "Kilo Code" })).toBe("Kilo Code is no longer offered in omher");
    // Restart and Resume start nothing; New session here opens the usual agent in its folder
    await ss.restart("s3");
    await ss.resume("s3");
    expect(((g.__omherSessionCalls as MockCall[] | undefined) ?? []).filter((c) => c.op === "chat.start" || c.op === "start")).toEqual([]);
    expect(ss.getState().list.find((r) => r.id === "s3")!.status).toBe("exited");
    const here = ss.draftHere("s3")!;
    expect(ss.getState().list.find((r) => r.id === here)).toMatchObject({ status: "draft", cwd: "/w/app" });
    expect(ss.getState().list.find((r) => r.id === here)!.agent).not.toBe("kilo");
  });

  it("a recent folder of Kilo Code is dropped", () => {
    expect(parseRecent(JSON.stringify([{ agent: "kilo", cwd: "/w/a", at: 2 }, { agent: "claude", cwd: "/w/b", at: 1 }]))).toEqual([{ agent: "claude", cwd: "/w/b", at: 1 }]);
  });
});
