// Kitty Unicode placeholders (virtual placements): a program transmits a picture once with `a=T,U=1,i=<id>` and then
// prints rows of U+10EEEE whose foreground colour is the image id and whose combining marks are the row and column;
// the terminal paints the matching slice of the picture over each such cell. xterm's image add-on draws Kitty
// pictures placed at the cursor but not these, so omher's terminals took them as text (and the OMH TUI and Hermes
// fell back to half-block mosaics). https://sw.kovidgoyal.net/kitty/graphics-protocol/#unicode-placeholders
//
// The APC `G` handler here takes ONLY transmissions with U=1 (and their `m=1` continuation chunks); every other
// Kitty command falls through to the add-on (registered before this one, so this one runs first). Like the add-on it
// refuses file, temp-file and shared-memory transfers (`t=f/t/s`): only bytes the program prints are drawn. Kept:
// the decoded pictures, in this terminal's memory, within the same 32 MB budget per terminal (the oldest go first);
// nothing is written to disk or sent anywhere, and nothing is replied to the program.
import { IMAGE_SEQUENCE_BYTES, IMAGE_STORAGE_MB } from "./engine-image";

/** The placeholder character. */
export const PLACEHOLDER = 0x10eeee;
/** Row/column/id-byte marks by index, verbatim from kitty's gen/rowcolumn-diacritics.txt (Hermes' table). */
export const ROWCOL_DIACRITICS: readonly number[] = [
  0x305, 0x30d, 0x30e, 0x310, 0x312, 0x33d, 0x33e, 0x33f, 0x346, 0x34a, 0x34b, 0x34c, 0x350, 0x351, 0x352, 0x357,
  0x35b, 0x363, 0x364, 0x365, 0x366, 0x367, 0x368, 0x369, 0x36a, 0x36b, 0x36c, 0x36d, 0x36e, 0x36f, 0x483, 0x484,
  0x485, 0x486, 0x487, 0x592, 0x593, 0x594, 0x595, 0x597, 0x598, 0x599, 0x59c, 0x59d, 0x59e, 0x59f, 0x5a0, 0x5a1,
  0x5a8, 0x5a9, 0x5ab, 0x5ac, 0x5af, 0x5c4, 0x610, 0x611, 0x612, 0x613, 0x614, 0x615, 0x616, 0x617, 0x657, 0x658,
  0x659, 0x65a, 0x65b, 0x65d, 0x65e, 0x6d6, 0x6d7, 0x6d8, 0x6d9, 0x6da, 0x6db, 0x6dc, 0x6df, 0x6e0, 0x6e1, 0x6e2,
  0x6e4, 0x6e7, 0x6e8, 0x6eb, 0x6ec, 0x730, 0x732, 0x733, 0x735, 0x736, 0x73a, 0x73d, 0x73f, 0x740, 0x741, 0x743,
  0x745, 0x747, 0x749, 0x74a, 0x7eb, 0x7ec, 0x7ed, 0x7ee, 0x7ef, 0x7f0, 0x7f1, 0x7f3, 0x816, 0x817, 0x818, 0x819,
  0x81b, 0x81c, 0x81d, 0x81e, 0x81f, 0x820, 0x821, 0x822, 0x823, 0x825, 0x826, 0x827, 0x829, 0x82a, 0x82b, 0x82c,
  0x82d, 0x951, 0x953, 0x954, 0xf82, 0xf83, 0xf86, 0xf87, 0x135d, 0x135e, 0x135f, 0x17dd, 0x193a, 0x1a17, 0x1a75, 0x1a76,
  0x1a77, 0x1a78, 0x1a79, 0x1a7a, 0x1a7b, 0x1a7c, 0x1b6b, 0x1b6d, 0x1b6e, 0x1b6f, 0x1b70, 0x1b71, 0x1b72, 0x1b73, 0x1cd0, 0x1cd1,
  0x1cd2, 0x1cda, 0x1cdb, 0x1ce0, 0x1dc0, 0x1dc1, 0x1dc3, 0x1dc4, 0x1dc5, 0x1dc6, 0x1dc7, 0x1dc8, 0x1dc9, 0x1dcb, 0x1dcc, 0x1dd1,
  0x1dd2, 0x1dd3, 0x1dd4, 0x1dd5, 0x1dd6, 0x1dd7, 0x1dd8, 0x1dd9, 0x1dda, 0x1ddb, 0x1ddc, 0x1ddd, 0x1dde, 0x1ddf, 0x1de0, 0x1de1,
  0x1de2, 0x1de3, 0x1de4, 0x1de5, 0x1de6, 0x1dfe, 0x20d0, 0x20d1, 0x20d4, 0x20d5, 0x20d6, 0x20d7, 0x20db, 0x20dc, 0x20e1, 0x20e7,
  0x20e9, 0x20f0, 0x2cef, 0x2cf0, 0x2cf1, 0x2de0, 0x2de1, 0x2de2, 0x2de3, 0x2de4, 0x2de5, 0x2de6, 0x2de7, 0x2de8, 0x2de9, 0x2dea,
  0x2deb, 0x2dec, 0x2ded, 0x2dee, 0x2def, 0x2df0, 0x2df1, 0x2df2, 0x2df3, 0x2df4, 0x2df5, 0x2df6, 0x2df7, 0x2df8, 0x2df9, 0x2dfa,
  0x2dfb, 0x2dfc, 0x2dfd, 0x2dfe, 0x2dff, 0xa66f, 0xa67c, 0xa67d, 0xa6f0, 0xa6f1, 0xa8e0, 0xa8e1, 0xa8e2, 0xa8e3, 0xa8e4, 0xa8e5,
  0xa8e6, 0xa8e7, 0xa8e8, 0xa8e9, 0xa8ea, 0xa8eb, 0xa8ec, 0xa8ed, 0xa8ee, 0xa8ef, 0xa8f0, 0xa8f1, 0xaab0, 0xaab2, 0xaab3, 0xaab7,
  0xaab8, 0xaabe, 0xaabf, 0xaac1, 0xfe20, 0xfe21, 0xfe22, 0xfe23, 0xfe24, 0xfe25, 0xfe26, 0x10a0f, 0x10a38, 0x1d185, 0x1d186, 0x1d187,
  0x1d188, 0x1d189, 0x1d1aa, 0x1d1ab, 0x1d1ac, 0x1d1ad, 0x1d242, 0x1d243, 0x1d244,
];
const DIACRITIC_INDEX = new Map(ROWCOL_DIACRITICS.map((cp, i) => [cp, i]));

/** The index a combining mark stands for, or -1 when it is not one of kitty's. */
export const diacriticIndex = (cp: number): number => DIACRITIC_INDEX.get(cp) ?? -1;

/** A decoded picture: anything canvas `drawImage` takes. */
export type Picture = CanvasImageSource & { width: number; height: number; close?(): void };
/** Bytes to picture: PNG (`f=100`) or raw RGB/RGBA (`f=24/32`, width and height given). */
export type Decode = (bytes: Uint8Array, format: 24 | 32 | 100, width: number, height: number) => Promise<Picture>;

/** One stored virtual image. `cols`/`rows` 0 means "from the picture's size" (kitty's default box). */
export interface VirtualImage {
  id: number;
  picture: Picture;
  bytes: number;
  cols: number;
  rows: number;
}

/** Kitty's `k=v,k=v` control keys. */
export function parseControl(s: string): Map<string, string> {
  const m = new Map<string, string>();
  for (const kv of s.split(",")) {
    const i = kv.indexOf("=");
    if (i > 0) m.set(kv.slice(0, i), kv.slice(i + 1));
  }
  return m;
}

const num = (m: Map<string, string>, k: string): number => {
  const v = Number(m.get(k) ?? 0);
  return Number.isFinite(v) && v > 0 ? Math.floor(v) : 0;
};

function b64(s: string): Uint8Array | null {
  try {
    const bin = atob(s.replace(/[^A-Za-z0-9+/=]/g, ""));
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  } catch {
    return null;
  }
}

async function inflate(bytes: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([bytes as BlobPart]).stream().pipeThrough(new DecompressionStream("deflate"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** The browser's decoder: PNG through `createImageBitmap`, raw pixels through ImageData. */
export const decodeInPage: Decode = async (bytes, format, width, height) => {
  if (format === 100) return createImageBitmap(new Blob([bytes as BlobPart], { type: "image/png" }));
  const rgba = new Uint8ClampedArray(width * height * 4);
  const step = format === 32 ? 4 : 3;
  for (let p = 0, q = 0; p < width * height; p++, q += step) {
    rgba[p * 4] = bytes[q];
    rgba[p * 4 + 1] = bytes[q + 1];
    rgba[p * 4 + 2] = bytes[q + 2];
    rgba[p * 4 + 3] = step === 4 ? bytes[q + 3] : 255;
  }
  return createImageBitmap(new ImageData(rgba, width, height));
};

interface Upload {
  ctrl: Map<string, string>;
  data: string[];
  size: number;
  refused: boolean;
}

/** One terminal's virtual images and the APC `G` handler that fills them. */
export class PlaceholderStore {
  readonly images = new Map<number, VirtualImage>();
  private upload: Upload | null = null;
  private used = 0;

  constructor(
    private readonly decode: Decode,
    private readonly changed: () => void = () => undefined,
    readonly budget = IMAGE_STORAGE_MB * 1_000_000,
  ) {}

  /** Bytes the decoded pictures take now (4 a pixel). */
  get usage(): number {
    return this.used;
  }

  /** One APC `G` payload (without the `G`). True when it was a virtual-placement transmit (or its continuation). */
  handle(payload: string): boolean {
    const semi = payload.indexOf(";");
    const ctrl = parseControl(semi < 0 ? payload : payload.slice(0, semi));
    const data = semi < 0 ? "" : payload.slice(semi + 1);
    const more = ctrl.get("m") === "1";
    if (this.upload) {
      // a continuation chunk carries only m (and q); anything else is a new command, which ends ours
      if ([...ctrl.keys()].every((k) => k === "m" || k === "q")) {
        this.chunk(data, more);
        return true;
      }
      this.upload = null;
    }
    const a = ctrl.get("a") ?? "t";
    if (a === "d") {
      this.forget(ctrl);
      return false; // the add-on deletes its own as well
    }
    if (ctrl.get("U") !== "1" || (a !== "T" && a !== "t")) return false;
    const t = ctrl.get("t") ?? "d";
    const f = Number(ctrl.get("f") ?? 32);
    const refused = t !== "d" || !num(ctrl, "i") || (f !== 100 && f !== 24 && f !== 32) || (ctrl.has("o") && ctrl.get("o") !== "z");
    this.upload = { ctrl, data: [], size: 0, refused };
    this.chunk(data, more);
    return true;
  }

  private chunk(data: string, more: boolean): void {
    const u = this.upload!;
    if (!u.refused) {
      u.size += data.length;
      if ((u.size * 3) / 4 > IMAGE_SEQUENCE_BYTES) u.refused = true;
      else u.data.push(data);
    }
    if (more) return;
    this.upload = null;
    if (!u.refused) void this.finish(u.ctrl, u.data.join(""));
  }

  private async finish(ctrl: Map<string, string>, data: string): Promise<void> {
    const id = num(ctrl, "i");
    const f = Number(ctrl.get("f") ?? 32) as 24 | 32 | 100;
    let bytes = b64(data);
    if (!bytes) return;
    try {
      if (ctrl.get("o") === "z") bytes = await inflate(bytes);
      const w = num(ctrl, "s");
      const h = num(ctrl, "v");
      if (f !== 100 && (!w || !h || bytes.length < w * h * (f / 8))) return;
      const picture = await this.decode(bytes, f, w, h);
      this.put({ id, picture, bytes: picture.width * picture.height * 4, cols: num(ctrl, "c"), rows: num(ctrl, "r") });
    } catch {
      /* not a picture: nothing drawn */
    }
  }

  /** Keeps `img` (replacing the same id), dropping the oldest past the budget; one larger than it is refused. */
  put(img: VirtualImage): void {
    if (img.bytes > this.budget) {
      img.picture.close?.();
      return;
    }
    this.drop(img.id);
    this.images.set(img.id, img);
    this.used += img.bytes;
    for (const old of this.images.values()) {
      if (this.used <= this.budget) break;
      this.drop(old.id);
    }
    this.changed();
  }

  private drop(id: number): void {
    const old = this.images.get(id);
    if (!old) return;
    this.images.delete(id);
    this.used -= old.bytes;
    old.picture.close?.();
  }

  /** `a=d`: all (`d=a/A`, or none given) or one id (`d=i/I`). */
  private forget(ctrl: Map<string, string>): void {
    const d = (ctrl.get("d") ?? "a").toLowerCase();
    if (d === "a") for (const id of [...this.images.keys()]) this.drop(id);
    else if (d === "i") this.drop(num(ctrl, "i"));
    else return;
    this.changed();
  }

  /** Drops every picture (the terminal closes, or Show images goes off). */
  clear(): void {
    for (const id of [...this.images.keys()]) this.drop(id);
    this.upload = null;
  }
}

/** The image id a placeholder cell's foreground names: 24-bit colour, or a 256-colour index; null for default. */
export function idFromColour(mode: "rgb" | "palette" | "default", value: number): number | null {
  if (mode === "rgb") return value & 0xffffff;
  if (mode === "palette") return value & 0xff;
  return null;
}

/** One placeholder cell as printed: its id (with the optional third mark as the high byte), row and column marks. */
export interface Cell {
  id: number;
  row: number;
  col: number;
}

/** The marks after a U+10EEEE in a cell's text: row, column, id high byte (-1 when absent). */
export function marks(chars: string): [number, number, number] {
  const cps = [...chars].map((c) => c.codePointAt(0)!);
  const at = (i: number) => (cps[i] === undefined ? -1 : diacriticIndex(cps[i]));
  return [at(1), at(2), at(3)];
}

/** A row of placeholder cells resolved as kitty does: a missing row or column continues the cell to the left (same
 *  id and row, next column); the first cell of a run without marks is row 0, column 0. `null` for other cells. */
export function resolveRow(cells: ({ id: number; chars: string } | null)[]): (Cell | null)[] {
  const out: (Cell | null)[] = [];
  let prev: Cell | null = null;
  for (const c of cells) {
    if (!c) {
      out.push((prev = null));
      continue;
    }
    const [r, col, hi] = marks(c.chars);
    const id = hi >= 0 ? (c.id & 0xffffff) | (hi << 24) : c.id;
    const p: Cell | null = prev;
    const continues: boolean = !!p && p.id === id >>> 0 && (r < 0 || r === p.row);
    const row: number = r >= 0 ? r : continues ? p!.row : 0;
    const cc: number = col >= 0 ? col : continues ? p!.col + 1 : 0;
    prev = { id: id >>> 0, row, col: cc };
    out.push(prev);
  }
  return out;
}

/** Where one cell's slice of a picture goes: the picture is fit into the cols×rows box keeping its aspect and centred
 *  (as kitty does); returns the source and destination rectangles (destination relative to the cell), or null when
 *  that cell is outside the picture. */
export function slice(
  w: number,
  h: number,
  cols: number,
  rows: number,
  cw: number,
  ch: number,
  col: number,
  row: number,
): { sx: number; sy: number; sw: number; sh: number; dx: number; dy: number; dw: number; dh: number } | null {
  const bw = cols * cw;
  const bh = rows * ch;
  const s = Math.min(bw / w, bh / h);
  const ox = (bw - w * s) / 2;
  const oy = (bh - h * s) / 2;
  const x0 = Math.max(col * cw, ox);
  const y0 = Math.max(row * ch, oy);
  const x1 = Math.min((col + 1) * cw, ox + w * s);
  const y1 = Math.min((row + 1) * ch, oy + h * s);
  if (x1 <= x0 || y1 <= y0) return null;
  return { sx: (x0 - ox) / s, sy: (y0 - oy) / s, sw: (x1 - x0) / s, sh: (y1 - y0) / s, dx: x0 - col * cw, dy: y0 - row * ch, dw: x1 - x0, dh: y1 - y0 };
}

/** The box a picture takes when the program gave no c/r: its size in cells, rounded up. */
export const autoBox = (img: VirtualImage, cw: number, ch: number): [number, number] => [
  img.cols || Math.max(1, Math.ceil(img.picture.width / cw)),
  img.rows || Math.max(1, Math.ceil(img.picture.height / ch)),
];
