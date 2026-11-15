import { beforeEach, describe, expect, it } from "vitest";
import { addTerminalTab, closeTerminalTab, getTermPanel, leafName, pickTerminalTab, resetTermPanel, setTabCwd, setTerminalCwd, toggleTerminal } from "./state";
import { clampPanelH, PANEL_H_DEFAULT, PANEL_H_MIN } from "./Panel";

beforeEach(() => resetTermPanel());

describe("the terminal panel's state", () => {
  it("Ctrl+` opens with a first tab at the folder setTerminalCwd named, hides, and shows the same tab again", () => {
    setTerminalCwd("/Users/you/code/web-app");
    toggleTerminal();
    let s = getTermPanel();
    expect(s.open).toBe(true);
    expect(s.tabs).toEqual([{ key: 1, want: "/Users/you/code/web-app", cwd: null }]);
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
    setTabCwd(1, "/Users/you/code/web-app/");
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
});
