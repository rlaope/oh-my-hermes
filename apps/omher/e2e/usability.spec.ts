// Usability: notifications while omher is in the background, keyboard shortcuts, the risk line on an
// approval card, and "Soon" tags on features that are not in this version.
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
      if (msg.id === "u1") res(msg);
    };
    ws.send(JSON.stringify({ id: "u1", op, ...params }));
  });
  ws.close();
  return reply.result;
}

/** Replace the Web Notification API with a recorder, and let the test say whether the window is watched. */
async function fakeNotifications(page: Page) {
  await page.addInitScript(() => {
    const w = window as any;
    w.__notes = [];
    w.__watched = true;
    class FakeNotification {
      static permission = "granted";
      static requestPermission = async () => "granted";
      onclick: null | (() => void) = null;
      constructor(title: string, opts: { body?: string; tag?: string } = {}) {
        w.__notes.push({ title, body: opts.body, tag: opts.tag, n: this });
      }
      close() {}
    }
    w.Notification = FakeNotification;
    Object.defineProperty(document, "visibilityState", { get: () => (w.__watched ? "visible" : "hidden") });
    document.hasFocus = () => w.__watched;
  });
}

const notes = (page: Page) => page.evaluate(() => (window as any).__notes.map((n: any) => ({ title: n.title, body: n.body })));
const watched = (page: Page, v: boolean) => page.evaluate((x) => ((window as any).__watched = x), v);

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
}

async function send(page: Page, text: string) {
  await page.getByTestId("composer").fill(text);
  await page.getByTestId("composer").press("Enter");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a background answer and an approval raise notifications; a watched chat raises none", async ({ page }) => {
  await fakeNotifications(page);
  await open(page);

  // watching the chat: the answer arrives, nothing pops up
  await send(page, "check the 502s");
  await expect(page.getByTestId("bubble-bot").filter({ hasText: "keep-alive" }).first()).toBeVisible({ timeout: 10_000 });
  expect(await notes(page)).toEqual([]);

  // in the background: the answer notifies with the bot's name and a plain gist
  await watched(page, false);
  await send(page, "check the 502s again");
  await expect.poll(() => notes(page), { timeout: 10_000 }).toEqual([
    expect.objectContaining({ title: "Kami", body: expect.stringMatching(/keep-alive/) }),
  ]);
  const body = (await notes(page))[0].body as string;
  expect(body).not.toMatch(/[`*#]/);

  // an approval waiting in the background notifies too, naming the command
  await send(page, "/approve clean the build");
  await expect.poll(async () => (await notes(page)).map((n: any) => n.title), { timeout: 10_000 }).toContain(
    "Kami needs your approval",
  );
  expect((await notes(page)).find((n: any) => n.title === "Kami needs your approval").body).toBe("rm -rf ./build");
});

test("Notify me can be turned off in Settings and stays off", async ({ page }) => {
  await fakeNotifications(page);
  await open(page);
  await page.getByTestId("nav-settings").click();
  const seg = page.getByTestId("notify-seg");
  await expect(seg.getByRole("radio", { name: "On" })).toHaveAttribute("aria-checked", "true");
  await seg.getByRole("radio", { name: "Off" }).click();
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("notify-seg").getByRole("radio", { name: "Off" })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("button", { name: "Close settings" }).click();

  await watched(page, false);
  await send(page, "check the 502s");
  await expect(page.getByTestId("bubble-bot").filter({ hasText: "keep-alive" }).first()).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(300);
  expect(await notes(page)).toEqual([]);
});

test("shortcuts: Mod+2 opens the second bot, Mod+K searches, Mod+. toggles Details, Mod+, opens Settings", async ({ page }) => {
  await open(page);
  // the page picks Cmd or Ctrl from navigator.platform, so press the one it expects
  const mac = await page.evaluate(() => /Mac/.test(navigator.platform));
  const key = mac ? "Meta" : "Control";

  await page.keyboard.press(`${key}+2`);
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await page.keyboard.press(`${key}+1`);
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");

  await page.keyboard.press(`${key}+k`);
  await expect(page.getByRole("searchbox", { name: "Search bots" })).toBeFocused();
  await page.keyboard.press("Escape");

  const details = page.getByTestId("details");
  await page.keyboard.press(`${key}+.`);
  await expect.poll(async () => Math.round((await details.boundingBox())?.width ?? 0)).toBe(300);
  await page.keyboard.press(`${key}+.`);
  await expect.poll(async () => Math.round((await details.boundingBox())?.width ?? 0)).toBeLessThan(2);

  await page.keyboard.press(`${key}+,`);
  await expect(page.getByTestId("settings-view")).toBeVisible();
  await expect(page.getByTestId("shortcuts")).toContainText(mac ? "⌘K" : "Ctrl+K");
  await page.keyboard.press(`${key}+,`);
  await expect(page.getByTestId("settings-view")).toHaveCount(0);
});

test("Esc stops a running answer, but not while the search field has focus", async ({ page }) => {
  await open(page);
  await send(page, "check the 502s");
  await expect(page.getByTestId("stop")).toBeVisible();
  // Esc inside the search field only clears the search
  await page.getByRole("searchbox", { name: "Search bots" }).focus();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("stop")).toBeVisible();
  expect((await mock("mock.calls")).calls.filter((c: any) => c.op === "chat.interrupt")).toEqual([]);
  // anywhere else it stops the turn
  await page.getByTestId("timeline").click({ position: { x: 20, y: 20 } });
  await page.keyboard.press("Escape");
  await expect.poll(async () => (await mock("mock.calls")).calls.filter((c: any) => c.op === "chat.interrupt").length).toBe(1);
});

test("a risky command gets a warning line; the buttons stay the same", async ({ page }) => {
  await open(page);
  await send(page, "/approve clean the build");
  const card = page.getByTestId("card-approval");
  await expect(card).toBeVisible();
  await expect(card.getByTestId("card-risk")).toHaveText(/Deletes files and folders/);
  await expect(card).toHaveClass(/\brisky\b/);
  const order = await card.getByRole("button").allTextContents();
  expect(order.slice(0, 3)).toEqual(["Deny", "Allow once", "Allow for session"]);
});

test("features not in this version say Soon", async ({ page }) => {
  await open(page);
  for (const id of ["nav-automations", "nav-plugins"]) {
    const b = page.getByTestId(id);
    await expect(b).toBeDisabled();
    await expect(b).toContainText("Soon");
  }
});

test("the bot's face sits beside its bubbles, once per run of bot messages", async ({ page }) => {
  await page.goto("/");
  const bot = page.getByTestId("bubble-bot").first();
  await expect(bot.locator("img.msg-face")).toBeVisible();
  // a reply right after another bot bubble keeps the indent but hides the face
  const faces = page.locator('[data-testid="bubble-bot"] img.msg-face:not(.blank)');
  expect(await faces.count()).toBeGreaterThan(0);
  // the thread is wider than before (920px cap) so a 1440px window is not a narrow centred column
  await page.setViewportSize({ width: 1440, height: 900 });
  const w = await page.locator(".thread > *").first().evaluate((e) => e.getBoundingClientRect().width);
  expect(w).toBeGreaterThan(760);
});
