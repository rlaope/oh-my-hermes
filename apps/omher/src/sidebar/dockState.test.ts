import { describe, expect, it } from "vitest";
import { botsAbove } from "./dockState";

describe("dock: the bots scrolled out of view above BOTS", () => {
  const rows = [
    { name: "kami", bottom: 40 },
    { name: "friren", bottom: 90 },
    { name: "bot01", bottom: 101 },
    { name: "bot02", bottom: 150 },
  ];
  it("none at the top of the list", () => {
    expect(botsAbove(0, rows)).toEqual([]);
  });
  it("exactly the rows wholly above the list's top, in list order; a row still partly in view is not one", () => {
    expect(botsAbove(100, rows)).toEqual(["kami", "friren", "bot01"]);
    expect(botsAbove(95, rows)).toEqual(["kami", "friren"]);
  });
});
