// Shots for a person who has Hermes but not oh-my-hermes (`omh`): the SESSIONS + menu, a Hermes session in a folder,
// the quiet offer to add oh-my-hermes (running), and the first-run cards. The mock host plays "Hermes, no omh" through
// `__omherMockNoOmh`; `__OMHER_GATE__` stands in for the shell's fixed installer (nothing is installed).
// One fresh page per shot. Run with OMHER_SHOTS=<dir> OMHER_SHOT_TAG=before|after.
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

/** Hermes without omh; the installer stand-in never ends (the running state is what the offer shot shows). */
async function open(page: Page, theme: string, onboarding = false) {
  await page.addInitScript(
    ([t, onb]) => {
      const w = window as unknown as Record<string, unknown>;
      localStorage.setItem("omher.theme", t as string);
      localStorage.removeItem("omher.sessions.recent");
      if (onb) localStorage.removeItem("omher.onboarded");
      w.__omherPickFolder = "/Users/you/code/web-app";
      w.__omherMockAgents = ["claude", "codex"];
      w.__omherMockNoOmh = true;
      w.__OMHER_GATE__ = {
        status: async () => ({ state: "ready" }),
        retry: async () => {},
        installCommand: async () => "",
        install: async (onEvent: (e: unknown) => void) => {
          for (const text of ["[ok] Hermes Agent found", "Installing oh-my-hermes 4.9.2", "[ok] omh installed to ~/.local/bin/omh"]) onEvent({ kind: "line", text });
          await new Promise(() => {});
          return 0;
        },
      };
    },
    [theme, onboarding] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

const shot = async (page: Page, what: string, theme: string) => {
  await page.mouse.move(1170, 750);
  await page.waitForTimeout(350);
  await page.screenshot({ path: join(SHOTS, `hermes-only-${what}-${TAG}-${theme}.png`), animations: "disabled" });
};

for (const theme of ["dark", "light"] as const) {
  test(`menu ${theme}`, async ({ page }) => {
    await open(page, theme);
    await page.getByTestId("session-new").click();
    await expect(page.getByTestId("session-menu")).toBeVisible();
    await shot(page, "menu", theme);
  });

  test(`offer ${theme}`, async ({ page }) => {
    await open(page, theme);
    await page.getByTestId("session-new").click();
    await expect(page.getByTestId("session-menu")).toBeVisible();
    // before: there is no such line, so the shot is the menu as it was
    const offer = page.getByTestId("session-add-omh");
    if (await offer.count()) {
      await offer.click();
      await expect(page.getByTestId("session-add-omh-log")).toContainText("omh installed");
    }
    await shot(page, "offer", theme);
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

  test(`onboarding ${theme}`, async ({ page }) => {
    await mock("mock.clearHistory", { bot: "friren" });
    await open(page, theme, true);
    await page.getByTestId("bot-friren").click();
    await expect(page.getByTestId("onboarding")).toBeVisible();
    await shot(page, "onboarding", theme);
  });
}
