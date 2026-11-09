// First run without Hermes: the setup screen, its Install button, the streamed output, the retry after.
// `window.__OMHER_GATE__` stands in for the Tauri shell: it reports Hermes missing and plays a scripted
// installer run. The page never names the command; the stand-in records what the page asked for.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const SHOTS = process.env.OMHER_SHOTS;
const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

/** One request to the mock bridge over its own websocket. */
async function mock(op: string, params: Record<string, unknown> = {}): Promise<unknown> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<{ ok: boolean; result: unknown }>((res) => {
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
const CMD = "curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_WITH_DESKTOP=0 sh -s -- omher@beta";

type Plan = { exit: number; lines: string[]; holdMs?: number; reject?: string };

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
          if (plan.reject) throw plan.reject;
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
  await expect(screen).toContainText("Install Hermes to start");
  await expect(page.getByTestId("setup-command")).toHaveText(CMD);
  // Install has focus on arrival, so Enter starts it; no step sends the person to a terminal
  await expect(page.getByTestId("setup-install")).toBeFocused();
  await expect(page.getByTestId("setup-note")).toHaveText("Takes a few minutes. You’ll pick a model in the app after.");
  await expect(screen).not.toContainText("hermes setup");
  await expect(page.getByTestId("bridge-retry")).toBeVisible();
  // the command is copyable as the exact ASCII string the shell runs, and the pipe starts its own line
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  const shown = await page.getByTestId("setup-command").innerText();
  await page.getByTestId("setup-copy").click();
  await expect(page.getByTestId("setup-copy")).toHaveText("Copied");
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toMatch(/^[\x20-\x7e]+$/);
  expect(copied).toContain("| ");
  expect(shown.split("\n").some((l) => l.trimStart().startsWith("|"))).toBe(true);

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
  await page.getByTestId("setup-install").press("Enter");
  await expect(page.getByTestId("setup-failed")).toContainText("exit 1");
  await expect(page.getByTestId("setup-log")).toContainText("could not reach github.com");
  await expect(page.getByTestId("setup-install")).toHaveText("Install again");
  await expect(page.getByTestId("setup-install")).toBeEnabled();
  await expect(page.getByTestId("setup-install")).toBeFocused();
  await expect(page.getByTestId("setup-head")).toHaveText("Install didn’t finish");
  await expect(page.getByTestId("setup-note")).toHaveCount(0);
  // error lines in the danger colour, done lines muted, both at 12px like the Copy button
  const look = await page.evaluate(() => {
    const css = (sel: string) => {
      const el = [...document.querySelectorAll<HTMLElement>(".gate-line")].find((e) => e.textContent?.includes(sel))!;
      const st = getComputedStyle(el);
      return { color: st.color, size: st.fontSize };
    };
    const probe = (v: string) => {
      const d = document.createElement("div");
      d.style.color = `var(${v})`;
      document.body.append(d);
      const c = getComputedStyle(d).color;
      d.remove();
      return c;
    };
    return {
      failed: css("[failed] Install OMH package"),
      error: css("ERROR: could not reach"),
      ok: css("[ok] Hermes Agent"),
      plain: css("Cloning hermes-agent"),
      danger: probe("--danger"),
      muted: probe("--muted"),
      copy: getComputedStyle(document.querySelector("[data-testid=setup-copy]")!).fontSize,
    };
  });
  expect(look.failed.color).toBe(look.danger);
  expect(look.error.color).toBe(look.danger);
  expect(look.ok.color).toBe(look.muted);
  expect(look.plain.color).not.toBe(look.danger);
  expect(look.plain.color).not.toBe(look.muted);
  for (const size of [look.failed.size, look.ok.size, look.copy]) expect(size).toBe("12px");
  if (SHOTS) {
    mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: join(SHOTS, "setup-failed-dark.png"), animations: "disabled" });
  }
});

test("exit 0 with Hermes still missing is an error, not the setup screen again", async ({ page }) => {
  await stub(page, {
    exit: 0,
    lines: [...RUN, "[ok] done"],
    reject: "Install finished but Hermes was not found. The output above shows where the installer put it.",
  });
  await page.goto("/");
  await page.getByTestId("setup-install").click();
  await expect(page.getByTestId("setup-failed")).toHaveText(/^Install finished but Hermes was not found/);
  await expect(page.getByTestId("setup-head")).toHaveText("Install didn’t finish");
  await expect(page.getByTestId("setup-log")).toContainText("[ok] done");
  await expect(page.getByTestId("setup-install")).toHaveText("Install again");
  await expect(page.getByTestId("setup-install")).toBeFocused();
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

test("a bot with no model yet says where to pick one in the first chat screen", async ({ page }) => {
  // what a Hermes installed from the setup screen looks like: no model chosen
  await mock("mock.reset");
  await mock("chat.set_model", { bot: "default", model: "" });
  try {
    await page.goto("/");
    await page.getByTestId("bot-default").click();
    await expect(page.getByTestId("chat-no-model")).toHaveText(
      "Hermes has no model yet. Pick one from the model menu at the top right to start.",
    );
    await expect(page.getByTestId("model-label")).toHaveText("Pick a model");
    await expect(page.getByTestId("timeline")).not.toContainText("hermes setup");
    // a bot with a model shows no such line
    await page.getByTestId("bot-kami").click();
    await expect(page.getByTestId("chat-no-model")).toHaveCount(0);
  } finally {
    await mock("mock.reset");
  }
});
