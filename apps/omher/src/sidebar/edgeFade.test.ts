import { describe, expect, it } from "vitest";
import { cutBelow, CUE_PX } from "./edgeFade";

describe("the cut row at a list's bottom edge is hidden whole", () => {
  it("a row the edge (or the chevron's band) would cut: hidden from its top", () => {
    // list ends at 400: rows 300..350, 352..402
    expect(cutBelow(400, [{ top: 300, bottom: 350 }, { top: 352, bottom: 402 }])).toBe(48);
  });
  it("rows ending above the band: only the band itself", () => {
    expect(cutBelow(400, [{ top: 300, bottom: 350 }])).toBe(CUE_PX);
  });
  it("a row that overlaps the hidden one (a bot row around its first thread) goes too", () => {
    expect(cutBelow(400, [{ top: 330, bottom: 382 }, { top: 370, bottom: 395 }])).toBe(70);
  });
  it("never leaves an open folder's header as the last row shown", () => {
    // header 300..330, its first card 332..380 cut by the end at 370: the header goes with it
    expect(cutBelow(370, [{ top: 250, bottom: 298 }, { top: 300, bottom: 330, head: true }, { top: 332, bottom: 380 }])).toBe(70);
  });
});
