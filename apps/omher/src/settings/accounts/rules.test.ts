import { describe, expect, it } from "vitest";
import type { Account, AccountGroup } from "../../lib/protocol";
import {
  accountForNewSessions,
  accountName,
  autoSwitchOn,
  mergeRow,
  nextAccount,
  pill,
  planName,
  rowSub,
  rowTitle,
  splitGroups,
  switchNote,
  usageLines,
} from "./rules";

const acc = (id: string, state: Account["state"], extra: Partial<Account> = {}): Account => ({ id, label: "", email: "", state, ...extra });
const NOW = new Date(2026, 10, 9, 12, 0, 0).getTime() / 1000;
const AT_14 = new Date(2026, 10, 9, 14, 0, 0).getTime() / 1000;
const AT_21 = new Date(2026, 10, 9, 21, 0, 0).getTime() / 1000;
const group = (cli: AccountGroup["cli"], accounts: Account[], extra: Partial<AccountGroup> = {}): AccountGroup => ({
  cli,
  installed: true,
  active: "default",
  accounts,
  ...extra,
});

describe("row names", () => {
  it("shows the full email, then the label, then This computer", () => {
    expect(rowTitle(acc("default", "active", { email: "khope@sionic.ai", label: "Personal" }), 0)).toBe("khope@sionic.ai");
    expect(rowTitle(acc("work", "ready", { label: "Work" }), 1)).toBe("Work");
    expect(rowTitle(acc("default", "ready"), 0)).toBe("This computer");
    expect(rowTitle(acc("x", "login"), 2)).toBe("Account 3");
  });
  it("says where the login lives under it", () => {
    expect(rowSub(acc("default", "active", { email: "a@b.c", label: "Personal" }))).toBe("Personal · This computer");
    expect(rowSub(acc("default", "active"))).toBe("");
    expect(rowSub(acc("work", "ready", { label: "Work" }))).toBe("Added in omher");
    expect(rowSub({ ...acc("default", "active"), method: "chatgpt" })).toBe("ChatGPT login");
    expect(rowSub({ ...acc("default", "active", { email: "a@b.c" }), method: "claude.ai" })).toBe("This computer");
  });
  it("outside the page: label, then email, then #n", () => {
    expect(accountName(acc("w", "ready", { label: "Work", email: "a@b.c" }), 0)).toBe("Work");
    expect(accountName(acc("w", "ready", { email: "alice@b.c" }), 0)).toBe("alice@b.c");
    expect(accountName(acc("default", "ready"), 0)).toBe("This computer");
    expect(accountName(acc("w", "ready"), 2)).toBe("#3");
  });
});

describe("planName", () => {
  it("words the CLI's plan and drops login methods", () => {
    expect(planName("max_20x")).toBe("Max 20x");
    expect(planName("pro")).toBe("Pro");
    expect(planName("chatgpt")).toBe("");
    expect(planName(null)).toBe("");
  });
});

describe("usageLines", () => {
  it("reads '5-hour limit: 62% used · resets 21:00' and never shows a % the record did not give", () => {
    const u = { id: "codex" as const, state: "ok" as const, source_mtime: 1, windows: [{ label: "5 hours", used_percent: 62.4, resets_at: AT_21 }, { label: "Weekly", used_percent: 21 }] };
    expect(usageLines(u, NOW)).toEqual(["5-hour limit: 62% used · resets 21:00", "Weekly limit: 21% used"]);
    const c = { id: "claude" as const, state: "limited" as const, source_mtime: 1, windows: [{ label: "Weekly", resets_at: AT_14 }] };
    expect(usageLines(c, NOW)).toEqual(["Weekly limit: limited until 14:00"]);
    expect(usageLines({ ...c, windows: [{ label: "5 hours", stale: true }] }, NOW)).toEqual(["5-hour limit: no recent record"]);
    expect(usageLines(null, NOW)).toEqual([]);
  });
});

describe("mergeRow + pill", () => {
  it("the CLI's own status wins: email and plan from `claude auth status`", () => {
    const r = mergeRow(acc("default", "login"), { logged_in: true, email: "owner@example.com", plan: "max_20x", method: "claude.ai" });
    expect([r.signedIn, r.state, r.email, r.plan]).toEqual([true, "ready", "owner@example.com", "Max 20x"]);
    const out = mergeRow(acc("work", "ready", { email: "old@example.com" }), { logged_in: false, email: null, plan: null, method: "none" });
    expect([out.signedIn, out.state]).toEqual([false, "login"]);
  });
  it("without a status the bridge's file check stands", () => {
    expect(mergeRow(acc("default", "active"), undefined).signedIn).toBe(true);
    expect(mergeRow(acc("x", "login"), null).signedIn).toBe(false);
  });
  it("In use / Limited until / Not signed in / nothing", () => {
    expect(pill(mergeRow(acc("a", "active"), null), true, NOW)).toBe("In use");
    expect(pill(mergeRow(acc("a", "ready"), null), false, NOW)).toBe("");
    expect(pill(mergeRow(acc("a", "limited", { resets_at: AT_14 }), null), true, NOW)).toBe("Limited until 14:00");
    expect(pill(mergeRow(acc("a", "login"), null), false, NOW)).toBe("Not signed in");
  });
});

describe("splitGroups", () => {
  it("hides CLIs not on this computer unless they hold added accounts, and names them", () => {
    const gs = [
      group("claude", [acc("default", "active")]),
      group("codex", [acc("default", "login")], { installed: false }),
      group("pi", [acc("default", "login"), acc("work", "ready")], { installed: false }),
      group("grok", [acc("default", "login")], { installed: false }),
    ];
    const { shown, missing } = splitGroups(gs, null);
    expect(shown.map((g) => g.cli)).toEqual(["claude", "pi"]);
    expect(missing).toEqual(["Codex", "Grok"]);
    expect(splitGroups(gs, { codex: true }).shown.map((g) => g.cli)).toEqual(["claude", "codex", "pi"]);
  });
});

describe("accountForNewSessions", () => {
  it("is the active row of that CLI", () => {
    const gs = [group("claude", [acc("default", "ready"), acc("work", "active", { email: "w@example.com" })], { active: "work" })];
    expect(accountForNewSessions(gs, "claude")?.email).toBe("w@example.com");
    expect(accountForNewSessions(gs, "codex")).toBeNull();
    expect(accountForNewSessions(null, "claude")).toBeNull();
  });
});

describe("nextAccount (fill-first)", () => {
  it("does nothing while the active account is fine", () => {
    expect(nextAccount([acc("1", "active"), acc("2", "ready")])).toBeNull();
  });
  it("moves a limited active account to the first ready one in list order", () => {
    expect(nextAccount([acc("1", "ready"), acc("2", "limited"), acc("3", "login"), acc("4", "ready")], {}, "2")).toEqual({ from: 1, to: 0 });
    expect(nextAccount([acc("1", "limited"), acc("2", "login"), acc("3", "ready")], {}, "1")).toEqual({ from: 0, to: 2 });
  });
  it("takes a usage record as a limit too, and skips limited / not signed in", () => {
    const usage = { "1": { id: "claude" as const, state: "limited" as const, windows: [], source_mtime: 1 } };
    expect(nextAccount([acc("1", "active"), acc("2", "ready")], usage)).toEqual({ from: 0, to: 1 });
    expect(nextAccount([acc("1", "limited"), acc("2", "limited"), acc("3", "login")], {}, "1")).toBeNull();
    expect(nextAccount([acc("1", "ready"), acc("2", "ready")], {}, "nope")).toBeNull();
  });
});

describe("switchNote", () => {
  it("is one quiet line with names, never a token", () => {
    const g = group("claude", [acc("default", "limited", { resets_at: AT_14 }), acc("two", "ready", { email: "two@example.com" })]);
    expect(switchNote(g, 0, 1, NOW)).toBe("Switched Claude Code to two@example.com for new sessions (limit on This computer, resets 14:00)");
  });
});

describe("autoSwitchOn", () => {
  it("is on unless that CLI was turned off", () => {
    const store = (v: string | null) => ({ getItem: () => v });
    expect(autoSwitchOn("claude", store(null))).toBe(true);
    expect(autoSwitchOn("claude", store('{"claude":false}'))).toBe(false);
    expect(autoSwitchOn("codex", store('{"claude":false}'))).toBe(true);
    expect(autoSwitchOn("codex", store("not json"))).toBe(true);
  });
});
