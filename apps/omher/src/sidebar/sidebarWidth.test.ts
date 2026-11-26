import { beforeEach, describe, expect, it, vi } from "vitest";
import { CHAT_MIN, OVERLAY_STRIP, PANEL_MIN } from "../app/panelWidth";
import { SIDE_KEY, SIDE_MAX, SIDE_MIN, clampSide, readSideWidth, saveSideWidth, shownSideWidth, sideMax } from "./sidebarWidth";

describe("sidebar width", () => {
  const disk = new Map<string, string>();
  beforeEach(() => {
    disk.clear();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => disk.get(k) ?? null,
      setItem: (k: string, v: string) => void disk.set(k, v),
      removeItem: (k: string) => void disk.delete(k),
    });
  });

  it("clamps within [SIDE_MIN, SIDE_MAX] while keeping room for main and any open panel", () => {
    expect(sideMax(1280, 0)).toBe(SIDE_MAX);
    expect(clampSide(1000, 1280, 0)).toBe(SIDE_MAX);
    expect(clampSide(50, 1280, 0)).toBe(SIDE_MIN);
    expect(clampSide(312.6, 1280, 0)).toBe(313);
    // wide window with a wide panel open: chat still keeps CHAT_MIN
    expect(sideMax(1150, 500)).toBe(1150 - 500 - CHAT_MIN);
    expect(clampSide(400, 1150, 500)).toBe(290);
    // narrow window (< 1100px): overlay panel keeps at least OVERLAY_STRIP clear of the sidebar
    expect(sideMax(900, 0)).toBe(SIDE_MAX);
    expect(sideMax(900, 460)).toBe(900 - 460 - OVERLAY_STRIP);
    // panel maximised: sidebar may grow up to window - PANEL_MIN (capped at SIDE_MAX)
    expect(sideMax(700, 400, true)).toBe(700 - PANEL_MIN);
    // very narrow window: sidebar keeps its minimum
    expect(sideMax(400, 0)).toBe(SIDE_MIN);
  });

  it("saves the width, forgets it on reset, and ignores junk", () => {
    expect(readSideWidth()).toBeNull();
    expect(saveSideWidth(342.4)).toBe(342);
    expect(readSideWidth()).toBe(342);
    expect(saveSideWidth(null)).toBeNull();
    expect(readSideWidth()).toBeNull();
    for (const bad of ["", "wide", "0", "100", "200", "900", "NaN", "Infinity"]) {
      localStorage.setItem(SIDE_KEY, bad);
      expect(readSideWidth(), bad).toBeNull();
    }
  });

  it("shows a saved width narrower in a small window without forgetting it", () => {
    saveSideWidth(420);
    expect(shownSideWidth(readSideWidth(), 1280, 0)).toBe(420);
    expect(shownSideWidth(readSideWidth(), 1150, 500)).toBe(290);
    expect(readSideWidth()).toBe(420);
    expect(shownSideWidth(null, 1280, 0)).toBeNull();
  });
});
