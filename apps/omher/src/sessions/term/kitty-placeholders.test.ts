// kitty-placeholders.ts: the U=1 transmit parser and store, the placeholder cell resolver and the slice geometry
// (the overlay is drawn on a page by e2e/term-kitty-placeholder.spec.ts).
import { describe, expect, it } from "vitest";
import { IMAGE_SEQUENCE_BYTES, IMAGE_STORAGE_MB, PIXEL_LIMIT } from "./engine-image";
import { PlaceholderStore, ROWCOL_DIACRITICS, autoBox, diacriticIndex, idFromColour, inflate, pngSize, resolveRow, slice, type Decode, type Picture } from "./kitty-placeholders";

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
const bytesB64 = (b: Uint8Array) => btoa(String.fromCharCode(...b));

/** The first bytes of a PNG of `w`×`h` (signature and IHDR): all the store reads before it decodes. */
function pngHead(w: number, h: number, tail = "PNGBYTES-0123456789"): Uint8Array {
  const b = new Uint8Array(33 + tail.length);
  b.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52]);
  const v = new DataView(b.buffer);
  v.setUint32(16, w);
  v.setUint32(20, h);
  for (let i = 0; i < tail.length; i++) b[33 + i] = tail.charCodeAt(i);
  return b;
}
const png = (w = 16, h = 32) => bytesB64(pngHead(w, h));

/** A decoder whose pictures arrive when the test says, each counting its `close`. */
function deferredDecode() {
  const waiting: ((p: Picture) => void)[] = [];
  let closed = 0;
  let calls = 0;
  const decode: Decode = () => {
    calls++;
    return new Promise<Picture>((r) => waiting.push(r));
  };
  const picture = (w = 1, h = 1) => ({ width: w, height: h, close: () => void closed++ }) as unknown as Picture;
  return { decode, waiting, picture, closed: () => closed, calls: () => calls };
}

async function deflate(bytes: Uint8Array): Promise<Uint8Array> {
  const s = new Blob([bytes as BlobPart]).stream().pipeThrough(new CompressionStream("deflate"));
  return new Uint8Array(await new Response(s).arrayBuffer());
}

describe("PlaceholderStore.handle", () => {
  it("takes Hermes' virtual transmit (a=T,U=1,…,f=100,q=2), chunked with m=1, and keeps it by id", async () => {
    const { calls, decode } = fakeDecode();
    let changed = 0;
    const s = new PlaceholderStore(decode, () => changed++);
    const data = png();
    // Hermes' _kitty_apc: the control on the first chunk only, then m=… alone
    expect(s.handle(`a=T,U=1,i=32769,c=2,r=2,f=100,q=2,m=1;${data.slice(0, 8)}`)).toBe(true);
    expect(s.handle(`m=1;${data.slice(8, 16)}`)).toBe(true);
    expect(s.handle(`m=0;${data.slice(16)}`)).toBe(true);
    await flush();
    expect(calls).toHaveLength(1);
    expect(calls[0].bytes).toEqual(pngHead(16, 32));
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
    s.handle(`a=T,U=1,i=1,f=100;${png()}`);
    s.handle(`a=T,U=1,i=2,f=100;${png()}`);
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

describe("PlaceholderStore lifecycle: a decode still on its way when the store changes", () => {
  it("dispose (the terminal closes) while decoding: the late picture is closed, nothing is kept or redrawn", async () => {
    const d = deferredDecode();
    let changed = 0;
    const s = new PlaceholderStore(d.decode, () => changed++);
    s.handle(`a=T,U=1,i=7,f=100,q=2;${png()}`);
    await flush();
    expect(d.calls()).toBe(1);
    s.dispose();
    d.waiting[0](d.picture());
    await flush();
    expect(s.images.size).toBe(0);
    expect(s.usage).toBe(0);
    expect(changed).toBe(0);
    expect(d.closed()).toBe(1);
    // and a disposed store takes nothing more
    expect(s.handle(`a=T,U=1,i=8,f=100;${png()}`)).toBe(false);
  });

  it("clear (Show images off) while decoding: the late picture is closed and not kept", async () => {
    const d = deferredDecode();
    const s = new PlaceholderStore(d.decode);
    s.handle(`a=T,U=1,i=7,f=100;${png()}`);
    await flush();
    s.clear();
    d.waiting[0](d.picture());
    await flush();
    expect(s.images.size).toBe(0);
    expect(d.closed()).toBe(1);
  });

  it("a delete that lands during the decode wins (one id, and all)", async () => {
    const d = deferredDecode();
    const s = new PlaceholderStore(d.decode);
    s.handle(`a=T,U=1,i=7,f=100;${png()}`);
    s.handle(`a=T,U=1,i=8,f=100;${png()}`);
    await flush();
    s.handle("a=d,d=i,i=7");
    d.waiting[0](d.picture());
    d.waiting[1](d.picture());
    await flush();
    expect([...s.images.keys()]).toEqual([8]);
    s.handle(`a=T,U=1,i=9,f=100;${png()}`);
    await flush();
    s.handle("a=d,d=A");
    d.waiting[2](d.picture());
    await flush();
    expect(s.images.size).toBe(0);
    expect(d.closed()).toBe(3); // 7 and 9 late, 8 deleted
  });

  it("a newer transmit of the same id wins over an older one still decoding", async () => {
    const d = deferredDecode();
    const s = new PlaceholderStore(d.decode);
    s.handle(`a=T,U=1,i=7,f=100;${png()}`);
    await flush(); // the first is decoding
    s.handle(`a=T,U=1,i=7,f=100;${png()}`);
    await flush();
    expect(d.calls()).toBe(2);
    d.waiting[1](d.picture(2, 2));
    d.waiting[0](d.picture(1, 1));
    await flush();
    expect(s.images.get(7)?.picture.width).toBe(2);
    expect(d.closed()).toBe(1);
  });
});

describe("PlaceholderStore budget: one 32 MB per terminal with the add-on, refused before decoding", () => {
  it("the add-on's pictures come out of the same budget: a virtual one that does not fit what is left is never decoded", async () => {
    const { calls, decode } = fakeDecode([16, 32]);
    let addon = 0;
    const s = new PlaceholderStore(decode, undefined, undefined, { used: () => addon });
    addon = s.budget - 1000; // 16×32×4 = 2048 bytes do not fit
    s.handle(`a=T,U=1,i=1,f=100;${png(16, 32)}`);
    await flush();
    expect(calls).toHaveLength(0);
    expect(s.images.size).toBe(0);
    addon = 0;
    s.handle(`a=T,U=1,i=1,f=100;${png(16, 32)}`);
    await flush();
    expect(s.usage).toBe(2048);
    expect(s.usage + addon).toBeLessThanOrEqual(s.budget);
  });

  it("when the add-on adds a picture, the oldest virtual ones go until both fit", () => {
    let addon = 0;
    const closed: number[] = [];
    const pic = (n: number) => ({ width: 1, height: 1, close: () => closed.push(n) }) as unknown as Picture;
    const s = new PlaceholderStore(fakeDecode().decode, undefined, undefined, { used: () => addon });
    const third = s.budget / 3;
    s.put({ id: 1, picture: pic(1), bytes: third, cols: 1, rows: 1 });
    s.put({ id: 2, picture: pic(2), bytes: third, cols: 1, rows: 1 });
    addon = s.budget / 2;
    s.fit();
    expect([...s.images.keys()]).toEqual([2]);
    expect(closed).toEqual([1]);
    expect(s.usage + addon).toBeLessThanOrEqual(s.budget);
  });

  it("a PNG whose header names more pixels than the limit is refused before decoding", async () => {
    const { calls, decode } = fakeDecode();
    const s = new PlaceholderStore(decode);
    const side = Math.ceil(Math.sqrt(PIXEL_LIMIT)) + 1;
    s.handle(`a=T,U=1,i=1,f=100;${png(side, side)}`);
    s.handle(`a=T,U=1,i=2,f=100;${b64("not a png at all")}`);
    await flush();
    expect(calls).toHaveLength(0);
  });

  it("raw pixels whose s×v is over the limit are refused before inflating or decoding (no allocation for them)", async () => {
    const { calls, decode } = fakeDecode();
    const s = new PlaceholderStore(decode);
    // 4000×2001 RGB (just over the 8 M pixel limit), sent as a small zlib stream that would fill it
    const z = await deflate(new Uint8Array(4000 * 2001 * 3));
    s.handle(`a=T,U=1,i=1,f=24,s=4000,v=2001,o=z;${bytesB64(z)}`);
    await new Promise((r) => setTimeout(r, 200));
    expect(calls).toHaveLength(0);
  });

  it("o=z output is capped while it inflates: a small stream that expands past the raw size is dropped", async () => {
    const { calls, decode } = fakeDecode([2, 2]);
    const s = new PlaceholderStore(decode);
    const bomb = await deflate(new Uint8Array(4 * 1024 * 1024)); // 4 MiB of zeros, a few KB deflated
    expect(bomb.length).toBeLessThan(64 * 1024);
    s.handle(`a=T,U=1,i=1,f=32,s=2,v=2,o=z;${bytesB64(bomb)}`);
    await flush();
    await new Promise((r) => setTimeout(r, 50));
    expect(calls).toHaveLength(0);
    // the inflater itself stops at the cap; a stream within it comes out whole
    expect(await inflate(bomb, IMAGE_SEQUENCE_BYTES / 4)).toBeNull();
    const ok = await deflate(new Uint8Array(16).fill(7));
    expect(await inflate(ok, 16)).toEqual(new Uint8Array(16).fill(7));
    s.handle(`a=T,U=1,i=2,f=32,s=2,v=2,o=z;${bytesB64(ok)}`);
    await new Promise((r) => setTimeout(r, 50));
    expect(calls.map((c) => [c.format, c.w, c.h, c.bytes.length])).toEqual([[32, 2, 2, 16]]);
  });

  it("pngSize reads the IHDR", () => {
    expect(pngSize(pngHead(640, 480))).toEqual([640, 480]);
    expect(pngSize(new Uint8Array(40))).toBeNull();
  });
});

describe("PlaceholderStore: kitty's two-command form (a=t, then a=p,U=1)", () => {
  it("a=p,U=1 for a picture the add-on kept becomes a virtual placement of it", async () => {
    const { calls, decode } = fakeDecode([16, 32]);
    const kept = new Map([[41, { data: new Blob([pngHead(16, 32) as BlobPart]), width: 0, height: 0, format: 100 as const }]]);
    const s = new PlaceholderStore(decode, undefined, undefined, { used: () => 0, transmitted: (id) => kept.get(id) });
    expect(s.handle("a=t,f=100,i=41;AAAA")).toBe(false); // the transmit itself is the add-on's, as before
    expect(s.handle("a=p,U=1,i=41,c=2,r=2,q=2")).toBe(true);
    await flush();
    await flush();
    expect(calls).toHaveLength(1);
    expect(s.images.get(41)).toMatchObject({ id: 41, cols: 2, rows: 2 });
  });

  it("a=p,U=1 for an id neither store has goes to the add-on (it answers ENOENT as before); a=p without U=1 is untouched", () => {
    const s = new PlaceholderStore(fakeDecode().decode, undefined, undefined, { used: () => 0, transmitted: () => undefined });
    expect(s.handle("a=p,U=1,i=5")).toBe(false);
    expect(s.handle("a=p,i=5")).toBe(false);
  });

  it("a=p,U=1 for one of ours gives it the new box", async () => {
    const s = new PlaceholderStore(fakeDecode().decode);
    s.handle(`a=T,U=1,i=3,c=1,r=1,f=100;${png()}`);
    await flush();
    expect(s.handle("a=p,U=1,i=3,c=4,r=2")).toBe(true);
    expect(s.images.get(3)).toMatchObject({ cols: 4, rows: 2 });
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
