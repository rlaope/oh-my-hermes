import { describe, expect, it } from "vitest";
import { sideAt } from "./splitDrag";

describe("a drop on a pane", () => {
  const box = { left: 100, top: 50, width: 400, height: 200 };
  it("goes to the side whose edge is nearest the pointer", () => {
    expect(sideAt(box, 480, 150)).toBe("right");
    expect(sideAt(box, 120, 150)).toBe("left");
    expect(sideAt(box, 300, 60)).toBe("up");
    expect(sideAt(box, 300, 240)).toBe("down");
    // measured against the pane's own width and height: a wide pane's corner area goes by the nearer fraction
    expect(sideAt(box, 450, 70)).toBe("up");
    expect(sideAt(box, 490, 70)).toBe("right");
  });
});
