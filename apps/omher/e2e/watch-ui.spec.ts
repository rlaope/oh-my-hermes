// Channel watches on the Automations page: collector jobs show as Watch rows (where, what, last check), a watch the
// bot can't read says "Can't read this channel" and why and is never green; Pause/Resume/Delete go through the
// bot's own cron.manage; "+ New watch" sends one sentence to that bot's chat and opens it, and makes no job.
// "Not useful" on a watch result line sends one chat message naming the watch and quoting the item. Four languages,
// dark and light; screenshots go to the scratch folder named by CW_SHOTS.
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.CW_SHOTS || "";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "u1") res(msg);
    };
    ws.send(JSON.stringify({ id: "u1", op, ...params }));
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

const OK = "w0a1b2c3d4e5"; // friren · og-outage, Slack, ok
const PAUSED = "w1b2c3d4e5f6"; // kami · deploy-talk, Discord, paused
const UNREAD = "w2c3d4e5f6a7"; // kami · support-escalations, Slack, not readable

async function openAutomations(page: Page, opts: { lang?: string; theme?: string } = {}) {
  await page.addInitScript(
    ({ lang, theme }) => {
      localStorage.setItem("omher.roster", JSON.stringify(["kami", "friren"]));
      if (lang) localStorage.setItem("omher.lang", lang);
      if (theme) localStorage.setItem("omher.theme", theme);
    },
    { lang: opts.lang ?? "", theme: opts.theme ?? "" },
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("nav-automations").click();
  await expect(page.getByTestId("auto-list")).toBeVisible();
  await expect(page.getByTestId(`auto-row-${UNREAD}`)).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
  await mock("mock.watches");
});

test("watch rows: where and what, ok, paused, and not readable never green", async ({ page }) => {
  await openAutomations(page);
  const ok = page.getByTestId(`auto-row-${OK}`);
  await expect(ok).toHaveAttribute("data-watch", "ok");
  await expect(ok.getByTestId("watch-tag")).toHaveText("Watch");
  await expect(ok.getByTestId("watch-desc")).toHaveText("Slack #og, #og-alerts · posts about an outage or an error");
  await expect(ok.locator(".au-st")).toHaveAttribute("data-status", "ok");
  await expect(ok.locator(".au-st")).toContainText("checked");
  await expect(ok.locator(".au-sched")).toHaveText("every 5 min");

  const paused = page.getByTestId(`auto-row-${PAUSED}`);
  await expect(paused).toHaveAttribute("data-watch", "paused");
  await expect(paused.getByTestId("watch-desc")).toContainText("Discord #deploys");
  await expect(paused.locator(".au-st")).toHaveAttribute("data-status", "paused");
  await expect(paused.getByTestId(`auto-toggle-${PAUSED}`)).toHaveAttribute("aria-checked", "false");

  const bad = page.getByTestId(`auto-row-${UNREAD}`);
  await expect(bad).toHaveAttribute("data-watch", "not_readable");
  await expect(bad.locator(".au-st")).toHaveAttribute("data-status", "failed");
  await expect(bad.locator(".au-st")).toHaveText("Can't read this channel");
  const dot = await bad.locator(".au-st i").evaluate((el) => getComputedStyle(el).backgroundColor);
  const okDot = await ok.locator(".au-st i").evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(dot).not.toBe(okDot);

  // the detail panel says why, by the collector's reason
  await bad.getByRole("button").first().click();
  await expect(page.getByTestId("watch-unreadable")).toContainText("Can't read this channel");
  await expect(page.getByTestId("watch-reason")).toContainText("#support-vip");
  await expect(page.getByTestId("watch-reason")).toContainText("Invite the bot");
  await expect(page.getByTestId("watch-where")).toHaveText("Slack #support-vip");
  await expect(page.getByTestId("watch-what")).toHaveText("a customer asks to escalate");
  await expect(page.getByTestId("watch-checks")).toContainText("tried");
  await expect(page.getByTestId("watch-checks")).not.toContainText("no alerts yet");

  await ok.getByRole("button").first().click();
  await expect(page.getByTestId("watch-unreadable")).toHaveCount(0);
  await expect(page.getByTestId("watch-checks")).toContainText("last alert");
  // ordinary jobs keep their own row
  await expect(page.getByTestId("auto-row-a1f0c2d9e801").getByTestId("watch-tag")).toHaveCount(0);
});

test("Pause, Resume and Delete a watch go through the bot's cron.manage only", async ({ page }) => {
  await openAutomations(page);
  await page.getByTestId(`auto-toggle-${OK}`).click();
  await expect(page.getByTestId(`auto-row-${OK}`)).toHaveAttribute("data-watch", "paused");
  await page.getByTestId(`auto-toggle-${PAUSED}`).click();
  await expect(page.getByTestId(`auto-row-${PAUSED}`)).toHaveAttribute("data-watch", "ok");

  await page.getByTestId(`auto-row-${UNREAD}`).getByRole("button").first().click();
  await page.getByTestId("auto-pause").click();
  await expect(page.getByTestId(`auto-row-${UNREAD}`)).toHaveAttribute("data-watch", "paused");
  await page.getByTestId("auto-delete").click();
  await page.getByTestId("auto-confirm-delete").click();
  await expect(page.getByTestId(`auto-row-${UNREAD}`)).toHaveCount(0);

  const ops = (await calls("automations.")).filter((c) => c.op !== "automations.list").map((c) => [c.op, c.params.bot, c.params.job]);
  expect(ops).toEqual([
    ["automations.pause", "friren", OK],
    ["automations.resume", "kami", PAUSED],
    ["automations.pause", "kami", UNREAD],
    ["automations.remove", "kami", UNREAD],
  ]);
  expect(await submitted("kami")).toEqual([]);
  expect(await submitted("friren")).toEqual([]);
});

test("+ New watch sends one sentence to that bot's chat, opens it, and makes no job", async ({ page }) => {
  await openAutomations(page);
  const before = (await mock("automations.list")).automations.length;
  await page.getByTestId("watch-new").click();
  await expect(page.getByTestId("watch-form-send")).toBeDisabled();
  await page.getByTestId("watch-form-bot").click();
  await page.getByRole("option", { name: /Friren/ }).click();
  await page.getByTestId("watch-form-platform").getByText("Discord").click();
  await page.getByTestId("watch-form-channel").fill("#deploys");
  await page.getByTestId("watch-form-what").fill("someone asks for a deploy");
  await page.getByTestId("watch-form-every").getByText("every 15 min").click();
  const sentence = "Watch Discord #deploys and tell me first when a post is about: someone asks for a deploy. Check every 15 min.";
  await expect(page.getByTestId("watch-form-sentence")).toHaveText(sentence);
  await page.getByTestId("watch-form-send").click();

  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").last()).toContainText("Watch Discord #deploys");
  await expect.poll(() => submitted("friren")).toEqual([sentence]);
  expect(await submitted("kami")).toEqual([]);
  const writes = (await calls("automations.")).filter((c) => c.op !== "automations.list");
  expect(writes).toEqual([]);
  expect((await mock("automations.list")).automations.length).toBe(before);
});

test("Not useful on a watch result sends one message naming the watch and quoting the item", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("omher.roster", JSON.stringify(["kami", "friren"])));
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await mock("mock.watchRun", { bot: "kami", name: "og-outage", kind: "hit", text: "og down: `__init__` failed in #og\nsee the thread" });
  await expect(page.getByTestId("watch-line")).toHaveCount(1);
  await page.getByTestId("watch-not-useful").click();
  await expect(page.getByTestId("watch-not-useful")).toBeDisabled();
  await page.waitForTimeout(300);
  const sent = await submitted("kami");
  expect(sent).toHaveLength(1);
  expect(sent[0]).toBe('The watch "og-outage" flagged this, but it was not useful: "og down: `__init__` failed in #og see the thread". Flag less like it from now on.');
  expect((await calls("chat.send")).length).toBe(1);
});

for (const [lang, unreadable, tag, note] of [
  ["en", "Can't read this channel", "Watch", "every 15 minutes"],
  ["ko", "이 채널을 읽을 수 없어요", "모니터링", "15분마다"],
  ["ja", "このチャンネルを読めません", "ウォッチ", "15 分ごと"],
  ["zh", "无法读取此频道", "监视", "每 15 分钟"],
] as const) {
  for (const theme of ["dark", "light"] as const) {
    test(`watch rows in ${lang}, ${theme}: no raw keys, nothing clipped`, async ({ page }) => {
      /** Text that overflows its box without an ellipsis, among the watch parts of the page. */
      const hardCut = () =>
        page.evaluate(() =>
          [...document.querySelectorAll<HTMLElement>(".au-st-t, .au-unread, .au-unread *, .au-f-say, .au-form .pg-btn, .au-f .mseg button, .au-d-top h2")]
            .filter((el) => {
              const r = el.getBoundingClientRect();
              const clip = el.closest(".au-row, .au-form, .au-detail")?.getBoundingClientRect();
              const cut = el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).textOverflow !== "ellipsis";
              return cut || (clip ? r.right > clip.right + 1 : false);
            })
            .map((el) => `${el.className}: ${el.textContent}`),
        );
      const shot = async (name: string) => {
        if (!SHOTS) return;
        mkdirSync(SHOTS, { recursive: true });
        await page.screenshot({ path: join(SHOTS, `${name}.png`), animations: "disabled" });
      };
      await openAutomations(page, { lang, theme });
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      const bad = page.getByTestId(`auto-row-${UNREAD}`);
      await expect(bad.locator(".au-st")).toHaveText(unreadable);
      await expect(page.getByTestId(`auto-row-${OK}`).getByTestId("watch-tag")).toHaveText(tag);
      await bad.getByRole("button").first().click();
      await expect(page.getByTestId("watch-unreadable")).toContainText(unreadable);
      // the panel's hint is a watch example, not the generic "move it to 10:00"
      await expect(page.getByTestId("auto-note")).toContainText(note);
      await expect(page.getByTestId("auto-note")).not.toContainText("10");
      await bad.scrollIntoViewIfNeeded();
      expect(await hardCut()).toEqual([]);
      await shot(`watch-${lang}-${theme}`);
      if (lang === "en" || lang === "ko") {
        await page.setViewportSize({ width: 900, height: 600 });
        await bad.scrollIntoViewIfNeeded();
        await expect(page.getByTestId("auto-detail")).toBeVisible();
        expect(await hardCut()).toEqual([]);
        await shot(`watch-${lang}-${theme}-900x600`);
      }
      // + New watch closes the panel so the form has the page's width
      await page.getByTestId("watch-new").click();
      await expect(page.getByTestId("auto-detail")).toHaveCount(0);
      await page.getByTestId("watch-form-channel").fill("#og");
      await page.getByTestId("watch-form-what").fill(lang === "en" ? "an outage or an error" : "장애나 에러");
      await page.getByTestId("watch-form-send").scrollIntoViewIfNeeded();
      await expect(page.getByTestId("watch-form-send")).toBeInViewport();
      const body = await page.getByTestId("automations").innerText();
      expect(body).not.toMatch(/\b(watch|auto)\.[a-zA-Z.]+\b/);
      expect(body).not.toMatch(/\{[a-z]+\}/);
      expect(await hardCut()).toEqual([]);
      if (lang === "en" || lang === "ko") await shot(`watch-form-${lang}-${theme}-900x600`);
    });
  }
}
