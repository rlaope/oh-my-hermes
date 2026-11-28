import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { HARNESSES, harness, harnessByName, harnessOf } from "./registry";
import { chatPieces, codexExecCommands, resultText, stepDetail } from "./session";

const ASSETS = join(__dirname, "..", "assets", "agents");

describe("harnessOf", () => {
  it.each([
    // explicit executor / fanout owner first
    [{ executor: "claude-code" }, "claude", "executor"],
    [{ executor: "claude", model: "claude-opus-5-5" }, "claude", "executor"],
    [{ executor: "codex", model: "gpt-6.1-sol" }, "codex", "executor"],
    [{ executor: "omp" }, "omp", "executor"],
    [{ executor: "Codex" }, "codex", "executor"],
    // then the ACP command's basename
    [{ acpCommand: "claude-agent-acp" }, "claude", "acp"],
    [{ acpCommand: "/usr/local/bin/claude-code-acp --verbose" }, "claude", "acp"],
    [{ acpCommand: "codex-acp" }, "codex", "acp"],
    [{ acpCommand: "gemini --experimental-acp" }, "gemini", "acp"],
    [{ acpCommand: "opencode acp" }, "opencode", "acp"],
    [{ acpCommand: "C:\\tools\\kimi-code.exe --acp" }, "kimi", "acp"],
    [{ acpCommand: "qwen --acp" }, "qwen", "acp"],
    [{ acpCommand: "copilot --acp" }, "copilot", "acp"],
    [{ acpCommand: "goose acp" }, "goose", "acp"],
    [{ acpCommand: "cline-acp" }, "cline", "acp"],
    // Antigravity's ACP server is `agy acp`; the installers' own paths on macOS/Linux and Windows
    [{ acpCommand: "agy acp" }, "antigravity", "acp"],
    [{ acpCommand: "/Users/me/.local/bin/agy acp" }, "antigravity", "acp"],
    [{ acpCommand: "C:\\Users\\me\\AppData\\Local\\agy\\bin\\agy.exe acp" }, "antigravity", "acp"],
    [{ executor: "antigravity" }, "antigravity", "executor"],
    [{ executor: "antigravity-cli", model: "gemini-3.5-pro" }, "antigravity", "executor"],
    [{ kind: "agy" }, "antigravity", "executor"],
    // an ACP command no row knows: neutral, never a company's logo
    [{ acpCommand: "mystery-agent --acp", model: "claude-opus-5-5" }, "generic", "acp"],
    // an executor no row knows: neutral by its executor, never Hermes because it reported a model
    [{ executor: "mystery-agent", model: "claude-opus-5-5" }, "generic", "executor"],
    [{ executor: "mystery-agent", model: "gpt-6.1-sol", provider: "openai-codex" }, "generic", "executor"],
    [{ executor: "mystery-agent", kind: "hermes" }, "generic", "executor"],
    [{ executor: "  ", model: "claude-opus-5-5" }, "hermes", "model"],
    // a plain Hermes child on any model is Hermes; the model is a second fact
    [{ model: "claude-opus-5-5", provider: "claude-proxy" }, "hermes", "model"],
    [{ model: "gpt-6.1-sol", provider: "openai-codex" }, "hermes", "model"],
    [{ model: "z-ai/glm-5.3", provider: "og" }, "hermes", "model"],
    [{ kind: "hermes" }, "hermes", "model"],
    [{ kind: "codex" }, "codex", "executor"],
    // a named kind no row knows: neutral by that kind, never Hermes because it reported a model
    [{ kind: "mystery-agent", model: "claude-opus-5-5" }, "generic", "executor"],
    [{ kind: "hermes", model: "claude-opus-5-5" }, "hermes", "model"],
    [{ kind: "", model: "claude-opus-5-5" }, "hermes", "model"],
    [{ kind: "hermes", executor: "mystery-agent", model: "claude-opus-5-5" }, "generic", "executor"],
    [{ executor: "", model: "claude-opus-5-5" }, "hermes", "model"],
    // nothing known
    [{}, "generic", "none"],
    [{ executor: "" }, "generic", "none"],
  ])("%j -> %s", (facts, id, by) => {
    const got = harnessOf(facts);
    expect(got.harness).toBe(id);
    expect(got.by).toBe(by);
  });

  it("a Hermes child on a Claude model is Hermes with a Claude model mark, never Claude Code", () => {
    const got = harnessOf({ model: "claude-opus-5-5", provider: "claude-proxy" });
    expect(got).toEqual({ harness: "hermes", modelMark: "claude", by: "model" });
    expect(harnessOf({ model: "gpt-6.1-sol", provider: "openai-codex" }).modelMark).toBe("openai");
    expect(harnessOf({ model: "grok-5", provider: "og" }).modelMark).toBe("grok");
  });

  it("names map case-insensitively and through aliases", () => {
    expect(harnessByName("Claude-Code")).toBe("claude");
    expect(harnessByName("hermes-agent")).toBe("hermes");
    expect(harnessByName("nobody")).toBeNull();
    expect(harness("nope").id).toBe("generic");
  });
});

describe("HARNESSES", () => {
  it("every row's mark is a file in src/assets/agents, and ids are unique", () => {
    const files = new Set(readdirSync(ASSETS));
    for (const h of HARNESSES) {
      if (h.id === "generic") expect(h.mark).toBe("");
      else expect(files.has(h.mark), `${h.id} -> ${h.mark}`).toBe(true);
      if (h.character) expect(files.has(h.character)).toBe(true);
    }
    expect(new Set(HARNESSES.map((h) => h.id)).size).toBe(HARNESSES.length);
  });

  it("only src/harness reads src/assets/agents (one place)", () => {
    const hits: string[] = [];
    const walk = (dir: string) => {
      for (const e of readdirSync(dir, { withFileTypes: true })) {
        const p = join(dir, e.name);
        if (e.isDirectory()) {
          if (!["harness", "__fixtures__"].includes(e.name)) walk(p);
        } else if (/\.(tsx?|css)$/.test(e.name) && readFileSync(p, "utf8").includes("assets/agents/")) hits.push(p);
      }
    };
    walk(join(__dirname, ".."));
    expect(hits).toEqual([]);
  });
});

describe("session view mapping", () => {
  it("parent words right, child words left, steps grouped in order, the last left bubble is the answer", () => {
    const pieces = chatPieces({
      items: [
        { type: "user", text: "Fix the fence" },
        { type: "assistant", text: "On it." },
        { type: "step", tool: "terminal", input: '{"command":"pytest -q"}', result: "3 passed", ok: true, ts: 10 },
        { type: "step", tool: "Read", input: '{"file_path":"a.py"}', result: "x", ok: true, ts: 12 },
        { type: "user", text: "Also run ruff" },
        { type: "step", tool: "exec_command", input: '{"cmd":["ruff","check"]}', result: "", ok: false, ts: 14 },
        { type: "child", ref: "hermes:abc", kind: "hermes", goal: "Count lines", state: "done", summary: "42", model: "glm-5" },
        { type: "assistant", text: "Done." },
      ],
    });
    expect(pieces.map((p) => p.kind)).toEqual(["user", "assistant", "steps", "user", "steps", "child", "assistant"]);
    const steps = pieces[2].kind === "steps" ? pieces[2].steps : [];
    expect(steps.map((s) => [s.name, s.detail])).toEqual([
      ["terminal", "pytest -q"],
      ["read_file", "a.py"],
    ]);
    const ruff = pieces[4].kind === "steps" ? pieces[4].steps[0] : null;
    expect([ruff?.name, ruff?.detail, ruff?.ok]).toEqual(["terminal", "ruff check", false]);
    expect(pieces[6]).toMatchObject({ kind: "assistant", text: "Done.", last: true });
    expect(pieces[1]).toMatchObject({ last: false });
    expect(pieces[5]).toMatchObject({ kind: "child", ref: "hermes:abc", sub: { goal: "Count lines", model: "glm-5", state: "done" } });
  });

  it("a Hermes tool result reads as its text, a failed exit code after it", () => {
    expect(resultText('{"output": "a\\nb", "exit_code": 0}')).toBe("a\nb");
    expect(resultText('{"output": "x", "exit_code": 2}')).toBe("x\n(exit 2)");
    expect(resultText('{"content": "1|hi"}')).toBe("1|hi");
    expect(resultText("plain")).toBe("plain");
  });

  it("a step's one line: the command, path or query; plain text as its first words", () => {
    expect(stepDetail("terminal", '{"command":"ls -la\\n  && pwd"}')).toBe("ls -la && pwd");
    // a Codex exec step's JavaScript reads as the command it runs, not the wrapper around it
    expect(stepDetail("exec", "const r = await tools.exec_command({cmd:'pwd'})")).toBe("pwd");
    expect(stepDetail("web_search", '{"query":"omh"}')).toBe("omh");
  });

  it("a Codex exec step: the commands out of its code, escapes decoded; no cmd leaves it as it was", () => {
    const one = 'text(await tools.exec_command({cmd:"touch probe.txt",workdir:"/w",justification:"Allow `touch`?"}))';
    expect(codexExecCommands(one)).toEqual(["touch probe.txt"]);
    const several =
      'const [a, b] = await Promise.all([tools.exec_command({cmd: "git status"}), tools.exec_command({ cmd: \'ls -la\' }),' +
      " tools.exec_command({cmd:`cat a.txt`})])";
    expect(codexExecCommands(several)).toEqual(["git status", "ls -la", "cat a.txt"]);
    expect(stepDetail("exec", several)).toBe("git status + 2 more");
    expect(codexExecCommands('tools.exec_command({cmd:"echo \\"hi\\" && printf \'a\\\\tb\'\\nls"})')).toEqual([
      'echo "hi" && printf \'a\\tb\'\nls',
    ]);
    expect(codexExecCommands("tools.exec_command({cmd:'it\\'s'})")).toEqual(["it's"]);
    expect(codexExecCommands("tools.exec_command({cmd:`rg -n \\`x\\` src`})")).toEqual(["rg -n `x` src"]);
    expect(codexExecCommands('tools.exec_command({cmd:"caf\\u00e9"})')).toEqual(["café"]);
    // no cmd (another tool), an unclosed string, a word that only ends in cmd: nothing
    const none = 'const r = await tools.view_image({path:"a.png"}); mycmd: "x"';
    expect(codexExecCommands(none)).toEqual([]);
    expect(codexExecCommands('tools.exec_command({cmd:"never closed')).toEqual([]);
    expect(stepDetail("exec", none)).toBe(none);
    // `cmd:` inside another call's string, or in a comment, is no command, and that code is not hidden behind one
    const yml = `await tools.write_file({path:"ci.yml", content:"steps:\\n  - cmd: 'rm -rf dist'"})`;
    expect(codexExecCommands(yml)).toEqual([]);
    expect(stepDetail("exec", yml)).toMatch(/^await tools\.write_file\(/);
    expect(codexExecCommands('// cmd: "x"\nconst r = 1;')).toEqual([]);
    expect(codexExecCommands('/* cmd: "x" */ const r = await tools.exec_command({cmd:"ls"}) // then cmd: "y"')).toEqual(["ls"]);
    // a step that runs a command and does something else too: left as it was, so the other code shows
    const mixed = 'const r = await tools.exec_command({cmd:"ls"}); await tools.apply_patch({input:"*** Begin Patch\\n*** End Patch"})';
    expect(codexExecCommands(mixed)).toEqual([]);
    expect(stepDetail("exec", mixed)).toBe(mixed);
    expect(codexExecCommands('const r = await tools.exec_command({cmd:"ls"}); if (r.exit_code) text("failed")')).toEqual([]);
    // only the call's own `cmd` key: not one nested deeper in its argument, not one of a string's text
    expect(codexExecCommands('tools.exec_command({env:{cmd:"x"}, cmd:"pwd", justification:"cmd: rm"})')).toEqual(["pwd"]);
    // a template's ${…} is skipped as written, quotes inside it included
    expect(codexExecCommands('tools.exec_command({cmd:`echo ${"}"} done`})')).toEqual(['echo ${"}"} done']);
    // the chat shows it as a shell step: one command reads on its row, several in its box
    const pieces = chatPieces({
      items: [
        { type: "step", tool: "exec", input: one, result: "", ok: true, ts: 1 },
        { type: "step", tool: "exec", input: several, result: "", ok: true, ts: 2 },
        { type: "step", tool: "exec", input: none, result: "", ok: true, ts: 3 },
      ],
    });
    const steps = pieces[0].kind === "steps" ? pieces[0].steps : [];
    expect(steps.map((s) => [s.name, s.detail, s.input])).toEqual([
      ["terminal", "touch probe.txt", ""],
      ["terminal", "git status + 2 more", "git status\nls -la\ncat a.txt"],
      ["terminal", none, none],
    ]);
  });

  it("an interrupt, a compaction and an API error are one quiet status line each", () => {
    const pieces = chatPieces({
      items: [
        { type: "user", text: "go" },
        { type: "status", code: "interrupted" },
        { type: "status", code: "compacted" },
        { type: "status", code: "api_error", text: "Overloaded", status: 529, retry: 3, retries: 10 },
        { type: "status", code: "api_error", text: "You've hit your weekly limit · resets 9pm" },
        { type: "status", code: "something_new" },
        { type: "assistant", text: "Done." },
      ],
    });
    expect(pieces.map((p) => (p.kind === "status" ? p.text : p.kind))).toEqual([
      "user",
      "Interrupted",
      "Conversation compacted",
      "API error 529 · retry 3/10 · Overloaded",
      "API error · You've hit your weekly limit · resets 9pm",
      "assistant",
    ]);
    expect(pieces[5]).toMatchObject({ kind: "assistant", last: true });
  });
});
