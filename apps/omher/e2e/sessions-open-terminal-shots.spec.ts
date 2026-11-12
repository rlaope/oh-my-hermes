// Shots and fit checks for the New session Chat | Terminal choice (dark and light). Run with
// OMHER_SHOTS=<dir>; without it only the fit checks run.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function open(page: Page, theme: string) {
  await page.addInitScript((t) => {
    localStorage.setItem("omher.theme", t);
    localStorage.removeItem("omher.sessions.recent");
    localStorage.removeItem("omher.sessions.open");
    localStorage.removeItem("omher.resume");
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
    w.__omherPickFolder = "/Users/you/code/web-app";
    w.__omherMockAgents = ["claude", "codex", "omh", "dsh", "grok", "opencode"];
  }, theme);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function draft(page: Page, agent: string) {
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await expect(page.getByTestId("session-way")).toBeVisible();
}

/** The control, the agent and the folder chip do not overlap and nothing in the composer is clipped or off screen. */
async function fits(page: Page) {
  const r = await page.evaluate(() => {
    const box = (sel: string) => {
      const e = document.querySelector<HTMLElement>(sel);
      if (!e) return null;
      const b = e.getBoundingClientRect();
      return { x: b.x, y: b.y, w: b.width, h: b.height, r: b.right, b: b.bottom };
    };
    const comp = document.querySelector<HTMLElement>("[data-testid=composer-box]")!;
    const kids = [...comp.querySelectorAll<HTMLElement>(".ss-way-o, [data-testid=session-agent-fixed], [data-testid=session-go]")].map((e) => e.getBoundingClientRect());
    const cb = comp.getBoundingClientRect();
    return {
      way: box("[data-testid=session-way]"),
      agent: box("[data-testid=session-agent-fixed]"),
      folder: box("[data-testid=session-folder]"),
      composer: { x: cb.x, r: cb.right, b: cb.bottom },
      inside: kids.every((k) => k.x >= cb.x - 0.5 && k.right <= cb.right + 0.5),
      clipped: comp.scrollWidth > comp.clientWidth + 1,
      vw: window.innerWidth,
      vh: window.innerHeight,
    };
  });
  expect(r.way && r.agent && r.folder).toBeTruthy();
  const apart = (a: { x: number; r: number }, b: { x: number; r: number }) => a.r <= b.x + 0.5 || b.r <= a.x + 0.5;
  expect(apart(r.way!, r.agent!)).toBe(true);
  // the folder chip sits under the box, never over the control
  expect(r.folder!.y).toBeGreaterThanOrEqual(r.composer.b - 1);
  expect(r.inside).toBe(true);
  expect(r.clipped).toBe(false);
  expect(r.way!.r).toBeLessThanOrEqual(r.vw);
  expect(r.folder!.b).toBeLessThanOrEqual(r.vh);
}

for (const theme of ["dark", "light"] as const) {
  test.describe(theme, () => {
    test.use({ colorScheme: theme });

    test(`the choice fits at 1280x820 and 900x700 (${theme})`, async ({ page }) => {
      await open(page, theme);
      for (const size of [{ width: 1280, height: 820 }, { width: 900, height: 700 }]) {
        await page.setViewportSize(size);
        for (const agent of ["claude", "omh", "opencode"]) {
          await draft(page, agent);
          await fits(page);
          await page.getByTestId("session-way-terminal").click();
          await fits(page);
        }
      }
    });

    test(`shots (${theme})`, async ({ page }) => {
      test.skip(!SHOTS, "no shot folder");
      mkdirSync(SHOTS, { recursive: true });
      // staged shots carry no bot named after the product: the default profile shows as "Juno" (mock.reset, before
      // each test, puts the name back)
      await mock("bots.rename", { bot: "default", name: "Juno" });
      const shot = async (what: string) => {
        await page.mouse.move(640, 60);
        await page.waitForTimeout(350);
        await page.screenshot({ path: join(SHOTS, `open-term-${what}-${theme}.png`), animations: "disabled" });
      };
      const neutral = () => page.locator("[data-testid=header]").click({ position: { x: 600, y: 10 } });
      await open(page, theme);

      await draft(page, "claude");
      await neutral();
      await shot("draft-chat");
      await page.getByTestId("session-way-terminal").click();
      await neutral();
      await shot("draft-terminal");

      await page.getByTestId("session-go").click();
      await expect(page.locator(".xterm-rows")).toContainText("(mock)");
      await page.locator(".xterm-helper-textarea").focus();
      await page.keyboard.type("hello from the terminal");
      await page.keyboard.press("Enter");
      await expect(page.locator(".xterm-rows")).toContainText("you said: hello from the terminal");
      await neutral();
      await shot("running-claude");

      // a second folder for the second session
      await page.evaluate(() => ((window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/api-server"));
      await draft(page, "opencode");
      await page.getByTestId("session-way-terminal").click();
      await page.getByTestId("session-go").click();
      await expect(page.locator(".xterm-rows")).toContainText("opencode");
      await neutral();
      await shot("running-opencode");

      // the first session ends with its program
      await page.locator("[data-testid=session-list] .ss-row").filter({ hasText: "web-app" }).locator(".ss-open").click();
      await page.locator(".xterm-helper-textarea").focus();
      await page.keyboard.type("exit");
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("session-ended")).toBeVisible();
      await neutral();
      await shot("ended");

      await draft(page, "dsh");
      await neutral();
      await shot("dsh-disabled");
    });
  });
}
