// The terminal-agent dialog detector over screens recorded from Claude Code 2.1.332 and Codex 0.171 (paths changed
// to /work/demo): a live dialog is an ask with its title and options; the screen after answering, a dialog pushed
// up into history, a shell printing the same words and a half-drawn frame are not. Plus the two-read debounce.
import { readFileSync } from "node:fs";
import { Terminal } from "@xterm/xterm";
import { describe, expect, it } from "vitest";
import { createAskDebounce, screenAsk, ASK_CONFIRM_MS, type ScreenAsk } from "./screenAsk";

const fixture = (name: string) => readFileSync(new URL(`./fixtures/${name}`, import.meta.url));

/** The visible screen after `bytes`, as the app reads it (sessions.ts readLine). */
async function screen(bytes: Uint8Array | string, rows = 30, cols = 100): Promise<string[]> {
  const t = new Terminal({ cols, rows, allowProposedApi: true });
  await new Promise<void>((r) => t.write(bytes, r));
  const b = t.buffer.active;
  const out: string[] = [];
  for (let y = 0; y < t.rows; y++) out.push(b.getLine(b.baseY + y)?.translateToString(true) ?? "");
  t.dispose();
  return out;
}

describe("screenAsk", () => {
  it("reads Claude Code's Bash permission dialog", async () => {
    const a = screenAsk(await screen(fixture("claude-bash-dialog.bin")), "claude");
    expect(a).toMatchObject({ kind: "approve", title: "Bash command: touch probe.txt" });
    expect(a!.options).toEqual(["Yes", "Yes, and always allow access to /work/demo from this project", "Yes, and switch to auto mode", "No"]);
  });

  it("reads Codex's command approval", async () => {
    const a = screenAsk(await screen(fixture("codex-exec-dialog.bin")), "codex");
    expect(a).toMatchObject({ kind: "approve", title: "$ touch probe.txt" });
    expect(a!.options).toEqual(["Yes, proceed", "Yes, and don't ask again for commands that start with `touch probe.txt`", "No, and tell Codex what to do differently"]);
  });

  it("is gone once the dialog is answered or cancelled", async () => {
    expect(screenAsk(await screen(fixture("claude-bash-answered.bin")), "claude")).toBeNull();
    expect(screenAsk(await screen(fixture("codex-exec-cancelled.bin")), "codex")).toBeNull();
  });

  it("never counts for a program that is not Claude Code or Codex", async () => {
    const lines = await screen(fixture("claude-bash-dialog.bin"));
    expect(screenAsk(lines, "shell")).toBeNull();
    expect(screenAsk(lines, null)).toBeNull();
    // a shell printing a dialog's words (cat of a log)
    const cat = "$ cat dialog.txt\r\n Do you want to proceed?\r\n ❯ 1. Yes\r\n   2. No\r\n\r\n Esc to cancel\r\n$ ";
    expect(screenAsk(await screen(cat, 10, 60), "shell")).toBeNull();
  });

  it("a dialog scrolled up into history is not live", async () => {
    const lines = await screen(fixture("claude-bash-dialog.bin"));
    // the same screen with output under the dialog: its options are no longer at the bottom
    const pushed = [...lines.filter((l) => l.trim()), "⏺ Bash(touch probe.txt)", "  ⎿  (No content)", "⏺ Done.", "", "❯ ", "  ? for shortcuts"];
    expect(screenAsk(pushed, "claude")).toBeNull();
    // and drawn by a terminal: the dialog bytes, then 40 lines of output scroll it into the scrollback
    const more = Array.from({ length: 40 }, (_, i) => `line ${i}`).join("\r\n");
    expect(screenAsk(await screen(Buffer.concat([fixture("claude-bash-dialog.bin"), Buffer.from(`\x1b[30;1H\r\n${more}\r\n`)])), "claude")).toBeNull();
  });

  it("a half-drawn frame is not a dialog", async () => {
    const lines = await screen(fixture("claude-bash-dialog.bin"));
    const at = lines.findIndex((l) => l.includes("4. No"));
    // cut mid-frame: options without the key hints under them, or only the first options
    expect(screenAsk(lines.slice(0, at + 1), "claude")).toBeNull();
    expect(screenAsk(lines.slice(0, at - 1), "claude")).toBeNull();
    // no option marked as selected yet
    expect(screenAsk(lines.map((l) => l.replace("❯ 1.", "  1.")), "claude")).toBeNull();
  });

  it("names an edit dialog by its file and a question menu by its question", () => {
    const edit = ["─".repeat(40), " Edit file", " notes.md", " 1 + hello", " Do you want to make this edit to notes.md?", " ❯ 1. Yes", "   2. Yes, allow all edits during this session (shift+tab)", "   3. No", "", " Esc to cancel · Tab to amend"];
    expect(screenAsk(edit, "claude")).toMatchObject({ kind: "approve", title: "Edit notes.md", options: ["Yes", "Yes, allow all edits during this session (shift+tab)", "No"] });
    const menu = ["─".repeat(40), " Which database should the app use?", " ❯ 1. Postgres", "   2. SQLite", "   3. Type something.", "", " Enter to select · ↑/↓ to navigate · Esc to cancel"];
    expect(screenAsk(menu, "claude")).toMatchObject({ kind: "question", title: "Which database should the app use?", options: ["Postgres", "SQLite", "Type something."] });
  });
});

describe("createAskDebounce", () => {
  const ask = (title: string): ScreenAsk => ({ kind: "approve", title, options: ["Yes", "No"], key: title });

  it("counts a dialog only after two reads at least 300 ms apart agree", () => {
    const d = createAskDebounce();
    expect(d.read(ask("a"), 1000)).toEqual({ live: null, confirmIn: ASK_CONFIRM_MS });
    expect(d.read(ask("a"), 1100)).toEqual({ live: null, confirmIn: 200 });
    const r = d.read(ask("a"), 1300);
    expect(r.live?.title).toBe("a");
    expect(r.fresh).toBe(true);
    // still showing: live, not fresh again
    expect(d.read(ask("a"), 2000)).toEqual({ live: ask("a") });
  });

  it("a different frame in between starts over", () => {
    const d = createAskDebounce();
    d.read(ask("a"), 0);
    d.read(ask("b"), 400);
    expect(d.read(ask("b"), 500).live).toBeNull();
    expect(d.read(ask("b"), 700).live?.title).toBe("b");
  });

  it("leaves on the first read without it", () => {
    const d = createAskDebounce();
    d.read(ask("a"), 0);
    d.read(ask("a"), 300);
    expect(d.read(null, 310)).toEqual({ live: null });
    // and a new dialog needs its two reads again
    expect(d.read(ask("a"), 320).live).toBeNull();
  });
});
