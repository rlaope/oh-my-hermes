// Settings › Accounts: the coding-CLI subscriptions on this computer that SESSIONS start with. One group per CLI
// found here: the CLI's own login first ("This computer"), then the ones added in omher. "+ Add account" runs the
// CLI's own sign-in with a new home folder; the browser part happens in the CLI, and omher never asks for or sees
// a token or key. Bots are not here: they are set up under Bots.
import { useEffect, useRef, useState } from "react";
import "./accounts.css";
import type { AccountGroup } from "../../lib/protocol";
import { getStore } from "../../state/store";
import { AgentIcon, Popover } from "../../ui";
import { Ring } from "../../sidebar/Usage";
import { accountHost, type LoginStatus, type SignInEvent } from "./native";
import {
  CLI_NAME,
  SIGN_IN,
  autoSwitchOn,
  cpaUsage,
  isCpa,
  mergeRow,
  pill,
  rowSub,
  rowTitle,
  setAutoSwitch,
  splitGroups,
  usageLines,
  type Row,
} from "./rules";
import { reloadAccounts, useAccounts } from "./useAccounts";
import { t, tx } from "../../i18n";
import { holdImeEnter } from "../../lib/ime";

const errText = (e: unknown) => (typeof e === "object" && e && "message" in e ? String((e as { message: unknown }).message) : String(e));
const NOTE_MS = 8000;

export function AccountsPage() {
  const { groups, error, note, onComputer, status } = useAccounts();
  const [, tick] = useState(0);
  useEffect(() => {
    void reloadAccounts();
  }, []);
  useEffect(() => {
    if (!note) return;
    const h = setTimeout(() => tick((n) => n + 1), NOTE_MS);
    return () => clearTimeout(h);
  }, [note]);
  const fresh = note && Date.now() - note.at < NOTE_MS;
  const split = groups ? splitGroups(groups, onComputer) : null;
  return (
    <div className="st-page acc" data-testid="accounts-page">
      <div className="st-gh st-gh0">{t("nav.accounts")}</div>
      <p className="acc-lead" data-testid="accounts-lead">
        {/* "Bots" opens Settings › Bots */}
        {tx("acc.headerLine", {
          bots: (
            <button type="button" className="acc-link" onClick={() => getStore().actions.openSettings("bots")} data-testid="accounts-to-bots">
              {t("set.bots")}
            </button>
          ),
        })}
      </p>
      {error && <p className="st-note">{t("acc.readFailed", { error })}</p>}
      {groups === null && !error && <p className="st-note">{t("acc.loading")}</p>}
      {split?.shown.length === 0 && <p className="st-note">{t("acc.noCli")}</p>}
      {split?.shown.map((g) => (
        <CliGroup key={g.cli} g={g} status={status} note={fresh && note.cli === g.cli ? note.text : null} />
      ))}
      {split && split.missing.length > 0 && (
        <p className="acc-missing" data-testid="accounts-missing">
          {t("acc.missing", { list: split.missing.join(t("list.sep")) })}
        </p>
      )}
    </div>
  );
}

/** "This computer · Max 20x · 5-hour limit: 62% used": source, plan (its own test id), then the first usage line. */
function SubLine({ src, plan, usage }: { src: string; plan: string; usage?: string }) {
  return (
    <span className="acc-sub">
      {src}
      {plan && (
        <>
          {src && " · "}
          <span className="acc-plan" data-testid="account-plan">
            {plan}
          </span>
        </>
      )}
      {usage && (
        <>
          {(src || plan) && " · "}
          {usage}
        </>
      )}
    </span>
  );
}

function RowMenu({ items, label }: { items: { label: string; on: () => void; disabled?: boolean; danger?: boolean }[]; label: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="acc-menu">
      <button type="button" className="acc-dots" aria-label={label} aria-expanded={open} onClick={() => setOpen((v) => !v)} data-testid="account-menu">
        ⋯
      </button>
      <Popover open={open} onClose={() => setOpen(false)} width={184} label={label} className="acc-pop">
        {items.map((it) => (
          <button
            key={it.label}
            type="button"
            className={`acc-mi${it.danger ? " danger" : ""}`}
            disabled={it.disabled}
            onClick={() => {
              setOpen(false);
              it.on();
            }}
          >
            {it.label}
          </button>
        ))}
      </Popover>
    </span>
  );
}

type SignIn = { id: string; login: number | null; lines: string[]; ending: boolean };

function CliGroup({ g, status, note }: { g: AccountGroup; status: Record<string, LoginStatus>; note: string | null }) {
  const s = getStore().actions;
  const host = accountHost();
  const [auto, setAuto] = useState(() => autoSwitchOn(g.cli));
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [signIn, setSignIn] = useState<SignIn | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<Row | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const live = useRef<SignIn | null>(null);
  live.current = signIn;

  const rows = g.accounts.map((a) => mergeRow(a, status[`${g.cli}:${a.id}`]));
  const cpaRows = rows.filter(isCpa).length;
  const now = Date.now() / 1000;
  const canAdd = SIGN_IN[g.cli] === "run" && host.canSignIn;

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setMsg(null);
      await reloadAccounts();
    } catch (e) {
      setMsg(errText(e));
    }
  };

  const finish = async (id: string) => {
    setSignIn((cur) => (cur ? { ...cur, ending: true } : cur));
    const st = await host.status(g.cli, id).catch(() => null);
    if (st?.logged_in) {
      setMsg(null);
      setSignIn(null);
      await reloadAccounts();
      return;
    }
    try {
      await s.discardAccount(g.cli, id);
    } catch {
      /* already gone, or the CLI did write a login after all: the next read shows it */
    }
    setSignIn(null);
    setMsg(t("acc.cancelled"));
    await reloadAccounts();
  };

  const start = async () => {
    setMsg(null);
    let id: string;
    try {
      id = (await s.addAccount(g.cli, label)).id;
    } catch (e) {
      setMsg(errText(e));
      return;
    }
    setAdding(false);
    setLabel("");
    const state: SignIn = { id, login: null, lines: [], ending: false };
    setSignIn(state);
    const onEvent = (ev: SignInEvent) => {
      if (ev.kind === "line") setSignIn((cur) => (cur && cur.id === id ? { ...cur, lines: [...cur.lines, ev.text].slice(-3) } : cur));
      else void finish(id);
    };
    try {
      const login = await host.signIn(g.cli, id, onEvent);
      setSignIn((cur) => (cur && cur.id === id ? { ...cur, login } : cur));
    } catch (e) {
      setMsg(errText(e));
      await s.discardAccount(g.cli, id).catch(() => {});
      setSignIn(null);
      await reloadAccounts();
    }
  };

  // CLIProxyAPI's logins are listed, never switched to: they do not count towards auto-switch
  const signedIn = rows.filter((r) => r.signedIn && !isCpa(r)).length;
  return (
    <section className="acc-g" data-testid={`accounts-${g.cli}`}>
      <div className="acc-gh">
        <span className="acc-gh-i">
          <AgentIcon id={g.cli} size={16} />
        </span>
        <b>{CLI_NAME[g.cli]}</b>
      </div>
      {note && (
        <div className="acc-toast" role="status" data-testid="accounts-toast">
          {note}
        </div>
      )}
      <div className="st-grp">
        {rows.map((r, i) => {
          const cpa = isCpa(r);
          const inUse = !cpa && r.id === g.active && r.signedIn;
          const lines = cpa ? [cpaUsage()] : usageLines(r.usage, now);
          const p = pill(r, inUse, now, rows.length - cpaRows);
          return (
            <div className="acc-row" key={r.id} data-testid="account-row" data-id={r.id} data-state={r.state} data-in-use={inUse}
              data-source={r.source ?? (r.id === "default" ? "cli" : "omher")}>
              <span className="acc-ring" title={lines.join("\n") || undefined} data-testid="account-usage">
                {r.usage && <Ring p={r.usage} />}
                <AgentIcon id={g.cli} size={16} />
              </span>
              {renaming === r.id ? (
                <RenameField
                  initial={r.label}
                  onDone={(text) => {
                    setRenaming(null);
                    if (text !== null) void run(() => s.labelAccount(g.cli, r.id, text));
                  }}
                />
              ) : (
                <span className="acc-who" data-testid="account-name">
                  <span className="acc-n">{rowTitle(r, i)}</span>
                  <SubLine src={rowSub({ ...r, plan: "" })} plan={r.plan} usage={lines[0]} />
                </span>
              )}
              {p && !cpa ? (
                <span className={`acc-pill${inUse && r.state !== "limited" ? " use" : ""}${r.signedIn ? "" : " out"}${r.state === "limited" ? " lim" : ""}`} data-testid="account-pill">
                  {p}
                </span>
              ) : (
                <span />
              )}
              {cpa ? (
                <span />
              ) : (
                <RowMenu
                  label={t("acc.actionsFor", { name: rowTitle(r, i) })}
                  items={[
                    { label: t("acc.useForNew"), on: () => void run(() => s.setActiveAccount(g.cli, r.id)), disabled: inUse || !r.signedIn },
                    { label: r.label ? t("acc.rename") : t("acc.addName"), on: () => setRenaming(r.id) },
                    ...(r.id === "default" ? [] : [{ label: t("acc.remove"), on: () => setConfirm(r), danger: true }]),
                  ]}
                />
              )}
            </div>
          );
        })}
        {signIn && (
          <div className="acc-signin" role="status" data-testid="signin-panel">
            <span className="acc-spin" aria-hidden="true" />
            <span className="acc-signin-t">
              <b>{signIn.ending ? t("acc.checking") : t("acc.finishIn", { cli: CLI_NAME[g.cli] })}</b>
              <span className="acc-sub" data-testid="signin-lines">
                {signIn.lines[signIn.lines.length - 1] ?? t("acc.starting")}
              </span>
            </span>
            <button
              type="button"
              className="st-btn"
              disabled={signIn.ending}
              onClick={() => (signIn.login !== null ? void host.cancel(signIn.login) : void finish(signIn.id))}
              data-testid="signin-cancel"
            >
              {t("acc.cancel")}
            </button>
          </div>
        )}
      </div>
      {signedIn > 1 && (
        <div className="acc-auto" data-testid={`autoswitch-row-${g.cli}`}>
          <button
            type="button"
            role="switch"
            aria-checked={auto}
            aria-label={t("acc.autoSwitchOf", { cli: CLI_NAME[g.cli] })}
            className="acc-switch"
            data-testid={`autoswitch-${g.cli}`}
            onClick={() => {
              setAutoSwitch(g.cli, !auto);
              setAuto(!auto);
            }}
          >
            <span />
          </button>
          <span>
            <b>{t("acc.autoSwitch")}</b> {t("acc.autoSwitchLine")}
          </span>
        </div>
      )}
      {g.also && (
        <p className="acc-also" data-testid="accounts-also">
          {g.also.accounts === 1 ? t("acc.also1", { name: g.also.name }) : t("acc.alsoN", { n: g.also.accounts, name: g.also.name })}
          {cpaRows > 0 && t("acc.alsoCpa")}
        </p>
      )}
      {msg && (
        <p className="acc-msg" role="status" data-testid="accounts-msg">
          {msg}
        </p>
      )}
      {confirm && (
        <div className="acc-confirm" role="alertdialog" aria-label={t("acc.removeAccount")} data-testid="remove-confirm">
          <span>{tx("acc.removeConfirm", { name: <b>{rowTitle(confirm, g.accounts.findIndex((a) => a.id === confirm.id))}</b> })}</span>
          <button type="button" className="st-btn danger" onClick={() => void run(() => s.removeAccount(g.cli, confirm.id)).then(() => setConfirm(null))}>
            {t("acc.removeBtn")}
          </button>
          <button type="button" className="st-btn" onClick={() => setConfirm(null)}>
            {t("acc.cancel")}
          </button>
        </div>
      )}
      {!canAdd && SIGN_IN[g.cli] === "session" && (
        <div className="acc-foot">
          <button
            type="button"
            className="acc-addbtn"
            disabled
            title={t("acc.addSoonTip", { cli: CLI_NAME[g.cli] })}
            data-testid={`add-account-${g.cli}`}
          >
            {t("acc.add")} <span className="nav-soon">{t("acc.soon")}</span>
          </button>
        </div>
      )}
      {canAdd && !signIn && (
        <div className="acc-foot">
          {adding ? (
            <form
              className="acc-add"
              onKeyDown={holdImeEnter}
              onSubmit={(e) => {
                e.preventDefault();
                void start();
              }}
            >
              <input
                autoFocus
                placeholder={t("acc.namePh")}
                aria-label={t("acc.name")}
                maxLength={40}
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                data-testid={`add-label-${g.cli}`}
              />
              <button type="submit" className="st-btn primary" data-testid={`add-confirm-${g.cli}`}>
                {t("acc.signIn")}
              </button>
              <button type="button" className="st-btn" onClick={() => setAdding(false)}>
                {t("acc.cancel")}
              </button>
            </form>
          ) : (
            <button type="button" className="acc-addbtn" onClick={() => setAdding(true)} data-testid={`add-account-${g.cli}`}>
              {t("acc.add")}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function RenameField({ initial, onDone }: { initial: string; onDone: (text: string | null) => void }) {
  const [v, setV] = useState(initial);
  return (
    <form
      className="acc-rename"
      onKeyDown={holdImeEnter}
      onSubmit={(e) => {
        e.preventDefault();
        onDone(v.trim());
      }}
    >
      <input
        autoFocus
        aria-label={t("acc.name")}
        placeholder={t("acc.renamePh")}
        maxLength={40}
        value={v}
        onChange={(e) => setV(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            onDone(null);
          }
        }}
        data-testid="rename-input"
      />
    </form>
  );
}
