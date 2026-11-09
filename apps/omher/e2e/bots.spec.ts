// Bots: rename, change the picture, and look through every bot (Settings → All bots / bot page).
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = join(dirname(fileURLToPath(import.meta.url)), "__shots__");

// 4x2 PNG: wider than tall, so the editor must crop it to a square.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAQAAAACCAYAAAB/qH1jAAAAEklEQVR4nGP4z9DwHxkzoAsAAFEhE/F9lUWJAAAAAElFTkSuQmCC",
  "base64",
);

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
}

async function botPage(page: Page, name = "kami") {
  await page.getByTestId("nav-settings").click();
  await page.getByTestId(`settings-nav-bot-${name}`).click();
  await expect(page.getByTestId("bot-head")).toBeVisible();
}

test.use({ colorScheme: "dark" });

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("rename: pencil, type, Enter saves; the new name shows everywhere and the profile id stays", async ({ page }) => {
  await open(page);
  await botPage(page);
  await expect(page.getByTestId("bot-name")).toHaveText("Kami");
  await page.getByTestId("rename").click();
  const field = page.getByTestId("rename-input");
  await expect(field).toBeFocused();
  await expect(page.getByText("The profile stays")).toBeVisible();
  await field.fill("  Kami   the Helper ");
  await field.press("Enter");
  await expect(page.getByTestId("bot-name")).toHaveText("Kami the Helper");
  await expect(page.getByTestId("bot-kami").locator(".bot-n")).toHaveText("Kami the Helper"); // sidebar
  await expect(page.getByTestId("settings-nav-bot-kami")).toContainText("Kami the Helper");
  await expect(page.locator(".st-row", { hasText: "Profile id" })).toContainText("kami"); // the id is unchanged
  expect((await callsOf("bots.rename")).map((c) => c.params)).toEqual([{ bot: "kami", name: "Kami   the Helper" }]);

  // Escape cancels without a call; empty goes back to the profile's own name
  await page.getByTestId("rename").click();
  await page.getByTestId("rename-input").fill("nope");
  await page.getByTestId("rename-input").press("Escape");
  await expect(page.getByTestId("bot-name")).toHaveText("Kami the Helper");
  await page.getByTestId("rename").click();
  await page.getByTestId("rename-input").fill("");
  await page.getByTestId("rename-save").click();
  await expect(page.getByTestId("bot-name")).toHaveText("Kami");
  expect(await callsOf("bots.rename")).toHaveLength(2);
});

test("rename: a name over 64 characters shows the bridge's reason and keeps editing", async ({ page }) => {
  await open(page);
  await botPage(page);
  await page.getByTestId("rename").click();
  // maxLength stops typing past 64, so send one over the wire the way a paste-race could
  await page.getByTestId("rename-input").evaluate((el: HTMLInputElement) => el.removeAttribute("maxlength"));
  await page.getByTestId("rename-input").fill("x".repeat(70));
  await page.getByTestId("rename-save").click();
  await expect(page.getByRole("alert")).toContainText("too long");
  await expect(page.getByTestId("rename-input")).toBeVisible();
});

test("picture: choose a file, it is cropped square and shows on every avatar; reset brings the face back", async ({ page }) => {
  await open(page);
  await botPage(page);
  await expect(page.getByTestId("avatar-reset")).toHaveCount(0);
  await page.getByTestId("avatar-file").setInputFiles({ name: "me.png", mimeType: "image/png", buffer: PNG });

  const own = page.getByTestId("bot-kami").locator("img.ui-av");
  await expect(own).toHaveAttribute("data-own", "1"); // sidebar row
  await expect(page.getByTestId("avatar-edit").locator("img")).toHaveAttribute("data-own", "1");
  const sent = (await callsOf("bots.set_avatar"))[0].params as { bot: string; data: string };
  expect(sent.bot).toBe("kami");
  expect(sent.data.startsWith("data:image/png;base64,")).toBe(true);
  const size = await page.evaluate(async (src) => {
    const i = new Image();
    i.src = src;
    await i.decode();
    return [i.naturalWidth, i.naturalHeight];
  }, sent.data);
  expect(size).toEqual([256, 256]);
  await expect(page.getByTestId("bot-head")).toBeVisible();

  await page.getByTestId("avatar-reset").click();
  await expect(own).not.toHaveAttribute("data-own", "1");
  await expect(page.getByTestId("avatar-reset")).toHaveCount(0);
  expect((await callsOf("bots.set_avatar")).at(-1)!.params).toEqual({ bot: "kami", clear: true });
});

test("picture: a file that is not an image is refused before anything is sent", async ({ page }) => {
  await open(page);
  await botPage(page);
  await page.getByTestId("avatar-file").setInputFiles({ name: "x.gif", mimeType: "image/gif", buffer: Buffer.from("GIF89a") });
  await expect(page.getByTestId("avatar-error")).toHaveText("Use a PNG, JPEG or WebP picture");
  expect(await callsOf("bots.set_avatar")).toEqual([]);
});

test("bot page: what the bot has done (sessions per place, skills, routines)", async ({ page }) => {
  await open(page);
  await botPage(page);
  const facts = page.getByTestId("bot-facts");
  await expect(facts).toContainText("141");
  await expect(facts).toContainText("sessions elsewhere");
  await expect(facts).toContainText("134");
  await expect(facts).toContainText("skills");
  await expect(facts).toContainText("2routines");
  const places = page.getByTestId("bot-places");
  await expect(places).toContainText("Slack78");
  await expect(places).toContainText("Discord48");
  await expect(places).toContainText("Cron15");
  await expect(places).toContainText("since");
  await page.getByTestId("bot-open-chat").click();
  await expect(page.getByTestId("settings-view")).toHaveCount(0);
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
});

test("All bots: a card per bot with status, model and places; search filters; a card opens the bot", async ({ page }) => {
  await open(page);
  await page.getByTestId("nav-settings").click();
  await page.getByTestId("settings-nav-bots").click();
  const grid = page.getByTestId("bots-grid");
  await expect(grid.locator(".bot-card")).toHaveCount(3);
  await expect(page.getByTestId("settings-nav-bots")).toContainText("3");
  const kami = page.getByTestId("bot-card-kami");
  await expect(kami).toContainText("Kami");
  await expect(kami).toContainText("Working");
  await expect(kami).toContainText("Opus 5.5");
  await expect(kami).toContainText("78");
  await expect(page.getByTestId("bot-card-default")).toContainText("Connected");

  await page.getByTestId("bots-search").fill("research");
  await expect(grid.locator(".bot-card")).toHaveCount(1);
  await expect(page.getByTestId("bot-card-friren")).toBeVisible();
  await page.getByTestId("bots-search").fill("zzz");
  await expect(grid).toContainText("No bot matches");
  await page.getByTestId("bots-search").fill("");

  await kami.click();
  await expect(page.getByTestId("bot-name")).toHaveText("Kami");
});

test("Details panel Edit opens that bot's page", async ({ page }) => {
  await open(page);
  await page.getByTestId("who").click();
  await page.getByTestId("details-edit").click();
  await expect(page.getByTestId("settings-view")).toBeVisible();
  await expect(page.getByTestId("bot-name")).toHaveText("Kami");
});

test("screenshots: All bots and a bot page with its own picture, dark and light", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 1200, height: 760 });
  await open(page);
  await botPage(page);
  const mark = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "src", "assets", "omher-mark.png"));
  await page.getByTestId("avatar-file").setInputFiles({ name: "me.png", mimeType: "image/png", buffer: mark });
  await expect(page.getByTestId("bot-kami").locator("img.ui-av")).toHaveAttribute("data-own", "1");
  await page.screenshot({ path: join(SHOTS, "bots-page-dark.png") });
  await page.getByTestId("settings-nav-bots").click();
  await expect(page.getByTestId("bot-card-kami").locator(".bc-place")).toHaveCount(3);
  await page.screenshot({ path: join(SHOTS, "bots-all-dark.png") });
  await page.emulateMedia({ colorScheme: "light" });
  await page.getByTestId("settings-nav-general").click();
  await page.getByTestId("theme-seg").getByRole("radio", { name: "Light" }).click();
  await page.getByTestId("settings-nav-bots").click();
  await expect(page.getByTestId("bot-card-kami").locator(".bc-place")).toHaveCount(3);
  await page.screenshot({ path: join(SHOTS, "bots-all-light.png") });
});
