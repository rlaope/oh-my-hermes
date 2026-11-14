// Restart from the app (BOUNDARY rule 29): the gateway PROCESS that serves the bot, against the mock bridge (the host
// gateway serves Kami, Friren and Hermes; OMH TUI runs its own, as on the owner's Mac):
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
  if (what !== "menu") await page.mouse.move(900, 600); // a hovered row shows its ⋯ in place of its status
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
    // Friren shares the host gateway: the Restart item says who restarts with it, before the press, quietly
    await expect(menu.getByTestId("row-restart-with")).toHaveText("with Kami and Hermes");
    await expect(items.nth(2)).toHaveText(/^Restart/);
    await expect(items.nth(0)).toHaveText("Pin to top");
    await expect(items.nth(3)).toHaveText("Remove from list");
    const sub = await menu.getByTestId("row-restart-with").evaluate((el) => {
      const s = getComputedStyle(el);
      const main = getComputedStyle(el.parentElement!);
      return { size: parseFloat(s.fontSize), color: s.color, mainColor: main.color, ws: s.whiteSpace };
    });
    expect(sub.size).toBeLessThan(12.5);
    expect(sub.color).not.toBe(sub.mainColor); // dim
    expect(sub.ws).toBe("nowrap");
    const restart = items.nth(2);
    const css = await restart.evaluate((el) => {
      const s = getComputedStyle(el);
      return { size: s.fontSize, border: s.borderTopWidth, radius: s.borderRadius, bg: s.backgroundColor, h: el.getBoundingClientRect().height };
    });
    const edit = await items.nth(1).evaluate((el) => getComputedStyle(el).fontSize);
    // a bot with its own gateway restarts alone: no second line
    await page.keyboard.press("Escape");
    const solo = await menuOf(page, "omh-tui");
    await expect(solo.getByRole("menuitem").nth(2)).toHaveText("Restart");
    await expect(solo.getByTestId("row-restart-with")).toHaveCount(0);
    await page.keyboard.press("Escape");
    await menuOf(page, "friren");
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
    await expect(page.getByTestId("row-menu").getByRole("menuitem").nth(2)).toHaveText(/^Restart/);
  });

  test(`one press restarts the host gateway: every bot on it reads Restarting together, then back (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await mock("mock.restart", { bot: "friren", outcome: "slow" });
    await (await menuOf(page, "friren")).getByTestId("row-restart").click();
    for (const b of ["friren", "kami", "default"]) {
      const time = page.getByTestId(`bot-${b}`).getByTestId("bot-time");
      await expect(time, b).toHaveText("Restarting");
      await expect(time, b).toHaveAttribute("data-restarting", "true");
    }
    // OMH TUI runs its own gateway: untouched
    await expect(page.getByTestId("bot-omh-tui")).not.toContainText("Restarting");
    await expect(page.getByTestId("restart-line-friren")).toHaveCount(0); // nothing was running: no confirm
    expect((await calls("bots.restart")).map((c) => c.params)).toEqual([{ bot: "friren" }]);
    await shot(page, "restarting", theme);
    await mock("mock.restartDone", { bot: "friren" });
    for (const b of ["friren", "kami", "default"])
      await expect(page.getByTestId(`bot-${b}`).getByTestId("bot-time"), b).not.toHaveText("Restarting");
  });

  test(`a bot with its own gateway restarts alone (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await mock("mock.restart", { bot: "omh-tui", outcome: "slow" });
    await (await menuOf(page, "omh-tui")).getByTestId("row-restart").click();
    await expect(page.getByTestId("bot-omh-tui").getByTestId("bot-time")).toHaveText("Restarting");
    for (const b of ["friren", "kami", "default"])
      await expect(page.getByTestId(`bot-${b}`).getByTestId("bot-time"), b).not.toHaveText("Restarting");
    await mock("mock.restartDone", { bot: "omh-tui" });
  });

  test(`a busy bot is never cut silently: what it does, Cancel first, then Restart anyway (${theme})`, async ({ page }) => {
    await setup(page, theme);
    // what the real bridge's work_unit reads out of Hermes' two unit lines (bridge test pins that reading)
    await mock("mock.restart", { bot: "kami", outcome: "refused", work: [
      { kind: "chat", name: null, secs: 185, bot: "kami" },
      { kind: "cron", name: "PR digest", secs: 40, bot: "friren" },
      { kind: "cron", name: "Nightly digest of every open pull request in every repository", secs: 3720, bot: "default" },
      // a line Hermes sent that the bridge could not read, but whose session key named the profile
      { kind: "work", name: null, secs: 120, bot: "default" },
      // and one it said nothing readable about
      { kind: "work", name: null, secs: null, bot: null },
    ] });
    await (await menuOf(page, "kami")).getByTestId("row-restart").click();
    const line = page.getByTestId("restart-line-kami");
    await expect(line).toHaveAttribute("data-step", "refused");
    // the sentence agrees with the count
    await expect(line.locator(".rs-t")).toHaveText("5 things are running. Restarting now stops them all:");
    const items = line.getByTestId("restart-work").locator("li");
    await expect(items.locator(".rs-what")).toHaveText([
      "Kami: A chat turn",
      "Friren: Scheduled job PR digest",
      "Hermes: Scheduled job Nightly digest of every open pull request in every repository",
      "Hermes: something else",
      "1 more thing is running",
    ]);
    // the time, the one thing a person weighs, is its own part: right-aligned, never cut
    await expect(items.nth(0).locator(".rs-for")).toHaveText("3m");
    await expect(items.nth(1).locator(".rs-for")).toHaveText("40s");
    await expect(items.nth(2).locator(".rs-for")).toHaveText("1h 2m");
    await expect(items.nth(3).locator(".rs-for")).toHaveText("2m");
    await expect(items.nth(4).locator(".rs-for")).toHaveCount(0);
    await expect(line).not.toContainText("Something it is doing");
    // no run id, pid, job id or bracket in what a person reads
    await expect(line).not.toContainText(/pid|\[|\]|20261112|a1b2|in-process/);
    // each thing on ONE line; only the description takes the ellipsis, never the time, never broken mid-word
    const rows = await items.evaluateAll((els) => els.map((el) => {
      const li = el.getBoundingClientRect();
      const what = el.querySelector<HTMLElement>(".rs-what")!;
      const time = el.querySelector<HTMLElement>(".rs-for");
      const w = getComputedStyle(what);
      const tr = time?.getBoundingClientRect();
      return {
        h: li.height, lh: parseFloat(getComputedStyle(el).lineHeight), ws: getComputedStyle(el).whiteSpace, to: w.textOverflow,
        over: what.scrollWidth > what.clientWidth,
        time: time ? { cut: time.scrollWidth > time.clientWidth, right: Math.abs(tr!.right - li.right), afterWhat: tr!.left >= what.getBoundingClientRect().right } : null,
      };
    }));
    for (const r of rows) {
      expect(r.h).toBeLessThanOrEqual(r.lh + 1);
      expect(r.ws).toBe("nowrap");
      expect(r.to).toBe("ellipsis");
      if (r.time) {
        expect(r.time.cut).toBe(false);
        expect(r.time.right).toBeLessThanOrEqual(0.5);
        expect(r.time.afterWhat).toBe(true);
      }
    }
    expect(rows[2].over).toBe(true); // the long name is cut with the ellipsis, not wrapped; its time stays whole
    await expect(items.nth(2)).toHaveAttribute("title", "Hermes: Scheduled job Nightly digest of every open pull request in every repository, 1h 2m");
    // nothing went down while Hermes refused
    await expect(page.getByTestId("bot-friren").getByTestId("bot-time")).not.toHaveText("Restarting");
    const buttons = line.getByRole("button");
    await expect(buttons).toHaveText(["Cancel", "Restart anyway"]);
    const look = await line.evaluate((el) => {
      const s = getComputedStyle(el);
      const menu = document.createElement("div");
      menu.className = "row-menu";
      document.body.appendChild(menu);
      const m = getComputedStyle(menu);
      const want = { bg: m.backgroundColor, border: m.borderTopColor, shadow: m.boxShadow };
      menu.remove();
      const [c, a] = [...el.querySelectorAll<HTMLElement>(".rs-act")].map((b) => getComputedStyle(b));
      const row = el.closest(".bot-w")!.querySelector(".bot")!.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      return {
        size: s.fontSize, bg: s.backgroundColor, border: s.borderTopWidth, borderColor: s.borderTopColor, shadow: s.boxShadow, want,
        inRow: r.left >= row.left && r.right <= row.right + 0.5, rowW: row.width, w: r.width,
        cancel: { bg: c.backgroundColor, border: c.borderTopWidth, deco: c.textDecorationLine },
        anyway: { bg: a.backgroundColor, border: a.borderTopWidth, radius: a.borderRadius, color: a.color, deco: a.textDecorationLine },
        ink: getComputedStyle(el.querySelector(".rs-t")!).color,
      };
    });
    expect(parseFloat(look.size)).toBeGreaterThanOrEqual(12);
    expect(parseFloat(look.size)).toBeLessThanOrEqual(13);
    // the menu's own surface: its background, border and shadow, inside the row's width
    expect(look.bg).toBe(look.want.bg);
    expect(look.border).toBe("1px");
    expect(look.borderColor).toBe(look.want.border);
    expect(look.shadow).toBe(look.want.shadow);
    expect(look.inRow).toBe(true);
    expect(look.w).toBeGreaterThan(look.rowW - 20);
    // Cancel quiet (no border), "Restart anyway" the outlined one; neither filled
    expect(look.cancel.border).toBe("0px");
    expect(look.cancel.bg).toBe("rgba(0, 0, 0, 0)");
    expect(look.anyway.border).toBe("1px");
    expect(look.anyway.bg).toBe("rgba(0, 0, 0, 0)");
    expect(look.anyway.deco).toBe("none");
    expect(parseFloat(look.anyway.radius)).toBeGreaterThanOrEqual(4);
    expect(parseFloat(look.anyway.radius)).toBeLessThanOrEqual(6);
    expect((await calls("bots.restart")).map((c) => c.params)).toEqual([{ bot: "kami" }]); // no interrupt yet
    await shot(page, "busy", theme);
    // Cancel: nothing more is sent
    await buttons.first().click();
    await expect(line).toHaveCount(0);
    expect((await calls("bots.restart")).length).toBe(1);
    // again, then Restart anyway: the one press that sends interrupt
    await (await menuOf(page, "kami")).getByTestId("row-restart").click();
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
    await (await menuOf(page, "friren")).getByTestId("row-restart").click();
    const line = page.getByTestId("restart-line-friren");
    await expect(line).toHaveAttribute("data-step", "failed");
    await expect(line).toContainText("Friren did not restart.");
    await expect(line.getByTestId("restart-why")).toHaveText("Gateway service restart failed.");
    // nothing is left to cancel after a failure: the app's dismiss word
    await expect(line.getByRole("button")).toHaveText(["Close", "Try again"]);
    await expect(line.getByRole("button", { name: "Cancel" })).toHaveCount(0);
    await shot(page, "failed", theme);
    await line.getByTestId("restart-again").click();
    await expect.poll(async () => (await calls("bots.restart")).length).toBe(2);
  });

  test(`an offline bot: "not connected" with Start in place (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await mock("mock.botStatus", { bot: "friren", status: "offline" });
    await expect(page.getByTestId("bot-friren").getByTestId("bot-sub")).toHaveText("Not connected");
    await expect((await menuOf(page, "friren")).getByRole("menuitem").nth(2)).toHaveText(/^Start/);
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
    // what goes down, in the person's terms, before any press: every bot that restarts with it
    await expect(load).toContainText("Only a restart loads it, and Kami, Friren and Hermes restart with it.");
    const press = load.getByTestId("sheet-load-restart");
    await expect(press).toHaveText("Restart them");
    // visibly an action: outlined like the offline line's Start, not the sentence's colour and weight
    const st = await press.evaluate((el) => {
      const b = getComputedStyle(el);
      const p = getComputedStyle(el.parentElement!);
      return { border: b.borderTopWidth, bg: b.backgroundColor, deco: b.textDecorationLine, w: b.fontWeight, pw: p.fontWeight };
    });
    expect(st.border).toBe("1px");
    expect(st.bg).toBe("rgba(0, 0, 0, 0)");
    expect(st.deco).toBe("none");
    // the title follows the state
    await expect(sheet.getByTestId("sheet-title")).toHaveText("babysit is installed");
    await expect(sheet).not.toContainText("Install babysit?");
    // the body starts with what is new, not the title's words again
    await expect(sheet.getByTestId("sheet-done")).not.toContainText("installed");
    // the press sits on its own line under its sentence at the sheet's own gap, not tight against it
    const gap = await press.evaluate((el) => {
      const p = el.parentElement!;
      const line = parseFloat(getComputedStyle(p).lineHeight);
      return { gap: el.getBoundingClientRect().top - p.getBoundingClientRect().top - line, sheet: parseFloat(getComputedStyle(el.closest(".pl-sheet")!).rowGap) };
    });
    expect(gap.sheet).toBe(14);
    expect(Math.abs(gap.gap - gap.sheet)).toBeLessThanOrEqual(0.5);
    await shot(page, "plugins-restart", theme);
    // the press is the same Restart as the row's: the gateway that serves Kami, every bot on it reads Restarting
    await mock("mock.restart", { bot: "kami", outcome: "slow" });
    await press.click();
    await expect.poll(async () => (await calls("bots.restart")).map((c) => c.params)).toEqual([{ bot: "kami" }]);
    for (const b of ["kami", "friren", "default"])
      await expect(page.getByTestId(`bot-${b}`).getByTestId("bot-time"), b).toHaveText("Restarting");
    await expect(page.getByTestId("bot-omh-tui")).not.toContainText("Restarting");
    await mock("mock.restartDone", { bot: "kami" });
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

for (const theme of ["dark", "light"] as const) {
  test(`Plugins: the reload was enough: ready in the next conversation, no restart offered (${theme})`, async ({ page }) => {
    await setup(page, theme);
    await page.getByTestId("nav-plugins").click();
    await page.getByTestId("plug-tab-browse").click();
    await mock("mock.pluginLoad", { load: "live" });
    await page.getByTestId("plug-install-babysit").click();
    const sheet = page.getByTestId("install-sheet");
    await sheet.getByTestId("sheet-install").click();
    await expect(sheet.getByTestId("sheet-title")).toHaveText("babysit is installed");
    const load = sheet.getByTestId("sheet-load");
    await expect(load).toHaveAttribute("data-load", "live");
    await expect(load).toHaveText("Ready in Kami's next conversation.");
    // the title says it is installed; the body is only what is new
    await expect(sheet.getByTestId("sheet-done")).toHaveText("Ready in Kami's next conversation.");
    await expect(sheet.getByRole("button", { name: /Restart|Load now/ })).toHaveCount(0);
    expect((await calls("bots.restart")).length).toBe(0);
    await shot(page, "plugins-ready", theme);
  });
}

test("one thing running: the sentence says it in the singular, and a line Hermes said nothing about reads honestly", async ({ page }) => {
  await setup(page);
  await mock("mock.restart", { bot: "kami", outcome: "refused", work: [{ kind: "chat", name: null, secs: 65, bot: "kami" }] });
  await (await menuOf(page, "kami")).getByTestId("row-restart").click();
  const line = page.getByTestId("restart-line-kami");
  await expect(line.locator(".rs-t")).toHaveText("Something is running. Restarting now stops it:");
  await expect(line.getByTestId("restart-work").locator(".rs-what")).toHaveText(["Kami: A chat turn"]);
  await expect(line.getByTestId("restart-work").locator(".rs-for")).toHaveText(["1m"]);
  await line.getByTestId("restart-cancel").click();
  // Hermes refused but named nothing readable: one honest line, not a placeholder
  await mock("mock.restart", { bot: "kami", outcome: "refused", work: [{ kind: "work", name: null, secs: null, bot: null }] });
  await (await menuOf(page, "kami")).getByTestId("row-restart").click();
  await expect(line.getByTestId("restart-work").locator("li")).toHaveText(["Hermes did not say what."]);
  await line.getByTestId("restart-cancel").click();
  // two such lines beside a readable one: they share one row with the count
  await mock("mock.restart", { bot: "kami", outcome: "refused", work: [
    { kind: "cron", name: "PR digest", secs: 40, bot: "kami" },
    { kind: "work", name: null, secs: null, bot: null },
    { kind: "work", name: null, secs: null, bot: null },
  ] });
  await (await menuOf(page, "kami")).getByTestId("row-restart").click();
  await expect(line.locator(".rs-t")).toHaveText("3 things are running. Restarting now stops them all:");
  await expect(line.getByTestId("restart-work").locator(".rs-what")).toHaveText(["Kami: Scheduled job PR digest", "2 more things are running"]);
});

const BUSY: Record<string, [string, string]> = {
  ko: ["하던 일이 있어요. 지금 다시 시작하면 멈춰요:", "하던 일이 2개 있어요. 지금 다시 시작하면 모두 멈춰요:"],
  ja: ["実行中の作業があります。いま再起動すると止まります:", "実行中の作業が 2 件あります。いま再起動するとすべて止まります:"],
  zh: ["有一项正在进行的工作。现在重启会中断它：", "有 2 项正在进行的工作。现在重启会把它们全部中断："],
};

for (const lang of ["ko", "ja", "zh"]) {
  test(`the busy sentence agrees with the count in ${lang}`, async ({ page }) => {
    await setup(page, "dark", lang);
    await mock("mock.restart", { bot: "kami", outcome: "refused", work: [{ kind: "cron", name: "PR digest", secs: 40, bot: null }] });
    await (await menuOf(page, "kami")).getByRole("menuitem").nth(2).click();
    const line = page.getByTestId("restart-line-kami");
    await expect(line.locator(".rs-t")).toHaveText(BUSY[lang][0]);
    await line.getByTestId("restart-cancel").click();
    await mock("mock.restart", { bot: "kami", outcome: "refused", work: [
      { kind: "cron", name: "PR digest", secs: 40, bot: null },
      { kind: "work", name: null, secs: 7, bot: null },
    ] });
    await (await menuOf(page, "kami")).getByRole("menuitem").nth(2).click();
    await expect(line.locator(".rs-t")).toHaveText(BUSY[lang][1]);
    await expect(line).not.toContainText(/rs\.[a-z]|\{/);
  });

  test(`the restart words read in ${lang}, with no raw keys`, async ({ page }) => {
    await setup(page, "dark", lang);
    await mock("mock.restart", { bot: "kami", outcome: "refused", work: [{ kind: "cron", name: "PR digest", secs: 40 }] });
    const menu = await menuOf(page, "kami");
    await expect(menu).not.toContainText(/row\.|rs\./);
    await menu.getByRole("menuitem").nth(2).click();
    const line = page.getByTestId("restart-line-kami");
    await expect(line).toBeVisible();
    await expect(line).not.toContainText(/rs\.[a-z]/);
  });
}
