// A person's own ACP agents (Settings › Agents): the page's model lists the built-ins by tier and the person's own
// after them; the confirm card's command is exactly what the shell will run; nothing is written before the card's
// Add; a person's own agent joins the + menu's ACP tier and opens a chat through the generic ACP adapter; removing
// it ends its open sessions.
import { describe, expect, it } from "vitest";
import { acpRow, isCustom, menuOrder, missingNote, parseAcpRow, registerAcp, type AgentInfo } from "./agents";
import { agentsPageModel, cardCommand, mockCheck, whyOf, whyText, type CustomPreview } from "./custom";
import { MockHost, type MockCall } from "./host";
import { createSessions } from "./sessions";
import { createStore, type BridgeLike } from "../state/store";
import { t } from "../i18n";

const bridge: BridgeLike = { connect: async () => undefined, onAny: () => () => {}, onStatus: () => () => {}, request: (async () => ({})) as BridgeLike["request"] };
const ids = (l: { id: string }[]) => l.map((a) => a.id);

describe("the Agents page model", () => {
  it("lists the built-ins read-only by tier with whether each is installed, then the person's own and the broken ones", async () => {
    const g: Record<string, unknown> = {
      __omherMockAgents: ["claude", "opencode", "gemini"],
      __omherCustomFile: [
        { id: "cursor", label: "Cursor", program: "cursor-agent", args: ["acp"], install: "" },
        { id: "missing", label: "Missing", program: "not-here", args: ["acp"], install: "" },
        { id: "evil", label: "Evil", program: "sh", args: ["-c", "rm -rf ~"], install: "" },
        { id: "claude", label: "Mine", program: "x", args: [] },
      ],
    };
    const host = new MockHost(g);
    const m = agentsPageModel(await host.agents(), await host.customList());
    expect(m.builtins.map((b) => [b.id, b.tier, b.installed])).toEqual([
      ["claude", "main", true],
      ["codex", "main", false],
      ["omo", "main", false],
      ["dsh", "builtin", false],
      ["omh", "builtin", false],
      ["pi", "builtin", false],
      ["omp", "builtin", false],
      ["grok", "builtin", false],
      ["opencode", "acp", true],
      ["gemini", "acp", true],
      ["qwen", "acp", false],
      ["kimi", "acp", false],
      ["copilot", "acp", false],
      ["cline", "acp", false],
    ]);
    // the person's own: the command it runs now, or not found; the broken entries are listed, never as agents
    expect(m.mine).toEqual([
      { id: "cursor", label: "Cursor", program: "cursor-agent", args: ["acp"], command: "/opt/homebrew/bin/cursor-agent acp" },
      { id: "missing", label: "Missing", program: "not-here", args: ["acp"], command: null },
    ]);
    expect(m.broken).toEqual([
      { id: "evil", why: "args" },
      { id: "claude", why: "builtin" },
    ]);
    // a broken entry is never in the + menu
    registerAcp(await host.agents());
    expect(ids(menuOrder(await host.agents(), []))).not.toContain("evil");
  });

  it("checks as the shell does: shell characters, relative paths, a built-in's id, OpenCode and Kilo Code are refused", () => {
    const ok = { id: "cursor", label: "Cursor", program: "cursor-agent", args: ["acp"], install: "" };
    const found = (p: string) => p === "/opt/homebrew/bin/cursor-agent";
    expect(mockCheck(ok, found)).toBeNull();
    expect(mockCheck({ ...ok, program: "/opt/homebrew/bin/cursor-agent" }, found)).toBeNull();
    expect(mockCheck({ ...ok, program: "/opt/elsewhere/cursor-agent" }, found)).toBe("path");
    for (const [patch, why] of [
      [{ id: "Cursor" }, "id"],
      [{ id: "gemini" }, "builtin"],
      [{ id: "kilo" }, "builtin"],
      [{ program: "./cursor-agent" }, "program"],
      [{ program: "bin/cursor-agent" }, "program"],
      [{ program: "cursor-agent; rm -rf ~" }, "program"],
      [{ program: "$(id)" }, "program"],
      [{ args: ["acp", "$(id)"] }, "args"],
      [{ args: ["a b"] }, "args"],
      [{ args: Array(9).fill("x") }, "args"],
      [{ install: "curl x | sh" }, "install"],
      [{ program: "opencode" }, "opencode"],
      [{ program: "/usr/local/bin/kilo" }, "kilo"],
      [{ label: "x; y" }, "label"],
    ] as const)
      expect(mockCheck({ ...ok, ...patch }, found), JSON.stringify(patch)).toBe(why);
  });
});

describe("the confirm card", () => {
  it("shows exactly the command that will run, or the not-found line, and refusals in words", async () => {
    const g: Record<string, unknown> = {};
    const host = new MockHost(g);
    const p = await host.customPreview(" Cursor Agent ", "cursor-agent", "acp  --model=x", "");
    expect(p.entry).toEqual({ id: "cursor-agent", label: "Cursor Agent", program: "cursor-agent", args: ["acp", "--model=x"], install: "" });
    // the card's text is the command, word for word: the program found, then the arguments the entry stores
    expect(cardCommand(p)).toBe("/opt/homebrew/bin/cursor-agent acp --model=x");
    expect(cardCommand(p)).toBe([p.command!.split(" ")[0], ...p.entry.args].join(" "));
    const missing: CustomPreview = { entry: { ...p.entry, program: "not-here" }, command: null };
    expect(cardCommand(missing)).toBe("not-here: not found on the search path");
    // the preview wrote nothing
    expect(g.__omherCustomFile).toBeUndefined();
    await expect(host.customPreview("x", "opencode", "acp", "")).rejects.toThrow("why:opencode");
    const e = await host.customPreview("x", "kilo", "acp", "").catch((x) => x);
    expect(whyOf(e)).toBe("kilo");
    expect(whyText(e)).toBe("Kilo Code is not offered.");
    expect(whyText(new Error("why:opencode"))).toBe("Use the built-in OpenCode.");
    expect(whyText(new Error("something else"))).toBe("something else");
    expect(t("ag.cardFolder")).toBe("In the folder you pick for each session.");
  });

  it("only Add writes: the entry appears in the look-up as an ACP row of the person's own", async () => {
    const g: Record<string, unknown> = { __omherMockAgents: ["claude", "gemini"] };
    const host = new MockHost(g);
    const p = await host.customPreview("Cursor Agent", "cursor-agent", "acp", "npm install -g cursor-agent");
    expect(g.__omherCustomFile).toBeUndefined();
    await host.customConfirm(p.entry);
    expect(g.__omherCustomFile).toEqual([p.entry]);
    await expect(host.customConfirm(p.entry)).rejects.toThrow("why:dup");
    const list = await host.agents();
    const row = list.find((a) => a.id === "cursor-agent")!;
    expect(row).toMatchObject({ label: "Cursor Agent", mode: "chat", path: "/opt/homebrew/bin/cursor-agent" });
    expect(parseAcpRow(row.acp)).toEqual({ id: "cursor-agent", label: "Cursor Agent", program: "cursor-agent", args: ["acp"], login: "cursor-agent", install: "npm install -g cursor-agent", mark: "", continues: true, custom: true });
    registerAcp(list);
    expect(isCustom("cursor-agent")).toBe(true);
    expect(isCustom("gemini")).toBe(false);
    // the + menu: installed first as always, and inside that after the generic ACP agents
    expect(ids(menuOrder(list, []).filter((a) => a.path))).toEqual(["claude", "gemini", "cursor-agent"]);
    // its install line when it is missing; with none, the note names only what is missing
    expect(missingNote("cursor-agent")).toBe("cursor-agent was not found on this computer · install: npm install -g cursor-agent");
    await host.customConfirm({ id: "bare", label: "Bare", program: "not-here", args: [], install: "" });
    registerAcp(await host.agents());
    expect(missingNote("bare")).toBe("not-here was not found on this computer");
    const calls = (g.__omherSessionCalls as MockCall[]).map((c) => c.op);
    expect(calls).toEqual(["custom.preview", "custom.confirm", "custom.confirm", "custom.confirm"]);
  });
});

describe("a person's own agent in SESSIONS", () => {
  it("opens a chat through the generic ACP adapter; removing it ends its open session and the menu forgets it", async () => {
    const storage = new Map<string, string>();
    (globalThis as { localStorage?: unknown }).localStorage = { getItem: (k: string) => storage.get(k) ?? null, setItem: (k: string, v: string) => void storage.set(k, v), removeItem: (k: string) => void storage.delete(k) };
    const g: Record<string, unknown> = { __omherMockAgents: ["claude"], __omherCustomFile: [{ id: "stub", label: "Stub", program: "stub-acp", args: ["acp"], install: "" }] };
    const host = new MockHost(g);
    const store = createStore(bridge);
    const ss = createSessions(host, () => store);
    await ss.loadAgents();
    expect(acpRow("stub")?.custom).toBe(true);
    const id = ss.draft("stub");
    await ss.start(id, "hello");
    await new Promise((r) => setTimeout(r, 900));
    expect(((g.__omherSessionCalls as MockCall[]) ?? []).find((c) => c.op === "chat.start")).toMatchObject({ agent: "stub" });
    expect(ss.getState().list.find((r) => r.id === id)!.status).toBe("running");
    // the chat answered (the mock speaks what the ACP adapter emits)
    const chat = store.getState().chats[ss.chatKey(id)!]!;
    expect(chat.items.some((i) => i.kind === "assistant")).toBe(true);
    // removed on the Agents page: the file loses it, its session ends cleanly, the + menu no longer offers it
    await host.customRemove("stub");
    await ss.endAgent("stub");
    expect(ss.getState().list.find((r) => r.id === id)).toMatchObject({ status: "exited", exitCode: null });
    expect(((g.__omherSessionCalls as MockCall[]) ?? []).some((c) => c.op === "chat.close")).toBe(true);
    expect(ids(menuOrder(ss.getState().agents!, []))).not.toContain("stub");
    expect(acpRow("stub")).toBeUndefined();
    expect(ss.getState().recent.some((r) => r.agent === "stub")).toBe(false);
  });
});
