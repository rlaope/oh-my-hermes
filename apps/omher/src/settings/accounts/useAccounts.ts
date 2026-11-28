// Shared copy of the Accounts data for the page and the auto-switch watcher: accounts.list from the bridge,
// plus what the desktop app knows (which CLIs are on this computer, each CLI's own login status). The watcher
// re-reads every minute (and on `accounts.update`); when a CLI's in-use account reaches its switch threshold (or is
// limited) and auto-switch is on, the next signed-in account with room becomes the one new sessions use, with one
// quiet line in the bot chat; when none has room, that is said once per window instead. Codex switches at most once
// every CODEX_SWITCH_EVERY_S. Running sessions are never touched.
import { useEffect, useSyncExternalStore } from "react";
import type { AccountCli, AccountGroup } from "../../lib/protocol";
import { getStore, notifyEnabled, useStore } from "../../state/store";
import { showNote } from "../../lib/notify";
import { t } from "../../i18n";
import { clock, limitName } from "../../sidebar/usageFormat";
import { accountHost, type LoginStatus } from "./native";
import { getSessions } from "../../sessions/sessions";
import {
  accountName,
  autoSwitchOn,
  isCpa,
  lapseNotices,
  modelsInUse,
  noRoomNote,
  pruneSeen,
  resetFirstOn,
  switchAt,
  switchCheck,
  switchHeld,
  switchNote,
  CLI_NAME,
} from "./rules";

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

/** When each CLI last switched by itself (seconds; this run of the app only). */
const lastSwitch: Partial<Record<AccountCli, number>> = {};
const ROOM_KEY = "omher.roomnoted";
/** A "no room" line with no known reset time is told again after this long at most. */
const ROOM_AGAIN_S = 5 * 3600;

async function autoSwitch(groups: AccountGroup[]): Promise<void> {
  const now = Date.now() / 1000;
  // the models the person's running sessions use: a model's own weekly limit counts only for its account's sessions
  const list = getSessions().getState().list;
  for (const g of groups) {
    if (!autoSwitchOn(g.cli) || switchHeld(g.cli, lastSwitch[g.cli], now)) continue;
    const move = switchCheck(g.accounts, {}, g.active, { resetFirst: resetFirstOn(g.cli), now, threshold: switchAt(g.cli), models: modelsInUse(list, g.cli) });
    if (!move) continue;
    if (move.to === null) {
      // once per account and window: the key ends with the reset of the window it is about (pruneSeen's form)
      const key = `${g.cli}:${g.accounts[move.from].id}:${move.at.resets_at ?? Math.floor(now / ROOM_AGAIN_S + 1) * ROOM_AGAIN_S}`;
      const seen = loadSeen(ROOM_KEY);
      if (seen.includes(key)) continue;
      saveSeen(ROOM_KEY, [...seen, key], now);
      tell(g.cli, noRoomNote(g, move.from, now, move.at));
      continue;
    }
    const text = switchNote(g, move.from, move.to, now, move.soonest, move.at);
    try {
      await getStore().actions.setActiveAccount(g.cli, g.accounts[move.to].id);
    } catch {
      continue;
    }
    lastSwitch[g.cli] = now;
    tell(g.cli, text);
  }
}

/** The auto-switch's one quiet line in the bot chat, and the toast on Settings › Accounts. */
function tell(cli: AccountCli, text: string): void {
  getStore().actions.systemNote(text);
  set({ note: { cli, text, at: Date.now() } });
}

const SEEN_KEY = "omher.lapsenoted";

function loadSeen(key = SEEN_KEY): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(key) ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function saveSeen(key: string, seen: string[], now: number): void {
  try {
    localStorage.setItem(key, JSON.stringify(pruneSeen(seen, now)));
  } catch {
    /* no storage */
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
  saveSeen(SEEN_KEY, seen, now);
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
