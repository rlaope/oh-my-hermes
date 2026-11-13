// Six more coding agents on the Agent Client Protocol adapter (Kilo Code, Gemini CLI, Qwen Code, Kimi Code, Copilot
// CLI, Cline), on the mock host (the browser build's MockHost sends what acp_chat.rs sends for the real CLIs: signed
// out for the five without a free model). The + menu shows the installed agents and folds the rest behind one "More
// agents" row, with "Continue a conversation" under it from the first view; folded or opened it stays inside a
// 900x600 window (its list scrolls there) and at 1280x820 the first view needs no scrolling. A missing agent's row
// gives its whole install line as copyable text. An installed agent that is not signed in ends in one plain line
// with its own sign-in command and Open in Terminal, never a raw error or a field that takes a key.
import { expect, test, type Page } from "@playwright/test";
import { INSTALL, type AgentId } from "../src/sessions/agents";

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

type Call = { op: string; agent?: string; cwd?: string; input?: { kind: string; [k: string]: unknown } };
const calls = (page: Page) => page.evaluate(() => ((window as unknown as { __omherSessionCalls?: Call[] }).__omherSessionCalls ?? []));

const SIX = ["kilo", "gemini", "qwen", "kimi", "copilot", "cline"];

async function open(page: Page, installed: string[], theme = "dark", signedIn: string[] = []) {
  await page.addInitScript(
    ([list, t, signed]) => {
      localStorage.setItem("omher.theme", t as string);
      localStorage.removeItem("omher.sessions.recent");
      const w = window as unknown as { __omherPickFolder: string; __omherMockAgents: string[]; __omherMockSignedIn: string[] };
      w.__omherPickFolder = "/Users/you/code/web-app";
      w.__omherMockAgents = list as string[];
      w.__omherMockSignedIn = signed as string[];
    },
    [installed, theme, signedIn] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

async function plus(page: Page) {
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-agent-claude")).toBeVisible();
  await page.waitForFunction(() => document.querySelector(".ss-pop")?.getAnimations().every((a) => a.playState !== "running"));
}

/** The menu's box, its list's scroll state and fade, how many rows it holds, and which of them are wholly in view. */
const geometry = (page: Page) =>
  page.evaluate(() => {
    const pop = document.querySelector(".ss-pop")!.getBoundingClientRect();
    const list = document.querySelector<HTMLElement>("[data-testid=session-menu-list]")!;
    const box = list.getBoundingClientRect();
    const foot = document.querySelector(".side-foot")!.getBoundingClientRect();
    const cs = getComputedStyle(list);
    const rows = [...list.querySelectorAll<HTMLElement>("[role=menuitem]")];
    return {
      top: pop.top,
      bottom: pop.bottom,
      right: pop.right,
      w: innerWidth,
      footTop: foot.top,
      rows: rows.length,
      scroll: list.scrollHeight > list.clientHeight + 1,
      fade: (cs.maskImage || (cs as unknown as { webkitMaskImage: string }).webkitMaskImage || "none").includes("gradient"),
      inView: rows
        .filter((r) => {
          const b = r.getBoundingClientRect();
          return b.top >= box.top - 0.5 && b.bottom <= box.bottom + 0.5;
        })
        .map((r) => r.dataset.testid!),
      // the height of every row that holds one line (an agent with no second line, More agents, a past-conversation row)
      oneLine: [...new Set(rows.filter((r) => !r.querySelector(".ss-as")).map((r) => r.getBoundingClientRect().height))],
    };
  });

/** The agents that are not installed in these tests' usual set. */
const MISSING: AgentId[] = ["omo", "dsh", "pi", "omp", "grok", "qwen", "kimi", "copilot", "cline"];
const PAST = ["session-past-claude", "session-past-codex"];

for (const theme of ["dark", "light"]) {
  test(`the + menu at 900x600: installed agents, one More agents row, then Continue a conversation, in the window (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 600 });
    await open(page, ["claude", "codex", "omh", "opencode", "kilo", "gemini"], theme);
    await plus(page);
    const menu = page.getByTestId("session-menu");
    const agents = menu.locator("[role=menuitem][data-testid^=session-agent-]");
    // six installed rows, then More agents; the nine others are folded away
    expect(await agents.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!.replace("session-agent-", "")))).toEqual(["claude", "codex", "omh", "opencode", "kilo", "gemini"]);
    const more = menu.getByTestId("session-more");
    await expect(more).toContainText("More agents");
    await expect(more).toContainText("9");
    await expect(more).toHaveAttribute("aria-expanded", "false");
    for (const a of ["qwen", "kimi", "copilot", "cline", "pi"]) await expect(menu.getByTestId(`session-agent-${a}`)).toHaveCount(0);
    // the new rows carry their own marks, never a letter
    for (const a of ["kilo", "gemini"]) await expect(menu.getByTestId(`session-agent-${a}`).locator('svg[data-agent]:not([data-agent="letter"])')).toHaveCount(1);
    // "Continue a conversation" is in the menu as first opened, under More agents, which stays closed
    await expect(menu.locator(".ss-h").last()).toHaveText("Continue a conversation");
    expect(await menu.locator("[role=menuitem]").evaluateAll((els) => els.slice(-3).map((e) => e.getAttribute("data-testid")))).toEqual(["session-more", ...PAST]);
    const g = await geometry(page);
    expect(g.rows).toBe(9);
    // every row holding one line is the usual 30px, folded as opened
    expect(g.oneLine).toEqual([30]);
    // this short window cuts the list: it scrolls inside the menu and says so with the fade at its cut edge
    expect(g.scroll).toBe(true);
    expect(g.fade).toBe(true);
    expect(g.inView.slice(0, 6)).toEqual(["claude", "codex", "omh", "opencode", "kilo", "gemini"].map((a) => `session-agent-${a}`));
    // End reaches the last past-conversation row without More agents being opened
    await page.keyboard.press("End");
    await expect(menu.getByTestId("session-past-codex")).toBeFocused();
    await expect(more).toHaveAttribute("aria-expanded", "false");
    expect((await geometry(page)).inView.slice(-2)).toEqual(PAST);
    expect(g.top).toBeGreaterThanOrEqual(0);
    expect(g.bottom).toBeLessThanOrEqual(g.footTop);
    // a borderless left-aligned row, 12-13px, no box: the same look as the agent rows
    const look = await more.evaluate((e) => {
      const cs = getComputedStyle(e);
      return { size: parseFloat(cs.fontSize), border: cs.borderTopWidth, bg: cs.backgroundColor, align: cs.textAlign };
    });
    expect(look.size).toBeGreaterThanOrEqual(12);
    expect(look.size).toBeLessThanOrEqual(13);
    expect(look.border).toBe("0px");
    expect(look.align).toBe("left");
  });

  test(`the + menu at 1280x820 as first opened: More agents and both Continue a conversation rows, no scrolling (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 820 });
    await open(page, ["claude", "codex", "omh", "opencode", "kilo", "gemini"], theme);
    await plus(page);
    const menu = page.getByTestId("session-menu");
    await expect(menu.getByTestId("session-more")).toHaveAttribute("aria-expanded", "false");
    await expect(menu.locator(".ss-h").last()).toHaveText("Continue a conversation");
    const g = await geometry(page);
    expect(g.rows).toBe(9);
    expect(g.scroll).toBe(false);
    expect(g.fade).toBe(false);
    // all nine rows are wholly in view: six agents, More agents, and the two past-conversation rows
    expect(g.inView).toHaveLength(9);
    expect(g.inView.slice(-3)).toEqual(["session-more", ...PAST]);
    expect(g.oneLine).toEqual([30]);
    expect(g.top).toBeGreaterThanOrEqual(0);
    expect(g.bottom).toBeLessThanOrEqual(g.footTop);
    // no sidebar row shows half above the menu: each is wholly clear of it or wholly under it and its band of air
    const half = await page.evaluate(() => {
      const el = document.querySelector(".ss-pop")!;
      const pop = el.getBoundingClientRect();
      const top = pop.top - (parseFloat(getComputedStyle(el, "::before").height) || 0);
      return [...document.querySelectorAll(".side-top, .side > .search, .bot-list > *, .side-sh, .ss-list > *")]
        .map((r) => r.getBoundingClientRect())
        .filter((r) => r.height > 0 && r.top < top - 0.5 && r.bottom > top + 0.5).length;
    });
    expect(half).toBe(0);
    // a past-conversation row opens its list straight from here
    await menu.getByTestId("session-past-claude").click();
    await expect(page.getByTestId("session-past-menu")).toBeVisible();
  });

  for (const [width, height] of [
    [900, 600],
    [1280, 820],
  ] as const) {
    test(`every missing agent shows its whole install line, none cut and no two alike, at ${width}x${height} (${theme})`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await open(page, ["claude", "codex", "omh", "opencode", "kilo", "gemini"], theme);
      await plus(page);
      const menu = page.getByTestId("session-menu");
      await menu.getByTestId("session-more").click();
      const seen: string[] = [];
      const colours = new Set<string>();
      for (const a of MISSING) {
        const line = menu.getByTestId(`session-install-${a}`);
        await line.evaluate((e) => e.scrollIntoView({ block: "nearest" }));
        await expect(line).toHaveText(INSTALL[a]);
        const m = await line.evaluate((e) => {
          const el = e as HTMLElement;
          const cs = getComputedStyle(el);
          return { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth, shown: el.innerText.replace(/\s+/g, " ").trim(), overflow: cs.textOverflow, colour: cs.color, opacity: cs.opacity };
        });
        // nothing of the line lies outside its box, and what is drawn is the line itself (no ellipsis)
        expect(m.scrollWidth, `${a}: ${m.shown}`).toBeLessThanOrEqual(m.clientWidth);
        expect(m.shown, a).toBe(INSTALL[a]);
        expect(m.shown).not.toContain("…");
        seen.push(m.shown);
        colours.add(`${m.colour} ${m.opacity}`);
        // the row is as tall as its lines: the install line ends inside it
        const row = (await menu.getByTestId(`session-agent-${a}`).boundingBox())!;
        const box = (await line.boundingBox())!;
        expect(box.y + box.height, a).toBeLessThanOrEqual(row.y + row.height + 0.5);
      }
      expect(new Set(seen).size).toBe(MISSING.length);
      // every install line is drawn in the one muted colour
      expect([...colours]).toHaveLength(1);
      // one-line rows keep their height with the fold open
      expect((await geometry(page)).oneLine).toEqual([30]);
    });
  }

  test(`More agents opens the missing ones with their install lines, and the menu still fits at 900x600 (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 600 });
    await open(page, ["claude", "codex", "omh", "opencode", "kilo", "gemini"], theme);
    await plus(page);
    const menu = page.getByTestId("session-menu");
    await menu.getByTestId("session-more").click();
    await expect(menu.getByTestId("session-more")).toHaveAttribute("aria-expanded", "true");
    for (const a of ["omo", "dsh", "pi", "omp", "grok", "qwen", "kimi", "copilot", "cline"]) {
      const row = menu.getByTestId(`session-agent-${a}`);
      await expect(row).toHaveAttribute("aria-disabled", "true");
      await expect(row).toContainText("Not installed");
    }
    // the install line shows as text under the name (the tooltip says the same)
    await expect(menu.getByTestId("session-install-cline")).toHaveText("npm install -g cline");
    await expect(menu.getByTestId("session-agent-qwen")).toHaveAttribute("title", "qwen was not found on this computer · install: npm install -g @qwen-code/qwen-code@latest");
    // the Kimi Code mark is the icon its own package ships
    await expect(menu.getByTestId("session-agent-kimi").locator('img[data-mark="kimi"]')).toHaveCount(1);
    // opened, the list scrolls inside the menu, which stays in the window and above the sidebar's bottom rows
    const g = await geometry(page);
    expect(g.top).toBeGreaterThanOrEqual(0);
    expect(g.bottom).toBeLessThanOrEqual(g.footTop);
    expect(g.right).toBeLessThanOrEqual(g.w);
    // arrow keys reach the last folded agent
    await menu.getByTestId("session-more").focus();
    await page.keyboard.press("End");
    await expect(menu.getByTestId("session-past-codex")).toBeFocused();
    await expect(menu.getByTestId("session-agent-cline")).toBeAttached();
    await menu.getByTestId("session-agent-cline").evaluate((e) => e.scrollIntoView({ block: "nearest" }));
    const r = (await menu.getByTestId("session-agent-cline").boundingBox())!;
    expect(r.y + r.height).toBeLessThanOrEqual(g.bottom + 0.5);
  });
}

test("a missing agent's row copies its install line and starts nothing", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await open(page, ["claude"]);
  await plus(page);
  const menu = page.getByTestId("session-menu");
  await menu.getByTestId("session-more").click();
  const row = menu.getByTestId("session-agent-gemini");
  await row.click({ force: true }); // aria-disabled: still clickable, it copies
  await expect(row).toContainText("Copied");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("npm install -g @google/gemini-cli");
  // the menu stays open and no session or chat started
  await expect(menu).toBeVisible();
  expect((await calls(page)).filter((c) => c.op === "chat.start" || c.op === "start")).toHaveLength(0);
});

test("with nothing installed every agent shows, with no More agents row", async ({ page }) => {
  await open(page, []);
  await page.getByTestId("session-new").click();
  const menu = page.getByTestId("session-menu");
  await expect(menu.getByTestId("session-agent-cline")).toBeAttached();
  await expect(menu.getByTestId("session-more")).toHaveCount(0);
  expect(await menu.locator("[data-testid^=session-agent-]").count()).toBe(15);
});

for (const [id, label, cmd] of [
  ["gemini", "Gemini CLI", "gemini"],
  ["qwen", "Qwen Code", "qwen"],
  ["kimi", "Kimi Code", "kimi login"],
  ["copilot", "Copilot CLI", "copilot login"],
  ["cline", "Cline", "cline auth"],
] as const) {
  test(`${label} installed but not signed in: one plain line with \`${cmd}\` and Open in Terminal`, async ({ page }) => {
    await open(page, ["claude", id]);
    await plus(page);
    await page.getByTestId(`session-agent-${id}`).click();
    await page.getByTestId("session-folder").click();
    await page.getByTestId("session-choose").click();
    await page.getByTestId("composer").fill("Add a dark mode toggle");
    await page.keyboard.press("Enter");
    const ended = page.getByTestId("session-ended");
    await expect(ended).toBeVisible({ timeout: 10_000 });
    const line = `${label} is not signed in. Run \`${cmd}\` in a terminal and sign in.`;
    await expect(ended).toContainText(line);
    await expect(page.getByTestId("chat-offline")).toHaveCount(0);
    await expect(page.getByTestId("chat-start")).toHaveCount(0);
    // the line is said once (the failed turn does not repeat it), never as raw JSON or a code
    const text = await page.getByTestId("session-chat").innerText();
    expect(text.split(line).length - 1).toBe(1);
    expect(text).not.toMatch(/-32000|jsonrpc|Authentication required|API key/);
    // no field anywhere that takes a key or a password
    await expect(page.locator('input[type="password"]')).toHaveCount(0);
    // Open in Terminal opens the person's own terminal in the session's folder; Restart is there too
    await ended.getByTestId("session-signin-terminal").click();
    expect((await calls(page)).filter((c) => c.op === "terminal").map((c) => c.cwd)).toEqual(["/Users/you/code/web-app"]);
    await expect(ended.getByTestId("session-restart")).toBeVisible();
  });
}

test("the not-signed-in line is in the person's language", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("omher.lang", "ko"));
  await open(page, ["claude", "gemini"]);
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-gemini").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("hi");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-ended")).toContainText("Gemini CLI 로그인이 안 되어 있어요. 터미널에서 `gemini`를 실행해 로그인하세요.", { timeout: 10_000 });
});

test("Kilo Code signed in (its free models need no account): a chat with its long model list searchable", async ({ page }) => {
  await open(page, ["claude", "kilo"], "dark", ["kilo"]);
  await plus(page);
  await page.getByTestId("session-agent-kilo").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("Add a dark mode toggle");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bubble-bot").last()).toContainText("You said: Add a dark mode toggle");
  await page.getByTestId("model-pill").click();
  const search = page.getByTestId("model-search");
  await expect(search).toBeFocused();
  await search.fill("free");
  await expect(page.getByTestId("model-opt")).toHaveCount(2);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("model-label")).toHaveText("Kilo Gateway/Auto Free");
  // the card offers Deny and Allow once only
  await page.getByTestId("composer").fill("/approve clean the build folder");
  await page.keyboard.press("Enter");
  const card = page.getByTestId("card-approval");
  await expect(card).toBeVisible();
  expect(await card.locator(".card-btn").allInnerTexts()).toEqual(["Deny", "Allow once"]);
  expect((await calls(page)).find((c) => c.op === "chat.start")!.agent).toBe("kilo");
});

test("each of the six starts only as its own id: the UI sends no command line", async ({ page }) => {
  await open(page, ["claude", ...SIX], "dark", SIX);
  for (const a of SIX) {
    await plus(page);
    await page.getByTestId(`session-agent-${a}`).click();
    await page.getByTestId("composer").fill("hi");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("bubble-bot").last()).toContainText("You said: hi");
  }
  const starts = (await calls(page)).filter((c) => c.op === "chat.start");
  expect(starts.map((c) => c.agent)).toEqual(SIX);
  for (const c of starts) expect(Object.keys(c).sort()).toEqual(["agent", "cwd", "id", "op", "session"].sort());
});
