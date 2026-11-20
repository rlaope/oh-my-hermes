// Little disk space on the home folder's volume (src/lib/disk.ts, src-tauri/src/disk.rs): the mock host reads
// `__omherDiskFree` bytes with the shell's rules. A low disk shows the sidebar chip and sends one note; the chip opens
// Settings › General, whose "Off" hides it. With OMHER_SHOTS=<dir> it writes disk-chip-{dark,light}.png.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const SHOTS = process.env.OMHER_SHOTS || "";

async function open(page: Page, free: number, theme: "dark" | "light" = "dark") {
  await page.emulateMedia({ colorScheme: theme });
  await page.addInitScript((f) => {
    const w = window as any;
    w.__omherDiskFree = f;
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
  }, free);
  await page.goto("/");
  await expect(page.getByTestId("foot-row")).toBeVisible();
}

const notes = (page: Page) => page.evaluate(() => (window as any).__notes as { title: string; body: string }[]);

test("a low disk shows the footer chip and sends one note; the chip opens Settings, Off hides it", async ({ page }) => {
  await open(page, 4.5e9);
  const chip = page.getByTestId("disk-chip");
  await expect(chip).toBeVisible();
  await expect(chip).toHaveAttribute("data-level", "critical");
  await expect(chip).toContainText("4.5 GB free");
  await expect.poll(() => notes(page)).toEqual([
    { title: "Disk space critically low: 4.5 GB left", body: "Free space on / before builds and agents start failing." },
  ]);
  await chip.click();
  const seg = page.getByTestId("set-disk-warn");
  await expect(seg).toBeVisible();
  await expect(seg.getByRole("radio")).toHaveText(["5 GB", "10 GB", "20 GB", "50 GB", "Off"]);
  await expect(seg.getByRole("radio", { name: "20 GB" })).toHaveAttribute("aria-checked", "true");
  await seg.getByRole("radio", { name: "Off" }).click();
  await expect(chip).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("omher.diskWarn"))).toBe("off");
  expect(await notes(page)).toHaveLength(1);
});

test("a disk with room shows no chip and no note", async ({ page }) => {
  await open(page, 80e9);
  await page.waitForTimeout(300);
  await expect(page.getByTestId("disk-chip")).toHaveCount(0);
  expect(await notes(page)).toEqual([]);
});

for (const theme of ["dark", "light"] as const) {
  test(`disk chip shot (${theme})`, async ({ page }) => {
    test.skip(!SHOTS, "OMHER_SHOTS unset");
    mkdirSync(SHOTS, { recursive: true });
    await open(page, 3.2e9, theme);
    await expect(page.getByTestId("disk-chip")).toHaveAttribute("data-level", "critical");
    await page.screenshot({ path: join(SHOTS, `disk-chip-critical-${theme}.png`), animations: "disabled" });
    await open(page, 12.4e9, theme);
    await expect(page.getByTestId("disk-chip")).toHaveAttribute("data-level", "low");
    await page.screenshot({ path: join(SHOTS, `disk-chip-${theme}.png`), animations: "disabled" });
    await page.getByTestId("disk-chip").click();
    await expect(page.getByTestId("set-disk-warn")).toBeVisible();
    await page.getByTestId("set-disk-warn").scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(SHOTS, `disk-setting-${theme}.png`), animations: "disabled" });
  });
}
