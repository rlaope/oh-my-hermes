// Shared copy of accounts.list for the Accounts page and the auto-switch watcher, plus the watcher itself.
// The watcher re-reads every minute (and on `accounts.update`); when an omher group's active account is
// limited and auto-switch is on, it makes the next Ready account active (fill-first) and drops one quiet line
// into the bot chat. Running sessions are never touched: only the account new sessions start with changes.
import { useEffect, useSyncExternalStore } from "react";
import type { AccountGroup } from "../../lib/protocol";
import { getStore, useStore } from "../../state/store";
import { autoSwitchOn, nextAccount, switchNote } from "./rules";

const REFRESH_MS = 60_000;

type Snap = { groups: AccountGroup[] | null; error: string | null; note: { cli: string; text: string; at: number } | null };
let snap: Snap = { groups: null, error: null, note: null };
const fns = new Set<() => void>();
const set = (next: Partial<Snap>) => {
  snap = { ...snap, ...next };
  for (const f of [...fns]) f();
};
let inflight: Promise<void> | null = null;

export function reloadAccounts(): Promise<void> {
  inflight ??= getStore()
    .actions.accounts()
    .then(
      async (r) => {
        set({ groups: r.groups, error: null });
        await autoSwitch(r.groups);
      },
      (e: unknown) => set({ error: typeof e === "object" && e && "message" in e ? String(e.message) : String(e) }),
    )
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

async function autoSwitch(groups: AccountGroup[]): Promise<void> {
  const now = Date.now() / 1000;
  for (const g of groups) {
    if (g.backend !== "omher" || !autoSwitchOn(g.cli)) continue;
    const move = nextAccount(g.accounts, {}, g.active);
    if (!move) continue;
    const text = switchNote(g, move.from, move.to, now);
    try {
      await getStore().actions.setActiveAccount(g.cli, g.accounts[move.to].id);
    } catch {
      continue;
    }
    getStore().actions.systemNote(text);
    set({ note: { cli: g.cli, text, at: Date.now() } });
  }
}

export function useAccounts(): Snap {
  return useSyncExternalStore(
    (f) => {
      fns.add(f);
      return () => fns.delete(f);
    },
    () => snap,
    () => snap,
  );
}

/** Mounted once in the sidebar: keeps the copy fresh and runs the auto-switch. Renders nothing. */
export function AccountsWatcher() {
  const conn = useStore().conn;
  useEffect(() => {
    if (conn !== "open") return;
    void reloadAccounts();
    const h = setInterval(() => void reloadAccounts(), REFRESH_MS);
    const off = getStore().actions.onBridgeEvent((ev) => {
      if (ev.event === "accounts.update") void reloadAccounts();
    });
    return () => {
      clearInterval(h);
      off();
    };
  }, [conn]);
  return null;
}
