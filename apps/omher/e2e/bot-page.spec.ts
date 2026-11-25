// The bot page (Settings › Bots › <bot>, opened from the row menu's Edit bot or the Details panel's Edit): who the bot
// is, read-only. Persona (`SOUL.md`) and memory (`memories/MEMORY.md`, `memories/USER.md`) come from `bots.page`, read
// when the page opens and on Read again; automations, sessions elsewhere and open threads come from what the app
// already reads. Edit never writes: it opens the bot's main chat with a request in the composer, and nothing is sent
// (BOUNDARY rule 42). Each section's empty and error states, a bot on another computer, keyboard use, and Korean.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

test.use({ colorScheme: "dark" });

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

type Call = { op: string; params: Record<string, unknown> };
const pageReads = async (bot: string): Promise<number> =>
  ((await mock("mock.calls")).calls as Call[]).filter((c) => c.op === "bots.page" && c.params.bot === bot).length;
const submits = async (): Promise<unknown[]> => (await mock("mock.submits")).submits;

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

/** The row menu's Edit bot: the bot's page in Settings. */
async function botPage(page: Page, bot: string) {
  await page.getByTestId(`bot-${bot}`).click({ button: "right" });
  await page.getByTestId("row-menu").getByRole("menuitem", { name: "Edit bot" }).click();
  await expect(page.getByTestId(`settings-page-bot-${bot}`)).toBeVisible();
  await expect(page.getByTestId("bot-sections")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a bot with everything: persona as plain text, memory entries against their limits, its work", async ({ page }) => {
  await mock("mock.threads", { bot: "kami", threads: [{ title: "Fix the flaky search test", ago: 600 }, { title: "Release notes", ago: 60 }] });
  await open(page);
  await botPage(page, "kami");

  const soul = page.getByTestId("bp-soul-text");
  await expect(soul).toContainText("A calm, direct helper. Short answers first, details when asked.");
  // the file's text is text: markup in it is shown, never made into elements
  await expect(soul).toContainText("<b>not markup</b>");
  await expect(soul.locator("b")).toHaveCount(0);
  await expect(page.getByTestId("bp-persona")).toContainText("SOUL.md");
  await expect(page.getByTestId("bp-soul-size")).toHaveText(/\d+ B/);

  const mem = page.getByTestId("bp-entries-memory").locator("li");
  await expect(mem).toHaveText(["The web app deploys from main after CI passes.", "Release notes go in CHANGELOG.md."]);
  await expect(page.getByTestId("bp-use-memory")).toContainText("/ 2,200 characters");
  await expect(page.getByTestId("bp-entries-user").locator("li")).toHaveText(["Prefers short answers.\nAsks for the command first."]);
  await expect(page.getByTestId("bp-use-user")).toContainText("/ 1,375 characters");
  await expect(page.getByTestId("bp-off-memory")).toHaveCount(0);

  // automations of this bot only, each opening the Automations page on that job
  const autos = page.getByTestId("bp-automation");
  await expect(autos).toHaveCount(4);
  await expect(page.getByTestId("bp-automations")).toContainText("PR morning digest");
  await expect(page.getByTestId("bp-automations")).not.toContainText("Weekly product-ab report");
  await expect(page.getByTestId("bp-automations")).toContainText("Failed");

  // sessions elsewhere, read-only rows
  await expect(page.getByTestId("bp-away")).toHaveCount(3);
  await expect(page.getByTestId("bp-elsewhere")).toContainText("gateway 502 on /v1/responses");

  // open threads with their status; one opens the thread
  const threads = page.getByTestId("bp-thread");
  await expect(threads).toHaveCount(2);
  await expect(threads.first().getByTestId("thread-glyph")).toHaveAttribute("data-state", "idle");
  await threads.filter({ hasText: "Release notes" }).click();
  await expect(page.getByTestId("settings-view")).toHaveCount(0);
  await expect(page.getByTestId("thread-chat")).toBeVisible();
});

test("Open in Automations shows that bot's automations; a row opens its job", async ({ page }) => {
  await open(page);
  await botPage(page, "kami");
  await page.getByTestId("bp-open-automations").click();
  await expect(page.getByTestId("automations")).toBeVisible();
  await expect(page.getByTestId("filter-kami")).toHaveClass(/\bon\b/);
  await expect(page.getByTestId("filter-all")).not.toHaveClass(/\bon\b/);

  await botPage(page, "kami");
  await page.getByTestId("bp-automation").filter({ hasText: "SSO token refresh" }).click();
  await expect(page.getByTestId("automations")).toBeVisible();
  await expect(page.getByTestId("auto-detail")).toContainText("SSO token refresh");
});

test("Edit puts a request in the bot's main chat and sends nothing", async ({ page }) => {
  await mock("mock.threads", { bot: "kami", threads: [{ title: "Release notes", ago: 60 }] });
  await open(page);
  const before = (await submits()).length;
  await botPage(page, "kami");
  await page.getByTestId("bp-edit-soul").click();
  await expect(page.getByTestId("settings-view")).toHaveCount(0);
  await expect(page.getByTestId("header")).toContainText("Kami");
  const box = page.getByTestId("composer");
  await expect(box).toHaveValue("Update your SOUL.md: ");
  await expect(box).toBeFocused();

  // from a thread too, Edit lands in the main chat; by keyboard as well
  await botPage(page, "kami");
  await page.getByTestId("bp-thread").click();
  await expect(page.getByTestId("thread-chat")).toBeVisible();
  await botPage(page, "kami");
  await page.getByTestId("bp-edit-user").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("thread-chat")).toHaveCount(0);
  // the first request was still unsent in the box: it stays, and this one comes after it
  await expect(page.getByTestId("composer")).toHaveValue("Update your SOUL.md:\nUpdate what you remember about me (memories/USER.md): ");
  await page.getByTestId("composer").fill("");
  await botPage(page, "kami");
  await page.getByTestId("bp-edit-memory").click();
  await expect(page.getByTestId("composer")).toHaveValue("Update your memory (memories/MEMORY.md): ");
  // the composer puts the caret at the end on the next frame; type after it, as a person does
  await expect(page.getByTestId("composer")).toBeFocused();
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  await page.getByTestId("composer").pressSequentially("drop the CHANGELOG line");
  await expect(page.getByTestId("composer")).toHaveValue("Update your memory (memories/MEMORY.md): drop the CHANGELOG line");
  expect((await submits()).length).toBe(before);
});

test("Edit keeps what the person had typed in the main chat, and a second press adds nothing", async ({ page }) => {
  await open(page);
  const before = (await submits()).length;
  await page.getByTestId("composer").fill("half a thought");
  await botPage(page, "kami");
  await page.getByTestId("bp-edit-soul").click();
  await expect(page.getByTestId("composer")).toHaveValue("half a thought\nUpdate your SOUL.md: ");
  await botPage(page, "kami");
  await page.getByTestId("bp-edit-soul").click();
  await expect(page.getByTestId("composer")).toHaveValue("half a thought\nUpdate your SOUL.md: ");
  expect((await submits()).length).toBe(before);
});

test("a long memory scrolls inside its card", async ({ page }) => {
  await open(page);
  await botPage(page, "kami");
  const list = page.getByTestId("bp-entries-memory");
  await expect(list).toHaveCSS("overflow-y", "auto");
  await expect(list).toHaveCSS("max-height", "360px");
  await expect(page.getByTestId("bp-automations").locator(".bp-rows")).toHaveCSS("max-height", "320px");
});

test("empty and error states say what is there", async ({ page }) => {
  await open(page);
  // no SOUL.md, a memory file too large to read, a target switched off, no threads
  await botPage(page, "friren");
  await expect(page.getByTestId("bp-soul-missing")).toHaveText("This profile has no SOUL.md.");
  await expect(page.getByTestId("bp-edit-soul")).toBeVisible(); // asking the bot to write one is still offered
  await expect(page.getByTestId("bp-mem-memory")).toContainText("memories/MEMORY.md is 3.0 MB, larger than the 1.0 MB omher reads, so it was not read.");
  await expect(page.getByTestId("bp-use-memory")).toHaveCount(0);
  await expect(page.getByTestId("bp-off-user")).toHaveText("Off");
  await expect(page.getByTestId("bp-mem-user")).toContainText("Hermes does not use this memory: it is switched off in the profile's config.yaml, so the bot cannot change it until it is on.");
  // the bot cannot change a switched-off target, so Edit is not offered there
  await expect(page.getByTestId("bp-edit-user")).toHaveCount(0);
  await expect(page.getByTestId("bp-edit-memory")).toBeVisible();
  await expect(page.getByTestId("bp-mem-empty-user")).toHaveText("Nothing remembered yet.");
  await expect(page.getByTestId("bp-threads")).toHaveText("No open threads.");
  await expect(page.getByTestId("bp-away")).toHaveCount(1);

  // a SOUL.md that is a link, a memory file that could not be read
  await botPage(page, "default");
  // the card keeps its header (file name, Edit) and says why it was not read; no size for a file not read
  await expect(page.getByTestId("bp-persona")).toContainText("SOUL.md is a link, so omher does not read it.");
  await expect(page.getByTestId("bp-soul-size")).toHaveCount(0);
  await expect(page.getByTestId("bp-mem-memory")).toContainText("memories/MEMORY.md could not be read.");
  await expect(page.getByTestId("bp-elsewhere")).toHaveText("No sessions elsewhere yet.");

  // nothing at all
  await botPage(page, "omh-tui");
  await expect(page.getByTestId("bp-soul-missing")).toBeVisible();
  await expect(page.getByTestId("bp-mem-empty-memory")).toBeVisible();
  // an empty file says so once: no empty meter track beside "Nothing remembered yet."
  await expect(page.getByTestId("bp-use-memory")).toHaveCount(0);
  await expect(page.getByTestId("bp-automations")).toHaveText("No automations.");
});

test("the page reads the files when it opens and on Read again, and not by itself", async ({ page }) => {
  await open(page);
  await botPage(page, "kami");
  await expect(page.getByTestId("bp-soul-text")).toBeVisible();
  expect(await pageReads("kami")).toBe(1);
  await page.waitForTimeout(1500);
  expect(await pageReads("kami")).toBe(1);
  await page.getByTestId("bp-refresh").click();
  await expect(page.getByTestId("bp-soul-text")).toBeVisible();
  await expect.poll(() => pageReads("kami")).toBe(2);
});

test("a bot on another computer is read there, and its page says so", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.removeItem("omher.mockPeers"));
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.getByRole("button", { name: "Add a bot" }).click();
  await page.getByTestId("addbot-ssh").click();
  const card = page.getByTestId("peer-card");
  await card.getByTestId("peer-host").fill("user@host.example");
  await card.getByTestId("peer-label").fill("Build box");
  await card.getByTestId("peer-check").click();
  await expect(card.getByTestId("peer-found")).toBeVisible();
  await card.getByTestId("peer-connect").click();
  const row = page.locator('button.bot[data-testid$=":mini"]');
  await expect(row).toBeVisible();
  const id = (await row.getAttribute("data-testid"))!.slice(4);
  await botPage(page, id);
  await expect(page.getByTestId("bot-sections")).toContainText("Read on Build box by omher's bridge there and sent over SSH.");
  await expect(page.getByTestId("bp-soul-text")).toHaveText("The persona kept on the other computer.");
  // its threads are sessions on that computer's gateway, listed through its bridge (#3172): none open yet
  await expect(page.getByTestId("bp-threads")).toHaveText("No open threads.");

  // Edit lands in that bot's own main chat, unsent
  const before = (await submits()).length;
  await page.getByTestId("bp-edit-soul").click();
  await expect(page.getByTestId("settings-view")).toHaveCount(0);
  await expect(page.getByTestId(`bot-${id}`)).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("composer")).toHaveValue("Update your SOUL.md: ");
  expect((await submits()).length).toBe(before);
});

test("a failed read says why in persona and memory, and Read again recovers", async ({ page }) => {
  await mock("mock.botPageFail", { bot: "kami", on: true });
  await open(page);
  await botPage(page, "kami");
  await expect(page.getByTestId("bp-persona")).toHaveText("Kami is offline. Start its gateway, then try again.");
  await expect(page.getByTestId("bp-memory")).toHaveText("Kami is offline. Start its gateway, then try again.");
  await expect(page.getByTestId("bp-edit-soul")).toHaveCount(0);
  await mock("mock.botPageFail", { bot: "kami", on: false });
  await page.getByTestId("bp-refresh").click();
  await expect(page.getByTestId("bp-soul-text")).toContainText("A calm, direct helper.");
  await expect(page.getByTestId("bp-entries-memory").locator("li")).toHaveCount(2);
});

test("in Korean every section is in Korean", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.setItem("omher.lang", "ko"));
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.getByTestId("bot-friren").click({ button: "right" });
  await page.getByTestId("row-menu").getByRole("menuitem", { name: "봇 편집" }).click();
  const sections = page.getByTestId("bot-sections");
  await expect(sections).toContainText("페르소나");
  await expect(sections).toContainText("이 프로필에는 SOUL.md가 없어요.");
  await expect(sections).toContainText("꺼짐");
  await expect(sections).not.toContainText("bp.");
  await page.getByTestId("bp-edit-soul").click();
  await expect(page.getByTestId("composer")).toHaveValue("SOUL.md를 이렇게 고쳐줘: ");
});

test("the facts, meters and Edit links line up: places on the stats' columns, a full-width meter, Edit in each card's header", async ({ page }) => {
  await open(page);
  await botPage(page, "kami");
  await expect(page.getByTestId("bot-places")).toBeVisible();
  await expect(page.getByTestId("bp-use-memory")).toBeVisible();
  // every place starts on one of the four stat columns, the date in the last one
  const cols = await page.getByTestId("bot-facts").evaluate((f) => {
    const x = (el: Element) => Math.round(el.getBoundingClientRect().left);
    return { stats: [...f.querySelectorAll(".be-stat")].map(x), places: [...f.querySelectorAll(".be-place, .be-since")].map(x) };
  });
  expect(cols.stats).toHaveLength(4);
  expect(cols.places.length).toBeGreaterThan(1);
  for (const p of cols.places) expect(cols.stats, JSON.stringify(cols)).toContain(p);
  await expect(page.getByTestId("bot-places")).toContainText("Cron15");
  // the meter's track runs to the count at the card's right, not a 180px stub
  const meter = await page.getByTestId("bp-use-memory").evaluate((row) => ({ row: row.getBoundingClientRect().width, bar: row.querySelector(".bp-bar-in")!.getBoundingClientRect().width }));
  expect(meter.bar / meter.row, JSON.stringify(meter)).toBeGreaterThan(0.6);
  // Persona's Edit and each memory file's Edit share one right edge, inside their cards
  const rights = await page.locator("[data-testid=bp-edit-soul], [data-testid=bp-edit-memory], [data-testid=bp-edit-user]").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().right)));
  expect(rights).toHaveLength(3);
  expect(new Set(rights).size, JSON.stringify(rights)).toBe(1);
  await expect(page.getByTestId("bp-persona").getByTestId("bp-edit-soul")).toBeVisible();
  // the Model group's row says which model it is, not the heading again
  const model = page.getByTestId("settings-page-bot-kami");
  await expect(model.locator(".st-row b", { hasText: /^Model$/ })).toHaveCount(0);
  await expect(model.locator(".st-row b", { hasText: "Main chat model" })).toHaveCount(1);
});

test("a bot with no history: one quiet line instead of four empty numbers", async ({ page }) => {
  await open(page);
  await botPage(page, "omh-tui");
  const facts = page.getByTestId("bot-facts");
  await expect(facts).toHaveText("No activity yet.");
  await expect(facts.locator(".be-stat")).toHaveCount(0);
});

test("ko: the scheduled-jobs place is in Korean, the memory row and empty facts read in Korean", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("omher.lang", "ko"));
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-bot-kami").click();
  await expect(page.getByTestId("bot-places")).toContainText("예약 작업15");
  await expect(page.getByTestId("bot-places")).not.toContainText("Cron");
  await page.getByTestId("settings-nav-bot-omh-tui").click();
  await expect(page.getByTestId("bot-facts")).toHaveText("아직 활동이 없어요.");
});
