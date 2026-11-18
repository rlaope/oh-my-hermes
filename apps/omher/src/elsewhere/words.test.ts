// The 1.0 usability pass: the small words a person reads in the sidebar and the side panel. A bot's preview line
// carries no markdown list marker; a routine's cadence and its last run read as words in the UI language, never
// Hermes' raw state ("ok", "delivery_failed").
import { afterEach, describe, expect, it } from "vitest";
import { plain } from "../sidebar/BotRow";
import { setLang } from "../i18n";
import { cadence, isFailure, statusText } from "./format";

afterEach(() => setLang("en"));

describe("sidebar preview", () => {
  it("drops list markers at a line's start, keeps hyphens inside words", () => {
    expect(plain("Links from today's work:\n- Fix PR rlaope/oh-my-hermes\n- Code")).toBe("Links from today's work: Fix PR rlaope/oh-my-hermes Code");
    expect(plain("1. first\n2) second\n* third\n+ fourth")).toBe("first second third fourth");
    expect(plain("- [ ] open task\n- [x] done task")).toBe("open task done task");
    expect(plain("omh-tui ships a - b range")).toBe("omh-tui ships a - b range");
    expect(plain("-5 degrees")).toBe("-5 degrees");
  });
});

describe("routine words", () => {
  it("cadence is a word in the UI language; other schedules stay as written", () => {
    expect(cadence("Daily 09:00")).toBe("daily");
    expect(cadence("Weekly (Mon 09:00)")).toBe("weekly");
    expect(cadence("every 30m")).toBe("every 30m");
    setLang("ko");
    expect(cadence("Daily 09:00")).toBe("매일");
    expect(cadence("Weekly (Mon 09:00)")).toBe("매주");
    expect(cadence("0 9 * * 1-5")).toBe("0 9 * * 1-5");
  });

  it("a last run reads as a word, never the raw state", () => {
    expect(statusText("ok")).toBe("done");
    expect(statusText("delivery_failed")).toBe("not delivered");
    expect(statusText("weird_new_state")).toBe("weird_new_state");
    setLang("ko");
    expect(statusText("ok")).not.toBe("ok");
    expect(statusText("error")).not.toBe("error");
    // a good run is not a failure because its word is not literally "ok"
    expect(isFailure("success")).toBe(false);
    expect(isFailure("done")).toBe(false);
    expect(isFailure("blocked_config")).toBe(true);
  });
});
