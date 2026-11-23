// Apps (src/apps, BOUNDARY rule 42), against the mock bridge: one bot's view of Hermes' MCP catalog and its
// integration skills, grouped by tier, each with its state; Connect, Sign in and Remove send `apps.install`,
// `apps.login` and `apps.remove` with the bot and the catalog name only; Hermes' own words when a run did not work, and
// the terminal command for an app whose install asks for a value.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

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
const calls = async (prefix: string): Promise<Call[]> =>
  ((await mock("mock.calls")).calls as Call[]).filter((c) => c.op.startsWith(prefix));

async function openApps(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("nav-apps").click();
  await expect(page.getByTestId("apps-sec-work")).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("lists the catalog and the skills by tier, each with the bot's state", async ({ page }) => {
  await openApps(page);
  await expect(page.getByTestId("nav-apps")).toHaveAttribute("aria-current", "page");
  await expect(page.getByTestId("apps-scope")).toContainText("Kami's apps");
  for (const tier of ["work", "ops", "more"]) await expect(page.getByTestId(`apps-sec-${tier}`)).toBeVisible();
  const state = (name: string) => page.getByTestId(`app-state-${name}`);
  await expect(state("linear")).toHaveText("Connected");
  await expect(state("figma")).toHaveText("Needs sign-in");
  await expect(state("datadog")).toHaveText("Turned off");
  await expect(state("notion")).toHaveText("Not connected");
  await expect(state("google-workspace")).toHaveText("Installed");
  await expect(state("obsidian")).toHaveText("Turned off");
  await expect(state("himalaya")).toHaveText("Ships with Hermes");
  // the tiers: Jira and Confluence among the work apps, Datadog under ops and data, Wolfram under the rest
  await expect(page.getByTestId("apps-sec-work").getByTestId("app-card-atlassian")).toContainText("Jira and Confluence");
  await expect(page.getByTestId("apps-sec-ops").getByTestId("app-card-datadog")).toBeVisible();
  await expect(page.getByTestId("apps-sec-more").getByTestId("app-card-wolfram")).toBeVisible();
  // a skill shows its state and offers no button; an app offers only what its state allows
  await expect(page.getByTestId("app-card-google-workspace").getByRole("button")).toHaveCount(0);
  await expect(page.getByTestId("app-card-linear").getByRole("button")).toHaveText(["Sign in again", "Remove"]);
  await expect(page.getByTestId("app-card-datadog").getByRole("button")).toHaveText(["Remove"]);
  await expect(page.getByTestId("app-card-deepwiki").getByRole("button")).toHaveText(["Connect"]);
  // search keeps the cards whose name, title or text has it
  await page.getByTestId("apps-search").fill("jira");
  await expect(page.getByTestId("app-card-atlassian")).toBeVisible();
  await expect(page.getByTestId("app-card-notion")).toHaveCount(0);
  expect((await calls("apps.")).map((c) => [c.op, c.params])).toEqual([["apps.list", { bot: "kami" }]]);
});

test("Connect then Sign in run the bot's own install and login with the catalog name, and say what changed", async ({ page }) => {
  await openApps(page);
  await page.getByTestId("app-install-notion").click();
  await expect(page.getByTestId("app-install-notion")).toHaveText("Connecting…");
  await expect(page.getByTestId("app-install-notion")).toBeDisabled();
  await expect(page.getByTestId("app-install-deepwiki")).toBeDisabled(); // one run at a time
  await expect(page.getByTestId("apps-result")).toHaveText("Notion is added to Kami. Sign in to finish.");
  await expect(page.getByTestId("app-state-notion")).toHaveText("Needs sign-in");
  await page.getByTestId("app-login-notion").click();
  await expect(page.getByTestId("apps-signing")).toContainText("Finish signing in to Notion in the browser page Hermes opened");
  await expect(page.getByTestId("apps-result")).toContainText("Kami is signed in to Notion");
  await expect(page.getByTestId("apps-result")).toContainText("/reload-mcp");
  await expect(page.getByTestId("app-state-notion")).toHaveText("Connected");
  await expect(page.getByTestId("app-login-notion")).toHaveText("Sign in again");
  // an app with no sign-in: Connect alone, and the line says when the bot gets its tools
  await page.getByTestId("app-install-deepwiki").click();
  await expect(page.getByTestId("apps-result")).toContainText("DeepWiki is connected to Kami. New chats get its tools within about a minute");
  const sent = (await calls("apps.")).filter((c) => c.op !== "apps.list").map((c) => [c.op, c.params]);
  expect(sent).toEqual([
    ["apps.install", { bot: "kami", name: "notion" }],
    ["apps.login", { bot: "kami", name: "notion" }],
    ["apps.install", { bot: "kami", name: "deepwiki" }],
  ]);
});

test("Remove asks first; a run that did not work shows Hermes' own words; a value it asks for points to the terminal", async ({ page }) => {
  await openApps(page);
  await page.getByTestId("app-remove-linear").click();
  await expect(page.getByRole("alertdialog")).toContainText("Remove Linear from Kami?");
  expect((await calls("apps.remove")).length).toBe(0);
  await page.getByTestId("app-confirm-remove").click();
  await expect(page.getByTestId("apps-result")).toHaveText("Linear is removed from Kami.");
  await expect(page.getByTestId("app-state-linear")).toHaveText("Not connected");
  expect((await calls("apps.remove")).map((c) => c.params)).toEqual([{ bot: "kami", name: "linear" }]);

  await mock("mock.appsNext", { verb: "login", line: "✗ Authentication failed: access_denied" });
  await page.getByTestId("app-login-figma").click();
  await expect(page.getByTestId("apps-result")).toHaveText("✗ Authentication failed: access_denied");
  await expect(page.getByTestId("apps-result")).toHaveAttribute("role", "alert");
  await expect(page.getByTestId("app-state-figma")).toHaveText("Needs sign-in");

  await expect(page.getByTestId("app-card-asana")).toContainText("Asks for ASANA_CLIENT_SECRET");
  await page.getByTestId("app-install-asana").click();
  await expect(page.getByTestId("apps-result")).toContainText("✗ install failed: ASANA_CLIENT_SECRET is required but no value was provided");
  await expect(page.getByTestId("apps-terminal-cmd")).toHaveText(/hermes -p kami mcp install asana/);
  await expect(page.getByTestId("apps-terminal")).toBeVisible();
});

test("the scope chip switches bots; another bot starts with nothing connected", async ({ page }) => {
  await openApps(page);
  await page.getByTestId("apps-scope").click();
  await page.getByTestId("apps-scope-friren").click();
  await expect(page.getByTestId("apps-scope")).toContainText("Friren's apps");
  await expect(page.getByTestId("app-state-linear")).toHaveText("Not connected");
  await expect(page.getByTestId("app-card-google-workspace")).toHaveCount(0);
  await page.getByTestId("app-install-linear").click();
  await expect(page.getByTestId("apps-result")).toHaveText("Linear is added to Friren. Sign in to finish.");
  expect((await calls("apps.install")).map((c) => c.params)).toEqual([{ bot: "friren", name: "linear" }]);
});

test("the page translates (ko) with no raw keys", async ({ page }) => {
  await openApps(page);
  await page.evaluate(() => localStorage.setItem("omher.lang", "ko"));
  await page.reload();
  await page.getByTestId("nav-apps").click();
  await expect(page.getByTestId("apps-sec-work")).toContainText("업무 앱");
  await expect(page.getByTestId("app-state-linear")).toHaveText("연결됨");
  await expect(page.getByTestId("apps")).not.toContainText("apps.");
});
