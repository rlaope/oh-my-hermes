import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Account, AccountGroup } from "../../lib/protocol";

const NOW = 1_800_000_000;
const shown: { tag: string }[] = [];
let notify = true;
let groups: AccountGroup[] = [];
const disk = new Map<string, string>();

vi.mock("../../state/store", () => ({
  getStore: () => ({ actions: { accounts: async () => ({ groups }), setActiveAccount: async () => {}, systemNote: () => {} } }),
  notifyEnabled: () => notify,
  useStore: () => ({ conn: "open" }),
}));
vi.mock("../../lib/notify", () => ({ showNote: async (n: { tag: string }) => void shown.push(n) }));
vi.mock("./native", () => ({ accountHost: () => ({ clis: async () => ({ codex: true }), status: async () => null, version: async () => null }) }));

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
