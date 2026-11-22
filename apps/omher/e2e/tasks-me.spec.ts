// Tasks › 나 (src/tasks/MeView.tsx) and Settings › Accounts › GitHub, against the mock task host (window.__omherTasks.gh):
// 1. with no GitHub account chosen, the "나" scope shows one "GitHub 연결" button that opens Settings › Accounts;
// 2. Settings › Accounts › GitHub lists gh's two accounts with "추가"; adding both keeps them; "Sign in to another
//    account" opens a terminal tab running gh's own sign-in, and gh's accounts are asked again when it ends;
// 3. the scope toggle switches between "이 저장소" and "나"; the list holds both accounts' rows, sorted by what needs
//    action (CI failed, changes requested, conflict, then review requests oldest first);
// 4. the account chips filter to one account; group by repository;
// 5. keys: j / k move, Enter opens the drawer (read as that row's account), o opens the browser;
// 6. one account failing ("sign in again") leaves the other's rows; GitHub's rate limit shows "try again soon";
// 7. the sidebar's Tasks row counts the review requests of the shown accounts.
// Shots (OMHER_SHOTS=<dir>): tasks-me-dark, tasks-me-light, accounts-github.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const A = "octo@github.com";
const B = "octo-work@github.com";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "m1") res(msg);
    };
    ws.send(JSON.stringify({ id: "m1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

const now = () => Math.floor(Date.now() / 1000);
const D = 86_400;
type Row = Record<string, unknown>;
function item(repo: string, number: number, p: Row = {}): Row {
  return {
    repo,
    number,
    title: `Item ${repo}#${number}`,
    url: `https://github.com/${repo}/pull/${number}`,
    pr: true,
    draft: false,
    state: "open",
    author: "octo",
    labels: [],
    created: now() - 10 * D,
    updated: now() - number * 60,
    asked: false,
    ci: "",
    review: "",
    conflict: false,
    requested: 0,
    ...p,
  };
}

function ghData(opts: { failB?: "auth" | "rate" } = {}) {
  const accounts = [
    { host: "github.com", login: "octo", active: true, state: "success", scopes: ["repo"] },
    { host: "github.com", login: "octo-work", active: false, state: "success", scopes: ["repo"] },
  ];
  const me = {
    [`${A}:review`]: [
      item("other/lib", 31, { asked: true, requested: now() - 2 * D }),
      item("other/lib", 32, { asked: true, requested: now() - 5 * D }),
    ],
    [`${A}:authored`]: [
      item("octo/app", 11, { ci: "passed", review: "approved" }),
      item("octo/app", 12, { ci: "failed" }),
      item("octo/app", 13, { conflict: true, draft: true }),
      item("octo/app", 14, { review: "changes", ci: "pending" }),
    ],
    [`${A}:assigned`]: [item("octo/app", 21, { pr: false, url: "https://github.com/octo/app/issues/21" })],
    [`${A}:mentions`]: [item("acme/site", 41, { pr: false, url: "https://github.com/acme/site/issues/41" })],
    [`${B}:review`]: [item("work/api", 51, { asked: true, requested: now() - 1 * D })],
    [`${B}:authored`]: [item("work/api", 61, { ci: "failed" })],
    [`${B}:assigned`]: [],
    [`${B}:mentions`]: [],
  };
  const fail = opts.failB === "auth" ? { [B]: { kind: "auth", line: "HTTP 401: Bad credentials" } } : opts.failB === "rate" ? { [B]: { kind: "rate", line: "API rate limit exceeded" } } : {};
  return { installed: true, accounts, me, fail };
}

async function setup(page: Page, opts: { chosen?: boolean; scope?: "me" | "repo"; failB?: "auth" | "rate"; theme?: "dark" | "light" } = {}) {
  const tasks = {
    status: { github: { installed: true, signed_in: true }, gitlab: { installed: false, signed_in: false } },
    items: {},
    gh: ghData(opts),
  };
  const saved = {
    source: "github",
    scope: opts.scope ?? "me",
    accounts: opts.chosen === false ? [] : [
      { host: "github.com", login: "octo", color: "#4c8dff" },
      { host: "github.com", login: "octo-work", color: "#f2994a" },
    ],
  };
  await page.addInitScript(
    ([theme, d, s]) => {
      localStorage.setItem("omher.theme", theme as string);
      if (!sessionStorage.getItem("__tkme")) {
        localStorage.setItem("omher.tasks", JSON.stringify(s));
        sessionStorage.setItem("__tkme", "1");
      }
      const w = window as unknown as { __omherTasks: unknown; __opened: unknown[] };
      w.__omherTasks = d;
      w.__opened = [];
      window.open = ((...a: unknown[]) => {
        w.__opened.push(a);
        return null;
      }) as typeof window.open;
    },
    [opts.theme ?? "dark", tasks, saved] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
}

const taskCalls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherTaskCalls?: any[] }).__omherTaskCalls ?? []));

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled", caret: "initial" });
}

async function openMe(page: Page) {
  await page.getByTestId("tasks-open").click();
  await expect(page.getByTestId("tasks-page")).toBeVisible();
  await page.getByTestId("tasks-scope-me").click();
  await expect(page.getByTestId("me-view")).toBeVisible();
}

/** The row test ids of a section, top to bottom. */
const order = (page: Page, sec: string) => page.getByTestId(`me-sec-${sec}`).locator(".tk-me-row").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("with no GitHub account chosen, 나 shows one Connect GitHub button that opens Settings › Accounts", async ({ page }) => {
  await setup(page, { chosen: false });
  await page.getByTestId("tasks-open").click();
  await page.getByTestId("tasks-scope-me").click();
  await expect(page.getByTestId("me-connect")).toBeVisible();
  await expect(page.getByTestId("me-connect").getByRole("button")).toHaveCount(1);
  await expect(page.getByTestId("tasks-badge")).toHaveCount(0);
  await page.getByTestId("me-connect-btn").click();
  await expect(page.getByTestId("accounts-page")).toBeVisible();
  await expect(page.getByTestId("accounts-github")).toBeVisible();
});

test("Settings › Accounts › GitHub adds gh's accounts and runs gh's own sign-in in a terminal tab", async ({ page }) => {
  await setup(page, { chosen: false });
  await page.getByTestId("tasks-open").click();
  await page.getByTestId("tasks-scope-me").click();
  await page.getByTestId("me-connect-btn").click();
  const rows = page.getByTestId("gh-account-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0).getByTestId("gh-active")).toBeVisible();
  await shot(page, "accounts-github");
  await page.getByTestId("gh-add-octo").click();
  await page.getByTestId("gh-add-octo-work").click();
  await expect(page.getByTestId("gh-remove-octo")).toBeVisible();
  await expect(page.getByTestId("gh-remove-octo-work")).toBeVisible();
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("omher.tasks") ?? "{}").accounts);
  expect(saved).toEqual([
    { host: "github.com", login: "octo", color: "#4c8dff" },
    { host: "github.com", login: "octo-work", color: "#f2994a" },
  ]);
  // another account: a terminal tab runs gh's own sign-in (the shell builds the argv; only the host goes)
  const before = (await taskCalls(page)).filter((c) => c.op === "ghAccounts" && c.fresh).length;
  await page.getByTestId("gh-login-another").click();
  await page.getByTestId("gh-login-host").fill("ghe.example.com");
  await page.getByTestId("gh-login-start").click();
  await expect(page.getByTestId("termpanel")).toBeVisible();
  await expect.poll(() => page.evaluate(() => ((window as any).__omherShellCalls ?? []).filter((c: any) => c.op === "gh-login"))).toEqual([expect.objectContaining({ op: "gh-login", host: "ghe.example.com" })]);
  await expect(page.locator('[data-testid="termpanel-terminal"]:not([hidden]) .xterm-rows')).toContainText("Where do you use GitHub?");
  await page.locator('[data-testid="termpanel-terminal"]:not([hidden]) .xterm-helper-textarea').focus();
  await page.keyboard.press("Enter");
  // the program ended: gh's accounts are asked again
  await expect.poll(async () => (await taskCalls(page)).filter((c) => c.op === "ghAccounts" && c.fresh).length).toBeGreaterThan(before);
  // nothing typed into it by omher: the only write is the person's Enter
  const writes = await page.evaluate(() => ((window as any).__omherShellCalls ?? []).filter((c: any) => c.op === "write"));
  expect(writes.map((w: any) => w.data).join("")).toBe("\r");
});

test("the scope toggle, both accounts' rows sorted by attention, chips and the sidebar badge", async ({ page }) => {
  await setup(page, { scope: "repo" });
  await page.getByTestId("tasks-open").click();
  await expect(page.getByTestId("tasks-scope-repo")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("tasks-src-github")).toBeVisible();
  await page.getByTestId("tasks-scope-me").click();
  await expect(page.getByTestId("me-view")).toBeVisible();
  await expect(page.getByTestId("tasks-src-github")).toHaveCount(0);
  // review: the longest wait first, across both accounts
  await expect.poll(() => order(page, "review")).toEqual(["me-row-other/lib#32", "me-row-other/lib#31", "me-row-work/api#51"]);
  // authored: CI failed (both accounts), changes requested, conflict, then the rest
  await expect.poll(() => order(page, "authored")).toEqual(["me-row-octo/app#12", "me-row-work/api#61", "me-row-octo/app#14", "me-row-octo/app#13", "me-row-octo/app#11"]);
  const r13 = page.getByTestId("me-row-octo/app#13");
  await expect(r13.locator('[data-chip="draft"]')).toBeVisible();
  await expect(r13.locator('[data-chip="conflict"]')).toBeVisible();
  await expect(page.getByTestId("me-row-octo/app#12").locator('[data-chip="ciFailed"]')).toBeVisible();
  await expect(page.getByTestId("me-row-octo/app#11").locator('[data-chip="approved"]')).toBeVisible();
  await expect(page.getByTestId("me-row-other/lib#32").locator('[data-chip="waiting"]')).toBeVisible();
  // the mentions section is closed until opened
  await expect(page.getByTestId("me-sec-mentions").locator(".tk-me-row")).toHaveCount(0);
  await page.getByTestId("me-sec-mentions-toggle").click();
  await expect(page.getByTestId("me-row-acme/site#41")).toBeVisible();
  // the sidebar counts the review requests of both accounts
  await expect(page.getByTestId("tasks-badge")).toHaveText("3");
  await shot(page, "tasks-me-dark");
  // every call carried only an account id, a section and a page number
  for (const c of (await taskCalls(page)).filter((c) => c.op === "me")) {
    expect(Object.keys(c).sort()).toEqual(["account", "fresh", "op", "page", "section"]);
    expect([A, B]).toContain(c.account);
  }
});

test("the account chips filter to one account, the badge follows, and the list groups by repository", async ({ page }) => {
  await setup(page);
  await openMe(page);
  await expect(page.getByTestId("me-row-work/api#61")).toBeVisible();
  await page.getByTestId("me-acct-octo-work").click();
  await expect(page.getByTestId("me-acct-octo-work")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("me-row-octo/app#12")).toHaveCount(0);
  await expect(page.locator(".tk-me-row")).toHaveCount(2);
  await expect(page.getByTestId("tasks-badge")).toHaveText("1");
  await page.getByTestId("me-acct-all").click();
  await expect(page.getByTestId("tasks-badge")).toHaveText("3");
  await page.getByTestId("me-group-repo").click();
  // the repository holding a CI failure comes first; each repository is one group
  const groups = await page.locator(".tk-me-sec").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(groups.slice(0, 2)).toEqual(["me-sec-octo/app", "me-sec-work/api"]);
  expect(groups).toContain("me-sec-other/lib");
  expect(groups).toContain("me-sec-acme/site");
});

test("keys: j / k move, Enter opens the drawer as that row's account, o opens the browser", async ({ page }) => {
  await setup(page);
  await openMe(page);
  const first = page.getByTestId("me-row-other/lib#32");
  await expect(first).toBeVisible();
  await first.focus();
  await page.keyboard.press("j");
  await expect(page.getByTestId("me-row-other/lib#31")).toBeFocused();
  await page.keyboard.press("j");
  await expect(page.getByTestId("me-row-work/api#51")).toBeFocused();
  await page.keyboard.press("k");
  await expect(page.getByTestId("me-row-other/lib#31")).toBeFocused();
  await page.keyboard.press("o");
  await expect.poll(() => page.evaluate(() => (window as any).__opened.map((a: unknown[]) => a[0]))).toEqual(["https://github.com/other/lib/pull/31"]);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("tasks-drawer")).toBeVisible();
  await expect(page.getByTestId("tasks-drawer-title")).toHaveText("Item other/lib#31");
  const views = (await taskCalls(page)).filter((c) => c.op === "view");
  expect(views.at(-1)).toEqual({ op: "view", source: "github", repo: "other/lib", kind: "prs", number: 31, account: A });
  // read-only: the drawer's actions are Start in thread, Open terminal here and Open in browser
  await expect(page.getByTestId("tasks-start")).toBeVisible();
  await expect(page.getByTestId("tasks-browser")).toBeVisible();
});

test("one account that must sign in again leaves the other's rows", async ({ page }) => {
  await setup(page, { failB: "auth" });
  await openMe(page);
  await expect(page.getByTestId("me-relogin-octo-work")).toBeVisible();
  await expect(page.getByTestId("me-acct-octo-work")).toHaveAttribute("data-state", "relogin");
  await expect(page.getByTestId("me-row-octo/app#12")).toBeVisible();
  await expect(page.getByTestId("me-row-work/api#61")).toHaveCount(0);
  await expect(page.getByTestId("tasks-badge")).toHaveText("2");
});

test("GitHub's rate limit says try again soon instead of failing", async ({ page }) => {
  await setup(page, { failB: "rate", theme: "light" });
  await openMe(page);
  await expect(page.getByTestId("me-rate")).toBeVisible();
  await expect(page.getByTestId("me-row-octo/app#12")).toBeVisible();
  await expect(page.getByTestId("me-relogin-octo-work")).toHaveCount(0);
  await expect(page.locator(".tk-err")).toHaveCount(0);
  await shot(page, "tasks-me-light");
  // ⟳ reads again, past the minute's answer
  await page.getByTestId("me-refresh").click();
  await expect.poll(async () => (await taskCalls(page)).filter((c) => c.op === "me" && c.fresh).length).toBeGreaterThan(0);
});
