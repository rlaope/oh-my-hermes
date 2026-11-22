// The overlay that paints kitty Unicode placeholders (kitty-placeholders.ts) in one terminal: a canvas over the
// screen, like the image add-on's own layer, redrawn on every frame xterm renders while a virtual picture is kept.
// Only visible rows are scanned, and none while no virtual picture is kept. Each placeholder cell is first filled
// with the terminal's background (so the U+10EEEE glyph never shows as tofu), then its slice of the picture, at the
// screen's device pixels (sharp on a Retina display).
import type { IBufferCell, IDisposable, Terminal } from "@xterm/xterm";
import { PLACEHOLDER, PlaceholderStore, autoBox, decodeInPage, idFromColour, resolveRow, slice, type Decode } from "./kitty-placeholders";

export const LAYER_CLASS = "xterm-kitty-placeholder-layer";
const MARK = String.fromCodePoint(PLACEHOLDER);

export interface Placeholders {
  store: PlaceholderStore;
  dispose(): void;
}

/** Starts taking virtual placements in `term` and painting their placeholders. Register AFTER the image add-on, so
 *  this handler is asked first (xterm asks the newest first) and the add-on still gets every other Kitty command. */
export function attachPlaceholders(term: Terminal, decode: Decode = decodeInPage): Placeholders {
  let frame = 0;
  let canvas: HTMLCanvasElement | null = null;
  const schedule = () => {
    if (!frame) frame = requestAnimationFrame(draw);
  };
  const store = new PlaceholderStore(decode, schedule);
  const cell = (): IBufferCell | undefined => term.buffer.active.getNullCell();

  function layer(): CanvasRenderingContext2D | null {
    if (canvas?.isConnected) return canvas.getContext("2d");
    const screen = term.element?.querySelector(".xterm-screen") as HTMLElement | null;
    if (!screen) return null;
    canvas = document.createElement("canvas");
    canvas.className = LAYER_CLASS;
    // the add-on's top layer stacks the same way: above the text, below the selection (z-index 1)
    canvas.style.zIndex = "0";
    canvas.style.pointerEvents = "none";
    screen.style.isolation = "isolate";
    screen.appendChild(canvas);
    return canvas.getContext("2d");
  }

  function draw(): void {
    frame = 0;
    if (!store.images.size) {
      canvas?.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }
    const dims = term.dimensions;
    const ctx = layer();
    if (!dims || !ctx || !canvas) return;
    const cw = dims.css.cell.width;
    const ch = dims.css.cell.height;
    const dpr = window.devicePixelRatio || 1;
    const w = Math.round(dims.css.canvas.width * dpr);
    const h = Math.round(dims.css.canvas.height * dpr);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      canvas.style.width = `${dims.css.canvas.width}px`;
      canvas.style.height = `${dims.css.canvas.height}px`;
    }
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, w, h);
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
        ctx.fillStyle = bg;
        ctx.fillRect(x * cw, y * ch, cw, ch);
        const img = store.images.get(p.id);
        if (!img) continue;
        const [cols, rows] = autoBox(img, cw, ch);
        const s = slice(img.picture.width, img.picture.height, cols, rows, cw, ch, p.col, p.row);
        if (s) ctx.drawImage(img.picture, s.sx, s.sy, s.sw, s.sh, x * cw + s.dx, y * ch + s.dy, s.dw, s.dh);
      }
    }
  }

  const subs: IDisposable[] = [
    term.parser.registerApcHandler({ final: "G" }, (data) => store.handle(data)),
    term.onRender(() => store.images.size && schedule()),
    term.onResize(schedule),
  ];
  return {
    store,
    dispose() {
      for (const s of subs) s.dispose();
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      store.clear();
      canvas?.remove();
      canvas = null;
    },
  };
}
