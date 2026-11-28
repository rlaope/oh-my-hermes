import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../../i18n";
import type { BridgeEvent } from "../../lib/protocol";
import { activityText, initialState, keptShots, liveLabel, reduce, SHOTS_KEPT, SHOTS_TOTAL, type Action, type AppState } from "../../state/store";
import { browserLine, isBrowserSentence } from "./browserSteps";

const run = (state: AppState, evs: BridgeEvent[]) =>
  evs.reduce((s, ev, i) => reduce(s, { type: "event", ev, now: 1_800_000_000_000 + i * 100 } as Action), state);

describe("a browser step", () => {
  afterEach(() => setLang("en"));

  it("reads as the label the model wrote, or a plain line without one", () => {
    expect(browserLine("browser_exec", undefined, "Searching Amazon for paper towels", false)).toBe("Searching Amazon for paper towels");
    expect(browserLine("browser_exec", undefined, "", false)).toBe("Used the browser");
    expect(browserLine("browser_exec", undefined, "  ", true)).toBe("Using the browser");
    expect(activityText("browser_exec", "Opening the login page")).toBe("Opening the login page");
    expect(activityText("browser_exec", "")).toBe("Using the browser");
  });

  it("names a dialog's and a saved login's action in plain words, never a value", () => {
    expect(browserLine("browser_dialog", "accept", "", false)).toBe("Accepted a page dialog");
    expect(browserLine("browser_dialog", "dismiss", "", true)).toBe("Dismissing a page dialog");
    expect(browserLine("browser_dialog", undefined, "", false)).toBe("Answered a page dialog");
    expect(browserLine("browser_vault", "fill", "", false)).toBe("Filled in a saved login");
    expect(browserLine("browser_vault", "enter_code", "", true)).toBe("Entering a sign-in code");
    expect(browserLine("browser_vault", "save_login", "", false)).toBe("Saved a login");
    expect(browserLine("browser_vault", "unlock", "", false)).toBe("Unlocked a password manager");
    expect(browserLine("browser_vault", "list", "", false)).toBe("Checked saved logins");
    expect(browserLine("browser_vault", "steal", "", false)).toBe("Used saved logins");
    // a CDP call is a verb and its method, as the other tools read
    expect(isBrowserSentence("browser_cdp")).toBe(false);
    expect(activityText("browser_cdp", "Page.navigate")).toBe("Running browser command Page.navigate");
  });

  it("is the running line in the current language, the label as it is", () => {
    setLang("ko");
    expect(activityText("browser_dialog", "", "accept")).toBe("페이지 대화상자 수락 중");
    expect(browserLine("browser_exec", undefined, "", false)).toBe("브라우저 사용");
    setLang("ja");
    expect(browserLine("browser_vault", "fill", "", false)).toBe("保存済みのログイン情報を入力");
    setLang("zh");
    expect(browserLine("browser_exec", undefined, "Searching", true)).toBe("Searching");
    expect(browserLine("browser_exec", undefined, "", true)).toBe("正在使用浏览器");
  });

  it("the live line keeps a label whole: it is not split into a verb and code", () => {
    const s = run(initialState(), [
      { event: "turn.start", bot: "kami" },
      { event: "tool.start", bot: "kami", tool_id: "b1", name: "browser_exec", detail: "Checking the cart" },
    ]);
    expect(liveLabel(s.chats.kami.turn!)).toEqual({ verb: "Checking the cart" });
  });
});

describe("a step's screenshot", () => {
  const shot = (tool_id: string, mime = "image/png", data = "iVBORw0KGgo="): BridgeEvent => ({ event: "tool.shot", bot: "kami", tool_id, mime, data_base64: data });

  it("is kept for a step of the running turn, by its id", () => {
    const s = run(initialState(), [
      { event: "turn.start", bot: "kami" },
      { event: "tool.start", bot: "kami", tool_id: "b1", name: "browser_exec", detail: "" },
      { event: "tool.end", bot: "kami", tool_id: "b1", name: "browser_exec", ok: true, ms: 5 },
      shot("b1"),
    ]);
    expect(s.chats.kami.shots).toEqual([{ id: "b1", url: "data:image/png;base64,iVBORw0KGgo=", n: 1 }]);
  });

  it("is dropped for a step no turn here holds, a type the bridge never sends, or no bytes", () => {
    let s = run(initialState(), [{ event: "turn.start", bot: "kami" }, { event: "tool.start", bot: "kami", tool_id: "b1", name: "browser_exec", detail: "" }]);
    s = run(s, [shot("zz"), shot("b1", "image/svg+xml"), shot("b1", "text/html"), shot("b1", "image/png", "")]);
    expect(s.chats.kami.shots).toBeUndefined();
    // a chat that never opened gets nothing either
    expect(run(initialState(), [shot("b1")]).chats.friren).toBeUndefined();
  });

  it("keeps the newest SHOTS_KEPT a chat, the oldest dropped first", () => {
    expect(SHOTS_KEPT).toBe(8);
    let kept = keptShots(undefined, "s0", "u0");
    for (let i = 1; i < 20; i += 1) kept = keptShots(kept, `s${i}`, `u${i}`);
    expect(kept.map((x) => x.id)).toEqual(["s12", "s13", "s14", "s15", "s16", "s17", "s18", "s19"]);
    // the same step again replaces its own, it does not take a second place
    kept = keptShots(kept, "s15", "new");
    expect(kept).toHaveLength(SHOTS_KEPT);
    expect(kept.at(-1)).toEqual({ id: "s15", url: "new", n: 0 });
    // through the reducer, across one long browser session
    const evs: BridgeEvent[] = [{ event: "turn.start", bot: "kami" }];
    for (let i = 0; i < 30; i += 1)
      evs.push({ event: "tool.start", bot: "kami", tool_id: `b${i}`, name: "browser_exec", detail: "" }, shot(`b${i}`));
    const s = run(initialState(), evs);
    expect(s.chats.kami.shots!.map((x) => x.id)).toEqual(["b22", "b23", "b24", "b25", "b26", "b27", "b28", "b29"]);
  });

  it("keeps the newest SHOTS_TOTAL across every chat and thread, the oldest dropped first wherever it is", () => {
    expect(SHOTS_TOTAL).toBe(16);
    // three chats (two bots and a thread's folder key) take turns: 3 x 7 = 21 captures, each chat under its own cap
    const keys = ["kami", "friren", "fold:kami:th1"];
    let s = initialState();
    for (const bot of keys) s = run(s, [{ event: "turn.start", bot }]);
    for (let i = 0; i < 21; i += 1) {
      const bot = keys[i % 3];
      s = run(s, [{ event: "tool.start", bot, tool_id: `c${i}`, name: "computer_use", detail: "", action: "capture" }, { ...shot(`c${i}`), bot }]);
    }
    const all = keys.flatMap((k) => s.chats[k].shots ?? []);
    expect(all).toHaveLength(SHOTS_TOTAL);
    // the five oldest (c0..c4) went, from whichever chat held them; every chat stays at or under its own cap
    expect(all.map((x) => Number(x.id.slice(1))).sort((a, b) => a - b)).toEqual(Array.from({ length: 16 }, (_, i) => i + 5));
    for (const k of keys) expect((s.chats[k].shots ?? []).length).toBeLessThanOrEqual(SHOTS_KEPT);
    expect(s.chats.kami.shots!.map((x) => x.id)).toEqual(["c6", "c9", "c12", "c15", "c18"]);
  });
});
