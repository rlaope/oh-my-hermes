// The SESSIONS + menu's "Not installed" rows carry each agent's install line as its own docs give it (omher only
// shows the line, it never runs it): pi's npm package moved to @earendil-works, oh-my-pi's npm build needs Bun so the
// line is its installer, and Grok has a one-line installer instead of "see grok docs".
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

/** Where the PR shots go (unset: none are taken). */
const SHOTS = process.env.OMHER_SHOTS || "";
/** `before` or `after`, in the shot file names. */
const PHASE = process.env.OMHER_SHOTS_PHASE || "after";

async function open(page: Page, theme: string) {
  await page.addInitScript((t) => {
    localStorage.setItem("omher.theme", t);
    localStorage.setItem("omher.sessions.recent", JSON.stringify([{ agent: "claude", cwd: "/Users/you/code/web-app", at: 1 }]));
    (window as unknown as Record<string, unknown>).__omherMockAgents = ["claude", "codex", "omo", "omh"];
  }, theme);
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await page.getByTestId("session-new").click();
  await expect(page.getByTestId("session-menu")).toBeVisible();
}

test("a missing agent's row names the install line from that agent's own docs", async ({ page }) => {
  await open(page, "dark");
  const menu = page.getByTestId("session-menu");
  await expect(menu.getByTestId("session-agent-pi")).toHaveAttribute(
    "title",
    "pi was not found on this computer · install: npm i -g --ignore-scripts @earendil-works/pi-coding-agent",
  );
  await expect(menu.getByTestId("session-agent-omp")).toHaveAttribute("title", "omp was not found on this computer · install: curl -fsSL https://omp.sh/install | sh");
  await expect(menu.getByTestId("session-agent-grok")).toHaveAttribute("title", "grok was not found on this computer · install: curl -fsSL https://x.ai/cli/install.sh | bash");
  for (const a of ["pi", "omp", "grok"]) {
    const tip = await menu.getByTestId(`session-agent-${a}`).getAttribute("title");
    expect(tip).not.toMatch(/mariozechner|see .* docs|npm i -g @oh-my-pi/);
  }
});

for (const theme of ["dark", "light"]) {
  test(`shot: the + menu with missing agents and their install lines (${theme})`, async ({ page }) => {
    test.skip(!SHOTS, "OMHER_SHOTS unset");
    await page.setViewportSize({ width: 1180, height: 760 });
    await open(page, theme);
    // A native tooltip is not drawn in a headless screenshot: draw each missing row's own `title` beside it.
    await page.evaluate(() => {
      const menu = document.querySelector("[data-testid=session-menu]")!;
      const box = menu.getBoundingClientRect();
      const dark = document.documentElement.dataset.theme !== "light" && !document.body.className.includes("light");
      for (const row of menu.querySelectorAll<HTMLElement>("[role=menuitem][aria-disabled=true]")) {
        const r = row.getBoundingClientRect();
        const tip = document.createElement("div");
        tip.textContent = row.getAttribute("title");
        Object.assign(tip.style, {
          position: "fixed", left: `${box.right + 10}px`, top: `${r.top + 4}px`, zIndex: "9999", font: "12px -apple-system, system-ui, sans-serif",
          padding: "3px 7px", borderRadius: "4px", whiteSpace: "nowrap",
          background: dark ? "#3a3a3c" : "#f4f4f4", color: dark ? "#eee" : "#222", border: `1px solid ${dark ? "#555" : "#ccc"}`,
        });
        document.body.appendChild(tip);
      }
    });
    await page.mouse.move(5, 700);
    await page.waitForTimeout(250);
    mkdirSync(SHOTS, { recursive: true });
    await page.screenshot({ path: join(SHOTS, `harness-detect-menu-${PHASE}-${theme}.png`), animations: "disabled" });
  });
}
