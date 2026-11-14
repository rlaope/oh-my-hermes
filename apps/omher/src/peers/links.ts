// Keeps the bridge in step with the desktop shell's SSH links: a link that comes up is attached to the bridge
// (`peers.attach`, its bots join the list as `<peer>:<name>`), and a link that goes away or is removed is detached.
// The same state feeds the SSH marker's status line and Settings › Remote machines.
import { useEffect, useSyncExternalStore } from "react";
import { BridgeClient } from "../lib/bridge";
import { getStore } from "../state/store";
import { getPeersHost, type PeerStatus } from "./host";

type Listener = () => void;

let peers: PeerStatus[] = [];
const listeners = new Set<Listener>();
const attached = new Map<string, string>(); // peer id -> the url attached to the bridge
const fresh = new Set<string>(); // peers the person just pressed Connect for: their bots join the sidebar list once

/** The confirm card's Connect added `id`: when its bots arrive they join the sidebar (a reattach on a later start
 *  leaves the list as the person keeps it). */
export function markFresh(id: string): void {
  fresh.add(id);
  // the link may have come up before Connect returned: list its bots now
  const st = peers.find((p) => p.id === id);
  if (st?.state === "connected" && attached.has(id)) {
    attached.delete(id);
    void sync(st);
  }
}
let started = false;

function emit() {
  for (const l of [...listeners]) l();
}

/** One short-lived bridge connection for a peers op (the store's own client keeps its events). */
async function withBridge<T>(fn: (b: BridgeClient) => Promise<T>): Promise<T> {
  const b = new BridgeClient();
  try {
    await b.connect();
    return await fn(b);
  } finally {
    b.close();
  }
}

async function sync(st: PeerStatus) {
  if (st.state === "connected" && st.url) {
    if (attached.get(st.id) === st.url) return;
    attached.set(st.id, st.url);
    try {
      const r = await withBridge((b) => b.request("peers.attach", { peer: st.id, label: st.label, host: st.host, url: st.url! }));
      if (fresh.delete(st.id)) {
        await getStore().actions.reloadBots();
        for (const b of r.bots) getStore().actions.listBot(b.name, true);
        if (r.bots[0]) void getStore().actions.selectBot(r.bots[0].name);
        return;
      }
    } catch {
      attached.delete(st.id);
    }
  } else if (st.state === "removed" && attached.has(st.id)) {
    // only a removed peer leaves the list: a link that is reconnecting or failed keeps its bots, shown offline
    // with the link's state on their SSH marker, and a new link replaces the old one when it comes up
    attached.delete(st.id);
    await withBridge((b) => b.request("peers.detach", { peer: st.id })).catch(() => undefined);
  }
  void getStore().actions.reloadBots();
}

function put(st: PeerStatus) {
  peers = st.state === "removed" ? peers.filter((p) => p.id !== st.id) : [...peers.filter((p) => p.id !== st.id), st].sort((a, b) => a.label.localeCompare(b.label));
  emit();
  void sync(st);
}

/** Start following the shell's links (once, at app start). */
export async function startPeers(): Promise<void> {
  if (started) return;
  started = true;
  const host = getPeersHost();
  await host.watch(put).catch(() => undefined);
  const list = await host.list().catch(() => [] as PeerStatus[]);
  for (const st of list) put(st);
  // the bridge restarted (an app retry) or the UI reconnected: attach again what is up
  getStore().subscribe(() => {
    const conn = getStore().getState().conn;
    if (conn !== "open") attached.clear();
  });
  let last = getStore().getState().conn;
  getStore().subscribe(() => {
    const conn = getStore().getState().conn;
    if (conn === "open" && last !== "open") for (const st of peers) void sync(st);
    last = conn;
  });
}

export const peerList = () => peers;

/** Every remote machine and its link state; re-renders on a change. */
export function usePeers(): PeerStatus[] {
  useEffect(() => {
    void startPeers();
  }, []);
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => peers,
    () => peers,
  );
}

/** One peer's link state by id. */
export function usePeer(id: string | undefined): PeerStatus | undefined {
  return usePeers().find((p) => p.id === id);
}

/** Settings' Remove: the shell drops the row and stops the link; the bridge lets its bots go. */
export async function removePeer(id: string): Promise<void> {
  await getPeersHost().remove(id);
}

export async function retryPeer(id: string): Promise<void> {
  await getPeersHost().retry(id);
}

/** e2e only (mock host): put a link in a state, as the shell would report it. */
export function mockPeerState(id: string, patch: Partial<PeerStatus>): void {
  const h = getPeersHost() as unknown as { set?: (id: string, p: Partial<PeerStatus>) => void };
  h.set?.(id, patch);
}
if (typeof window !== "undefined") (window as unknown as { __omherPeerState?: typeof mockPeerState }).__omherPeerState = mockPeerState;
