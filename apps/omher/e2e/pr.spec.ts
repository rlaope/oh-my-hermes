// A plan node's pull request: GitHub's state mark (Octicons, GitHub's colours) and "#2353" at the end of the node's
// status line, the same with "· Merged" in its detail. The number comes with the run (`runs.get`), the state apart
// (`runs.prs`), so the graph never waits on GitHub. A click on the number opens the PR's page and does not select
// the node. The demo plan (mock.demo): Color tokens merged #2353, Theme toggle merged #2352, Page styles open
// #2359, Code block colors draft #2360, the rest none.
import { expect, test, type Page } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const DEMO = "dag:20261110_091904_d4a1c7e2/docs-dark-mode";
const WANT: Record<string, [number, string, string] | null> = {
  "color-tokens": [2353, "merged", "Merged"],
  "theme-toggle": [2352, "merged", "Merged"],
  "page-styles": [2359, "open", "Open"],
  "code-colors": [2360, "draft", "Draft"],
  contrast: null,
  "verify-pr": null,
};
// GitHub's own colours per state, dark then light
const COLORS: Record<string, [string, string]> = {
  open: ["rgb(63, 185, 80)", "rgb(26, 127, 55)"],
  merged: ["rgb(163, 113, 247)", "rgb(130, 80, 223)"],
  draft: ["rgb(145, 152, 161)", "rgb(89, 99, 110)"],
};

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => res(JSON.parse(String(m.data)));
    ws.send(JSON.stringify({ id: "p1", op, ...params }));
  });
  ws.close();
  return reply.result;
}

test.beforeEach(async () => {
  await mock("mock.reset");
  await mock("mock.demo");
});

async function openDemo(page: Page, theme: "dark" | "light" = "dark") {
  await page.addInitScript((t) => localStorage.setItem("omher.theme", t), theme);
  const opened: string[] = [];
  await page.exposeFunction("__omherOpened", (u: string) => opened.push(u));
  await page.addInitScript(() => {
    window.open = ((u: string) => {
      (window as unknown as { __omherOpened: (u: string) => void }).__omherOpened(String(u));
      return null;
    }) as typeof window.open;
  });
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("places").click();
  await page.getByTestId("panel-tab-runs").click();
  const box = page.getByTestId("run-graph-box");
  await expect(box).toHaveAttribute("data-run", DEMO);
  await expect(box.getByTestId("run-node")).toHaveCount(6);
  await page.mouse.move(5, 400);
  return { box, opened };
}
const nodeOf = (root: ReturnType<Page["getByTestId"]>, id: string) => root.locator(`[data-testid="run-node"][data-node="${id}"]`);

test("each node that opened a PR ends its status line with GitHub's state mark and the number; the others have none", async ({ page }) => {
  const { box } = await openDemo(page);
  for (const [id, want] of Object.entries(WANT)) {
    const pr = nodeOf(box, id).getByTestId("node-pr");
    if (!want) {
      await expect(pr).toHaveCount(0);
      continue;
    }
    const [n, state] = want;
    await expect(pr).toHaveText(`#${n}`);
    await expect(pr).toHaveAttribute("data-state", state); // from runs.prs, not from the run's words
    await expect(pr.locator("svg.pr-ic")).toHaveAttribute("data-state", state);
    // inside the status line, after the word: one line, never a box of its own
    expect(await pr.evaluate((e) => e.parentElement?.getAttribute("data-testid"))).toBe("node-status");
  }
  // a box is still its title, its facts and its status line
  for (const id of Object.keys(WANT))
    expect(await nodeOf(box, id).evaluate((e) => [...e.children].map((c) => c.getAttribute("data-testid")))).toEqual(["node-title", "node-facts", "node-status"]);
  // the state is asked once per opened run, apart from runs.get
  const ops = (await mock("mock.calls")).calls.map((c: any) => c.op);
  expect(ops.filter((o: string) => o === "runs.prs").length).toBeGreaterThanOrEqual(1);
  expect(ops.indexOf("runs.get")).toBeLessThan(ops.indexOf("runs.prs"));
});

for (const theme of ["dark", "light"] as const) {
  test(`only the mark carries GitHub's colour; the number is muted, with no chip, fill or glow (${theme})`, async ({ page }) => {
    const { box } = await openDemo(page, theme);
    const looks = await box.getByTestId("node-pr").evaluateAll((els) =>
      els.map((e) => {
        const s = getComputedStyle(e);
        const svg = e.querySelector("svg")!;
        const num = getComputedStyle(e.querySelector(".bx-prn")!);
        const r = svg.getBoundingClientRect();
        return {
          state: e.getAttribute("data-state")!,
          icon: getComputedStyle(svg).color,
          size: [Math.round(r.width), Math.round(r.height)],
          number: num.color,
          bg: [s.backgroundColor, s.backgroundImage, s.borderTopWidth, s.boxShadow, s.borderRadius],
          numBg: [num.backgroundColor, num.backgroundImage],
          muted: (() => {
            const i = document.createElement("i");
            i.style.color = "var(--muted)";
            e.appendChild(i);
            const c = getComputedStyle(i).color;
            i.remove();
            return c;
          })(),
        };
      }),
    );
    expect(looks.length).toBe(4);
    for (const l of looks) {
      expect(l.icon, l.state).toBe(COLORS[l.state][theme === "dark" ? 0 : 1]);
      expect(l.size).toEqual([12, 12]);
      expect(l.number, "the number stays the muted text colour").toBe(l.muted);
      expect(l.bg).toEqual(["rgba(0, 0, 0, 0)", "none", "0px", "none", "0px"]);
      expect(l.numBg).toEqual(["rgba(0, 0, 0, 0)", "none"]);
    }
    // the box itself is unchanged: no fill, no gradient, no shadow at rest
    const surface = await page.getByTestId("details").evaluate((e) => getComputedStyle(e).backgroundColor);
    for (const b of await box.getByTestId("run-node").evaluateAll((els) => els.map((e) => [getComputedStyle(e).backgroundColor, getComputedStyle(e).backgroundImage, getComputedStyle(e).boxShadow])))
      expect(b).toEqual([surface, "none", "none"]);
    // the status line still fits: nothing is cut by the browser
    const cut = await box.locator("[data-testid=node-status]").evaluateAll((els) => els.filter((e) => e.scrollWidth > e.clientWidth + 0.5).map((e) => e.textContent));
    expect(cut).toEqual([]);
    // the PR sits on the status line's own baseline row, at its right end, inside the box
    for (const id of ["color-tokens", "page-styles", "code-colors"]) {
      const [line, pr, node] = await Promise.all([
        nodeOf(box, id).getByTestId("node-status").boundingBox(),
        nodeOf(box, id).getByTestId("node-pr").boundingBox(),
        nodeOf(box, id).boundingBox(),
      ]);
      expect(Math.abs(pr!.y + pr!.height / 2 - (line!.y + line!.height / 2))).toBeLessThanOrEqual(1.5);
      expect(pr!.x + pr!.width).toBeLessThanOrEqual(node!.x + node!.width - 11);
      expect(Math.abs(pr!.x + pr!.width - (line!.x + line!.width))).toBeLessThanOrEqual(1);
    }
  });
}

test("a click on the number opens the PR's page and does not select the node; a click elsewhere on the box still does", async ({ page }) => {
  const { box, opened } = await openDemo(page);
  const node = nodeOf(box, "color-tokens");
  await node.getByTestId("node-pr").click();
  await expect.poll(() => opened).toEqual(["https://github.com/rlaope/oh-my-hermes/pull/2353"]);
  await expect(node).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByTestId("run-drawer")).toHaveCount(0);
  await node.getByTestId("node-title").click();
  await expect(node).toHaveAttribute("aria-pressed", "true");
  // the detail: the same mark, "#2353 · Merged", a link to the same page
  const pr = page.getByTestId("run-drawer").getByTestId("run-pr");
  await expect(pr).toHaveText("#2353 · Merged");
  await expect(pr).toHaveAttribute("data-state", "merged");
  await expect(pr.locator("svg.pr-ic")).toHaveAttribute("data-state", "merged");
  await expect(pr.locator("a")).toHaveAttribute("href", "https://github.com/rlaope/oh-my-hermes/pull/2353");
  await pr.locator("a").click();
  await expect.poll(() => opened.length).toBe(2);
  expect(opened[1]).toBe("https://github.com/rlaope/oh-my-hermes/pull/2353");
  // a node with no PR says nothing about one
  await nodeOf(box, "contrast").getByTestId("node-title").click();
  await expect(page.getByTestId("run-drawer")).toHaveAttribute("data-node", "contrast");
  await expect(page.getByTestId("run-drawer").getByTestId("run-pr")).toHaveCount(0);
});

test("in the full view (⌘⇧G) a click on the number neither selects nor drags the node", async ({ page }) => {
  const { opened } = await openDemo(page);
  await page.getByTestId("graph-expand").click();
  const full = page.getByTestId("runs-full");
  await expect(full.getByTestId("run-node")).toHaveCount(6);
  await page.waitForTimeout(1300);
  const node = nodeOf(full, "page-styles");
  const before = await node.boundingBox();
  await node.getByTestId("node-pr").click();
  await expect.poll(() => opened).toEqual(["https://github.com/rlaope/oh-my-hermes/pull/2359"]);
  await expect(node).toHaveAttribute("aria-pressed", "false");
  await expect(full.getByTestId("run-drawer")).toHaveCount(0);
  expect(await node.boundingBox()).toEqual(before);
  await expect(node.getByTestId("node-pr")).toHaveAttribute("data-state", "open");
});

test("a closed PR carries GitHub's red closed mark, in the box and in the detail", async ({ page }) => {
  // GitHub says #2359 was closed without a merge
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
      if (msg.ok && ops.get(msg.id) === "runs.prs") msg.result.prs["page-styles"].state = "closed";
      ws.send(JSON.stringify(msg));
    });
  });
  const { box } = await openDemo(page);
  const pr = nodeOf(box, "page-styles").getByTestId("node-pr");
  await expect(pr).toHaveAttribute("data-state", "closed");
  expect(await pr.locator("svg").evaluate((e) => getComputedStyle(e).color)).toBe("rgb(248, 81, 73)");
  expect(await pr.locator("path").getAttribute("d")).toMatch(/^M3\.25 1A2\.25 2\.25 0 0 1 4 5\.372v5\.256/); // git-pull-request-closed
  await nodeOf(box, "page-styles").getByTestId("node-title").click();
  await expect(page.getByTestId("run-drawer").getByTestId("run-pr")).toHaveText("#2359 · Closed");
});

test("without GitHub's answer the number shows with no state colour, and the graph does not wait for it", async ({ page }) => {
  // runs.prs that never answers: the graph draws, the numbers are there, the marks stay the muted text colour
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((raw) => {
      if (JSON.parse(String(raw)).op === "runs.prs") return; // swallowed: no reply ever comes
      server.send(raw);
    });
    server.onMessage((raw) => ws.send(raw));
  });
  const { box } = await openDemo(page);
  const pr = nodeOf(box, "color-tokens").getByTestId("node-pr");
  await expect(pr).toHaveText("#2353");
  await expect(pr).toHaveAttribute("data-state", "unknown");
  const [icon, muted] = await pr.evaluate((e) => {
    const i = document.createElement("i");
    i.style.color = "var(--muted)";
    e.appendChild(i);
    const m = getComputedStyle(i).color;
    i.remove();
    return [getComputedStyle(e.querySelector("svg")!).color, m];
  });
  expect(icon).toBe(muted);
  await nodeOf(box, "color-tokens").getByTestId("node-title").click();
  await expect(page.getByTestId("run-drawer").getByTestId("run-pr")).toHaveText("#2353");
});
