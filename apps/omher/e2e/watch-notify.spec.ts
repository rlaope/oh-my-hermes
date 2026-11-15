// Watch results reach the person: an automation of a bot that is not open answers -> one notification
// "<bot> · <watch>", unread 1, one Dock badge call; a silent run leaves nothing; 40 answers that came in while
// omher was closed -> one summary notification and unread 40. "Not useful" sends exactly one chat message.
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
      if (msg.id === "w1") res(msg);
    };
    ws.send(JSON.stringify({ id: "w1", op, ...params }));
  });
  ws.close();
  return reply.result;
}

/** Notifications and Dock badge calls are recorded; kami is open, friren is listed but not open. `seen`: when the
 *  person last saw friren's automation answers (unix s), or none recorded. */
async function setup(page: Page, seen?: number) {
  await page.addInitScript((seenAt) => {
    const w = window as any;
    w.__notes = [];
    w.__badgeCalls = [];
    let badge: number | undefined;
    Object.defineProperty(w, "__omherBadge", {
      configurable: true,
      get: () => badge,
      set: (v: number) => {
        badge = v;
        w.__badgeCalls.push(v);
      },
    });
    class FakeNotification {
      static permission = "granted";
      static requestPermission = async () => "granted";
      onclick: null | (() => void) = null;
      constructor(title: string, opts: { body?: string; tag?: string } = {}) {
        w.__notes.push({ title, body: opts.body, n: this });
      }
      close() {}
    }
    w.Notification = FakeNotification;
    localStorage.setItem("omher.roster", JSON.stringify(["kami", "friren"]));
    if (typeof seenAt === "number") localStorage.setItem("omher.watchSeen", JSON.stringify({ friren: seenAt }));
  }, seen ?? null);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bot-friren")).toBeVisible();
}

const notes = (page: Page) => page.evaluate(() => (window as any).__notes.map((n: any) => ({ title: n.title, body: n.body })));
const badgeCalls = (page: Page) => page.evaluate(() => [...(window as any).__badgeCalls]);
const unread = (page: Page, bot: string) => page.getByTestId(`bot-${bot}`).getByTestId("unread");

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a hit on a bot that is not open: one notification, unread 1, one badge call; click opens that bot", async ({ page }) => {
  await setup(page);
  await expect.poll(() => badgeCalls(page)).toEqual([0]);
  await mock("mock.watchRun", { bot: "friren", name: "deploys", kind: "hit", text: "**Deploy failed** on main\nsecond line" });
  await expect.poll(() => notes(page)).toEqual([{ title: "Friren · deploys", body: "Deploy failed on main" }]);
  await expect(unread(page, "friren")).toHaveText("1");
  await expect.poll(() => badgeCalls(page)).toEqual([0, 1]);
  await page.waitForTimeout(300);
  expect(await notes(page)).toHaveLength(1); // the delivered run's routine.ran adds no second note

  // the notification opens friren: the answer sits under one "Watch · deploys" line, no bubble from the person
  await page.evaluate(() => (window as any).__notes[0].n.onclick());
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("watch-line")).toHaveCount(1);
  await expect(page.getByTestId("watch-line")).toContainText(/Watch · deploys · \d\d:\d\d/);
  await expect(page.getByTestId("bubble-bot").filter({ hasText: "Deploy failed" })).toHaveCount(1);
  await expect(page.getByTestId("bubble-user").filter({ hasText: "Cronjob" })).toHaveCount(0);
  await expect(page.getByTestId("routine-line")).toHaveCount(0);
  await expect.poll(() => badgeCalls(page)).toEqual([0, 1, 0]);

  // "Not useful" tells the bot once
  await page.getByTestId("watch-not-useful").click();
  await expect(page.getByTestId("watch-not-useful")).toBeDisabled();
  const sends = (await mock("mock.calls")).calls.filter((c: any) => c.op === "chat.send");
  expect(sends).toHaveLength(1);
  expect(sends[0].params.bot).toBe("friren");
  expect(sends[0].params.text).toContain('"deploys"');
  expect(sends[0].params.text).toContain("**Deploy failed** on main second line"); // quoted verbatim
});

test("a silent run: no notification, no unread, no badge call, no line", async ({ page }) => {
  await setup(page);
  await expect.poll(() => badgeCalls(page)).toEqual([0]);
  await mock("mock.watchRun", { bot: "friren", name: "deploys", kind: "silent" });
  await mock("mock.watchRun", { bot: "friren", name: "deploys", kind: "silent" });
  await page.waitForTimeout(500);
  expect(await notes(page)).toEqual([]);
  await expect(unread(page, "friren")).toHaveCount(0);
  expect(await badgeCalls(page)).toEqual([0]);
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("timeline")).toBeVisible();
  await expect(page.getByTestId("watch-line")).toHaveCount(0);
  await expect(page.getByTestId("routine-line")).toHaveCount(0);
});

test("40 answers that came in while omher was closed: one summary notification, unread 40", async ({ page }) => {
  await mock("mock.watchQueued", { bot: "friren", name: "deploys", n: 40 });
  await setup(page, 1);
  await expect(unread(page, "friren")).toHaveText("40");
  await expect.poll(() => notes(page)).toEqual([{ title: "Friren: 40 watch alerts", body: expect.stringContaining("match 40") }]);
  await expect.poll(() => badgeCalls(page)).toContain(40);
  await page.waitForTimeout(300);
  expect(await notes(page)).toHaveLength(1);
});

test("a first start with no record of what was seen does not flood", async ({ page }) => {
  await mock("mock.watchQueued", { bot: "friren", name: "deploys", n: 5 });
  await setup(page);
  await page.waitForTimeout(500);
  expect(await notes(page)).toEqual([]);
  await expect(unread(page, "friren")).toHaveCount(0);
});
