// Shots for a person who has Hermes but not oh-my-hermes (`omh`), owner design of 13:25 KST: the sidebar's "!" left
// of the top row's + (at rest), its popover (as it opens, running, done, failed), the SESSIONS + menu with the
// Hermes row and "Add oh-my-hermes", a Hermes session in a folder, and an empty chat with no first-run panel.
// The mock host plays "Hermes, no omh" through `__omherMockNoOmh`; `__OMHER_GATE__` stands in for the shell's fixed
// installer (nothing is installed). One fresh page per shot. Run with OMHER_SHOTS=<dir> OMHER_SHOT_TAG=before|after.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "s1", op, ...params }));
  });
  ws.close();
}

test.beforeEach(async ({ page }) => {
  test.skip(!SHOTS, "OMHER_SHOTS unset");
  mkdirSync(SHOTS, { recursive: true });
  await mock("mock.reset");
  await page.setViewportSize({ width: 1180, height: 760 });
});

type Run = "hold" | "done" | "failed";

/** Hermes without omh. The installer stand-in plays a few lines, then holds (running), exits 0 (`omh` is then found)
 *  or exits 1 after a failure line. `fresh`: a first launch (no `omher.onboarded`). */
async function open(page: Page, theme: string, o: { run?: Run; fresh?: boolean } = {}) {
  await page.addInitScript(
    ([t, run, fresh]) => {
      const w = window as unknown as Record<string, unknown>;
      localStorage.setItem("omher.theme", t as string);
      localStorage.removeItem("omher.sessions.recent");
      localStorage.removeItem("omher.omhOffer.hidden");
      if (fresh) localStorage.removeItem("omher.onboarded");
      w.__omherPickFolder = "/Users/you/code/web-app";
      w.__omherMockAgents = ["claude", "codex"];
      w.__omherMockNoOmh = true;
      const lines =
        run === "failed"
          ? ["[ok] Hermes Agent found", "Installing oh-my-hermes 4.9.2", "[failed] could not reach github.com (curl: (6))"]
          : ["[ok] Hermes Agent found", "Installing oh-my-hermes 4.9.2", "Downloading the release wheel"];
      w.__OMHER_GATE__ = {
        status: async () => ({ state: "ready" }),
        retry: async () => {},
        installCommand: async () => "",
        install: async (onEvent: (e: unknown) => void) => {
          for (const text of lines) onEvent({ kind: "line", text });
          if (run === "hold") await new Promise(() => {});
          await new Promise((r) => setTimeout(r, 150));
          const code = run === "failed" ? 1 : 0;
          onEvent({ kind: "exit", code });
          if (code === 0) {
            w.__omherMockNoOmh = false;
            (w.__omherMockAgents as string[]).push("omh");
          }
          return code;
        },
      };
    },
    [theme, o.run ?? "hold", !!o.fresh] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

const shot = async (page: Page, what: string, theme: string) => {
  await page.mouse.move(1170, 750);
  await page.waitForTimeout(350);
  await page.screenshot({ path: join(SHOTS, `hermes-only-${what}-${TAG}-${theme}.png`), animations: "disabled" });
};

const settle = (page: Page) =>
  page.waitForFunction(() => [...document.querySelectorAll(".ui-pop")].every((p) => p.getAnimations().every((a) => a.playState !== "running")));

/** Opens the "!" popover (after) or does nothing (before: there is no "!"). */
async function openNotice(page: Page): Promise<boolean> {
  const b = page.getByTestId("omh-notice");
  if (!(await b.count())) return false;
  await b.click();
  await expect(page.getByTestId("omh-pop")).toBeVisible();
  return true;
}

for (const theme of ["dark", "light"] as const) {
  test(`header icon ${theme}`, async ({ page }) => {
    await open(page, theme);
    await page.waitForTimeout(300);
    await shot(page, "header-icon", theme);
  });

  test(`header popover ${theme}`, async ({ page }) => {
    await open(page, theme);
    if (await openNotice(page)) await settle(page);
    await shot(page, "header-popover", theme);
  });

  for (const run of ["hold", "done", "failed"] as const) {
    const name = run === "hold" ? "running" : run;
    test(`header ${name} ${theme}`, async ({ page }) => {
      await open(page, theme, { run });
      if (await openNotice(page)) {
        await page.getByTestId("omh-pop-install").click();
        if (run === "hold") await expect(page.getByTestId("omh-pop-log")).toContainText("Downloading");
        if (run === "done") {
          await expect(page.getByTestId("omh-notice")).toHaveCount(0);
          // the + menu's row now reads oh-my-hermes and the offer line is gone
          await page.getByTestId("session-new").click();
          await expect(page.getByTestId("session-agent-omh")).toContainText("oh-my-hermes");
          await expect(page.getByTestId("session-add-omh")).toHaveCount(0);
        }
        if (run === "failed") await expect(page.getByTestId("omh-pop-install")).toHaveText("Install again");
        await settle(page);
      }
      await shot(page, `header-${name}`, theme);
    });
  }

  test(`menu ${theme}`, async ({ page }) => {
    await open(page, theme);
    await page.getByTestId("session-new").click();
    await expect(page.getByTestId("session-menu")).toBeVisible();
    await settle(page);
    await shot(page, "menu", theme);
  });

  test(`session ${theme}`, async ({ page }) => {
    await open(page, theme);
    await page.getByTestId("session-new").click();
    const row = page.getByTestId("session-agent-omh");
    await expect(row).toBeVisible();
    if ((await row.getAttribute("aria-disabled")) === "true") {
      // before: the row cannot be picked, so there is no session to show
      await row.hover();
      await shot(page, "session", theme);
      return;
    }
    await row.click();
    await expect(page.getByTestId("session-folder")).toBeVisible();
    await page.getByTestId("session-folder").click();
    await page.getByTestId("session-choose").click();
    await expect(page.getByTestId("session-folder")).toContainText("web-app");
    await page.getByTestId("composer").fill("What is in this folder?");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("session-agent")).toBeVisible();
    await expect(page.getByTestId("session-status")).toHaveText("Ready");
    await shot(page, "session", theme);
  });

  test(`empty chat ${theme}`, async ({ page }) => {
    await mock("mock.clearHistory", { bot: "friren" });
    await open(page, theme, { fresh: true });
    await page.getByTestId("bot-friren").click();
    await expect(page.locator('[data-pane="friren"]').getByTestId("composer")).toBeVisible();
    await shot(page, "empty-chat", theme);
  });
}
