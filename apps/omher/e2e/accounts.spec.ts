// Settings › Accounts (accounts.*): the user row opens it; CLIProxyAPI rows are read-only while CPA management
// is off; omher's own stack adds, switches and removes (after asking); auto-switch leaves one quiet line.
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

async function openAccounts(page: Page, theme: "dark" | "light" = "dark") {
  await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("me").click();
  await expect(page.getByTestId("accounts-page")).toBeVisible();
}

const codexRow = (page: Page, id: string) => page.getByTestId("accounts-codex").locator(`[data-testid=account-row][data-id="${id}"]`);

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("the user row opens Settings › Accounts, listed first", async ({ page }) => {
  await openAccounts(page);
  await expect(page.getByTestId("settings-nav-accounts")).toHaveAttribute("aria-current", "page");
  const first = page.locator(".st-nav button").first();
  await expect(first).toHaveText("Accounts");
  await expect(page.getByTestId("me")).toHaveClass(/\bon\b/);
  await expect(page.getByTestId("nav-settings")).not.toHaveClass(/\bon\b/);
});

test("five CPA rows are read-only with the hint; emails masked, full on hover; never a token", async ({ page }) => {
  await openAccounts(page);
  const g = page.getByTestId("accounts-claude");
  await expect(g).toHaveAttribute("data-backend", "cpa");
  const rows = g.getByTestId("account-row");
  await expect(rows).toHaveCount(5);
  await expect(g.getByTestId("cpa-hint")).toHaveText(
    "CPA management is off. Turn it on in ~/.cli-proxy-api/config.yaml (management.secret-key) to manage accounts here.",
  );
  await expect(g.getByTestId("cpa-strategy")).toHaveText("Auto-switch: CPA fill-first");
  await expect(g.getByTestId("account-menu")).toHaveCount(0); // read-only: no ⋯ menu
  for (let i = 0; i < 5; i++) await expect(rows.nth(i)).toHaveAttribute("data-readonly", "true");
  await expect(rows.nth(0).getByTestId("account-name")).toHaveText("a***@example.com");
  await expect(rows.nth(0).getByTestId("account-name")).toHaveAttribute("title", "alice@example.com");
  await expect(rows.nth(3).getByTestId("account-state")).toHaveText("Disabled");
  await expect(rows.nth(0).getByTestId("account-state")).toHaveText("Ready");
  // + Add account on a CPA group points at CPA's own login
  await g.getByTestId("add-account-claude").click();
  await expect(g.getByTestId("cpa-add-hint")).toContainText("cliproxyapi -claude-login");
  const html = await page.content();
  for (const k of ["access_token", "refresh_token", "id_token", "api_key"]) expect(html).not.toContain(k);
  expect(await callsOf("accounts.cpa_action")).toEqual([]);
});

test("omher stack: add → row appears and says how to log in; make active moves the chip", async ({ page }) => {
  await openAccounts(page);
  const g = page.getByTestId("accounts-codex");
  await expect(g).toHaveAttribute("data-backend", "omher");
  await expect(g.getByTestId("account-row")).toHaveCount(2);
  await expect(codexRow(page, "default").getByTestId("account-state")).toHaveText("Active");
  await expect(codexRow(page, "work").getByTestId("account-state")).toHaveText("Ready");

  await g.getByTestId("add-account-codex").click();
  await g.getByTestId("add-label-codex").fill("Side Project");
  await g.getByTestId("add-confirm-codex").click();
  await expect(g.getByTestId("account-row")).toHaveCount(3);
  await expect(codexRow(page, "side-project").getByTestId("account-state")).toHaveText("Log in");
  await expect(g.getByTestId("login-hint")).toContainText("CODEX_HOME=/mock/.omher/accounts/codex/side-project codex login");
  expect((await callsOf("accounts.add")).map((c) => c.params)).toEqual([{ cli: "codex", label: "Side Project" }]);

  await codexRow(page, "work").getByTestId("account-menu").click();
  await page.getByRole("button", { name: "Make active" }).click();
  await expect(codexRow(page, "work").getByTestId("account-state")).toHaveText("Active");
  await expect(codexRow(page, "default").getByTestId("account-state")).toHaveText("Ready");
  expect((await callsOf("accounts.set_active")).map((c) => c.params)).toEqual([{ cli: "codex", account: "work" }]);
});

test("remove asks first; cancel keeps the row, confirm deletes only that account", async ({ page }) => {
  await openAccounts(page);
  const g = page.getByTestId("accounts-codex");
  await codexRow(page, "work").getByTestId("account-menu").click();
  await page.getByRole("button", { name: "Remove…" }).click();
  const confirm = g.getByTestId("remove-confirm");
  await expect(confirm).toContainText("Remove Work?");
  await expect(confirm).toContainText("/mock/.omher/accounts/codex/work");
  expect(await callsOf("accounts.remove")).toEqual([]);
  await confirm.getByRole("button", { name: "Cancel" }).click();
  await expect(confirm).toHaveCount(0);
  await expect(g.getByTestId("account-row")).toHaveCount(2);

  await codexRow(page, "work").getByTestId("account-menu").click();
  await page.getByRole("button", { name: "Remove…" }).click();
  await g.getByTestId("remove-confirm").getByRole("button", { name: "Remove" }).click();
  await expect(g.getByTestId("account-row")).toHaveCount(1);
  expect((await callsOf("accounts.remove")).map((c) => c.params)).toEqual([{ cli: "codex", account: "work" }]);
  // the default login has no Remove
  await codexRow(page, "default").getByTestId("account-menu").click();
  await expect(page.getByRole("button", { name: "Remove…" })).toHaveCount(0);
});

test("auto-switch: the active account hits its limit → next Ready one, a toast and one quiet chat line", async ({ page }) => {
  await openAccounts(page);
  await mock("mock.accounts", { limit: "default" });
  await expect(codexRow(page, "work").getByTestId("account-state")).toHaveText("Active");
  await expect(codexRow(page, "default").getByTestId("account-state")).toHaveText(/^Limited until/);
  const toast = page.getByTestId("accounts-codex").getByTestId("accounts-toast");
  await expect(toast).toHaveText(/^Switched to Codex #2 Work \(limit on #1 Default, resets .+\)$/);
  expect((await callsOf("accounts.set_active")).map((c) => c.params)).toEqual([{ cli: "codex", account: "work" }]);
  // the bot chat shows the same line, quietly, and nothing was sent to the bot
  await page.getByTestId("bot-kami").click();
  const line = page.getByTestId("system-line");
  await expect(line).toHaveCount(1);
  await expect(line).toHaveText(/^Switched to Codex #2 Work/);
  expect(await callsOf("chat.send")).toEqual([]);
});

test("auto-switch off for a group: a limit does not move the active account", async ({ page }) => {
  await openAccounts(page);
  await page.getByTestId("autoswitch-codex").getByRole("radio", { name: "Off" }).click();
  await mock("mock.accounts", { limit: "default" });
  await expect(codexRow(page, "default").getByTestId("account-state")).toHaveText(/^Limited until/);
  await page.waitForTimeout(300);
  await expect(codexRow(page, "work").getByTestId("account-state")).toHaveText("Ready");
  expect(await callsOf("accounts.set_active")).toEqual([]);
});

test("screenshots: Accounts in dark and light", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  for (const theme of ["dark", "light"] as const) {
    await mock("mock.reset");
    await page.setViewportSize({ width: 1180, height: 820 });
    await openAccounts(page, theme);
    await expect(page.getByTestId("accounts-claude").getByTestId("account-row")).toHaveCount(5);
    await page.screenshot({ path: join(SHOTS, `T11-accounts-${theme}.png`), animations: "disabled" });
    await codexRow(page, "work").getByTestId("account-menu").click();
    await page.screenshot({ path: join(SHOTS, `T11-menu-${theme}.png`), animations: "disabled" });
    await page.keyboard.press("Escape");
    await mock("mock.accounts", { limit: "default" });
    await expect(page.getByTestId("accounts-toast")).toBeVisible();
    await expect(codexRow(page, "work").getByTestId("account-state")).toHaveText("Active");
    await page.screenshot({ path: join(SHOTS, `T11-switch-${theme}.png`), animations: "disabled" });
    await page.getByTestId("bot-kami").click();
    await expect(page.getByTestId("system-line")).toBeVisible();
    await page.screenshot({ path: join(SHOTS, `T11-chatline-${theme}.png`), animations: "disabled" });
  }
});
