// A bot's agent draft (```omher-agent): parsed from finished bot replies, checked as the shell checks it (stricter
// than the form: no shell or interpreter, no built-in program), one chip per block, and chips only in a bot's main
// chat and Hermes folder chats, never a CLI agent's session chat. The chip opens the form's own confirm card, filled
// from the draft; nothing is written until its Add.
import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { draftBot, draftsAllowed, parseDrafts } from "./agentDraft";
import { AgentChips } from "./AgentChip";
import { Bubble } from "./Bubble";
import { botRefusal, INTERPRETERS } from "../../sessions/custom";
import { MockHost } from "../../sessions/host";
import { t } from "../../i18n";

const block = (o: unknown, lang = "omher-agent") => "```" + lang + "\n" + (typeof o === "string" ? o : JSON.stringify(o)) + "\n```";
const CURSOR = { name: "Cursor Agent", program: "cursor-agent", args: ["acp"], install: "npm install -g @cursor/agent" };

describe("parseDrafts", () => {
  it("reads one JSON object per fenced block, ignores unknown keys, and defaults args and install", () => {
    const text = `Here is a draft:\n\n${block({ ...CURSOR, env: { KEY: "x" }, why: "you asked" })}\n\nPress the chip.`;
    expect(parseDrafts(text)).toEqual([{ draft: CURSOR, why: null }]);
    expect(parseDrafts(block({ name: " Stub ", program: "stub-acp" }))).toEqual([{ draft: { name: "Stub", program: "stub-acp", args: [], install: "" }, why: null }]);
    // ~~~ fences and longer fences too; other languages and inline code are not drafts
    expect(parseDrafts("~~~omher-agent\n" + JSON.stringify(CURSOR) + "\n~~~")).toHaveLength(1);
    expect(parseDrafts("````omher-agent\n" + JSON.stringify(CURSOR) + "\n````")).toHaveLength(1);
    expect(parseDrafts(block(CURSOR, "json"))).toEqual([]);
    expect(parseDrafts("`omher-agent` " + JSON.stringify(CURSOR))).toEqual([]);
  });

  it("two blocks make two drafts, in order", () => {
    const text = `${block(CURSOR)}\n\nor\n\n${block({ name: "Stub ACP", program: "stub-acp", args: ["--acp"] })}`;
    expect(parseDrafts(text).map((b) => b.draft?.name)).toEqual(["Cursor Agent", "Stub ACP"]);
  });

  it("invalid JSON or the wrong shape is a refusal, not a draft", () => {
    expect(parseDrafts(block("{name: 'x'}"))).toEqual([{ draft: null, why: "json" }]);
    expect(parseDrafts(block("[1, 2]"))).toEqual([{ draft: null, why: "json" }]);
    expect(parseDrafts(block({ name: "x", program: 3 }))).toEqual([{ draft: null, why: "shape" }]);
    expect(parseDrafts(block({ name: "x", program: "y", args: "acp" }))).toEqual([{ draft: null, why: "shape" }]);
    expect(parseDrafts(block({ name: "x", program: "y", args: [1] }))).toEqual([{ draft: null, why: "shape" }]);
  });

  it("refuses shell characters in any field, as the form does", () => {
    for (const [patch, why] of [
      [{ program: "cursor-agent; rm -rf ~" }, "program"],
      [{ program: "$(curl x)" }, "program"],
      [{ args: ["acp", "$(id)"] }, "args"],
      [{ args: ["acp && rm -rf ~"] }, "args"],
      [{ args: ["a b"] }, "args"],
      [{ name: "x`id`" }, "label"],
      [{ install: "curl -fsSL x | sh" }, "install"],
      [{ program: "./run.sh" }, "program"],
    ] as const)
      expect(parseDrafts(block({ ...CURSOR, ...patch }))[0].why, JSON.stringify(patch)).toBe(why);
  });

  it("is stricter than the form: no shell, interpreter or launcher, any case, with or without .exe or a folder", () => {
    for (const p of ["sh", "BASH", "/bin/zsh", "/usr/bin/env", "python3", "Node.exe", "pwsh", "powershell", "osascript", "sudo", "doas", "open", "xargs", "deno", "bun", "/opt/homebrew/bin/ruby"])
      expect(parseDrafts(block({ ...CURSOR, program: p }))[0].why, p).toBe("interp");
    expect(INTERPRETERS).toHaveLength(25);
    // OpenCode, Kilo Code and a built-in agent's program get the form's own refusal
    expect(parseDrafts(block({ ...CURSOR, program: "opencode" }))[0].why).toBe("opencode");
    expect(parseDrafts(block({ ...CURSOR, program: "/usr/local/bin/kilo" }))[0].why).toBe("kilo");
    for (const p of ["claude", "codex", "gemini", "cline"]) expect(botRefusal(p), p).toBe("builtin");
    expect(t("ag.why.opencode")).toBe("Use the built-in OpenCode.");
    expect(t("ag.why.interp")).toBe("A bot may not propose a shell or an interpreter as the program.");
  });
});

describe("where drafts are read", () => {
  it("in a bot's main chat and a Hermes folder chat only, never a CLI agent's session chat", () => {
    expect(draftsAllowed("kami")).toBe(true);
    expect(draftsAllowed("fold:kami:f1")).toBe(true);
    expect(draftsAllowed("agent:s3")).toBe(false);
    expect(draftBot("kami")).toBe("kami");
    expect(draftBot("fold:friren:f1")).toBe("friren");
  });

  it("draws one chip per draft under a finished bot reply in an allowed chat, a refused one disabled with its reason", () => {
    const text = `${block(CURSOR)}\n${block({ ...CURSOR, program: "bash" })}`;
    const main = renderToStaticMarkup(createElement(AgentChips, { chatKey: "kami", text }));
    expect(main.match(/data-testid="agent-chip"/g)).toHaveLength(2);
    expect(main).toContain(`title="${t("ag.why.interp")}"`);
    expect(main).toMatch(/disabled=""[^>]*data-why="interp"/);
    expect(renderToStaticMarkup(createElement(AgentChips, { chatKey: "fold:kami:f1", text }))).toContain("agent-chip");
    expect(renderToStaticMarkup(createElement(AgentChips, { chatKey: "agent:s3", text }))).toBe("");
    // through the bubble: a finished bot reply gets them, the code block stays; a user message and a streaming reply do not
    const bot = renderToStaticMarkup(createElement(Bubble, { item: { kind: "assistant", text }, bot: "kami" }));
    expect(bot).toContain('data-testid="agent-chips"');
    expect(bot).toContain("<pre>");
    expect(renderToStaticMarkup(createElement(Bubble, { item: { kind: "assistant", text }, bot: "kami", streaming: true }))).not.toContain("agent-chip");
    expect(renderToStaticMarkup(createElement(Bubble, { item: { kind: "user", text } }))).not.toContain("agent-chip");
    expect(renderToStaticMarkup(createElement(Bubble, { item: { kind: "assistant", text }, bot: "agent:s3" }))).not.toContain("agent-chip");
  });
});

describe("the bot's card", () => {
  it("the shell checks the draft again, stricter than the form, and writes nothing", async () => {
    const g: Record<string, unknown> = {};
    const host = new MockHost(g);
    const p = await host.customBotPreview("Cursor Agent", "cursor-agent", ["acp"], "");
    expect(p).toEqual({ entry: { id: "cursor-agent", label: "Cursor Agent", program: "cursor-agent", args: ["acp"], install: "" }, command: "/opt/homebrew/bin/cursor-agent acp" });
    await expect(host.customBotPreview("X", "bash", ["-c", "id"], "")).rejects.toThrow("why:interp");
    await expect(host.customBotPreview("X", "/bin/sh", ["acp"], "")).rejects.toThrow("why:interp");
    await expect(host.customBotPreview("X", "codex", ["acp"], "")).rejects.toThrow("why:builtin");
    // an argument holding a space is refused, not split into two
    await expect(host.customBotPreview("X", "cursor-agent", ["acp --yolo"], "")).rejects.toThrow("why:args");
    // the form still lets a person name a shell (the card shows it)
    await expect(host.customPreview("X", "bash", "acp", "")).resolves.toBeTruthy();
    expect(g.__omherCustomFile).toBeUndefined();
    expect(t("ag.cardBy", { bot: "Milo" })).toBe("Proposed by Milo");
  });
});
