import { afterEach, describe, expect, it } from "vitest";
import { levelOptions, reasoningPill, sentInstead } from "./levels";
import { initialState, reduce } from "../../state/store";
import { setLang } from "../../i18n";

describe("chat reasoning levels", () => {
  afterEach(() => setLang("en"));

  it("offers the bot's own levels, else Hermes' full ladder in its order", () => {
    expect(levelOptions(["none", "low", "high"]).map((o) => o.value)).toEqual(["none", "low", "high"]);
    const full = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"];
    expect(levelOptions().map((o) => o.value)).toEqual(full);
    expect(levelOptions([]).map((o) => o.label)).toEqual(full);
  });

  it("says what the route sends only when Hermes reports a different level", () => {
    expect(sentInstead("ultra", "max")).toBe("max");
    expect(sentInstead("minimal", "low")).toBe("low");
    expect(sentInstead("xhigh", "xhigh")).toBe("");
    expect(sentInstead("ultra", "")).toBe(""); // Hermes did not say: no claim either way
    expect(sentInstead("ultra", undefined)).toBe("");
    expect(sentInstead("", "max")).toBe("");
    expect(reasoningPill("ultra", "max")).toBe("ultra · sends max");
    expect(reasoningPill("high", "high")).toBe("high");
    expect(reasoningPill("ultra")).toBe("ultra");
    setLang("ko");
    expect(reasoningPill("ultra", "max")).toBe("ultra · 실제 max");
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
});
