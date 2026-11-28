// A file edit's change keeps its line numbers (src/chat/activity/diffLines.ts): against the mock bridge's `/diff` turn,
// whose one `tool.diff` has two hunks, the diff view draws an old and a new number beside each line (a context line
// both, a removed line the old one, an added line the new one), a thin rule between the hunks, and a line's text is
// the line alone. Checked at the chat's narrow width, in dark and light.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || process.env.OMHER_SHOTS_DIR || "";

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

async function openDiff(page: Page, theme: "dark" | "light") {
  await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
  await page.setViewportSize({ width: 760, height: 820 });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("composer").fill("/diff fix calc");
  await page.getByTestId("composer").press("Enter");
  const act = page.locator("[data-testid=activity][data-state=done]").last();
  await act.getByTestId("activity-toggle").click();
  await act.getByTestId("activity-step").first().click();
  const view = act.getByTestId("diff-view");
  await expect(view).toHaveCount(1);
  return view;
}

for (const theme of ["dark", "light"] as const)
  test(`a diff shows old and new line numbers per hunk, a rule between hunks (${theme})`, async ({ page }) => {
    const view = await openDiff(page, theme);
    const rows = view.locator(".dv-l:not(.hunk)");
    const got = await rows.evaluateAll((els) =>
      els.map((e) => [e.getAttribute("data-kind"), e.getAttribute("data-old"), e.getAttribute("data-new"), e.textContent]),
    );
    expect(got).toEqual([
      ["ctx", "5", "5", "def sub(a, b):"],
      ["del", "6", null, "    return a + b"],
      ["add", null, "6", "    return a - b"],
      ["add", null, "7", " "],
      ["ctx", "7", "8", " "],
      ["ctx", "98", "99", "def mul(a, b):"],
      ["add", null, "100", "    return a * b"],
    ]);
    // one rule between the two hunks, none above the first
    await expect(view.locator(".dv-l.hunk")).toHaveCount(1);
    // the drawn numbers: right-aligned gutters left of the mark and the text, never overlapping them
    const geo = await view.locator(".dv-l.add").last().evaluate((el) => {
      const [o, n] = [...el.querySelectorAll(".dv-no")] as HTMLElement[];
      const box = el.getBoundingClientRect();
      const pad = parseFloat(getComputedStyle(el).paddingLeft);
      return {
        old: getComputedStyle(o, "::before").content,
        neu: getComputedStyle(n, "::before").content,
        nRight: n.getBoundingClientRect().right - box.left,
        sign: parseFloat(getComputedStyle(el, "::before").left),
        pad,
        color: getComputedStyle(n).color,
        ink: getComputedStyle(el).color,
      };
    });
    expect(geo.old).toBe('""');
    expect(geo.neu).toBe('"100"');
    expect(geo.nRight).toBeLessThanOrEqual(geo.sign);
    expect(geo.sign).toBeLessThan(geo.pad);
    expect(geo.color).not.toBe(geo.ink);
    if (SHOTS) {
      mkdirSync(SHOTS, { recursive: true });
      await view.screenshot({ path: join(SHOTS, `diff-lines-${theme}.png`) });
    }
  });
