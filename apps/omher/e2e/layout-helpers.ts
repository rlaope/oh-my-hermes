// Layout probes shared by the fit specs: a grid's rows end on its right edge (no card alone beside empty slots), a
// control's label stays on one line, and nothing is cut by an ellipsis.
import type { Locator } from "@playwright/test";

/** Each row of a grid's direct children, as the count of cards in it, plus the gap left at the row's right end (px). */
export async function gridRows(grid: Locator): Promise<{ n: number; gap: number }[]> {
  return grid.evaluate((g) => {
    const right = g.getBoundingClientRect().right;
    const rows = new Map<number, number[]>();
    for (const c of Array.from(g.children)) {
      const r = c.getBoundingClientRect();
      if (r.width === 0) continue;
      const top = Math.round(r.top);
      rows.set(top, [...(rows.get(top) ?? []), r.right]);
    }
    return [...rows.entries()].sort((a, b) => a[0] - b[0]).map(([, rights]) => ({ n: rights.length, gap: Math.round(right - Math.max(...rights)) }));
  });
}

/** Lines a text box takes: 1 when its label is on one line. */
export async function lineCount(el: Locator): Promise<number> {
  return el.evaluate((e) => {
    const range = document.createRange();
    range.selectNodeContents(e);
    return new Set(Array.from(range.getClientRects()).filter((r) => r.width > 1).map((r) => Math.round(r.top))).size;
  });
}

/** Visible elements under `root` whose text an ellipsis cuts, as "class: text". */
export async function cutText(root: Locator): Promise<string[]> {
  return root.evaluate((r) =>
    Array.from(r.querySelectorAll<HTMLElement>("*"))
      .filter((el) => {
        const cs = getComputedStyle(el);
        return cs.textOverflow === "ellipsis" && el.offsetWidth > 0 && el.scrollWidth > el.clientWidth + 1 && (el.textContent ?? "").trim() !== "";
      })
      .map((el) => `${el.className}: ${(el.textContent ?? "").trim().slice(0, 40)}`),
  );
}
