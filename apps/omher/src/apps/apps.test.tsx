import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { AppRow, AppSkill, AppState, Bot } from "../lib/protocol";
import { AppCard, doneWords } from "./AppsPage";
import { actionsOf, markOf, sections, tierOf, titleOf, type Card } from "./tiers";

const app = (name: string, state: AppState, auth: AppRow["auth"] = "oauth", asks: string[] = [], terminal = false, device = false): AppRow => ({
  name,
  description: `${name} things.`,
  auth,
  asks,
  terminal,
  device,
  state,
});
const skill = (name: string, state: AppSkill["state"]): AppSkill => ({ name, description: `${name} skill.`, state });
const BOT = { name: "demo-bot", display_name: "Demo" } as Bot;

const card = (c: Card, busy: { name: string; verb: "install" | "login" | "remove" } | null = null) =>
  renderToStaticMarkup(<AppCard card={c} bot={BOT} busy={busy} onRun={() => {}} />);
const mcp = (a: AppRow): Card => ({ kind: "mcp", tier: tierOf(a.name), app: a });
const buttons = (html: string) => [...html.matchAll(/data-testid="app-(install|login|remove)-[^"]+"/g)].map((m) => m[1]);

describe("what a card offers for each state", () => {
  it("Connect only when not connected; Sign in and Remove once added; nothing when the state could not be read", () => {
    expect(actionsOf(app("notion", "available"))).toEqual(["install"]);
    expect(actionsOf(app("notion", "needs_signin"))).toEqual(["login", "remove"]);
    expect(actionsOf(app("notion", "installed"))).toEqual(["login", "remove"]);
    expect(actionsOf(app("deepwiki", "installed", "none"))).toEqual(["remove"]);
    expect(actionsOf(app("deepwiki", "installed", "api_key"))).toEqual(["remove"]);
    expect(actionsOf(app("notion", "disabled"))).toEqual(["remove"]);
    expect(actionsOf(app("notion", "unknown"))).toEqual([]);
    // a value only a terminal can give: no Connect (it would always fail); once added, Sign in and Remove as usual
    expect(actionsOf(app("asana", "available", "oauth", ["ASANA_CLIENT_ID"], true))).toEqual([]);
    expect(actionsOf(app("asana", "needs_signin", "oauth", ["ASANA_CLIENT_ID"], true))).toEqual(["login", "remove"]);
  });

  it("a device-code sign-in (the bot's oauth.flow) is never offered from the page: its login command instead", () => {
    const dev = (st: AppState) => app("notion", st, "oauth", [], false, true);
    expect(actionsOf(dev("needs_signin"))).toEqual(["remove"]);
    expect(actionsOf(dev("installed"))).toEqual(["remove"]);
    const html = card(mcp(dev("needs_signin")));
    expect(buttons(html)).toEqual(["remove"]);
    expect(html).toContain("hermes -p demo-bot mcp login notion");
    expect(html).toContain("device code");
    expect(html).not.toContain("mcp install notion");
    // not added yet: Connect as usual (the flow is the bot's own config, which has no server yet)
    expect(buttons(card(mcp(app("notion", "available"))))).toEqual(["install"]);
  });

  it("shows the terminal command up front for an install only a terminal can answer", () => {
    const html = card(mcp(app("asana", "available", "oauth", ["ASANA_CLIENT_ID", "ASANA_CLIENT_SECRET"], true)));
    expect(buttons(html)).toEqual([]);
    expect(html).toContain("hermes -p demo-bot mcp install asana");
    expect(html).toContain("only in a terminal");
    expect(html).toContain('data-testid="app-open-terminal-asana"');
    // a secret alone may already be in Hermes' .env: Connect stays, no command up front
    const key = card(mcp(app("keyed", "available", "api_key", ["MCP_KEYED_API_KEY"], false)));
    expect(buttons(key)).toEqual(["install"]);
    expect(key).not.toContain("mcp install keyed");
  });

  it("draws the state word and only those buttons", () => {
    const html = (a: AppRow) => card(mcp(a));
    expect(html(app("notion", "available"))).toContain("Not connected");
    expect(buttons(html(app("notion", "available")))).toEqual(["install"]);
    const need = html(app("notion", "needs_signin"));
    expect(need).toContain("Needs sign-in");
    expect(need).toMatch(/class="ap-state needs_signin need"/);
    expect(need).toContain(">Sign in<");
    expect(buttons(need)).toEqual(["login", "remove"]);
    expect(html(app("notion", "installed"))).toContain(">Sign in again<");
    expect(html(app("notion", "disabled"))).toContain("Turned off");
    const unknown = html(app("notion", "unknown"));
    expect(unknown).toContain("State unknown");
    expect(buttons(unknown)).toEqual([]);
  });

  it("says what an install will ask for, and a skill shows its state with no button", () => {
    expect(card(mcp(app("asana", "available", "oauth", ["DEMO_SECRET"])))).toContain("Asks for DEMO_SECRET");
    expect(card(mcp(app("asana", "installed", "oauth", ["DEMO_SECRET"])))).not.toContain("Asks for");
    const s = card({ kind: "skill", tier: "work", skill: skill("google-workspace", "available") });
    expect(s).toContain("Ships with Hermes");
    expect(s).toContain("Skill");
    expect(buttons(s)).toEqual([]);
    expect(card({ kind: "skill", tier: "work", skill: skill("obsidian", "disabled") })).toContain("Turned off");
  });

  it("while a run is on, every button waits and the running one says so", () => {
    const html = card(mcp(app("notion", "needs_signin")), { name: "notion", verb: "login" });
    expect(html).toContain(">Waiting…<");
    expect((html.match(/disabled=""/g) ?? []).length).toBe(2);
    expect(card(mcp(app("linear", "available")), { name: "notion", verb: "login" })).toMatch(/disabled=""/);
  });
});

describe("tiers, names and order", () => {
  it("puts the platform list's tiers first and everything else under More", () => {
    expect(["notion", "linear", "atlassian", "google-workspace", "obsidian"].map(tierOf)).toEqual(["work", "work", "work", "work", "work"]);
    expect(["datadog", "vercel", "deepwiki", "prisma-postgres"].map(tierOf)).toEqual(["ops", "ops", "ops", "ops"]);
    expect(["wolfram", "kiwi", "anything-new"].map(tierOf)).toEqual(["more", "more", "more"]);
  });

  it("names products as their makers do and capitalises the rest", () => {
    expect(titleOf("atlassian")).toBe("Jira and Confluence");
    expect(titleOf("gitlab")).toBe("GitLab");
    expect(titleOf("hugging_face")).toBe("Hugging Face");
    expect(titleOf("new-app")).toBe("New app");
    expect(markOf("google-workspace")).toBe("google");
    expect(markOf("notion")).toBe("notion");
  });

  it("orders sections work, ops, more; what the bot has first; drops empty sections; filters by name, title or text", () => {
    const apps = [app("wolfram", "available", "none"), app("notion", "available"), app("linear", "installed"), app("vercel", "available")];
    const skills = [skill("google-workspace", "installed"), skill("box", "available")];
    const got = sections(apps, skills);
    expect(got.map((s) => s.tier)).toEqual(["work", "ops", "more"]);
    const names = got[0].cards.map((c) => (c.kind === "mcp" ? c.app.name : c.skill.name));
    expect(names).toEqual(["google-workspace", "linear", "box", "notion"]);
    expect(sections(apps, skills, "jira").length).toBe(0);
    expect(sections([app("atlassian", "available")], [], "jira")[0].cards.length).toBe(1);
    expect(sections(apps, skills, "VERCEL").map((s) => s.tier)).toEqual(["ops"]);
    expect(sections(apps, skills, "box skill")[0].cards.length).toBe(1);
  });
});

describe("the line after a run that worked", () => {
  it("says what changed and how the bot gets the tools", () => {
    expect(doneWords("install", "installed", "deepwiki", "Demo")).toContain("DeepWiki is connected to Demo");
    expect(doneWords("install", "installed", "deepwiki", "Demo")).toContain("/reload-mcp");
    expect(doneWords("install", "needs_signin", "notion", "Demo")).toBe("Notion is added to Demo. Sign in to finish.");
    expect(doneWords("login", "installed", "notion", "Demo")).toContain("Demo is signed in to Notion");
    expect(doneWords("remove", "available", "notion", "Demo")).toBe("Notion is removed from Demo.");
  });
});
