// Settings › Accounts: the reset-first choice (off by default, under Auto-switch), which account takes over when the
// one in use is limited, and the CLI's version beside its name. Same stand-in for the desktop app as accounts.spec.ts,
// plus `version` (Claude Code and Codex print one, pi has no such command).
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS_DIR || join(dirname(fileURLToPath(import.meta.url)), "__shots__");

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "a1") res(msg);
    };
    ws.send(JSON.stringify({ id: "a1", op, ...params }));
  });
  ws.close();
  return reply.result;
}
const callsOf = async (op: string) =>
  ((await mock("mock.calls")).calls as { op: string; params: Record<string, unknown> }[]).filter((c) => c.op === op);

function installHost() {
  const w = window as any;
  w.__omherAccountHost = {
    canSignIn: true,
    clis: async () => ({ claude: true, codex: true, pi: true, omp: false, grok: false, gemini: false }),
    status: async (cli: string, account: string) =>
      cli === "claude" && account === "default"
        ? { logged_in: true, email: "owner@example.com", plan: "max_20x", method: "claude.ai" }
        : cli === "codex"
          ? { logged_in: true, email: null, plan: null, method: "chatgpt" }
          : null,
    version: async (cli: string) => (cli === "claude" ? "2.1.322" : cli === "codex" ? "0.167.0-alpha.4.1" : null),
    signIn: async () => 1,
    cancel: async () => {},
  };
}

/** Codex: This computer (limited soon), then Alpha, Beta and Work, each signed in. */
async function threeMore() {
  for (const label of ["Alpha", "Beta"]) {
    const { id } = await mock("accounts.add", { cli: "codex", label });
    await mock("mock.accounts", { cli: "codex", signed_in: { id, email: "" } });
  }
}

async function openAccounts(page: Page, theme: "dark" | "light" = "dark") {
  await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
  await page.addInitScript(installHost);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("me").click();
  await expect(page.getByTestId("accounts-page")).toBeVisible();
  await expect(page.getByTestId("accounts-codex").getByTestId("account-row")).toHaveCount(2);
}

const row = (page: Page, id: string) => page.getByTestId("accounts-codex").locator(`[data-testid=account-row][data-id="${id}"]`);
const inUse = (page: Page, id: string) => expect(row(page, id).getByTestId("account-pill")).toHaveText("In use");

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("the setting is off by default, sits under Auto-switch, and needs Auto-switch on", async ({ page }) => {
  await openAccounts(page);
  const sw = page.getByTestId("resetfirst-codex");
  await expect(sw).toHaveAttribute("role", "switch");
  await expect(sw).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("resetfirst-row-codex")).toContainText("Use the account that resets soonest first");
  await expect(page.getByTestId("resetfirst-row-codex")).toContainText("Quota about to reset is used before it lapses.");
  const y = async (id: string) => (await page.getByTestId(id).boundingBox())!.y;
  expect(await y("resetfirst-row-codex")).toBeGreaterThan(await y("autoswitch-row-codex"));
  await expect(sw).toBeEnabled();
  await sw.click();
  await expect(sw).toHaveAttribute("aria-checked", "true");
  // Auto-switch off: the choice cannot be used, and shows as off
  await page.getByTestId("autoswitch-codex").click();
  await expect(sw).toBeDisabled();
  await expect(sw).toHaveAttribute("aria-checked", "false");
  expect(await page.evaluate(() => localStorage.getItem("omher.resetfirst"))).toBe('{"codex":true}');
});

test("off: a limit moves the session to the first ready account in list order", async ({ page }) => {
  await openAccounts(page);
  await threeMore();
  await mock("mock.accounts", { cli: "codex", usage: { id: "alpha", windows: [{ label: "5 hours", used_percent: 20, resets_in_min: 200 }] } });
  await mock("mock.accounts", { cli: "codex", usage: { id: "beta", windows: [{ label: "5 hours", used_percent: 20, resets_in_min: 50 }] } });
  await mock("mock.accounts", { limit: "default" });
  await inUse(page, "alpha");
  expect((await callsOf("accounts.set_active")).map((c) => c.params)).toEqual([{ cli: "codex", account: "alpha" }]);
  await expect(page.getByTestId("accounts-codex").getByTestId("accounts-toast")).toHaveText(/^Switched Codex to Alpha for new sessions \(limit on This computer, resets .+\)$/);
});

test("on: the account whose limit resets soonest takes over, and the line says why", async ({ page }) => {
  await openAccounts(page);
  await threeMore();
  await page.getByTestId("resetfirst-codex").click();
  await mock("mock.accounts", { cli: "codex", usage: { id: "alpha", windows: [{ label: "5 hours", used_percent: 20, resets_in_min: 200 }] } });
  await mock("mock.accounts", { cli: "codex", usage: { id: "beta", windows: [{ label: "5 hours", used_percent: 20, resets_in_min: 50 }] } });
  await mock("mock.accounts", { cli: "codex", usage: { id: "work", windows: [{ label: "5 hours", used_percent: 20, resets_in_min: 120 }] } });
  await mock("mock.accounts", { limit: "default" });
  await inUse(page, "beta");
  expect((await callsOf("accounts.set_active")).map((c) => c.params)).toEqual([{ cli: "codex", account: "beta" }]);
  await expect(page.getByTestId("accounts-codex").getByTestId("accounts-toast")).toHaveText(
    /^Switched Codex to Beta for new sessions \(limit on This computer, resets .+\); its limit resets soonest, .+$/,
  );
});

test("on, no account has a reset time: list order, with the usual line", async ({ page }) => {
  await openAccounts(page);
  await threeMore();
  await page.getByTestId("resetfirst-codex").click();
  await mock("mock.accounts", { cli: "codex", usage: { id: "beta", windows: [{ label: "5 hours", used_percent: 20 }] } });
  await mock("mock.accounts", { limit: "default" });
  await inUse(page, "alpha");
  await expect(page.getByTestId("accounts-codex").getByTestId("accounts-toast")).toHaveText(/^Switched Codex to Alpha for new sessions \(limit on This computer, resets [^;]+\)$/);
});

test("on: an account that is not limited is never moved off", async ({ page }) => {
  await openAccounts(page);
  await threeMore();
  await page.getByTestId("resetfirst-codex").click();
  await mock("mock.accounts", { cli: "codex", usage: { id: "beta", windows: [{ label: "5 hours", used_percent: 20, resets_in_min: 5 }] } });
  await page.waitForTimeout(400);
  await inUse(page, "default");
  expect(await callsOf("accounts.set_active")).toEqual([]);
});

test("the CLI's version sits beside its name as muted text; a CLI with none shows none", async ({ page }) => {
  await openAccounts(page);
  await expect(page.getByTestId("cli-version-claude")).toHaveText("2.1.322");
  await expect(page.getByTestId("cli-version-codex")).toHaveText("0.167.0-alpha.4.1");
  await expect(page.getByTestId("cli-version-pi")).toHaveCount(0);
  const head = page.getByTestId("accounts-codex").locator(".acc-gh");
  await expect(head).toHaveText(/^Codex\s*0\.167\.0-alpha\.4\.1$/);
  // text only: no border, fill or icon on the version
  const v = page.getByTestId("cli-version-codex");
  expect(await v.evaluate((e) => { const s = getComputedStyle(e); return [s.backgroundColor, s.borderTopWidth, s.boxShadow, e.children.length].join("|"); })).toBe("rgba(0, 0, 0, 0)|0px|none|0");
});

test("screenshots: the new row and the version, dark and light", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  for (const theme of ["dark", "light"] as const) {
    await mock("mock.reset");
    await page.setViewportSize({ width: 1180, height: 820 });
    await openAccounts(page, theme);
    await page.getByTestId("resetfirst-codex").click();
    await page.mouse.move(5, 5);
    await page.waitForTimeout(350);
    await page.screenshot({ path: join(SHOTS, `accounts-reset-first-${theme}.png`), animations: "disabled" });
    await page.getByTestId("autoswitch-codex").click();
    await page.mouse.move(5, 5);
    await page.screenshot({ path: join(SHOTS, `accounts-reset-first-off-${theme}.png`), animations: "disabled" });
    await page.evaluate(() => localStorage.clear());
  }
});
