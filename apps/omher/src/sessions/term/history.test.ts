// Terminal history across restarts: how kept text is drawn back (dim, under a divider), what is kept of a buffer
// (its newest lines, no modes, no alternate screen), the bottom panel's saved tabs, and the Settings switch.
import { Terminal } from "@xterm/xterm";
import { SerializeAddon } from "@xterm/addon-serialize";
import { afterEach, describe, expect, it } from "vitest";
import { dimmed, divider, HISTORY_LINES, restoredText, serializeTail, type HistoryHost } from "./history";
import { parseTermSettings, resetTermSettings, TERM_DEFAULTS, writeTermSettings } from "./settings";
import { parseSavedTabs } from "../../terminal/state";

const write = (t: Terminal, d: string) => new Promise<void>((r) => t.write(d, r));
const lines = (t: Terminal) => {
  const b = t.buffer.active;
  const out: string[] = [];
  for (let y = 0; y < b.length; y++) out.push(b.getLine(y)?.translateToString(true) ?? "");
  while (out.length && !out[out.length - 1]) out.pop();
  return out;
};

const host = (got: { text: string; at: number } | null): HistoryHost & { calls: string[] } => {
  const calls: string[] = [];
  return {
    calls,
    historySave: async () => void calls.push("save"),
    historyRead: async (k) => (calls.push(`read ${k}`), got),
    historyRemove: async () => void calls.push("remove"),
    historyPrune: async () => void calls.push("prune"),
    historyClear: async () => void calls.push("clear"),
  };
};

afterEach(() => resetTermSettings());

describe("terminal history", () => {
  it("is on by default and a stored off is kept", () => {
    expect(TERM_DEFAULTS.keepHistory).toBe(true);
    expect(parseTermSettings("{}").keepHistory).toBe(true);
    expect(parseTermSettings(JSON.stringify({ keepHistory: false })).keepHistory).toBe(false);
    expect(parseTermSettings(JSON.stringify({ keepHistory: "no" })).keepHistory).toBe(true);
  });

  it("draws kept text faint, even after its own colour changes and resets", async () => {
    const d = dimmed("\x1b[32mgreen\x1b[0m plain\r\n");
    expect(d.startsWith("\x1b[0m\x1b[2m")).toBe(true);
    expect(d).toContain("\x1b[32m\x1b[2mgreen\x1b[0m\x1b[2m plain");
    const t = new Terminal({ cols: 40, rows: 5, allowProposedApi: true });
    await write(t, d + divider(1_700_000_000) + "new");
    const b = t.buffer.active;
    const cell = (y: number, x: number) => b.getLine(y)!.getCell(x)!;
    expect(cell(0, 0).isDim()).toBeTruthy(); // "green"
    expect(cell(0, 6).isDim()).toBeTruthy(); // "plain", after the reset
    expect(lines(t)[2]).toMatch(/^--- restored .+ ---$/);
    expect(cell(2, 0).isDim()).toBeTruthy();
    expect(cell(3, 0).isDim()).toBeFalsy(); // the program's own output is as it prints it
    t.dispose();
  });

  it("keeps the newest lines of the main screen, without modes or a full-screen program's screen", async () => {
    const t = new Terminal({ cols: 30, rows: 10, scrollback: 5000, allowProposedApi: true });
    t.loadAddon(new SerializeAddon());
    let out = "";
    for (let i = 0; i < HISTORY_LINES + 300; i++) out += `row ${i}\r\n`;
    await write(t, out + "\x1b[?2004h\x1b[?1049h\x1b[Hfull screen app");
    const kept = serializeTail(t, SerializeAddon);
    expect(kept).not.toContain("full screen app");
    expect(kept).not.toContain("\x1b[?2004h");
    expect(kept).not.toContain("\x1b[?1049h");
    const back = new Terminal({ cols: 30, rows: 10, scrollback: 5000, allowProposedApi: true });
    await write(back, kept);
    const got = lines(back);
    expect(got.length).toBeLessThanOrEqual(HISTORY_LINES);
    expect(got[got.length - 1]).toBe(`row ${HISTORY_LINES + 299}`);
    expect(got).not.toContain("row 0");
    t.dispose();
    back.dispose();
  });

  it("gives nothing to write back when nothing was kept, or history is off", async () => {
    expect(await restoredText(host(null), "s1")).toBe("");
    expect(await restoredText(host({ text: "  \r\n", at: 1 }), "s1")).toBe("");
    const h = host({ text: "kept", at: 1 });
    expect(await restoredText(h, "s1")).toContain("kept");
    expect(h.calls).toEqual(["read s1"]);
    writeTermSettings({ keepHistory: false });
    const off = host({ text: "kept", at: 1 });
    expect(await restoredText(off, "s1")).toBe("");
    expect(off.calls).toEqual([]);
  });

  it("each save carries when history was last turned on, so the shell can refuse one from before a clear", async () => {
    const { flushHistory, trackHistory, watchHistorySetting } = await import("./history");
    const sent: number[] = [];
    const h: HistoryHost = { ...host(null), historySave: async (_k, _t, since) => void sent.push(since) };
    watchHistorySetting(h);
    const t = new Terminal({ cols: 20, rows: 3, allowProposedApi: true });
    await write(t, "x");
    const tr = trackHistory(h, "s1", () => t);
    // the serializer loads on first use
    await new Promise((r) => setTimeout(r, 50));
    tr.touch();
    flushHistory();
    expect(sent).toHaveLength(1);
    writeTermSettings({ keepHistory: false });
    await new Promise((r) => setTimeout(r, 5));
    writeTermSettings({ keepHistory: true });
    tr.touch();
    flushHistory();
    expect(sent).toHaveLength(2);
    expect(sent[1]).toBeGreaterThan(sent[0]);
    tr.stop();
    t.dispose();
  });
});

describe("the bottom panel's saved tabs", () => {
  it("come back with their folders, checked, as restored one-pane tabs", () => {
    const raw = JSON.stringify({ tabs: [{ key: 3, cwd: "/home/you/code/api" }, { key: 5, cwd: null }, { key: 3, cwd: "/dup" }, { key: "x" }, { key: 7, cwd: "relative/path" }], active: 5 });
    expect(parseSavedTabs(raw)).toEqual({
      tabs: [
        { key: 3, want: "/home/you/code/api", cwd: null, layout: { pane: 3 }, panes: [{ id: 3, want: "/home/you/code/api", cwd: null, restored: true }], focus: 3 },
        { key: 5, want: null, cwd: null, layout: { pane: 5 }, panes: [{ id: 5, want: null, cwd: null, restored: true }], focus: 5 },
        { key: 7, want: null, cwd: null, layout: { pane: 7 }, panes: [{ id: 7, want: null, cwd: null, restored: true }], focus: 7 },
      ],
      active: 5,
    });
    for (const bad of [null, "", "{", "[]", "42", JSON.stringify({ tabs: "x" })]) expect(parseSavedTabs(bad)).toEqual({ tabs: [], active: null });
    expect(parseSavedTabs(JSON.stringify({ tabs: [{ key: 2, cwd: "/a" }], active: 9 })).active).toBe(2);
  });
});
