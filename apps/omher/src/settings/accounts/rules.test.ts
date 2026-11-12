import { describe, expect, it } from "vitest";
import type { Account, AccountGroup, UsageProvider } from "../../lib/protocol";
import {
  accountForNewSessions,
  accountName,
  autoSwitchOn,
  isCpa,
  lapseNotices,
  mergeRow,
  nextAccount,
  pill,
  planName,
  pruneSeen,
  resetFirstOn,
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
    // the CLI's own login with a name but no email is still "This computer"; the name goes under it
    expect(rowTitle(acc("default", "ready", { label: "Personal" }), 0)).toBe("This computer");
  });
  it("says where the login lives under it", () => {
    expect(rowSub(acc("default", "active", { email: "a@b.c", label: "Personal" }))).toBe("Personal · This computer");
    expect(rowSub(acc("default", "active"))).toBe("");
    expect(rowSub(acc("work", "ready", { label: "Work" }))).toBe("Added in omher");
    expect(rowSub({ ...acc("default", "active"), method: "chatgpt" })).toBe("ChatGPT login");
    expect(rowSub({ ...acc("default", "active", { email: "a@b.c" }), method: "claude.ai" })).toBe("This computer");
  });
  it("reads source · plan, the same for every CLI", () => {
    expect(rowSub({ ...acc("default", "active", { email: "a@b.c" }), plan: "Max 20x" })).toBe("This computer · Max 20x");
    expect(rowSub({ ...acc("work", "ready", { email: "w@b.c" }), plan: "Pro" })).toBe("Added in omher · Pro");
    expect(rowSub({ ...acc("default", "active"), method: "chatgpt", plan: "Plus" })).toBe("ChatGPT login · Plus");
    expect(rowSub({ ...acc("default", "active", { label: "Personal" }), plan: "" })).toBe("Personal");
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
  it("In use only when the CLI has two or more logins to pick from", () => {
    expect(pill(mergeRow(acc("a", "active"), null), true, NOW, 1)).toBe("");
    expect(pill(mergeRow(acc("a", "active"), null), true, NOW, 2)).toBe("In use");
    expect(pill(mergeRow(acc("a", "login"), null), false, NOW, 1)).toBe("Not signed in");
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

describe("CLIProxyAPI logins", () => {
  const cpa = acc("cpa:2", "ready", { email: "ana@example.com", source: "cpa" });
  it("are titled by the email in the file name and say where they live; a shared login says it is also there", () => {
    expect(rowTitle(cpa, 1)).toBe("ana@example.com");
    expect(rowTitle(acc("cpa:3", "ready", { source: "cpa" }), 2)).toBe("CLIProxyAPI login 3");
    expect(rowSub({ ...cpa, plan: "" })).toBe("CLIProxyAPI");
    expect(rowSub({ ...acc("default", "active", { email: "o@example.com", in_cpa: true }), plan: "Max 20x" })).toBe(
      "This computer · also in CLIProxyAPI · Max 20x",
    );
    expect(isCpa(cpa)).toBe(true);
    expect(isCpa(acc("work", "ready"))).toBe(false);
  });
  it("are never what auto-switch moves to", () => {
    const accounts = [acc("default", "limited"), cpa, acc("work", "ready")];
    expect(nextAccount(accounts, {}, "default")).toEqual({ from: 0, to: 2 });
    expect(nextAccount([acc("default", "limited"), cpa], {}, "default")).toBeNull();
  });
});

const codexUsage = (windows: { label: string; used_percent?: number; resets_at?: number; stale?: boolean }[]): UsageProvider => ({
  id: "codex",
  state: "ok",
  source_mtime: NOW - 60,
  windows,
});
const HOUR = 3600;

describe("nextAccount reset-first", () => {
  const limitedFirst = (...rest: Account[]) => [acc("a", "limited"), ...rest];
  const withReset = (id: string, label: string, inS: number) => acc(id, "ready", { usage: codexUsage([{ label, used_percent: 60, resets_at: NOW + inS }]) });
  const on = { resetFirst: true, now: NOW };

  it("takes the candidate whose window resets soonest, and says when", () => {
    const accounts = limitedFirst(withReset("b", "5 hours", 4 * HOUR), withReset("c", "5 hours", 1 * HOUR));
    expect(nextAccount(accounts, {}, "a", on)).toEqual({ from: 0, to: 2, soonest: NOW + HOUR });
    expect(nextAccount(accounts, {}, "a")).toEqual({ from: 0, to: 1 });
  });
  it("compares the shortest window every candidate reports, not a weekly against a 5-hour one", () => {
    const b = acc("b", "ready", { usage: codexUsage([{ label: "5 hours", resets_at: NOW + 3 * HOUR }, { label: "Weekly", resets_at: NOW + 1 * HOUR }]) });
    const c = acc("c", "ready", { usage: codexUsage([{ label: "5 hours", resets_at: NOW + 2 * HOUR }, { label: "Weekly", resets_at: NOW + 90 * HOUR }]) });
    expect(nextAccount(limitedFirst(b, c), {}, "a", on)).toEqual({ from: 0, to: 2, soonest: NOW + 2 * HOUR });
  });
  it("puts a candidate with no known reset after those that have one, in list order", () => {
    const accounts = limitedFirst(acc("b", "ready"), acc("c", "ready"), withReset("d", "5 hours", 2 * HOUR));
    expect(nextAccount(accounts, {}, "a", on)).toEqual({ from: 0, to: 3, soonest: NOW + 2 * HOUR });
  });
  it("is list order when nothing is comparable, and sets no reason", () => {
    const accounts = limitedFirst(acc("b", "ready"), acc("c", "ready"));
    expect(nextAccount(accounts, {}, "a", on)).toEqual({ from: 0, to: 1 });
    // a stale window, a past reset and a window without a time are not comparable
    const stale = acc("b", "ready", { usage: codexUsage([{ label: "5 hours", resets_at: NOW - HOUR, stale: true }]) });
    const none = acc("c", "ready", { usage: codexUsage([{ label: "5 hours", used_percent: 10 }]) });
    expect(nextAccount(limitedFirst(stale, none, withReset("d", "5 hours", HOUR)), {}, "a", on)).toEqual({ from: 0, to: 3, soonest: NOW + HOUR });
    expect(nextAccount(limitedFirst(stale, none), {}, "a", on)).toEqual({ from: 0, to: 1 });
  });
  it("sets no reason when the soonest one is also the first in list order", () => {
    const accounts = limitedFirst(withReset("b", "5 hours", HOUR), withReset("c", "5 hours", 3 * HOUR));
    expect(nextAccount(accounts, {}, "a", on)).toEqual({ from: 0, to: 1 });
  });
  it("never moves off an account that is not limited, and still skips limited, signed-out and CLIProxyAPI ones", () => {
    const fine = [acc("a", "active"), withReset("b", "5 hours", HOUR), withReset("c", "5 hours", 2 * HOUR)];
    expect(nextAccount(fine, {}, "a", on)).toBeNull();
    const cpa = acc("cpa:2", "ready", { source: "cpa", usage: codexUsage([{ label: "5 hours", resets_at: NOW + 60 }]) });
    const skipped = limitedFirst(acc("b", "limited", { usage: codexUsage([{ label: "5 hours", resets_at: NOW + 60 }]) }), acc("c", "login"), cpa, withReset("d", "5 hours", 2 * HOUR));
    expect(nextAccount(skipped, {}, "a", on)).toEqual({ from: 0, to: 4 });
    expect(nextAccount([acc("a", "limited"), acc("b", "login")], {}, "a", on)).toBeNull();
  });
  it("with the setting off returns exactly what fill-first returns, for generated account lists", () => {
    let seed = 20261112;
    const rnd = () => {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    };
    const pick = <T,>(xs: T[]): T => xs[Math.floor(rnd() * xs.length)];
    // the base nextAccount body, as it was before reset-first existed
    const base = (accounts: Account[], usage: Record<string, UsageProvider | null | undefined>, activeId?: string | null) => {
      const from = accounts.findIndex((a) => (activeId ? a.id === activeId : a.state === "active"));
      if (from < 0) return null;
      const lim = (a: Account) => a.state === "limited" || usage[a.id]?.state === "limited";
      if (!lim(accounts[from])) return null;
      const to = accounts.findIndex((a, i) => i !== from && a.state === "ready" && !isCpa(a) && !lim(a));
      return to < 0 ? null : { from, to };
    };
    let moved = 0;
    for (let n = 0; n < 500; n++) {
      const size = 1 + Math.floor(rnd() * 6);
      const accounts: Account[] = Array.from({ length: size }, (_, i) => {
        const windows = rnd() < 0.7 ? [{ label: pick(["5 hours", "Weekly", "2d"]), used_percent: rnd() < 0.8 ? Math.floor(rnd() * 100) : undefined, resets_at: NOW + Math.floor((rnd() - 0.2) * 100 * HOUR), stale: rnd() < 0.1 }] : [];
        return acc(`id${i}`, pick(["active", "ready", "ready", "limited", "login"] as Account["state"][]), {
          source: rnd() < 0.1 ? "cpa" : undefined,
          usage: windows.length ? codexUsage(windows) : null,
        });
      });
      const usage: Record<string, UsageProvider | null | undefined> = {};
      for (const a of accounts) if (rnd() < 0.15) usage[a.id] = { id: "claude", state: "limited", windows: [], source_mtime: 1 };
      const activeId = rnd() < 0.8 ? pick(accounts).id : undefined;
      const want = base(accounts, usage, activeId);
      expect(nextAccount(accounts, usage, activeId)).toEqual(want);
      expect(nextAccount(accounts, usage, activeId, { resetFirst: false, now: NOW })).toEqual(want);
      if (want) moved++;
    }
    expect(moved).toBeGreaterThan(50); // the generated lists do exercise the switch
  });
});

describe("resetFirstOn", () => {
  it("is off unless that CLI was turned on", () => {
    const store = (v: string | null) => ({ getItem: () => v });
    expect(resetFirstOn("codex", store(null))).toBe(false);
    expect(resetFirstOn("codex", store('{"codex":true}'))).toBe(true);
    expect(resetFirstOn("claude", store('{"codex":true}'))).toBe(false);
    expect(resetFirstOn("codex", store("not json"))).toBe(false);
  });
});

describe("switchNote with reset-first", () => {
  it("says why when the choice differed from list order", () => {
    const g = group("codex", [acc("default", "limited", { resets_at: AT_14 }), acc("one", "ready", { label: "One" }), acc("two", "ready", { label: "Two" })]);
    expect(switchNote(g, 0, 2, NOW, AT_21)).toBe("Switched Codex to Two for new sessions (limit on This computer, resets 14:00); its limit resets soonest, 21:00");
    expect(switchNote(g, 0, 1, NOW)).toBe("Switched Codex to One for new sessions (limit on This computer, resets 14:00)");
  });
});

describe("lapseNotices (unused quota about to lapse)", () => {
  const w = (extra: Partial<{ used_percent: number; resets_at: number; stale: boolean }>) => codexUsage([{ label: "5 hours", ...extra }]);
  const ids = (accounts: Account[], seen: string[] = []) => lapseNotices("codex", accounts, NOW, new Set(seen)).map((n) => n.key);

  it("fires for a window with a percentage and a reset inside the hour, under half used", () => {
    const a = acc("default", "active", { usage: w({ used_percent: 30, resets_at: NOW + 20 * 60 }) });
    expect(lapseNotices("codex", [a], NOW, new Set())).toEqual([{ key: `codex:default:${NOW + 20 * 60}`, index: 0, percent: 30, resets_at: NOW + 20 * 60 }]);
  });
  it("does not fire at 50% or more, past an hour, stale, already reset, or without a percentage or a time", () => {
    expect(ids([acc("a", "ready", { usage: w({ used_percent: 50, resets_at: NOW + 600 }) })])).toEqual([]);
    expect(ids([acc("a", "ready", { usage: w({ used_percent: 10, resets_at: NOW + HOUR + 1 }) })])).toEqual([]);
    expect(ids([acc("a", "ready", { usage: w({ used_percent: 10, resets_at: NOW + HOUR }) })])).toEqual([`codex:a:${NOW + HOUR}`]);
    expect(ids([acc("a", "ready", { usage: w({ used_percent: 10, resets_at: NOW + 600, stale: true }) })])).toEqual([]);
    expect(ids([acc("a", "ready", { usage: w({ used_percent: 10, resets_at: NOW - 5 }) })])).toEqual([]);
    expect(ids([acc("a", "ready", { usage: w({ resets_at: NOW + 600 }) })])).toEqual([]); // Claude Code: no percentage
    expect(ids([acc("a", "ready", { usage: w({ used_percent: 10 }) })])).toEqual([]);
    expect(ids([acc("a", "ready")])).toEqual([]);
  });
  it("is once per account and reset time: a pair already told is not told again, a new reset time is", () => {
    const a = acc("a", "ready", { usage: w({ used_percent: 10, resets_at: NOW + 600 }) });
    expect(ids([a], [`codex:a:${NOW + 600}`])).toEqual([]);
    expect(ids([a], [`codex:a:${NOW + 1}`])).toEqual([`codex:a:${NOW + 600}`]);
  });
  it("gives one notice per account (its soonest window), and none for signed-out or CLIProxyAPI logins", () => {
    const both = codexUsage([
      { label: "5 hours", used_percent: 10, resets_at: NOW + 30 * 60 },
      { label: "Weekly", used_percent: 5, resets_at: NOW + 10 * 60 },
    ]);
    expect(ids([acc("a", "ready", { usage: both })])).toEqual([`codex:a:${NOW + 10 * 60}`]);
    const usage = w({ used_percent: 10, resets_at: NOW + 600 });
    expect(ids([acc("a", "login", { usage }), acc("cpa:2", "ready", { source: "cpa", usage })])).toEqual([]);
  });
});

describe("pruneSeen (told pairs kept until their reset passes)", () => {
  it("keeps every key whose reset is still ahead, however many, and drops the ones that have passed", () => {
    const live = Array.from({ length: 150 }, (_, i) => `codex:id${i}:${NOW + 600}`);
    const gone = [`codex:old:${NOW - 1}`, `codex:older:${NOW}`];
    expect(pruneSeen([...gone, ...live], NOW)).toEqual(live);
  });
});
