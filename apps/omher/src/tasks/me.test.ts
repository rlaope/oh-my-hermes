import { afterEach, describe, expect, it } from "vitest";
import { accountsOnHost, attention, accountState, chipsFor, groupRows, pickRepoAccount, reviewBadge, shownAccounts, sortMe, type AccountLists, type MeRow } from "./me";
import { ACCOUNT_COLORS, chooseAccount, cycleAccountColor, getTasks, removeAccount, resetTasks, setMeAccount, setRepoAccount, setScope } from "./state";
import { accountId, accountIdOk, type MeItem } from "./types";

const base: MeItem = { repo: "o/r", number: 1, title: "t", url: "", pr: true, draft: false, state: "open", author: "a", labels: [], created: 100, updated: 1000, asked: false, ci: "", review: "", conflict: false, requested: 0 };
const it_ = (n: number, p: Partial<MeItem> = {}): MeItem => ({ ...base, number: n, updated: 1000 + n, ...p });
const row = (n: number, p: Partial<MeRow> = {}): MeRow => ({ ...it_(n), account: "octo@github.com", section: "authored", ...p });

describe("the attention order", () => {
  it("puts CI failed, changes requested, conflict, then review requests oldest first, then the rest newest first", () => {
    const items = [
      it_(1),
      it_(2, { asked: true, created: 500 }),
      it_(3, { asked: true, requested: 50 }),
      it_(4, { conflict: true }),
      it_(5, { review: "changes" }),
      it_(6, { ci: "failed" }),
      it_(7, { ci: "failed", review: "changes" }),
      it_(8),
    ];
    expect(sortMe(items).map((i) => i.number)).toEqual([7, 6, 5, 4, 3, 2, 8, 1]);
    expect(attention(it_(9, { ci: "failed", conflict: true }))).toBe(0);
    expect(attention(it_(9, { ci: "passed", review: "approved" }))).toBe(4);
  });

  it("groups by section in a fixed order, or by repository once per item", () => {
    const rows = [row(1, { section: "review", asked: true }), row(2, { section: "authored", ci: "failed", repo: "z/z" }), row(1, { section: "mentions" })];
    const bySection = groupRows(rows, "section");
    expect(bySection.map((g) => [g.key, g.rows.length])).toEqual([["review", 1], ["authored", 1], ["assigned", 0], ["mentions", 1]]);
    const byRepo = groupRows(rows, "repo");
    // z/z holds the CI failure: it comes first; o/r#1 shows once
    expect(byRepo.map((g) => [g.key, g.rows.map((r) => r.number)])).toEqual([["z/z", [2]], ["o/r", [1]]]);
  });
});

describe("chips", () => {
  it("shows draft, CI, review, conflict and waiting in that order", () => {
    expect(chipsFor(it_(1, { draft: true, ci: "pending", review: "approved", conflict: true, asked: true })).map((c) => c.kind)).toEqual(["draft", "ciPending", "approved", "conflict", "waiting"]);
    expect(chipsFor(it_(1, { ci: "failed", review: "changes" })).map((c) => [c.kind, c.tone])).toEqual([["ciFailed", "fail"], ["changes", "fail"]]);
    expect(chipsFor(it_(1, { ci: "passed" }))).toEqual([{ kind: "ciPassed", tone: "ok" }]);
    expect(chipsFor(it_(1))).toEqual([]);
  });
});

describe("accounts", () => {
  afterEach(() => resetTasks());

  it("checks account ids as the shell does", () => {
    for (const ok of ["octo@github.com", "a-b_c@ghe.example.co.kr"]) expect(accountIdOk(ok), ok).toBe(true);
    for (const bad of ["", "octo", "@github.com", "-x@github.com", "octo@--hostname", "octo@github.com:8080", "a@b@github.com", "octo@localhost", "octo@GITHUB.COM", "o cto@github.com"])
      expect(accountIdOk(bad), bad).toBe(false);
  });

  it("chooses, colours and removes accounts; the chips follow", () => {
    expect(chooseAccount({ host: "github.com", login: "octo" })).toBe(true);
    expect(chooseAccount({ host: "github.com", login: "octo" })).toBe(false);
    expect(chooseAccount({ host: "github.com", login: "--x" })).toBe(false);
    chooseAccount({ host: "github.com", login: "octo-work" });
    expect(getTasks().accounts.map((a) => a.color)).toEqual([ACCOUNT_COLORS[0], ACCOUNT_COLORS[1]]);
    cycleAccountColor("octo@github.com");
    expect(getTasks().accounts[0].color).toBe(ACCOUNT_COLORS[1]);
    setMeAccount("octo-work@github.com");
    setRepoAccount("octo-work@github.com");
    setMeAccount("nobody@github.com");
    expect(getTasks().meAccount).toBe("octo-work@github.com");
    expect(shownAccounts(getTasks().accounts, getTasks().meAccount)).toEqual(["octo-work@github.com"]);
    removeAccount("octo-work@github.com");
    expect(getTasks().meAccount).toBe("all");
    expect(getTasks().repoAccount).toBe(null);
    expect(shownAccounts(getTasks().accounts, "all")).toEqual(["octo@github.com"]);
    setScope("me");
    expect(getTasks().scope).toBe("me");
    // only host, login and colour are kept (no token, no scope)
    expect(Object.keys(getTasks().accounts[0]).sort()).toEqual(["color", "host", "login"]);
  });

  it("sums the review badge over the shown accounts, a failed one adding nothing", () => {
    const lists = (n: number, fail = false): AccountLists => ({ sections: fail ? {} : { review: { items: Array.from({ length: n }, (_, i) => it_(i)), more: false, page: 0 } }, fail: fail ? { kind: "auth", line: "x" } : null, rate: false, loading: false, at: 0 });
    const all = { "a@github.com": lists(3), "b@github.com": lists(2), "c@github.com": lists(0, true) };
    expect(reviewBadge(all, ["a@github.com", "b@github.com", "c@github.com"])).toBe(5);
    expect(reviewBadge(all, ["b@github.com"])).toBe(2);
    expect(reviewBadge(all, [])).toBe(0);
  });

  it("picks the account for a repository: the person's pick, else the owner's login, else gh's own", () => {
    const accounts = [
      { host: "github.com", login: "octo", color: ACCOUNT_COLORS[0] },
      { host: "github.com", login: "Work-Org", color: ACCOUNT_COLORS[1] },
    ];
    expect(pickRepoAccount(accounts, null, "work-org")).toBe("Work-Org@github.com");
    expect(pickRepoAccount(accounts, "octo@github.com", "work-org")).toBe("octo@github.com");
    expect(pickRepoAccount(accounts, "gone@github.com", "someone")).toBe(null);
    expect(pickRepoAccount([], null, "octo")).toBe(null);
    // a GitHub Enterprise account never reads a github.com repository, picked or by its login
    const ghe = [...accounts, { host: "ghe.example.com", login: "octo-corp", color: ACCOUNT_COLORS[2] }];
    expect(pickRepoAccount(ghe, "octo-corp@ghe.example.com", "octo-corp")).toBe(null);
    expect(pickRepoAccount(ghe, "octo-corp@ghe.example.com", "work-org")).toBe("Work-Org@github.com");
    expect(accountsOnHost(ghe).map((a) => a.login)).toEqual(["octo", "Work-Org"]);
  });

  it("says when a chosen account must sign in again", () => {
    const a = { host: "github.com", login: "octo", color: ACCOUNT_COLORS[0] };
    expect(accountState(a, null)).toBe("unknown");
    expect(accountState(a, { installed: true, accounts: [{ host: "github.com", login: "octo", active: true, state: "success", scopes: [] }] })).toBe("ok");
    expect(accountState(a, { installed: true, accounts: [{ host: "github.com", login: "octo", active: true, state: "error", scopes: [] }] })).toBe("relogin");
    expect(accountState(a, { installed: true, accounts: [] })).toBe("relogin");
    expect(accountId(a)).toBe("octo@github.com");
  });
});
