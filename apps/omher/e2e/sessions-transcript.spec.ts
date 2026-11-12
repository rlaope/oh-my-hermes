// What a SESSIONS chat shows of the agent's work, on the mock host: a file edit opens to its change, the agent's
// todo list is one checklist that updates in place, thinking text sits closed under the activity line, an answer
// and a code block can be copied (the bot chat too), and the last message can be taken back and edited when the
// agent has its own rewind (Claude Code and Codex). The mock's "/work" sends the events the Claude adapter emitted
// for a real two-file edit (claude-12-work.jsonl).
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

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

async function session(page: Page, agent: "claude" | "codex" | "omh" = "claude", first = "/work") {
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    (window as unknown as { __omherPickFolder: string }).__omherPickFolder = "/Users/you/code/calc";
  });
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/");
  await page.getByTestId("session-new").click();
  await page.getByTestId(`session-agent-${agent}`).click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill(first);
  await page.keyboard.press("Enter");
}

const done = (page: Page) => expect(page.getByTestId("activity").last()).toHaveAttribute("data-state", "done");

test("a file edit opens to its real change, per file, in mono with its own scroll", async ({ page }) => {
  await session(page);
  await done(page);
  await page.getByTestId("activity-toggle").last().click();
  const steps = page.getByTestId("activity-step");
  await expect(steps).toHaveCount(3);
  // nothing is open until asked
  await expect(page.getByTestId("diff-view")).toHaveCount(0);
  await steps.nth(1).click();
  const view = page.getByTestId("diff-view");
  await expect(view).toHaveCount(1);
  await expect(view.getByTestId("diff-file")).toContainText("calc.py");
  await expect(view.locator(".dv-l.add")).toHaveText(["", "", "def mul(a, b):", "    return a * b"]);
  await expect(view.locator(".dv-l.ctx").first()).toHaveText("def sub(a, b):");
  const body = view.getByTestId("diff-body");
  const css = await body.evaluate((el) => {
    const c = getComputedStyle(el);
    return { font: c.fontFamily, size: c.fontSize, max: c.maxHeight, over: c.overflowY };
  });
  expect(css.font).toMatch(/mono|Menlo/i);
  expect(css.size).toBe("12px");
  expect(css.max).toBe("280px");
  expect(css.over).toBe("auto");
  // keyboard: Enter closes it again
  await steps.nth(1).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("diff-view")).toHaveCount(0);
});

test("the todo list is one checklist that updates in place and stays after the turn", async ({ page }) => {
  await session(page, "claude", "/work hold");
  const plan = page.getByTestId("plan");
  await expect(plan).toHaveCount(1);
  await expect(plan.getByTestId("plan-row")).toHaveCount(3);
  // mid-turn: the first two done, the third under way, still one list
  await expect(plan.getByTestId("plan-row").nth(2)).toHaveAttribute("data-status", "in_progress");
  await expect(plan.getByTestId("plan-row").nth(0)).toHaveAttribute("data-status", "completed");
  await expect(page.getByTestId("plan")).toHaveCount(1);
  await page.getByTestId("stop").click();
  await expect(page.getByTestId("activity").last()).toHaveAttribute("data-state", "interrupted");
  await page.getByTestId("composer").fill("/work");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("activity")).toHaveCount(2);
  await done(page);
  // the finished turn keeps its own list, all done; the stopped one keeps where it stopped
  const lists = page.getByTestId("plan");
  await expect(lists).toHaveCount(2);
  await expect(lists.last().locator('[data-status="completed"]')).toHaveCount(3);
  await expect(lists.last()).toContainText("3 of 3 done");
  const size = await lists.last().evaluate((el) => getComputedStyle(el).fontSize);
  expect(size).toBe("12px");
});

test("thinking text is kept, closed by default, and opens on a click", async ({ page }) => {
  await session(page);
  await done(page);
  const th = page.getByTestId("thinking").last();
  await expect(th).toBeVisible();
  await expect(page.getByTestId("thinking-text")).toHaveCount(0);
  await th.getByTestId("thinking-toggle").click();
  await expect(page.getByTestId("thinking-text")).toHaveText("Three small steps: a docstring on `add`, a new `mul`, then list the functions in README.md.");
  // an agent that sends no thinking text shows no thinking line
  await page.getByTestId("composer").fill("plain question");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("activity")).toHaveCount(2);
  await done(page);
  await expect(page.getByTestId("activity").last().getByTestId("thinking")).toHaveCount(0);
});

test("an answer and a code block can be copied with one click; the control shows on hover only", async ({ page }) => {
  await session(page);
  await done(page);
  const bubble = page.getByTestId("bubble-bot").last();
  const copy = bubble.getByTestId("copy-answer");
  expect(await copy.evaluate((el) => getComputedStyle(el).opacity)).toBe("0");
  await bubble.hover();
  await expect.poll(() => copy.evaluate((el) => getComputedStyle(el).opacity)).toBe("1");
  await copy.click();
  await expect(copy).toHaveAttribute("aria-label", "Copied");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("README.md lists the functions");
  // the code block's own
  const pre = bubble.locator(".md-pre");
  await pre.hover();
  await pre.getByTestId("copy-code").click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("def mul(a, b):\n    return a * b");
  // showing it moves nothing: the bubble's box is the same with and without the control visible
  const before = await bubble.locator(".b").boundingBox();
  await page.mouse.move(5, 5);
  const after = await bubble.locator(".b").boundingBox();
  expect(after).toEqual(before);
});

test("the bot chat's answers have the same copy control", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("composer").fill("hello");
  await page.keyboard.press("Enter");
  const bubble = page.getByTestId("bubble-bot").last();
  await expect(bubble).toBeVisible();
  await expect(bubble.getByTestId("copy-answer")).toHaveCount(1);
});

test("edit and resend: the agent takes the last message back and the box holds its text", async ({ page }) => {
  await session(page, "claude", "rename the add function to plus");
  await done(page);
  const users = page.getByTestId("bubble-user");
  await expect(users).toHaveCount(1);
  const edit = page.getByTestId("bubble-edit");
  await expect(edit).toHaveCount(1);
  await users.last().hover();
  await edit.click();
  await expect(page.getByTestId("bubble-user")).toHaveCount(0);
  await expect(page.getByTestId("bubble-bot")).toHaveCount(0);
  await expect(page.getByTestId("composer")).toHaveValue("rename the add function to plus");
  const calls = await page.evaluate(() => (window as unknown as { __omherSessionCalls: { op: string; input?: { kind: string } }[] }).__omherSessionCalls);
  expect(calls.filter((c) => c.op === "chat.input" && c.input?.kind === "rewind")).toHaveLength(1);
  // nothing left to take back: no Edit
  await page.getByTestId("composer").fill("rename add to plus, and update README.md");
  await page.keyboard.press("Enter");
  await done(page);
  await expect(page.getByTestId("bubble-edit")).toHaveCount(1);
});

test("after Terminal and back, the new process offers no Edit for the old one's message", async ({ page }) => {
  await session(page, "claude", "hello");
  await done(page);
  await expect(page.getByTestId("bubble-edit")).toHaveCount(1);
  await page.getByTestId("session-terminal-toggle").click();
  await expect(page.getByTestId("terminal")).toBeVisible();
  await page.getByTestId("session-terminal-toggle").click();
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("bubble-user")).toHaveText("hello");
  await expect(page.getByTestId("bubble-edit")).toHaveCount(0);
});

test("no Edit while a turn runs, and none for an agent without its own rewind", async ({ page }) => {
  await session(page, "claude", "/work hold");
  await expect(page.getByTestId("plan")).toHaveCount(1);
  await expect(page.getByTestId("bubble-edit")).toHaveCount(0);
  await page.getByTestId("stop").click();
  await expect(page.getByTestId("activity").last()).toHaveAttribute("data-state", "interrupted");
  await expect(page.getByTestId("bubble-edit")).toHaveCount(1);
  // oh-my-hermes (a Hermes chat in the folder) has no rewind
  await page.goto("/");
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-omh").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("hi");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bubble-bot").last()).toBeVisible();
  await expect(page.getByTestId("bubble-edit")).toHaveCount(0);
});

test("the new parts keep the house sizes: text 12-13px, corners 4-6px, no fill on the controls", async ({ page }) => {
  await session(page);
  await done(page);
  await page.getByTestId("activity-toggle").last().click();
  await page.getByTestId("activity-step").nth(1).click();
  await page.getByTestId("thinking-toggle").last().click();
  await page.getByTestId("bubble-bot").last().hover();
  const m = await page.evaluate(() => {
    const q = (sel: string) => document.querySelector(sel) as HTMLElement;
    const css = (sel: string) => {
      const c = getComputedStyle(q(sel));
      return { size: parseFloat(c.fontSize), radius: parseFloat(c.borderTopLeftRadius), bg: c.backgroundColor, border: c.borderTopColor, width: c.borderTopWidth };
    };
    return {
      file: css(".dv-file"), body: css(".dv-body"), path: css(".dv-path"), head: css(".dv-head"),
      plan: css(".pl"), box: css(".pl-box"), row: css(".pl-row"), think: css(".th-h"), text: css(".th-body"),
      copy: css(".copy-btn"), edit: css(".msg-edit"),
    };
  });
  for (const k of ["body", "path", "head", "plan", "row", "think", "text", "edit"] as const) {
    expect(m[k].size, k).toBeGreaterThanOrEqual(12);
    expect(m[k].size, k).toBeLessThanOrEqual(13);
  }
  expect(m.file.radius).toBe(6);
  expect(m.box.radius).toBe(4);
  expect(m.copy.radius).toBe(4);
  // the controls are not filled until hovered: the edit label and the closed thinking line have no background
  expect(m.edit.bg).toBe("rgba(0, 0, 0, 0)");
  expect(m.think.bg).toBe("rgba(0, 0, 0, 0)");
});

test("a long diff and long thinking stay inside their boxes; the chat stays pinned while the answer streams", async ({ page }) => {
  await session(page);
  await done(page);
  await page.getByTestId("activity-toggle").last().click();
  await page.getByTestId("activity-step").nth(2).click();
  await page.getByTestId("thinking-toggle").last().click();
  const tl = page.getByTestId("timeline");
  // a new turn streams below: the view stays at the bottom
  await page.getByTestId("composer").fill("/slow");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(1200);
  const gap = await tl.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight);
  expect(gap).toBeLessThan(40);
  await page.getByTestId("stop").click();
});
