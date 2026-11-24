// Hand to <bot> from a split card's cell: the cell's menu kit (ROW_MENU) offers the row's Hand item under the row's
// conditions, labels it as the row does, and opens the row's card for the session's own folder.
import { describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { Bot } from "../lib/protocol";
import type { SessionRec } from "./agents";

const shown = vi.hoisted(() => ({ bots: [] as Bot[] }));
vi.mock("../state/store", async (orig) => {
  const real = await orig<typeof import("../state/store")>();
  return {
    ...real,
    getStore: () => {
      const s = real.getStore();
      return { ...s, getSnapshot: () => ({ ...s.getSnapshot(), bots: shown.bots }) };
    },
  };
});

const { ROW_MENU, termMenuItems } = await import("./SessionsSection");
const { HandoverCard } = await import("../handover/HandoverCard");

const bot = (name: string, over: Partial<Bot> = {}): Bot => ({ name, display_name: name, is_default: false, model: "", provider: "", description: "", status: "online", running: true, ...over });
const rec = (over: Partial<SessionRec> = {}) => ({ id: "s1", agent: "shell", cwd: "/w/demo", startedAt: 1, linkId: "abcdefgh23", status: "running", ...over }) as SessionRec;
const menu = (r: SessionRec) => renderToStaticMarkup(<ROW_MENU.Menu at={{ x: 0, y: 0 }} name="demo" actions={ROW_MENU.items(r)} onPick={() => {}} onDismiss={() => {}} />);

describe("a split card cell's menu", () => {
  it("offers Hand to <bot> exactly when a row does: a folder, and a bot of this computer online", () => {
    shown.bots = [bot("demo-bot")];
    expect(ROW_MENU.items(rec())).toEqual(["rename", "reveal", "terminal", "link", "hand", "here", "close"]);
    expect(ROW_MENU.items(rec())).toEqual(termMenuItems(rec(), true));
    // no folder: nothing to hand
    expect(ROW_MENU.items(rec({ cwd: "" }))).not.toContain("hand");
  });

  it("offers no Hand with no bot, only offline bots, or only bots over SSH", () => {
    const ssh = { kind: "ssh", peer: "mini", label: "Mini", host: "demo@example.invalid" } as unknown as Bot["host"];
    for (const bots of [[], [bot("demo-bot", { status: "offline" })], [bot("mini:default", { host: ssh })]]) {
      shown.bots = bots;
      expect(ROW_MENU.items(rec())).toEqual(["rename", "reveal", "terminal", "link", "here", "close"]);
      expect(menu(rec())).not.toContain('data-testid="session-hand"');
    }
  });

  it("draws the item as a menu item named for the one bot, else for a bot of several", () => {
    shown.bots = [bot("demo-bot", { display_name: "Demo" })];
    const one = menu(rec());
    expect(one).toContain('role="menu"');
    expect(one).toMatch(/<button type="button" role="menuitem" class="row-mi" data-testid="session-hand">Hand to Demo…<\/button>/);
    shown.bots = [bot("demo-bot"), bot("default")];
    expect(menu(rec())).toMatch(/role="menuitem" class="row-mi" data-testid="session-hand">Hand to a bot…<\/button>/);
  });

  it("opens the row's card for the folder its own session started in, one per cell", () => {
    const onClose = () => {};
    const back = () => null;
    const hand = ROW_MENU.Hand as (p: { at: { x: number; y: number }; rec: SessionRec; back: () => HTMLElement | null; onClose: () => void }) => ReactElement;
    const left = hand({ at: { x: 4, y: 5 }, rec: rec({ id: "s1", cwd: "/w/demo" }), back, onClose });
    const right = hand({ at: { x: 4, y: 5 }, rec: rec({ id: "s2", cwd: "/w/other" }), back, onClose });
    expect(left.type).toBe(HandoverCard);
    // the card gives the keyboard back to the cell's face, else termBack's fallbacks (termBack.test.ts)
    expect(left.props).toEqual({ at: { x: 4, y: 5 }, from: { kind: "terminal", folder: "/w/demo" }, back: expect.any(Function), onClose });
    expect((right.props as { from: unknown }).from).toEqual({ kind: "terminal", folder: "/w/other" });
  });
});
