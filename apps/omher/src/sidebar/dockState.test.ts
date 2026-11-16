import { describe, expect, it } from "vitest";
import { dockTiles, DOCK_MAX, parseDock } from "./dockState";

describe("dock state", () => {
  it("keeps only well-formed pins, once each", () => {
    expect(parseDock(JSON.stringify({ pins: ["bot:kami", "term:s3", "bot:kami", "x", 4, "term:"] })).pins).toEqual(["bot:kami", "term:s3"]);
    expect(parseDock("not json").pins).toEqual([]);
    expect(parseDock(null).pins).toEqual([]);
  });
  it("shows the pins that still exist, in order, at most six", () => {
    const pins = ["bot:a", "term:s1", "bot:gone", "bot:b", "bot:c", "bot:d", "bot:e", "bot:f"];
    const t = dockTiles(pins, (k) => k !== "bot:gone", []);
    expect(t.auto).toBe(false);
    expect(t.keys).toEqual(["bot:a", "term:s1", "bot:b", "bot:c", "bot:d", "bot:e"]);
    expect(t.keys).toHaveLength(DOCK_MAX);
  });
  it("with nothing pinned, the bots with the newest activity (no terminal)", () => {
    expect(dockTiles([], () => true, ["kami", "friren"])).toEqual({ keys: ["bot:kami", "bot:friren"], auto: true });
  });
});
