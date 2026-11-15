import { beforeEach, describe, expect, it, vi } from "vitest";
import { CHAT_MIN, PANEL_MIN, clampPanel, panelKind, panelMax, readPanelWidths, savePanelWidth } from "./panelWidth";

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
});
