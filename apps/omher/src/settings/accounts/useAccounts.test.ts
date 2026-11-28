import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Account, AccountGroup, UsageWindow } from "../../lib/protocol";

const NOW = 1_800_000_000;
const shown: { tag: string }[] = [];
let notify = true;
let groups: AccountGroup[] = [];
const disk = new Map<string, string>();
const switched: string[] = [];
const notes: string[] = [];
let sessions: { agent: string; status: string; account?: string; model?: string }[] = [];

vi.mock("../../state/store", () => ({
  getStore: () => ({
    actions: {
      accounts: async () => ({ groups }),
      setActiveAccount: async (cli: string, id: string) => void switched.push(`${cli}:${id}`),
      systemNote: (text: string) => void notes.push(text),
    },
  }),
  notifyEnabled: () => notify,
  useStore: () => ({ conn: "open" }),
}));
vi.mock("../../lib/notify", () => ({ showNote: async (n: { tag: string }) => void shown.push(n) }));
vi.mock("./native", () => ({ accountHost: () => ({ clis: async () => ({ codex: true }), status: async () => null, version: async () => null }) }));
vi.mock("../../sessions/sessions", () => ({ getSessions: () => ({ getState: () => ({ list: sessions }) }) }));

const acc = (id: string): Account => ({
  id,
  label: "",
  email: "",
  state: "ready",
  usage: { id: "codex", state: "ok", source_mtime: NOW, windows: [{ label: "5 hours", used_percent: 20, resets_at: NOW + 1800 }] },
});
const setAccounts = (n: number) => {
  groups = [{ cli: "codex", installed: true, active: "none", accounts: Array.from({ length: n }, (_, i) => acc(`id${i}`)) }];
};

beforeEach(() => {
  shown.length = 0;
  switched.length = 0;
  notes.length = 0;
  sessions = [];
  notify = true;
  disk.clear();
  vi.useFakeTimers();
  vi.setSystemTime(NOW * 1000);
  vi.stubGlobal("localStorage", { getItem: (k: string) => disk.get(k) ?? null, setItem: (k: string, v: string) => void disk.set(k, v) });
});

describe("lapse notice across reloads", () => {
  it("tells each of 101 live pairs once, not again on the next reload", async () => {
    const { reloadAccounts } = await import("./useAccounts");
    setAccounts(101);
    await reloadAccounts();
    expect(shown).toHaveLength(101);
    await reloadAccounts();
    expect(shown).toHaveLength(101);
  });

  it("records nothing while Notify me is off, so turning it on before the reset still tells once", async () => {
    const { reloadAccounts } = await import("./useAccounts");
    setAccounts(1);
    notify = false;
    await reloadAccounts();
    expect(shown).toHaveLength(0);
    notify = true;
    await reloadAccounts();
    expect(shown).toHaveLength(1);
    await reloadAccounts();
    expect(shown).toHaveLength(1);
  });
});

// The in-use account and two others, each with one fresh reading (a window that resets in 3 hours, so no lapse notice).
const used = (id: string, pct: number, windows: UsageWindow[] = []): Account => ({
  id,
  label: id,
  email: "",
  state: "ready",
  usage: { id: "codex", state: "ok", source_mtime: NOW, windows: [{ label: "5 hours", used_percent: pct, resets_at: NOW + 3 * 3600 }, ...windows] },
});
const setGroup = (cli: AccountGroup["cli"], active: string, accounts: Account[]) => {
  groups = [{ cli, installed: true, active, accounts: accounts.map((a) => (a.id === active ? { ...a, state: "active" } : a)) }];
};

describe("auto-switch at the threshold", () => {
  it("Codex: one automatic switch at most every 300 seconds, by the clock", async () => {
    const { reloadAccounts } = await import("./useAccounts");
    setGroup("codex", "a", [used("a", 95), used("b", 10), used("c", 10)]);
    await reloadAccounts();
    expect(switched).toEqual(["codex:b"]);
    expect(notes).toHaveLength(1);
    expect(notes[0]).toMatch(/^Switched Codex to b for new sessions \(a at 95%, resets .+\)$/);
    // b fills up at once: held for 300 s after the last switch
    setGroup("codex", "b", [used("a", 10), used("b", 95), used("c", 10)]);
    vi.setSystemTime((NOW + 299) * 1000);
    await reloadAccounts();
    expect(switched).toEqual(["codex:b"]);
    vi.setSystemTime((NOW + 300) * 1000);
    await reloadAccounts();
    expect(switched).toEqual(["codex:b", "codex:a"]);
  });

  it("no account with room: said once per episode, not on every poll nor when the fullest window changes, and again for the next episode", async () => {
    const { reloadAccounts } = await import("./useAccounts");
    setGroup("claude", "a", [used("a", 93), used("b", 88)]);
    await reloadAccounts();
    await reloadAccounts();
    expect(switched).toEqual([]);
    expect(notes).toHaveLength(1);
    expect(notes[0]).toMatch(/^Claude Code: no other account has room, so new sessions stay on a \(at 93%, resets .+\)$/);
    // the weekly window passes the 5-hour one as the fullest: the same episode, nothing more said
    setGroup("claude", "a", [used("a", 93, [{ label: "Weekly", used_percent: 96, resets_at: NOW + 90 * 3600 }]), used("b", 88)]);
    await reloadAccounts();
    expect(notes).toHaveLength(1);
    // the window resets (nothing to move), then fills again: a new episode, told again
    setGroup("claude", "a", [used("a", 5), used("b", 88)]);
    await reloadAccounts();
    const next = used("a", 94);
    next.usage!.windows[0].resets_at = NOW + 8 * 3600;
    setGroup("claude", "a", [next, used("b", 88)]);
    await reloadAccounts();
    expect(notes).toHaveLength(2);
  });

  it("Codex: the 300-second hold outlives a reload (saved on this computer), and a saved time in the future holds nothing", async () => {
    vi.resetModules();
    let { reloadAccounts } = await import("./useAccounts");
    setGroup("codex", "a", [used("a", 95), used("b", 10), used("c", 10)]);
    await reloadAccounts();
    expect(switched).toEqual(["codex:b"]);
    // a reload of the app: module memory is gone, the store is kept
    vi.resetModules();
    ({ reloadAccounts } = await import("./useAccounts"));
    setGroup("codex", "b", [used("a", 10), used("b", 95), used("c", 10)]);
    vi.setSystemTime((NOW + 100) * 1000);
    await reloadAccounts();
    expect(switched).toEqual(["codex:b"]);
    vi.setSystemTime((NOW + 300) * 1000);
    await reloadAccounts();
    expect(switched).toEqual(["codex:b", "codex:a"]);
    // a clock set back: the saved time is ahead of now and is ignored
    disk.set("omher.lastswitch", JSON.stringify({ codex: NOW + 9999 }));
    vi.resetModules();
    ({ reloadAccounts } = await import("./useAccounts"));
    setGroup("codex", "a", [used("a", 95), used("b", 10), used("c", 10)]);
    await reloadAccounts();
    expect(switched).toEqual(["codex:b", "codex:a", "codex:b"]);
  });

  it("Claude Code: a full Opus week moves new sessions only while an Opus session runs on that account", async () => {
    const { reloadAccounts } = await import("./useAccounts");
    const opus: UsageWindow = { label: "Weekly (Opus)", used_percent: 100, resets_at: NOW + 40 * 3600, model: "opus" };
    setGroup("claude", "default", [used("default", 30, [opus]), used("work", 10)]);
    sessions = [{ agent: "claude", status: "running", account: "work", model: "claude-opus-4-5" }];
    await reloadAccounts();
    expect(switched).toEqual([]);
    sessions = [{ agent: "claude", status: "running", model: "claude-opus-4-5" }];
    await reloadAccounts();
    expect(switched).toEqual(["claude:work"]);
  });
});
