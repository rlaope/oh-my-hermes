// Notifications ring only for what needs the person: a bot turn that ends with an error marks its chat (the row and
// the chat say it failed) but raises no system notification unless Settings > General "Also notify on errors" is on.
// Notifications are recorded into window.__omherNotes by a stand-in Web Notification API.
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<unknown> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<{ result: unknown }>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "n1") res(msg);
    };
    ws.send(JSON.stringify({ id: "n1", op, ...params }));
  });
  ws.close();
  return reply.result;
}

/** kami is open; friren is listed. Notifications go to __omherNotes; the test says whether the window is watched. */
async function open(page: Page, theme: "dark" | "light" = "dark") {
  await page.addInitScript((th) => {
    const w = window as unknown as { __omherNotes: { title: string; body?: string }[]; __watched: boolean; Notification: unknown };
    w.__omherNotes = [];
    w.__watched = true;
    w.Notification = class {
      static permission = "granted";
      static requestPermission = async () => "granted";
      onclick: null | (() => void) = null;
      constructor(title: string, opts: { body?: string } = {}) {
        w.__omherNotes.push({ title, body: opts.body });
      }
      close() {}
    };
    Object.defineProperty(document, "visibilityState", { get: () => (w.__watched ? "visible" : "hidden") });
    document.hasFocus = () => w.__watched;
    localStorage.setItem("omher.roster", JSON.stringify(["kami", "friren"]));
    localStorage.setItem("omher.theme", th);
  }, theme);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bot-friren")).toBeVisible();
}

const notes = (page: Page) => page.evaluate(() => (window as unknown as { __omherNotes: unknown[] }).__omherNotes.slice());
const watched = (page: Page, v: boolean) => page.evaluate((x) => ((window as unknown as { __watched: boolean }).__watched = x), v);

/** A friren turn ends with an error while the person looks elsewhere. */
async function frirenFails(page: Page) {
  await mock("mock.emit", { events: [{ event: "turn.start", bot: "friren" }] });
  await page.waitForTimeout(200);
  await mock("mock.emit", { events: [{ event: "turn.end", bot: "friren", outcome: "error", error: "provider 500" }] });
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("a bot error marks its chat but raises no notification by default", async ({ page }) => {
  await open(page);
  await watched(page, false);
  await frirenFails(page);
  // the chat says the turn failed
  await page.getByTestId("bot-friren").click();
  await expect(page.getByText("Failed").first()).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(300);
  expect(await notes(page)).toEqual([]);
});

test("Also notify on errors brings the error notification back", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-settings").click();
  const seg = page.getByTestId("notify-errors-seg");
  await expect(seg.getByRole("radio", { name: "Off" })).toHaveAttribute("aria-checked", "true");
  await seg.getByRole("radio", { name: "On" }).click();
  await page.getByRole("button", { name: "Close settings" }).click();
  await watched(page, false);
  await frirenFails(page);
  await expect.poll(() => notes(page), { timeout: 10_000 }).toEqual([expect.objectContaining({ title: "Friren stopped with an error" })]);
});

test("an empty question followed by a texted one within 8 s rings once", async ({ page }) => {
  await open(page);
  await watched(page, false);
  await mock("mock.emit", { events: [{ event: "clarify.request", bot: "friren", request_id: "q0", question: "" }] });
  await page.waitForTimeout(1500);
  await mock("mock.emit", { events: [{ event: "clarify.request", bot: "friren", request_id: "q1", question: "Which branch should I deploy? main or next." }] });
  await expect.poll(() => notes(page), { timeout: 10_000 }).toEqual([{ title: "Friren has a question", body: "Which branch should I deploy?" }]);
  await page.waitForTimeout(8000);
  expect(await notes(page)).toHaveLength(1);
});

for (const theme of ["dark", "light"] as const) {
  test(`shot: Settings notifications, ${theme}`, async ({ page }) => {
    test.skip(!SHOTS, "OMHER_SHOTS not set");
    await page.setViewportSize({ width: 1200, height: 800 });
    await open(page, theme);
    await page.getByTestId("nav-settings").click();
    const row = page.getByTestId("notify-errors-seg");
    await row.scrollIntoViewIfNeeded();
    await expect(row).toBeVisible();
    mkdirSync(SHOTS, { recursive: true });
    await page.waitForTimeout(300);
    await page.screenshot({ path: join(SHOTS, `knotify-settings-${theme}.png`), animations: "disabled", caret: "initial" });
  });
}
