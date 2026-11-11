// The session controls' pure parts: the modes omher offers, reasoning labels, the agent's `/` menu, context use, and
// a message sent while a turn runs (the reducer's message.queued / taken / dropped).
import { describe, expect, it } from "vitest";
import { levelLabel, levelOptions, modeLabel, modesOf, tokens, usageText } from "./controls";
import { commandQuery, matchCommands, MENU_MAX, parseCommands, pickText, type AgentCommand } from "../chat/parts/commands";
import { groupModels } from "./SessionView";
import { initialState, reduce, type Action, type AppState } from "../state/store";
import type { BridgeEvent } from "../lib/protocol";

describe("permission modes", () => {
  it("offers only modes that keep approvals and the sandbox", () => {
    expect(modesOf("claude")).toEqual(["default", "plan", "acceptEdits"]);
    expect(modesOf("codex")).toEqual(["read-only", "ask", "auto"]);
    for (const a of ["omo", "pi", "omp", "dsh", "omh", "grok"] as const) expect(modesOf(a)).toEqual([]);
    for (const a of ["claude", "codex"] as const)
      for (const m of ["bypassPermissions", "dontAsk", "danger-full-access", "dangerFullAccess", "never"]) expect(modesOf(a)).not.toContain(m);
  });
  it("names each mode, and a mode it does not offer as the agent's own", () => {
    expect(modeLabel("plan")).toBe("Plan");
    expect(modeLabel("default")).toBe("Ask");
    expect(modeLabel("acceptEdits")).toBe("Accept edits");
    expect(modeLabel("read-only")).toBe("Read-only");
    expect(modeLabel("auto")).toBe("Auto in folder");
    expect(modeLabel("")).toBe("Agent's own");
    expect(modeLabel(undefined)).toBe("Agent's own");
  });
});

describe("reasoning levels", () => {
  it("labels levels as the agent names them; xhigh and max never read the same", () => {
    expect(levelOptions(["low", "medium", "high", "xhigh", "max"]).map((o) => o.label)).toEqual(["Low", "Med", "High", "Extra high", "Max"]);
    // without a `max`, xhigh is the bot chat's "Max"
    expect(levelLabel("xhigh", ["low", "high", "xhigh"])).toBe("Max");
    expect(levelOptions(["minimal", "low", "ultra"]).map((o) => o.label)).toEqual(["Minimal", "Low", "Ultra"]);
    expect(levelLabel("weird")).toBe("Weird");
  });
});

const C = (name: string, kind: "command" | "skill" = "command", prefix: "/" | "$" = "/", description = ""): AgentCommand => ({ name, description, hint: "", kind, prefix });

describe("the agent's / menu", () => {
  it("reads session.commands once per name and drops odd entries", () => {
    const list = parseCommands([
      { name: "compact", description: "Free up context", hint: "<x>", kind: "command", prefix: "/" },
      { name: "compact", description: "again" },
      { name: "review", kind: "skill", prefix: "$" },
      { name: "has space" },
      { name: "" },
      null,
      "x",
    ]);
    expect(list).toEqual([
      { name: "compact", description: "Free up context", hint: "<x>", kind: "command", prefix: "/" },
      { name: "review", description: "", hint: "", kind: "skill", prefix: "$" },
    ]);
    expect(parseCommands(undefined)).toEqual([]);
  });
  it("opens only on / or $ at the start of the box", () => {
    expect(commandQuery("/")).toEqual({ prefix: "/", query: "" });
    expect(commandQuery("/com")).toEqual({ prefix: "/", query: "com" });
    expect(commandQuery("$skill:hy")).toEqual({ prefix: "$", query: "skill:hy" });
    expect(commandQuery("hello /com")).toBeNull();
    expect(commandQuery("/compact now")).toBeNull();
  });
  it("puts names that start with the query first, then those containing it, then descriptions", () => {
    const list = [C("context"), C("compact"), C("recompile"), C("init", "command", "/", "compose a CLAUDE.md"), C("review", "skill", "$")];
    expect(matchCommands(list, "/", "comp").shown.map((c) => c.name)).toEqual(["compact", "recompile", "init"]);
    // `/` lists $ skills too; `$` only them
    expect(matchCommands(list, "/", "").total).toBe(5);
    expect(matchCommands(list, "$", "").shown.map((c) => c.name)).toEqual(["review"]);
  });
  it("never renders a long list at once", () => {
    const many = Array.from({ length: 450 }, (_, i) => C(`skill-${i}`, "skill"));
    const r = matchCommands(many, "/", "");
    expect(r.shown).toHaveLength(MENU_MAX);
    expect(r.total).toBe(450);
    expect(matchCommands(many, "/", "skill-44").shown.map((c) => c.name)).toEqual(["skill-44", "skill-440", "skill-441", "skill-442", "skill-443", "skill-444", "skill-445", "skill-446", "skill-447", "skill-448", "skill-449"]);
  });
  it("a pick puts the command and a space in the box", () => {
    expect(pickText(C("compact"))).toBe("/compact ");
    expect(pickText(C("skill:hyperframes", "skill", "$"))).toBe("$skill:hyperframes ");
  });
});

describe("context use", () => {
  it("shows the agent's own numbers, never a guess", () => {
    expect(usageText({ used: 23386, max: 1_000_000 })).toEqual({ text: "23k / 1M · 2%", pct: 2 });
    expect(usageText({ used: 41250, max: 258400 })).toEqual({ text: "41k / 258k · 16%", pct: 16 });
    expect(usageText(undefined)).toBeNull();
    expect(usageText({ used: 5, max: 0 })).toBeNull();
    expect(usageText({ used: 2_000_000, max: 1_000_000 })?.pct).toBe(100);
    expect([tokens(950), tokens(1250000), tokens(1_000_000)]).toEqual(["950", "1.3M", "1M"]);
  });
});

describe("the session model menu", () => {
  const opts = [
    { id: "anthropic/claude-opus-5", label: "Claude Opus 5", provider: "anthropic" },
    { id: "anthropic/claude-fable-5-1", label: "Claude Fable 5.1", provider: "anthropic" },
    { id: "opengateway/gpt-6", label: "GPT-6", provider: "opengateway" },
  ];
  it("groups by provider in order and searches label, id and provider", () => {
    expect(groupModels(opts, "").map((g) => [g.provider, g.rows.length])).toEqual([["anthropic", 2], ["opengateway", 1]]);
    expect(groupModels(opts, "opengate").map((g) => g.rows.map((r) => r.label))).toEqual([["GPT-6"]]);
    expect(groupModels(opts, "fable 5.1")[0].rows[0].id).toBe("anthropic/claude-fable-5-1");
    expect(groupModels(opts, "nothing")).toEqual([]);
    // an agent's own list (no provider) is one group
    expect(groupModels([{ id: "opus", label: "Opus" }], "")).toEqual([{ provider: "", rows: [{ id: "opus", label: "Opus" }] }]);
  });
});

describe("a message sent while a turn runs", () => {
  const key = "agent:s1";
  const ev = (s: AppState, e: Record<string, unknown>) => reduce(s, { type: "event", ev: { ...e, bot: key } as unknown as BridgeEvent, now: 2 } as Action);
  const user = (s: AppState, id: string) => s.chats[key].items.find((i) => i.kind === "user" && i.id === id) as { wait?: string };
  it("waits until the agent takes it, or shows that Stop dropped it", () => {
    let s = reduce(initialState(), { type: "chat.opened", bot: key, res: { session_id: key, messages: [], running: false, model: "", provider: "", reasoning: "" }, now: 1 });
    s = reduce(s, { type: "local.user", bot: key, id: "local-s1", text: "first", now: 1 });
    s = reduce(s, { type: "local.user", bot: key, id: "local-s2", text: "second", now: 1 });
    s = ev(s, { event: "message.queued", id: "local-s2" });
    expect(user(s, "local-s2").wait).toBe("queued");
    expect(user(s, "local-s1").wait).toBeUndefined();
    s = ev(s, { event: "message.taken", id: "local-s2" });
    expect(user(s, "local-s2").wait).toBeUndefined();
    s = ev(s, { event: "message.queued", id: "local-s1" });
    s = ev(s, { event: "message.dropped", id: "local-s1" });
    expect(user(s, "local-s1").wait).toBe("dropped");
    // an unknown id or chat changes nothing
    expect(ev(s, { event: "message.taken", id: "nope" })).toBe(s);
  });
});
