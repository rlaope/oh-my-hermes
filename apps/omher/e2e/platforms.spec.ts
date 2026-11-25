// A bot's messaging platforms (BOUNDARY rule 43): `bots.platforms` is what OMH's read-only `omh hermes platforms`
// said. A platform known not to be connected shows on the bot's sidebar row in words; the bot page lists each
// platform with its state, since when, why, Hermes' own words and the fix: a link to the Discord Developer Portal and
// Hermes' restart command to copy. Nothing on either changes anything. Connected, unknown and "OMH could not say"
// show nothing on the row.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

test.use({ colorScheme: "dark" });

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
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

type Call = { op: string; params: Record<string, unknown> };
const platformReads = async (): Promise<Call[]> => ((await mock("mock.calls")).calls as Call[]).filter((c) => c.op === "bots.platforms");

const REFUSED = {
  platform: "discord",
  status: "disconnected",
  attention: true,
  since: "2020-01-02T03:04:05Z",
  logged: "2020-01-02T03:34:05Z",
  reason_kind: "discord_privileged_intents",
  unknown_why: "",
  reason: "Shard ID None is requesting privileged intents that have not been explicitly enabled in the developer portal.",
  guidance: "Hermes is requesting: - Message Content Intent - Server Members Intent (required for DISCORD_ALLOWED_ROLES)",
  restart: "hermes -p default gateway restart",
  intents: ["Message Content", "Server Members"],
};
const one = (bot: string, ...platforms: Record<string, unknown>[]) => ({ bots: { [bot]: { log: "read", platforms } } });

async function botPage(page: Page, bot: string) {
  await page.getByTestId(`bot-${bot}`).click({ button: "right" });
  await page.getByTestId("row-menu").getByRole("menuitem", { name: "Edit bot" }).click();
  await expect(page.getByTestId("bot-sections")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("connected: the row says nothing and the page lists the platform as connected", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bot-default")).toBeVisible();
  await expect.poll(async () => (await platformReads()).length).toBeGreaterThan(0);
  await expect(page.getByTestId("platform-down-default")).toHaveCount(0);
  await botPage(page, "default");
  const section = page.getByTestId("bp-platforms");
  await expect(section.getByTestId("pf-state-discord")).toHaveText("Connected");
  await expect(section.getByTestId("pf-fix-discord")).toHaveCount(0);
});

test("a refused Discord: the row names it, the page gives the reason, the portal and the restart to copy", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await mock("mock.platforms", one("default", REFUSED));
  await page.goto("/");
  const chip = page.getByTestId("platform-down-default");
  await expect(chip).toHaveText("!Discord disconnected");
  await expect(chip).toHaveAttribute("role", "status");
  await expect(page.getByTestId("platform-down-friren")).toHaveCount(0);

  await botPage(page, "default");
  const item = page.getByTestId("pf-discord");
  await expect(item.getByTestId("pf-state-discord")).toHaveText("!Disconnected");
  await expect(item).toContainText("since");
  await expect(item).toContainText("Discord refused the bot's privileged gateway intents.");
  await expect(item.getByTestId("pf-reason-discord")).toContainText("requesting privileged intents");
  await expect(item.getByTestId("pf-guidance-discord")).toContainText("Server Members Intent");
  const fix = item.getByTestId("pf-fix-discord");
  await expect(fix).toContainText("Turn on Message Content Intent and Server Members Intent in the Discord Developer Portal");
  await expect(fix).toContainText("Or remove the role allowlist that needs Server Members Intent.");
  await expect(fix.getByTestId("pf-portal")).toHaveAttribute("href", "https://discord.com/developers/applications");
  await expect(fix.getByTestId("pf-restart")).toHaveText("hermes -p default gateway restart");
  await expect(fix).toContainText("omher does not run it");
  await fix.getByTestId("pf-copy").click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("hermes -p default gateway restart");
  // the only control in the section is Copy (and the portal link): nothing restarts or edits
  await expect(page.getByTestId("bp-platforms").getByRole("button")).toHaveCount(1);
  const before = (await mock("mock.calls")).calls.filter((c: Call) => c.op === "bots.restart").length;
  expect(before).toBe(0);

  // Read again asks OMH again (fresh), and a later connect clears the row
  await mock("mock.platforms", one("default", { ...REFUSED, status: "connected", attention: false, reason_kind: "", since: "" }));
  await page.getByTestId("bp-refresh").click();
  await expect(item.getByTestId("pf-state-discord")).toHaveText("Connected");
  await expect(chip).toHaveCount(0);
  expect((await platformReads()).some((c) => c.params.fresh === true)).toBe(true);
});

test("unknown and an OMH that could not say: nothing on the row, and the page says which", async ({ page }) => {
  await mock("mock.platforms", one("default", { ...REFUSED, status: "unknown", attention: false, unknown_why: "earlier_run", since: "" }));
  await page.goto("/");
  await expect(page.getByTestId("bot-default")).toBeVisible();
  await expect.poll(async () => (await platformReads()).length).toBeGreaterThan(0);
  await expect(page.getByTestId("platform-down-default")).toHaveCount(0);
  await botPage(page, "default");
  const item = page.getByTestId("pf-discord");
  await expect(item.getByTestId("pf-state-discord")).toHaveText("Not known");
  await expect(item).toContainText("from before the gateway serving it started");
  await expect(item.getByTestId("pf-fix-discord")).toHaveCount(0);

  await mock("mock.platforms", { available: false });
  await page.getByTestId("bp-refresh").click();
  await expect(page.getByTestId("pf-unavailable")).toBeVisible();
  await expect(page.getByTestId("pf-discord")).toHaveCount(0);
});

test("a bot with no messaging platform shows none, and Korean says it in Korean", async ({ page }) => {
  await mock("mock.platforms", one("default", REFUSED));
  await page.goto("/");
  await page.evaluate(() => localStorage.setItem("omher.lang", "ko"));
  await page.reload();
  await expect(page.getByTestId("platform-down-default")).toHaveText("!Discord 연결 끊김");
  await page.getByTestId("bot-friren").click({ button: "right" });
  await page.getByTestId("row-menu").getByRole("menuitem", { name: "봇 편집" }).click();
  await expect(page.getByTestId("pf-none")).toContainText("메신저 플랫폼이 없어요");
  await expect(page.getByTestId("bp-platforms")).not.toContainText("pf.");
});

// A bot on another computer (rule 45): its platforms are what that computer's own bridge read there, under `peers`.
async function attachPeer(page: Page): Promise<string> {
  await page.evaluate(() => localStorage.removeItem("omher.mockPeers"));
  await page.reload();
  await page.getByRole("button", { name: "Add a bot" }).click();
  await page.getByTestId("addbot-ssh").click();
  const card = page.getByTestId("peer-card");
  await card.getByTestId("peer-host").fill("build-box");
  await card.getByTestId("peer-label").fill("Build box");
  await card.getByTestId("peer-check").click();
  await expect(card.getByTestId("peer-found")).toBeVisible();
  await card.getByTestId("peer-connect").click();
  const row = page.locator('button.bot[data-testid$=":mini"]');
  await expect(row).toBeVisible();
  return (await row.getAttribute("data-testid"))!.slice("bot-".length);
}

test("a bot on another computer: its own computer's read shows on its row and page, with where to restart", async ({ page }) => {
  await mock("mock.peerPlatforms", one("mini", { ...REFUSED, restart: "hermes -p mini gateway restart" }));
  await page.goto("/");
  const key = await attachPeer(page);
  const chip = page.getByTestId(`platform-down-${key}`);
  await expect(chip).toHaveText("!Discord disconnected"); // read when the computer attached, not a minute later
  await expect(page.getByTestId("platform-down-default")).toHaveCount(0); // this computer's bots are unchanged

  await botPage(page, key);
  const section = page.getByTestId("bp-platforms");
  const item = section.getByTestId("pf-discord");
  await expect(item.getByTestId("pf-state-discord")).toHaveText("!Disconnected");
  await expect(item.getByTestId("pf-restart")).toHaveText("hermes -p mini gateway restart");
  await expect(item.getByTestId("pf-fix-discord")).toContainText("Run it on Build box");
  await expect(item.getByTestId("pf-portal")).toHaveAttribute("href", "https://discord.com/developers/applications");
  await expect(section).toContainText("Read on Build box by its own oh-my-hermes");
  // the page asks this bridge once for every computer; Read again never sends `fresh` for a bot there
  await page.getByTestId("bp-refresh").click();
  await expect.poll(async () => (await platformReads()).length).toBeGreaterThan(1);
  expect((await platformReads()).every((c) => c.params.fresh !== true && c.params.bot === undefined)).toBe(true);
});

test("a computer that could not say, or whose link is down: cannot tell, never connected or not", async ({ page }) => {
  await mock("mock.peerPlatforms", { available: false, why: "unread" });
  await page.goto("/");
  const key = await attachPeer(page);
  await expect.poll(async () => (await platformReads()).length).toBeGreaterThan(1);
  await expect(page.getByTestId(`platform-down-${key}`)).toHaveCount(0);
  await botPage(page, key);
  const told = page.getByTestId("pf-peer-cannot-tell");
  await expect(told).toHaveAttribute("data-why", "unread");
  await expect(told).toContainText("Build box gave no answer omher could use");
  await expect(page.getByTestId("pf-discord")).toHaveCount(0);

  await mock("mock.peerPlatforms", { available: false, why: "offline" });
  await page.getByTestId("bp-refresh").click();
  await expect(told).toHaveAttribute("data-why", "offline");
  await expect(told).toContainText("Build box is not connected now");
  await expect(page.getByTestId("bp-platforms")).not.toContainText("Connected");
});
