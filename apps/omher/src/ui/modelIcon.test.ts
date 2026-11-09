import { describe, expect, it } from "vitest";
import { markFor } from "./ModelIcon";
import { MODEL_MARKS } from "./modelMarks";

describe("markFor", () => {
  it("names the company behind the model, from the model name first", () => {
    const cases: [string, string | undefined, string | null][] = [
      ["Opus 5.5", "claude-proxy", "claude"],
      ["claude-sonnet-5-5", undefined, "claude"],
      ["anthropic/claude-opus-5-5", "og", "claude"],
      ["gpt-6.1-sol", "openai", "openai"],
      ["gpt-5.5-mini", undefined, "openai"],
      ["x-ai/grok-4.7", "openrouter", "grok"],
      ["z-ai/glm-5.3-ultrafast", "og", "zhipu"],
      ["deepseek/deepseek-v4.1-flash-ultrafast", "og", "deepseek"],
      ["moonshotai/kimi-k3-ultrafast", "og", "kimi"],
      ["gemini-3-pro", undefined, "gemini"],
      ["qwen3-coder", undefined, "qwen"],
      ["llama-4-maverick", "ollama", "meta"],
    ];
    for (const [m, p, want] of cases) expect(markFor(m, p), m).toBe(want);
  });
  it("falls back to the provider, then to nothing", () => {
    expect(markFor("some-local-model", "ollama")).toBe("ollama");
    expect(markFor("mystery-7b", "openrouter OpenRouter")).toBe("openrouter");
    expect(markFor("mystery-7b", "og")).toBeNull();
    expect(markFor(undefined, undefined)).toBeNull();
  });
  it("every mark it can return exists, with ids that do not clash between marks", () => {
    const ids = Object.values(MODEL_MARKS).flatMap((m) => [...m.body.matchAll(/id="([^"]+)"/g)].map((x) => x[1]));
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ["claude", "openai", "gemini", "deepseek", "grok", "kimi", "zhipu", "qwen", "mistral", "meta", "ollama", "openrouter"])
      expect(MODEL_MARKS[id]?.body.length ?? 0, id).toBeGreaterThan(20);
  });
});
