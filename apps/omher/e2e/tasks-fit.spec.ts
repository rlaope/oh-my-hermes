// Fit of Tasks (UI review B26-B30): the search never sits alone on a toolbar row, a narrow row keeps its title over its
// labels, a pale label's dot shows on light, the repo account chip names a login, and Linear's connect state fills the
// pane with one primary action. 1280x820 and the 900x600 minimum window, en and ko.
import { expect, test, type Page } from "@playwright/test";
import { lineCount } from "./layout-helpers";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const REPO = "rlaope/oh-my-hermes";
const D = 86_400;
const now = () => Math.floor(Date.now() / 1000);

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
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

function data() {
  const rows = [
    { number: 1836, title: "Measurement path for the Claude composer calibration", labels: [] },
    { number: 1817, title: "Shadow, decline, refuse and replay — an OMH decision surface from the owner's traffic", labels: [{ name: "enhancement", color: "a2eeef" }, { name: "area/routing", color: "1d76db" }] },
    { number: 1815, title: "Measure the routing-questions lane's model and decision-model arms", labels: [{ name: "area/quality", color: "0052cc" }] },
  ];
  const issues = rows.map((r, i) => ({ ...r, author: "rlaope", state: "open", url: `https://github.com/${REPO}/issues/${r.number}`, created: now() - (i + 2) * D, updated: now() - (i + 1) * D, checks: null }));
  return {
    status: { github: { installed: true, signed_in: true }, gitlab: { installed: false, signed_in: false } },
    items: { [`github:${REPO}:issues`]: issues, [`github:${REPO}:prs`]: [] },
    details: { [`github:${REPO}:issues:1836`]: { body: "body", comments: [] } },
    remotes: {},
    gh: {
      installed: true,
      accounts: [
        { host: "github.com", login: "octo", active: true, state: "success", scopes: ["repo"] },
        { host: "github.com", login: "octo-work", active: false, state: "success", scopes: ["repo"] },
      ],
      me: {},
      fail: {},
    },
  };
}

async function setup(page: Page, o: { lang?: string; theme?: "dark" | "light"; w?: number } = {}) {
  const w = o.w ?? 1280;
  await page.setViewportSize({ width: w, height: w === 900 ? 600 : 820 });
  await page.addInitScript(
    ([lang, theme, d]) => {
      localStorage.setItem("omher.lang", lang as string);
      localStorage.setItem("omher.theme", theme as string);
      if (!sessionStorage.getItem("__tkfit")) {
        // one chosen account on another owner, so the repo is read as gh's active one
        localStorage.setItem("omher.tasks", JSON.stringify({ source: "github", scope: "repo", repo: { github: "rlaope/oh-my-hermes", gitlab: "" }, recent: { github: ["rlaope/oh-my-hermes"], gitlab: [] }, accounts: [{ host: "github.com", login: "octo", color: "#4c8dff" }] }));
        sessionStorage.setItem("__tkfit", "1");
      }
      (window as unknown as { __omherTasks: unknown }).__omherTasks = d;
    },
    [o.lang ?? "en", o.theme ?? "dark", data()] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("tasks-open").click();
  await expect(page.getByTestId("tasks-page")).toBeVisible();
  await expect(page.getByTestId("tasks-row-1836")).toBeVisible();
}

/** Rows of the list's toolbar: the controls on each and the gap left at the row's right end (px). */
const toolbarRows = (page: Page) =>
  page.locator(".tk-chrome").evaluate((c) => {
    const cs = getComputedStyle(c);
    const right = c.getBoundingClientRect().right - parseFloat(cs.paddingRight);
    const rows = new Map<number, { n: string[]; r: number }>();
    for (const el of Array.from(c.children) as HTMLElement[]) {
      const b = el.getBoundingClientRect();
      const top = Math.round(b.top);
      const was = rows.get(top) ?? { n: [], r: 0 };
      rows.set(top, { n: [...was.n, el.className || el.tagName], r: Math.max(was.r, b.right) });
    }
    return [...rows.values()].map((x) => ({ n: x.n, gap: Math.round(right - x.r) }));
  });

test.beforeEach(async () => {
  await mock("mock.reset");
});

for (const [w, lang] of [
  [1280, "en"],
  [1280, "ko"],
  [900, "ko"],
  [900, "en"],
] as const) {
  test(`${w} ${lang}: the search sits in the header beside ×, never alone on a toolbar row`, async ({ page }) => {
    await setup(page, { lang, w });
    const search = page.getByTestId("tasks-search");
    await expect(search).toBeVisible();
    const inHead = await search.evaluate((el) => !!el.closest("header"));
    expect(inHead).toBe(true);
    // one row, or every wrapped row runs to the right edge: no control alone beside empty space
    const check = async () => {
      const rows = await toolbarRows(page);
      if (rows.length > 1) for (const r of rows) expect(Math.abs(r.gap), JSON.stringify(rows)).toBeLessThanOrEqual(1);
      return rows;
    };
    await check();
    // the header itself stays one row
    const head = await page.getByTestId("tasks-page").locator("header").evaluate((h) => Math.round(h.getBoundingClientRect().height));
    expect(head).toBe(52);
    // a narrow row keeps its title: at least 40% of the row's text area, labels give way first
    await page.getByTestId("tasks-row-1836").click();
    const withDrawer = await check();
    // the drawer open in the 900px window: three rows at most (it took four with the search on its own row)
    expect(withDrawer.length, JSON.stringify(withDrawer)).toBeLessThanOrEqual(3);
    const t = await page.getByTestId("tasks-row-1817").evaluate((r) => {
      const area = r.querySelector(".tk-row-t")!.getBoundingClientRect().width;
      const title = r.querySelector(".tk-row-title")!.getBoundingClientRect().width;
      return { area: Math.round(area), title: Math.round(title) };
    });
    expect(t.title / t.area, JSON.stringify(t)).toBeGreaterThan(0.4);
  });
}

test("the repo account chip names gh's active login with its dot, in the UI font", async ({ page }) => {
  await setup(page, { lang: "ko" });
  const chip = page.getByTestId("tasks-repo-account");
  await expect(chip).toHaveText("octo");
  await expect(chip.locator(".tk-dot")).toHaveCount(1);
  expect(await chip.evaluate((el) => getComputedStyle(el).fontFamily)).not.toMatch(/mono/i);
});

test("light: a pale label colour's dot has a ring", async ({ page }) => {
  await setup(page, { theme: "light" });
  const ring = await page.getByTestId("tasks-row-1817").locator(".tk-label i").first().evaluate((el) => getComputedStyle(el).boxShadow);
  expect(ring).not.toBe("none");
});

for (const [w, lang] of [
  [1280, "ko"],
  [900, "en"],
] as const) {
  test(`${w} ${lang}: Linear's connect state is centred in the pane with its mark and one primary button`, async ({ page }) => {
    await setup(page, { lang, w });
    await page.getByTestId("tasks-src-linear").click();
    const box = page.getByTestId("tasks-linear-connect");
    await expect(box).toBeVisible();
    await expect(box.locator("svg.tk-mark[data-source=linear]")).toHaveCount(1);
    await expect(page.getByTestId("tasks-linear-apps")).toHaveClass(/primary/);
    expect(await lineCount(page.getByTestId("tasks-linear-apps"))).toBe(1);
    const m = await box.evaluate((b) => {
      const pane = b.closest(".tk-linear")!.getBoundingClientRect();
      const r = b.getBoundingClientRect();
      const ps = [...b.querySelectorAll<HTMLElement>("p")].map((p) => {
        const range = document.createRange();
        range.selectNodeContents(p);
        const lines = [...range.getClientRects()].filter((x) => x.width > 1);
        const tops = [...new Set(lines.map((x) => Math.round(x.top)))];
        const last = lines.filter((x) => Math.round(x.top) === tops[tops.length - 1]).reduce((a, x) => a + x.width, 0);
        const first = lines.filter((x) => Math.round(x.top) === tops[0]).reduce((a, x) => a + x.width, 0);
        return { lines: tops.length, ratio: tops.length > 1 ? last / first : 1 };
      });
      return { paneH: pane.height, h: r.height, topGap: r.top - pane.top, ps };
    });
    // it fills the pane below the toolbar; no 500px empty band under three small lines
    expect(m.h, JSON.stringify(m)).toBeGreaterThan(m.paneH * 0.6);
    // balanced: a wrapped paragraph's last line is not a stub
    for (const p of m.ps) expect(p.ratio, JSON.stringify(m)).toBeGreaterThan(0.45);
  });
}
