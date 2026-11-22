// The overlay that paints kitty Unicode placeholders (kitty-placeholders.ts) in one terminal: ONE canvas over the
// screen for the terminal's life, like the image add-on's own layer. It is drawn in the same frame xterm renders
// (inside `onRender`, so a buffer switch is right on its first frame), and on the next frame after a picture arrives
// or the terminal is resized. Each placeholder cell is first filled with the terminal's background (so the U+10EEEE
// glyph never shows as tofu, also when its picture is gone: evicted, deleted, or a terminal made again from a
// snapshot), then its slice of the picture, at the screen's device pixels (sharp on a Retina display).
//
// Cost: nothing is scanned until this terminal took a virtual placement (or showed placeholders when its pictures
// were turned on, or before it was parked); after that, the visible rows on each frame xterm renders.
//
// Stacking: z-index 0 like the add-on's top layer (above the text, below the selection). A renderer canvas added
// later in the same stacking level (the GPU renderer, attached after a picture shows or again when the terminal is
// shown) would cover it, so the canvas moves back to the end of the screen whenever one is added after it.
// While the terminal is off the page (its element detached) nothing is drawn; it is painted once when it is back.
import type { IBufferCell, IDisposable, Terminal } from "@xterm/xterm";
import { PLACEHOLDER, PlaceholderStore, autoBox, decodeInPage, idFromColour, resolveRow, slice, type AddonView, type Decode } from "./kitty-placeholders";

export const LAYER_CLASS = "xterm-kitty-placeholder-layer";
const MARK = String.fromCodePoint(PLACEHOLDER);

export interface Placeholders {
  store: PlaceholderStore;
  /** a placeholder (or a virtual placement) was in this terminal: a terminal made again from it keeps blanking them */
  readonly seen: boolean;
  /** what goes with it (engine-image adds the add-on's eviction listener here) */
  subs: IDisposable[];
  dispose(): void;
}

/** Starts taking virtual placements in `term` and painting their placeholders. Register AFTER the image add-on, so
 *  this handler is asked first (xterm asks the newest first) and the add-on still gets every other Kitty command. */
export function attachPlaceholders(term: Terminal, decode: Decode = decodeInPage, addon?: AddonView, wasSeen = false): Placeholders {
  let frame = 0;
  let canvas: HTMLCanvasElement | null = null;
  let painted = false; // the canvas holds something
  let seen = wasSeen; // a placeholder (or a virtual placement) was ever in this terminal
  let owed = false; // a draw was skipped while the terminal was off the page
  let gone = false;
  let watch: MutationObserver | null = null;
  let shown: IntersectionObserver | null = null;
  const schedule = () => {
    if (!frame && !gone) frame = requestAnimationFrame(draw);
  };
  const store = new PlaceholderStore(
    decode,
    () => {
      seen = true;
      schedule();
    },
    undefined,
    addon,
  );
  const cell = (): IBufferCell | undefined => term.buffer.active.getNullCell();
  const screen = (): HTMLElement | null => (term.element?.querySelector(".xterm-screen") as HTMLElement | null) ?? null;

  /** Keeps the canvas the last canvas of the screen: one added after it (a renderer's) moves it back on top. */
  function onTop(): void {
    if (!canvas?.parentElement) return;
    for (let n = canvas.nextElementSibling; n; n = n.nextElementSibling) {
      if (n.tagName === "CANVAS") {
        canvas.parentElement.appendChild(canvas);
        schedule();
        return;
      }
    }
  }

  /** The one canvas, made the first time it is needed and put back in the screen if something took it out. */
  function layer(): HTMLCanvasElement | null {
    const sc = screen();
    if (!sc) return null;
    if (!canvas) {
      canvas = document.createElement("canvas");
      canvas.className = LAYER_CLASS;
      // the add-on's top layer stacks the same way: above the text, below the selection (z-index 1)
      canvas.style.zIndex = "0";
      canvas.style.pointerEvents = "none";
      sc.style.isolation = "isolate";
      if (typeof MutationObserver !== "undefined") {
        watch = new MutationObserver(onTop);
        watch.observe(sc, { childList: true });
      }
      if (typeof IntersectionObserver !== "undefined") {
        shown = new IntersectionObserver((entries) => {
          if (owed && entries.some((e) => e.isIntersecting)) draw();
        });
        shown.observe(sc);
      }
    }
    if (canvas.parentElement !== sc) sc.appendChild(canvas);
    else onTop();
    return canvas;
  }

  /** Whether one of rows `start`..`end` of the screen holds a placeholder. */
  function marked(start: number, end: number): boolean {
    const buf = term.buffer.active;
    for (let y = Math.max(0, start); y <= Math.min(end, term.rows - 1); y++) {
      if (buf.getLine(buf.viewportY + y)?.translateToString(false).includes(MARK)) return true;
    }
    return false;
  }

  function clear(): void {
    if (painted && canvas) canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    painted = false;
  }

  function draw(): void {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    if (gone) return;
    if (store.images.size) seen = true;
    if (!seen) return clear();
    const dims = term.dimensions;
    const cv = layer();
    if (!dims || !cv) return;
    if (!cv.isConnected) {
      owed = true; // off the page: nothing to draw now, once when it is back
      return;
    }
    owed = false;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const cw = dims.css.cell.width;
    const ch = dims.css.cell.height;
    const dpr = window.devicePixelRatio || 1;
    const w = Math.round(dims.css.canvas.width * dpr);
    const h = Math.round(dims.css.canvas.height * dpr);
    if (cv.width !== w || cv.height !== h) {
      cv.width = w;
      cv.height = h;
      cv.style.width = `${dims.css.canvas.width}px`;
      cv.style.height = `${dims.css.canvas.height}px`;
    }
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, w, h);
    painted = false;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    const bg = term.options.theme?.background ?? "#000000";
    const buf = term.buffer.active;
    const c = cell();
    for (let y = 0; y < term.rows; y++) {
      const line = buf.getLine(buf.viewportY + y);
      if (!line || !line.translateToString(false).includes(MARK)) continue;
      const cells = [];
      for (let x = 0; x < term.cols; x++) {
        const k = line.getCell(x, c);
        const chars = k?.getChars() ?? "";
        const id = k && chars.codePointAt(0) === PLACEHOLDER ? idFromColour(k.isFgRGB() ? "rgb" : k.isFgPalette() ? "palette" : "default", k.getFgColor()) : null;
        cells.push(id === null ? null : { id, chars });
      }
      const row = resolveRow(cells);
      for (let x = 0; x < row.length; x++) {
        const p = row[x];
        if (!p) continue;
        // the cell's own glyph never shows: blank background first, also when its picture is gone
        ctx.fillStyle = bg;
        ctx.fillRect(x * cw, y * ch, cw, ch);
        painted = true;
        const img = store.images.get(p.id);
        if (!img) continue;
        const [cols, rows] = autoBox(img, cw, ch);
        const s = slice(img.picture.width, img.picture.height, cols, rows, cw, ch, p.col, p.row);
        if (s) ctx.drawImage(img.picture, s.sx, s.sy, s.sw, s.sh, x * cw + s.dx, y * ch + s.dy, s.dw, s.dh);
      }
    }
  }

  const subs: IDisposable[] = [
    term.parser.registerApcHandler({ final: "G" }, (data) => {
      const mine = store.handle(data);
      if (mine) seen = true; // also one refused: its placeholder cells still must not show the glyph
      return mine;
    }),
    // in the frame xterm just drew, so the overlay never shows the previous screen
    term.onRender(() => {
      if (seen) draw();
    }),
    term.onResize(schedule),
  ];
  // a terminal made again from a snapshot (or pictures turned on over a screen) may already show placeholders whose
  // pictures are gone: they are blanked from the start
  if (seen || marked(0, term.rows - 1)) {
    seen = true;
    schedule();
  }
  return {
    store,
    subs,
    get seen() {
      return seen;
    },
    dispose() {
      gone = true;
      for (const s of subs) s.dispose();
      subs.length = 0;
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      watch?.disconnect();
      shown?.disconnect();
      store.dispose();
      canvas?.remove();
      canvas = null;
    },
  };
}
