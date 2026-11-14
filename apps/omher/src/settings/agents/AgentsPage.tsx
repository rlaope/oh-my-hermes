// Settings › Agents: the agents SESSIONS offers, read-only, with their tier and whether each is installed; then the
// person's own Agent Client Protocol agents, which they add and remove here. Nothing is saved from the form: Save
// opens a confirm card that shows the exact command omher will run (the shell resolves it now), Cancel first and Add
// second, and only Add asks the shell to write the entry (src-tauri/src/custom_agents.rs). Removing asks once, then
// each open session of that agent ends.
import { useEffect, useState } from "react";
import "./agents.css";
import { AgentMark } from "../../sessions/AgentMark";
import { getHost } from "../../sessions/host";
import { getSessions, useSessions } from "../../sessions/sessions";
import { agentsPageModel, cardCommand, EMPTY_FORM, whyText, type CustomForm, type CustomList, type CustomPreview, type Tier } from "../../sessions/custom";
import { t, tx, type Key } from "../../i18n";
import { holdImeEnter } from "../../lib/ime";

const TIER: Record<Tier, Key> = { main: "ag.tierMain", acp: "ag.tierAcp", builtin: "ag.tierBuiltin" };

export function AgentsPage() {
  const ss = useSessions();
  const [custom, setCustom] = useState<CustomList | null>(null);
  const [form, setForm] = useState<CustomForm | null>(null);
  const [card, setCard] = useState<CustomPreview | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<{ id: string; label: string } | null>(null);

  const reload = async () => {
    try {
      setCustom(await getHost().customList());
    } catch (e) {
      setErr(whyText(e));
    }
  };
  useEffect(() => {
    if (ss.agents === null) void getSessions().loadAgents();
    void reload();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const m = agentsPageModel(ss.agents, custom);

  /** Save: the shell checks the fields and resolves the command; nothing is written. */
  const preview = async () => {
    if (!form) return;
    setBusy(true);
    setErr("");
    try {
      setCard(await getHost().customPreview(form.label, form.program, form.args, form.install));
    } catch (e) {
      setErr(whyText(e));
    } finally {
      setBusy(false);
    }
  };
  /** The card's Add: the one call that writes. */
  const add = async () => {
    if (!card) return;
    setBusy(true);
    try {
      await getHost().customConfirm(card.entry);
      setCard(null);
      setForm(null);
      setErr("");
      await reload();
      await getSessions().loadAgents();
    } catch (e) {
      setCard(null);
      setErr(whyText(e));
    } finally {
      setBusy(false);
    }
  };
  const remove = async (id: string) => {
    setBusy(true);
    try {
      await getHost().customRemove(id);
      setRemoving(null);
      await getSessions().endAgent(id);
      await reload();
    } catch (e) {
      setErr(whyText(e));
    } finally {
      setBusy(false);
    }
  };

  const field = (k: keyof CustomForm, label: Key, hint: Key, placeholder: string, mono = false) => (
    <div className="st-row">
      <label className="st-k" htmlFor={`ag-${k}`}>
        <b>{t(label)}</b>
        <span>{t(hint)}</span>
      </label>
      <div className="st-v">
        <input
          id={`ag-${k}`}
          className={`ag-in${mono ? " mono" : ""}`}
          value={form?.[k] ?? ""}
          placeholder={placeholder}
          spellCheck={false}
          autoComplete="off"
          autoCapitalize="off"
          onChange={(e) => setForm((f) => (f ? { ...f, [k]: e.target.value } : f))}
          data-testid={`agent-form-${k}`}
        />
      </div>
    </div>
  );

  return (
    <div className="st-page" data-testid="agents-page">
      <div className="st-gh st-gh0">{t("ag.offered")}</div>
      <div className="st-grp" data-testid="agents-builtins">
        {m.builtins.map((a) => (
          <div key={a.id} className="st-row ag-row" data-testid={`agents-row-${a.id}`}>
            <div className="st-k st-kt">
              <b className="st-kt">
                <AgentMark agent={a.id} size={16} />
                {a.label}
              </b>
            </div>
            <div className="st-v ag-meta">
              <span className={`ag-tier ${a.tier}`} data-testid={`agents-tier-${a.id}`}>
                {t(TIER[a.tier])}
              </span>
              <span className={`ag-state${a.installed ? " on" : ""}`}>{a.installed ? t("ag.installed") : t("ag.notInstalled")}</span>
            </div>
          </div>
        ))}
        {ss.agents === null && <div className="st-row ag-empty">{t("ss.lookingAgents")}</div>}
      </div>

      <div className="st-gh">{t("ag.yours")}</div>
      <p className="st-note">{t("ag.yoursHint")}</p>
      <div className="st-grp" data-testid="agents-mine">
        {m.mine.map((a) => (
          <div key={a.id} className="st-row ag-row" data-testid={`agents-mine-${a.id}`}>
            <div className="st-k">
              <b className="st-kt">
                <AgentMark agent={a.id} size={16} />
                {a.label}
              </b>
              <span className="ag-cmd" title={a.command ?? undefined}>
                {a.command ?? t("ag.notFound", { program: a.program })}
              </span>
            </div>
            <div className="st-v">
              <button type="button" className="st-btn" disabled={busy} onClick={() => setRemoving({ id: a.id, label: a.label })} data-testid={`agents-remove-${a.id}`}>
                {t("ag.remove")}
              </button>
            </div>
          </div>
        ))}
        {m.broken.map((b, i) => (
          <div key={`broken-${i}`} className="st-row ag-row" data-testid={`agents-broken-${b.id || i}`}>
            <div className="st-k">
              <b>{b.id ? t("ag.brokenNamed", { id: b.id }) : t("ag.broken")}</b>
              <span>{whyText(`why:${b.why}`)}</span>
            </div>
            {b.id && (
              <div className="st-v">
                <button type="button" className="st-btn" disabled={busy} onClick={() => setRemoving({ id: b.id, label: b.id })} data-testid={`agents-remove-${b.id}`}>
                  {t("ag.remove")}
                </button>
              </div>
            )}
          </div>
        ))}
        {custom && m.mine.length === 0 && m.broken.length === 0 && !form && <div className="st-row ag-empty">{t("ag.none")}</div>}
        {!form && (
          <div className="st-row ag-addrow">
            <button type="button" className="st-btn" onClick={() => (setForm({ ...EMPTY_FORM }), setErr(""))} data-testid="agents-add">
              {t("ag.add")}
            </button>
          </div>
        )}
      </div>

      {removing && (
        <div className="ag-confirm" role="alertdialog" aria-label={t("ag.removeTitle")} data-testid="agents-remove-confirm">
          <span>{tx("ag.removeConfirm", { name: <b>{removing.label}</b> })}</span>
          <button type="button" className="st-btn" onClick={() => setRemoving(null)} data-testid="agents-remove-cancel">
            {t("ag.cancel")}
          </button>
          <button type="button" className="st-btn ag-danger" disabled={busy} onClick={() => void remove(removing.id)} data-testid="agents-remove-yes">
            {t("ag.remove")}
          </button>
        </div>
      )}

      {form && (
        <>
          <div className="st-gh">{t("ag.addTitle")}</div>
          <form
            className="st-grp"
            data-testid="agent-form"
            onKeyDown={holdImeEnter}
            onSubmit={(e) => {
              e.preventDefault();
              void preview();
            }}
          >
            {field("label", "ag.name", "ag.nameHint", "Cursor Agent")}
            {field("program", "ag.program", "ag.programHint", "cursor-agent", true)}
            {field("args", "ag.args", "ag.argsHint", "acp", true)}
            {field("install", "ag.install", "ag.installHint", "npm install -g …", true)}
            <div className="st-row ag-formfoot">
              <span className="ag-quiet" data-testid="agent-form-nokeys">
                {t("ag.noKeys")}
              </span>
              <span className="ag-acts">
                <button type="button" className="st-btn" onClick={() => (setForm(null), setErr(""))} data-testid="agent-form-cancel">
                  {t("ag.cancel")}
                </button>
                <button type="submit" className="st-btn ag-primary" disabled={busy || !form.label.trim() || !form.program.trim()} data-testid="agent-form-save">
                  {t("ag.save")}
                </button>
              </span>
            </div>
          </form>
        </>
      )}
      {err && (
        <p className="ag-err" role="status" data-testid="agents-error">
          {err}
        </p>
      )}

      {card && (
        <div className="ag-scrim" onClick={() => setCard(null)}>
          <div
            className="ag-card"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="ag-card-t"
            data-testid="agent-confirm"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.key === "Escape" && setCard(null)}
          >
            <b id="ag-card-t">{t("ag.cardTitle", { name: card.entry.label })}</b>
            <p>{t("ag.cardRuns")}</p>
            <code className={`ag-card-cmd${card.command ? "" : " missing"}`} data-testid="agent-confirm-command">
              {cardCommand(card)}
            </code>
            <p className="ag-quiet">{t("ag.cardFolder")}</p>
            <p className="ag-quiet">{t("ag.cardApprovals")}</p>
            <div className="ag-acts">
              <button type="button" className="st-btn" autoFocus onClick={() => setCard(null)} data-testid="agent-confirm-cancel">
                {t("ag.cancel")}
              </button>
              <button type="button" className="st-btn ag-primary" disabled={busy} onClick={() => void add()} data-testid="agent-confirm-add">
                {t("ag.addBtn")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
