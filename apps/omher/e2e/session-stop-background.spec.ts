// Work a coding agent left running in the background after its turn ended can be stopped (Claude Code 2.1.323,
// the event order of src-tauri/tests/fixtures/real/claude-13-late-ask-stop.jsonl and claude-14-background-stop.jsonl,
// mock host `/lateask` and `/background`): a quiet "Stop" beside "1 still running in the background" while no turn
// runs, never while one runs (the composer's Stop is the turn's), only for an agent whose own Stop reaches that work;
// pressing it sends the agent's own interrupt, the subagent row ends stopped, the count goes, an open late ask reads
// "Not answered" and the header is Ready. Esc keeps stopping a running turn only. Also: the fan-out card and the
// subagent's ask under it end at one right edge, the card's head says "Waiting" while its only row waits on the
// person, and the needs strip never ends on a lone " · ". With OMHER_SHOTS=<dir> it writes
// orch-stop-bg-<tag>-{dark,light}.png (OMHER_SHOT_TAG, default "after").
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || "";
const TAG = process.env.OMHER_SHOT_TAG || "after";

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "sb1", op, ...params }));
  });
  ws.close();
}

type Call = { op: string; input?: { kind: string; [k: string]: unknown } };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));
const interrupts = async (page: Page) => (await calls(page)).filter((c) => c.input?.kind === "interrupt").length;

async function session(page: Page, agent: "claude" | "codex", first: string, theme: "dark" | "light" = "dark") {
  await page.emulateMedia({ colorScheme: theme });
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/web-app";
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  // staged shots never show a bot named after the product
  await mock("bots.rename", { bot: "default", name: "Mira" });
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill(first);
  await page.keyboard.press("Enter");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

for (const theme of SHOTS ? (["dark", "light"] as const) : (["dark"] as const)) {
  test(`with no turn running, Stop beside the background label stops the background subagent and its ask (${theme})`, async ({ page }) => {
    await session(page, "claude", "/lateask", theme);
    await expect(page.getByTestId("session-background")).toHaveText("1 still running in the background");
    await expect(page.getByTestId("card-approval")).toBeVisible();
    if (SHOTS) {
      // before any assertion on the new parts, so the same spec on the unfixed tree writes the before shots
      mkdirSync(SHOTS, { recursive: true });
      await page.mouse.move(640, 700);
      await page.screenshot({ path: join(SHOTS, `orch-stop-bg-${TAG}-${theme}.png`), animations: "disabled" });
    }
    const stop = page.getByTestId("session-background-stop");
    await expect(stop).toHaveText("Stop");
    await expect(stop).toHaveAttribute("title", "Stop what still runs in the background");
    // a quiet word, not a boxed button: no border, no fill, the label's size
    const look = await stop.evaluate((e) => {
      const c = getComputedStyle(e);
      return { border: c.borderTopWidth, bg: c.backgroundColor, size: c.fontSize };
    });
    expect(look).toEqual({ border: "0px", bg: "rgba(0, 0, 0, 0)", size: "11.5px" });
    // the composer keeps Send: the person may type the next message instead
    await expect(page.getByTestId("send")).toBeVisible();
    await expect(page.getByTestId("stop")).toHaveCount(0);
    await stop.click();
    // the agent's own interrupt, once
    expect(await interrupts(page)).toBe(1);
    const row = page.getByTestId("subagent-row");
    await expect(row).toHaveAttribute("data-state", "cancelled");
    await expect(row.getByTestId("subagent-state")).toHaveText("stopped");
    await expect(page.getByTestId("session-background")).toHaveCount(0);
    await expect(stop).toHaveCount(0);
    await expect(page.getByTestId("card-line").filter({ hasText: "echo gamma > c.txt" })).toContainText("Not answered");
    await expect(page.getByTestId("card-approval")).toHaveCount(0);
    await expect(page.getByTestId("session-status")).toHaveText("Ready");
  });
}

test("a background command left after the turn: Stop stops it; Esc does not", async ({ page }) => {
  await session(page, "claude", "/background hold");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("session-background")).toHaveText("1 still running in the background");
  // Esc stops a running turn only: with none running it leaves the background work alone
  await page.getByTestId("composer").focus();
  await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
  expect(await interrupts(page)).toBe(0);
  await expect(page.getByTestId("session-background")).toBeVisible();
  await page.getByTestId("session-background-stop").click();
  await expect(page.getByTestId("session-background")).toHaveCount(0);
  expect(await interrupts(page)).toBe(1);
});

test("no background Stop while a turn runs: the composer's Stop is the turn's", async ({ page }) => {
  await session(page, "claude", "/background busy");
  await expect(page.getByTestId("session-background")).toBeVisible();
  await expect(page.getByTestId("session-status")).toHaveText("Working");
  await expect(page.getByTestId("stop")).toBeVisible();
  await expect(page.getByTestId("session-background-stop")).toHaveCount(0);
});

test("an agent whose Stop cannot reach its background work gets the label and no Stop", async ({ page }) => {
  await session(page, "codex", "/background hold");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("session-background")).toBeVisible();
  await expect(page.getByTestId("session-background-stop")).toHaveCount(0);
});

test("the subagent's card and its ask end at one right edge; the head says Waiting; the strip keeps each · with its word", async ({ page }) => {
  await session(page, "claude", "/lateask");
  const card = page.getByTestId("fanout-card");
  const ask = page.getByTestId("card-approval");
  await expect(ask).toBeVisible();
  const [a, b] = await Promise.all([card.boundingBox(), ask.boundingBox()]);
  expect(Math.abs(a!.x + a!.width - (b!.x + b!.width))).toBeLessThanOrEqual(1);
  expect(Math.abs(a!.x - b!.x)).toBeLessThanOrEqual(1);
  // its only row waits on the person: the head says so in the rows' amber, without the working spinner
  await expect(card.getByTestId("fanout-summary")).toHaveText(/^Waiting · 0 of 1 done · \d+s$/);
  await expect(card).toHaveAttribute("data-waiting", "true");
  await expect(card.locator(".sa-head [role=status], .sa-head .ui-spin")).toHaveCount(0);
  const [head, rowState] = await Promise.all([
    card.getByTestId("fanout-summary").evaluate((e) => getComputedStyle(e).color),
    card.getByTestId("subagent-state").evaluate((e) => getComputedStyle(e).color),
  ]);
  expect(head).toBe(rowState);
  // looking elsewhere, the strip names it; a cut line can only end inside a word, never on a lone " · "
  await page.getByTestId("bot-friren").click();
  const line = page.getByTestId("needs-line");
  await expect(line).toHaveText("1 needs you · web-app · Claude Code: Allow echo gamma > c.txt?");
  const loose = await line.evaluate((el) => {
    const out: string[] = [];
    const walk = (n: Node) => {
      for (const c of Array.from(n.childNodes)) {
        if (c.nodeType === Node.TEXT_NODE && /·\s*$/.test(c.textContent ?? "") && !(c.parentElement?.classList.contains("needs-sep"))) out.push(c.textContent!);
        else walk(c);
      }
    };
    walk(el);
    return out;
  });
  expect(loose).toEqual([]);
  expect(await line.locator(".needs-sep").evaluateAll((els) => els.map((e) => getComputedStyle(e).display))).toEqual(["inline-block", "inline-block"]);
});
