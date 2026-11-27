// Tasks › GitHub, the dashboard (src/tasks/DashView.tsx), against the mock task host (window.__omherTasks.gh.dash):
// 1. with a github.com account chosen, the sidebar's GitHub row opens the dashboard in one click; with none, the row is
//    not there and the scope shows one Connect GitHub button;
// 2. one screen, three columns side by side (repositories, pull requests, Actions above Releases), each scrolling
//    inside itself, the page itself never scrolling;
// 3. a pinned repository filters the other two columns; "모든 repo" shows them all; a dot shows the default branch CI;
// 4. the centre has only the tabs 전체 and 내 리뷰 요청, "N Open", CI ✓ / ✗ / ● beside the title, labels as pills in
//    their own colour, and opens the read-only drawer; ↗ opens the pull request in the browser;
// 5. runs show their state, workflow, branch and duration; releases their tag, Latest and the commits since;
// 6. pin from the box or a folder's suggestion, unpin, kept on this computer; ⟳ reads again (fresh); a rate limit
//    says "try again soon"; every call sends only an account id and a repository.
// Shots (OMHER_SHOTS=<dir>): tasks-dash-dark, tasks-dash-light.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const A = "example@github.com";
const WEB = "example/web-console";
const API = "example/api";
const LIB = "acme/lib";

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
type Row = Record<string, unknown>;
function pr(repo: string, number: number, p: Row = {}): Row {
  return {
    repo,
    number,
    title: `Pull ${repo}#${number}`,
    url: `https://github.com/${repo}/pull/${number}`,
    pr: true,
    draft: false,
    state: "open",
    author: "contributor-b",
    labels: [],
    created: now() - 86_400,
    updated: now() - number * 60,
    asked: false,
    ci: "",
    review: "",
    conflict: false,
    requested: 0,
    ...p,
  };
}
const run = (id: number, p: Row = {}): Row => ({ id, workflow: "CI", title: "t", branch: "main", event: "push", state: "passed", created: now() - id * 60, started: now() - id * 60, updated: now() - id * 60 + 494, url: `https://github.com/x/actions/runs/${id}`, ...p });

function dashData() {
  return {
    [WEB]: {
      branch: "main",
      ci: "failed",
      prs: [
        pr(WEB, 212, { ci: "passed", review: "approved", labels: [{ name: "bug", color: "d73a4a" }] }),
        pr(WEB, 209, { ci: "failed", asked: true, review: "required", labels: [{ name: "enhancement", color: "a2eeef" }] }),
        pr(WEB, 205, { draft: true, state: "draft", ci: "pending" }),
      ],
      runs: [run(1, { workflow: "e2e", branch: "fix/login", state: "failed" }), run(3, { workflow: "CI", state: "pending", updated: now() })],
      releases: [{ tag: "v1.4.0", name: "v1.4.0", latest: true, prerelease: false, published: now() - 3 * 86_400, url: "https://github.com/example/web-console/releases/tag/v1.4.0" }],
      ahead: 7,
    },
    [API]: {
      branch: "main",
      ci: "passed",
      prs: [pr(API, 48, { asked: true, conflict: true })],
      runs: [run(2, { workflow: "build" })],
      releases: [],
      ahead: null,
    },
    [LIB]: { branch: "trunk", ci: "pending", prs: [], runs: [], releases: [{ tag: "v0.9.0", name: "v0.9.0", latest: false, prerelease: false, published: now() - 10 * 86_400, url: "" }], ahead: 2 },
  };
}

async function setup(page: Page, opts: { chosen?: boolean; theme?: "dark" | "light"; rate?: boolean; pins?: string[] } = {}) {
  const tasks = {
    status: { github: { installed: true, signed_in: true }, gitlab: { installed: false, signed_in: false } },
    items: {},
    gh: {
      installed: true,
      accounts: [
        { host: "github.com", login: "example", active: true, state: "success", scopes: ["repo"] },
        { host: "github.com", login: "contributor-a", active: false, state: "success", scopes: ["repo"] },
      ],
      me: {},
      dash: dashData(),
      dashFail: opts.rate ? { [API]: { kind: "rate", line: "API rate limit exceeded" } } : {},
    },
  };
  const saved = {
    source: "github",
    scope: "repo",
    pins: opts.pins ?? [WEB, API, LIB],
    folders: { "github:example/site": "/tmp/clones/site" },
    accounts: opts.chosen === false ? [] : [
      { host: "github.com", login: "example", color: "#4c8dff" },
      { host: "github.com", login: "contributor-a", color: "#f2994a" },
    ],
  };
  await page.addInitScript(
    ([theme, d, s]) => {
      localStorage.setItem("omher.theme", theme as string);
      if (!sessionStorage.getItem("__tkdash")) {
        localStorage.setItem("omher.tasks", JSON.stringify(s));
        sessionStorage.setItem("__tkdash", "1");
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
const prOrder = (page: Page) => page.getByTestId("dash-pr-list").locator(".tk-dash-pr").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled", caret: "initial" });
}

async function openDash(page: Page) {
  await page.getByTestId("ghdash-open").click();
  await expect(page.getByTestId("dash-view")).toBeVisible();
  await expect(page.getByTestId("tasks-scope-gh")).toHaveAttribute("aria-pressed", "true");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("with no GitHub account chosen there is no GitHub row, and the scope offers Connect GitHub", async ({ page }) => {
  await setup(page, { chosen: false });
  await expect(page.getByTestId("tasks-bar")).toBeVisible();
  await expect(page.getByTestId("ghdash-bar")).toHaveCount(0);
  await page.getByTestId("tasks-open").click();
  await page.getByTestId("tasks-scope-gh").click();
  await expect(page.getByTestId("dash-connect")).toBeVisible();
  await page.getByTestId("dash-connect-btn").click();
  await expect(page.getByTestId("accounts-github")).toBeVisible();
  expect((await taskCalls(page)).filter((c) => c.op === "dash")).toEqual([]);
});

test("one click from the sidebar: three columns side by side on one screen, each scrolling inside itself", async ({ page }) => {
  await setup(page);
  await openDash(page);
  await expect(page.getByTestId("ghdash-bar")).toHaveClass(/\bon\b/);
  await expect(page.getByTestId("tasks-bar")).not.toHaveClass(/\bon\b/);
  const boxes = await Promise.all(["dash-repos", "dash-prs", "dash-actions", "dash-releases"].map((id) => page.getByTestId(id).boundingBox()));
  const [repos, prs, actions, releases] = boxes.map((b) => b!);
  // left, centre, right; Actions above Releases in the right column
  expect(repos.x + repos.width).toBeLessThanOrEqual(prs.x + 1);
  expect(prs.x + prs.width).toBeLessThanOrEqual(actions.x + 1);
  expect(Math.abs(actions.x - releases.x)).toBeLessThan(1);
  expect(actions.y + actions.height).toBeLessThanOrEqual(releases.y + 1);
  // the three columns share one top and fit the window: the page does not scroll
  expect(Math.abs(repos.y - prs.y)).toBeLessThan(1);
  const vp = page.viewportSize()!;
  for (const b of [repos, prs, actions, releases]) expect(b.y + b.height).toBeLessThanOrEqual(vp.height + 1);
  const pageScrolls = await page.evaluate(() => document.scrollingElement!.scrollHeight > window.innerHeight + 1);
  expect(pageScrolls).toBe(false);
  for (const id of ["dash-repos", "dash-pr-list", "dash-actions", "dash-releases"]) {
    const overflow = await page.getByTestId(id).evaluate((el) => {
      const s = el.classList.contains("tk-dash-scroll") ? el : el.querySelector(".tk-dash-scroll")!;
      return getComputedStyle(s).overflowY;
    });
    expect(overflow, id).toBe("auto");
  }
  await shot(page, "tasks-dash-dark");
});

test("pinned repositories filter the pull requests, Actions and Releases; the default branch CI shows as a dot", async ({ page }) => {
  await setup(page);
  await openDash(page);
  await expect(page.getByTestId("dash-repo-all")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("dash-repo-all")).toContainText("3");
  await expect.poll(() => prOrder(page)).toEqual([`dash-pr-${API}#48`, `dash-pr-${WEB}#205`, `dash-pr-${WEB}#209`, `dash-pr-${WEB}#212`]);
  await expect(page.getByTestId(`dash-ci-${WEB}`)).toHaveAttribute("data-ci", "failed");
  await expect(page.getByTestId(`dash-ci-${API}`)).toHaveAttribute("data-ci", "passed");
  await expect(page.getByTestId(`dash-ci-${LIB}`)).toHaveAttribute("data-ci", "pending");
  await expect(page.getByTestId("dash-actions").locator(".tk-dash-run")).toHaveCount(3);
  await expect(page.getByTestId("dash-releases").locator(".tk-dash-rel")).toHaveCount(2);
  // one repository
  await page.getByTestId(`dash-repo-${WEB}`).click();
  await expect.poll(() => prOrder(page)).toEqual([`dash-pr-${WEB}#205`, `dash-pr-${WEB}#209`, `dash-pr-${WEB}#212`]);
  await expect(page.getByTestId("dash-open-count")).toContainText("3 Open");
  await expect(page.getByTestId("dash-actions").locator(".tk-dash-run")).toHaveCount(2);
  await expect(page.getByTestId("dash-releases").locator(".tk-dash-rel")).toHaveCount(1);
  // with one repository the rows do not repeat its name
  await expect(page.locator(".tk-dash-pr-repo")).toHaveCount(0);
  // back to every repository
  await page.getByTestId("dash-repo-all").click();
  await expect(page.locator(".tk-dash-pr-repo").first()).toBeVisible();
});

test("only the tabs 전체 and 내 리뷰 요청; GitHub's list: Open count, CI marks, label pills, the review line", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("omher.lang", "ko"));
  await setup(page);
  await openDash(page);
  const tabs = page.getByTestId("dash-prs").getByRole("tab");
  await expect(tabs).toHaveCount(2);
  await expect(tabs.nth(0)).toContainText("전체");
  await expect(tabs.nth(1)).toContainText("내 리뷰 요청");
  await expect(page.getByTestId("dash-prs")).not.toContainText("내가 연 PR");
  await expect(page.getByTestId("dash-prs")).not.toContainText("bot이 연 PR");
  await expect(page.getByTestId("dash-tab-all")).toContainText("4");
  await expect(page.getByTestId("dash-tab-asked")).toContainText("2");
  await expect(page.getByTestId("dash-open-count")).toContainText("4 Open");
  // CI beside the title
  await expect(page.getByTestId(`dash-pr-ci-${WEB}#212`)).toHaveText("✓");
  await expect(page.getByTestId(`dash-pr-ci-${WEB}#209`)).toHaveText("✗");
  await expect(page.getByTestId(`dash-pr-ci-${WEB}#205`)).toHaveText("●");
  // an open pull request's mark is GitHub's green, a draft's gray
  const color = (k: string) => page.getByTestId(`dash-pr-${k}`).locator(".pr-ic").getAttribute("data-state");
  expect(await color(`${WEB}#212`)).toBe("open");
  expect(await color(`${WEB}#205`)).toBe("draft");
  // a label is a pill tinted with its own colour
  const pill = page.getByTestId(`dash-pr-${WEB}#212`).locator(".tk-pill");
  await expect(pill).toHaveText("bug");
  expect(await pill.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgba(215, 58, 74, 0.18)");
  // the second line: #number · when · author · review state
  await expect(page.getByTestId(`dash-pr-${WEB}#212`).locator(".tk-dash-pr-l2")).toContainText("#212");
  await expect(page.getByTestId(`dash-pr-${WEB}#212`).locator(".tk-dash-pr-l2")).toContainText("contributor-b");
  await expect(page.getByTestId(`dash-pr-${WEB}#212`).locator(".tk-dash-pr-l2")).toContainText("승인됨");
  await expect(page.getByTestId(`dash-asked-${WEB}#209`)).toBeVisible();
  // the review tab
  await page.getByTestId("dash-tab-asked").click();
  await expect.poll(() => prOrder(page)).toEqual([`dash-pr-${API}#48`, `dash-pr-${WEB}#209`]);
  await expect(page.getByTestId("dash-open-count")).toContainText("2 Open");
  // kept on this computer
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("omher.tasks") ?? "{}"));
  expect(saved).toMatchObject({ scope: "gh", dashTab: "asked", pins: [WEB, API, LIB] });
});

test("a pull request opens the read-only drawer; ↗, a run and a release open in the browser", async ({ page }) => {
  await setup(page);
  await openDash(page);
  await page.getByTestId(`dash-pr-${WEB}#209`).locator(".tk-dash-pr-main").click();
  await expect(page.getByTestId("tasks-drawer")).toBeVisible();
  await expect(page.getByTestId("tasks-drawer-title")).toHaveText(`Pull ${WEB}#209`);
  await expect(page.getByTestId("tasks-start")).toBeVisible();
  // the drawer read it as the account that owns the repository
  await expect.poll(async () => (await taskCalls(page)).filter((c) => c.op === "view")).toEqual([
    { op: "view", source: "github", repo: WEB, kind: "prs", number: 209, account: A },
  ]);
  await page.getByTestId("tasks-browser").click();
  await page.getByTestId("tasks-drawer").locator(".tk-dr-head .ui-ib").click();
  await expect(page.getByTestId("tasks-drawer")).toHaveCount(0);
  await page.getByTestId(`dash-pr-${API}#48`).hover();
  await page.getByTestId(`dash-pr-open-${API}#48`).click();
  await page.getByTestId("dash-run-1").click();
  await page.getByTestId(`dash-release-${WEB}`).click();
  const opened = await page.evaluate(() => (window as unknown as { __opened: unknown[][] }).__opened.map((a) => a[0]));
  expect(opened).toEqual([
    `https://github.com/${WEB}/pull/209`,
    `https://github.com/${API}/pull/48`,
    "https://github.com/x/actions/runs/1",
    "https://github.com/example/web-console/releases/tag/v1.4.0",
  ]);
});

test("Actions show state, workflow, branch and duration; Releases the tag, Latest and the commits since", async ({ page }) => {
  await setup(page);
  await openDash(page);
  const r1 = page.getByTestId("dash-run-1");
  await expect(r1.locator(".tk-dash-mark")).toHaveAttribute("data-ci", "failed");
  await expect(r1).toContainText("e2e");
  await expect(r1).toContainText(`${WEB} · fix/login`);
  await expect(r1).toContainText("8m 14s");
  await expect(page.getByTestId("dash-run-3").locator(".tk-dash-mark")).toHaveAttribute("data-ci", "pending");
  const rel = page.getByTestId(`dash-release-${WEB}`);
  await expect(rel).toContainText("v1.4.0");
  await expect(rel.locator(".tk-dash-latest")).toBeVisible();
  await expect(rel).toContainText("7 commits to main since");
  await expect(page.getByTestId(`dash-release-${LIB}`)).toContainText("2 commits to trunk since");
  // newest release first
  const order = await page.getByTestId("dash-releases").locator(".tk-dash-rel").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(order).toEqual([`dash-release-${WEB}`, `dash-release-${LIB}`]);
});

test("pin, unpin and a folder's suggestion; ⟳ reads again; each call sends only an account and a repository", async ({ page }) => {
  await setup(page, { pins: [WEB] });
  await openDash(page);
  await expect.poll(() => prOrder(page)).toHaveLength(3);
  // a repository omher found cloned in a folder is suggested
  await expect(page.getByTestId("dash-suggest-example/site")).toBeVisible();
  await page.getByTestId("dash-suggest-example/site").click();
  await expect(page.getByTestId("dash-repo-example/site")).toBeVisible();
  await expect(page.getByTestId("dash-suggest")).toHaveCount(0);
  // pinned by name; a bad name is refused
  await page.getByTestId("dash-pin-input").fill("not a repo");
  await expect(page.getByTestId("dash-pin-go")).toBeDisabled();
  await page.getByTestId("dash-pin-input").fill(API);
  await page.getByTestId("dash-pin-go").click();
  await expect(page.getByTestId(`dash-repo-${API}`)).toBeVisible();
  await expect.poll(() => prOrder(page)).toHaveLength(4);
  // unpin
  await page.getByTestId(`dash-repo-${WEB}`).hover();
  await page.getByTestId(`dash-unpin-${WEB}`).click();
  await expect(page.getByTestId(`dash-repo-${WEB}`)).toHaveCount(0);
  await expect.poll(() => prOrder(page)).toEqual([`dash-pr-${API}#48`]);
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("omher.tasks") ?? "{}").pins);
  expect(saved).toEqual(["example/site", API]);
  // ⟳ asks again, past the minute's answer
  await page.getByTestId("dash-refresh").click();
  await expect.poll(async () => (await taskCalls(page)).filter((c) => c.op === "dash" && c.fresh).map((c) => c.repo).sort()).toEqual([API, "example/site"]);
  const calls = (await taskCalls(page)).filter((c) => c.op === "dash");
  for (const c of calls) {
    expect(Object.keys(c).sort()).toEqual(["account", "fresh", "op", "repo"]);
    // the account that owns the repository, else the first github.com account
    expect(c.account).toBe(A);
  }
});

test("GitHub's rate limit says try again soon and keeps the other repositories; light theme", async ({ page }) => {
  await setup(page, { rate: true, theme: "light" });
  await openDash(page);
  await expect(page.getByTestId("dash-rate")).toBeVisible();
  await expect.poll(() => prOrder(page)).toEqual([`dash-pr-${WEB}#205`, `dash-pr-${WEB}#209`, `dash-pr-${WEB}#212`]);
  await shot(page, "tasks-dash-light");
});
