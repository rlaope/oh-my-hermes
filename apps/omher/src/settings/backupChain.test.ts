// A bot's backup model (BOUNDARY rule 57): what the picker offers, the whole list `fallback.set` sends, and the row a
// chat keeps where Hermes switched its turn to the backup model.
import { describe, expect, it } from "vitest";
import { modelRows } from "../chat/model/modelSearch";
import { fallbackDetail, initialState, reduce, type Action, type SystemItem } from "../state/store";
import type { BridgeEvent } from "../lib/protocol";
import { BACKUP_VALUE, backupOptions, withBackup, withoutBackup } from "./backupChain";

const PROVIDERS = [
  { slug: "openai", name: "OpenAI", models: ["gpt-6.1-sol", "gpt-6.1-terra"] },
  { slug: "openrouter", name: "OpenRouter", models: ["x-ai/grok-4.7", "qwen/qwen3-coder"] },
  { slug: "claude-proxy", name: "Claude (proxy)", models: ["Opus 5.5"] },
];
const ids = (rows: ReturnType<typeof modelRows>) => rows.map((r) => `${r.provider.slug}/${r.model}`);

describe("backup options", () => {
  it("offer the bot's own list without its main model, the list's models and ids the bridge refuses", () => {
    const rows = modelRows(PROVIDERS);
    const got = backupOptions(rows, [{ provider: "openrouter", model: "X-AI/Grok-4.7" }], { provider: "openai", model: "gpt-6.1-sol" });
    expect(ids(got)).toEqual(["openai/gpt-6.1-terra", "openrouter/qwen/qwen3-coder"]);
  });

  it("match the bridge's charset", () => {
    for (const ok of ["gpt-6.1-sol", "qwen3:8b", "claude-opus-4-5@20251101", "x-ai/grok-4.7"]) expect(BACKUP_VALUE.test(ok), ok).toBe(true);
    for (const bad of ["Opus 5.5", "-p", "a;b", "x:", "@x", "a,b", "a}b", "", "x".repeat(129)]) expect(BACKUP_VALUE.test(bad), bad).toBe(false);
  });

  it("send the whole list as provider and model only", () => {
    const chain = [{ provider: "openai", model: "a", custom: true as const }, { provider: "openrouter", model: "b" }];
    expect(withBackup(chain, { provider: "ollama", model: "c" })).toEqual([
      { provider: "openai", model: "a" },
      { provider: "openrouter", model: "b" },
      { provider: "ollama", model: "c" },
    ]);
    expect(withoutBackup(chain, 0)).toEqual([{ provider: "openrouter", model: "b" }]);
    expect(withoutBackup([{ provider: "openai", model: "a" }], 0)).toEqual([]);
  });
});

describe("the switch notice", () => {
  const LINE = "⚠️ Model fallback: gpt-6.1-sol via openai could not respond (rate limited); using x-ai/grok-4.7 via openrouter.";
  const run = (events: BridgeEvent[]) =>
    events.reduce((s, ev, i) => reduce(s, { type: "event", ev, now: 1000 + i } as Action), initialState());
  const notices = (s: ReturnType<typeof initialState>, key = "kami") =>
    (s.chats[key]?.items ?? []).filter((i): i is SystemItem => i.kind === "system");

  it("Hermes' sentence without its sign and label is the detail", () => {
    expect(fallbackDetail(LINE)).toBe("gpt-6.1-sol via openai could not respond (rate limited); using x-ai/grok-4.7 via openrouter.");
    expect(fallbackDetail("⚠ Model fallback: a; using b.")).toBe("a; using b.");
    expect(fallbackDetail("Using another model now.")).toBe("Using another model now.");
    // Hermes' pre-agent notice is the same status kind, with its own label
    expect(fallbackDetail("⚠️ Provider fallback: openai could not be reached; using openrouter.")).toBe("openai could not be reached; using openrouter.");
    expect(fallbackDetail("provider FALLBACK: a")).toBe("a");
  });

  it("a marked status leaves a lasting row and keeps the passing status line; the title is not fixed in one language", () => {
    const s = run([
      { event: "turn.start", bot: "kami" },
      { event: "status", bot: "kami", text: LINE, fallback: true },
    ]);
    const rows = notices(s);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ notice: "fallback", text: LINE, detail: fallbackDetail(LINE) });
    expect(JSON.stringify(rows[0])).not.toContain("backup model");
    expect(s.chats.kami.turn?.status).toBe(LINE);
    // a walk down the chain: each switch adds its own row
    const walk = run([
      { event: "turn.start", bot: "kami" },
      { event: "status", bot: "kami", text: LINE, fallback: true },
      { event: "status", bot: "kami", text: "⚠️ Model fallback: x-ai/grok-4.7 via openrouter could not respond; using qwen3:8b via ollama.", fallback: true },
    ]);
    expect(notices(walk)).toHaveLength(2);
    // the row stays after the turn ends; another status line adds none
    const after = run([
      { event: "turn.start", bot: "kami" },
      { event: "status", bot: "kami", text: LINE, fallback: true },
      { event: "status", bot: "kami", text: "Retrying (2/3)" },
      { event: "turn.end", bot: "kami", outcome: "done" } as BridgeEvent,
    ]);
    expect(notices(after)).toHaveLength(1);
  });

  it("lands in the chat that switched: a thread's own key", () => {
    const s = run([{ event: "status", bot: "kami", session: "th1", text: LINE, fallback: true }]);
    expect(notices(s)).toHaveLength(0);
    expect(notices(s, "fold:kami:th1")).toHaveLength(1);
  });
});
