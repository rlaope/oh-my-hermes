// The composer's `/` skill picker: `/` at the start or after a space, anywhere in a bot chat message, lists the
// bot's skills (skills.list) while one matches; a `/name` token is a gray pill drawn by a mirror layer under the
// textarea, and goes out hoisted to the front. `./name` is plain text. The bubble keeps the text as typed with a
// monospace pill. A SESSIONS chat keeps its agent's own `/` menu and never gets this picker.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const SHOTS = process.env.OMHER_SHOTS || join(homedir(), ".hermes/profiles/kami/cache/scratch/omher-fable/shots3");

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

const calls = async () => (await mock("mock.calls")).result.calls as { op: string; params: any }[];
const sends = async () => (await calls()).filter((c) => c.op === "chat.send").map((c) => c.params.text);
const lists = async () => (await calls()).filter((c) => c.op === "skills.list").length;
const options = (page: Page) => page.getByTestId("skill-option");

async function openFriren(page: Page) {
  await page.goto("/");
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("header").getByText("Friren", { exact: true })).toBeVisible();
  await expect(page.getByTestId("composer")).toBeEnabled();
  await page.getByTestId("composer").click();
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("/ mid-message: the picker filters, Enter inserts a pill, Send hoists it to the front", async ({ page }) => {
  await openFriren(page);
  const box = page.getByTestId("composer");
  await box.pressSequentially("fix this /pl");
  await expect(page.getByTestId("skill-picker")).toBeVisible();
  // prefix match first, then a name that only contains "pl"
  await expect(options(page)).toHaveCount(2);
  expect(await options(page).evaluateAll((els) => els.map((e) => e.getAttribute("data-name")))).toEqual(["plan", "explain-code"]);
  await expect(options(page).first()).toHaveAttribute("aria-selected", "true");
  await expect(options(page).first().locator(".sk-pill")).toHaveCSS("font-family", /Mono|monospace|Menlo/);
  await expect(page.getByTestId("skill-hint")).toHaveCount(0);

  await page.keyboard.press("Enter");
  await expect(page.getByTestId("skill-picker")).toHaveCount(0);
  await expect(box).toHaveValue("fix this /plan ");
  expect(await sends()).toEqual([]); // Enter picked, it did not send
  await expect(page.getByTestId("composer-mirror").locator(".cm-tok")).toHaveText(["/plan"]);

  await box.pressSequentially("now");
  await page.getByTestId("send").click();
  await expect.poll(sends).toEqual(["/plan fix this now"]);
  const submits = (await mock("mock.submits")).result.submits;
  expect(submits.at(-1).text).toBe("/plan fix this now");
  // the bubble shows what was typed, the token as a monospace pill
  const mine = page.getByTestId("bubble-user").last();
  await expect(mine).toHaveText("fix this /plan now");
  await expect(mine.getByTestId("bubble-skill")).toHaveText("/plan");
  await expect(box).toHaveValue("");
});

test("tokens typed by hand at the start, middle and end are recognised; paths, unknown names and code are not", async ({ page }) => {
  await openFriren(page);
  const box = page.getByTestId("composer");
  await box.pressSequentially("check /review then /plan it, and /research");
  await expect(page.getByTestId("skill-picker")).toBeVisible(); // the caret is still on the last one
  await box.pressSequentially(" ");
  await expect(page.getByTestId("skill-picker")).toHaveCount(0); // past it: Enter sends (the trailing space is trimmed)
  await expect(page.getByTestId("composer-mirror").locator(".cm-tok")).toHaveText(["/review", "/plan", "/research"]);
  await page.keyboard.press("Enter");
  await expect.poll(sends).toEqual(["/review /plan /research check then it, and"]);
  await expect(page.getByTestId("bubble-user").last().getByTestId("bubble-skill")).toHaveText(["/review", "/plan", "/research"]);

  // none of these is a token: a path, a longer word, inline code, a URL, and/or, an unknown name: byte for byte
  const plain = "open /src/app.ts and /planning, `/plan` too https://x.dev/plan and/or /nope";
  await box.fill(plain);
  await expect(page.getByTestId("composer-mirror").locator(".cm-tok")).toHaveCount(0);
  await box.press("End");
  await expect(page.getByTestId("skill-picker")).toHaveCount(0); // /nope matches no skill: no popup
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await sends()).length).toBe(2);
  expect((await sends())[1]).toBe(plain);
  await expect(page.getByTestId("bubble-user").last().getByTestId("bubble-skill")).toHaveCount(0);

  // Hermes' own commands at the start are not skills: sent as typed, one Enter each
  for (const cmd of ["/new", "/help", "/model x"]) {
    await box.fill(cmd);
    await page.keyboard.press("Enter");
  }
  await expect.poll(async () => (await sends()).slice(2)).toEqual(["/new", "/help", "/model x"]);
});

test("./name is plain text: no picker, no pill, sent byte for byte; ./ alone does not read the skill list", async ({ page }) => {
  await openFriren(page);
  const box = page.getByTestId("composer");
  await box.pressSequentially("rename ./pl");
  await expect(page.getByTestId("skill-picker")).toHaveCount(0);
  await box.pressSequentially("an to ./plan-steps in ./plan.md, then ./review");
  await expect(page.getByTestId("composer-mirror").locator(".cm-tok")).toHaveCount(0);
  expect(await lists()).toBe(0);
  await page.keyboard.press("Enter");
  const typed = "rename ./plan to ./plan-steps in ./plan.md, then ./review";
  await expect.poll(sends).toEqual([typed]);
  const mine = page.getByTestId("bubble-user").last();
  await expect(mine).toHaveText(typed);
  await expect(mine.getByTestId("bubble-skill")).toHaveCount(0);
  // the list is read the first time a / stands where a token can
  await box.pressSequentially("then /");
  await expect.poll(lists).toBe(1);
  await expect(page.getByTestId("skill-picker")).toBeVisible();
});

test("Esc closes until the fragment changes; with no match there is no popup and one Enter sends", async ({ page }) => {
  await openFriren(page);
  const box = page.getByTestId("composer");
  await box.pressSequentially("/");
  await expect(options(page)).toHaveCount(6); // every skill
  await page.keyboard.press("ArrowDown");
  await expect(options(page).nth(1)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowUp"); // wraps to the last
  await expect(options(page).last()).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("skill-picker")).toHaveCount(0);
  await box.pressSequentially("r");
  await expect(page.getByTestId("skill-picker")).toBeVisible();
  expect(await options(page).evaluateAll((els) => els.map((e) => e.getAttribute("data-name")))).toEqual([
    "research",
    "review",
    "deep-interview",
    "long-document-reading-and-summarising",
  ]);
  // Tab inserts too, and a click on a row
  await page.keyboard.press("Tab");
  await expect(box).toHaveValue("/research ");
  await box.pressSequentially("and /rev");
  await options(page).filter({ hasText: "review" }).click();
  await expect(box).toHaveValue("/research and /review ");
  await expect(box).toBeFocused();

  // a path matches no skill: no popup at any point, and the first Enter sends
  await box.fill("");
  await box.pressSequentially("clean /tmp");
  await expect(page.getByTestId("skill-picker")).toHaveCount(0);
  await expect(page.getByTestId("skill-none")).toHaveCount(0);
  await page.keyboard.press("Enter");
  await expect.poll(sends).toEqual(["clean /tmp"]);
  await box.pressSequentially("/zz");
  await expect(page.getByTestId("skill-picker")).toHaveCount(0);
  await page.keyboard.press("Enter");
  await expect.poll(sends).toEqual(["clean /tmp", "/zz"]);
});

test("the /skill hint shows only where there is no skill list to pick from", async ({ page }) => {
  await openFriren(page);
  const box = page.getByTestId("composer");
  await box.fill("/pl");
  await expect(page.getByTestId("skill-picker")).toBeVisible();
  await expect(page.getByTestId("skill-hint")).toHaveCount(0);

  await mock("mock.noSkills", { bot: "friren" });
  await openFriren(page);
  await box.fill("/pl");
  await expect(page.getByTestId("skill-hint")).toBeVisible();
  await expect(page.getByTestId("skill-hint")).toContainText("No skill list from Friren");
  await expect(page.getByTestId("skill-picker")).toHaveCount(0);
  await box.fill("hello /plan");
  await expect(page.getByTestId("skill-hint")).toHaveCount(0);
});

test("a SESSIONS chat keeps its agent's own / menu and never gets the bot skill picker", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.removeItem("omher.sessions.recent");
    const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[] };
    w.__omherPickFolder = "/Users/you/code/web-app";
    w.__omherMockAgents = ["claude", "codex", "omo", "omh"];
  });
  await page.goto("/");
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  const box = page.getByTestId("composer");
  await box.fill("/status");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");

  await box.fill("/");
  await expect(page.getByTestId("command-picker")).toBeVisible();
  await expect(page.getByTestId("skill-picker")).toHaveCount(0);
  await box.fill("");
  await box.pressSequentially("fix this /pl");
  await expect(page.getByTestId("skill-picker")).toHaveCount(0);
  await expect(page.getByTestId("command-picker")).toHaveCount(0);
  await expect(page.getByTestId("composer-mirror").locator(".cm-tok")).toHaveCount(0);
  expect(await lists()).toBe(0);
});

/** Two animation frames: scroll and resize work (and their events) have run. */
const frames = (page: Page) => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(0)))));

/** Ink per text line of a PNG (20px lines from the 5px top padding): total darkness off the background and its
 * horizontal centre. Decoded in the page, so the spec needs no image library. */
async function inkLines(page: Page, png: Buffer): Promise<{ ink: number; x: number }[]> {
  return page.evaluate(async (b64) => {
    const bmp = await createImageBitmap(await (await fetch(`data:image/png;base64,${b64}`)).blob());
    const c = new OffscreenCanvas(bmp.width, bmp.height);
    const g = c.getContext("2d")!;
    g.drawImage(bmp, 0, 0);
    const { data, width, height } = g.getImageData(0, 0, bmp.width, bmp.height);
    const bg = data[(height * width - 1) * 4];
    const lines: { ink: number; x: number }[] = [];
    for (let y0 = 5; y0 + 20 <= height; y0 += 20) {
      let ink = 0;
      let sx = 0;
      for (let y = y0; y < y0 + 20; y += 1)
        for (let x = 0; x < width; x += 1) {
          const v = Math.abs(data[(y * width + x) * 4] - bg);
          ink += v;
          sx += v * x;
        }
      lines.push({ ink, x: ink ? sx / ink : 0 });
    }
    return lines;
  }, png.toString("base64"));
}

test("the mirror lays out the textarea's own text: same lines, same places, at every width and scrolled", async ({ page }) => {
  await openFriren(page);
  const box = page.getByTestId("composer");
  const text = [
    "Read the logs first /review then a much longer sentence that has to wrap more than once in this box,",
    "with 한국어 문장도 섞어서 /plan 줄바꿈이 같은지 보고, aVeryLongUnbrokenIdentifierThatMustBreakSomewhereInTheMiddleOfTheLine",
    "/research.",
    "",
    "New paragraph /plan",
    "/deep-interview, then /long-document-reading-and-summarising at the end of a line",
    "",
  ].join("\n");
  await box.fill(text + text);
  await expect(page.getByTestId("composer-mirror").locator(".cm-tok")).toHaveCount(12);
  const field = page.locator(".cm-field");
  // A: the textarea draws the text. B: the mirror draws it instead (pill grounds off, caret hidden). The two
  // rasterise a little differently (anti-aliasing), so compare each line's ink and its horizontal centre: a
  // glyph or a line break in another place moves them by whole pixels.
  const style = await page.addStyleTag({
    content: ".cm-field textarea { caret-color: transparent; } .cm-tok { background: none !important; box-shadow: none !important; }",
  });
  for (const width of [1440, 1180, 980, 860, 760]) {
    await page.setViewportSize({ width, height: 900 });
    await frames(page);
    for (const scroll of [0, 60, 10_000]) {
      await box.evaluate((el, y) => el.scrollTo(0, y), scroll);
      await frames(page); // scroll events go out with the next frame
      const boxes = await field.evaluate((f) =>
        [f.querySelector(".cm-mirror")!, f.querySelector("textarea")!].map((e) => [e.scrollTop, e.scrollHeight, e.clientHeight, e.clientWidth]),
      );
      expect(boxes[0], `width ${width}, scroll ${scroll}: mirror vs textarea box`).toEqual(boxes[1]);
      const a = await inkLines(page, await field.screenshot());
      const swap = await page.addStyleTag({
        content: ".cm-field textarea { color: transparent !important; } .cm-mirror, .cm-tok { color: var(--ink) !important; }",
      });
      const b = await inkLines(page, await field.screenshot());
      await swap.evaluate((el) => el.remove());
      expect(a.filter((l) => l.ink > 1000).length, "lines with text").toBeGreaterThan(5);
      a.forEach((la, i) => {
        const lb = b[i];
        const at = `width ${width}, scroll ${scroll}, line ${i}`;
        expect(Math.abs(lb.ink - la.ink), at).toBeLessThanOrEqual(Math.max(400, la.ink * 0.02));
        if (la.ink > 1000) expect(Math.abs(lb.x - la.x), at).toBeLessThan(0.25);
      });
    }
  }
  await style.evaluate((el) => el.remove());
});

test("screenshots: the / picker mid-message, a sent bubble and ./ as plain text, dark and light", async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => localStorage.removeItem("omher.theme"));
  const shoot = async (name: string) => {
    await page.mouse.move(5, 895);
    await page.waitForTimeout(400);
    await page.screenshot({ path: join(SHOTS, name), caret: "initial" });
  };
  for (const theme of ["dark", "light"] as const) {
    await mock("mock.reset");
    await page.emulateMedia({ colorScheme: theme });
    await openFriren(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const box = page.getByTestId("composer");
    await box.fill(""); // the other theme's unsent draft is kept across reloads
    await box.pressSequentially("Look at the failing upload test /review and then /pl");
    await expect(options(page).first()).toHaveAttribute("data-name", "plan");
    await shoot(`skills-slash-picker-after-${theme}.png`);
    await page.keyboard.press("Enter");
    await box.pressSequentially("the fix");
    let answers = await page.getByTestId("bubble-bot").count();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("bubble-user").last().getByTestId("bubble-skill")).toHaveCount(2);
    await expect(page.getByTestId("bubble-bot")).toHaveCount(answers + 1, { timeout: 20_000 }); // the scripted answer is in
    await shoot(`skills-slash-sent-after-${theme}.png`);

    answers = await page.getByTestId("bubble-bot").count();
    await box.pressSequentially("Rename the ./plan skill folder to ./plan-steps");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("bubble-bot")).toHaveCount(answers + 1, { timeout: 20_000 });
    await expect(page.getByTestId("bubble-user").last().getByTestId("bubble-skill")).toHaveCount(0);
    await box.pressSequentially("and keep ./pl");
    await expect(page.getByTestId("skill-picker")).toHaveCount(0);
    await shoot(`skills-dotslash-plain-after-${theme}.png`);
  }
});
