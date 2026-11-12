// Shots for what a SESSIONS chat shows of the agent's work: a file edit's diff, the todo list, the thinking text
// and the copy control, in a Claude Code chat on the mock host. Run with OMHER_SHOTS=<dir> OMHER_SHOT_TAG=before|after.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";

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

const shot = (page: Page, what: string, theme: string) =>
  page.screenshot({ path: join(SHOTS, `sessions-transcript-${what}-${TAG}-${theme}.png`), animations: "disabled" });

const has = async (page: Page, id: string) => (await page.getByTestId(id).count()) > 0;

for (const theme of ["dark", "light"] as const) {
  test(`shots ${theme}`, async ({ page }) => {
    test.skip(!SHOTS, "no shot folder");
    mkdirSync(SHOTS, { recursive: true });
    await page.addInitScript((t) => {
      localStorage.setItem("omher.theme", t);
      localStorage.removeItem("omher.sessions.recent");
      (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/calc";
    }, theme);
    await page.goto("/");
    await page.getByTestId("session-new").click();
    await page.getByTestId("session-agent-claude").click();
    await page.getByTestId("session-folder").click();
    await page.getByTestId("session-choose").click();
    // the todo list mid-turn (before: no list; the mock answers with an echo)
    await page.getByTestId("composer").fill("/work hold");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(900);
    await page.mouse.move(900, 790);
    await shot(page, "todo", theme);
    if (await page.getByTestId("stop").isVisible()) await page.getByTestId("stop").click();
    await expect(page.getByTestId("activity").last()).not.toHaveAttribute("data-state", "live");
    await page.getByTestId("composer").fill("/work");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("activity")).toHaveCount(2);
    await expect(page.getByTestId("activity").last()).toHaveAttribute("data-state", "done");
    await page.waitForTimeout(300);

    // the diff of an edit (before: one clipped line per edit)
    await page.getByTestId("activity-toggle").last().click();
    const steps = page.getByTestId("activity").last().getByTestId("activity-step");
    if (await has(page, "plan")) await steps.nth(1).click();
    await page.mouse.move(900, 790);
    await page.waitForTimeout(350);
    await shot(page, "diff", theme);

    // thinking text, opened (before: none kept)
    if (await has(page, "thinking-toggle")) await page.getByTestId("thinking-toggle").last().click();
    await page.mouse.move(900, 790);
    await page.waitForTimeout(350);
    await shot(page, "thinking", theme);

    // copy on a hovered answer and its code block (before: none)
    const bubble = page.getByTestId("bubble-bot").last();
    await bubble.scrollIntoViewIfNeeded();
    const pre = bubble.locator(".md-pre, pre").first();
    if (await pre.count()) await pre.hover();
    else await bubble.hover();
    await page.waitForTimeout(250);
    await shot(page, "copy", theme);

    // edit and resend, both from this tree: "edit-before" is the control on the hovered last message (with the line
    // that the files stay), "edit-after" the box holding its text once Edit was pressed
    if (TAG !== "after") return;
    const editShot = (when: string) =>
      page.screenshot({ path: join(SHOTS, `sessions-transcript-edit-${when}-${theme}.png`), animations: "disabled" });
    const user = page.getByTestId("bubble-user").last();
    await user.scrollIntoViewIfNeeded();
    await user.hover();
    await page.waitForTimeout(250);
    await editShot("before");
    await page.getByTestId("bubble-edit").click();
    await expect(page.getByTestId("composer")).toHaveValue("/work");
    await expect(page.getByTestId("command-picker")).toHaveCount(0);
    await page.mouse.move(900, 790);
    await page.waitForTimeout(300);
    await editShot("after");
  });
}
