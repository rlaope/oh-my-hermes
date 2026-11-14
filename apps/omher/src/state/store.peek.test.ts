// Bots outside the sidebar list (the roster) are only asked for the prompts their existing Bot Chat holds
// (`chat.open` with `existing_only`). These cover every path that must ask them: start, a reconnect, a restart of
// that bot, and a profile that appears later. The fake reads every bot offline, as the real bridge does for a
// profile it has not attached yet. Reproducers from the independent re-verify of the roster run.
import { expect, it } from "vitest";
import { createStore, selectAsks, selectSidebarBots, type BridgeLike } from "./store";
import type { BridgeEvent } from "../lib/protocol";
import type { BridgeStatus } from "../lib/bridge";

function fixture() {
  let event!: (e: BridgeEvent) => void, status!: (s: BridgeStatus) => void;
  let names = ["default", "friren"];
  let pending = false;
  const calls: { op: string; params: any }[] = [];
  const ask = () =>
    event({ event: "approval.request", bot: "friren", request_id: "ap1", title: "Delete files", command: "rm scratch-file", choices: ["once", "deny"] } as BridgeEvent);
  const bridge: BridgeLike = {
    connect: async () => {
      status("open");
    },
    onAny: (h) => {
      event = h;
      return () => {};
    },
    onStatus: (h) => {
      status = h;
      return () => {};
    },
    request: (async (op: string, params: any) => {
      calls.push({ op, params });
      if (op === "hello") return { bridge: "mock", version: "test", hermes: { home: "/scratch" } };
      if (op === "bots.list")
        return { bots: names.map((name) => ({ name, display_name: name, is_default: name === "default", model: "m", provider: "p", description: "", status: "offline", running: false })) };
      if (op === "chat.open") {
        if (params.bot === "friren" && pending) queueMicrotask(ask);
        return { session_id: `s-${params.bot}`, messages: [], running: params.bot === "friren" && pending, model: "m", provider: "p", reasoning: "high" };
      }
      if (op === "elsewhere.list") return { sessions: [] };
      if (op === "routines.list") return { routines: [] };
      if (op === "automations.list") return { automations: [] };
      if (op === "models.options") return { providers: [], current: { model: "m", provider: "p", reasoning: "high" }, reasoning_levels: [] };
      return {};
    }) as BridgeLike["request"],
  };
  const store = createStore(bridge);
  return {
    store, calls, ask,
    event: (e: BridgeEvent) => event(e),
    status: (s: BridgeStatus) => status(s),
    pending: (p: boolean) => { pending = p; },
    names: (n: string[]) => { names = n; },
  };
}
const settle = () => new Promise((r) => setTimeout(r, 30));
const peeks = (calls: { op: string; params: any }[], bot: string) =>
  calls.filter((c) => c.op === "chat.open" && c.params.bot === bot && c.params.existing_only === true).length;

it("start: a waiting ask is replayed into Needs; opening it and answering makes one card and clears it", async () => {
  const f = fixture();
  f.pending(true);
  await f.store.actions.init();
  await settle();
  expect(selectSidebarBots(f.store.getState()).map((b) => b.name)).toEqual(["default"]);
  const asks = selectAsks(f.store.getState());
  expect(asks).toHaveLength(1);
  expect(asks[0].item).toMatchObject({ kind: "approval", request_id: "ap1", command: "rm scratch-file" });
  await f.store.actions.jumpToAsk("friren", asks[0].item.id);
  await settle();
  expect(f.calls.some((c) => c.op === "chat.open" && c.params.bot === "friren" && c.params.existing_only !== true)).toBe(true);
  expect(f.store.getState().chats.friren.items.filter((i) => i.kind === "approval")).toHaveLength(1);
  await f.store.actions.respondApproval("ap1", "deny");
  expect(selectAsks(f.store.getState())).toHaveLength(0);
});

it("a live ask after the start peek reaches Needs without listing the bot", async () => {
  const f = fixture();
  await f.store.actions.init();
  f.ask();
  expect(selectAsks(f.store.getState())).toHaveLength(1);
  expect(selectSidebarBots(f.store.getState()).map((b) => b.name)).toEqual(["default"]);
});

it("reconnect: an ask raised while the stream was down is replayed from a bot outside the list", async () => {
  const f = fixture();
  await f.store.actions.init();
  f.calls.length = 0;
  f.status("closed");
  f.pending(true);
  f.status("open");
  await settle();
  expect(peeks(f.calls, "friren")).toBe(1);
  expect(selectAsks(f.store.getState())).toHaveLength(1);
  expect(selectSidebarBots(f.store.getState()).map((b) => b.name)).toEqual(["default"]);
});

it("bot.restarted: a bot outside the list is asked again (the restart dropped its Bot Chat link)", async () => {
  const f = fixture();
  await f.store.actions.init();
  f.calls.length = 0;
  f.event({ event: "bot.restarted", bot: "friren", ok: true } as BridgeEvent);
  await settle();
  expect(peeks(f.calls, "friren")).toBe(1);
});

it("bots.update: a profile that appeared later is asked for its waiting asks; known ones are not asked again", async () => {
  const f = fixture();
  f.names(["default"]);
  await f.store.actions.init();
  f.calls.length = 0;
  f.names(["default", "friren"]);
  f.pending(true);
  f.event({ event: "bots.update", bot: "friren" } as BridgeEvent);
  await settle();
  expect(selectAsks(f.store.getState())).toHaveLength(1);
  f.calls.length = 0;
  f.event({ event: "bots.update", bot: "friren" } as BridgeEvent);
  await settle();
  expect(peeks(f.calls, "friren")).toBe(0);
});
