import { afterEach, describe, expect, it } from "vitest";
import { levelOptions, reasoningPill, sentLevel } from "./levels";
import { initialState, reduce } from "../../state/store";
import { setLang } from "../../i18n";

describe("chat reasoning levels", () => {
  afterEach(() => setLang("en"));

  it("offers the levels of the bot's route, else Hermes' full ladder in its order", () => {
    const claude = ["none", "minimal", "low", "medium", "high", "xhigh", "max"];
    expect(levelOptions(claude).map((o) => o.value)).toEqual(claude); // no ultra next to max
    const full = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"];
    expect(levelOptions().map((o) => o.value)).toEqual(full);
    expect(levelOptions([]).map((o) => o.label)).toEqual(full);
  });

  it("shows the level the route sends, alone, whatever the saved pick", () => {
    expect(sentLevel("ultra", "max")).toBe("max");
    expect(sentLevel("minimal", "low")).toBe("low");
    expect(sentLevel("xhigh", "xhigh")).toBe("xhigh");
    expect(sentLevel("ultra", "")).toBe("ultra"); // Hermes did not say: the pick
    expect(sentLevel("none", "")).toBe("none"); // thinking off carries no wire level
    expect(sentLevel("", "max")).toBe("");
    expect(reasoningPill("ultra", "max")).toBe("max");
    expect(reasoningPill("high", "high")).toBe("high");
    expect(reasoningPill("ultra")).toBe("ultra");
    setLang("ko");
    expect(reasoningPill("ultra", "max")).toBe("max"); // a level name, never a sentence, in every language
  });

  it("a saved none on a route that cannot send it shows and selects no level", () => {
    const astra = ["low", "medium", "high", "xhigh", "max"]; // Hermes' CODEX_ASTRA_EFFORTS: no none
    expect(sentLevel("none", "", astra)).toBe("");
    expect(reasoningPill("none", "", astra)).toBe("");
    expect(sentLevel("high", "high", astra)).toBe("high");
    const compat = ["none", "minimal", "low", "medium", "high", "xhigh", "max"];
    expect(sentLevel("none", "", compat)).toBe("none"); // a route that sends none keeps it
    expect(sentLevel("ultra", "max", compat)).toBe("max");
    expect(sentLevel("none", "", [])).toBe("none"); // no route levels yet: the pick
  });

  it("keeps the route's level with the chat from chat.open and chat.set_model", () => {
    const res = { session_id: "s", messages: [], running: false, model: "m", provider: "p", reasoning: "ultra" };
    let s = reduce(initialState(), { type: "chat.opened", bot: "kami", res: { ...res, reasoning_wire: "max" }, now: 1 });
    expect(s.chats.kami.reasoningWire).toBe("max");
    s = reduce(s, { type: "model.set", bot: "kami", current: { model: "m", provider: "p", reasoning: "high", reasoning_wire: "high" } });
    expect([s.chats.kami.reasoning, s.chats.kami.reasoningWire]).toEqual(["high", "high"]);
    s = reduce(s, { type: "chat.opened", bot: "kami", res, now: 2 }); // an older bridge sends none
    expect(s.chats.kami.reasoningWire).toBe("");
  });

  it("takes the new route's levels from chat.set_model, and keeps them when an older bridge sends none", () => {
    const claude = ["none", "minimal", "low", "medium", "high", "xhigh", "max"];
    const codex = ["none", "low", "medium", "high", "xhigh", "max", "ultra"];
    const cur = { model: "Opus 5.5", provider: "claude-proxy", reasoning: "high", reasoning_wire: "high" };
    let s = reduce(initialState(), { type: "models", bot: "kami", options: { providers: [], current: cur, reasoning_levels: claude } });
    s = reduce(s, {
      type: "model.set",
      bot: "kami",
      current: { model: "gpt-6-sol", provider: "openai-codex", reasoning: "high", reasoning_wire: "high", reasoning_levels: codex },
    });
    expect(s.models.kami.reasoning_levels).toEqual(codex);
    expect(s.models.kami.current).toEqual({ model: "gpt-6-sol", provider: "openai-codex", reasoning: "high", reasoning_wire: "high" });
    s = reduce(s, { type: "model.set", bot: "kami", current: { ...cur, reasoning: "low", reasoning_wire: "low" } });
    expect(s.models.kami.reasoning_levels).toEqual(codex);
    expect(s.models.kami.current.reasoning).toBe("low");
  });
});
