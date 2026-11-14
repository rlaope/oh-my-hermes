// The v0.2 polish pass: what each fix promises, measured. (The sidebar split is in sessions.spec.ts, the graph in
// runs.spec.ts.)
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string, params: Record<string, unknown> = {}): Promise<void> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  await new Promise<void>((res) => {
    ws.onmessage = () => res();
    ws.send(JSON.stringify({ id: "x1", op, ...params }));
  });
  ws.close();
}
async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("the first-run screen is drawn in the person's theme: light, though the app has not mounted", async ({ page }) => {
  // `__OMHER_GATE__` stands in for the Tauri shell and reports Hermes missing: the setup screen shows and <App>
  // (which used to be the only place the theme was set) never mounts
  await page.addInitScript(() => {
    localStorage.setItem("omher.theme", "light");
    (window as unknown as Record<string, unknown>).__OMHER_GATE__ = {
      status: async () => ({ state: "failed", error: "Hermes not found: install Hermes Agent first", missing: "hermes" }),
      retry: async () => {},
      installCommand: async () => "sh install.sh",
      install: async () => {},
    };
  });
  await page.goto("/");
  await expect(page.getByTestId("setup-screen")).toBeVisible();
  await expect(page.getByTestId("sidebar")).toHaveCount(0);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const [r, g, b] = bg.match(/\d+/g)!.map(Number);
  expect(Math.min(r, g, b)).toBeGreaterThan(200); // a light page, not the dark default
});

test("no bots: the empty pane says, in one line, that Hermes has no bot and where to connect one", async ({ page }) => {
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    const ops = new Map<string, string>();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      ops.set(msg.id, msg.op);
      server.send(raw);
    });
    server.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (ops.get(msg.id) === "bots.list" && msg.ok) {
        msg.result.bots = [];
        ws.send(JSON.stringify(msg));
        return;
      }
      ws.send(raw);
    });
  });
  await page.goto("/");
  const empty = page.getByTestId("chat-empty");
  await expect(empty).toHaveText("Hermes has no bot yet. Connect one from the + menu at the top left.");
  // no terminal command any more
  await expect(empty.locator("code")).toHaveCount(0);
  await expect(empty).not.toContainText("hermes profile create");
  // readable: the hint is not in the faintest gray
  const [hint, faint] = await empty.evaluate((e) => {
    const probe = document.createElement("i");
    probe.style.color = "var(--quiet)";
    e.appendChild(probe);
    const out = [getComputedStyle(e).color, getComputedStyle(probe).color];
    probe.remove();
    return out;
  });
  expect(hint).not.toBe(faint);
});

test("the bridge goes away: the composer says so and waits, then comes back by itself", async ({ page }) => {
  let drop: (() => void) | null = null;
  let away = false;
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    // while the bridge is away every reconnect is refused, so the waiting state stays (a routed socket left unhandled
    // would open, and the app would think it was back)
    if (away) return void ws.close({ code: 1011, reason: "bridge down" });
    const server = ws.connectToServer();
    ws.onMessage((raw) => server.send(raw));
    drop = () => {
      away = true;
      ws.close({ code: 1011, reason: "bridge died" });
    };
  });
  await open(page);
  const composer = page.getByTestId("composer");
  await expect(composer).toBeEnabled();
  await expect(composer).toHaveAttribute("placeholder", "Message Kami");
  drop!();
  await expect(composer).toBeDisabled();
  await expect(composer).toHaveAttribute("placeholder", "Connecting to Hermes…");
  await expect(page.getByTestId("send")).toBeDisabled();
  // it holds through the retries (250ms, 500ms, 1s…), not only until the first one
  await page.waitForTimeout(1500);
  await expect(composer).toBeDisabled();
  await expect(composer).toHaveAttribute("placeholder", "Connecting to Hermes…");
});

test("one divider across the window: the side panel's tab bar ends where the chat header ends", async ({ page }) => {
  await open(page);
  await page.getByTestId("places").click();
  await expect(page.getByTestId("details-panel")).toBeVisible();
  const [head, tabs] = await page.evaluate(() => [
    document.querySelector(".head")!.getBoundingClientRect().bottom,
    document.querySelector(".details .details-h")!.getBoundingClientRect().bottom,
  ]);
  expect(Math.abs(head - tabs)).toBeLessThanOrEqual(0.5);
});

test("a narrow chat column: a bubble may use the column, instead of a sentence in five lines beside empty room", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 760 });
  await open(page);
  await page.getByTestId("places").click();
  await page.getByTestId("panel-tab-terminal").click();
  // one long paragraph from the bot
  const text = "The upstream closes idle connections after sixty seconds while the gateway keeps them for seventy five, so a request that picks a stale one fails; ".repeat(3);
  await mock("mock.emit", { events: [{ event: "turn.start", bot: "kami" }, { event: "message", bot: "kami", id: "polish-1", text }, { event: "turn.end", bot: "kami", outcome: "done" }] });
  const bubble = page.locator(".msg.a").filter({ hasText: "The upstream closes idle connections" }).last();
  await expect(bubble).toBeVisible();
  const narrow = await bubble.evaluate((row: HTMLElement) => {
    const b = row.querySelector<HTMLElement>(".b")!;
    return b.getBoundingClientRect().width / (b.parentElement as HTMLElement).clientWidth;
  });
  // it fills the column beside the face; it used to stop at 80% of it
  expect(narrow).toBeGreaterThan(0.98);
  // in a wide column the old proportion holds: the same bubble stops well short of the row's right edge
  await page.setViewportSize({ width: 1440, height: 900 });
  const wide = await bubble.evaluate((row: HTMLElement) => {
    const b = row.querySelector<HTMLElement>(".b")!.getBoundingClientRect();
    const r = row.getBoundingClientRect();
    return (r.right - b.right) / r.width;
  });
  expect(wide).toBeGreaterThan(0.12);
});

test("a message of several lines: + and send stay level on the last line", async ({ page }) => {
  await open(page);
  const composer = page.getByTestId("composer");
  await composer.fill("one\ntwo\nthree\nfour");
  const [plus, send, box] = await page.evaluate(() => {
    const r = (sel: string) => document.querySelector(sel)!.getBoundingClientRect();
    return [r("[data-testid=attach]"), r("[data-testid=send]"), r("[data-testid=composer]")];
  });
  expect(box.height).toBeGreaterThan(70); // the box grew to four lines
  const mid = (r: DOMRect) => r.top + r.height / 2;
  expect(Math.abs(mid(plus) - mid(send))).toBeLessThanOrEqual(2);
  expect(plus.bottom).toBeGreaterThan(box.bottom - 12); // both on the last line, not the first
  // and on one line they are level too
  await composer.fill("one");
  const [p1, s1] = await page.evaluate(() => {
    const r = (sel: string) => document.querySelector(sel)!.getBoundingClientRect();
    return [r("[data-testid=attach]"), r("[data-testid=send]")];
  });
  expect(Math.abs(mid(p1) - mid(s1))).toBeLessThanOrEqual(2);
});

test("light theme: the working spinner's arc is the accent, dark enough to see on white", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("omher.theme", "light"));
  await open(page);
  const [spin, accent] = await page.evaluate(() => {
    const probe = document.createElement("i");
    probe.className = "ui-spin";
    document.body.appendChild(probe);
    const a = document.createElement("i");
    a.style.color = "var(--accent)";
    document.body.appendChild(a);
    const out = [getComputedStyle(probe).borderTopColor, getComputedStyle(a).color];
    probe.remove();
    a.remove();
    return out;
  });
  expect(spin).toBe(accent);
  // 4.5:1 or better on white
  const [r, g, b] = spin.match(/\d+/g)!.map((v) => Number(v) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  expect(1.05 / (0.2126 * r + 0.7152 * g + 0.0722 * b + 0.05)).toBeGreaterThanOrEqual(4.5);
});

// ---- UI pass 2 ---------------------------------------------------------------------------------------------------

/** A theme token as the page resolves it ("rgb(…)"). */
const token = (page: Page, name: string) =>
  page.evaluate((n) => {
    const probe = document.createElement("i");
    probe.style.color = `var(${n})`;
    document.body.appendChild(probe);
    const c = getComputedStyle(probe).color;
    probe.remove();
    return c;
  }, name);
/** WCAG contrast of two "rgb(…)" colours. */
function contrast(a: string, b: string): number {
  const lum = (c: string) => {
    const [r, g, bl] = c.match(/[\d.]+/g)!.slice(0, 3).map((v) => Number(v) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [x, y] = [lum(a), lum(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

test("five asks: the Needs list ends on the third, whole, and a '+2 more' row opens the rest", async ({ page }) => {
  // one open ask per bot: five more bots (copies of Friren the mock does not know, so nothing re-reads their asks
  // away) ask at once
  const extra = ["n1", "n2", "n3", "n4", "n5"];
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    const ops = new Map<string, string>();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      ops.set(msg.id, msg.op);
      server.send(raw);
    });
    server.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (ops.get(msg.id) === "bots.list" && msg.ok) {
        const friren = msg.result.bots.find((b: { name: string }) => b.name === "friren");
        msg.result.bots.push(...extra.map((name) => ({ ...friren, name, display_name: `Bot ${name}` })));
        ws.send(JSON.stringify(msg));
        return;
      }
      ws.send(raw);
    });
  });
  await open(page);
  const ask = (bot: string, i: number) => [
    { event: "turn.start", bot },
    { event: "approval.request", bot, request_id: `p2-${i}`, title: "Run shell command", command: "kubectl rollout restart deploy/gateway -n production --timeout=120s", choices: ["once", "session", "always", "deny"] },
  ];
  await mock("mock.emit", { events: extra.flatMap((b, i) => ask(b, i)) });
  await expect(page.getByTestId("needs-strip")).toContainText("5 need you");
  await page.getByTestId("needs-strip").click();
  const list = page.getByTestId("needs-list");
  await expect(list.getByTestId("needs-item")).toHaveCount(3);
  await expect(list.getByTestId("needs-more")).toHaveText("+2 more");
  // nothing is cut: the list does not scroll, and its last row (the "+2 more") ends inside it
  const fit = await list.evaluate((l) => ({ over: l.scrollHeight - l.clientHeight, more: l.lastElementChild!.getBoundingClientRect().bottom, end: l.getBoundingClientRect().bottom }));
  expect(fit.over).toBeLessThanOrEqual(0);
  expect(fit.more).toBeLessThanOrEqual(fit.end);
  await list.getByTestId("needs-more").click();
  await expect(list.getByTestId("needs-item")).toHaveCount(5);
  await expect(list.getByTestId("needs-more")).toHaveCount(0);
  await expect(list.getByTestId("needs-item").nth(3)).toBeFocused(); // the first ask it showed
  // closed and opened again, it starts short again
  await page.keyboard.press("Escape");
  await page.getByTestId("needs-strip").click();
  await expect(list.getByTestId("needs-item")).toHaveCount(3);
});

test("an away bubble has one left edge: a link or a 'working' that wraps starts where the text starts", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page);
  const bubble = page.getByTestId("away").filter({ has: page.getByTestId("away-time") }).first();
  await expect(bubble).toBeVisible();
  const edges = await bubble.evaluate((m) => {
    // each part on a line of its own, as a narrow column wraps them
    const text = m.querySelector<HTMLElement>(".ew-text")!;
    const link = m.querySelector<HTMLElement>(".ew-link, .ew-where")!;
    text.style.display = "inline-block";
    text.style.width = "100%";
    link.style.width = "100%";
    const left = (e: Element) => e.getBoundingClientRect().left;
    return { text: left(text), mark: left(link.querySelector(".src-ic")!), working: left(m.querySelector("[data-testid=away-time]")!), lines: [text, link, m.querySelector("[data-testid=away-time]")!].map((e) => Math.round(e.getBoundingClientRect().top)) };
  });
  expect(new Set(edges.lines).size).toBe(3); // three lines
  expect(Math.abs(edges.mark - edges.text)).toBeLessThanOrEqual(0.5);
  expect(Math.abs(edges.working - edges.text)).toBeLessThanOrEqual(0.5);
});

test("lines that carry information are 12px in --muted, not the 11px tertiary gray", async ({ page }) => {
  // the bot cannot be reached: the notice in the date dividers' place
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (msg.op === "chat.open" && msg.bot === "friren") ws.send(JSON.stringify({ id: msg.id, ok: false, error: { code: "bot_offline", message: "gateway could not start" } }));
      else server.send(raw);
    });
    server.onMessage((raw) => ws.send(raw));
  });
  await open(page);
  const muted = await token(page, "--muted");
  const look = (sel: string) => page.locator(sel).first().evaluate((e) => [getComputedStyle(e).color, getComputedStyle(e).fontSize]);
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("chat-error")).toBeVisible();
  expect(await look("[data-testid=chat-error]")).toEqual([muted, "12px"]);
  // the key hint beside an approval's buttons
  await page.getByTestId("bot-kami").click();
  await mock("mock.ask", { bot: "kami", kind: "approval" });
  await expect(page.getByTestId("card-approval")).toBeVisible();
  expect(await look(".card-keys")).toEqual([muted, "12px"]);
});

test("question cards: a clarify's choices are the interview's chips, one control in one style", async ({ page }) => {
  await open(page);
  const style = (sel: string) =>
    page.locator(sel).first().evaluate((e) => {
      const cs = getComputedStyle(e);
      return [cs.backgroundColor, cs.boxShadow, cs.fontWeight, cs.fontSize, cs.height, cs.borderRadius, cs.color].join(" | ");
    });
  await mock("mock.ask", { bot: "kami", kind: "clarify" });
  await expect(page.getByTestId("card-clarify")).toBeVisible();
  const clarify = await style("[data-testid=card-clarify] button");
  await mock("mock.ask", { bot: "friren", kind: "interview" });
  await page.getByTestId("bot-friren").click();
  await expect(page.locator(".iv-chip").first()).toBeVisible();
  const interview = await style(".iv-chips .iv-chip:not(.on)");
  expect(clarify).toBe(interview);
  expect(clarify).toContain("| 400 |"); // outlined and regular, not filled and bold
});

test("text fields take one calm focus: a 1px edge in --muted, the sidebar search and the model search alike", async ({ page }) => {
  for (const theme of ["dark", "light"] as const) {
    await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
    await open(page);
    const muted = await token(page, "--muted");
    const side = page.locator(".search");
    const before = await side.evaluate((e) => getComputedStyle(e).boxShadow);
    await page.getByRole("searchbox", { name: "Search bots and sessions" }).focus();
    const sideFocus = await side.evaluate((e) => ({ shadow: getComputedStyle(e).boxShadow, outline: getComputedStyle(e).outlineStyle }));
    expect(sideFocus.shadow).not.toBe(before);
    expect(sideFocus.shadow).toBe(`${muted} 0px 0px 0px 1px inset`);
    expect(sideFocus.outline).toBe("none");
    await page.getByTestId("head-right").locator("button").first().click();
    const search = page.locator(".mp-search");
    await expect(page.getByTestId("model-search")).toBeFocused();
    const pick = await search.evaluate((e) => ({ edge: getComputedStyle(e).borderTopColor, width: getComputedStyle(e).borderTopWidth, outline: getComputedStyle(e).outlineStyle }));
    expect(pick).toEqual({ edge: muted, width: "1px", outline: "none" });
  }
});

test("a running terminal session's dot: 6px, solid, inside its tile, readable on it", async ({ page }) => {
  for (const theme of ["dark", "light"] as const) {
    await page.addInitScript(
      (t) => {
        localStorage.setItem("omher.theme", t);
        localStorage.removeItem("omher.sessions.recent");
        (window as unknown as Record<string, unknown>).__omherPickFolder = "/Users/you/code/api";
        (window as unknown as Record<string, unknown>).__omherMockAgents = ["claude", "grok"];
      },
      theme,
    );
    await open(page);
    await page.getByTestId("session-new").click();
    await page.getByTestId("session-agent-grok").click();
    await page.getByTestId("session-folder").click();
    await page.getByTestId("session-choose").click();
    await page.getByTestId("session-go").click();
    const dot = page.locator("[data-testid=session-list] [data-testid=live-dot]").first();
    await expect(dot).toBeVisible();
    await page.getByTestId("bot-kami").click(); // the row unselected, as in the list
    const m = await dot.evaluate((d) => {
      const tile = d.closest(".ss-av")!;
      const r = d.getBoundingClientRect();
      const t = tile.getBoundingClientRect();
      const cs = getComputedStyle(d);
      return { w: r.width, inside: r.left >= t.left && r.right <= t.right && r.top >= t.top && r.bottom <= t.bottom, anim: cs.animationName, opacity: cs.opacity, color: cs.backgroundColor, tile: getComputedStyle(tile).backgroundColor };
    });
    expect(m.w).toBe(6);
    expect(m.inside).toBe(true);
    expect(m.anim).toBe("none");
    expect(m.opacity).toBe("1");
    expect(contrast(m.color, m.tile), theme).toBeGreaterThanOrEqual(3);
    await mock("mock.reset");
  }
});

test("side panel tabs: a hovered tab never looks selected (no fill), only the selected one is filled", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page);
  await page.getByTestId("who").click();
  // the click on Terminal widens the panel, which slides another tab under the pointer
  await page.getByTestId("panel-tab-terminal").click();
  await page.getByTestId("panel-tab-diff").hover();
  const bg = (id: string) => page.getByTestId(id).evaluate((e) => getComputedStyle(e).backgroundColor);
  expect(await bg("panel-tab-diff")).toBe("rgba(0, 0, 0, 0)");
  expect(await bg("panel-tab-terminal")).not.toBe("rgba(0, 0, 0, 0)");
});

test("while an answer streams, its caret ends the last line of text, not a line of its own", async ({ page }) => {
  await open(page);
  await mock("mock.emit", {
    events: [
      { event: "turn.start", bot: "kami" },
      { event: "delta", bot: "kami", text: "Done. The 502s came from expired keep-alive connections.\n\n- Cause: upstream connection reuse\n- Fix: raised the idle" },
    ],
  });
  const b = page.getByTestId("bubble-streaming").locator(".b");
  await expect(b).toContainText("raised the idle");
  const caret = await b.evaluate((el) => {
    const on = (e: Element) => getComputedStyle(e, "::after").content !== "none";
    const li = el.querySelector("ul > li:last-child")!;
    return { bubble: on(el), lastItem: on(li), firstItem: on(el.querySelector("ul > li")!), height: li.getBoundingClientRect().height, line: parseFloat(getComputedStyle(li).lineHeight) };
  });
  expect(caret).toMatchObject({ bubble: false, lastItem: true, firstItem: false });
  expect(caret.height).toBeLessThanOrEqual(caret.line + 1); // still one line: the caret sits on it
  await mock("mock.emit", { events: [{ event: "turn.end", bot: "kami", outcome: "done" }] });
});

test("Accounts: every leading mark sits in one 16px slot, one column", async ({ page }) => {
  await page.addInitScript(() => {
    const st: Record<string, unknown> = {
      "claude:default": { logged_in: true, email: "owner@example.com", plan: "max_20x", method: "claude.ai" },
      "codex:default": { logged_in: true, email: null, plan: null, method: "chatgpt" },
      "codex:work": { logged_in: true, email: null, plan: null, method: "chatgpt" },
    };
    (window as unknown as Record<string, unknown>).__omherAccountHost = {
      canSignIn: true,
      clis: async () => ({ claude: true, codex: true, pi: true, omp: false, grok: false, gemini: false }),
      status: async (cli: string, account: string) => st[`${cli}:${account}`] ?? null,
      signIn: async () => 1,
      cancel: async () => {},
    };
  });
  await open(page);
  await page.getByTestId("me").click();
  await expect(page.getByTestId("accounts-codex")).toBeVisible();
  const marks = await page.evaluate(() =>
    [...document.querySelectorAll(".acc-gh-i .agent-ic, .acc-ring .agent-ic")].map((e) => {
      const r = e.getBoundingClientRect();
      return [r.width, r.height, r.left + r.width / 2];
    }),
  );
  expect(marks.length).toBeGreaterThanOrEqual(6); // three headings and their rows
  for (const [w, h] of marks) expect([w, h]).toEqual([16, 16]);
  expect(new Set(marks.map(([, , c]) => Math.round(c))).size).toBe(1);
});

test("the window never scrolls sideways: a scroll into view cannot shift the app off the screen's left edge", async ({ page }) => {
  for (const width of [1100, 900]) {
    await page.setViewportSize({ width, height: 760 });
    await open(page);
    const left = await page.evaluate(() => {
      const w = document.querySelector<HTMLElement>(".window")!;
      w.scrollLeft = 50;
      document.querySelector(".details")?.scrollIntoView();
      return [w.scrollLeft, document.querySelector(".side")!.getBoundingClientRect().left];
    });
    expect(left, `${width}px`).toEqual([0, 0]);
  }
});
