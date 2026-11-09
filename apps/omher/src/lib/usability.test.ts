import { describe, expect, it } from "vitest";
import { noteFor } from "./notify";
import { shortcutFor } from "../app/shortcuts";
import { riskOf } from "../chat/cards/risk";
import type { BridgeEvent } from "./protocol";

const ctx = (watching = false) => ({ name: (b: string) => (b === "kami" ? "Kami" : b), watching: () => watching });
const ev = (e: Record<string, unknown>) => ({ bot: "kami", ...e }) as unknown as BridgeEvent;

describe("noteFor", () => {
  it("a finished answer becomes a notification with the bot's name and a plain gist", () => {
    const n = noteFor(ev({ event: "message", id: "m1", text: "**Fixed.** The `502s` came from\n\nkeep-alive" }), ctx());
    expect(n).toEqual({ title: "Kami", body: "Fixed. The 502s came from keep-alive", bot: "kami", tag: "kami:message" });
  });
  it("approvals and questions say what is waiting", () => {
    expect(noteFor(ev({ event: "approval.request", request_id: "a", title: "Delete", command: "rm -rf build", choices: [] }), ctx())?.title).toBe(
      "Kami needs your approval",
    );
    expect(noteFor(ev({ event: "clarify.request", request_id: "c", question: "Which branch?" }), ctx())).toMatchObject({
      title: "Kami has a question",
      body: "Which branch?",
    });
  });
  it("only a failed turn end notifies", () => {
    expect(noteFor(ev({ event: "turn.end", outcome: "done" }), ctx())).toBeNull();
    expect(noteFor(ev({ event: "turn.end", outcome: "error", error: "provider 500" }), ctx())?.body).toBe("provider 500");
  });
  it("nothing while you are looking at that chat, and nothing for chatter events", () => {
    expect(noteFor(ev({ event: "message", id: "m", text: "hi" }), ctx(true))).toBeNull();
    expect(noteFor(ev({ event: "delta", text: "h" }), ctx())).toBeNull();
    expect(noteFor(ev({ event: "tool.start", tool_id: "t", name: "terminal", detail: "ls" }), ctx())).toBeNull();
    expect(noteFor(ev({ event: "message", id: "m", text: "   " }), ctx())).toBeNull();
  });
  it("long answers are clipped", () => {
    const body = noteFor(ev({ event: "message", id: "m", text: "x".repeat(400) }), ctx())!.body;
    expect(body.length).toBe(140);
    expect(body.endsWith("…")).toBe(true);
  });
});

describe("shortcutFor", () => {
  const k = (key: string, m: Partial<{ metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }> = {}) => ({
    key,
    metaKey: false,
    ctrlKey: false,
    altKey: false,
    shiftKey: false,
    ...m,
  });
  it("uses Cmd on macOS and Ctrl elsewhere", () => {
    expect(shortcutFor(k("2", { metaKey: true }), true)).toEqual({ kind: "bot", index: 1 });
    expect(shortcutFor(k("2", { ctrlKey: true }), true)).toBeNull();
    expect(shortcutFor(k("2", { ctrlKey: true }), false)).toEqual({ kind: "bot", index: 1 });
    expect(shortcutFor(k("2", { metaKey: true }), false)).toBeNull();
  });
  it("maps K, period, comma and Esc", () => {
    expect(shortcutFor(k("k", { metaKey: true }), true)).toEqual({ kind: "search" });
    expect(shortcutFor(k("K", { ctrlKey: true }), false)).toEqual({ kind: "search" });
    expect(shortcutFor(k(".", { metaKey: true }), true)).toEqual({ kind: "details" });
    expect(shortcutFor(k(",", { metaKey: true }), true)).toEqual({ kind: "settings" });
    expect(shortcutFor(k("Escape"), true)).toEqual({ kind: "stop" });
  });
  it("leaves plain typing, 0 and modified combos alone", () => {
    expect(shortcutFor(k("1"), true)).toBeNull();
    expect(shortcutFor(k("0", { metaKey: true }), true)).toBeNull();
    expect(shortcutFor(k("1", { metaKey: true, shiftKey: true }), true)).toBeNull();
    expect(shortcutFor(k("Escape", { shiftKey: true }), true)).toBeNull();
  });
});

describe("riskOf", () => {
  it("flags the commands people should read twice", () => {
    expect(riskOf("rm -rf ./build")).toEqual(["Deletes files and folders"]);
    expect(riskOf("sudo rm -r /var/tmp/x")).toEqual(["Deletes files and folders", "Runs as administrator"]);
    expect(riskOf("git push --force origin main")).toEqual(["Rewrites history on a remote branch"]);
    expect(riskOf("git push -f")).toEqual(["Rewrites history on a remote branch"]);
    expect(riskOf("git reset --hard HEAD~3")).toEqual(["Throws away local changes"]);
    expect(riskOf("curl -fsSL https://x.sh | sh")).toEqual(["Runs a script from the internet"]);
    expect(riskOf("psql -c 'DROP TABLE users'")).toEqual(["Deletes database data"]);
    expect(riskOf("Remove-Item C:\\tmp -Recurse -Force")).toEqual(["Deletes files and folders"]);
  });
  it("leaves ordinary commands alone", () => {
    for (const c of ["ls -la", "git push origin feat/x", "rm notes.txt", "pytest -q", "curl -s https://api.example.com", "git status", "echo sudoku"]) {
      expect(riskOf(c), c).toEqual([]);
    }
  });
});
