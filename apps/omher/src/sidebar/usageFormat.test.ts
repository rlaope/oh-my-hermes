import { describe, expect, it } from "vitest";
import type { UsageProvider } from "../lib/protocol";
import { duration, meterLabel, ringLevel, topPercent, windowRow } from "./usageFormat";

const NOW = 1_794_200_000;
const codex: UsageProvider = {
  id: "codex", plan: "pro", state: "near", source_mtime: NOW - 60,
  windows: [
    { label: "5 hours", used_percent: 73, resets_at: NOW + 107 * 60 },
    { label: "Weekly", used_percent: 60, resets_at: NOW + (4 * 24 + 23) * 3600 },
  ],
};
const claude: UsageProvider = { id: "claude", state: "limited", source_mtime: NOW, windows: [{ label: "Weekly", resets_at: NOW + 3600 }] };

describe("usage format", () => {
  it("rings fill to the largest window and change colour at 70 and 90", () => {
    expect(topPercent(codex)).toBe(73);
    expect([ringLevel(0), ringLevel(69.9), ringLevel(70), ringLevel(90), ringLevel(90.5)]).toEqual(["gray", "gray", "amber", "amber", "red"]);
  });

  it("card rows read like the brief: label, %, resets in", () => {
    expect(windowRow(codex, codex.windows[0], NOW)).toEqual(["5 hours", "73%", "resets in 1h 47m"]);
    expect(windowRow(codex, codex.windows[1], NOW)).toEqual(["Weekly", "60%", "resets in 4d 23h"]);
    expect([duration(59), duration(600), duration(7200), duration(86400)]).toEqual(["<1m", "10m", "2h", "1d"]);
  });

  it("never shows a % the source did not give", () => {
    expect(topPercent(claude)).toBeNull();
    const [, pct, note] = windowRow(claude, claude.windows[0], NOW);
    expect(pct).toBe("");
    expect(note).toMatch(/^Limited until /);
    expect(meterLabel(claude)).toBe("Claude Code usage: Limited");
    const connected: UsageProvider = { id: "grok", state: "connected", source_mtime: null, windows: [] };
    expect(topPercent(connected)).toBeNull();
    expect(meterLabel(connected)).toBe("Grok usage: Connected · no usage record");
  });

  it("a stale window says stale, with no number even if one leaked through", () => {
    const stale: UsageProvider = { id: "codex", state: "stale", source_mtime: 1, windows: [{ label: "Weekly", used_percent: 40, resets_at: NOW - 5, stale: true }] };
    expect(topPercent(stale)).toBeNull();
    expect(windowRow(stale, stale.windows[0], NOW)).toEqual(["Weekly", "", "stale"]);
  });
});
