// The store has no "re-read bots" action, so the add-bot popover asks the bridge itself over a short-lived
// second connection (same URL resolution as the app's client) and hands the result to the store.
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
