// kitty-placeholders.ts: the U=1 transmit parser and store, the placeholder cell resolver and the slice geometry
// (the overlay is drawn on a page by e2e/term-kitty-placeholder.spec.ts).
import { describe, expect, it } from "vitest";
import { IMAGE_STORAGE_MB } from "./engine-image";
import { PlaceholderStore, ROWCOL_DIACRITICS, autoBox, diacriticIndex, idFromColour, resolveRow, slice, type Decode, type Picture } from "./kitty-placeholders";

const flush = () => new Promise((r) => setTimeout(r, 0));

/** A decoder that records what it was given and returns a picture of the size the test names. */
function fakeDecode(size: [number, number] = [16, 32]) {
  const calls: { bytes: Uint8Array; format: number; w: number; h: number }[] = [];
  const decode: Decode = async (bytes, format, w, h) => {
    calls.push({ bytes, format, w, h });
    return { width: size[0], height: size[1] } as unknown as Picture;
  };
  return { calls, decode };
}

const b64 = (s: string) => btoa(s);

describe("PlaceholderStore.handle", () => {
  it("takes Hermes' virtual transmit (a=T,U=1,…,f=100,q=2), chunked with m=1, and keeps it by id", async () => {
    const { calls, decode } = fakeDecode();
    let changed = 0;
    const s = new PlaceholderStore(decode, () => changed++);
    const data = b64("PNGBYTES-0123456789");
    // Hermes' _kitty_apc: the control on the first chunk only, then m=… alone
    expect(s.handle(`a=T,U=1,i=32769,c=2,r=2,f=100,q=2,m=1;${data.slice(0, 8)}`)).toBe(true);
    expect(s.handle(`m=1;${data.slice(8, 16)}`)).toBe(true);
    expect(s.handle(`m=0;${data.slice(16)}`)).toBe(true);
    await flush();
    expect(calls).toHaveLength(1);
    expect(new TextDecoder().decode(calls[0].bytes)).toBe("PNGBYTES-0123456789");
    expect(calls[0].format).toBe(100);
    expect(s.images.get(32769)).toMatchObject({ id: 32769, cols: 2, rows: 2, bytes: 16 * 32 * 4 });
    expect(s.usage).toBe(16 * 32 * 4);
    expect(changed).toBe(1);
  });

  it("takes raw RGB/RGBA with its size, and refuses raw pixels that do not fill it", async () => {
    const { calls, decode } = fakeDecode([2, 1]);
    const s = new PlaceholderStore(decode);
    expect(s.handle(`a=T,U=1,i=7,f=24,s=2,v=1;${b64("\xff\x00\x00\x00\xff\x00")}`)).toBe(true);
    expect(s.handle(`a=t,U=1,i=8,f=32,s=2,v=1;${b64("\xff\x00\x00")}`)).toBe(true);
    await flush();
    expect(calls.map((c) => [c.format, c.w, c.h])).toEqual([[24, 2, 1]]);
    expect([...s.images.keys()]).toEqual([7]);
  });

  it("refuses file, temp-file and shared-memory transfers, and other compressions, but still swallows them", async () => {
    const { calls, decode } = fakeDecode();
    const s = new PlaceholderStore(decode);
    for (const t of ["f", "t", "s"]) expect(s.handle(`a=T,U=1,i=5,t=${t},f=100;${b64("/etc/passwd")}`)).toBe(true);
    expect(s.handle(`a=T,U=1,i=5,f=100,o=x;${b64("x")}`)).toBe(true);
    expect(s.handle(`a=T,U=1,f=100;${b64("x")}`)).toBe(true); // no id: nothing could ever name it
    await flush();
    expect(calls).toHaveLength(0);
    expect(s.images.size).toBe(0);
  });

  it("leaves every non-virtual command to the image add-on", () => {
    const s = new PlaceholderStore(fakeDecode().decode);
    expect(s.handle(`a=T,i=1,f=100;${b64("x")}`)).toBe(false);
    expect(s.handle(`a=t,i=1,f=100,m=1;${b64("x")}`)).toBe(false);
    expect(s.handle(`m=0;${b64("x")}`)).toBe(false); // the add-on's continuation, not ours
    expect(s.handle("a=p,U=1,i=1")).toBe(false);
    expect(s.handle("a=q,i=1")).toBe(false);
    expect(s.handle("a=d,d=a")).toBe(false);
  });

  it("a=d drops its pictures (all, or one id) and still lets the add-on delete its own", async () => {
    const s = new PlaceholderStore(fakeDecode().decode);
    s.handle(`a=T,U=1,i=1,f=100;${b64("x")}`);
    s.handle(`a=T,U=1,i=2,f=100;${b64("x")}`);
    await flush();
    expect(s.handle("a=d,d=I,i=1")).toBe(false);
    expect([...s.images.keys()]).toEqual([2]);
    expect(s.handle("a=d")).toBe(false);
    expect(s.images.size).toBe(0);
    expect(s.usage).toBe(0);
  });

  it("drops the oldest past the 32 MB budget, refuses one larger than it, and replaces the same id in place", () => {
    const closed: number[] = [];
    const pic = (n: number) => ({ width: 1, height: 1, close: () => closed.push(n) }) as unknown as Picture;
    const s = new PlaceholderStore(fakeDecode().decode);
    expect(s.budget).toBe(IMAGE_STORAGE_MB * 1_000_000);
    const third = s.budget / 3;
    s.put({ id: 1, picture: pic(1), bytes: third, cols: 1, rows: 1 });
    s.put({ id: 2, picture: pic(2), bytes: third, cols: 1, rows: 1 });
    s.put({ id: 1, picture: pic(11), bytes: third, cols: 1, rows: 1 }); // replaces: 1 goes to the back of the line
    expect(closed).toEqual([1]);
    s.put({ id: 3, picture: pic(3), bytes: third, cols: 1, rows: 1 });
    expect([...s.images.keys()]).toEqual([2, 1, 3]);
    s.put({ id: 4, picture: pic(4), bytes: third, cols: 1, rows: 1 }); // over: the oldest (2) goes
    expect([...s.images.keys()]).toEqual([1, 3, 4]);
    expect(closed).toEqual([1, 2]);
    s.put({ id: 5, picture: pic(5), bytes: s.budget + 1, cols: 1, rows: 1 });
    expect(s.images.has(5)).toBe(false);
    expect(s.usage).toBeLessThanOrEqual(s.budget);
  });
});

describe("placeholder cells", () => {
  const P = String.fromCodePoint(0x10eeee);
  const d = (i: number) => String.fromCodePoint(ROWCOL_DIACRITICS[i]);

  it("the mark table is kitty's (297 marks, first U+0305, last U+1D244) and maps back to its index", () => {
    expect(ROWCOL_DIACRITICS).toHaveLength(297);
    expect(ROWCOL_DIACRITICS[0]).toBe(0x305);
    expect(ROWCOL_DIACRITICS[296]).toBe(0x1d244);
    expect(diacriticIndex(0x30d)).toBe(1);
    expect(diacriticIndex(0x41)).toBe(-1);
  });

  it("the image id is the foreground colour (24-bit, or a 256-colour index); default colour names none", () => {
    expect(idFromColour("rgb", 0x008001)).toBe(32769);
    expect(idFromColour("palette", 42)).toBe(42);
    expect(idFromColour("default", 0)).toBeNull();
  });

  it("Hermes' rows (row mark on the first cell, bare cells after) auto-increment the column", () => {
    const id = 0x8001;
    // kitty_placeholder_rows(3, 2): P+row0 P P / P+row1 P P
    expect(resolveRow([{ id, chars: P + d(0) }, { id, chars: P }, { id, chars: P }])).toEqual([
      { id, row: 0, col: 0 },
      { id, row: 0, col: 1 },
      { id, row: 0, col: 2 },
    ]);
    expect(resolveRow([{ id, chars: P + d(1) }, { id, chars: P }, null, { id, chars: P + d(1) + d(5) }])).toEqual([
      { id, row: 1, col: 0 },
      { id, row: 1, col: 1 },
      null,
      { id, row: 1, col: 5 },
    ]);
  });

  it("a different id starts a new run, and a third mark is the id's high byte", () => {
    expect(resolveRow([{ id: 1, chars: P + d(2) }, { id: 2, chars: P }])).toEqual([
      { id: 1, row: 2, col: 0 },
      { id: 2, row: 0, col: 0 },
    ]);
    expect(resolveRow([{ id: 0x10, chars: P + d(0) + d(0) + d(3) }])).toEqual([{ id: 0x03000010, row: 0, col: 0 }]);
  });

  it("each cell gets its slice of the picture fit into the c×r box, aspect kept and centred", () => {
    // a 16×32 picture in a 2×2 box of 8×16 cells: it fills exactly, cell (1,1) shows the bottom-right quarter
    expect(slice(16, 32, 2, 2, 8, 16, 1, 1)).toEqual({ sx: 8, sy: 16, sw: 8, sh: 16, dx: 0, dy: 0, dw: 8, dh: 16 });
    // a wide 32×8 picture in a 2×2 box of 8×16 cells: scaled to 16 wide (×0.5), 4 tall, centred at y 14..18
    expect(slice(32, 8, 2, 2, 8, 16, 0, 0)).toEqual({ sx: 0, sy: 0, sw: 16, sh: 4, dx: 0, dy: 14, dw: 8, dh: 2 });
    expect(slice(32, 8, 2, 2, 8, 16, 0, 1)).toEqual({ sx: 0, sy: 4, sw: 16, sh: 4, dx: 0, dy: 0, dw: 8, dh: 2 });
    // a cell outside the box's picture area: nothing
    expect(slice(8, 8, 1, 3, 8, 8, 0, 0)).toBeNull();
    expect(slice(16, 32, 2, 2, 8, 16, 3, 0)).toBeNull();
  });

  it("with no c/r the box is the picture's own size in cells", () => {
    const img = { id: 1, picture: { width: 17, height: 32 } as unknown as Picture, bytes: 0, cols: 0, rows: 0 };
    expect(autoBox(img, 8, 16)).toEqual([3, 2]);
    expect(autoBox({ ...img, cols: 4, rows: 1 }, 8, 16)).toEqual([4, 1]);
  });
});
