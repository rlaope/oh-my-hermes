import { describe, expect, it } from "vitest";
import { rowMoving, type RowFrame } from "./rowMotion";

/** [ms relative to the press, left edge of the row's free space] */
const frames = (xs: [number, number][]): RowFrame[] => xs.map(([at, x0]) => ({ at, x0 }));

describe("rowMoving: was the tab row still moving for a press during the maximise / restore slide", () => {
  it("a tab that stopped three frames before the click is the tab's (panel-max.spec.ts:154 flake, recorded at 6x CPU throttle)", () => {
    // the restore's last steps 951-ish then 953, then three still frames, all within 60 ms of the click; the
    // transition had ended and the hit test found the Terminal tab where the person saw it
    const recorded = frames([[-239, 651], [-224, 651], [-208, 696], [-191, 738], [-108, 777], [-69, 901], [-54, 950], [-40, 953], [-26, 953], [-9, 953]]);
    expect(rowMoving(recorded, 0, 953, false)).toBe(false);
  });

  it("a press mid-slide whose handler runs after the slide ended is the row's: the row slid between the frame seen and the hit test", () => {
    // a loaded runner: frames 60 ms apart, the press at 0 while the row was at 655, the handler late, the transition
    // over and the row at 953 when the browser hit-tested the press (a tab now under the pointer)
    const sparse = frames([[-130, 473], [-70, 473], [-10, 655]]);
    expect(rowMoving(sparse, 0, 953, false)).toBe(true);
  });

  it("a frame drawn after the press is not what the person saw, but the row it shows counts against the hit test", () => {
    expect(rowMoving(frames([[-30, 953], [-10, 953], [20, 960]]), 0, 960, false)).toBe(true);
    expect(rowMoving(frames([[-30, 953], [-10, 953], [20, 953]]), 0, 953, false)).toBe(false);
  });

  it("while the slide's transition runs the row is moving, whatever the frames say", () => {
    expect(rowMoving(frames([[-40, 953], [-20, 953]]), 0, 953, true)).toBe(true);
  });

  it("a row that arrived in the very frame the person saw (less than MOVE_MS before the press) was aimed at a frame earlier", () => {
    expect(rowMoving(frames([[-40, 900], [-8, 953]]), 0, 953, false)).toBe(true);
  });

  it("a row that arrived long before the press and held still has stopped", () => {
    expect(rowMoving(frames([[-200, 900], [-100, 953]]), 0, 953, false)).toBe(false);
  });

  it("a press before the slide's first frame saw the row where it was before the slide", () => {
    expect(rowMoving(frames([[10, 953]]), 0, 953, false)).toBe(true);
  });

  it("sub-pixel jitter is not movement", () => {
    expect(rowMoving(frames([[-30, 952.6], [-10, 953.4]]), 0, 953.9, false)).toBe(false);
  });
});
