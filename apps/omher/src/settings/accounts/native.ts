// What Accounts asks the desktop app (Tauri commands in src-tauri/src/accounts.rs): which coding CLIs are on
// this computer, a CLI's own login status, and the CLI's own sign-in with an account's home. In a plain browser
// (dev, e2e) there is no app: e2e injects a stand-in as `window.__omherAccountHost`; otherwise the page says
// signing in needs the desktop app and shows what the bridge read.
import type { AccountCli } from "../../lib/protocol";
import { t } from "../../i18n";

type Invoke = <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;

/** What omher keeps from a CLI's status (never its text, a token or a key). */
export interface LoginStatus {
  logged_in: boolean;
  email: string | null;
  plan: string | null;
  method: string | null;
  last_refresh?: string | null;
}

export type SignInEvent = { kind: "line"; text: string } | { kind: "exit"; code: number | null };

export interface AccountHost {
  /** Can run the CLIs' sign-in here. */
  canSignIn: boolean;
  /** cli -> on this computer, or null when unknown (the bridge's PATH check stands). */
  clis(): Promise<Partial<Record<AccountCli, boolean>> | null>;
  /** null: this CLI has no status command (or there is no app). */
  status(cli: AccountCli, account: string): Promise<LoginStatus | null>;
  signIn(cli: AccountCli, account: string, onEvent: (ev: SignInEvent) => void): Promise<number>;
  cancel(login: number): Promise<void>;
}

declare global {
  interface Window {
    __omherAccountHost?: AccountHost;
  }
}

export function isDesktop(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

async function core() {
  return (await import("@tauri-apps/api/core")) as unknown as { invoke: Invoke; Channel: new <T>() => { onmessage: (m: T) => void } };
}

const tauriHost: AccountHost = {
  canSignIn: true,
  async clis() {
    const { invoke } = await core();
    const pairs = await invoke<[AccountCli, boolean][]>("account_clis");
    return Object.fromEntries(pairs);
  },
  async status(cli, account) {
    const { invoke } = await core();
    return invoke<LoginStatus | null>("account_status", { cli, id: account });
  },
  async signIn(cli, account, onEvent) {
    const { invoke, Channel } = await core();
    const ch = new Channel<SignInEvent>();
    ch.onmessage = onEvent;
    return invoke<number>("account_login_start", { cli, id: account, onEvent: ch });
  },
  async cancel(login) {
    const { invoke } = await core();
    await invoke("account_login_cancel", { login });
  },
};

const noHost: AccountHost = {
  canSignIn: false,
  clis: async () => null,
  status: async () => null,
  signIn: async () => {
    throw new Error(t("acc.needsApp"));
  },
  cancel: async () => {},
};

export function accountHost(): AccountHost {
  if (isDesktop()) return tauriHost;
  return (typeof window !== "undefined" && window.__omherAccountHost) || noHost;
}
