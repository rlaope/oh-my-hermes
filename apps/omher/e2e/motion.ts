// The side panel opens, closes, maximises and restores by sliding (app.css: the .window grid's columns; under
// 1100px the panel's transform), and the chat header's right-hand controls and the panel's tabs move with it.
// Playwright's click waits for its target to hold still for two frames, which a loaded runner can give at the very
// start of a slide: the press then lands on the target and the release, once the slide moved it, on whatever slid
// in, so the browser clicks neither (seen: pointerdown on panel-button, pointerup on the panel's tab row).
import type { Page } from "@playwright/test";

/** No CSS transition is running, three frames in a row: whatever a slide moves is where it stays. */
export const motionDone = (page: Page) =>
  page.waitForFunction(
    (key) => {
      const w = window as unknown as Record<string, number>;
      const moving = document.getAnimations().some((a) => a instanceof CSSTransition);
      w[key] = moving ? 0 : (w[key] ?? 0) + 1;
      return w[key] >= 3;
    },
    `__still${Math.random().toString(36).slice(2)}`,
    { polling: "raf" },
  );
