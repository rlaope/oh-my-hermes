// Files the person sends: the + at the composer's left edge (menu above the composer), drag-and-drop onto
// the chat, paste, chips with limits, and sending as `chat.attach` for each file, then `chat.send`.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || join(homedir(), ".hermes/profiles/kami/cache/scratch/omher-v02");
const PNG = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "fixtures", "media", "chart.png"));
const PDF = Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n");

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
  return reply;
}

const sendOps = async () =>
  (await mock("mock.calls")).result.calls.filter((c: any) => c.op === "chat.attach" || c.op === "chat.send");

async function openFriren(page: Page) {
  await page.goto("/");
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("header").getByText("Friren", { exact: true })).toBeVisible();
  await expect(page.getByTestId("composer")).toBeEnabled();
}

/** Picks files through the + (one file picker, no menu) and the system file chooser. */
async function pickFiles(page: Page, files: { name: string; mimeType: string; buffer: Buffer }[]) {
  const chooser = page.waitForEvent("filechooser");
  await page.getByTestId("attach").click();
  await (await chooser).setFiles(files);
}

/** Drops files made in the page onto the chat area (a 101 MB one costs no transfer this way). */
async function dropFiles(page: Page, files: { name: string; type: string; size?: number; text?: string }[]) {
  const dt = await page.evaluateHandle((list) => {
    const d = new DataTransfer();
    for (const f of list) d.items.add(new File([f.size ? new Uint8Array(f.size) : (f.text ?? "x")], f.name, { type: f.type }));
    return d;
  }, files);
  const pane = page.locator(".pane");
  await pane.dispatchEvent("dragenter", { dataTransfer: dt });
  await pane.dispatchEvent("dragover", { dataTransfer: dt });
  await expect(page.getByTestId("attach-drop")).toHaveText("Drop to attach");
  await pane.dispatchEvent("drop", { dataTransfer: dt });
  await expect(page.getByTestId("attach-drop")).toHaveCount(0);
}

test.beforeEach(async () => {
  expect((await mock("mock.reset")).ok).toBe(true);
});

test("the + sits at the composer's left edge, level with Send, always there", async ({ page }) => {
  await openFriren(page);
  const plus = page.getByTestId("attach");
  await expect(plus).toBeVisible();
  await expect(page.getByTestId("attach-chips")).toHaveCount(0);
  const p = (await plus.boundingBox())!;
  const input = (await page.getByTestId("composer").boundingBox())!;
  const send = (await page.getByTestId("send").boundingBox())!;
  const box = (await page.getByTestId("composer-box").boundingBox())!;
  expect(Math.round(p.width)).toBe(26);
  expect(Math.round(p.height)).toBe(26);
  expect(p.x + p.width).toBeLessThanOrEqual(input.x); // typed text starts after it
  expect(p.x - box.x).toBeLessThan(14); // at the far-left edge
  expect(Math.abs(p.y + p.height / 2 - (send.y + send.height / 2))).toBeLessThanOrEqual(2);
  const style = await plus.evaluate((e) => {
    const s = getComputedStyle(e);
    return { radius: s.borderRadius, border: s.borderTopStyle, bg: s.backgroundImage };
  });
  expect(style).toEqual({ radius: "6px", border: "solid", bg: "none" }); // gray outline, never the brand gradient
});

test("the + opens one file picker (no menu); it adds chips; × removes one; a drop adds one", async ({ page }) => {
  await openFriren(page);
  await pickFiles(page, [
    { name: "one.png", mimeType: "image/png", buffer: PNG },
    { name: "two.png", mimeType: "image/png", buffer: PNG },
    { name: "report.pdf", mimeType: "application/pdf", buffer: PDF },
  ]);
  const chips = page.getByTestId("attach-chip");
  await expect(chips).toHaveCount(3);
  await expect(chips.nth(0).locator("img.att-thumb")).toBeVisible();
  await expect(chips.nth(2).locator(".att-badge")).toHaveText("PDF");
  await expect(chips.nth(0).getByTestId("attach-chip-note")).toHaveText(`${(PNG.length / 1024).toFixed(1)} KB`);
  expect(Math.round((await chips.nth(0).locator(".att-thumb").boundingBox())!.width)).toBe(24);

  // one picker for every kind of file: the + opens it straight away, with no menu of kinds in between
  const chooser = page.waitForEvent("filechooser");
  await page.getByTestId("attach").click();
  const fc = await chooser;
  expect(fc.isMultiple()).toBe(true);
  expect(await page.getByTestId("attach-file-input").getAttribute("accept")).toBeNull(); // pictures, videos and documents alike
  await expect(page.locator('[role="menu"]')).toHaveCount(0);
  await fc.setFiles([]);

  await chips.filter({ hasText: "two.png" }).getByTestId("attach-remove").click();
  await expect(chips).toHaveCount(2);
  await dropFiles(page, [{ name: "notes.txt", type: "text/plain", text: "hello" }]);
  await expect(chips).toHaveCount(3);
  await expect(chips.nth(2)).toHaveAttribute("data-name", "notes.txt");
  await expect(chips.nth(2).locator(".att-badge")).toHaveText("TXT");
  expect(await sendOps()).toEqual([]); // nothing goes until Send
});

test("send attaches each chip in order, then sends; the bubble shows the files", async ({ page }) => {
  await openFriren(page);
  await pickFiles(page, [
    { name: "one.png", mimeType: "image/png", buffer: PNG },
    { name: "two.png", mimeType: "image/png", buffer: PNG },
    { name: "report.pdf", mimeType: "application/pdf", buffer: PDF },
  ]);
  await dropFiles(page, [{ name: "notes.txt", type: "text/plain", text: "hello" }]);
  // paste of a file into the input adds a chip too
  await page.getByTestId("composer").evaluate((el) => {
    const d = new DataTransfer();
    d.items.add(new File(["clip"], "pasted.png", { type: "image/png" }));
    el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: d, bubbles: true, cancelable: true }));
  });
  await expect(page.getByTestId("attach-chip")).toHaveCount(5);
  await page.getByTestId("attach-chip").filter({ hasText: "pasted.png" }).getByTestId("attach-remove").click();

  await page.getByTestId("composer").fill("Look at these");
  await page.getByTestId("composer").press("Enter");
  await expect(page.getByTestId("attach-chip")).toHaveCount(0);
  await expect(page.getByTestId("composer")).toHaveValue("");

  const ops = await sendOps();
  expect(ops.map((c: any) => [c.op, c.params.kind ?? null, c.params.name ?? null])).toEqual([
    ["chat.attach", "image", "one.png"],
    ["chat.attach", "image", "two.png"],
    ["chat.attach", "pdf", "report.pdf"],
    ["chat.attach", "file", "notes.txt"],
    ["chat.send", null, null],
  ]);
  expect(ops.every((c: any) => c.params.bot === "friren")).toBe(true);
  expect(Buffer.from(ops[0].params.data_base64, "base64").equals(PNG)).toBe(true);
  expect(ops[4].params.text).toBe("@file:.hermes/attachments/notes.txt\n\nLook at these");

  const mine = page.getByTestId("timeline").getByTestId("bubble-user").last();
  await expect(mine.locator(".b")).toHaveText("Look at these"); // the @file ref is not shown
  await expect(mine.getByTestId("media-image")).toHaveCount(2);
  await expect(mine.getByTestId("sent-file")).toHaveCount(2);
  await expect.poll(() => mine.getByTestId("media-image").first().locator("img").evaluate((e: HTMLImageElement) => e.naturalWidth)).toBe(480);

  // the files sit under the person's bubble (6px), on its right edge: two pictures side by side, then one
  // compact row per file (icon, name, size)
  const box = (l: import("@playwright/test").Locator) => l.evaluate((e) => e.getBoundingClientRect().toJSON() as DOMRect);
  const bub = await box(mine.locator(".b"));
  const files = mine.getByTestId("sent-files");
  await expect(files).toHaveAttribute("data-grid", "2");
  const [a, b] = await Promise.all((await mine.getByTestId("media-image").all()).map(box));
  expect(Math.round(a.top - bub.bottom)).toBe(6);
  expect(Math.abs(a.top - b.top)).toBeLessThanOrEqual(1);
  expect(Math.abs(b.right - bub.right)).toBeLessThanOrEqual(1);
  for (const row of await mine.getByTestId("sent-file").all()) {
    const r = await box(row);
    expect(r.top).toBeGreaterThan(b.bottom);
    expect(Math.abs(r.right - bub.right)).toBeLessThanOrEqual(1);
    expect(r.height).toBeLessThanOrEqual(40);
    await expect(row.locator("svg.media-ic")).toHaveCount(1);
  }
  await expect(mine.getByTestId("sent-file").first().getByTestId("media-file-name")).toHaveText("report.pdf");
});

test("over-limit files show a red chip and are not sent; a failed attach sends nothing", async ({ page }) => {
  await openFriren(page);
  await dropFiles(page, [
    { name: "huge.bin", type: "application/octet-stream", size: 100 * 1024 * 1024 + 1 },
    { name: "ok.txt", type: "text/plain", text: "ok" },
  ]);
  const huge = page.getByTestId("attach-chip").filter({ hasText: "huge.bin" });
  await expect(huge).toHaveClass(/bad/);
  await expect(huge.getByTestId("attach-chip-note")).toHaveText("Over 100 MB");
  await page.getByTestId("send").click();
  await expect(page.getByTestId("attach-chip")).toHaveCount(1); // the red chip stays
  let ops = await sendOps();
  expect(ops.map((c: any) => c.params.name ?? c.op)).toEqual(["ok.txt", "chat.send"]);

  await huge.getByTestId("attach-remove").click();
  await mock("mock.reset");
  await dropFiles(page, [
    { name: "good.png", type: "image/png", text: "png" },
    { name: "fail.png", type: "image/png", text: "png" },
  ]);
  await page.getByTestId("composer").fill("try this");
  await page.getByTestId("send").click();
  await expect(page.getByTestId("attach-error")).toContainText("Couldn't attach fail.png");
  await expect(page.getByTestId("attach-chip")).toHaveCount(2); // chips kept
  await expect(page.getByTestId("composer")).toHaveValue("try this"); // text kept
  ops = await sendOps();
  expect(ops.map((c: any) => c.op)).toEqual(["chat.attach", "chat.attach"]); // no chat.send
});

test("screenshots: chips and the + menu, dark and light", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => localStorage.removeItem("omher.theme"));
  await openFriren(page);
  await page.screenshot({ path: join(SHOTS, "T2-composer-dark.png") });
  await pickFiles(page, [
    { name: "chart.png", mimeType: "image/png", buffer: PNG },
    { name: "quarterly-report-final.pdf", mimeType: "application/pdf", buffer: PDF },
  ]);
  await dropFiles(page, [{ name: "huge.mov", type: "video/quicktime", size: 100 * 1024 * 1024 + 1 }]);
  await page.getByTestId("composer").fill("What changed since last week?");
  await page.screenshot({ path: join(SHOTS, "T2-attach-dark.png") });
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.waitForTimeout(400); // let the theme transition finish
  await page.screenshot({ path: join(SHOTS, "T2-attach-light.png") });
  await page.getByTestId("attach-chip").filter({ hasText: "huge.mov" }).getByTestId("attach-remove").click();
  await page.getByTestId("send").click();
  await expect(page.getByTestId("timeline").getByTestId("sent-files")).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(SHOTS, "T2-sent-light.png") });
});
