import { describe, expect, it } from "vitest";
import { filterRows, matchesModel, modelRows, vendorOf, vendorsPresent } from "./modelSearch";

const PROVIDERS = [
  { slug: "claude-proxy", name: "Claude (proxy)", models: ["Opus 5.5", "claude-opus-5-5"] },
  { slug: "openai", name: "OpenAI", models: ["gpt-6.1-sol", "gpt-6.1-terra"] },
  { slug: "openrouter", name: "OpenRouter", models: ["google/gemini-3-pro", "x-ai/grok-4.7", "mystery-7b"] },
];
const rows = modelRows(PROVIDERS);
const find = (q: string, vendor = "all") => filterRows(rows, q, vendor).map((r) => r.model);

describe("model search", () => {
  it("files each model under the company behind it, provider-only marks under Other", () => {
    expect(rows.map((r) => r.vendor)).toEqual(["claude", "claude", "openai", "openai", "gemini", "grok", "other"]);
    expect(vendorOf("some-local-model", "ollama")).toBe("other");
    expect(vendorsPresent(rows).map((v) => v.label)).toEqual(["Claude", "OpenAI", "Gemini", "Grok", "Other"]);
  });

  it("matches model id and provider, case-insensitive; empty query keeps everything", () => {
    expect(find("")).toHaveLength(rows.length);
    expect(find("   ")).toHaveLength(rows.length);
    expect(find("GPT-6.1-TERRA")).toEqual(["gpt-6.1-terra"]);
    expect(find("Ini")).toEqual(["google/gemini-3-pro"]); // substring: gemini
    expect(find("openrouter")).toEqual(["google/gemini-3-pro", "x-ai/grok-4.7", "mystery-7b"]);
    expect(find("proxy")).toEqual(["Opus 5.5", "claude-opus-5-5"]);
    expect(find("anthropic")).toEqual(["Opus 5.5", "claude-opus-5-5"]);
  });

  it("matches without separators on either side", () => {
    expect(find("opus55")).toEqual(["Opus 5.5", "claude-opus-5-5"]);
    expect(find("gpt61terra")).toEqual(["gpt-6.1-terra"]);
    expect(find("grok-47")).toEqual(["x-ai/grok-4.7"]);
  });

  it("needs every word, and combines with the vendor chip", () => {
    expect(find("gpt terra")).toEqual(["gpt-6.1-terra"]);
    expect(find("gpt opus")).toEqual([]);
    expect(find("6.1", "openai")).toEqual(["gpt-6.1-sol", "gpt-6.1-terra"]);
    expect(find("", "other")).toEqual(["mystery-7b"]);
    expect(find("gemini", "grok")).toEqual([]);
  });

  it("a query of only separators finds nothing new", () => {
    const r = rows[2];
    expect(matchesModel("-", r)).toBe(true); // literal "-" is in "gpt-6.1-sol"
    expect(matchesModel("--", r)).toBe(false);
  });
});
