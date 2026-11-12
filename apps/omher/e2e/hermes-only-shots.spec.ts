// Shots for a person who has Hermes but not oh-my-hermes (`omh`): the SESSIONS + menu, a Hermes session in a folder,
// the quiet offer to add oh-my-hermes, and the first-run cards. The mock host plays "Hermes, no omh" through
// `__omherMockNoOmh`; `__OMHER_GATE__` stands in for the shell's fixed installer (nothing is installed).
// Run with OMHER_SHOTS=<dir> OMHER_SHOT_TAG=before|after.
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

test.beforeEach(async () => {
  await mock("mock.reset");
});

/** Hermes without omh; the installer stand-in holds its run until `__release()` so the running state can be shot. */
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
      let release: () => void = () => {};
      w.__release = () => release();
      w.__OMHER_GATE__ = {
        status: async () => ({ state: "ready" }),
        retry: async () => {},
        installCommand: async () => "curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_WITH_DESKTOP=0 sh -s -- omher@beta",
        install: async (onEvent: (e: unknown) => void) => {
          for (const text of ["[ok] Hermes Agent found", "Installing oh-my-hermes 4.9.2 …", "[ok] omh installed to ~/.local/bin/omh"]) onEvent({ kind: "line", text });
          await new Promise<void>((r) => (release = r));
          onEvent({ kind: "exit", code: 0 });
          return 0;
        },
      };
    },
    [theme, onboarding],
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

const shot = async (page: Page, what: string, theme: string) => {
  await page.mouse.move(1270, 810);
  await page.waitForTimeout(350);
  await page.screenshot({ path: join(SHOTS, `hermes-only-${what}-${TAG}-${theme}.png`), animations: "disabled" });
};

for (const theme of ["dark", "light"] as const) {
  test(`shots ${theme}`, async ({ page }) => {
    test.skip(!SHOTS, "OMHER_SHOTS unset");
    mkdirSync(SHOTS, { recursive: true });
    await page.setViewportSize({ width: 1180, height: 760 });

    // the + menu
    await open(page, theme);
    await page.getByTestId("session-new").click();
    await expect(page.getByTestId("session-menu")).toBeVisible();
    await shot(page, "menu", theme);

    // the offer, running (after: its own line; before: no such line, the same menu)
    const offer = page.getByTestId("session-add-omh");
    if (await offer.count()) {
      await offer.click();
      await expect(page.getByTestId("session-add-omh-log")).toBeVisible();
    }
    await shot(page, "offer", theme);
    await page.evaluate(() => (window as unknown as { __release: () => void }).__release());

    // a Hermes session in a folder (before: the row cannot be picked; the draft shows what is missing)
    await page.goto("/");
    await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
    await page.getByTestId("session-new").click();
    await page.getByTestId("session-agent-omh").click({ force: true });
    if (await page.getByTestId("session-folder").count()) {
      await page.getByTestId("session-folder").click();
      await page.getByTestId("session-choose").click();
      await page.getByTestId("composer").fill("What is in this folder?");
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("session-status")).not.toHaveText("Starting…");
    }
    await shot(page, "session", theme);

    // the first-run cards over an empty chat
    await mock("mock.clearHistory", { bot: "friren" });
    await open(page, theme, true);
    await page.getByTestId("bot-friren").click();
    await expect(page.getByTestId("onboarding")).toBeVisible();
    await shot(page, "onboarding", theme);
  });
}
