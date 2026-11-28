// A bot's backup model (BOUNDARY rule 55): Settings › Bots › <bot> lists Hermes' own fallback chain under the model line
// (`fallback.get`), Add picks from the bot's own model list and Remove takes one out, each sending the whole list through
// `fallback.set` (Hermes' `config set`); a chain written in Hermes' config is shown read-only. When Hermes switches a
// turn to the backup model, its marked status line leaves one lasting row in that chat.
// Shots (the section with one backup listed, the notice in a chat): OMHER_SHOTS=<dir>.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

test.use({ colorScheme: "dark" });

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const reply = await request(op, params);
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}
/** One request to the mock bridge, answered or refused. */
async function request(op: string, params: Record<string, unknown> = {}): Promise<any> {
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
  return reply;
}

type Call = { op: string; params: Record<string, unknown> };
const sets = async (): Promise<Call[]> => ((await mock("mock.calls")).calls as Call[]).filter((c) => c.op === "fallback.set");

async function shot(page: Page, name: string, el = page.locator("body")) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await el.screenshot({ path: join(SHOTS, name) });
}

/** The row menu's Edit bot: the bot's page in Settings. */
async function botPage(page: Page, bot: string) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId(`bot-${bot}`).click({ button: "right" });
  await page.getByTestId("row-menu").getByRole("menuitem", { name: "Edit bot" }).click();
  await expect(page.getByTestId(`settings-page-bot-${bot}`)).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("empty, then a backup added from the bot's own models, listed, and removed", async ({ page }) => {
  await botPage(page, "kami");
  const section = page.getByTestId("backup-model");
  await expect(section.getByTestId("backup-empty")).toHaveText(
    "No backup model: if Kami's model cannot respond, the turn stops. A backup model lets Hermes go on with another one.",
  );
  await expect(section).toContainText("A change applies from the next turn.");

  await section.getByTestId("backup-add").click();
  const pop = page.getByTestId("backup-pop");
  // the bot's own list (models.options), its main model left out; the mock's Claude (proxy) ids ("Opus 5.5") hold a
  // space, which omher cannot set, so that whole group is left out too
  await expect(pop.getByRole("group", { name: "OpenAI" }).getByTestId("backup-opt")).toHaveCount(2);
  await expect(pop.getByRole("group", { name: "Claude (proxy)" })).toHaveCount(0);
  await pop.getByTestId("backup-search").fill("grok");
  await expect(pop.getByTestId("backup-opt")).toHaveCount(1);
  await pop.getByTestId("backup-opt").click();
  await expect(section.getByTestId("backup-saving")).toBeVisible();
  await expect(section.getByTestId("backup-entry")).toHaveCount(1);
  await expect(section.getByTestId("backup-entry")).toContainText("OpenRouter · x-ai/grok-4.7");
  await expect(section.getByTestId("backup-saving")).toHaveCount(0);
  expect((await sets()).map((c) => c.params.chain)).toEqual([[{ provider: "openrouter", model: "x-ai/grok-4.7" }]]);
  // with the list it was built from
  expect((await sets())[0].params.base).toEqual([]);
  await shot(page, "backup-section.png", page.getByTestId("settings-view"));

  // a second one goes after it, and the picker no longer offers the first
  await section.getByTestId("backup-add").click();
  await pop.getByTestId("backup-search").fill("grok");
  await expect(pop.getByTestId("backup-none")).toBeVisible();
  await pop.getByTestId("backup-search").fill("terra");
  await pop.getByTestId("backup-opt").click();
  await expect(section.getByTestId("backup-entry")).toHaveCount(2);
  await expect(section.getByTestId("backup-entry").nth(1)).toContainText("OpenAI · gpt-6.1-terra");

  // Remove sends the list without it; the read after a reload is what was stored
  await section.getByTestId("backup-remove").first().click();
  await expect(section.getByTestId("backup-entry")).toHaveCount(1);
  await expect(section.getByTestId("backup-entry")).toContainText("gpt-6.1-terra");
  expect((await sets()).at(-1)!.params.chain).toEqual([{ provider: "openai", model: "gpt-6.1-terra" }]);
  await section.getByTestId("backup-remove").click();
  await expect(section.getByTestId("backup-empty")).toBeVisible();
  expect((await sets()).at(-1)!.params).toEqual({ bot: "kami", chain: [], base: [{ provider: "openai", model: "gpt-6.1-terra" }] });
});

test("a list changed elsewhere since the page read it is not written over: the page shows it as it is now", async ({ page }) => {
  await botPage(page, "kami");
  const section = page.getByTestId("backup-model");
  await expect(section.getByTestId("backup-empty")).toBeVisible();
  // someone else (Hermes' own `hermes fallback add`, another omher) sets a backup model after the page read none
  await mock("mock.fallback", { bot: "kami", chain: [{ provider: "openrouter", model: "x-ai/grok-4.7" }] });
  await section.getByTestId("backup-add").click();
  await page.getByTestId("backup-search").fill("terra");
  await page.getByTestId("backup-opt").click();
  await expect(section.getByTestId("backup-error")).toHaveText("The backup models were changed elsewhere; this is the list as it is now.");
  await expect(section.getByTestId("backup-entry")).toHaveCount(1);
  await expect(section.getByTestId("backup-entry")).toContainText("OpenRouter · x-ai/grok-4.7");
  expect((await mock("fallback.get", { bot: "kami" })).chain).toEqual([{ provider: "openrouter", model: "x-ai/grok-4.7" }]);
  // the next press builds on the fresh list
  await section.getByTestId("backup-add").click();
  await page.getByTestId("backup-search").fill("terra");
  await page.getByTestId("backup-opt").click();
  await expect(section.getByTestId("backup-entry")).toHaveCount(2);
  await expect(section.getByTestId("backup-error")).toHaveCount(0);
});

test("the mock, as the bridge, takes the bot's own model in any case as no backup model", async () => {
  await mock("chat.set_model", { bot: "kami", provider: "openai", model: "gpt-6.1-terra" });
  const reply = await request("fallback.set", { bot: "kami", chain: [{ provider: "OpenAI", model: "GPT-6.1-Terra" }], base: [] });
  expect(reply.ok).toBe(false);
  expect(reply.error.code).toBe("bad_request");
  expect(reply.error.message).toContain("own model");
});

test("Hermes' refusal shows its words, and the list stays as Hermes keeps it", async ({ page }) => {
  await mock("mock.fallback", { bot: "kami", fail: "✗ Value for 'fallback_providers' is not valid YAML/JSON — nothing was written." });
  await botPage(page, "kami");
  const section = page.getByTestId("backup-model");
  await section.getByTestId("backup-add").click();
  await page.getByTestId("backup-search").fill("terra");
  await page.getByTestId("backup-opt").click();
  await expect(section.getByTestId("backup-error")).toContainText("nothing was written");
  await expect(section.getByTestId("backup-empty")).toBeVisible();
});

test("a chain written in Hermes' config is shown read-only", async ({ page }) => {
  await mock("mock.fallback", {
    bot: "kami",
    editable: false,
    chain: [{ provider: "custom", model: "local-llm", custom: true }, { provider: "openrouter", model: "x-ai/grok-4.7" }],
  });
  await botPage(page, "kami");
  const section = page.getByTestId("backup-model");
  await expect(section.getByTestId("backup-entry")).toHaveCount(2);
  await expect(section.getByTestId("backup-entry").first()).toContainText("custom · local-llm");
  await expect(section.getByTestId("backup-entry").first()).toContainText("set in Hermes");
  await expect(section.getByTestId("backup-readonly")).toHaveText(
    "This list was written in Hermes' config, and omher will not rewrite it.",
  );
  await expect(section.getByTestId("backup-add")).toHaveCount(0);
  await expect(section.getByTestId("backup-remove")).toHaveCount(0);
  expect(await sets()).toEqual([]);
});

test("a switch to the backup model during a turn leaves a notice row in that chat", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  const line = "⚠️ Model fallback: Sonnet 5.5 via claude-proxy could not respond (rate limited); using x-ai/grok-4.7 via openrouter.";
  const ev = (event: string, extra: Record<string, unknown> = {}) => ({ event, bot: "friren", ...extra });
  await mock("mock.emit", { events: [ev("turn.start"), ev("status", { text: line, fallback: true })] });
  const notice = page.getByTestId("backup-notice");
  await expect(notice).toHaveCount(1);
  await expect(notice).toContainText("Hermes switched to a backup model");
  await expect(notice.getByTestId("system-detail")).toHaveText(
    "Sonnet 5.5 via claude-proxy could not respond (rate limited); using x-ai/grok-4.7 via openrouter.",
  );
  // the passing status line still says it while the turn runs
  await expect(page.getByTestId("activity").last()).toContainText("Model fallback");
  await mock("mock.emit", { events: [ev("status", { text: "Retrying (2/3)" }), ev("turn.end", { outcome: "done" })] });
  await expect(page.getByTestId("activity").last()).toHaveAttribute("data-state", "done");
  await expect(notice).toHaveCount(1);
  await shot(page, "backup-notice.png");

  // its title follows a language change made after the switch
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("language").getByRole("radio", { name: "한국어" }).click();
  await page.getByTestId("bot-friren").click();
  await expect(notice).toHaveCount(1);
  await expect(notice).toContainText("Hermes가 예비 모델로 전환했어요");
  await expect(notice.getByTestId("system-detail")).toHaveText(
    "Sonnet 5.5 via claude-proxy could not respond (rate limited); using x-ai/grok-4.7 via openrouter.",
  );
});
