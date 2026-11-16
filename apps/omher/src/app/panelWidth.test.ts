import { beforeEach, describe, expect, it, vi } from "vitest";
import { CHAT_MIN, PANEL_MIN, clampPanel, maxedPanel, panelKind, panelMax, readPanelWidths, savePanelWidth, shownPanelWidth } from "./panelWidth";

describe("panel width", () => {
  const disk = new Map<string, string>();
  beforeEach(() => {
    disk.clear();
    vi.stubGlobal("localStorage", { getItem: (k: string) => disk.get(k) ?? null, setItem: (k: string, v: string) => void disk.set(k, v) });
  });

  it("groups tabs: Details alone, Plans alone, every tool tab together", () => {
    expect(panelKind("details")).toBe("details");
    expect(panelKind("runs")).toBe("runs");
    for (const t of ["terminal", "schedule", "worktrees", "diff"]) expect(panelKind(t)).toBe("tools");
  });

  it("keeps the chat column its room and the panel its minimum", () => {
    expect(panelMax(1280, 248)).toBe(1280 - 248 - CHAT_MIN);
    expect(clampPanel(2000, 1280, 248)).toBe(1280 - 248 - CHAT_MIN);
    expect(clampPanel(100, 1280, 248)).toBe(PANEL_MIN);
    expect(clampPanel(431.6, 1280, 248)).toBe(432);
    // a window too small for both: the panel keeps its minimum
    expect(clampPanel(500, 1100, 900)).toBe(PANEL_MIN);
    // under 1100px the panel slides over the chat: it may grow up to the window less 300px (the sidebar and a strip
    // of chat stay in sight)
    expect(panelMax(900, 248)).toBe(600);
    expect(clampPanel(610, 900, 248)).toBe(600);
  });

  it("saves per kind, forgets one on reset, and ignores junk", () => {
    savePanelWidth("runs", 640);
    savePanelWidth("details", 352.4);
    expect(readPanelWidths()).toEqual({ runs: 640, details: 352 });
    savePanelWidth("runs", null);
    expect(readPanelWidths()).toEqual({ details: 352 });
    localStorage.setItem("omher.panelWidth", JSON.stringify({ details: "wide", tools: 12, runs: 500 }));
    expect(readPanelWidths()).toEqual({ runs: 500 });
    localStorage.setItem("omher.panelWidth", "{not json");
    expect(readPanelWidths()).toEqual({});
  });

  it("maximised takes every pixel right of the sidebar, in a wide window and in the overlay", () => {
    expect(maxedPanel(1440, 248)).toBe(1192);
    expect(maxedPanel(1280, 248.4)).toBe(1032);
    expect(maxedPanel(900, 248)).toBe(652); // under 1100px: the overlay, full width minus the sidebar
    expect(maxedPanel(400, 300)).toBe(PANEL_MIN);
    expect(shownPanelWidth(true, 500, 1440, 248)).toBe(1192);
    expect(shownPanelWidth(true, undefined, 1440, 248)).toBe(1192);
  });

  it("restores the exact width each tab had before, and saves nothing while maximised", () => {
    savePanelWidth("runs", 640);
    savePanelWidth("details", 352);
    const before = readPanelWidths();
    for (const tab of ["details", "runs", "terminal"]) {
      const saved = before[panelKind(tab)];
      const prior = shownPanelWidth(false, saved, 1440, 248);
      expect(shownPanelWidth(true, saved, 1440, 248)).toBe(1192);
      expect(shownPanelWidth(false, saved, 1440, 248)).toBe(prior);
    }
    expect(shownPanelWidth(false, before.runs, 1440, 248)).toBe(640);
    expect(shownPanelWidth(false, before.details, 1440, 248)).toBe(352);
    // a tab with no saved width goes back to the stylesheet's own
    expect(shownPanelWidth(false, before.tools, 1440, 248)).toBeNull();
    expect(readPanelWidths()).toEqual(before);
  });
});
