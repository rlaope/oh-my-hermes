import { describe, expect, it } from "vitest";
import { moveInSidebar, moveRange } from "./order";

describe("moveInSidebar", () => {
  const order = ["kami", "friren", "default", "omh-tui"];

  it("moves an unpinned bot within the roster", () => {
    expect(moveInSidebar(order, [], order, "omh-tui", 0)).toEqual({ pinned: [], roster: ["omh-tui", "kami", "friren", "default"] });
    expect(moveInSidebar(order, [], order, "kami", 2)).toEqual({ pinned: [], roster: ["friren", "default", "kami", "omh-tui"] });
  });

  it("returns null when the bot lands where it was or is not listed", () => {
    expect(moveInSidebar(order, [], order, "friren", 1)).toBeNull();
    expect(moveInSidebar(order, [], order, "ghost", 0)).toBeNull();
  });

  it("keeps a drag inside the bot's group: pinned among pinned, the rest below them", () => {
    // sidebar: [default (pinned), kami, friren, omh-tui]
    const shown = ["default", "kami", "friren", "omh-tui"];
    const roster = ["kami", "friren", "default", "omh-tui"];
    expect(moveRange(shown, ["default"], "default")).toEqual([0, 0]);
    expect(moveRange(shown, ["default"], "friren")).toEqual([1, 3]);
    // dropping an unpinned bot above the pinned one clamps to the first unpinned slot; nothing gets pinned, and the
    // pinned bot keeps its own roster slot (it shows on top because it is pinned, not because of the roster)
    expect(moveInSidebar(shown, ["default"], roster, "omh-tui", 0)).toEqual({ pinned: ["default"], roster: ["omh-tui", "kami", "default", "friren"] });
    // the pinned bot cannot be dragged below the rest
    expect(moveInSidebar(shown, ["default"], roster, "default", 3)).toBeNull();
  });

  it("reorders pinned bots in the pin list and leaves the roster alone", () => {
    const shown = ["friren", "kami", "default"];
    expect(moveInSidebar(shown, ["friren", "kami"], ["kami", "friren", "default"], "kami", 0)).toEqual({
      pinned: ["kami", "friren"],
      roster: ["kami", "friren", "default"],
    });
  });

  it("keeps roster entries Hermes no longer lists in their slots", () => {
    // "gone" is saved in the roster but not on this computer any more: it is not shown and must not be dropped
    const shown = ["kami", "friren", "default"];
    expect(moveInSidebar(shown, [], ["kami", "gone", "friren", "default"], "default", 0)).toEqual({
      pinned: [],
      roster: ["default", "gone", "kami", "friren"],
    });
  });
});
