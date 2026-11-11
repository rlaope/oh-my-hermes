// Shots for the SESSIONS attach work: paste a picture, drop a file, and the sent bubble, in a Claude Code chat.
// Run with OMHER_SHOTS=<dir> OMHER_SHOT_TAG=before|after.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";
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

test.beforeEach(async () => {
  await mock("mock.reset");
});

async function running(page: Page, theme: string) {
  await page.addInitScript((t) => {
    localStorage.setItem("omher.theme", t);
    localStorage.removeItem("omher.sessions.recent");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/omher";
  }, theme);
  await page.goto("/");
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("/status");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
}

async function paste(page: Page, png: number[]) {
  await page.getByTestId("composer").focus();
  await page.evaluate((bytes) => {
    const dt = new DataTransfer();
    dt.items.add(new File([new Uint8Array(bytes)], "image.png", { type: "image/png" }));
    const el = document.querySelector<HTMLTextAreaElement>("[data-testid=composer]")!;
    el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
  }, png);
}

for (const theme of ["dark", "light"] as const) {
  test(`shots ${theme}`, async ({ page }) => {
    test.skip(!SHOTS, "no shot folder");
    mkdirSync(SHOTS, { recursive: true });
    await running(page, theme);
    await page.getByTestId("composer").fill("What does this picture say?");
    await paste(page, [...PNG]);
    await page.waitForTimeout(300);
    await page.mouse.move(900, 790);
    await page.screenshot({ path: join(SHOTS, `sessions-attach-paste-${TAG}-${theme}.png`), animations: "disabled" });

    const dt = await page.evaluateHandle(() => {
      const d = new DataTransfer();
      d.items.add(new File(["first line\nsecond line\n"], "notes.txt", { type: "text/plain" }));
      return d;
    });
    const pane = page.locator(".pane");
    await pane.dispatchEvent("dragenter", { dataTransfer: dt });
    await pane.dispatchEvent("dragover", { dataTransfer: dt });
    await page.waitForTimeout(200);
    await page.screenshot({ path: join(SHOTS, `sessions-attach-drop-${TAG}-${theme}.png`), animations: "disabled" });
    await pane.dispatchEvent("drop", { dataTransfer: dt });
    await page.waitForTimeout(200);

    if (TAG === "after") {
      await page.getByTestId("send").click();
      await expect(page.getByTestId("sent-files").last()).toBeVisible();
      await expect(page.getByTestId("session-status")).toHaveText("Ready", { timeout: 5000 });
    } else {
      await page.keyboard.press("Enter");
      await page.waitForTimeout(1200);
    }
    await page.mouse.move(900, 790);
    await page.screenshot({ path: join(SHOTS, `sessions-attach-sent-${TAG}-${theme}.png`), animations: "disabled" });
  });
}
