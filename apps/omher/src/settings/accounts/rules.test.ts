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
  modelsInUse,
  noRoomNote,
  pruneSeen,
  resetFirstOn,
  rowSub,
  rowTitle,
  splitGroups,
  switchAt,
  switchCheck,
  switchHeld,
  switchNote,
  usageLines,
  CODEX_SWITCH_EVERY_S,
  SWITCH_AT_DEFAULT,
  SWITCH_AT_STEPS,
  SWITCH_ROOM,
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
    expect(rowTitle(acc("default", "active", { email: "demo@example.com", label: "Personal" }), 0)).toBe("demo@example.com");
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
  it("orders only accounts with a fresh reading once one has: those without are no candidates at all", () => {
    const accounts = limitedFirst(acc("b", "ready"), acc("c", "ready"), withReset("d", "5 hours", 2 * HOUR));
    expect(nextAccount(accounts, {}, "a", on)).toEqual({ from: 0, to: 3 });
  });
  it("is list order when nothing is comparable, and sets no reason", () => {
    const accounts = limitedFirst(acc("b", "ready"), acc("c", "ready"));
    expect(nextAccount(accounts, {}, "a", on)).toEqual({ from: 0, to: 1 });
    // a stale window, a past reset and a window without a time are not comparable
    const stale = acc("b", "ready", { usage: codexUsage([{ label: "5 hours", resets_at: NOW - HOUR, stale: true }]) });
    const none = acc("c", "ready", { usage: codexUsage([{ label: "5 hours", used_percent: 10 }]) });
    expect(nextAccount(limitedFirst(stale, none, withReset("d", "5 hours", HOUR)), {}, "a", on)).toEqual({ from: 0, to: 3 });
    // no one has a fresh reading: as before the threshold, the first ready account
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
    // fill-first at the default threshold, written out on its own: the first ready account with a fresh reading at
    // least SWITCH_ROOM under the threshold once the one in use reaches it; with no fresh reading anywhere else, the
    // first ready one once the one in use is limited
    const base = (accounts: Account[], usage: Record<string, UsageProvider | null | undefined>, activeId?: string | null) => {
      const from = accounts.findIndex((a) => (activeId ? a.id === activeId : a.state === "active"));
      if (from < 0) return null;
      const lim = (a: Account) => a.state === "limited" || usage[a.id]?.state === "limited";
      const pct = (a: Account): number | null => {
        const live = ((usage[a.id] ?? a.usage)?.windows ?? []).filter(
          (w) => !w.stale && typeof w.used_percent === "number" && typeof w.resets_at === "number" && w.resets_at > NOW,
        );
        return live.length ? Math.max(...live.map((w) => w.used_percent as number)) : null;
      };
      const others = accounts.flatMap((a, i) => (i !== from && a.state === "ready" && !isCpa(a) ? [i] : []));
      const fresh = others.filter((i) => pct(accounts[i]) !== null);
      const cur = accounts[from];
      if (fresh.length === 0) {
        if (!lim(cur)) return null;
        const to = others.find((i) => !lim(accounts[i]));
        return to === undefined ? null : { from, to };
      }
      if (!lim(cur) && (pct(cur) ?? -1) < 90) return null;
      const to = fresh.find((i) => !lim(accounts[i]) && (pct(accounts[i]) as number) <= 85);
      return to === undefined ? null : { from, to };
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
      expect(nextAccount(accounts, usage, activeId, { now: NOW })).toEqual(want);
      expect(nextAccount(accounts, usage, activeId, { resetFirst: false, now: NOW, threshold: SWITCH_AT_DEFAULT })).toEqual(want);
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

// A Codex or Claude Code account with one fresh reading: `pct` of its 5-hour window, which resets in an hour.
const at = (id: string, state: Account["state"], pct: number, extra: Partial<Account> = {}): Account =>
  acc(id, state, { usage: codexUsage([{ label: "5 hours", used_percent: pct, resets_at: NOW + HOUR }]), ...extra });

describe("switch threshold and headroom", () => {
  const opts = { now: NOW };
  it("moves at the threshold, not under it, and only to an account at least SWITCH_ROOM points under it", () => {
    expect(SWITCH_AT_DEFAULT).toBe(90);
    expect(SWITCH_ROOM).toBe(5);
    expect(nextAccount([at("a", "active", 89.9), at("b", "ready", 10)], {}, "a", opts)).toBeNull();
    expect(switchCheck([at("a", "active", 90), at("b", "ready", 85)], {}, "a", opts)).toEqual({
      from: 0,
      to: 1,
      at: { percent: 90, resets_at: NOW + HOUR },
    });
    // 86 is under 90 but has too little room: the one after it takes over
    expect(nextAccount([at("a", "active", 92), at("b", "ready", 86), at("c", "ready", 40)], {}, "a", opts)).toEqual({ from: 0, to: 2 });
  });
  it("says there is no room when every other account is too full, with the window it is about", () => {
    expect(switchCheck([at("a", "active", 92), at("b", "ready", 86)], {}, "a", opts)).toEqual({
      from: 0,
      to: null,
      at: { percent: 92, resets_at: NOW + HOUR },
    });
    expect(nextAccount([at("a", "active", 92), at("b", "ready", 86)], {}, "a", opts)).toBeNull();
    // a single login has nowhere to go: nothing to say
    expect(switchCheck([at("a", "active", 99)], {}, "a", opts)).toBeNull();
  });
  it("at 100 waits for the limit, as before the threshold existed", () => {
    const o = { ...opts, threshold: 100 };
    expect(nextAccount([at("a", "active", 99), at("b", "ready", 10)], {}, "a", o)).toBeNull();
    expect(nextAccount([at("a", "active", 100), at("b", "ready", 95)], {}, "a", o)).toEqual({ from: 0, to: 1 });
    expect(nextAccount([at("a", "active", 100), at("b", "ready", 96)], {}, "a", o)).toBeNull();
    expect(nextAccount([acc("a", "limited"), at("b", "ready", 95)], {}, "a", o)).toEqual({ from: 0, to: 1 });
  });
  it("takes only a threshold of the offered steps; anything else is the default", () => {
    expect(SWITCH_AT_STEPS).toEqual([80, 85, 90, 95, 100]);
    expect(nextAccount([at("a", "active", 80), at("b", "ready", 75)], {}, "a", { ...opts, threshold: 80 })).toEqual({ from: 0, to: 1 });
    expect(nextAccount([at("a", "active", 80), at("b", "ready", 75)], {}, "a", { ...opts, threshold: 42 })).toBeNull();
  });
  it("a limited account in use moves even below the threshold by its numbers, and says so as a limit", () => {
    expect(switchCheck([at("a", "limited", 40), at("b", "ready", 10)], {}, "a", opts)).toEqual({ from: 0, to: 1 });
  });
});

describe("only an account with a fresh reading is a candidate", () => {
  const opts = { now: NOW };
  it("skips no record, a stale window, a reset in the past, a window with no reset and one with no percent", () => {
    const stale = acc("s", "ready", { usage: codexUsage([{ label: "5 hours", resets_at: NOW - 60, stale: true }]) });
    const past = acc("p", "ready", { usage: codexUsage([{ label: "5 hours", used_percent: 5, resets_at: NOW - 1 }]) });
    const noReset = acc("n", "ready", { usage: codexUsage([{ label: "5 hours", used_percent: 5 }]) });
    const noPct = acc("q", "ready", { usage: codexUsage([{ label: "5 hours", resets_at: NOW + HOUR }]) });
    const none = acc("x", "ready");
    const list = [at("a", "active", 95), none, stale, past, noReset, noPct, at("ok", "ready", 50)];
    expect(nextAccount(list, {}, "a", opts)).toEqual({ from: 0, to: 6 });
    expect(switchCheck(list.slice(0, 6).concat(at("full", "ready", 99)), {}, "a", opts)).toMatchObject({ from: 0, to: null });
  });
  it("with no other fresh reading anywhere, behaves as before: waits for a real limit, then the first ready one", () => {
    const list = (cur: Account) => [cur, acc("x", "ready"), acc("y", "ready", { usage: codexUsage([{ label: "5 hours", resets_at: NOW - 1, stale: true }]) })];
    expect(switchCheck(list(at("a", "active", 99)), {}, "a", opts)).toBeNull();
    expect(nextAccount(list(acc("a", "limited")), {}, "a", opts)).toEqual({ from: 0, to: 1 });
    // limited, and the others are limited too: no room, said once
    expect(switchCheck([acc("a", "limited", { resets_at: AT_14 }), acc("b", "limited")], {}, "a", opts)).toEqual({ from: 0, to: null, at: { resets_at: AT_14 } });
  });
  it("never a CLIProxyAPI login or a signed-out one, however much room it has", () => {
    const cpa = at("cpa:1", "ready", 0, { source: "cpa" });
    expect(switchCheck([at("a", "active", 95), cpa, at("l", "login", 0)], {}, "a", opts)).toBeNull();
    expect(nextAccount([at("a", "active", 95), cpa, at("l", "login", 0), at("b", "ready", 30)], {}, "a", opts)).toEqual({ from: 0, to: 3 });
  });
  it("reset-first orders the new candidates only", () => {
    const soon = (id: string, pct: number, inS: number) => acc(id, "ready", { usage: codexUsage([{ label: "5 hours", used_percent: pct, resets_at: NOW + inS }]) });
    // c resets soonest but is too full; d is next soonest of those with room
    const list = [at("a", "active", 91), soon("b", 50, 4 * HOUR), soon("c", 88, HOUR / 2), soon("d", 40, 2 * HOUR), acc("e", "ready")];
    expect(nextAccount(list, {}, "a", { ...opts, resetFirst: true })).toEqual({ from: 0, to: 3, soonest: NOW + 2 * HOUR });
    expect(nextAccount(list, {}, "a", opts)).toEqual({ from: 0, to: 1 });
  });
});

describe("a model's own weekly limit counts only while a session of the account uses that model", () => {
  const claude = (id: string, state: Account["state"], wide: number, opus: number): Account =>
    acc(id, state, {
      usage: {
        id: "claude",
        state: "ok",
        source_mtime: NOW - 60,
        windows: [
          { label: "Weekly", used_percent: wide, resets_at: NOW + 50 * HOUR },
          { label: "Weekly (Opus)", used_percent: opus, resets_at: NOW + 20 * HOUR, model: "opus" },
        ],
      },
    });
  it("no model known: the Opus window is left out, so a full Opus week moves nothing", () => {
    expect(switchCheck([claude("a", "active", 40, 100), claude("b", "ready", 10, 0)], {}, "a", { now: NOW })).toBeNull();
    expect(switchCheck([claude("a", "active", 40, 100), claude("b", "ready", 10, 0)], {}, "a", { now: NOW, models: { a: ["claude-sonnet-4-5"] } })).toBeNull();
  });
  it("an Opus session on the account: the Opus window counts, at the threshold and at its limit", () => {
    const models = { a: ["claude-opus-4-5-20251101"] };
    expect(switchCheck([claude("a", "active", 40, 91), claude("b", "ready", 10, 0)], {}, "a", { now: NOW, models })).toEqual({
      from: 0,
      to: 1,
      at: { percent: 91, resets_at: NOW + 20 * HOUR },
    });
    // a refused request on the Opus window (no %): limited for that account's Opus session
    const refused = acc("a", "active", { usage: { id: "claude", state: "ok", source_mtime: NOW, windows: [{ label: "Weekly (Opus)", resets_at: NOW + HOUR, model: "opus", limited: true }] } });
    expect(nextAccount([refused, claude("b", "ready", 10, 0)], {}, "a", { now: NOW, models })).toEqual({ from: 0, to: 1 });
    expect(nextAccount([refused, claude("b", "ready", 10, 0)], {}, "a", { now: NOW })).toBeNull();
  });
  it("a candidate is judged by its own sessions' models: its full Opus week counts only if one of them uses Opus", () => {
    const list = [claude("a", "active", 95, 0), claude("b", "ready", 10, 100)];
    expect(nextAccount(list, {}, "a", { now: NOW })).toEqual({ from: 0, to: 1 });
    expect(nextAccount(list, {}, "a", { now: NOW, models: { b: ["opus"] } })).toBeNull();
  });
});

describe("modelsInUse", () => {
  it("collects the models of the running and starting sessions of one CLI, by account (none = the CLI's own)", () => {
    const list = [
      { agent: "claude", status: "running", model: "claude-opus-4-5" },
      { agent: "claude", status: "starting", account: "work", model: "claude-sonnet-4-5" },
      { agent: "claude", status: "running", account: "work" }, // a terminal: its model is not known
      { agent: "claude", status: "exited", model: "claude-haiku-4-5" },
      { agent: "codex", status: "running", model: "gpt-5.2-codex" },
    ];
    expect(modelsInUse(list, "claude")).toEqual({ default: ["claude-opus-4-5"], work: ["claude-sonnet-4-5"] });
    expect(modelsInUse(list, "codex")).toEqual({ default: ["gpt-5.2-codex"] });
  });
});

describe("Codex: at most one automatic switch every 300 seconds", () => {
  it("holds Codex until 300 s after its last switch, and never holds another CLI", () => {
    expect(CODEX_SWITCH_EVERY_S).toBe(300);
    expect(switchHeld("codex", undefined, NOW)).toBe(false);
    expect(switchHeld("codex", NOW - 299, NOW)).toBe(true);
    expect(switchHeld("codex", NOW - 300, NOW)).toBe(false);
    expect(switchHeld("claude", NOW - 1, NOW)).toBe(false);
  });
});

describe("switchAt (the threshold setting)", () => {
  it("is 90 unless one of the steps was saved for that CLI", () => {
    const store = (v: string | null) => ({ getItem: () => v });
    expect(switchAt("codex", store(null))).toBe(90);
    expect(switchAt("codex", store('{"codex":80}'))).toBe(80);
    expect(switchAt("claude", store('{"codex":80}'))).toBe(90);
    expect(switchAt("codex", store('{"codex":83}'))).toBe(90);
    expect(switchAt("codex", store("not json"))).toBe(90);
  });
});

describe("switch and no-room lines", () => {
  const g = group("codex", [acc("default", "active"), acc("work", "ready", { label: "Work" })]);
  it("names the level when the switch came before the limit", () => {
    expect(switchNote(g, 0, 1, NOW, undefined, { percent: 92.4, resets_at: AT_14 })).toBe(
      "Switched Codex to Work for new sessions (This computer at 92%, resets 14:00)",
    );
    expect(switchNote(g, 0, 1, NOW, AT_21, { percent: 90 })).toBe("Switched Codex to Work for new sessions (This computer at 90%); its limit resets soonest, 21:00");
  });
  it("says no other account has room, with the level or the limit", () => {
    expect(noRoomNote(g, 0, NOW, { percent: 93, resets_at: AT_14 })).toBe(
      "Codex: no other account has room, so new sessions stay on This computer (at 93%, resets 14:00)",
    );
    expect(noRoomNote(g, 0, NOW, {})).toBe("Codex: no other account has room, so new sessions stay on This computer (limit reached)");
  });
});

describe("usageLines: a model's window", () => {
  it("is named for its model, and a refused one says limited without limiting the account", () => {
    const u: UsageProvider = {
      id: "claude",
      state: "ok",
      source_mtime: NOW,
      windows: [
        { label: "Weekly (Opus)", resets_at: AT_14, model: "opus", limited: true },
        { label: "Weekly (Sonnet)", used_percent: 12, resets_at: AT_21, model: "sonnet" },
      ],
    };
    expect(usageLines(u, NOW)).toEqual(["Weekly Opus limit: limited until 14:00", "Weekly Sonnet limit: 12% used · resets 21:00"]);
  });
});
