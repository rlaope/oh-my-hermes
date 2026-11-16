// Tasks (src/tasks), against the mock bridge and the mock task host (window.__omherTasks):
// 1. the sidebar's Tasks row sits under the search, above BOTS; each source mark opens the page on that source;
// 2. filters and kinds reach the host as fixed words (list calls recorded in window.__omherTaskCalls); search filters
//    the page; pagination asks for the next page;
// 3. a row opens the read-only drawer (description, comments, checks for a PR, Open in browser);
// 4. Start in thread creates a thread under the picked bot titled `#<n> <title>` whose first message is the issue's
//    URL, title and body + "Work on this issue." (thread.create + chat.send session=<thread>);
// 5. gh not signed in: one sentence naming `gh auth login` and a button that opens a terminal shell;
// 6. right-click the row -> Hide from sidebar; Settings › General shows it again;
// 7. Linear: the connect screen names the bot and the `hermes -p <bot> mcp install linear` command.
// Shots first (OMHER_SHOTS=<dir>): tasks-bar-dark, tasks-page-github-{dark,light}, tasks-detail, tasks-start-thread.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const REPO = "rlaope/oh-my-hermes";
const FOLDER = "/home/you/code/oh-my-hermes";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "x1") res(msg);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}
type Call = { op: string; params: Record<string, any> };
const calls = async (op: string): Promise<Call[]> => ((await mock("mock.calls")).calls as Call[]).filter((c) => c.op === op);

const H = 3600;
const now = () => Math.floor(Date.now() / 1000);
function issues() {
  const base = [
    { number: 1836, title: "Measurement path for the Claude composer calibration", labels: [], author: "rlaope", ago: 2 * 86_400, assignee: true },
    { number: 1817, title: "Shadow, decline, refuse and replay — an OMH decision surface from the owner's traffic", labels: [{ name: "enhancement", color: "a2eeef" }, { name: "area/routing", color: "1d76db" }], author: "rlaope", ago: 5 * 86_400, mine: true },
    { number: 1815, title: "Measure the routing-questions lane's model and decision-model arms", labels: [{ name: "area/quality", color: "0052cc" }], author: "kana", ago: 9 * 86_400, mentions: true },
    { number: 1789, title: "No chat trigger reaches the story close: the token set over-fires", labels: [{ name: "bug", color: "d73a4a" }], author: "friren", ago: 20 * 86_400 },
    { number: 1692, title: "Relational database work has no owner (index sizing, online migration)", labels: [], author: "kana", ago: 60 * 86_400 },
  ];
  const extra = Array.from({ length: 26 }, (_, i) => ({ number: 1600 - i, title: `Older open issue ${i + 1}`, labels: [], author: "rlaope", ago: (70 + i) * 86_400 }));
  return [...base, ...extra].map(({ ago, ...r }) => ({ ...r, state: "open", url: `https://github.com/${REPO}/issues/${r.number}`, created: now() - ago, updated: now() - ago + H, checks: null }));
}
function prs() {
  return [
    { number: 2907, title: "omher: bot threads, harness marks and the terminal panel", state: "open", author: "rlaope", checks: { passed: 11, failed: 0, pending: 2, total: 13 }, ago: 3 * H },
    { number: 2906, title: "omher: stacked bot threads integration", state: "draft", author: "rlaope", checks: { passed: 9, failed: 1, pending: 0, total: 10 }, ago: 26 * H },
    { number: 2899, title: "omher: live plans in the side panel", state: "open", author: "kana", checks: { passed: 12, failed: 0, pending: 0, total: 12 }, ago: 4 * 86_400 },
  ].map(({ ago, ...r }) => ({ ...r, labels: [{ name: "omher", color: "f07cc4" }], url: `https://github.com/${REPO}/pull/${r.number}`, created: now() - ago, updated: now() - ago, mine: true }));
}
const BODY = "## What\nThe composer calibration needs a **measurement path** before any change.\n\n- record 20 real turns\n- compare `p50` and `p90`\n\n" + "Detail line. ".repeat(500);

async function setup(page: Page, opts: { theme?: "dark" | "light"; gh?: { installed: boolean; signed_in: boolean } } = {}) {
  const data = {
    status: { github: opts.gh ?? { installed: true, signed_in: true }, gitlab: { installed: false, signed_in: false } },
    items: { [`github:${REPO}:issues`]: issues(), [`github:${REPO}:prs`]: prs() },
    details: {
      [`github:${REPO}:issues:1836`]: { body: BODY, comments: [{ author: "kana", body: "I can take the recording part.", created: now() - 86_400 }] },
      [`github:${REPO}:prs:2907`]: {
        body: "Bot threads replace SESSIONS.",
        checks: [
          { name: "omher / e2e", state: "passed", url: "https://github.com/x" },
          { name: "omher / cargo test", state: "pending", url: "" },
          { name: "Hermes compatibility", state: "passed", url: "" },
        ],
      },
    },
    remotes: { [FOLDER]: { source: "github", repo: REPO } },
  };
  await page.addInitScript(
    ([theme, d]) => {
      localStorage.setItem("omher.theme", theme as string);
      if (!sessionStorage.getItem("__tk")) {
        localStorage.removeItem("omher.tasks");
        sessionStorage.setItem("__tk", "1");
      }
      const w = window as unknown as { __omherTasks: unknown; __opened: unknown[] };
      w.__omherTasks = d;
      w.__opened = [];
      window.open = ((...a: unknown[]) => {
        w.__opened.push(a);
        return null;
      }) as typeof window.open;
    },
    [opts.theme ?? "dark", data] as const,
  );
  // the open thread's folder is a clone of the repository: the page picks it
  await mock("mock.threads", { bot: "kami", threads: [{ title: "Tasks port", ago: 60, cwd: FOLDER }] });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled", caret: "initial" });
}

const taskCalls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherTaskCalls?: any[] }).__omherTaskCalls ?? []));

async function openOn(page: Page, src: "github" | "gitlab" | "linear") {
  await page.getByTestId("tasks-bar").hover();
  await page.getByTestId(`tasks-bar-${src}`).click();
  await expect(page.getByTestId("tasks-page")).toBeVisible();
  await expect(page.getByTestId(`tasks-src-${src}`)).toHaveAttribute("aria-pressed", "true");
}

async function openThreadFolder(page: Page) {
  // open the seeded thread so its folder becomes the page's context
  await page.getByTestId("bot-kami").click();
  const row = page.locator('[role="treeitem"][aria-level="2"]').first();
  await expect(row).toBeVisible();
  await row.click();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test.describe("shots", () => {
  test.skip(!SHOTS, "OMHER_SHOTS unset");

  test("bar, page (dark and light), detail, start in thread", async ({ page }) => {
    test.setTimeout(60_000);
    await setup(page);
    await openThreadFolder(page);
    await page.getByTestId("tasks-bar").hover();
    await shot(page, "tasks-bar-dark");
    await openOn(page, "github");
    await expect(page.getByTestId("tasks-row-1836")).toBeVisible();
    await page.mouse.move(5, 700);
    await shot(page, "tasks-page-github-dark");
    await page.getByTestId("tasks-row-1836").click();
    await expect(page.getByTestId("tasks-drawer-body")).toContainText("measurement path");
    await shot(page, "tasks-detail");
    await page.getByTestId("tasks-kind-prs").click();
    await page.getByTestId("tasks-row-2907").click();
    await expect(page.getByTestId("tasks-drawer-checks")).toBeVisible();
    await shot(page, "tasks-detail-pr");
    await page.getByTestId("tasks-kind-issues").click();
    await page.getByTestId("tasks-row-1836").click();
    await page.getByTestId("tasks-start").click();
    await expect(page.getByTestId("tasks-page")).toBeHidden();
    await expect(page.getByText("Work on this issue.").first()).toBeVisible();
    await shot(page, "tasks-start-thread");

    const light = await page.context().newPage();
    await setup(light, { theme: "light" });
    await openThreadFolder(light);
    await openOn(light, "github");
    await expect(light.getByTestId("tasks-row-1836")).toBeVisible();
    await light.mouse.move(5, 700);
    await shot(light, "tasks-page-github-light");
  });
});

test("the Tasks row sits under the search, above BOTS, and each mark opens its source", async ({ page }) => {
  await setup(page);
  const bar = await page.getByTestId("tasks-bar").boundingBox();
  const search = await page.getByTestId("bot-search").boundingBox();
  const bots = await page.getByTestId("side-bots").boundingBox();
  expect(bar!.y).toBeGreaterThan(search!.y);
  expect(bar!.y + bar!.height).toBeLessThanOrEqual(bots!.y + 1);
  for (const src of ["gitlab", "linear", "github"] as const) await openOn(page, src);
  // the plain row keeps the last source
  await page.getByTestId("tasks-page").getByRole("button", { name: "Close tasks" }).click();
  await page.getByTestId("tasks-open").click();
  await expect(page.getByTestId("tasks-src-github")).toHaveAttribute("aria-pressed", "true");
});

test("the open thread's repository, filters, kinds, search and pages reach the host as fixed words", async ({ page }) => {
  await setup(page);
  await openThreadFolder(page);
  await openOn(page, "github");
  await expect(page.getByTestId("tasks-repo")).toHaveText(REPO);
  await expect(page.getByTestId("tasks-list").locator(".tk-row")).toHaveCount(25);
  await page.getByTestId("tasks-next").click();
  await expect(page.getByTestId("tasks-list").locator(".tk-row")).toHaveCount(6);
  await page.getByTestId("tasks-f-assigned").click();
  await expect(page.getByTestId("tasks-list").locator(".tk-row")).toHaveCount(1);
  await expect(page.getByTestId("tasks-row-1836")).toBeVisible();
  await page.getByTestId("tasks-f-mentioned").click();
  await expect(page.getByTestId("tasks-row-1815")).toBeVisible();
  await page.getByTestId("tasks-f-open").click();
  await page.getByTestId("tasks-search").fill("routing");
  await expect(page.getByTestId("tasks-list").locator(".tk-row")).toHaveCount(2);
  await page.getByTestId("tasks-search").fill("");
  await page.getByTestId("tasks-kind-prs").click();
  await expect(page.getByTestId("tasks-row-2907").getByTestId("tasks-checks")).toHaveText("2 pending");
  await expect(page.getByTestId("tasks-row-2906").getByTestId("tasks-checks")).toHaveText("1 failing");
  await expect(page.getByTestId("tasks-row-2899").getByTestId("tasks-checks")).toHaveText("12 of 12 passing");
  const lists = (await taskCalls(page)).filter((c: any) => c.op === "list");
  // only source, repo, kind, filter and page cross
  for (const c of lists) expect(Object.keys(c).sort()).toEqual(["filter", "kind", "op", "page", "repo", "source"]);
  expect(lists.map((c: any) => `${c.kind}:${c.filter}:${c.page}`)).toEqual(
    expect.arrayContaining(["issues:open:0", "issues:open:1", "issues:assigned:0", "issues:mentioned:0", "prs:open:0"]),
  );
  expect(new Set(lists.map((c: any) => c.repo))).toEqual(new Set([REPO]));
});

test("a row opens the read-only drawer; Start in thread opens a bot thread with the issue's text", async ({ page }) => {
  await setup(page);
  await openThreadFolder(page);
  await openOn(page, "github");
  await page.getByTestId("tasks-row-1836").click();
  const dr = page.getByTestId("tasks-drawer");
  await expect(dr.getByTestId("tasks-drawer-title")).toHaveText("Measurement path for the Claude composer calibration");
  await expect(dr.getByTestId("tasks-drawer-body").locator("strong")).toHaveText("measurement path");
  await expect(dr.getByTestId("tasks-drawer-comments")).toContainText("I can take the recording part.");
  // nothing on the drawer writes to GitHub: its only buttons are these
  const names = await dr.getByRole("button").allInnerTexts();
  for (const n of names) expect(n).not.toMatch(/comment|close issue|assign|merge|label|edit/i);
  await dr.getByTestId("tasks-browser").click();
  expect(await page.evaluate(() => (window as any).__opened[0][0])).toBe(`https://github.com/${REPO}/issues/1836`);
  await expect(dr.getByTestId("tasks-terminal")).toBeEnabled();

  // pick another bot, then start
  await dr.getByTestId("tasks-bot").click();
  await page.getByTestId("tasks-bot-friren").click();
  await dr.getByTestId("tasks-start").click();
  await expect(page.getByTestId("tasks-page")).toBeHidden();
  const made = await calls("thread.create");
  expect(made).toHaveLength(1);
  expect(made[0].params.bot).toBe("friren");
  expect(made[0].params.title).toBe("#1836 Measurement path for the Claude composer calibration");
  await expect.poll(async () => (await calls("chat.send")).length).toBe(1);
  const sent = (await calls("chat.send"))[0].params;
  expect(sent.bot).toBe("friren");
  expect(sent.session).toBeTruthy();
  expect(sent.text.startsWith(`https://github.com/${REPO}/issues/1836\n\n#1836 Measurement path for the Claude composer calibration\n\n## What`)).toBe(true);
  expect(sent.text.endsWith("\n\nWork on this issue.")).toBe(true);
  expect(new TextEncoder().encode(sent.text).length).toBeLessThan(4096 + 300);
  await expect(page.locator('[role="treeitem"][aria-level="2"]', { hasText: "#1836 Measurement path" })).toBeVisible();
});

test("a PR's drawer lists its checks", async ({ page }) => {
  await setup(page);
  await openThreadFolder(page);
  await openOn(page, "github");
  await page.getByTestId("tasks-kind-prs").click();
  await page.getByTestId("tasks-row-2907").click();
  const ck = page.getByTestId("tasks-drawer-checks");
  await expect(ck.locator(".tk-check")).toHaveCount(3);
  await expect(ck.locator('.tk-check[data-state="pending"]')).toContainText("omher / cargo test");
});

test("gh not signed in: one sentence naming gh auth login, and a button that opens a terminal shell", async ({ page }) => {
  await setup(page, { gh: { installed: true, signed_in: false } });
  await openOn(page, "github");
  const box = page.getByTestId("tasks-signin");
  await expect(box.locator("p")).toHaveText("Run `gh auth login` in a terminal.");
  await box.getByTestId("tasks-signin-terminal").click();
  await expect(page.getByTestId("termpanel")).toBeVisible();
  const shells = await page.evaluate(() => ((window as any).__omherShellCalls ?? []).filter((c: any) => c.op === "start"));
  expect(shells).toHaveLength(1);
  // no list was asked while signed out
  expect((await taskCalls(page)).some((c: any) => c.op === "list")).toBe(false);
});

test("right-click › Hide from sidebar; Settings › General shows it again", async ({ page }) => {
  await setup(page);
  await page.getByTestId("tasks-bar").click({ button: "right" });
  await page.getByTestId("tasks-bar-hide").click();
  await expect(page.getByTestId("tasks-bar")).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await expect(page.getByTestId("tasks-bar")).toHaveCount(0);
  await page.getByTestId("nav-settings").click();
  const tog = page.getByTestId("set-tasks-bar");
  await expect(tog).toHaveAttribute("aria-checked", "false");
  await tog.click();
  await expect(page.getByTestId("tasks-bar")).toBeVisible();
});

test("Linear: connect screen with the bot's own Hermes command; a configured Linear MCP is said, nothing listed", async ({ page }) => {
  await setup(page);
  await openOn(page, "linear");
  await expect(page.getByTestId("tasks-linear-connect")).toContainText("Connect Linear to Kami");
  await expect(page.getByTestId("tasks-linear-cmd")).toContainText("hermes -p kami mcp install linear");
  await mock("mock.linear", { bot: "kami", server: "linear" });
  await page.getByTestId("tasks-linear-bot").click();
  await page.getByTestId("tasks-linear-bot-friren").click();
  await expect(page.getByTestId("tasks-linear-cmd")).toContainText("hermes -p friren mcp install linear");
  await page.getByTestId("tasks-linear-bot").click();
  await page.getByTestId("tasks-linear-bot-kami").click();
  await expect(page.getByTestId("tasks-linear-on")).toContainText("Kami has Linear (linear)");
  expect((await calls("tasks.linear")).map((c) => c.params.bot)).toEqual(["kami", "friren", "kami"]);
});
