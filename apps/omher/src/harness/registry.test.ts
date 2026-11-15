import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { HARNESSES, harness, harnessByName, harnessOf } from "./registry";
import { chatPieces, resultText, stepDetail } from "./session";

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
    expect(stepDetail("exec", "const r = await tools.exec_command({cmd:'pwd'})")).toBe("const r = await tools.exec_command({cmd:'pwd'})");
    expect(stepDetail("web_search", '{"query":"omh"}')).toBe("omh");
  });
});
