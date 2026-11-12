// Automations and Plugins: one list of every bot's cron jobs (read from files) and one bot's plugins and the
// catalog, both changed only through the bot's own `cron.manage` / `plugins.manage` when the person presses a
// button; the "say it in words" box, Run now and Edit go to the bot's chat; the cards a bot's own changes leave in
// its chat; the language picker (ko, ja) with no raw keys on either page.
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
const calls = async (prefix: string): Promise<Call[]> =>
  ((await mock("mock.calls")).calls as Call[]).filter((c) => c.op.startsWith(prefix));
const submitted = async (bot: string): Promise<string[]> =>
  ((await mock("mock.submits")).submits as { bot: string; text: string }[]).filter((x) => x.bot === bot).map((x) => x.text);

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
}
async function openAutomations(page: Page) {
  await open(page);
  await page.getByTestId("nav-automations").click();
  await expect(page.getByTestId("auto-list")).toBeVisible();
}
async function openPlugins(page: Page) {
  await open(page);
  await page.getByTestId("nav-plugins").click();
  await expect(page.getByTestId("plug-grid-installed")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

// ---- Automations ----------------------------------------------------------------------------------------------

test("Automations lists every bot's jobs with status, filters by bot and counts failed and paused", async ({ page }) => {
  await openAutomations(page);
  const rows = page.getByTestId("auto-list").getByRole("listitem");
  await expect(rows).toHaveCount(6);
  await expect(page.getByTestId("nav-automations")).toContainText("6");
  await expect(page.getByTestId("auto-summary")).toHaveText("1 failed · 1 paused");
  // one of each mark: done, failed, never ran, paused (its toggle off)
  await expect(page.getByTestId("auto-row-c93a7f1e0b55").locator("[data-status]")).toHaveAttribute("data-status", "failed");
  await expect(page.getByTestId("auto-row-d01be6a4c7f3").locator("[data-status]")).toHaveText("hasn't run yet");
  await expect(page.getByTestId("auto-row-f8d3e0a27c61").locator("[data-status]")).toHaveText("paused");
  await expect(page.getByTestId("auto-toggle-f8d3e0a27c61")).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("auto-toggle-a1f0c2d9e801")).toHaveAttribute("aria-checked", "true");
  // name + first line of the prompt
  await expect(page.getByTestId("auto-row-a1f0c2d9e801")).toContainText("PR morning digest");
  await expect(page.getByTestId("auto-row-a1f0c2d9e801")).toContainText("Go through the open PRs in rlaope/oh-my-hermes");
  await expect(page.getByTestId("auto-row-a1f0c2d9e801")).toContainText(/next: /);
  // the schedule in words, Hermes' own text kept in the tooltip; a script job names its script
  await expect(page.getByTestId("auto-row-a1f0c2d9e801").locator(".au-sched")).toHaveText("weekdays at 09:00");
  await expect(page.getByTestId("auto-row-a1f0c2d9e801").locator(".au-sched")).toHaveAttribute("title", "0 9 * * 1-5");
  await expect(page.getByTestId("auto-row-b7e41d0c22aa").locator(".au-sched")).toHaveText("every 30 min");
  await expect(page.getByTestId("auto-row-d01be6a4c7f3").locator(".au-sched")).toHaveText("once, Dec 1, 2026 09:00");
  await expect(page.getByTestId("auto-row-b7e41d0c22aa")).toContainText("Runs the script sso_refresh.sh");

  await expect(page.getByTestId("filter-kami")).toHaveText("Kami 4");
  await page.getByTestId("filter-friren").click();
  await expect(rows).toHaveCount(1);
  await expect(page.getByTestId("auto-summary")).toHaveText("");
  await page.getByTestId("filter-all").click();
  await expect(rows).toHaveCount(6);
  // listing reads files: no gateway call at all
  expect((await calls("automations.")).map((c) => c.op).every((op) => op === "automations.list")).toBe(true);
});

test("a row opens its detail: when, what, where it delivers, last run, and the note about chat", async ({ page }) => {
  await openAutomations(page);
  await page.getByTestId("auto-row-c93a7f1e0b55").click();
  const d = page.getByTestId("auto-detail");
  await expect(d.getByRole("heading")).toHaveText("Nightly disk cleanup");
  await expect(d).toContainText("Kami · made");
  await expect(d.getByTestId("auto-prompt")).toHaveText("Clear caches and old build output in /w, then report only what was freed.");
  await expect(d.getByTestId("auto-deliver")).toHaveText("Discord #cron");
  await expect(d.getByTestId("auto-last")).toContainText("15 runs so far");
  await expect(d.getByTestId("auto-last")).toContainText("Permission denied");
  await expect(d).toContainText('You can also change it by telling Kami in chat');
  // a job delivered to the bot's own chat says so
  await page.getByTestId("auto-row-a1f0c2d9e801").click();
  await expect(d.getByTestId("auto-deliver")).toHaveText("Kami chat (omher)");
  // primary action is the neutral ink fill, never the accent gradient
  const bg = await d.getByTestId("auto-run").evaluate((el) => getComputedStyle(el).backgroundImage);
  expect(bg).toBe("none");
});

test("the toggle pauses and resumes through cron.manage with the job id; offline is one short line", async ({ page }) => {
  await openAutomations(page);
  const tog = page.getByTestId("auto-toggle-a1f0c2d9e801");
  await tog.click();
  await expect(tog).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("auto-summary")).toHaveText("1 failed · 2 paused");
  await tog.click();
  await expect(tog).toHaveAttribute("aria-checked", "true");
  const writes = (await calls("automations.")).filter((c) => c.op !== "automations.list");
  expect(writes.map((c) => [c.op, c.params.bot, c.params.job])).toEqual([
    ["automations.pause", "kami", "a1f0c2d9e801"],
    ["automations.resume", "kami", "a1f0c2d9e801"],
  ]);
  await mock("mock.offline", { bot: "kami" });
  await tog.click();
  await expect(page.getByTestId("page-error")).toHaveText("Kami is offline. Start its gateway, then try again.");
  await expect(tog).toHaveAttribute("aria-checked", "true");
});

test("Delete asks first, then removes through cron.manage", async ({ page }) => {
  await openAutomations(page);
  await page.getByTestId("auto-row-d01be6a4c7f3").click();
  await page.getByTestId("auto-delete").click();
  await expect(page.getByTestId("auto-confirm")).toContainText('Delete "Gemini price tier check"? Kami stops running it.');
  expect((await calls("automations.remove")).length).toBe(0);
  await page.getByTestId("auto-confirm-delete").click();
  await expect(page.getByTestId("auto-row-d01be6a4c7f3")).toHaveCount(0);
  await expect(page.getByTestId("auto-detail")).toHaveCount(0);
  expect((await calls("automations.remove")).map((c) => c.params)).toEqual([{ bot: "kami", job: "d01be6a4c7f3" }]);
});

test("Run now is a chat message to the bot and opens its chat; Edit fills the box and sends nothing", async ({ page }) => {
  await openAutomations(page);
  await page.getByTestId("auto-row-e5c2a9b81d40").click();
  await page.getByTestId("auto-edit").click();
  await expect(page.getByTestId("ask-input")).toHaveValue('Change automation "Weekly product-ab report": ');
  await expect(page.getByTestId("ask-input")).toBeFocused();
  await expect(page.getByTestId("ask-bot")).toContainText("Friren");
  expect(await submitted("friren")).toEqual([]);

  await page.getByTestId("auto-run").click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").last()).toHaveText('Run my automation "Weekly product-ab report" (id e5c2a9b81d40) now.');
  expect(await submitted("friren")).toEqual(['Run my automation "Weekly product-ab report" (id e5c2a9b81d40) now.']);
  expect((await calls("automations.")).filter((c) => c.op !== "automations.list")).toEqual([]);
});

test("the top box sends to the picked bot's chat; a suggestion only fills it", async ({ page }) => {
  await openAutomations(page);
  await expect(page.getByTestId("ask-input")).toHaveAttribute("placeholder", "Say what to do and when. e.g. Every weekday at 9, summarize open PRs and send them here");
  await page.getByTestId("suggestions").getByRole("button").nth(1).click();
  await expect(page.getByTestId("ask-input")).toHaveValue("Tell me when CI fails on one of my PRs");
  expect(await submitted("default")).toEqual([]);
  await page.getByTestId("ask-bot").click();
  await page.getByTestId("ask-bot-default").click();
  await page.getByTestId("ask-send").click();
  await expect(page.getByTestId("bot-default")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").last()).toHaveText("Tell me when CI fails on one of my PRs");
  expect(await submitted("default")).toEqual(["Tell me when CI fails on one of my PRs"]);
});

test("New adds through cron.manage; Hermes' refusal shows as its own words", async ({ page }) => {
  await openAutomations(page);
  await page.getByTestId("auto-new").click();
  const form = page.getByTestId("auto-form");
  await form.getByTestId("form-name").fill("Standup notes");
  await form.getByTestId("form-schedule").fill("whenever");
  await form.getByTestId("form-prompt").fill("Collect yesterday's merged PRs into standup notes.");
  await form.getByTestId("form-add").click();
  await expect(form.getByTestId("form-error")).toContainText("Invalid schedule 'whenever'. Use: 30m, every 2h, 0 9 * * *");
  await form.getByTestId("form-schedule").fill("0 9 * * 1-5");
  await form.getByTestId("form-add").click();
  await expect(form).toHaveCount(0);
  await expect(page.getByTestId("auto-list").getByRole("listitem")).toHaveCount(7);
  await expect(page.getByTestId("auto-detail").getByRole("heading")).toHaveText("Standup notes");
  await expect(page.getByTestId("auto-deliver")).toHaveText("Kami chat (omher)");
  const adds = (await calls("automations.add")).map((c) => c.params);
  expect(adds[1]).toEqual({ bot: "kami", name: "Standup notes", schedule: "0 9 * * 1-5", prompt: "Collect yesterday's merged PRs into standup notes.", deliver: "bot-chat:kami" });
});

test("an automation the bot made in chat leaves a card there: run, open, undo", async ({ page }) => {
  await open(page);
  await mock("mock.botMade", { bot: "kami", kind: "routine" });
  const card = page.getByTestId("routine-added-card");
  await expect(card).toBeVisible();
  await expect(card).toContainText("CI watch on my PRs");
  await expect(card).toContainText("New automation");
  await expect(card).toContainText("every 15 min");
  await expect(card).toContainText("Kami chat (omher)");
  await expect(page.getByTestId("nav-automations")).toContainText("7");

  await card.getByTestId("card-open-auto").click();
  await expect(page.getByTestId("auto-detail").getByRole("heading")).toHaveText("CI watch on my PRs");
  await page.getByTestId("bot-kami").click();
  await card.getByTestId("card-undo").click();
  await card.getByTestId("card-undo-confirm").click();
  await expect(card).toContainText("Removed");
  expect((await calls("automations.remove")).map((c) => c.params)).toEqual([{ bot: "kami", job: "a9c1e7f30d12" }]);
});

// ---- Plugins --------------------------------------------------------------------------------------------------

test("Plugins: the bot's own, the catalog and the built-in ones in three tabs", async ({ page }) => {
  await openPlugins(page);
  await expect(page.getByTestId("plug-scope")).toHaveText("Kami's plugins");
  await expect(page.getByTestId("plug-tab-installed")).toHaveText("Installed4");
  await expect(page.getByTestId("plug-tab-browse")).toHaveText("Browse13");
  await expect(page.getByTestId("plug-tab-builtin")).toHaveText("Built-in3");
  const eleven = page.getByTestId("plug-card-elevenlabs-music");
  await expect(eleven.getByTestId("needs-key")).toHaveText("Needs an API key to turn on");
  await expect(eleven.getByRole("switch")).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("plug-card-homeassistant")).toContainText("4 tools");
  await page.getByTestId("plug-tab-builtin").click();
  await expect(page.getByTestId("plug-grid-builtin").locator("[data-testid^=plug-card-]")).toHaveCount(3);
  await page.getByTestId("plug-tab-browse").click();
  const grid = page.getByTestId("plug-grid-browse");
  await expect(grid.locator("[data-testid^=plug-card-]")).toHaveCount(13);
  // official first; an installed one says so instead of offering Install
  await expect(grid.locator("[data-testid^=plug-card-]").first()).toContainText("official");
  await expect(page.getByTestId("plug-card-homeassistant")).toContainText("Installed");
  await page.getByTestId("plug-cat-voice").click();
  await expect(grid.locator("[data-testid^=plug-card-]")).toHaveCount(2);
  await page.getByTestId("plug-search").fill("whisper");
  await expect(grid.locator("[data-testid^=plug-card-]")).toHaveCount(1);
  // the scope picker switches the bot
  await page.getByTestId("plug-scope").click();
  await page.getByTestId("plug-scope-friren").click();
  await expect(page.getByTestId("plug-scope")).toHaveText("Friren's plugins");
  await expect(page.getByTestId("plug-tab-installed")).toHaveText("Installed0");
});

test("Install: inspect, see what it adds and for which bot, then install that pin", async ({ page }) => {
  await openPlugins(page);
  await page.getByTestId("plug-tab-browse").click();
  await page.getByTestId("plug-install-babysit").click();
  const sheet = page.getByTestId("install-sheet");
  await expect(sheet.getByTestId("sheet-facts")).toContainText("babysit-dev/babysit");
  await expect(sheet.getByTestId("sheet-facts")).toContainText("3 tools · 1 hook");
  await expect(sheet.getByTestId("sheet-facts")).toContainText("watch_log, stop_watch, list_watches");
  await expect(sheet.getByTestId("sheet-facts")).toContainText("Kami only");
  // nothing installed by looking
  expect((await calls("plugins.install")).length).toBe(0);
  const ink = await sheet.getByTestId("sheet-install").evaluate((el) => getComputedStyle(el).backgroundImage);
  expect(ink).toBe("none");
  await sheet.getByTestId("sheet-install").click();
  await expect(sheet.getByTestId("sheet-done")).toContainText("babysit is installed and on.");
  // Hermes reloaded the bot's gateway itself: no restart is named (restarting one bot would not load it anyway)
  await expect(sheet.getByTestId("sheet-done")).toContainText("Ready in Kami's next conversation.");
  const inspect = (await calls("plugins.inspect"))[0].params;
  const install = (await calls("plugins.install"))[0].params;
  expect(inspect).toEqual({ bot: "kami", catalog_name: "babysit" });
  expect(install.catalog_name).toBe("babysit");
  expect(typeof install.inspected_sha).toBe("string");
  await sheet.getByTestId("sheet-close").click();
  await expect(page.getByTestId("plug-tab-installed")).toHaveText("Installed5");

  // a refusal reads its reason, never Hermes' message
  await page.getByTestId("plug-install-brownout").click();
  await sheet.getByTestId("sheet-install").click();
  await expect(sheet.getByTestId("sheet-error")).toHaveText("The catalog moved brownout since Hermes read it. Check it again before installing.");
  await expect(sheet.getByTestId("sheet-recheck")).toBeVisible();
});

test("toggle, update and remove (after confirm) go through plugins.manage", async ({ page }) => {
  await openPlugins(page);
  const ha = page.getByTestId("plug-toggle-homeassistant");
  await ha.click();
  await expect(ha).toHaveAttribute("aria-checked", "false");
  await page.getByTestId("plug-menu-homeassistant").click();
  await page.getByTestId("plug-update").click();
  await expect(page.getByTestId("page-note")).toHaveText("Home Assistant updated.");
  await page.getByTestId("plug-menu-herdr").click();
  await page.getByTestId("plug-remove").click();
  expect((await calls("plugins.remove")).length).toBe(0);
  await page.getByTestId("plug-confirm-remove").click();
  await expect(page.getByTestId("plug-card-herdr")).toHaveCount(0);
  await expect(page.getByTestId("page-note")).toHaveText("Herdr status removed.");
  const writes = (await calls("plugins.")).filter((c) => !["plugins.list", "plugins.catalog"].includes(c.op));
  expect(writes.map((c) => [c.op, c.params])).toEqual([
    ["plugins.toggle", { bot: "kami", key: "homeassistant", enable: false }],
    ["plugins.update", { bot: "kami", name: "homeassistant" }],
    ["plugins.remove", { bot: "kami", name: "herdr" }],
  ]);
});

test("a plugin the bot installed from chat leaves a card there: open, turn off", async ({ page }) => {
  await open(page);
  await mock("mock.botMade", { bot: "kami", kind: "plugin" });
  const card = page.getByTestId("plugin-added-card");
  await expect(card).toContainText("babysit installed");
  await expect(card).toContainText("Adds 3 tools · 1 hook");
  await card.getByTestId("card-turn-off").click();
  await expect(card).toContainText("Turned off");
  expect((await calls("plugins.toggle")).map((c) => c.params)).toEqual([{ bot: "kami", key: "babysit", enable: false }]);
  await card.getByTestId("card-open-plug").click();
  await expect(page.getByTestId("plugins")).toBeVisible();
  await expect(page.getByTestId("plug-card-babysit").getByRole("switch")).toHaveAttribute("aria-checked", "false");
});

// ---- language --------------------------------------------------------------------------------------------------

const RAW_KEY = /\b(auto|plug|nav|card|page|ask|lang|time|sched)\.[a-z][A-Za-z0-9.]*\b/;

test("the language picker switches at once (ko, ja); both pages translate and show no raw keys", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-settings").click();
  const seg = page.getByTestId("language");
  await expect(seg.getByRole("radio")).toHaveText(["English", "한국어", "日本語", "中文"]);
  await expect(seg.getByRole("radio", { name: "English" })).toHaveAttribute("aria-checked", "true");

  await seg.getByRole("radio", { name: "한국어" }).click();
  expect(await page.evaluate(() => localStorage.getItem("omher.lang"))).toBe("ko");
  await expect(page.getByTestId("nav-automations")).toContainText("자동화");
  await page.getByTestId("nav-automations").click();
  const auto = page.getByTestId("automations");
  await expect(auto.getByTestId("header")).toContainText("봇이 정해진 시간에 혼자 하는 일");
  await expect(page.getByTestId("auto-summary")).toHaveText("실패 1 · 멈춤 1");
  await expect(page.getByTestId("auto-row-a1f0c2d9e801").locator(".au-sched")).toHaveText("평일 09:00");
  await expect(page.getByTestId("auto-row-b7e41d0c22aa").locator(".au-sched")).toHaveText("30분마다");
  await expect(page.getByTestId("auto-row-b7e41d0c22aa")).toContainText("스크립트 sso_refresh.sh 실행");
  await page.getByTestId("auto-row-a1f0c2d9e801").click();
  await expect(page.getByTestId("auto-run")).toHaveText("지금 실행");
  await expect(page.getByTestId("auto-pause")).toHaveText("멈춤");
  await expect(page.getByTestId("auto-delete")).toHaveText("삭제");
  expect(await auto.innerText()).not.toMatch(RAW_KEY);
  await page.getByTestId("nav-plugins").click();
  const plug = page.getByTestId("plugins");
  await expect(page.getByTestId("plug-tab-installed")).toHaveText("설치됨4");
  await expect(page.getByTestId("plug-card-elevenlabs-music").getByTestId("needs-key")).toHaveText("켜려면 API 키가 필요해요");
  expect(await plug.innerText()).not.toMatch(RAW_KEY);

  // the choice stays after a reload, and Japanese works the same way
  await page.reload();
  await expect(page.getByTestId("nav-plugins")).toContainText("플러그인");
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("language").getByRole("radio", { name: "日本語" }).click();
  await page.getByTestId("nav-automations").click();
  await expect(page.getByTestId("automations").getByTestId("header")).toContainText("オートメーション");
  await page.getByTestId("auto-row-a1f0c2d9e801").click();
  await expect(page.getByTestId("auto-run")).toHaveText("今すぐ実行");
  expect(await page.getByTestId("automations").innerText()).not.toMatch(RAW_KEY);
  await page.getByTestId("nav-plugins").click();
  await expect(page.getByTestId("plug-tab-browse")).toContainText("探す");
  await page.getByTestId("plug-tab-browse").click();
  await expect(page.getByTestId("plug-install-babysit")).toHaveText("インストール");
  expect(await page.getByTestId("plugins").innerText()).not.toMatch(RAW_KEY);
  await expect(page.getByTestId("sidebar")).toContainText("ボット");

  // back to English for the other specs on this browser
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("language").getByRole("radio", { name: "English" }).click();
  await expect(page.getByTestId("nav-settings")).toHaveText("Settings");
});
