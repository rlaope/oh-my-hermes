// A person who has Hermes but not oh-my-hermes (`omh`). The mock host reports that with `__omherMockNoOmh` (the
// shell's `via: "hermes"` row); `__OMHER_GATE__` stands in for the shell's one fixed installer, so nothing installs.
// One test per item of the brief: (1) the + row reads Hermes and opens a Hermes chat in the folder on the bot in view,
// (2) with `omh` nothing changes, (3) that session has no dead Terminal toggle, (4) one quiet "Add oh-my-hermes" line
// runs the same installer and the row then reads oh-my-hermes, (4a) a third first-run card recommends it,
// (5) Plans says what is missing in plain words, (6) the new strings come in every language.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string, params: Record<string, unknown> = {}): Promise<{ calls?: { op: string; params: Record<string, unknown> }[] }> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<{ result: unknown }>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "h1") res(msg);
    };
    ws.send(JSON.stringify({ id: "h1", op, ...params }));
  });
  ws.close();
  return reply.result as { calls?: { op: string; params: Record<string, unknown> }[] };
}

test.beforeEach(async () => {
  await mock("mock.reset");
});

type Plan = { exit: number; lines: string[]; hold?: boolean };

/** Hermes without omh (or with it, `omh: true`), and a stand-in installer that plays `plan` and, on a clean exit,
 *  makes `omh` found from then on (the next agents look-up). */
async function open(page: Page, o: { omh?: boolean; plan?: Plan; onboarding?: boolean; lang?: string } = {}) {
  await page.addInitScript(
    ([omh, plan, onb, lang]) => {
      const w = window as unknown as Record<string, unknown>;
      localStorage.removeItem("omher.sessions.recent");
      if (!sessionStorage.getItem("kept")) {
        localStorage.removeItem("omher.omhOffer.hidden");
        sessionStorage.setItem("kept", "1");
      }
      if (onb) localStorage.removeItem("omher.onboarded");
      if (lang) localStorage.setItem("omher.lang", lang as string);
      w.__omherPickFolder = "/Users/you/code/web-app";
      w.__omherMockAgents = ["claude", "codex", ...(omh ? ["omh"] : [])];
      w.__omherMockNoOmh = !omh;
      const calls: string[] = [];
      w.__installCalls = calls;
      const p = plan as Plan;
      w.__OMHER_GATE__ = {
        status: async () => ({ state: "ready" }),
        retry: async () => {},
        installCommand: async () => "",
        install: async (onEvent: (e: unknown) => void) => {
          calls.push("install");
          for (const text of p.lines) {
            onEvent({ kind: "line", text });
            await new Promise((r) => setTimeout(r, 30));
          }
          await new Promise((r) => setTimeout(r, 300));
          if (p.hold) await new Promise(() => {});
          onEvent({ kind: "exit", code: p.exit });
          if (p.exit === 0) {
            w.__omherMockNoOmh = false;
            (w.__omherMockAgents as string[]).push("omh");
          }
          return p.exit;
        },
      };
    },
    [!!o.omh, o.plan ?? { exit: 0, lines: ["[ok] omh installed"] }, !!o.onboarding, o.lang ?? ""] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
}

const installs = (page: Page) => page.evaluate(() => ((window as unknown as { __installCalls: string[] }).__installCalls ?? []).length);

test("1. Hermes without omh: the + row reads Hermes with Hermes' mark and opens a Hermes chat in the folder, on the bot in view", async ({ page }) => {
  await open(page);
  await page.getByTestId("bot-friren").click();
  await expect(page.getByTestId("bot-friren")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("session-new").click();
  const row = page.getByTestId("session-menu").getByTestId("session-agent-omh");
  await expect(row).toContainText("Hermes");
  await expect(row).not.toContainText("oh-my-hermes");
  await expect(row).not.toHaveAttribute("aria-disabled", "true");
  await expect(row).not.toContainText("Not installed");
  await expect(row.locator('[data-mark="hermes"]')).toHaveCount(1);
  await row.click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("What is in this folder?");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-agent")).toHaveText("Hermes");
  await expect(page.getByTestId("session-cwd")).toHaveText("~/code/web-app");
  const opened = (await mock("mock.calls")).calls!.find((c) => c.op === "folder.open")!;
  expect(opened.params).toMatchObject({ bot: "friren", cwd: "/Users/you/code/web-app" });
  await expect
    .poll(async () => (await mock("mock.calls")).calls!.find((c) => c.op === "chat.send" && c.params.session)?.params.text)
    .toBe("What is in this folder?");
  await expect(page.getByTestId("session-list").getByTestId("session-sub").first()).toContainText("Hermes");
});

test("2. Hermes and omh: the row reads oh-my-hermes as before, and nothing offers to add it", async ({ page }) => {
  await open(page, { omh: true });
  await page.getByTestId("session-new").click();
  const row = page.getByTestId("session-menu").getByTestId("session-agent-omh");
  await expect(row).toContainText("oh-my-hermes");
  await expect(row.locator('[data-mark="omh"]')).toHaveCount(1);
  await expect(page.getByTestId("session-add-omh")).toHaveCount(0);
});

test("3. a Hermes session without omh has no Terminal toggle (it would start omh); its model and panel stay", async ({ page }) => {
  await open(page);
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-omh").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("hello");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-agent")).toHaveText("Hermes");
  await expect(page.getByTestId("session-status")).toHaveText("Ready");
  await expect(page.getByTestId("session-terminal-toggle")).toHaveCount(0);
  await expect(page.getByTestId("head-right").getByTestId("panel-button")).toBeVisible();
  // no terminal was ever started for it
  const ops = await page.evaluate(() => ((window as unknown as { __omherSessionCalls?: { op: string }[] }).__omherSessionCalls ?? []).map((c) => c.op));
  expect(ops).not.toContain("start");
});

test("3b. with omh the same session keeps its Terminal toggle", async ({ page }) => {
  await open(page, { omh: true });
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-omh").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("composer").fill("hello");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("session-agent")).toHaveText("oh-my-hermes");
  await expect(page.getByTestId("session-terminal-toggle")).toBeVisible();
});

const LINES = Array.from({ length: 12 }, (_, i) => `step ${i + 1}: fetching part ${i + 1} of the oh-my-hermes wheel`);

/** The rectangles that matter in the sidebar's top row and the popover. */
const rects = (page: Page) =>
  page.evaluate(() => {
    const r = (sel: string) => {
      const e = document.querySelector(sel);
      if (!e) return null;
      const b = e.getBoundingClientRect();
      return { top: b.top, bottom: b.bottom, left: b.left, right: b.right };
    };
    return { icon: r("[data-testid=omh-notice]"), plus: r(".side-add > .ui-ib:last-child"), pop: r("[data-testid=omh-pop]")?.top !== undefined ? r(".omh-pop") : null, h: innerHeight, w: innerWidth };
  });

test("C. Hermes without omh: one quiet ! left of the top row's +, the +'s size, no fill, nothing overlapping", async ({ page }) => {
  await open(page);
  const icon = page.getByTestId("omh-notice");
  await expect(icon).toBeVisible();
  await expect(icon).toHaveAttribute("aria-label", "oh-my-hermes is not installed");
  await expect(icon).toHaveAttribute("title", "oh-my-hermes is not installed");
  const m = await rects(page);
  expect(m.icon && m.plus).toBeTruthy();
  // left of the +, same size, no overlap, same row
  expect(m.icon!.right).toBeLessThanOrEqual(m.plus!.left);
  expect(Math.round(m.icon!.right - m.icon!.left)).toBe(Math.round(m.plus!.right - m.plus!.left));
  expect(Math.round(m.icon!.bottom - m.icon!.top)).toBe(Math.round(m.plus!.bottom - m.plus!.top));
  expect(Math.abs(m.icon!.top - m.plus!.top)).toBeLessThanOrEqual(0.5);
  const look = await icon.evaluate((el) => {
    const cs = getComputedStyle(el);
    const plus = getComputedStyle(document.querySelector(".side-add > .ui-ib:last-child")!);
    return { bg: cs.backgroundColor, border: cs.borderTopWidth, shadow: cs.boxShadow, color: cs.color, plusColor: plus.color, badge: el.querySelectorAll(".badge, [data-count]").length };
  });
  expect(look.bg).toBe("rgba(0, 0, 0, 0)");
  expect(look.border).toBe("0px");
  expect(look.shadow).toBe("none");
  expect(look.color).toBe(look.plusColor);
  expect(look.badge).toBe(0);
});

test("C. with omh there is no ! at all", async ({ page }) => {
  await open(page, { omh: true });
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.waitForTimeout(300);
  await expect(page.getByTestId("omh-notice")).toHaveCount(0);
});

test("C. the popover: title, one sentence, Install and Don't show again; 12-13px text, 4-6px radius", async ({ page }) => {
  await open(page);
  await page.getByTestId("omh-notice").click();
  const pop = page.getByTestId("omh-pop");
  await expect(pop).toBeVisible();
  await expect(pop.locator(".omh-pop-t")).toHaveText("oh-my-hermes");
  await expect(pop).toContainText("plan big jobs in parts");
  await expect(pop).toContainText("Plans");
  await expect(pop).not.toContainText(/dag|delegate_task|omh_/);
  await expect(page.getByTestId("omh-pop-install")).toHaveText("Install");
  await expect(page.getByTestId("omh-pop-hide")).toHaveText("Don't show again");
  const look = await page.locator(".omh-pop").evaluate((el) => {
    const cs = getComputedStyle(el);
    const sizes = [...el.querySelectorAll("p, button, b")].map((e) => parseFloat(getComputedStyle(e).fontSize));
    return { radius: parseFloat(cs.borderTopLeftRadius), sizes };
  });
  expect(look.radius).toBeGreaterThanOrEqual(4);
  expect(look.radius).toBeLessThanOrEqual(6);
  for (const s of look.sizes) {
    expect(s).toBeGreaterThanOrEqual(12);
    expect(s).toBeLessThanOrEqual(13);
  }
  // it covers neither the ! nor the +
  const m = await rects(page);
  for (const b of [m.icon!, m.plus!]) expect(m.pop!.top >= b.bottom || m.pop!.bottom <= b.top).toBe(true);
});

/** Every sidebar element beside the popover: one it lies over must be under it across its whole width, never cut by
 *  the popover's left or right edge (the bottom edge may cross a row: the popover has its own border). */
const partly = (page: Page) =>
  page.evaluate(() => {
    const pop = document.querySelector(".omh-pop")!.getBoundingClientRect();
    const side = document.querySelector(".side")!;
    const bad: string[] = [];
    // what paints: the rows themselves, the search field, and every leaf (text, icons, rings)
    const painted = [...side.querySelectorAll(".search, .bot-list > *, .ss-list > *, .side-sec > .side-sh, .side-foot > *, *")].filter(
      (e) => e.matches(".search, .bot-list > *, .ss-list > *, .side-sec > .side-sh, .side-foot > *") || e.children.length === 0 || e.matches(".ui-ring, svg"),
    );
    for (const e of painted) {
      if (e.closest(".omh-note") || e.closest("svg") !== e && e.closest("svg")) continue;
      const r = e.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      if (r.bottom <= pop.top + 0.5 || r.top >= pop.bottom - 0.5) continue;
      const cutLeft = r.left < pop.left - 0.5 && r.right > pop.left + 0.5;
      const cutRight = r.left < pop.right - 0.5 && r.right > pop.right + 0.5;
      if (cutLeft || cutRight) bad.push(`${e.className || e.tagName} ${Math.round(r.left)},${Math.round(r.top)}-${Math.round(r.right)},${Math.round(r.bottom)}`);
    }
    return { bad, pop: { left: pop.left, right: pop.right, top: pop.top, bottom: pop.bottom } };
  });

/** The popover's vertical gaps, top to bottom: its edge to the title, between each part (title, sentence, log, error,
 *  actions), and the actions to its edge. */
const gaps = (page: Page) =>
  page.evaluate(() => {
    const pop = document.querySelector(".omh-pop")!.getBoundingClientRect();
    const parts = [...document.querySelectorAll(".omh-pop-c > *"), document.querySelector(".omh-pop-a")!].map((e) => e.getBoundingClientRect());
    const edges = [pop.top, ...parts.flatMap((r) => [r.top, r.bottom]), pop.bottom];
    const out: number[] = [];
    for (let i = 0; i < edges.length; i += 2) out.push(Math.round((edges[i + 1] - edges[i]) * 10) / 10);
    return { gaps: out, pop: { top: pop.top, bottom: pop.bottom, left: pop.left, right: pop.right }, h: innerHeight, w: innerWidth };
  });

const settled = (page: Page) => page.waitForFunction(() => document.querySelector(".omh-pop")!.getAnimations().every((a) => a.playState !== "running"));

test("C. the popover is exactly as wide as a sidebar row, starts under the top row, and cuts no sidebar element at its left or right edge", async ({ page }) => {
  await open(page);
  await page.getByTestId("omh-notice").click();
  await expect(page.getByTestId("omh-pop")).toBeVisible();
  await settled(page);
  const m = await page.evaluate(() => {
    const r = (sel: string) => document.querySelector(sel)!.getBoundingClientRect();
    return { pop: r(".omh-pop"), row: r(".bot-list > *"), top: r(".side-top"), side: r(".side") };
  });
  // as wide as the rows, plus the live ring's reach past their edge (4px each side), and inside the sidebar
  expect(m.row.left - m.pop.left).toBeGreaterThanOrEqual(4);
  expect(m.row.left - m.pop.left).toBeLessThanOrEqual(4.5);
  expect(m.pop.right - m.row.right).toBeGreaterThanOrEqual(4);
  expect(m.pop.right - m.row.right).toBeLessThanOrEqual(4.5);
  expect(m.pop.left).toBeGreaterThanOrEqual(m.side.left);
  expect(m.pop.right).toBeLessThanOrEqual(m.side.right);
  expect(Math.abs(m.pop.top - m.top.bottom)).toBeLessThanOrEqual(0.5);
  const c = await partly(page);
  expect(c.bad, JSON.stringify(c.pop)).toEqual([]);
});

test("C. the popover takes its natural height: the same padding above the title and below the actions, even gaps between its parts", async ({ page }) => {
  await open(page);
  await page.getByTestId("omh-notice").click();
  await settled(page);
  const m = await gaps(page);
  // edge→title, title→sentence, sentence→actions, actions→edge
  expect(m.gaps.length, JSON.stringify(m)).toBe(4);
  expect(Math.abs(m.gaps[0] - m.gaps[m.gaps.length - 1]), JSON.stringify(m)).toBeLessThanOrEqual(0.5);
  for (const g of m.gaps) {
    expect(g, JSON.stringify(m)).toBeGreaterThanOrEqual(10);
    expect(g, JSON.stringify(m)).toBeLessThanOrEqual(16);
  }
});

test("C. running: Installing… keeps Install's outlined box and left edge, only lower contrast", async ({ page }) => {
  await open(page, { plan: { exit: 0, lines: ["[1/4] Create isolated Python environment at ~/.local/share/omh/venv"], hold: true } });
  await page.getByTestId("omh-notice").click();
  const b = page.getByTestId("omh-pop-install");
  const look = () =>
    b.evaluate((el) => {
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      const p = document.querySelector(".omh-pop-c")!.getBoundingClientRect();
      return { left: Math.round(r.left - p.left), h: r.height, border: cs.borderTopWidth, style: cs.borderTopStyle, borderColor: cs.borderTopColor, color: cs.color, opacity: cs.opacity };
    });
  const rest = await look();
  await b.click();
  await expect(b).toHaveText("Installing…");
  await expect(b).toBeDisabled();
  const run = await look();
  expect(run.left).toBe(rest.left);
  expect(run.left).toBe(0);
  expect(run.h).toBe(rest.h);
  expect(run.border).toBe("1px");
  expect(run.style).toBe("solid");
  expect(run.borderColor).not.toBe("rgba(0, 0, 0, 0)");
  expect(run.color).not.toBe(rest.color);
  expect(run.opacity).toBe("1");
});

test("C. the output wraps at spaces and after / only, never inside a word; one token too long for the box scrolls sideways", async ({ page }) => {
  const LONG = "sha256:" + "0123456789abcdef".repeat(4);
  await open(page, { plan: { exit: 0, lines: ["[1/4] Create isolated Python environment at ~/.local/share/omh/venv", LONG], hold: true } });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  const log = page.getByTestId("omh-pop-log");
  await expect(log).toContainText("0123456789abcdef");
  const m = await log.evaluate((el) => {
    // the words of each line, as the rows they land on: a word split over two rows has two client rects
    const split: string[] = [];
    for (const line of el.querySelectorAll(".gate-line")) {
      const text = line.textContent ?? "";
      const node = document.createTreeWalker(line, NodeFilter.SHOW_TEXT);
      let offset = 0;
      const runs: { n: Text; start: number }[] = [];
      for (let t = node.nextNode() as Text | null; t; t = node.nextNode() as Text | null) {
        runs.push({ n: t, start: offset });
        offset += t.data.length;
      }
      // words between spaces, and between "/" inside a path
      const re = /[^\s/]+\/?/g;
      for (let w; (w = re.exec(text)); ) {
        const range = document.createRange();
        const at = (i: number) => {
          const r = runs.filter((x) => x.start <= i).pop()!;
          return [r.n, i - r.start] as const;
        };
        const [sn, so] = at(w.index);
        const [en, eo] = at(w.index + w[0].length - 1);
        range.setStart(sn, so);
        range.setEnd(en, eo + 1);
        const tops = new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.top)));
        if (tops.size > 1) split.push(w[0]);
      }
    }
    const rows = [...el.querySelectorAll(".gate-line")].map((l) => Math.round(l.getBoundingClientRect().height / 18));
    return { split, rows, sw: el.scrollWidth, cw: el.clientWidth };
  });
  expect(m.split).toEqual([]);
  // the path line wraps (at spaces / after "/"), the long token stays on one row and the box scrolls sideways
  expect(m.rows[1]).toBe(1);
  expect(m.sw).toBeGreaterThan(m.cw);
});

test("C. the ! has the + menu's pressed look while its popover is open, and none at rest", async ({ page }) => {
  await open(page);
  const icon = page.getByTestId("omh-notice");
  const bg = () => icon.evaluate((el) => getComputedStyle(el).backgroundColor);
  await page.mouse.move(700, 500);
  expect(await bg()).toBe("rgba(0, 0, 0, 0)");
  await icon.click();
  await expect(icon).toHaveAttribute("aria-expanded", "true");
  await page.mouse.move(700, 500);
  const pressed = await bg();
  // the SESSIONS +, its menu open
  await page.keyboard.press("Escape");
  await page.getByTestId("session-new").click();
  await page.mouse.move(700, 500);
  const plus = await page.getByTestId("session-new").evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(pressed).not.toBe("rgba(0, 0, 0, 0)");
  expect(pressed).toBe(plus);
});

test("C. Install is the quiet outlined action: transparent, a thin border, 12px, never the brightest thing in the popover", async ({ page }) => {
  await open(page);
  await page.getByTestId("omh-notice").click();
  const look = await page.getByTestId("omh-pop-install").evaluate((el) => {
    const cs = getComputedStyle(el);
    const pop = getComputedStyle(el.closest(".omh-pop")!);
    return { bg: cs.backgroundColor, border: cs.borderTopWidth, style: cs.borderTopStyle, size: cs.fontSize, popBg: pop.backgroundColor };
  });
  expect(look.bg).toBe("rgba(0, 0, 0, 0)");
  expect(look.border).toBe("1px");
  expect(look.style).toBe("solid");
  expect(look.size).toBe("12px");
});

test("C. running: the installer's output in the house style, as tall as its lines, then it scrolls; one run only", async ({ page }) => {
  await open(page, { plan: { exit: 0, lines: ["Installing oh-my-hermes 4.9.2"], hold: true } });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  await expect(page.getByTestId("omh-pop-install")).toHaveText("Installing…");
  await expect(page.getByTestId("omh-pop-install")).toBeDisabled();
  // one spinner only: the "!" turns into it; the popover has none of its own
  await expect(page.getByTestId("omh-notice").locator(".ui-spin")).toHaveCount(1);
  await expect(page.locator(".omh-pop .ui-spin")).toHaveCount(0);
  const log = page.getByTestId("omh-pop-log");
  await expect(log).toContainText("Installing oh-my-hermes");
  const look = await log.evaluate((el) => {
    const cs = getComputedStyle(el);
    const probe = document.createElement("div");
    probe.style.background = "var(--raise)";
    document.body.appendChild(probe);
    const raise = getComputedStyle(probe).backgroundColor;
    probe.remove();
    const kids = [...el.children].map((c) => c.getBoundingClientRect());
    const text = kids.length ? kids[kids.length - 1].bottom - kids[0].top : 0;
    const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    return { bg: cs.backgroundColor, raise, radius: parseFloat(cs.borderTopLeftRadius), size: cs.fontSize, family: cs.fontFamily, sh: el.scrollHeight, ch: el.clientHeight, text, pad };
  });
  expect(look.bg).not.toBe("rgb(0, 0, 0)");
  expect(look.bg).toBe(look.raise);
  expect(look.radius).toBeGreaterThanOrEqual(4);
  expect(look.radius).toBeLessThanOrEqual(6);
  expect(look.size).toBe("12px");
  expect(look.family).toMatch(/mono|Menlo/i);
  // as tall as its line (wrapped or not), no dead space under it, nothing to scroll
  expect(look.sh).toBe(look.ch);
  expect(look.text).toBeGreaterThan(0);
  expect(Math.abs(look.ch - look.pad - look.text)).toBeLessThanOrEqual(1);
  expect(await installs(page)).toBe(1);
});

test("C. the output takes the popover's whole inner width; a short line stays one line, a long one wraps", async ({ page }) => {
  await open(page, { plan: { exit: 0, lines: ["[ok] Hermes Agent", "step ".repeat(14) + "xxxx"], hold: true } });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  const log = page.getByTestId("omh-pop-log");
  await expect(log).toContainText("xxxx");
  const m = await log.evaluate((el) => {
    const c = el.closest(".omh-pop-c")!;
    const lines = [...el.querySelectorAll(".gate-line")].map((l) => l.getBoundingClientRect().height);
    return { log: el.getBoundingClientRect().width, inner: c.clientWidth, lines };
  });
  expect(Math.abs(m.log - m.inner)).toBeLessThanOrEqual(1);
  expect(m.lines[0]).toBeLessThanOrEqual(18.5);
  expect(m.lines[1]).toBeGreaterThan(18.5);
});

test("C. a long output stops at five lines and scrolls, the newest line in view", async ({ page }) => {
  await open(page, { plan: { exit: 0, lines: LINES, hold: true } });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  const log = page.getByTestId("omh-pop-log");
  await expect(log).toContainText("step 12");
  const m = await log.evaluate((el) => ({ sh: el.scrollHeight, ch: el.clientHeight, top: el.scrollTop }));
  expect(m.ch).toBe(5 * 18);
  expect(m.sh).toBeGreaterThan(m.ch);
  expect(m.top + m.ch).toBeGreaterThanOrEqual(m.sh - 1);
  // whole rows only: scrolled to its end, the top edge falls on the 18px row grid, so no row shows cut
  expect(m.top % 18).toBe(0);
});

test("C. done: the ! and its popover go, the + row reads oh-my-hermes and its Add line is gone", async ({ page }) => {
  await open(page, { plan: { exit: 0, lines: ["Installing oh-my-hermes …", "[ok] omh installed"] } });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  await expect(page.getByTestId("omh-notice")).toHaveCount(0);
  await expect(page.getByTestId("omh-pop")).toHaveCount(0);
  expect(await installs(page)).toBe(1);
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-menu").getByTestId("session-agent-omh")).toContainText("oh-my-hermes");
  await expect(page.getByTestId("session-add-omh")).toHaveCount(0);
});

test("C. failed: the last line and Install again, which runs the same installer again", async ({ page }) => {
  await open(page, { plan: { exit: 1, lines: ["Installing oh-my-hermes …", "[failed] could not reach github.com"] } });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  await expect(page.getByTestId("omh-pop-error")).toHaveText("[failed] could not reach github.com");
  await expect(page.getByTestId("omh-pop-install")).toHaveText("Install again");
  await expect(page.getByTestId("omh-notice")).toBeVisible();
  // nothing in the popover runs past its edges (Install again and Don't show again wrap if they must)
  const over = await page.locator(".omh-pop").evaluate((pop) => {
    const p = pop.getBoundingClientRect();
    return [...pop.querySelectorAll("button, p, b, pre")].filter((e) => {
      const r = e.getBoundingClientRect();
      return r.left < p.left || r.right > p.right - 1;
    }).length;
  });
  expect(over).toBe(0);
  await page.getByTestId("omh-pop-install").click();
  await expect.poll(() => installs(page)).toBe(2);
});

test("C. a silent failure says the exit code", async ({ page }) => {
  await open(page, { plan: { exit: 7, lines: [] } });
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-install").click();
  await expect(page.getByTestId("omh-pop-error")).toHaveText("The installer stopped (exit 7).");
});

test("C+D. Don't show again hides the ! (also after a reload); the + menu's line closes the menu and opens the popover again", async ({ page }) => {
  await open(page);
  await page.getByTestId("omh-notice").click();
  await page.getByTestId("omh-pop-hide").click();
  await expect(page.getByTestId("omh-notice")).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("bot-kami")).toBeVisible();
  await page.waitForTimeout(300);
  await expect(page.getByTestId("omh-notice")).toHaveCount(0);
  await page.getByTestId("session-new").click();
  const line = page.getByTestId("session-add-omh");
  await expect(line).toHaveText("Add oh-my-hermes");
  await line.click();
  await expect(page.getByTestId("session-menu")).toHaveCount(0);
  await expect(page.getByTestId("omh-notice")).toBeVisible();
  await expect(page.getByTestId("omh-pop")).toBeVisible();
  // the menu prints no output of its own, and nothing was installed by picking the line
  await expect(page.locator("[data-testid=session-add-omh-log]")).toHaveCount(0);
  expect(await installs(page)).toBe(0);
});

test("D. the + menu's line is a quiet borderless row and never runs the installer itself", async ({ page }) => {
  await open(page);
  await page.getByTestId("session-new").click();
  const line = page.getByTestId("session-add-omh");
  const look = await line.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { border: cs.borderTopWidth, bg: cs.backgroundColor, size: parseFloat(cs.fontSize), align: cs.textAlign };
  });
  expect(look.border).toBe("0px");
  expect(look.bg).toBe("rgba(0, 0, 0, 0)");
  expect(look.size).toBeGreaterThanOrEqual(12);
  expect(look.size).toBeLessThanOrEqual(13);
  expect(look.align).toBe("left");
  await line.click();
  await expect(page.getByTestId("omh-pop")).toBeVisible();
  expect(await installs(page)).toBe(0);
});

for (const height of [600, 720, 820]) {
  test(`C. the popover with a long output stays inside a ${height}px window with air at both ends`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height });
    await open(page, { plan: { exit: 0, lines: LINES, hold: true } });
    await page.getByTestId("omh-notice").click();
    await page.getByTestId("omh-pop-install").click();
    await expect(page.getByTestId("omh-pop-log")).toContainText("step 12");
    await page.waitForTimeout(250);
    const m = await rects(page);
    expect(m.pop!.top).toBeGreaterThanOrEqual(4);
    expect(m.pop!.bottom).toBeLessThanOrEqual(m.h - 4);
    expect(m.pop!.left).toBeGreaterThanOrEqual(4);
    expect(m.pop!.right).toBeLessThanOrEqual(m.w - 4);
    // and no sidebar element shows partly under it
    const c = await partly(page);
    expect(c.bad, JSON.stringify(c.pop)).toEqual([]);
    // Install again's buttons are in view: the actions never scroll away
    await expect(page.getByTestId("omh-pop-install")).toBeInViewport();
    // no dead band inside it: every vertical gap (edges, title, sentence, log, actions) is at most 16px
    const g = await gaps(page);
    expect(g.gaps.length, JSON.stringify(g)).toBe(5);
    for (const v of g.gaps) expect(v, JSON.stringify(g)).toBeLessThanOrEqual(16);
  });

  test(`C. at rest in a ${height}px window the popover has no vertical gap over 16px and stays inside the window`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height });
    await open(page);
    await page.getByTestId("omh-notice").click();
    await settled(page);
    const g = await gaps(page);
    for (const v of g.gaps) expect(v, JSON.stringify(g)).toBeLessThanOrEqual(16);
    expect(g.pop.top).toBeGreaterThanOrEqual(4);
    expect(g.pop.bottom).toBeLessThanOrEqual(g.h - 4);
    expect(g.pop.left).toBeGreaterThanOrEqual(4);
    expect(g.pop.right).toBeLessThanOrEqual(g.w - 4);
    const c = await partly(page);
    expect(c.bad, JSON.stringify(c.pop)).toEqual([]);
  });
}

test("5. Plans without omh: the plain empty state says what adds plans, no error and no spinner", async ({ page }) => {
  await open(page);
  await page.getByTestId("bot-friren").click();
  await page.getByTestId("panel-button").click();
  const empty = page.getByTestId("plans-empty");
  await expect(empty).toContainText("No plans yet.");
  await expect(page.getByTestId("plans-none-how")).toHaveText(/oh-my-hermes, which isn't on this computer/);
  await expect(page.getByTestId("plans-none-how")).not.toContainText("dag ulw");
  await expect(page.getByTestId("panel-runs").locator(".pn-empty.bad, .ui-spin")).toHaveCount(0);
});

for (const [lang, line, row, tip] of [
  ["ko", "oh-my-hermes 추가", "Hermes", "oh-my-hermes가 설치되어 있지 않아요"],
  ["ja", "oh-my-hermes を追加", "Hermes", "oh-my-hermes がインストールされていません"],
  ["zh", "添加 oh-my-hermes", "Hermes", "未安装 oh-my-hermes"],
] as const) {
  test(`6. the new line in ${lang}`, async ({ page }) => {
    await open(page, { lang });
    await page.getByTestId("session-new").click();
    await expect(page.getByTestId("session-add-omh")).toHaveText(line);
    await expect(page.getByTestId("session-agent-omh")).toContainText(row);
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("omh-notice")).toHaveAttribute("aria-label", tip);
  });
}
