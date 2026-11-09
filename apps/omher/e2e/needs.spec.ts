// Needs you: approvals and questions from bots you are not looking at. Amber dot + count on the bot row, a
// "N need you" strip above BOTS that jumps to the card, 1/2/3 on a focused approval card only, a 3-question
// interview answered with one clarify.respond, timeout clears the dot, and the row menu (pin / hide).
import { expect, test, type Page } from "@playwright/test";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
// Screenshots stay out of the repo (NEEDS_SHOTS dir, else Playwright's ignored test-results).
const SHOTS = process.env.NEEDS_SHOTS || "test-results";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "n1") res(msg);
    };
    ws.send(JSON.stringify({ id: "n1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

const calls = async (op: string) => (await mock("mock.calls")).calls.filter((c: any) => c.op === op);
const mod = async (page: Page) => ((await page.evaluate(() => /Mac/.test(navigator.platform))) ? "Meta" : "Control");

async function open(page: Page, theme: "dark" | "light" = "dark") {
  await page.emulateMedia({ colorScheme: theme });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  // every other bot's chat is loaded too, so its asks can show in the sidebar
  await expect(page.getByTestId("bot-friren").getByTestId("bot-sub")).toContainText("updater");
}

test.beforeEach(async ({ page }) => {
  await mock("mock.reset");
  // start each test with nothing pinned or hidden (once per tab, so a reload keeps what the test set)
  await page.addInitScript(() => {
    if (sessionStorage.getItem("needs-e2e")) return;
    sessionStorage.setItem("needs-e2e", "1");
    localStorage.removeItem("omher.pinned");
    localStorage.removeItem("omher.hidden");
  });
});

test("asks on bots you are not looking at: amber dot + count, strip shows 2, click jumps and focuses the card", async ({ page }) => {
  await open(page);
  await mock("mock.ask", { bot: "friren", kind: "approval" });
  await mock("mock.ask", { bot: "default", kind: "clarify" });

  const friren = page.getByTestId("bot-friren");
  const dot = friren.getByTestId("needs");
  await expect(dot).toHaveText("1");
  await expect(dot).toHaveAttribute("aria-label", "Needs your answer");
  await expect(friren.getByTestId("unread")).toHaveCount(0);
  await expect(friren.getByTestId("bot-sub")).toHaveText("Allow `rm -rf build/`?");
  await expect(page.getByTestId("bot-default").getByTestId("bot-sub")).toHaveText("Which environment should I deploy to?");
  // amber, not the accent gradient of an unread badge
  const look = await dot.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { bg: cs.backgroundColor, img: cs.backgroundImage };
  });
  expect(look.img).toBe("none");
  const [r, g, b] = (look.bg.match(/[\d.]+/g) ?? []).map(Number);
  expect(r).toBeGreaterThan(180);
  expect(g).toBeGreaterThan(120);
  expect(b).toBeLessThan(110);

  const strip = page.getByTestId("needs-strip");
  await expect(strip).toContainText("2 need you");
  await page.screenshot({ path: join(SHOTS, "T12-needs-dark.png"), animations: "disabled" });
  await strip.click();
  const items = page.getByTestId("needs-item");
  await expect(items).toHaveCount(2);
  await expect(items.nth(0)).toContainText("Friren");
  await expect(items.nth(0)).toContainText("Allow `rm -rf build/`?");
  await expect(items.nth(1)).toContainText("Hermes");
  await page.screenshot({ path: join(SHOTS, "T12-strip-dark.png"), animations: "disabled" });

  await items.nth(0).click();
  await expect(friren).toHaveAttribute("aria-current", "true");
  const card = page.getByTestId("timeline").getByTestId("card-approval");
  await expect(card).toBeFocused();
  await expect(card).toBeInViewport();

  // ⌘J goes to the next ask (Hermes' question), then wraps back
  const key = await mod(page);
  await page.keyboard.press(`${key}+j`);
  await expect(page.getByTestId("bot-default")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("timeline").getByTestId("card-clarify")).toBeFocused();
  await page.keyboard.press(`${key}+j`);
  await expect(friren).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("timeline").getByTestId("card-approval")).toBeFocused();
});

test("1/2/3 answer an approval only while its card has focus", async ({ page }) => {
  await open(page);
  await mock("mock.ask", { bot: "friren", kind: "approval" });
  await page.getByTestId("bot-friren").click();
  const card = page.getByTestId("timeline").getByTestId("card-approval");
  await expect(card).toBeVisible();

  // typing 1/2/3 in the composer just types
  const composer = page.getByTestId("composer");
  await composer.focus();
  await page.keyboard.type("123");
  await expect(composer).toHaveValue("123");
  await composer.fill("");
  // nor do they act with the focus on the page body
  await page.getByTestId("timeline").click({ position: { x: 20, y: 20 } });
  await page.keyboard.press("2");
  await page.waitForTimeout(300);
  expect(await calls("approval.respond")).toEqual([]);
  await expect(card).toBeVisible();

  // focused: 2 = Allow once
  await card.focus();
  await page.screenshot({ path: join(SHOTS, "T12-card-focused-dark.png"), animations: "disabled" });
  await page.keyboard.press("2");
  await expect(page.getByTestId("timeline").getByTestId("card-line")).toHaveText(/Allowed once/);
  expect(await calls("approval.respond")).toEqual([
    expect.objectContaining({ params: expect.objectContaining({ bot: "friren", choice: "once" }) }),
  ]);
  await expect(page.getByTestId("bot-friren").getByTestId("needs")).toHaveCount(0);
  await expect(page.getByTestId("needs-strip")).toHaveCount(0);
});

test("interview: three questions in one card, answers go back in one clarify.respond (skips allowed)", async ({ page }) => {
  await open(page);
  await mock("mock.ask", { bot: "friren", kind: "interview" });
  await expect(page.getByTestId("bot-friren").getByTestId("bot-sub")).toHaveText(/^3 questions: Who is the release note for\?/);
  await page.getByTestId("needs-strip").click();
  await page.getByTestId("needs-item").first().click();

  const card = page.getByTestId("timeline").getByTestId("card-interview");
  await expect(card).toBeFocused();
  await expect(card.getByTestId("iv-question")).toHaveCount(3);
  await expect(card.getByTestId("iv-count")).toHaveText("0 of 3 answered · the rest are skipped");

  // 1: single choice; picking another replaces it
  const q1 = card.getByRole("radiogroup", { name: "Who is the release note for?" });
  await q1.getByRole("radio", { name: "Users" }).click();
  await q1.getByRole("radio", { name: "Both" }).click();
  await expect(q1.getByRole("radio", { name: "Both" })).toHaveAttribute("aria-checked", "true");
  await expect(q1.getByRole("radio", { name: "Users" })).toHaveAttribute("aria-checked", "false");
  // 2: multi-select plus an Other text
  const q2 = card.getByRole("group", { name: "Which sections should it have?" });
  await q2.getByRole("checkbox", { name: "Highlights" }).click();
  await q2.getByRole("checkbox", { name: "Fixes" }).click();
  await q2.getByRole("button", { name: "Other…" }).click();
  await q2.getByLabel("Other answer 2").fill("Upgrade notes");
  // 3: left blank -> skipped
  await expect(card.getByTestId("iv-count")).toHaveText("2 of 3 answered · the rest are skipped");

  // selected chips are gray, never the brand gradient
  const on = q1.getByRole("radio", { name: "Both" });
  expect(await on.evaluate((el) => getComputedStyle(el).backgroundImage)).toBe("none");
  const [r, g, b] = ((await on.evaluate((el) => getComputedStyle(el).backgroundColor)).match(/[\d.]+/g) ?? []).map(Number);
  expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThan(24);
  await page.screenshot({ path: join(SHOTS, "T12-interview-dark.png"), animations: "disabled" });

  await card.getByRole("button", { name: "Submit" }).click();
  await expect(page.getByTestId("timeline").getByTestId("card-line")).toHaveText(/Answered: 2 of 3/);
  const responds = await calls("clarify.respond");
  expect(responds).toHaveLength(1);
  expect(responds[0].params).toEqual({
    bot: "friren",
    request_id: expect.stringMatching(/^interview-/),
    answers: { q1: "Both", q2: JSON.stringify(["Highlights", "Fixes", "Upgrade notes"]), q3: null },
  });
  await expect(page.getByTestId("bubble-bot").filter({ hasText: "Got it, using 2 of 3 answers." })).toBeVisible();
  await expect(page.getByTestId("needs-strip")).toHaveCount(0);
});

test("a timed-out ask shows Timed out and the dot clears", async ({ page }) => {
  await open(page);
  await mock("mock.ask", { bot: "friren", kind: "approval", timeout_ms: 1500 });
  const dot = page.getByTestId("bot-friren").getByTestId("needs");
  await expect(dot).toHaveText("1");
  await expect(page.getByTestId("needs-strip")).toContainText("1 needs you");
  await expect(dot).toHaveCount(0, { timeout: 6_000 });
  await expect(page.getByTestId("needs-strip")).toHaveCount(0);
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("timeline").getByTestId("card-line")).toHaveText(/Timed out/);
  await expect(page.getByTestId("timeline").getByTestId("card-approval")).toHaveCount(0);
  expect(await calls("approval.respond")).toEqual([]);
});

test("row menu: pin moves a bot to the top (and ⌘1 follows), hide removes it, Show hidden brings it back", async ({ page }) => {
  await open(page);
  const order = () => page.locator(".bot-list button.bot").evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(await order()).toEqual(["bot-kami", "bot-friren", "bot-default"]);

  // right-click opens the menu; it offers no New thread, Duplicate or Delete
  await page.getByTestId("bot-default").click({ button: "right" });
  const menu = page.getByTestId("row-menu");
  await expect(menu.getByRole("menuitem")).toHaveText(["Pin to top", "Edit bot", "Hide from sidebar"]);
  await page.screenshot({ path: join(SHOTS, "T12-menu-dark.png"), animations: "disabled" });
  await menu.getByRole("menuitem", { name: "Pin to top" }).click();
  expect(await order()).toEqual(["bot-default", "bot-kami", "bot-friren"]);
  await expect(page.getByTestId("bot-default").getByTestId("pinned")).toBeVisible();
  await page.keyboard.press(`${await mod(page)}+1`);
  await expect(page.getByTestId("bot-default")).toHaveAttribute("aria-current", "true");

  // the ⋯ button opens the same menu; hide survives a reload
  await page.getByTestId("bot-friren").hover();
  await page.getByTestId("bot-more-friren").click();
  await page.getByTestId("row-menu").getByRole("menuitem", { name: "Hide from sidebar" }).click();
  expect(await order()).toEqual(["bot-default", "bot-kami"]);
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  expect(await order()).toEqual(["bot-default", "bot-kami"]);

  await page.getByTestId("bot-kami").click({ button: "right" });
  await page.getByTestId("row-menu").getByRole("menuitem", { name: "Show hidden…" }).click();
  const hidden = page.getByTestId("hidden-list");
  await expect(hidden).toContainText("Friren");
  await hidden.getByRole("button", { name: "Show Friren" }).click();
  await expect(hidden).toHaveCount(0);
  expect(await order()).toEqual(["bot-default", "bot-kami", "bot-friren"]);

  // Edit bot opens that bot's page in Settings
  await page.getByTestId("bot-friren").click({ button: "right" });
  await page.getByTestId("row-menu").getByRole("menuitem", { name: "Edit bot" }).click();
  await expect(page.getByTestId("settings-view")).toBeVisible();
  await expect(page.getByTestId("bot-name")).toHaveText("Friren");
});

test("light theme: dot, strip and interview stay readable", async ({ page }) => {
  await open(page, "light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await mock("mock.ask", { bot: "friren", kind: "interview" });
  await mock("mock.ask", { bot: "default", kind: "approval" });
  await expect(page.getByTestId("needs-strip")).toContainText("2 need you");
  await page.screenshot({ path: join(SHOTS, "T12-needs-light.png"), animations: "disabled" });
  await page.getByTestId("needs-strip").click();
  await page.screenshot({ path: join(SHOTS, "T12-strip-light.png"), animations: "disabled" });
  await page.getByTestId("needs-item").first().click();
  const card = page.getByTestId("timeline").getByTestId("card-interview");
  await expect(card).toBeFocused();
  await card.getByRole("radio", { name: "Developers" }).click();
  await card.getByRole("checkbox", { name: "Fixes" }).click();
  await page.screenshot({ path: join(SHOTS, "T12-interview-light.png"), animations: "disabled" });
  await page.getByTestId("bot-default").click({ button: "right" });
  await expect(page.getByTestId("row-menu")).toBeVisible();
  await page.screenshot({ path: join(SHOTS, "T12-menu-light.png"), animations: "disabled" });
});
