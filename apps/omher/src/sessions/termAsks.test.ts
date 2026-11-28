// The terminal asks store: a dialog is new once (one notification), the same dialog read again is not, a different
// dialog in the same row replaces it, a row's ask leaves on clear, the setting off keeps them out and clears them, and
// picking one (`jumpToAsk` with its `term:` key) opens that row through the hook SESSIONS sets.
import { afterEach, describe, expect, it, vi } from "vitest";
import { clearTermAsk, hasTermAsk, setTermAsk, termAskKey, termAsks } from "./termAsks";
import { resetTermSettings, writeTermSettings } from "./term/settings";
import { getStore, setTermAskOpen } from "../state/store";

const dialog = { agent: "claude", kind: "approve" as const, title: "Bash command: touch probe.txt", options: ["Yes", "No"], name: "web-app · Claude Code" };

afterEach(() => {
  for (const a of termAsks()) clearTermAsk(a.session);
  resetTermSettings();
  setTermAskOpen(null);
});

describe("termAsks", () => {
  it("a dialog is new once; read again it is the same ask", () => {
    expect(setTermAsk("s1", dialog)).toBe(true);
    const first = termAsks()[0];
    expect(setTermAsk("s1", dialog)).toBe(false);
    expect(termAsks()).toEqual([first]);
    expect(hasTermAsk("s1")).toBe(true);
  });

  it("another dialog in the same row replaces it, as a new ask", () => {
    setTermAsk("s1", dialog);
    const was = termAsks()[0].id;
    expect(setTermAsk("s1", { ...dialog, title: "Edit notes.md" })).toBe(true);
    expect(termAsks()).toHaveLength(1);
    expect(termAsks()[0].id).not.toBe(was);
  });

  it("leaves when its row clears it, oldest first among the rest", () => {
    setTermAsk("s1", dialog);
    setTermAsk("s2", { ...dialog, title: "$ touch probe.txt", agent: "codex" });
    clearTermAsk("s1");
    expect(termAsks().map((a) => a.session)).toEqual(["s2"]);
  });

  it("the setting off keeps new ones out and takes the shown ones away", () => {
    setTermAsk("s1", dialog);
    writeTermSettings({ agentAsks: false });
    expect(termAsks()).toEqual([]);
    expect(setTermAsk("s2", dialog)).toBe(false);
    expect(termAsks()).toEqual([]);
  });

  it("jumpToAsk with a terminal ask's key opens that row", async () => {
    const open = vi.fn();
    setTermAskOpen(open);
    setTermAsk("s7", dialog);
    await getStore().actions.jumpToAsk(termAskKey("s7"), termAsks()[0].id);
    expect(open).toHaveBeenCalledWith("s7");
    expect(getStore().getState().ui.focusAsk).toMatchObject({ bot: "term:s7" });
  });
});
