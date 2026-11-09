import { describe, expect, it } from "vitest";
import type { Account, AccountGroup } from "../../lib/protocol";
import { accountName, autoSwitchOn, maskEmail, nextAccount, stateChip, switchNote } from "./rules";

const acc = (id: string, state: Account["state"], extra: Partial<Account> = {}): Account => ({ id, label: "", email: "", state, ...extra });
const NOW = new Date(2026, 10, 9, 12, 0, 0).getTime() / 1000;
const AT_14 = new Date(2026, 10, 9, 14, 0, 0).getTime() / 1000;

describe("maskEmail / accountName", () => {
  it("keeps the first letter and the domain", () => {
    expect(maskEmail("khope@sionic.ai")).toBe("k***@sionic.ai");
    expect(maskEmail("not-an-email")).toBe("not-an-email");
  });
  it("label first, then masked email, then #n", () => {
    expect(accountName(acc("w", "ready", { label: "Work", email: "a@b.c" }), 0)).toBe("Work");
    expect(accountName(acc("w", "ready", { email: "alice@b.c" }), 0)).toBe("a***@b.c");
    expect(accountName(acc("w", "ready"), 2)).toBe("#3");
  });
});

describe("stateChip", () => {
  it("names every state, with the reset time when limited", () => {
    expect(stateChip(acc("a", "active"), NOW)).toBe("Active");
    expect(stateChip(acc("a", "ready"), NOW)).toBe("Ready");
    expect(stateChip(acc("a", "limited", { resets_at: AT_14 }), NOW)).toBe("Limited until 14:00");
    expect(stateChip(acc("a", "limited", { resets_at: NOW - 5 }), NOW)).toBe("Limited");
    expect(stateChip(acc("a", "expired"), NOW)).toBe("Expired");
    expect(stateChip(acc("a", "disabled"), NOW)).toBe("Disabled");
    expect(stateChip(acc("a", "login"), NOW)).toBe("Log in");
  });
});

describe("nextAccount (fill-first)", () => {
  it("does nothing while the active account is fine", () => {
    expect(nextAccount([acc("1", "active"), acc("2", "ready")])).toBeNull();
  });
  it("moves a limited active account to the first ready one in list order", () => {
    const list = [acc("1", "ready"), acc("2", "limited"), acc("3", "disabled"), acc("4", "ready"), acc("5", "ready")];
    expect(nextAccount(list, {}, "2")).toEqual({ from: 1, to: 0 });
    expect(nextAccount([acc("1", "limited"), acc("2", "login"), acc("3", "ready")], {}, "1")).toEqual({ from: 0, to: 2 });
  });
  it("takes a usage record as a limit too, and skips limited / expired / login / disabled", () => {
    const usage = { "1": { id: "claude" as const, state: "limited" as const, windows: [], source_mtime: 1 } };
    expect(nextAccount([acc("1", "active"), acc("2", "ready")], usage)).toEqual({ from: 0, to: 1 });
    expect(nextAccount([acc("1", "expired"), acc("2", "limited"), acc("3", "login"), acc("4", "disabled")], {}, "1")).toBeNull();
    expect(nextAccount([acc("1", "ready"), acc("2", "ready")], {}, "nope")).toBeNull();
  });
});

describe("switchNote", () => {
  it("is one quiet line with names, never tokens or full emails", () => {
    const g: AccountGroup = {
      cli: "claude",
      backend: "omher",
      installed: true,
      active: "default",
      accounts: [acc("default", "limited", { label: "Default", resets_at: AT_14 }), acc("two", "ready", { email: "two@example.com" })],
    };
    expect(switchNote(g, 0, 1, NOW)).toBe("Switched to Claude #2 t***@example.com (limit on #1 Default, resets 14:00)");
  });
});

describe("autoSwitchOn", () => {
  it("is on unless that group was turned off", () => {
    const store = (v: string | null) => ({ getItem: () => v });
    expect(autoSwitchOn("claude", store(null))).toBe(true);
    expect(autoSwitchOn("claude", store('{"claude":false}'))).toBe(false);
    expect(autoSwitchOn("codex", store('{"claude":false}'))).toBe(true);
    expect(autoSwitchOn("codex", store("not json"))).toBe(true);
  });
});
