// Add bot › New bot (BOUNDARY rule 44), against the mock bridge: the gallery lists OMH's bot templates from
// `bots.templates`, the name follows Hermes' own rule, Create sends `bots.create` with the name only, and with a
// template the new bot's main chat gets exactly one message, the template's `/omh-bot-template` line. A bot that has no
// oh-my-hermes skills yet waits for Apply template; no template, or no oh-my-hermes, still makes a bot.
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
      if (msg.id === "x1") res(msg);
    };
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

type Call = { op: string; params: Record<string, unknown> };
const calls = async (op: string): Promise<Call[]> => ((await mock("mock.calls")).calls as Call[]).filter((c) => c.op === op);
const APPLY = { name: "omh-bot-template", description: "Apply one OMH bot template in this bot's own chat." };

async function openNewBot(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByRole("button", { name: "Add a bot" }).click();
  await page.getByTestId("addbot-new-open").click();
  await expect(page.getByTestId("addbot-new")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("the gallery lists OMH's templates beside No template, and the name follows Hermes' rule", async ({ page }) => {
  await openNewBot(page);
  await expect(page.getByTestId("addbot-template-none")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("addbot-template-pr-review")).toContainText("PR reviewer");
  await expect(page.getByTestId("addbot-template-inbox-triage")).toContainText("Schedules, each created paused: 2");
  const name = page.getByTestId("addbot-name");
  const create = page.getByTestId("addbot-create");
  await expect(create).toBeDisabled();
  await name.fill("a b");
  await expect(page.getByTestId("addbot-name-error")).toContainText("Use lowercase letters");
  await name.fill("root");
  await expect(page.getByTestId("addbot-name-error")).toContainText("root is a name Hermes keeps for itself.");
  await name.fill("Kami");
  await expect(page.getByTestId("addbot-name-error")).toContainText("A bot named kami is already on this computer.");
  await expect(create).toBeDisabled();
  await name.fill("omh-tui");
  await expect(page.getByTestId("addbot-name-error")).toContainText("omh-tui is oh-my-hermes' own TUI profile");
  await expect(page.getByTestId("addbot-mirror")).toContainText("copies the main profile's API keys and model and shares its logins");
  await name.fill("  PR-Bot ");
  await expect(page.getByTestId("addbot-name-error")).toHaveCount(0);
  await expect(create).toBeEnabled();
  expect(await calls("bots.create")).toEqual([]);
});

test("Create with a template makes the bot, opens its chat and sends exactly the one apply line", async ({ page }) => {
  await mock("mock.skills", { add: [APPLY], after: 0 });
  await openNewBot(page);
  await page.getByTestId("addbot-template-pr-review").click();
  await page.getByTestId("addbot-name").fill("pr-bot");
  await page.getByTestId("addbot-create").click();
  const done = page.getByTestId("addbot-done");
  await expect(done).toContainText("pr-bot is made and its chat is open; it shows its plan for the template and changes nothing until you say yes.");
  // --no-alias left Hermes' wrapper out: the page names Hermes' own command for it
  await expect(page.getByTestId("addbot-alias").locator("code")).toHaveText("hermes profile alias pr-bot");
  await expect(page.getByTestId("bot-pr-bot")).toHaveAttribute("aria-current", "true");
  expect((await calls("bots.create")).map((c) => c.params)).toEqual([{ name: "pr-bot" }]);
  await expect.poll(async () => (await calls("chat.send")).map((c) => [c.params.bot, c.params.text])).toEqual([
    ["pr-bot", "/omh-bot-template Apply the bot template `pr-review` to this bot."],
  ]);
  await page.getByTestId("addbot-close").click();
  await expect(page.getByTestId("addbot")).toHaveCount(0);
});

test("a new bot without oh-my-hermes' skills waits for Apply template, here or on its page, and sends nothing until it can", async ({ page }) => {
  await openNewBot(page);
  await page.getByTestId("addbot-template-inbox-triage").click();
  await page.getByTestId("addbot-name").fill("mail-bot");
  await page.getByTestId("addbot-create").click();
  const waiting = page.getByTestId("addbot-waiting");
  await expect(waiting).toContainText("mail-bot is made, but it does not have oh-my-hermes' skills yet.");
  // the one-profile command for this bot, not `omh update` (which updates OMH and touches every profile)
  await expect(waiting.locator("code").first()).toHaveText("omh apply --profile mail-bot");
  await expect(waiting).toContainText("It sets up only this bot, and Hermes needs no restart.");
  await expect(waiting).toContainText("/omh-bot-template Apply the bot template `inbox-triage` to this bot.");
  await expect(page.getByTestId("bot-mail-bot")).toBeVisible();
  await page.getByTestId("addbot-apply").click();
  await expect(waiting).toContainText("mail-bot still has no oh-my-hermes skills.");
  expect(await calls("chat.send")).toEqual([]);
  // close it and come back later from the bot's page
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("addbot")).toHaveCount(0);
  await page.getByTestId("bot-mail-bot").click({ button: "right" });
  await page.getByTestId("row-menu").getByRole("menuitem", { name: "Edit bot" }).click();
  const pending = page.getByTestId("bp-template");
  await expect(pending).toContainText("Bot template inbox-triage waits to be applied.");
  await expect(pending.locator("code").nth(1)).toHaveText("omh apply --profile mail-bot");
  await page.getByTestId("bp-template-apply").click();
  await expect(pending).toContainText("mail-bot still has no oh-my-hermes skills.");
  expect(await calls("chat.send")).toEqual([]);
  await mock("mock.skills", { add: [APPLY], after: 0 });
  await page.getByTestId("bp-template-apply").click();
  await expect(page.getByTestId("bp-template")).toHaveCount(0);
  await expect.poll(async () => (await calls("chat.send")).map((c) => [c.params.bot, c.params.text])).toEqual([
    ["mail-bot", "/omh-bot-template Apply the bot template `inbox-triage` to this bot."],
  ]);
});

test("No template makes an empty bot and sends nothing; Hermes' own words show when it fails", async ({ page }) => {
  await mock("mock.createNext", { line: "Error: Cannot create profile 'empty-bot': a running gateway still owns it" });
  await openNewBot(page);
  await page.getByTestId("addbot-name").fill("empty-bot");
  await page.getByTestId("addbot-create").click();
  await expect(page.getByTestId("addbot-create-error")).toHaveText(
    "Error: Cannot create profile 'empty-bot': a running gateway still owns it",
  );
  await expect(page.getByTestId("bot-empty-bot")).toHaveCount(0);
  await page.getByTestId("addbot-create").click();
  await expect(page.getByTestId("addbot-done")).toContainText("empty-bot is made and its chat is open.");
  await expect(page.getByTestId("bot-empty-bot")).toHaveAttribute("aria-current", "true");
  expect(await calls("chat.send")).toEqual([]);
});

test("without oh-my-hermes, or one that gives no templates, the gallery says so and a plain bot still works", async ({ page }) => {
  await mock("mock.templates", { omh: "missing" });
  await openNewBot(page);
  await expect(page.getByTestId("addbot-omh-missing")).toContainText("oh-my-hermes is not on this computer");
  await expect(page.getByTestId("addbot-gallery").getByRole("radio")).toHaveCount(1);
  await mock("mock.templates", { omh: "unavailable" });
  await page.getByTestId("addbot-new").getByRole("button", { name: "Back" }).click();
  await page.getByTestId("addbot-new-open").click();
  await expect(page.getByTestId("addbot-omh-unavailable")).toContainText("oh-my-hermes gave no bot templates");
  await page.getByTestId("addbot-name").fill("plain");
  await page.getByTestId("addbot-create").click();
  await expect(page.getByTestId("bot-plain")).toHaveAttribute("aria-current", "true");
});

test("a create omher cannot confirm lists nothing, sends nothing, and points at hermes profile list", async ({ page }) => {
  await mock("mock.skills", { add: [APPLY], after: 0 });
  await mock("mock.createNext", {
    line: "omher could not confirm that Hermes finished making half-bot. It may have left profiles/half-bot. Check with `hermes profile list` in a terminal.",
    unconfirmed: true,
  });
  await openNewBot(page);
  await page.getByTestId("addbot-template-pr-review").click();
  await page.getByTestId("addbot-name").fill("half-bot");
  // a double click starts one create
  await page.getByTestId("addbot-create").dblclick();
  const box = page.getByTestId("addbot-unconfirmed");
  await expect(box).toContainText("could not confirm that Hermes finished making half-bot");
  await expect(box.locator("code")).toHaveText("hermes profile list");
  expect((await calls("bots.create")).length).toBe(1);
  await expect(page.getByTestId("bot-half-bot")).toHaveCount(0);
  expect(await calls("chat.send")).toEqual([]);
  expect(await calls("skills.list").then((c) => c.filter((x) => x.params.bot === "half-bot"))).toEqual([]);
});

test("a finished create whose setup step failed shows Hermes' warning and holds the template", async ({ page }) => {
  await mock("mock.skills", { add: [APPLY], after: 0 });
  await mock("mock.createNext", { line: "\u26a0 Skills could not be seeded. Run `held-bot update` to retry.", incomplete: true });
  await openNewBot(page);
  await page.getByTestId("addbot-template-pr-review").click();
  await page.getByTestId("addbot-name").fill("held-bot");
  await page.getByTestId("addbot-create").click();
  const done = page.getByTestId("addbot-done");
  await expect(done).toContainText("held-bot is made, but Hermes did not finish setting it up");
  await expect(page.getByTestId("addbot-notes")).toContainText("Skills could not be seeded");
  await expect(page.getByTestId("bot-held-bot")).toBeVisible();
  expect(await calls("chat.send")).toEqual([]);
  await page.getByTestId("addbot-close").click();
  await page.getByTestId("bot-held-bot").click({ button: "right" });
  await page.getByTestId("row-menu").getByRole("menuitem", { name: "Edit bot" }).click();
  await expect(page.getByTestId("bp-template")).toContainText("Bot template pr-review waits to be applied.");
});
