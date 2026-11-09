// First run without Hermes: the setup screen, its Install button, the streamed output, the retry after.
// `window.__OMHER_GATE__` stands in for the Tauri shell: it reports Hermes missing and plays a scripted
// installer run. The page never names the command; the stand-in records what the page asked for.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const SHOTS = process.env.OMHER_SHOTS;
const CMD = "curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_WITH_DESKTOP=0 sh -s -- omher@beta";

type Plan = { exit: number; lines: string[]; holdMs?: number };

async function stub(page: Page, plan: Plan) {
  await page.addInitScript(
    ({ plan, cmd }) => {
      const w = window as unknown as Record<string, unknown>;
      const calls: string[] = [];
      let installed = false;
      w.__gateCalls = calls;
      w.__OMHER_GATE__ = {
        status: async () => {
          calls.push("status");
          return installed
            ? { state: "ready" }
            : { state: "failed", error: "Hermes not found: install Hermes Agent first", missing: "hermes" };
        },
        retry: async () => {
          calls.push("retry");
        },
        installCommand: async () => cmd,
        install: async (onEvent: (e: unknown) => void) => {
          calls.push("install");
          for (const text of plan.lines) {
            onEvent({ kind: "line", text });
            await new Promise((r) => setTimeout(r, 15));
          }
          if (plan.holdMs) await new Promise((r) => setTimeout(r, plan.holdMs));
          onEvent({ kind: "exit", code: plan.exit });
          if (plan.exit === 0) installed = true;
          return plan.exit;
        },
      };
    },
    { plan, cmd: CMD },
  );
}

const RUN = [
  "OMH installer",
  "[note] omher@beta: found neither Hermes nor OMH. Installing Hermes first, then OMH, 'omh setup', and the omher app.",
  "[note] omher@beta: OMH_WITH_DESKTOP=0, so the omher app is not installed.",
  "[hermes] Install Hermes Agent with its official installer (non-interactive)",
  "  Cloning hermes-agent …",
  "  Downloading Python 3.12 …",
  "[ok] Hermes Agent",
  "[1/5] Create isolated Python environment at ~/.local/share/omh/venv",
  "[ok] done",
  "[2/5] Install OMH package",
];

test("Hermes missing: the setup screen shows what Install runs, streams it, and opens the app after", async ({ page }) => {
  await stub(page, { exit: 0, lines: [...RUN, "[ok] done", "oh-my-hermes is installed."], holdMs: 400 });
  await page.goto("/");
  const screen = page.getByTestId("setup-screen");
  await expect(screen).toBeVisible();
  await expect(screen).toContainText("omher needs Hermes and oh-my-hermes");
  await expect(page.getByTestId("setup-command")).toHaveText(CMD);
  await expect(page.getByTestId("bridge-retry")).toBeVisible();

  await page.getByTestId("setup-install").click();
  await expect(page.getByTestId("setup-install")).toBeDisabled();
  await expect(page.getByTestId("setup-install")).toHaveText("Installing…");
  await expect(page.getByTestId("setup-log")).toContainText("[ok] Hermes Agent");
  if (SHOTS) {
    mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: join(SHOTS, "setup-running-dark.png") });
  }

  // Exit 0: the gate polls again, the shell says ready, and the app replaces the screen.
  await expect(page.getByTestId("setup-screen")).toHaveCount(0, { timeout: 5000 });
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  const calls = await page.evaluate(() => (window as unknown as { __gateCalls: string[] }).__gateCalls);
  expect(calls.filter((c) => c === "install")).toHaveLength(1);
});

test("a failed install says so and offers Install again", async ({ page }) => {
  await stub(page, { exit: 1, lines: [...RUN, "[failed] Install OMH package", "  ERROR: could not reach github.com"] });
  await page.goto("/");
  await page.getByTestId("setup-install").click();
  await expect(page.getByTestId("setup-failed")).toContainText("exit 1");
  await expect(page.getByTestId("setup-log")).toContainText("could not reach github.com");
  await expect(page.getByTestId("setup-install")).toHaveText("Install again");
  await expect(page.getByTestId("setup-install")).toBeEnabled();
});

for (const theme of ["dark", "light"] as const) {
  test(`setup screen before Install (${theme})`, async ({ page }) => {
    await stub(page, { exit: 0, lines: [] });
    await page.addInitScript((t) => {
      document.addEventListener("DOMContentLoaded", () => {
        document.documentElement.dataset.theme = t;
      });
    }, theme);
    await page.goto("/");
    await expect(page.getByTestId("setup-command")).toBeVisible();
    if (SHOTS) {
      mkdirSync(SHOTS, { recursive: true });
      await page.screenshot({ path: join(SHOTS, `setup-${theme}.png`) });
    }
  });
}

test("any other bridge failure keeps the plain Retry screen", async ({ page }) => {
  await page.addInitScript(() => {
    (window as unknown as Record<string, unknown>).__OMHER_GATE__ = {
      status: async () => ({ state: "failed", error: "the bridge exited before it was ready: ImportError" }),
      retry: async () => {},
      installCommand: async () => "",
      install: async () => 0,
    };
  });
  await page.goto("/");
  await expect(page.getByTestId("bridge-error")).toContainText("ImportError");
  await expect(page.getByTestId("setup-screen")).toHaveCount(0);
  await expect(page.getByTestId("setup-install")).toHaveCount(0);
});
