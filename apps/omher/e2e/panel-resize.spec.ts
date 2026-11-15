// The side panel's left edge is a drag handle: drag it to make the panel wider or narrower; the width stays after a
// reload, per kind of tab (Details, the tool tabs, Plans); a double click goes back to the usual width; the chat
// column keeps its room; ←/→ on the focused handle step it. No bridge call is made for any of it.
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
      if (msg.id === "r1") res(msg);
    };
    ws.send(JSON.stringify({ id: "r1", op, ...params }));
  });
  ws.close();
  return reply.result;
}

const width = async (page: Page) => Math.round((await page.getByTestId("details").boundingBox())?.width ?? 0);
const saved = (page: Page) => page.evaluate(() => JSON.parse(localStorage.getItem("omher.panelWidth") || "null"));

async function openPanel(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("places").click();
  await expect(page.getByTestId("details-panel")).toHaveAttribute("data-tab", "details");
  await expect.poll(() => width(page)).toBe(300);
}

/** Press on the handle and move the pointer `dx` px (negative = left = wider), then let go. */
async function dragBy(page: Page, dx: number) {
  const h = (await page.getByTestId("panel-resizer").boundingBox())!;
  const x = h.x + h.width / 2;
  const y = h.y + 200;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx, y, { steps: 6 });
  await page.mouse.up();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("drag the panel's edge wider, it stays after a reload, and double-click brings the usual width back", async ({ page }) => {
  await openPanel(page);
  await expect(page.getByTestId("panel-resizer")).toHaveCSS("cursor", "col-resize");
  await dragBy(page, -120);
  await expect.poll(() => width(page)).toBe(420);
  expect(await saved(page)).toEqual({ details: 420 });
  await expect(page.getByTestId("window")).not.toHaveClass(/panel-dragging/);

  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await expect.poll(() => width(page)).toBe(420);

  await page.getByTestId("panel-resizer").dblclick();
  await expect.poll(() => width(page)).toBe(300);
  expect(await saved(page)).toEqual({});
});

test("each kind of tab keeps its own width: Details, a tool tab, Plans", async ({ page }) => {
  await openPanel(page);
  await dragBy(page, -60);
  await expect.poll(() => width(page)).toBe(360);
  await page.getByTestId("panel-tab-diff").click();
  await expect.poll(() => width(page)).toBe(400);
  await dragBy(page, -100);
  await expect.poll(() => width(page)).toBe(500);
  await page.getByTestId("panel-tab-terminal").click();
  await expect.poll(() => width(page)).toBe(500);
  await page.getByTestId("panel-tab-details").click();
  await expect.poll(() => width(page)).toBe(360);
  expect(await saved(page)).toEqual({ details: 360, tools: 500 });
});

test("the chat column keeps its room and the panel its minimum", async ({ page }) => {
  await openPanel(page);
  const vw = page.viewportSize()!.width;
  await dragBy(page, -2000);
  await expect.poll(() => width(page)).toBe(vw - 248 - 360);
  const main = (await page.locator("main.main").boundingBox())!;
  expect(Math.round(main.width)).toBeGreaterThanOrEqual(359);
  await dragBy(page, 2000);
  await expect.poll(() => width(page)).toBe(260);
});

test("keyboard: ←/→ on the focused handle steps the width, Enter resets it", async ({ page }) => {
  await openPanel(page);
  await page.getByTestId("panel-resizer").focus();
  await page.keyboard.press("ArrowLeft");
  await expect.poll(() => width(page)).toBe(316);
  await page.keyboard.press("Shift+ArrowLeft");
  await expect.poll(() => width(page)).toBe(380);
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => width(page)).toBe(364);
  await page.keyboard.press("Enter");
  await expect.poll(() => width(page)).toBe(300);
});

test("a closed panel has no handle, and resizing makes no bridge call", async ({ page }) => {
  await openPanel(page);
  await dragBy(page, -50);
  await page.getByTestId("panel-button").click();
  await expect(page.getByTestId("panel-resizer")).toHaveCount(0);
  const ops = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(ops.filter((op: string) => /panel|width|resize/i.test(op) && !/^panel\.(worktrees|diff|terminal|schedule)/.test(op))).toEqual([]);
});
