// Settings › Accounts › GitHub: the GitHub accounts Tasks › 나 reads as. gh lists the accounts it is signed in to
// (`gh auth status --json hosts`: host, login, active, state, scopes; never a token); "Add" keeps one in omher's own
// setting (host, login and a colour, src/tasks/state.ts), "Remove" takes it out of omher only (gh keeps its login).
// "Sign in to another account" opens a terminal-panel tab running gh's own `gh auth login` (`--hostname <host>` for
// GitHub Enterprise); omher types nothing into it, and asks gh for its accounts again when it ends. BOUNDARY rule 18.
import { useEffect, useState } from "react";
import { t } from "../../i18n";
import { holdImeEnter } from "../../lib/ime";
import { addGhLoginTab, GH_LOGIN_ENDED } from "../../terminal/state";
import { detectAccounts, forgetAccount, useMeData } from "../../tasks/me";
import { chooseAccount, cycleAccountColor, removeAccount, useTasks } from "../../tasks/state";
import { AccountDot } from "../../tasks/MeView";
import { accountId, type ChosenAccount, type GhAccount } from "../../tasks/types";

const HOST_RX = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;

export function GithubAccounts() {
  const tk = useTasks();
  const me = useMeData();
  const [adding, setAdding] = useState(false);
  const [host, setHost] = useState("");
  useEffect(() => {
    void detectAccounts(true);
    const again = () => void detectAccounts(true);
    window.addEventListener(GH_LOGIN_ENDED, again);
    return () => window.removeEventListener(GH_LOGIN_ENDED, again);
  }, []);
  const det = me.detected;
  const same = (a: { host: string; login: string }, b: { host: string; login: string }) => a.host === b.host && a.login.toLowerCase() === b.login.toLowerCase();
  // gh's accounts, then the chosen ones gh no longer lists
  const rows: { g: GhAccount | null; c: ChosenAccount | null; key: string }[] = [
    ...(det?.accounts ?? []).map((g) => ({ g, c: tk.accounts.find((c) => same(c, g)) ?? null, key: accountId(g) })),
    ...(det ? tk.accounts.filter((c) => !det.accounts.some((g) => same(c, g))).map((c) => ({ g: null, c, key: accountId(c) })) : []),
  ];
  const h = host.trim().toLowerCase();
  const hostOk = !h || HOST_RX.test(h);
  return (
    <section className="acc-g" data-testid="accounts-github">
      <div className="acc-gh">
        <b>{t("acc.gh.title")}</b>
      </div>
      <p className="acc-lead">{t("acc.gh.lead")}</p>
      <div className="st-grp">
        {!det ? (
          <p className="st-note">{t("acc.gh.loading")}</p>
        ) : !det.installed ? (
          <p className="st-note" data-testid="gh-missing">
            {t("acc.gh.missing")}
          </p>
        ) : rows.length === 0 ? (
          <p className="st-note" data-testid="gh-none">
            {t("acc.gh.none")}
          </p>
        ) : (
          rows.map(({ g, c, key }) => {
            const login = g?.login ?? c?.login ?? "";
            const bad = !g || g.state !== "success";
            return (
              <div className="acc-row" key={key} data-testid="gh-account-row" data-id={key} data-chosen={!!c}>
                <span className="acc-ring">
                  {c ? (
                    <button type="button" className="acc-dotbtn" aria-label={t("acc.gh.color", { login })} title={t("acc.gh.color", { login })} onClick={() => cycleAccountColor(key)} data-testid={`gh-color-${login}`}>
                      <AccountDot color={c.color} />
                    </button>
                  ) : (
                    <AccountDot color="var(--line)" />
                  )}
                </span>
                <span className="acc-who">
                  <span className="acc-n">{login}</span>
                  <span className="acc-sub">{g?.host ?? c?.host}</span>
                </span>
                {bad ? (
                  <span className="acc-pill out" title={!g ? t("acc.gh.gone") : undefined} data-testid="gh-relogin">
                    {t("tasks.me.relogin")}
                  </span>
                ) : g?.active ? (
                  <span className="acc-pill" data-testid="gh-active">
                    {t("acc.gh.active")}
                  </span>
                ) : (
                  <span />
                )}
                {c ? (
                  <button
                    type="button"
                    className="st-btn"
                    onClick={() => {
                      removeAccount(key);
                      forgetAccount(key);
                    }}
                    data-testid={`gh-remove-${login}`}
                  >
                    {t("acc.gh.remove")}
                  </button>
                ) : (
                  <button type="button" className="st-btn primary" disabled={bad} onClick={() => g && chooseAccount(g)} data-testid={`gh-add-${login}`}>
                    {t("acc.gh.add")}
                  </button>
                )}
              </div>
            );
          })
        )}
      </div>
      {det?.installed !== false && (
        <div className="acc-foot">
          {adding ? (
            <form
              className="acc-add"
              onKeyDown={holdImeEnter}
              onSubmit={(e) => {
                e.preventDefault();
                if (!hostOk) return;
                addGhLoginTab(h && h !== "github.com" ? h : null);
                setAdding(false);
                setHost("");
              }}
            >
              <input autoFocus placeholder={t("acc.gh.hostPh")} aria-label={t("acc.gh.host")} maxLength={253} value={host} onChange={(e) => setHost(e.target.value)} data-testid="gh-login-host" />
              <button type="submit" className="st-btn primary" disabled={!hostOk} data-testid="gh-login-start">
                {t("acc.gh.start")}
              </button>
              <button type="button" className="st-btn" onClick={() => setAdding(false)}>
                {t("acc.cancel")}
              </button>
            </form>
          ) : (
            <>
              <button type="button" className="acc-addbtn" onClick={() => setAdding(true)} data-testid="gh-login-another">
                {t("acc.gh.another")}
              </button>
              <button type="button" className="acc-addbtn" onClick={() => void detectAccounts(true)} data-testid="gh-check">
                {t("acc.gh.check")}
              </button>
            </>
          )}
        </div>
      )}
      {adding && <p className="acc-also">{t("acc.gh.startHint")}</p>}
    </section>
  );
}
