import { beforeEach, describe, expect, it } from "vitest";
import { addTerminalTab, closePane, closeTerminalTab, getTermPanel, leafName, movePaneFocus, pickTerminalTab, resetTermPanel, ringPane, setPaneCwd, setTerminalCwd, splitPane, toggleTerminal } from "./state";
import { clampPanelH, PANEL_H_DEFAULT, PANEL_H_MIN } from "./Panel";

beforeEach(() => resetTermPanel());

describe("the terminal panel's state", () => {
  it("Ctrl+` opens with a first tab at the folder setTerminalCwd named, hides, and shows the same tab again", () => {
    setTerminalCwd("/home/you/code/web-app");
    toggleTerminal();
    let s = getTermPanel();
    expect(s.open).toBe(true);
    expect(s.tabs).toEqual([expect.objectContaining({ key: 1, want: "/home/you/code/web-app", cwd: null, layout: { pane: 1 }, focus: 1 })]);
    toggleTerminal();
    expect(getTermPanel().open).toBe(false);
    expect(getTermPanel().tabs).toHaveLength(1); // hidden, not closed
    const focus = getTermPanel().focus;
    toggleTerminal();
    s = getTermPanel();
    expect(s.open).toBe(true);
    expect(s.tabs).toHaveLength(1);
    expect(s.focus).toBeGreaterThan(focus);
  });

  it("with no thread folder a tab starts at home (null), and a changed folder applies to the next tab only", () => {
    toggleTerminal();
    expect(getTermPanel().tabs[0].want).toBeNull();
    setTerminalCwd("/srv/app");
    addTerminalTab();
    setTerminalCwd(null);
    addTerminalTab();
    expect(getTermPanel().tabs.map((t) => t.want)).toEqual([null, "/srv/app", null]);
    setTerminalCwd("   ");
    expect(getTermPanel().cwd).toBeNull();
  });

  it("closing a tab picks its neighbour; closing the last hides the panel", () => {
    addTerminalTab();
    addTerminalTab();
    addTerminalTab();
    pickTerminalTab(2);
    closeTerminalTab(2);
    expect(getTermPanel().active).toBe(3);
    closeTerminalTab(3);
    expect(getTermPanel().active).toBe(1);
    closeTerminalTab(1);
    expect(getTermPanel()).toMatchObject({ tabs: [], active: null, open: false });
  });

  it("names a tab by its folder's last part", () => {
    addTerminalTab();
    setPaneCwd(1, "/home/you/code/web-app/");
    expect(leafName(getTermPanel().tabs[0].cwd)).toBe("web-app");
    expect(leafName("C:\\Users\\you\\proj")).toBe("proj");
    expect(leafName(null)).toBe("~");
    expect(leafName("/")).toBe("/");
  });

  it("keeps the panel height between its minimum and what leaves the view above usable", () => {
    expect(clampPanelH(50, 900)).toBe(PANEL_H_MIN);
    expect(clampPanelH(5000, 900)).toBe(900 - 160);
    expect(clampPanelH(NaN, 900)).toBe(PANEL_H_DEFAULT);
    expect(clampPanelH(300, 200)).toBe(PANEL_H_MIN);
  });

  it("splits the focused pane in its own folder, closes a pane into its sibling, and the last pane closes the tab", () => {
    setTerminalCwd("/srv/app");
    toggleTerminal();
    setPaneCwd(1, "/srv/app/web");
    expect(splitPane("right")).toBe(true);
    let tab = getTermPanel().tabs[0];
    expect(tab.panes.map((p) => [p.id, p.want])).toEqual([[1, "/srv/app"], [2, "/srv/app/web"]]);
    expect(tab.layout).toEqual({ dir: "row", ratio: 0.5, a: { pane: 1 }, b: { pane: 2 } });
    expect(tab.focus).toBe(2);
    expect(splitPane("down")).toBe(true);
    expect(splitPane("down")).toBe(true);
    expect(splitPane("right")).toBe(false); // four is the most
    expect(getTermPanel().tabs[0].panes).toHaveLength(4);
    expect(movePaneFocus("left")).toBe(true);
    expect(getTermPanel().tabs[0].focus).toBe(1);
    closePane(1);
    tab = getTermPanel().tabs[0];
    expect(tab.panes.map((p) => p.id)).toEqual([2, 3, 4]);
    expect(tab.focus).toBe(2);
    closePane(2);
    closePane(3);
    expect(getTermPanel().tabs[0].layout).toEqual({ pane: 4 });
    closePane(4);
    expect(getTermPanel()).toMatchObject({ tabs: [], open: false });
  });

  it("a shell that rings marks its tab while the tab is not in front; picking the tab clears it", () => {
    addTerminalTab();
    addTerminalTab();
    ringPane(1);
    expect(getTermPanel().tabs.map((t) => !!t.rang)).toEqual([true, false]);
    pickTerminalTab(1);
    expect(getTermPanel().tabs[0].rang).toBe(false);
  });
});
