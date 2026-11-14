// The roster: omher starts with one bot, and the other Hermes profiles on this computer join from the sidebar `+` in
// one click. Fresh start: the default profile alone. A person whose last bot (saved for resume) was Kami: Kami alone.
// `+` lists the others; Add brings one in and opens its chat. Remove from list puts it back under `+`; the last bot
// cannot be removed. An ask from a bot outside the list shows in Needs you and opens that bot. The connect block has
// no Claude sign-in.
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
      if (msg.id === "r1") res(msg);
    };
    ws.send(JSON.stringify({ id: "r1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

const calls = async (op: string) => (await mock("mock.calls")).calls.filter((c: any) => c.op === op).map((c: any) => c.params);
const listed = (page: Page) => page.locator(".bot-list button.bot").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
const roster = (page: Page) => page.evaluate(() => JSON.parse(localStorage.getItem("omher.roster") || "null"));

// nothing saved: no roster, no resume (onboarded, so no first-run language pick)
test.use({ storageState: { cookies: [], origins: [] }, colorScheme: "dark" });

test.beforeEach(async ({ page }) => {
  await mock("mock.reset");
  await page.addInitScript(() => {
    if (sessionStorage.getItem("roster-e2e")) return;
    sessionStorage.setItem("roster-e2e", "1");
    localStorage.setItem("omher.onboarded", "1");
  });
});

test("fresh start: only the default bot; + lists the others; Add brings Friren in and opens its chat in one click", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bot-default")).toHaveAttribute("aria-current", "true");
  expect(await listed(page)).toEqual(["bot-default"]);
  expect(await roster(page)).toEqual(["default"]);
  // the profiles outside the list were not opened: no Bot Chat made for them
  expect((await calls("chat.open")).map((c: any) => c.bot)).toEqual(["default"]);

  await page.getByRole("button", { name: "Add a bot" }).click();
  const pop = page.getByTestId("addbot");
  await expect(pop.locator(".ab-h")).toHaveText("Add a bot");
  await expect(pop.locator(".ab-row")).toHaveCount(3);
  await expect(page.getByTestId("addbot-default")).toHaveCount(0);
  await expect(page.getByTestId("addbot-friren")).toContainText("Friren");
  await expect(page.getByTestId("addbot-friren")).toContainText("Sonnet 5.5");
  await expect(page.getByTestId("addbot-create")).toHaveCount(0);
  await expect(pop).not.toContainText("Soon");

  await page.getByTestId("addbot-friren").getByRole("button", { name: "Add" }).click();
  await expect(pop).toHaveCount(0);
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await expect(page.locator('[data-pane="friren"]').getByTestId("timeline")).toContainText("Tauri 2 updater");
  expect(await listed(page)).toEqual(["bot-default", "bot-friren"]);
  expect(await roster(page)).toEqual(["default", "friren"]);
  // attached as Connect did: one models.options read for it
  await expect.poll(async () => (await calls("models.options")).some((c: any) => c.bot === "friren")).toBe(true);

  // it stays after a reload
  await page.reload();
  await expect(page.getByTestId("bot-friren")).toBeVisible();
  expect(await listed(page)).toEqual(["bot-default", "bot-friren"]);
});

test("resume saved Kami: Kami alone; Remove from list puts a bot back under +; the last bot cannot be removed", async ({ page }) => {
  await page.addInitScript(() => {
    if (sessionStorage.getItem("roster-resume")) return;
    sessionStorage.setItem("roster-resume", "1");
    const snap = { v: 1, at: Date.now(), bot: "kami", view: "chat", session: null, panelOpen: false, panelTab: "details", runsFull: false, runId: null, drafts: {}, sessions: [] };
    localStorage.setItem("omher.resume", JSON.stringify(snap));
    localStorage.setItem("omher.hidden", JSON.stringify(["friren"]));
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  expect(await listed(page)).toEqual(["bot-kami"]);
  expect(await roster(page)).toEqual(["kami"]);

  // the last bot: Remove from list is there but disabled, with a reason
  await page.getByTestId("bot-kami").click({ button: "right" });
  const menu = page.getByTestId("row-menu");
  await expect(menu.getByRole("menuitem")).toHaveText(["Pin to top", "Edit bot", /^Restart/, "Remove from list"]);
  const remove = page.getByTestId("row-remove");
  await expect(remove).toHaveAttribute("aria-disabled", "true");
  await expect(remove).toHaveAttribute("title", "The last bot in the list stays");
  // a press does nothing (force: Playwright itself would wait for an enabled item)
  await remove.click({ force: true });
  expect(await listed(page)).toEqual(["bot-kami"]);
  await page.keyboard.press("Escape");

  // a bot hidden in the old sidebar is still offered under +
  await page.getByRole("button", { name: "Add a bot" }).click();
  await page.getByTestId("addbot-friren").getByRole("button", { name: "Add" }).click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  expect(await listed(page)).toEqual(["bot-kami", "bot-friren"]);

  // Remove from list: out of the sidebar, the open chat moves to the bot left, and it is under + again
  await page.getByTestId("bot-friren").click({ button: "right" });
  await page.getByTestId("row-remove").click();
  expect(await listed(page)).toEqual(["bot-kami"]);
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByRole("button", { name: "Add a bot" }).click();
  await expect(page.getByTestId("addbot-friren")).toBeVisible();
  // nothing about the profile changed: only reads went out
  const ops = new Set(((await mock("mock.calls")).calls as { op: string }[]).map((c) => c.op));
  for (const op of ["chat.send", "chat.set_model", "bots.rename", "bots.set_avatar"]) expect(ops.has(op)).toBe(false);
});

test("+ with every bot already listed says so in one line, with how Hermes makes another", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("omher.roster", JSON.stringify(["kami", "friren", "default", "omh-tui"])));
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.getByRole("button", { name: "Add a bot" }).click();
  const empty = page.getByTestId("addbot-empty");
  await expect(empty).toContainText("Every bot on this computer is already here.");
  await expect(empty.locator("code")).toHaveText("hermes profile create <name>");
  await expect(page.getByTestId("addbot").locator(".ab-row")).toHaveCount(0);
});

test("an ask from a bot outside the list shows in Needs you; opening it adds that bot and opens its chat", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bot-default")).toHaveAttribute("aria-current", "true");
  await mock("mock.ask", { bot: "friren", kind: "approval" });
  const strip = page.getByTestId("needs-strip");
  await expect(page.getByTestId("needs-line")).toContainText("Friren");
  expect(await listed(page)).toEqual(["bot-default"]);
  await strip.click();
  await page.getByTestId("needs-item").first().click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("timeline").getByTestId("card-approval")).toBeVisible();
  expect(await listed(page)).toEqual(["bot-default", "bot-friren"]);
});

test("Settings › All bots lists every profile, each In list or Add to list (same action, stays on the page)", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bot-default")).toBeVisible();
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-bots").click();
  for (const b of ["kami", "friren", "default", "omh-tui"]) await expect(page.getByTestId(`bot-card-${b}`)).toBeVisible();
  await expect(page.getByTestId("bot-inlist-default")).toHaveText("In list");
  await page.getByTestId("bot-addlist-kami").click();
  await expect(page.getByTestId("bot-inlist-kami")).toHaveText("In list");
  await expect(page.getByTestId("settings-view")).toBeVisible();
  expect(await listed(page)).toEqual(["bot-default", "bot-kami"]);
});

test("the connect block offers no Claude sign-in", async ({ page }) => {
  await mock("mock.ready", { bot: "default", ok: false });
  await page.goto("/");
  const block = page.getByTestId("connect-block");
  await expect(block).toBeVisible();
  await expect(block.getByRole("button")).toHaveText(["ChatGPT / Codex", "Nous Portal", "API key…"]);
  await expect(page.getByTestId("connect-anthropic")).toHaveCount(0);
  await expect(block).not.toContainText("Claude");
});
