// Restart one bot from the app (BOUNDARY rule 29), against the mock bridge:
// 1. the bot row's menu (right-click and ⋯) has Restart under Edit, borderless, 12px, like its neighbours;
// 2. an idle bot restarts on the first press with no confirm and no --yes; the row's time slot reads "Restarting"
//    with the ring, and is normal again once the bridge says the bot is attached;
// 3. a busy bot: Hermes refuses and names the work; the row shows those lines with Cancel first, then
//    "Restart anyway", the only press that sends `interrupt` (Hermes' --yes); Cancel sends nothing;
// 4. a failure shows Hermes' last line once, with Try again;
// 5. the default profile's restart (the host gateway) names the other bots before anything runs;
// 6. an offline bot's chat says "not connected" with Start in place, and its row menu says Start;
// 7. the Plugins sheet: when Hermes says only a restart loads it, the line names that restart and offers it; when
//    the gateway did not reload, "Load now" asks for Hermes' reload-plugins (never a restart);
// 8. ko/ja/zh: no raw keys.
// Shots: OMHER_SHOTS=<dir> OMHER_SHOT_TAG=before|after (bot-restart-<what>-<tag>-<theme>.png).
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";

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

async function setup(page: Page, theme: "dark" | "light" = "dark", lang = "en") {
  await page.addInitScript(
    ([t, l]) => {
      localStorage.setItem("omher.theme", t as string);
      localStorage.setItem("omher.lang", l as string);
    },
    [theme, lang] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function shot(page: Page, what: string, theme: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: join(SHOTS, `bot-restart-${what}-${TAG}-${theme}.png`), animations: "disabled", caret: "initial" });
}

async function menuOf(page: Page, bot: string) {
  await page.getByTestId(`bot-${bot}`).click({ button: "right" });
  const menu = page.getByTestId("row-menu");
  await expect(menu).toBeVisible();
  return menu;
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

for (const theme of ["dark", "light"] as const) {
  test(`the row menu has Restart under Edit, in the house style (${theme})`, async ({ page }) => {
    await setup(page, theme);
    const menu = await menuOf(page, "friren");
    const items = menu.getByRole("menuitem");
    await expect(items).toHaveText(["Pin to top", "Edit bot", "Restart", "Hide from sidebar"]);
    const restart = items.nth(2);
    const css = await restart.evaluate((el) => {
      const s = getComputedStyle(el);
      return { size: s.fontSize, border: s.borderTopWidth, radius: s.borderRadius, bg: s.backgroundColor, h: el.getBoundingClientRect().height };
    });
    const edit = await items.nth(1).evaluate((el) => getComputedStyle(el).fontSize);
    expect(css.size).toBe(edit);
    expect(parseFloat(css.size)).toBeGreaterThanOrEqual(12);
    expect(parseFloat(css.size)).toBeLessThanOrEqual(13);
    expect(css.border).toBe("0px");
    expect(parseFloat(css.radius)).toBeGreaterThanOrEqual(4);
    expect(parseFloat(css.radius)).toBeLessThanOrEqual(6);
    // the menu stays inside the window
    const box = (await menu.boundingBox())!;
    expect(box.y + box.height).toBeLessThanOrEqual(page.viewportSize()!.height);
    await shot(page, "menu", theme);
    // the ⋯ button opens the same menu
    await page.keyboard.press("Escape");
    await page.getByTestId("bot-friren").hover();
    await page.getByTestId("bot-more-friren").click();
    await expect(page.getByTestId("row-menu").getByRole("menuitem").nth(2)).toHaveText("Restart");
  });

  test(`an idle bot restarts on one press: Restarting with the ring, then back (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await mock("mock.restart", { bot: "friren", outcome: "slow" });
    await (await menuOf(page, "friren")).getByRole("menuitem", { name: "Restart" }).click();
    const time = page.getByTestId("bot-friren").getByTestId("bot-time");
    await expect(time).toHaveText("Restarting");
    await expect(time).toHaveAttribute("data-restarting", "true");
    await expect(page.getByTestId("restart-line-friren")).toHaveCount(0); // no confirm for an idle named bot
    expect((await calls("bots.restart")).map((c) => c.params)).toEqual([{ bot: "friren" }]);
    await shot(page, "restarting", theme);
    await mock("mock.restartDone", { bot: "friren" });
    await expect(time).not.toHaveText("Restarting");
  });

  test(`a busy bot is never cut silently: what it does, Cancel first, then Restart anyway (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await mock("mock.restart", { bot: "kami", outcome: "refused", lines: [
      "chat turn 20261112_0915 pid 4242, running 3m [model claude-opus-5-5, tool terminal]",
      "cron job a1b2 (PR digest) in-process, running 40s",
    ] });
    await (await menuOf(page, "kami")).getByRole("menuitem", { name: "Restart" }).click();
    const line = page.getByTestId("restart-line-kami");
    await expect(line).toHaveAttribute("data-step", "refused");
    await expect(line.getByTestId("restart-work").locator("li")).toHaveText([
      "chat turn 20261112_0915 pid 4242, running 3m [model claude-opus-5-5, tool terminal]",
      "cron job a1b2 (PR digest) in-process, running 40s",
    ]);
    const buttons = line.getByRole("button");
    await expect(buttons).toHaveText(["Cancel", "Restart anyway"]);
    const look = await line.evaluate((el) => {
      const s = getComputedStyle(el);
      const b = getComputedStyle(el.querySelector(".rs-act")!);
      const li = getComputedStyle(el.querySelector("li")!);
      return { size: s.fontSize, li: li.fontSize, bg: s.backgroundColor, border: s.borderTopWidth, bBg: b.backgroundColor, bBorder: b.borderTopWidth, bRadius: b.borderRadius };
    });
    for (const v of [look.size, look.li]) {
      expect(parseFloat(v)).toBeGreaterThanOrEqual(12);
      expect(parseFloat(v)).toBeLessThanOrEqual(13);
    }
    expect(look.bg).toBe("rgba(0, 0, 0, 0)"); // no box
    expect(look.border).toBe("0px");
    expect(look.bBg).toBe("rgba(0, 0, 0, 0)");
    expect(look.bBorder).toBe("0px");
    expect(parseFloat(look.bRadius)).toBeGreaterThanOrEqual(4);
    expect(parseFloat(look.bRadius)).toBeLessThanOrEqual(6);
    expect((await calls("bots.restart")).map((c) => c.params)).toEqual([{ bot: "kami" }]); // no interrupt yet
    await shot(page, "busy", theme);
    // Cancel: nothing more is sent
    await buttons.first().click();
    await expect(line).toHaveCount(0);
    expect((await calls("bots.restart")).length).toBe(1);
    // again, then Restart anyway: the one press that sends interrupt
    await (await menuOf(page, "kami")).getByRole("menuitem", { name: "Restart" }).click();
    await page.getByTestId("restart-line-kami").getByTestId("restart-anyway").click();
    await expect.poll(async () => (await calls("bots.restart")).map((c) => c.params)).toEqual([
      { bot: "kami" },
      { bot: "kami" },
      { bot: "kami", interrupt: true },
    ]);
    await expect(page.getByTestId("bot-kami").getByTestId("bot-time")).toHaveText("Restarting");
  });

  test(`a failed restart shows Hermes' last line once, with Try again (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await mock("mock.restart", { bot: "friren", outcome: "failed", line: "Gateway service restart failed." });
    await (await menuOf(page, "friren")).getByRole("menuitem", { name: "Restart" }).click();
    const line = page.getByTestId("restart-line-friren");
    await expect(line).toHaveAttribute("data-step", "failed");
    await expect(line).toContainText("Friren did not restart.");
    await expect(line.getByTestId("restart-why")).toHaveText("Gateway service restart failed.");
    await expect(line.getByRole("button")).toHaveText(["Cancel", "Try again"]);
    await shot(page, "failed", theme);
    await line.getByTestId("restart-again").click();
    await expect.poll(async () => (await calls("bots.restart")).length).toBe(2);
  });

  test(`an offline bot: "not connected" with Start in place (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await mock("mock.botStatus", { bot: "friren", status: "offline" });
    await expect(page.getByTestId("bot-friren").getByTestId("bot-sub")).toHaveText("Not connected");
    await expect((await menuOf(page, "friren")).getByRole("menuitem").nth(2)).toHaveText("Start");
    await page.keyboard.press("Escape");
    await page.getByTestId("bot-friren").click();
    const note = page.getByTestId("chat-offline");
    await expect(note).toContainText("Friren is not connected.");
    await expect(note.getByTestId("chat-start")).toHaveText("Start");
    await shot(page, "offline", theme);
    await note.getByTestId("chat-start").click();
    await expect(page.getByTestId("bot-friren").getByTestId("bot-time")).toHaveText(/Starting|Restarting/);
    await expect.poll(async () => (await calls("bots.restart")).map((c) => c.params)).toEqual([{ bot: "friren" }]);
    // back online: the note goes
    await expect(note).toHaveCount(0, { timeout: 5000 });
  });

  test(`Plugins: only the restart that loads it is offered, never a per-bot one (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await page.getByTestId("nav-plugins").click();
    await page.getByTestId("plug-tab-browse").click();
    await mock("mock.pluginLoad", { load: "restart" });
    await page.getByTestId("plug-install-babysit").click();
    const sheet = page.getByTestId("install-sheet");
    await sheet.getByTestId("sheet-install").click();
    const load = sheet.getByTestId("sheet-load");
    await expect(load).toHaveAttribute("data-load", "restart");
    await expect(load).toContainText("Only a restart of Hermes loads it.");
    await expect(load.getByTestId("sheet-load-restart")).toHaveText("Restart");
    await shot(page, "plugins", theme);
    // the host gateway's restart names the bots it takes along before anything runs
    await load.getByTestId("sheet-load-restart").click();
    const confirm = load.getByTestId("sheet-load-restart-line");
    await expect(confirm).toHaveAttribute("data-step", "confirm");
    await expect(confirm).toContainText("Restarting Hermes also restarts Kami, Friren, OMH TUI.");
    await expect(confirm.getByRole("button")).toHaveText(["Cancel", "Restart"]);
    expect((await calls("bots.restart")).length).toBe(0);
    await confirm.getByTestId("restart-cancel").click();
    expect((await calls("bots.restart")).length).toBe(0);
  });
}

test("Plugins: a gateway that did not reload gets Load now (Hermes' reload-plugins), never a restart", async ({ page }) => {
  await setup(page);
  await page.getByTestId("nav-plugins").click();
  await page.getByTestId("plug-tab-browse").click();
  await mock("mock.pluginLoad", { load: "reload" });
  await page.getByTestId("plug-install-babysit").click();
  const sheet = page.getByTestId("install-sheet");
  await sheet.getByTestId("sheet-install").click();
  const load = sheet.getByTestId("sheet-load");
  await expect(load).toHaveAttribute("data-load", "reload");
  await expect(load).toContainText("Kami has not loaded it yet.");
  await load.getByTestId("sheet-load-now").click();
  await expect(load).toHaveAttribute("data-load", "live");
  await expect(load).toContainText("Ready in Kami's next conversation.");
  expect((await calls("plugins.reload")).map((c) => c.params)).toEqual([{ bot: "kami", name: "babysit" }]);
  expect((await calls("bots.restart")).length).toBe(0);
});

for (const lang of ["ko", "ja", "zh"]) {
  test(`the restart words read in ${lang}, with no raw keys`, async ({ page }) => {
    await setup(page, "dark", lang);
    await mock("mock.restart", { bot: "kami", outcome: "refused", lines: ["chat turn s1"] });
    const menu = await menuOf(page, "kami");
    await expect(menu).not.toContainText(/row\.|rs\./);
    await menu.getByRole("menuitem").nth(2).click();
    const line = page.getByTestId("restart-line-kami");
    await expect(line).toBeVisible();
    await expect(line).not.toContainText(/rs\.[a-z]/);
  });
}
