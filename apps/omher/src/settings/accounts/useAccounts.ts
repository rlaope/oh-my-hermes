// Shared copy of the Accounts data for the page and the auto-switch watcher: accounts.list from the bridge,
// plus what the desktop app knows (which CLIs are on this computer, each CLI's own login status). The watcher
// re-reads every minute (and on `accounts.update`); when a CLI's in-use account is limited and auto-switch is
// on, the next signed-in account becomes the one new sessions use, with one quiet line in the bot chat.
// Running sessions are never touched.
import { useEffect, useSyncExternalStore } from "react";
import type { AccountCli, AccountGroup } from "../../lib/protocol";
import { getStore, useStore } from "../../state/store";
import { accountHost, type LoginStatus } from "./native";
import { autoSwitchOn, nextAccount, switchNote } from "./rules";

const REFRESH_MS = 60_000;
const ASKS_STATUS: AccountCli[] = ["claude", "codex"];

type Snap = {
  groups: AccountGroup[] | null;
  error: string | null;
  /** cli -> on this computer (desktop app), null when unknown. */
  onComputer: Partial<Record<AccountCli, boolean>> | null;
  /** `${cli}:${account}` -> the CLI's own status. */
  status: Record<string, LoginStatus>;
  note: { cli: string; text: string; at: number } | null;
};
let snap: Snap = { groups: null, error: null, onComputer: null, status: {}, note: null };
const fns = new Set<() => void>();
const set = (next: Partial<Snap>) => {
  snap = { ...snap, ...next };
  for (const f of [...fns]) f();
};
let inflight: Promise<void> | null = null;

const errText = (e: unknown) => (typeof e === "object" && e && "message" in e ? String((e as { message: unknown }).message) : String(e));

async function readStatuses(groups: AccountGroup[]): Promise<Record<string, LoginStatus>> {
  const host = accountHost();
  const out: Record<string, LoginStatus> = {};
  const asks: Promise<void>[] = [];
  for (const g of groups) {
    if (!ASKS_STATUS.includes(g.cli)) continue;
    for (const a of g.accounts) {
      asks.push(
        host.status(g.cli, a.id).then(
          (st) => {
            if (st) out[`${g.cli}:${a.id}`] = st;
          },
          () => {},
        ),
      );
    }
  }
  await Promise.all(asks);
  return out;
}

export function reloadAccounts(): Promise<void> {
  inflight ??= (async () => {
    try {
      const [r, onComputer] = await Promise.all([getStore().actions.accounts(), accountHost().clis().catch(() => null)]);
      set({ groups: r.groups, error: null, onComputer });
      set({ status: await readStatuses(r.groups.filter((g) => onComputer?.[g.cli] ?? g.installed)) });
      await autoSwitch(r.groups);
    } catch (e) {
      set({ error: errText(e) });
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

async function autoSwitch(groups: AccountGroup[]): Promise<void> {
  const now = Date.now() / 1000;
  for (const g of groups) {
    if (!autoSwitchOn(g.cli)) continue;
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

/** The accounts as last read (null before the first read); SESSIONS notes which one a new session runs as. */
export const accountGroups = (): AccountGroup[] | null => snap.groups;

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
