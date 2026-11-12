// Shared copy of the Accounts data for the page and the auto-switch watcher: accounts.list from the bridge,
// plus what the desktop app knows (which CLIs are on this computer, each CLI's own login status). The watcher
// re-reads every minute (and on `accounts.update`); when a CLI's in-use account is limited and auto-switch is
// on, the next signed-in account becomes the one new sessions use, with one quiet line in the bot chat.
// Running sessions are never touched.
import { useEffect, useSyncExternalStore } from "react";
import type { AccountCli, AccountGroup } from "../../lib/protocol";
import { getStore, notifyEnabled, useStore } from "../../state/store";
import { showNote } from "../../lib/notify";
import { t } from "../../i18n";
import { clock, limitName } from "../../sidebar/usageFormat";
import { accountHost, type LoginStatus } from "./native";
import { accountName, autoSwitchOn, isCpa, lapseNotices, nextAccount, pruneSeen, resetFirstOn, switchNote, CLI_NAME } from "./rules";

const REFRESH_MS = 60_000;
const ASKS_STATUS: AccountCli[] = ["claude", "codex"];

type Snap = {
  groups: AccountGroup[] | null;
  error: string | null;
  /** cli -> on this computer (desktop app), null when unknown. */
  onComputer: Partial<Record<AccountCli, boolean>> | null;
  /** `${cli}:${account}` -> the CLI's own status. */
  status: Record<string, LoginStatus>;
  /** cli -> the CLI's version token, for the CLIs that have a fixed `--version` and printed one. */
  versions: Partial<Record<AccountCli, string>>;
  note: { cli: string; text: string; at: number } | null;
};
let snap: Snap = { groups: null, error: null, onComputer: null, status: {}, versions: {}, note: null };
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
      if (isCpa(a)) continue; // CLIProxyAPI's: no folder, no CLI to ask
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

async function readVersions(groups: AccountGroup[]): Promise<Partial<Record<AccountCli, string>>> {
  const host = accountHost();
  const out: Partial<Record<AccountCli, string>> = { ...snap.versions };
  await Promise.all(
    groups
      .filter((g) => ASKS_STATUS.includes(g.cli) && !out[g.cli])
      .map((g) =>
        Promise.resolve()
          .then(() => host.version(g.cli))
          .then(
          (v) => {
            if (v) out[g.cli] = v;
          },
          () => {},
        ),
      ),
  );
  return out;
}

export function reloadAccounts(): Promise<void> {
  inflight ??= (async () => {
    try {
      const [r, onComputer] = await Promise.all([getStore().actions.accounts(), accountHost().clis().catch(() => null)]);
      set({ groups: r.groups, error: null, onComputer });
      const here = r.groups.filter((g) => onComputer?.[g.cli] ?? g.installed);
      set({ status: await readStatuses(here) });
      set({ versions: await readVersions(here) });
      await autoSwitch(r.groups);
      await lapseNotice(r.groups);
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
    const move = nextAccount(g.accounts, {}, g.active, { resetFirst: resetFirstOn(g.cli), now });
    if (!move) continue;
    const text = switchNote(g, move.from, move.to, now, move.soonest);
    try {
      await getStore().actions.setActiveAccount(g.cli, g.accounts[move.to].id);
    } catch {
      continue;
    }
    getStore().actions.systemNote(text);
    set({ note: { cli: g.cli, text, at: Date.now() } });
  }
}

const SEEN_KEY = "omher.lapsenoted";

function loadSeen(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** One system notification per account and reset time when a window that is about to reset has barely been used.
 *  The pairs told are kept on this computer, so a reload or a restart does not tell the same one twice. */
async function lapseNotice(groups: AccountGroup[]): Promise<void> {
  const now = Date.now() / 1000;
  const seen = loadSeen();
  const told = new Set(seen);
  for (const g of groups) {
    for (const n of lapseNotices(g.cli, g.accounts, now, told)) {
      if (!notifyEnabled()) continue; // not shown, so not told: turning notices on before the reset still tells once
      told.add(n.key);
      seen.push(n.key);
      const name = limitName(g.accounts[n.index].usage?.windows.find((w) => w.resets_at === n.resets_at)?.label ?? "");
      void showNote({
        title: t("acc.lapseTitle", { cli: CLI_NAME[g.cli], name: accountName(g.accounts[n.index], n.index) }),
        body: t("acc.lapseBody", { pct: Math.round(n.percent), name, when: clock(n.resets_at, now) }),
        bot: "",
        tag: n.key,
      });
    }
  }
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify(pruneSeen(seen, now)));
  } catch {
    /* no storage */
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
