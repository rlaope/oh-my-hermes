// Another app keeping a CPU core busy (src/lib/cpu.ts, src-tauri/src/cpu.rs): the mock host's `__omherCpuHog` stands in
// for the shell's readings. A hog sends one note and shows the sidebar chip; it clears when the hog cools; Settings ›
// General's toggle off means no note and no chip. With OMHER_SHOTS=<dir> it writes cpu-chip-{dark,light}.png.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const SHOTS = process.env.OMHER_SHOTS || "";

async function open(page: Page, theme: "dark" | "light" = "dark") {
  await page.emulateMedia({ colorScheme: theme });
  await page.addInitScript(() => {
    const w = window as any;
    w.__notes = [];
    class FakeNotification {
      static permission = "granted";
      static requestPermission = async () => "granted";
      onclick: null | (() => void) = null;
      constructor(title: string, opts: { body?: string } = {}) {
        w.__notes.push({ title, body: opts.body });
      }
      close() {}
    }
    w.Notification = FakeNotification;
  });
  await page.goto("/");
  await expect(page.getByTestId("foot-row")).toBeVisible();
  await expect.poll(() => page.evaluate(() => typeof (window as any).__omherCpuHog)).toBe("function");
}

const notes = (page: Page) => page.evaluate(() => (window as any).__notes as { title: string; body: string }[]);
const hog = (page: Page, h: { name: string; pct: number; pid: number } | null) => page.evaluate((x) => (window as any).__omherCpuHog(x), h);

test("a CPU hog sends one note and shows the chip until it cools", async ({ page }) => {
  await open(page);
  await hog(page, { name: "Web", pct: 99, pid: 4242 });
  const chip = page.getByTestId("cpu-chip");
  await expect(chip).toBeVisible();
  await expect(chip).toContainText("Web · 99 % CPU");
  await expect.poll(() => notes(page)).toEqual([
    { title: "Web has kept a CPU core busy for over a minute · 99 %", body: "It may be stuck. Quit it in Activity Monitor or Task Manager if you do not need it." },
  ]);
  await hog(page, null);
  await expect(chip).toHaveCount(0);
  expect(await notes(page)).toHaveLength(1);
});

test("with the warning off in Settings there is no note and no chip", async ({ page }) => {
  await open(page);
  await hog(page, { name: "Web", pct: 99, pid: 4242 });
  await page.getByTestId("cpu-chip").click();
  const toggle = page.getByTestId("set-cpu-warn");
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(page.getByTestId("cpu-chip")).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("omher.cpuWarn"))).toBe("off");
  await expect.poll(() => page.evaluate(() => (window as any).__omherCpuWatch)).toEqual([true, false]);
  await page.evaluate(() => ((window as any).__notes = []));
  await hog(page, { name: "Other", pct: 97, pid: 4243 });
  await page.waitForTimeout(300);
  await expect(page.getByTestId("cpu-chip")).toHaveCount(0);
  expect(await notes(page)).toEqual([]);
});

for (const theme of ["dark", "light"] as const) {
  test(`cpu chip shot (${theme})`, async ({ page }) => {
    test.skip(!SHOTS, "OMHER_SHOTS unset");
    mkdirSync(SHOTS, { recursive: true });
    await open(page, theme);
    await hog(page, { name: "Google Chrome", pct: 98, pid: 4242 });
    await expect(page.getByTestId("cpu-chip")).toBeVisible();
    await page.screenshot({ path: join(SHOTS, `cpu-chip-${theme}.png`), animations: "disabled" });
    await page.getByTestId("cpu-chip").click();
    await page.getByTestId("set-cpu-warn").scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(SHOTS, `cpu-setting-${theme}.png`), animations: "disabled" });
  });
}
