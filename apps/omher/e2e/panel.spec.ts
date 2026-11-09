// Right panel tabs: Details · Terminal · Schedule · Worktrees · Diff · Runs, all read-only. Plus the default faces.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "p1") res(msg);
    };
    ws.send(JSON.stringify({ id: "p1", op, ...params }));
  });
  ws.close();
  return reply.result;
}

const WRITES = ["chat.send", "chat.interrupt", "approval.respond", "clarify.respond", "chat.set_model", "bots.rename", "bots.set_avatar"];

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  await page.getByTestId("places").click();
  await expect(page.getByTestId("details-panel")).toHaveAttribute("data-tab", "details");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("the panel header is six tabs; the header keeps one control", async ({ page }) => {
  await open(page);
  const tabs = page.getByRole("tablist", { name: "Panel" }).getByRole("tab");
  await expect(tabs).toHaveCount(6);
  expect(await tabs.evaluateAll((els) => els.map((e) => e.getAttribute("title")))).toEqual([
    "Details",
    "Terminal",
    "Schedule",
    "Worktrees",
    "Diff",
    "Runs",
  ]);
  await expect(page.getByTestId("panel-tab-details")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("head-right").locator(":scope > *")).toHaveCount(1);
  // the selected tab is gray, not the brand gradient
  const bg = await page.getByTestId("panel-tab-details").evaluate((e) => getComputedStyle(e).backgroundImage);
  expect(bg).toBe("none");
});

test("Terminal lists what the bot ran, newest first, with failures marked", async ({ page }) => {
  await open(page);
  await page.getByTestId("panel-tab-terminal").click();
  const runs = page.getByTestId("panel-run");
  await expect(runs).toHaveCount(4);
  await expect(runs.nth(0).locator(".pn-cmd")).toHaveText("pytest tests/test_upstream.py -q");
  await expect(runs.nth(0)).toContainText("12 passed");
  await expect(runs.nth(2)).toContainText("Slack"); // run from a Slack thread
  await expect(runs.nth(3)).toHaveClass(/\bbad\b/);
  await expect(runs.nth(3)).toContainText("exit 1");
  // nothing to type into
  expect(await page.getByTestId("details-panel").locator("textarea, input, [contenteditable=true]").count()).toBe(0);
});

test("Schedule shows the routines; Worktrees opens a Diff of that worktree", async ({ page }) => {
  await open(page);
  await page.getByTestId("panel-tab-schedule").click();
  await expect(page.getByTestId("panel-routine")).toHaveCount(2);
  await expect(page.getByTestId("panel-schedule")).toContainText("Repo watch");

  await page.getByTestId("panel-tab-worktrees").click();
  const trees = page.getByTestId("panel-tree");
  await expect(trees).toHaveCount(2);
  await expect(trees.nth(0)).toContainText("fix/keepalive");
  await expect(trees.nth(0)).toContainText("2 changed");
  await expect(trees.nth(1)).toContainText("clean");

  // the second worktree: clean, so its diff is the last commit
  await trees.nth(1).click();
  await expect(page.getByTestId("panel-tab-diff")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("panel-diff")).toContainText("Last commit");
  await expect(page.getByTestId("panel-diff-patch")).toContainText("Upstream closes idle connections after 60s.");

  // switch with the picker
  await page.getByTestId("panel-diff-pick").selectOption("/w/gateway-keepalive");
  await expect(page.getByTestId("panel-diff")).toContainText("Uncommitted changes");
  await expect(page.getByTestId("panel-diff-patch").locator(".df-f")).toHaveCount(2);
  await expect(page.getByTestId("panel-diff-patch").locator(".df-l.a").first()).toContainText("idle_timeout = 55");
  await expect(page.getByTestId("panel-diff-patch").locator(".df-l.d")).toContainText("idle_timeout = 75");

  // the whole tour was reads only
  const calls = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(calls.filter((op: string) => WRITES.includes(op))).toEqual([]);
  expect(calls).toEqual(expect.arrayContaining(["panel.worktrees", "panel.diff"]));
});

test("tool tabs widen the panel; Details is the normal width again", async ({ page }) => {
  await open(page);
  const details = page.getByTestId("details");
  await expect.poll(async () => Math.round((await details.boundingBox())?.width ?? 0)).toBe(300);
  await page.getByTestId("panel-tab-diff").click();
  await expect.poll(async () => Math.round((await details.boundingBox())?.width ?? 0)).toBe(400);
  await page.getByTestId("panel-tab-details").click();
  await expect.poll(async () => Math.round((await details.boundingBox())?.width ?? 0)).toBe(300);
});

test("a bot with nothing yet says so instead of an empty panel", async ({ page }) => {
  await open(page);
  await page.getByTestId("bot-friren").click();
  await page.getByTestId("panel-tab-terminal").click();
  await expect(page.getByTestId("panel-terminal")).toContainText("has not run a command yet");
  await page.getByTestId("panel-tab-schedule").click();
  await expect(page.getByTestId("panel-schedule")).toContainText("No routines yet");
  await page.getByTestId("panel-tab-worktrees").click();
  await expect(page.getByTestId("panel-worktrees")).toContainText("No git worktrees");
});

test("default faces are drawn whole (not cropped to a circle); an uploaded picture is round", async ({ page }) => {
  await page.goto("/");
  const av = page.getByTestId("bot-kami").locator("img.ui-av");
  await expect(av).toHaveAttribute("src", /face-blob|data:image\/svg/);
  expect(await av.evaluate((e) => getComputedStyle(e).borderRadius)).toBe("0px");
  const srcs = await page.locator('[data-testid^="bot-"] img.ui-av').evaluateAll((els) => els.map((e) => (e as HTMLImageElement).src));
  expect(new Set(srcs).size).toBe(srcs.length); // each bot its own face
});
