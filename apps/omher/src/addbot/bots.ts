// The store has no "re-read bots" action, so the add-bot popover asks the bridge itself over a short-lived
// second connection (same URL resolution as the app's client) and hands the result to the store. addToList is the
// one "bring this bot in" action: the sidebar `+` and Settings › All bots both use it.
import { BridgeClient } from "../lib/bridge";
import type { Bot } from "../lib/protocol";
import type { Store } from "../state/store";

async function withBridge<T>(fn: (b: BridgeClient) => Promise<T>): Promise<T> {
  const b = new BridgeClient();
  try {
    await b.connect();
    return await fn(b);
  } finally {
    b.close();
  }
}

/** bots.list -> store. Returns the fresh list. */
export async function refreshBots(store: Store): Promise<Bot[]> {
  const { bots } = await withBridge((b) => b.request("bots.list", {}));
  store.dispatch({ type: "bots", bots });
  return bots;
}

/**
 * Attach a profile's gateway with one harmless read (`models.options`, which the bridge serves only after
 * attaching), then re-read bots.list. A profile that still cannot start replies `bot_offline`; the list is
 * re-read anyway so the row shows the bridge's view. Returns the bot as the bridge now reports it.
 */
export async function connectProfile(store: Store, name: string): Promise<Bot | undefined> {
  return withBridge(async (b) => {
    let err: unknown = null;
    try {
      const options = await b.request("models.options", { bot: name });
      store.dispatch({ type: "models", bot: name, options });
    } catch (e) {
      err = e;
    }
    const { bots } = await b.request("bots.list", {});
    store.dispatch({ type: "bots", bots });
    const bot = bots.find((x) => x.name === name);
    if (err && bot?.status !== "online") throw err;
    return bot;
  });
}

/**
 * One click from `+` (or Settings › All bots): the bot joins the sidebar list, its chat opens (Settings passes
 * `open: false` and stays on its page), and its gateway is attached as Connect did. A profile that cannot start
 * still joins; its chat shows the usual offline line.
 */
export async function addToList(store: Store, name: string, { open = true }: { open?: boolean } = {}): Promise<void> {
  store.actions.listBot(name, true);
  await Promise.all([open ? store.actions.selectBot(name) : undefined, connectProfile(store, name).catch(() => undefined)]);
}
