// Settings node: model + reasoning pill/popover, the settings view, and the add-bot popover.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = join(dirname(fileURLToPath(import.meta.url)), "__shots__");

test.use({ colorScheme: "dark" });

/** One request to the mock bridge over its own websocket (mock.reset, mock.calls). */
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

const callsOf = async (op: string) =>
  ((await mock("mock.calls")).calls as { op: string; params: Record<string, unknown> }[]).filter((c) => c.op === op);

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("model pill: one control, popover lists providers and models with the current one checked", async ({ page }) => {
  await open(page);
  const right = page.getByTestId("head-right");
  await expect(right.locator(":scope > *")).toHaveCount(1);
  expect(await right.locator("button, a, [role=button], input, select").count()).toBe(1);
  const pill = page.getByTestId("model-pill");
  await expect(pill).toContainText("Opus 5.5");
  await expect(pill).toContainText("High");

  await pill.click();
  const pop = page.getByTestId("model-pop");
  await expect(pop).toBeVisible();
  await expect(pop.getByText("Claude (proxy)")).toBeVisible();
  await expect(pop.getByText("OpenAI")).toBeVisible();
  const opts = pop.getByTestId("model-opt");
  await expect(opts).toHaveCount(5);
  const on = pop.locator(".mp-opt.on");
  await expect(on).toHaveCount(1);
  await expect(on).toContainText("Opus 5.5");
  // selection is gray, never the brand gradient
  expect(await on.evaluate((el) => getComputedStyle(el).backgroundImage)).toBe("none");
  await expect(pop.getByRole("radio", { name: "High" })).toHaveAttribute("aria-checked", "true");
  for (const label of ["Off", "Low", "Med", "High", "Max"]) await expect(pop.getByRole("radio", { name: label })).toBeVisible();

  // Escape closes
  await page.keyboard.press("Escape");
  await expect(pop).toHaveCount(0);
});

test("changing reasoning and model calls chat.set_model and updates the pill", async ({ page }) => {
  await open(page);
  await page.getByTestId("model-pill").click();
  const pop = page.getByTestId("model-pop");
  await pop.getByRole("radio", { name: "Max" }).click();
  await expect(page.getByTestId("reasoning-label")).toHaveText("Max");
  await expect(pop.getByRole("radio", { name: "Max" })).toHaveAttribute("aria-checked", "true");
  await expect.poll(async () => (await callsOf("chat.set_model")).map((c) => c.params)).toEqual([
    { bot: "kami", reasoning: "xhigh" },
  ]);

  await pop.getByTestId("model-opt").filter({ hasText: "gpt-5.5-mini" }).click();
  await expect(page.getByTestId("model-label")).toHaveText("gpt-5.5-mini");
  await expect(pop.locator(".mp-opt.on")).toContainText("gpt-5.5-mini");
  const calls = await callsOf("chat.set_model");
  expect(calls[1].params).toEqual({ bot: "kami", model: "gpt-5.5-mini", provider: "openai" });
  await expect(page.getByTestId("model-note")).toHaveCount(0);
});

test("unsupported: one gray note, the old value stays", async ({ page }) => {
  // The mock always accepts chat.set_model; answer it `unsupported` in the page's socket instead.
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (msg.op === "chat.set_model") {
        ws.send(JSON.stringify({ id: msg.id, ok: false, error: { code: "unsupported", message: "Hermes cannot change this yet" } }));
        return;
      }
      server.send(raw);
    });
  });
  await open(page);
  await page.getByTestId("model-pill").click();
  const pop = page.getByTestId("model-pop");
  await pop.getByRole("radio", { name: "Low" }).click();
  const note = page.getByTestId("model-note");
  await expect(note).toHaveText("Change it in Hermes for now");
  await expect(page.getByTestId("reasoning-label")).toHaveText("High");
  await expect(pop.getByRole("radio", { name: "High" })).toHaveAttribute("aria-checked", "true");
  const color = await note.evaluate((el) => getComputedStyle(el).color);
  const [r, g, b] = color.match(/\d+/g)!.map(Number);
  expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThan(24); // gray, not a colour
});

test("settings opens and closes; theme Light sets data-theme; bot and provider pages", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => localStorage.removeItem("omher.theme"));
  await open(page);
  await page.getByTestId("nav-settings").click();
  const view = page.getByTestId("settings-view");
  await expect(view).toBeVisible();
  await expect(page.getByTestId("composer")).toHaveCount(0);
  for (const label of ["Kami", "Friren", "Hermes", "General", "Providers", "Computer"])
    await expect(view.locator(".st-nav").getByRole("button", { name: label, exact: true })).toBeVisible();

  // General: theme
  await expect(page.getByTestId("settings-nav-general")).toHaveAttribute("aria-current", "page");
  const theme = page.getByTestId("theme-seg");
  await expect(theme.getByRole("radio", { name: "System" })).toHaveAttribute("aria-checked", "true");
  await theme.getByRole("radio", { name: "Light" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(await page.evaluate(() => localStorage.getItem("omher.theme"))).toBe("light");
  await theme.getByRole("radio", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  // Bot page: Profile, Model, Work
  await page.getByTestId("settings-nav-bot-friren").click();
  const body = page.getByTestId("settings-page-bot-friren");
  await expect(body.locator(".st-gh")).toHaveText(["Profile", "Model", "Work"]);
  await expect(body).toContainText("Sonnet 5.5");
  await expect(body).toContainText("Med");
  await expect(body).toContainText("friren");

  // Providers: read-only list from models.options
  await page.getByTestId("settings-nav-providers").click();
  const list = page.getByTestId("providers-list");
  await expect(list).toContainText("Claude (proxy)");
  await expect(list).toContainText("OpenAI");
  await expect(list.locator("input, select, textarea")).toHaveCount(0);

  await page.getByTestId("settings-nav-computer").click();
  await expect(page.getByTestId("settings-page-computer")).toContainText("Soon");

  // close with the header button
  await page.getByRole("button", { name: "Close settings" }).click();
  await expect(view).toHaveCount(0);
  await expect(page.getByTestId("composer")).toBeVisible();

  // the popover's "Bot settings" link opens the bot's page
  await page.getByTestId("model-pill").click();
  await page.getByRole("button", { name: "Bot settings" }).click();
  await expect(page.getByTestId("settings-page-bot-kami")).toBeVisible();
  await page.getByTestId("nav-settings").click();
  await expect(page.getByTestId("settings-view")).toHaveCount(0);
});

test("add bot: lists profiles with status; Connect re-reads bots.list; create is disabled", async ({ page }) => {
  // Show the default profile as not connected until something attaches it (a models.options read).
  let attached = false;
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    const ops = new Map<string, string>();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      ops.set(msg.id, msg.op);
      if (msg.op === "models.options" && msg.bot === "default") attached = true;
      server.send(raw);
    });
    server.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (ops.get(msg.id) === "bots.list" && msg.ok && !attached) {
        for (const b of msg.result.bots) if (b.name === "default") b.status = "offline";
        ws.send(JSON.stringify(msg));
        return;
      }
      ws.send(raw);
    });
  });
  await open(page);
  const before = (await callsOf("bots.list")).length;
  await page.getByRole("button", { name: "Add a bot" }).click();
  const pop = page.getByTestId("addbot");
  await expect(pop).toBeVisible();
  await expect(pop.getByText("Connect a Hermes profile")).toBeVisible();
  for (const name of ["Kami", "Friren", "Hermes"]) await expect(pop.getByText(name, { exact: true })).toBeVisible();
  await expect(page.getByTestId("addbot-kami")).toContainText("Connected");
  const hermes = page.getByTestId("addbot-default");
  await expect(hermes).toContainText("Not connected");
  await expect(page.getByTestId("addbot-kami").getByRole("button", { name: "Connect" })).toHaveCount(0);
  const create = page.getByTestId("addbot-create");
  await expect(create).toBeDisabled();
  await expect(create).toContainText("Soon");

  await hermes.getByRole("button", { name: "Connect" }).click();
  await expect(hermes).toContainText("Connected");
  await expect(hermes.getByRole("button", { name: "Connect" })).toHaveCount(0);
  expect((await callsOf("bots.list")).length).toBeGreaterThan(before);
  // no file copied, no chat touched: only read ops were sent
  const ops = new Set(((await mock("mock.calls")).calls as { op: string }[]).map((c) => c.op));
  for (const op of ["chat.send", "chat.set_model"]) expect(ops.has(op)).toBe(false);

  await page.keyboard.press("Escape");
  await expect(pop).toHaveCount(0);
});

test("screenshots: settings in dark and light", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => localStorage.removeItem("omher.theme"));
  await open(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-bot-kami").click();
  await expect(page.getByTestId("settings-page-bot-kami")).toContainText("Opus 5.5");
  await expect(page.getByTestId("settings-page-bot-kami")).toContainText("2 routines");
  await page.mouse.move(700, 600);
  await page.screenshot({ path: join(SHOTS, "settings-dark.png") });

  await page.getByTestId("settings-nav-general").click();
  await page.getByTestId("theme-seg").getByRole("radio", { name: "Light" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByTestId("settings-nav-bot-kami").click();
  await page.mouse.move(700, 600);
  await page.waitForTimeout(400); // let colour transitions settle
  await page.screenshot({ path: join(SHOTS, "settings-light.png") });
});
