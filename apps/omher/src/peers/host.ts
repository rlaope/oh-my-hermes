// The desktop shell's side of SSH peers (src-tauri/src/peers.rs): the remote machines, each link's state, Check,
// Connect and Remove. In a plain browser (dev, e2e) a mock host plays the shell with fixed answers, so the whole flow
// runs against the mock bridge; it never starts anything.
import type { BridgeEvent } from "../lib/protocol";

/** Why a link failed, as the shell sorts `ssh`'s own words (peers.rs `FailKind`). */
export type FailKind = "auth" | "host_key" | "unreachable" | "timeout" | "no_hermes" | "bad_copy" | "bridge" | "port" | "dropped" | "no_ssh";

export interface PeerStatus {
  id: string;
  label: string;
  host: string;
  port?: number;
  state: "connecting" | "connected" | "reconnecting" | "failed" | "removed";
  /** The forwarded loopback address while connected. */
  url?: string;
  kind?: FailKind;
  /** The last line ssh or the remote printed. */
  reason?: string;
  attempt: number;
}

/** What Check found: the exact command omher runs, and the remote Hermes' Python. */
export interface Found {
  python: string;
  pyver: string;
  command: string;
  script: string;
}

export interface CheckResult {
  check: string;
  url: string;
  found: Found;
}

export interface Failure {
  kind: FailKind;
  line: string;
}

export interface PeersHost {
  list(): Promise<PeerStatus[]>;
  watch(fn: (st: PeerStatus) => void): Promise<void>;
  hosts(): Promise<string[]>;
  check(host: string, port?: number): Promise<CheckResult>;
  checkClose(check: string): Promise<void>;
  add(label: string, host: string, port: number | undefined, check: string | undefined): Promise<PeerStatus>;
  remove(id: string): Promise<void>;
  retry(id: string): Promise<void>;
}

const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

class TauriPeers implements PeersHost {
  private async call<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<T>(cmd, args);
  }
  list() {
    return this.call<PeerStatus[]>("peers_list");
  }
  async watch(fn: (st: PeerStatus) => void) {
    const { Channel } = await import("@tauri-apps/api/core");
    const ch = new Channel<PeerStatus>();
    ch.onmessage = fn;
    await this.call("peers_watch", { onEvent: ch });
  }
  hosts() {
    return this.call<string[]>("peers_hosts");
  }
  check(host: string, port?: number) {
    return this.call<CheckResult>("peers_check", { host, port: port ?? null });
  }
  checkClose(check: string) {
    return this.call<void>("peers_check_close", { check });
  }
  add(label: string, host: string, port: number | undefined, check: string | undefined) {
    return this.call<PeerStatus>("peers_add", { label, host, port: port ?? null, check: check ?? null });
  }
  remove(id: string) {
    return this.call<void>("peers_remove", { id });
  }
  retry(id: string) {
    return this.call<void>("peers_retry", { id });
  }
}

/** The mock bridge's own peer: `mock.peerUrl` names a loopback URL whose bridge answers `hello` and `bots.list`
 *  (the mock serves both on its own port). Hosts that end in a failure word fail the way ssh would. */
const MOCK_HOSTS = ["mini", "build-box", "studio"];
const MOCK_FAIL: Record<string, Failure> = {
  "denied": { kind: "auth", line: "sionic@denied: Permission denied (publickey,password)." },
  "nowhere": { kind: "unreachable", line: "ssh: Could not resolve hostname nowhere: nodename nor servname provided, or not known" },
  "slow": { kind: "timeout", line: "ssh: connect to host slow port 22: Operation timed out" },
  "bare": { kind: "no_hermes", line: "" },
  "broken": { kind: "bridge", line: "ModuleNotFoundError: No module named 'websockets'" },
};

export function mockPeerUrl(): string {
  const env = (import.meta.env?.VITE_OMHER_BRIDGE as string | undefined) || "ws://127.0.0.1:5308/?token=e2e";
  return env.replace(/\?token=.*$/, `?token=${"ab".repeat(16)}`);
}

class MockPeers implements PeersHost {
  private peers: PeerStatus[] = [];
  private fns: ((st: PeerStatus) => void)[] = [];
  private seq = 0;
  constructor() {
    try {
      const saved = JSON.parse(localStorage.getItem("omher.mockPeers") || "[]") as PeerStatus[];
      this.peers = saved.map((p) => ({ ...p, state: "connected", url: mockPeerUrl(), attempt: 0 }));
    } catch {
      this.peers = [];
    }
  }
  private save() {
    localStorage.setItem("omher.mockPeers", JSON.stringify(this.peers.map(({ id, label, host, port }) => ({ id, label, host, port }))));
  }
  private tell(st: PeerStatus) {
    for (const f of this.fns) f(st);
  }
  async list() {
    return this.peers.map((p) => ({ ...p }));
  }
  async watch(fn: (st: PeerStatus) => void) {
    this.fns.push(fn);
  }
  async hosts() {
    return [...MOCK_HOSTS];
  }
  async check(host: string): Promise<CheckResult> {
    await new Promise((r) => setTimeout(r, 120));
    const word = host.split("@").pop() ?? host;
    const fail = MOCK_FAIL[word];
    if (fail) throw { ...fail, line: fail.line.replace("sionic@denied", host) };
    return {
      check: `c${++this.seq}`,
      url: mockPeerUrl(),
      found: {
        python: "/Users/sionic/.hermes/tools/python-3.14.9/bin/python3",
        pyver: "3.14.9",
        command: `ssh -o BatchMode=yes -o ConnectTimeout=10 -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -T -L 127.0.0.1:53005:127.0.0.1:41873 -- ${host} sh -c '<remote script>'`,
        script: "",
      },
    };
  }
  async checkClose() {}
  async add(label: string, host: string, port: number | undefined) {
    if (this.peers.some((p) => p.host === host)) throw new Error("that computer is already connected");
    const base = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 24) || "peer";
    let id = base;
    for (let n = 2; this.peers.some((p) => p.id === id); n++) id = `${base}-${n}`;
    const st: PeerStatus = { id, label, host, ...(port ? { port } : {}), state: "connecting", attempt: 0 };
    this.peers.push(st);
    this.save();
    setTimeout(() => {
      const up = { ...st, state: "connected" as const, url: mockPeerUrl() };
      this.peers = this.peers.map((p) => (p.id === id ? up : p));
      this.tell(up);
    }, 80);
    return st;
  }
  async remove(id: string) {
    const p = this.peers.find((x) => x.id === id);
    this.peers = this.peers.filter((x) => x.id !== id);
    this.save();
    if (p) this.tell({ ...p, state: "removed" });
  }
  async retry(id: string) {
    const p = this.peers.find((x) => x.id === id);
    if (p) this.tell({ ...p, state: "connected", url: mockPeerUrl() });
  }
  /** e2e: a link changes state (`mock.peerState` in the page). */
  set(id: string, patch: Partial<PeerStatus>) {
    const p = this.peers.find((x) => x.id === id);
    if (!p) return;
    const next = { ...p, ...patch };
    this.peers = this.peers.map((x) => (x.id === id ? next : x));
    this.tell(next);
  }
}

let host: PeersHost | null = null;
export function getPeersHost(): PeersHost {
  if (!host) {
    host = inTauri() ? new TauriPeers() : new MockPeers();
    if (!inTauri() && typeof window !== "undefined") (window as unknown as { __omherPeers?: PeersHost }).__omherPeers = host;
  }
  return host;
}

/** The failure's sentence, from its kind (the card and Settings show it in the person's language). */
export const failKey = (kind: FailKind | undefined) => `peer.fail.${kind ?? "bridge"}` as const;

export type PeerEvent = BridgeEvent;
