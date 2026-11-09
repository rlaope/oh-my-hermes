// Settings › Accounts: one group per coding CLI. A CLIProxyAPI group lists CPA's own auth files (read-only
// unless CPA management is on); an omher group is omher's own stack of login folders, one active at a time,
// with fill-first auto-switch. Emails are masked here and shown in full only on hover.
import { useEffect, useState } from "react";
import "./accounts.css";
import type { Account, AccountGroup } from "../../lib/protocol";
import { getStore } from "../../state/store";
import { AgentIcon, Popover } from "../../ui";
import { Seg } from "../../chat/model/Seg";
import { Ring } from "../../sidebar/Usage";
import { planText } from "../../sidebar/usageFormat";
import { CLI_NAME, CPA_LOGIN, CPA_OFF_HINT, HOME_VAR, LOGIN_CMD, accountName, autoSwitchOn, maskEmail, setAutoSwitch, stateChip } from "./rules";
import { reloadAccounts, useAccounts } from "./useAccounts";
import { cpaKeyPresent, cpaKeySet, cpaSend, isDesktop } from "./native";

const errText = (e: unknown) => (typeof e === "object" && e && "message" in e ? String((e as { message: unknown }).message) : String(e));
const NOTE_MS = 8000;

export function AccountsPage() {
  const { groups, error, note } = useAccounts();
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
  return (
    <div className="st-page acc" data-testid="accounts-page">
      <div className="st-gh st-gh0">Accounts</div>
      <p className="st-note">Stack your logins per coding CLI and switch in one click. omher never reads or shows tokens.</p>
      {error && <p className="st-note">Could not read accounts: {error}</p>}
      {groups === null && !error && <p className="st-note">Loading…</p>}
      {groups?.length === 0 && <p className="st-note">No coding CLI found on this computer (Claude Code, Codex, Grok, Gemini CLI).</p>}
      {groups?.map((g) =>
        g.backend === "cpa" ? (
          <CpaGroup key={g.cli} g={g} />
        ) : (
          <OmherGroup key={g.cli} g={g} note={fresh && note.cli === g.cli ? note.text : null} />
        ),
      )}
    </div>
  );
}

function GroupHead({ g, children }: { g: AccountGroup; children?: React.ReactNode }) {
  return (
    <div className="acc-gh">
      <AgentIcon id={g.cli} size={14} />
      <b>{CLI_NAME[g.cli]}</b>
      <span className="acc-src">{g.backend === "cpa" ? "CLIProxyAPI" : "omher"}</span>
      <span className="acc-gh-r">{children}</span>
    </div>
  );
}

function Who({ a, i }: { a: Account; i: number }) {
  const name = a.email ? maskEmail(a.email) : accountName(a, i);
  return (
    <span className="acc-who" title={a.email || undefined} data-testid="account-name">
      <span className="acc-n">{name}</span>
      {a.label && a.email && <span className="acc-sub">{a.label}</span>}
    </span>
  );
}

function Chip({ a }: { a: Account }) {
  return (
    <span className={`acc-chip st-${a.state}`} data-testid="account-state">
      {stateChip(a, Date.now() / 1000)}
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
      <Popover open={open} onClose={() => setOpen(false)} width={168} label={label} className="acc-pop">
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

// ---- CLIProxyAPI ----------------------------------------------------------------------------

function CpaGroup({ g }: { g: AccountGroup }) {
  const cpa = g.cpa!;
  const [hasKey, setHasKey] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  useEffect(() => {
    if (cpa.management) void cpaKeyPresent().then(setHasKey, () => setHasKey(false));
  }, [cpa.management]);
  const canWrite = cpa.management && isDesktop() && hasKey;

  const act = async (action: "disable" | "enable" | "remove", a: Account) => {
    if (action === "remove" && !window.confirm(`Remove ${maskEmail(a.email) || a.id} from CLIProxyAPI?`)) return;
    try {
      const req = await getStore().actions.cpaAction(action, a.id);
      await cpaSend(req);
      setMsg(null);
      await reloadAccounts();
    } catch (e) {
      setMsg(errText(e));
    }
  };

  return (
    <section className="acc-g" data-testid={`accounts-${g.cli}`} data-backend="cpa">
      <GroupHead g={g}>
        <span className="acc-auto" data-testid="cpa-strategy">
          Auto-switch: CPA {cpa.strategy}
        </span>
      </GroupHead>
      {!cpa.management && (
        <p className="acc-hint" data-testid="cpa-hint">
          {CPA_OFF_HINT}
        </p>
      )}
      {cpa.management && !canWrite && <KeyRow onSaved={() => setHasKey(true)} />}
      {msg && <p className="acc-hint err">{msg}</p>}
      <div className="st-grp">
        {g.accounts.map((a, i) => (
          <div className="acc-row" key={a.id} data-testid="account-row" data-state={a.state} data-readonly={!canWrite}>
            <span className="acc-ring" aria-hidden="true" />
            <Who a={a} i={i} />
            <Chip a={a} />
            {canWrite ? (
              <RowMenu
                label={`Actions for ${maskEmail(a.email) || a.id}`}
                items={[
                  a.state === "disabled" ? { label: "Enable", on: () => void act("enable", a) } : { label: "Disable", on: () => void act("disable", a) },
                  { label: "Remove", on: () => void act("remove", a), danger: true },
                ]}
              />
            ) : (
              <span className="acc-dots-ph" />
            )}
          </div>
        ))}
      </div>
      <div className="acc-foot">
        <button type="button" className="st-btn" onClick={() => setAdding((v) => !v)} data-testid={`add-account-${g.cli}`}>
          + Add account
        </button>
        {adding && (
          <span className="acc-cmd" data-testid="cpa-add-hint">
            Run <code>{CPA_LOGIN[g.cli]}</code> in a terminal; CPA picks it up.
          </span>
        )}
      </div>
    </section>
  );
}

function KeyRow({ onSaved }: { onSaved: () => void }) {
  const [v, setV] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (!isDesktop()) return <p className="acc-hint">CPA management is on. Managing it needs the desktop app.</p>;
  return (
    <form
      className="acc-key"
      onSubmit={(e) => {
        e.preventDefault();
        cpaKeySet(v).then(
          () => {
            setV("");
            onSaved();
          },
          (x) => setErr(errText(x)),
        );
      }}
    >
      <input
        type="password"
        autoComplete="off"
        placeholder="CPA management key"
        aria-label="CPA management key"
        value={v}
        onChange={(e) => setV(e.target.value)}
      />
      <button type="submit" className="st-btn" disabled={!v.trim()}>
        Save to keychain
      </button>
      {err && <span className="acc-hint err">{err}</span>}
    </form>
  );
}

// ---- omher stacks -----------------------------------------------------------------------------

function OmherGroup({ g, note }: { g: AccountGroup; note: string | null }) {
  const [auto, setAuto] = useState(() => autoSwitchOn(g.cli));
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [added, setAdded] = useState<{ id: string; dir: string } | null>(null);
  const [confirm, setConfirm] = useState<Account | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const s = getStore().actions;

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setMsg(null);
      await reloadAccounts();
    } catch (e) {
      setMsg(errText(e));
    }
  };

  return (
    <section className="acc-g" data-testid={`accounts-${g.cli}`} data-backend="omher">
      <GroupHead g={g}>
        <span className="acc-auto">Auto-switch</span>
        <Seg
          small
          label={`Auto-switch ${CLI_NAME[g.cli]}`}
          value={auto ? "on" : "off"}
          options={[
            { value: "on", label: "On" },
            { value: "off", label: "Off" },
          ]}
          onChange={(v) => {
            setAutoSwitch(g.cli, v === "on");
            setAuto(v === "on");
          }}
          testId={`autoswitch-${g.cli}`}
        />
      </GroupHead>
      {note && (
        <div className="acc-toast" role="status" data-testid="accounts-toast">
          {note}
        </div>
      )}
      {msg && <p className="acc-hint err">{msg}</p>}
      <div className="st-grp">
        {g.accounts.map((a, i) => (
          <div className="acc-row" key={a.id} data-testid="account-row" data-id={a.id} data-state={a.state}>
            <span className="acc-ring">{a.usage ? <Ring p={a.usage} /> : null}</span>
            <Who a={a} i={i} />
            {a.usage?.plan && <span className="acc-plan">{planText(a.usage.plan)}</span>}
            <Chip a={a} />
            <RowMenu
              label={`Actions for ${accountName(a, i)}`}
              items={[
                { label: "Make active", on: () => void run(() => s.setActiveAccount(g.cli, a.id)), disabled: a.state === "active" },
                { label: "Re-login", on: () => setAdded({ id: a.id, dir: a.dir ?? "" }) },
                ...(a.id === "default" ? [] : [{ label: "Remove…", on: () => setConfirm(a), danger: true }]),
              ]}
            />
          </div>
        ))}
      </div>
      {confirm && (
        <div className="acc-confirm" role="alertdialog" aria-label="Remove account" data-testid="remove-confirm">
          <span>
            Remove <b>{accountName(confirm, g.accounts.indexOf(confirm))}</b>? This deletes its folder <code>{confirm.dir}</code>.
          </span>
          <button type="button" className="st-btn danger" onClick={() => void run(() => s.removeAccount(g.cli, confirm.id)).then(() => setConfirm(null))}>
            Remove
          </button>
          <button type="button" className="st-btn" onClick={() => setConfirm(null)}>
            Cancel
          </button>
        </div>
      )}
      <div className="acc-foot">
        {adding ? (
          <form
            className="acc-add"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                setAdded(await s.addAccount(g.cli, label));
                setLabel("");
                setAdding(false);
              });
            }}
          >
            <input
              autoFocus
              placeholder="Name (e.g. Work)"
              aria-label="Account name"
              maxLength={40}
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              data-testid={`add-label-${g.cli}`}
            />
            <button type="submit" className="st-btn" data-testid={`add-confirm-${g.cli}`}>
              Add
            </button>
            <button type="button" className="st-btn" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <button type="button" className="st-btn" onClick={() => setAdding(true)} data-testid={`add-account-${g.cli}`}>
            + Add account
          </button>
        )}
      </div>
      {added && (
        <div className="acc-login" data-testid="login-hint">
          <span>Run login in a new session:</span>
          <code>
            {added.dir ? `${HOME_VAR[g.cli]}=${added.dir} ` : ""}
            {LOGIN_CMD[g.cli]}
          </code>
          <button type="button" className="acc-x" aria-label="Close" onClick={() => setAdded(null)}>
            ×
          </button>
        </div>
      )}
    </section>
  );
}
