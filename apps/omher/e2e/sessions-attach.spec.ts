// Files in a SESSIONS chat (mock host): the composer of a chat agent has the bot chat's + and takes files by paste,
// the + menu and a drop on the chat, in a running chat and in a draft, with the same chips and limits. The first
// send of a draft carries its files; the sent bubble shows them, also after a reload; a file that cannot be saved
// sends nothing and keeps the chips. A file dropped on a terminal is saved and its path typed at the prompt.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const PNG = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "fixtures", "media", "chart.png"));

async function mock(op: string): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op }));
  });
  ws.close();
}

type Call = { op: string; agent?: string; session?: string; name?: string; size?: number; path?: string; data?: string; input?: { kind: string; text?: string; images?: string[] } };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function open(page: Page) {
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/omher";
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function draft(page: Page, agent: string) {
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await expect(page.getByTestId("session-chat")).toHaveAttribute("data-draft", "true");
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
}

async function running(page: Page, agent = "claude") {
  await draft(page, agent);
  await page.getByTestId("composer").fill("/status");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
}

async function paste(page: Page, name: string, type: string, bytes: number[]) {
  await page.getByTestId("composer").focus();
  await page.evaluate(
    ([n, t, b]) => {
      const dt = new DataTransfer();
      dt.items.add(new File([new Uint8Array(b as number[])], n as string, { type: t as string }));
      document.querySelector("[data-testid=composer]")!.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
    },
    [name, type, bytes] as const,
  );
}

async function drop(page: Page, target: string, files: { name: string; type: string; text?: string; size?: number }[]) {
  const dt = await page.evaluateHandle((list) => {
    const d = new DataTransfer();
    for (const f of list) d.items.add(new File([f.size ? new Uint8Array(f.size) : (f.text ?? "x")], f.name, { type: f.type }));
    return d;
  }, files);
  const el = page.locator(target).first();
  await el.dispatchEvent("dragenter", { dataTransfer: dt });
  await el.dispatchEvent("dragover", { dataTransfer: dt });
  await el.dispatchEvent("drop", { dataTransfer: dt });
}

async function pick(page: Page, files: { name: string; mimeType: string; buffer: Buffer }[]) {
  const chooser = page.waitForEvent("filechooser");
  await page.getByTestId("attach").click();
  await (await chooser).setFiles(files);
}

const chipNames = (page: Page) => page.getByTestId("attach-chip").evaluateAll((els) => els.map((e) => e.getAttribute("data-name")));

test("a running Claude Code chat has the +, and paste, pick and drop each add a chip; send carries them", async ({ page }) => {
  await open(page);
  await running(page);
  await expect(page.getByTestId("attach")).toBeVisible();
  await paste(page, "image.png", "image/png", [...PNG]);
  await pick(page, [{ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("first\nsecond\n") }]);
  await drop(page, ".pane", [{ name: "data.csv", type: "text/csv", text: "a,b\n1,2\n" }]);
  expect(await chipNames(page)).toEqual(["image.png", "notes.txt", "data.csv"]);
  await expect(page.getByTestId("attach-chip").first().locator("img.att-thumb")).toBeVisible();
  await page.getByTestId("composer").fill("what is in these?");
  await page.getByTestId("send").click();
  await expect(page.getByTestId("attach-chips")).toHaveCount(0);
  const sent = page.getByTestId("bubble-user").last();
  await expect(sent).toContainText("what is in these?");
  await expect(sent.getByTestId("media-image")).toHaveCount(1);
  await expect(sent.getByTestId("sent-file")).toHaveCount(2);
  const c = await calls(page);
  expect(c.filter((x) => x.op === "file.save").map((x) => x.name)).toEqual(["image.png", "notes.txt", "data.csv"]);
  const input = c.filter((x) => x.op === "chat.input").pop()!.input!;
  expect(input.images).toEqual([expect.stringMatching(/\/\.omher\/session-files\/s\d+\/1-image\.png$/)]);
  expect(input.text).toMatch(/^what is in these\?\n\nAttached files \(copies omher saved; open them with your tools\):\n- .*1-notes\.txt\n- .*1-data\.csv$/);
  // the agent answered the picture
  await expect(page.getByTestId("bubble-bot").last()).toContainText("(1 picture)");
});

test("a draft takes paste, pick and drop too, and its first send starts the agent with the files", async ({ page }) => {
  await open(page);
  await draft(page, "codex");
  await expect(page.getByTestId("attach")).toBeVisible();
  await paste(page, "image.png", "image/png", [...PNG]);
  await pick(page, [{ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("first\nsecond\n") }]);
  await drop(page, ".pane", [{ name: "spec.md", type: "text/markdown", text: "# spec" }]);
  expect(await chipNames(page)).toEqual(["image.png", "notes.txt", "spec.md"]);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-chat")).not.toHaveAttribute("data-draft", "true");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  const c = await calls(page);
  const ops = c.map((x) => x.op).filter((o) => o !== "reset" && o !== "file.prune");
  expect(ops.slice(0, 5)).toEqual(["file.save", "file.save", "file.save", "chat.start", "chat.input"]);
  expect(c.find((x) => x.op === "chat.input")!.input!.images).toHaveLength(1);
  await expect(page.getByTestId("bubble-user").first().getByTestId("sent-files")).toBeVisible();
});

test("the same limits and red chips as the bot chat; a file that cannot be saved sends nothing and keeps the chips", async ({ page }) => {
  await open(page);
  await running(page);
  await drop(page, ".pane", [{ name: "huge.bin", type: "application/octet-stream", size: 101 * 1024 * 1024 }]);
  await expect(page.getByTestId("attach-chip-note")).toHaveText("Over 100 MB");
  await page.getByTestId("attach-remove").click();
  const many = Array.from({ length: 21 }, (_, i) => ({ name: `f${i}.txt`, type: "text/plain", text: "x" }));
  await drop(page, ".pane", many);
  await expect(page.getByTestId("attach-chip").last().getByTestId("attach-chip-note")).toHaveText("Over 20 files");
  await page.getByTestId("attach-remove").last().click();
  for (let i = 0; i < 19; i++) await page.getByTestId("attach-remove").last().click();
  await page.evaluate(() => ((window as unknown as { __omherFileSaveError: string }).__omherFileSaveError = "disk full"));
  const before = (await calls(page)).filter((x) => x.op === "chat.input").length;
  await page.getByTestId("send").click();
  await expect(page.getByTestId("attach-error")).toHaveText("Couldn't attach f0.txt · disk full");
  expect(await chipNames(page)).toEqual(["f0.txt"]);
  expect((await calls(page)).filter((x) => x.op === "chat.input")).toHaveLength(before);
});

test("the sent bubble shows its files again after omher restarts", async ({ page }) => {
  await open(page);
  await running(page);
  await paste(page, "image.png", "image/png", [...PNG]);
  await page.getByTestId("composer").fill("keep this");
  await page.getByTestId("send").click();
  await expect(page.getByTestId("bubble-user").last().getByTestId("media-image")).toBeVisible();
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  // the mock host keeps saved copies in memory only, so this reload proves the bubble is put back from the record:
  // the picture is read back from the saved copy where one exists, else it shows as a file row
  await page.reload();
  await expect(page.getByTestId("session-chat")).toBeVisible();
  const bubble = page.getByTestId("bubble-user").filter({ hasText: "keep this" });
  await expect(bubble).toHaveCount(1);
  await expect(bubble.getByTestId("sent-files")).toBeVisible();
  await expect(bubble.getByText("image.png")).toBeVisible();
});

test("an oh-my-hermes session's chat has no + (Hermes takes files in a bot's main chat only)", async ({ page }) => {
  await open(page);
  await draft(page, "omh");
  await expect(page.getByTestId("composer")).toBeVisible();
  await expect(page.getByTestId("attach")).toHaveCount(0);
});

test("a file dropped on a terminal is saved and its path typed at the prompt, quoted for the shell", async ({ page }) => {
  await open(page);
  await running(page);
  await page.getByTestId("session-terminal-toggle").click();
  await expect(page.locator(".xterm-rows")).toContainText("(mock)");
  await drop(page, "[data-testid=terminal]", [{ name: "my shot.png", type: "image/png", text: "x" }]);
  // the shell's own quoting: single quotes on macOS and Linux, double quotes on Windows (the page's platform)
  const QUOTED = process.platform === "win32" ? /^"\/Users\/you\/\.omher\/session-files\/s\d+\/1-my shot\.png" $/ : /^'\/Users\/you\/\.omher\/session-files\/s\d+\/1-my shot\.png' $/;
  await expect.poll(async () => (await calls(page)).filter((x) => x.op === "write").map((x) => x.data).join("")).toMatch(QUOTED);
  expect((await calls(page)).find((x) => x.op === "file.save")).toMatchObject({ name: "my shot.png" });
});
