// Settings › Computer (BOUNDARY rule 52): whether a bot may click and type in this computer's apps through Hermes'
// `computer_use` toolset. "This computer" is read through Hermes' own `computer-use permissions status --json`; Install
// and Grant access run Hermes' own `computer-use install` and `computer-use permissions grant`. "Bots" reads each bot's
// switch from its gateway (and the profile's `agent.disabled_toolsets`, which turns it off for new sessions) and flips
// it with `hermes -p <bot> tools enable|disable computer_use`, then reads it back.
// A change reaches new threads, and a bot's main chat after the bot restarts: an open chat keeps the tools it was built
// with (Hermes rebuilds a live session's tools only by starting it over, which would drop the conversation). A bot on
// another computer, and every bot while omher uses a server, would act on that computer's screen: not set up here.
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Bot, ComputerStatus, ComputerSwitch } from "../../lib/protocol";
import { useStore } from "../../state/store";
import { useServerMode } from "../../app/remote";
import { t, type Key } from "../../i18n";
import { Avatar } from "../../ui";
import { errorLine, Toggle } from "../../pages/kit";
import { checkLook, driverActions, flipFailure, grantKey, overall, platformName, readOnReturn, switchOff } from "./computer";
import "./computer.css";

type Verb = "install" | "grant";
type Run = { kind: "check" | Verb } | { kind: "toggle"; bot: string };
type BotRead = { state: ComputerSwitch; why: string; code_focus: boolean };
type BotResult = { ok: boolean; text: string; said?: string };

const READY_WORD = { ready: "cu.ready", notReady: "cu.notReady", unknown: "cu.notKnown" } as const;
const RUNNING: Record<"check" | Verb, Key> = { check: "cu.checking", install: "cu.installing", grant: "cu.granting" };
const PRESS: Record<Verb, Key> = { install: "cu.install", grant: "cu.grant" };
/** How often the page asks again while another computer-use run (a press in another window) holds the one slot. */
const BUSY_RETRY_MS = 3000;
const FAIL_WORD: Record<"disagrees" | "unknown" | "notAsked", [Key, Key]> = {
  disagrees: ["cu.onFailed", "cu.offFailed"],
  unknown: ["cu.flipUnknown", "cu.flipUnknown"],
  notAsked: ["cu.flipNotAsked", "cu.flipNotAsked"],
};

const errCode = (e: unknown): string => String((typeof e === "object" && e && (e as { code?: unknown }).code) || "unknown");
const grantsMissing = (st: ComputerStatus | null) => !!st?.read && st.can_grant && (st.accessibility !== true || st.screen_recording !== true);

function Row({ title, hint, hintId, icon, children, testId }: {
  title: string;
  hint?: ReactNode;
  hintId?: string;
  icon?: ReactNode;
  children?: ReactNode;
  testId?: string;
}) {
  return (
    <div className="st-row" data-testid={testId}>
      <div className="st-k">
        <b className={icon ? "st-kt" : undefined}>
          {icon}
          {title}
        </b>
        {hint && <span id={hintId}>{hint}</span>}
      </div>
      {children !== undefined && <div className="st-v">{children}</div>}
    </div>
  );
}

export function ComputerPage() {
  const s = useStore();
  const remote = useServerMode().mode === "remote";
  const [status, setStatus] = useState<ComputerStatus | null>(null);
  const [statusErr, setStatusErr] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  // another computer-use run holds the bridge's one slot (an install pressed before this page opened): wait for it
  const [elsewhere, setElsewhere] = useState(false);
  const [failed, setFailed] = useState<{ verb: Verb; text: string } | null>(null);
  const [unconfirmed, setUnconfirmed] = useState(false);
  // Grant access was pressed: macOS' dialog may outlast Hermes' command, so the note stays until a read shows the grants
  const [grantAsked, setGrantAsked] = useState(false);
  const [reads, setReads] = useState<Record<string, BotRead>>({});
  const [results, setResults] = useState<Record<string, BotResult>>({});
  const local = s.bots.filter((b) => !b.host);
  // a bot that comes online (or goes offline) is read again: its switch is asked of its own gateway only
  const seen = local.map((b) => `${b.name}:${b.status}`).join(",");
  const alive = useRef(true);
  // set in the body too: a remount (StrictMode mounts twice) must not leave it false and drop every answer
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  // the run under way, for listeners that outlive the render they were made in
  const runRef = useRef<Run | null>(null);
  runRef.current = run;

  const check = async () => {
    setRun({ kind: "check" });
    setFailed(null);
    try {
      const st = await s.computerStatus();
      if (!alive.current) return;
      setStatus(st);
      setStatusErr(null);
      setElsewhere(false);
      if (!grantsMissing(st)) setGrantAsked(false);
    } catch (e) {
      if (!alive.current) return;
      if (errCode(e) === "busy") setElsewhere(true);
      else setStatusErr(errorLine(e, "Hermes"));
    }
    setRun(null);
  };

  const readBot = async (b: Bot) => {
    let r: BotRead;
    try {
      r = await s.computerBot(b.name);
    } catch {
      r = { state: "unknown", why: "unread", code_focus: false };
    }
    if (alive.current) setReads((m) => ({ ...m, [b.name]: r }));
  };

  useEffect(() => {
    if (!remote) void check();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remote]);
  useEffect(() => {
    if (remote) return;
    for (const b of local) void readBot(b);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remote, seen]);
  // a run elsewhere holds the slot: ask again until it is free, so the page needs no reload
  useEffect(() => {
    if (!elsewhere || run) return;
    const id = setTimeout(() => void check(), BUSY_RETRY_MS);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elsewhere, run]);
  // after Grant access, coming back to omher reads the grants again (the person answered macOS' dialog meanwhile)
  useEffect(() => {
    if (!grantAsked) return;
    const again = () => {
      // never during a flip, an install or a read: that run's end frees the buttons, not this read
      if (readOnReturn({ grantAsked: true, running: runRef.current !== null, visible: document.visibilityState === "visible" })) void check();
    };
    window.addEventListener("focus", again);
    document.addEventListener("visibilitychange", again);
    return () => {
      window.removeEventListener("focus", again);
      document.removeEventListener("visibilitychange", again);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grantAsked]);

  const driver = async (verb: Verb) => {
    setRun({ kind: verb });
    setFailed(null);
    setUnconfirmed(false);
    try {
      const out = await s.computerDriver(verb);
      if (out.status) setStatus(out.status);
      if (out.outcome !== "ok") setFailed({ verb, text: out.line ?? t("cu.runFailed") });
      else if (out.unconfirmed && verb === "install") setUnconfirmed(true);
      if (verb === "grant" && out.outcome === "ok") setGrantAsked(grantsMissing(out.status));
    } catch (e) {
      if (errCode(e) === "busy") setElsewhere(true);
      else setFailed({ verb, text: errorLine(e, "Hermes") });
    }
    setRun(null);
  };

  const flip = async (b: Bot, on: boolean) => {
    setRun({ kind: "toggle", bot: b.name });
    setResults(({ [b.name]: _gone, ...rest }) => rest);
    const failure = (kind: "disagrees" | "unknown" | "notAsked", said?: string): BotResult => ({
      ok: false,
      text: t(FAIL_WORD[kind][on ? 0 : 1], { bot: b.display_name }),
      said,
    });
    let r: BotResult;
    try {
      const out = await s.computerToggle(b.name, on);
      // the reason the readback gave (off because agent.disabled_toolsets names it, say), kept with the state
      setReads((m) => ({
        ...m,
        [b.name]: { state: out.state, why: out.why ?? (out.state === "unknown" ? "unread" : ""), code_focus: m[b.name]?.code_focus ?? false },
      }));
      r =
        out.outcome === "ok"
          ? { ok: true, text: t(out.state === "on" ? "cu.nowOn" : "cu.nowOff", { bot: b.display_name }) }
          : failure(flipFailure({ state: out.state }), out.line);
    } catch (e) {
      const sent = typeof e === "object" && e && (e as { sent?: unknown }).sent === false ? false : undefined;
      r = failure(flipFailure({ thrownCode: errCode(e), sent }), errorLine(e, b.display_name));
      await readBot(b);
    }
    setResults((m) => ({ ...m, [b.name]: r }));
    setRun(null);
  };

  if (remote) {
    return (
      <div className="st-page" data-testid="computer">
        <div className="st-gh st-gh0">{t("set.computer")}</div>
        <p className="st-note">{t("set.useComputerHint2")}</p>
        <p className="pg-note" data-testid="computer-remote">
          {t("cu.offRemote")}
        </p>
      </div>
    );
  }

  const read = status?.read ? status : null;
  const acts = driverActions(status);
  const busy = run !== null || elsewhere;
  const ready = overall(status);

  return (
    <div className="st-page" data-testid="computer">
      <div className="st-gh st-gh0">{t("set.computer")}</div>
      <p className="st-note">{t("set.useComputerHint2")}</p>
      <p className="st-note">{t("cu.approvals")}</p>

      <div className="st-gh">{t("cu.thisComputer")}</div>
      <div className="st-grp" data-testid="computer-this">
        {status === null ? (
          <Row
            title={statusErr && !elsewhere ? t("cu.cannotTell") : t("cu.checking")}
            hint={elsewhere ? t("cu.busyElsewhere") : (statusErr ?? undefined)}
            testId="computer-reading"
          />
        ) : !read ? (
          <Row title={t("cu.cannotTell")} hint={status.read ? undefined : status.line} testId="computer-unread" />
        ) : (
          <>
            <Row title={t("cu.platform")}>
              <span className="st-val" data-testid="computer-platform">
                {platformName(read.platform)}
              </span>
            </Row>
            {!read.platform_supported ? (
              <Row title={t("cu.unsupported", { platform: platformName(read.platform) })} testId="computer-unsupported" />
            ) : (
              <>
                <Row title={t("cu.driver")} hint={t("cu.driverHint")}>
                  <span className="st-val" data-testid="computer-driver">
                    {read.installed ? (read.version ? t("cu.installedAs", { version: read.version }) : t("cu.installed")) : t("cu.notInstalled")}
                  </span>
                </Row>
                {read.can_grant && (
                  <>
                    <Row title={t("cu.accessibility")} hint={t("cu.accessibilityHint")}>
                      <span className={`st-val cu-st ${read.accessibility === true ? "ok" : "warn"}`} data-testid="computer-accessibility">
                        {t(grantKey(read.accessibility))}
                      </span>
                    </Row>
                    <Row title={t("cu.screenRecording")} hint={t("cu.screenRecordingHint")}>
                      <span className={`st-val cu-st ${read.screen_recording === true ? "ok" : "warn"}`} data-testid="computer-screen">
                        {t(grantKey(read.screen_recording))}
                      </span>
                    </Row>
                  </>
                )}
                {read.checks.map((c, i) => {
                  const look = checkLook(c.status);
                  return (
                    <Row key={`${c.label}-${i}`} title={c.label} hint={c.message || undefined} testId="computer-check">
                      <span className={`st-val cu-st ${look.tone}`} data-testid="computer-check-state">
                        {look.key ? t(look.key) : c.status}
                      </span>
                    </Row>
                  );
                })}
                {read.error && <Row title={t("cu.hermesSaid")} hint={read.error} testId="computer-error" />}
              </>
            )}
          </>
        )}
        <div className="st-row cu-acts">
          <span className={`cu-ready ${ready}`} data-testid="computer-ready">
            {status === null ? t("cu.checking") : t(READY_WORD[ready])}
          </span>
          <span className="cu-btns">
            {acts.map((verb) => (
              <button key={verb} type="button" className="st-btn cu-pri" disabled={busy} onClick={() => void driver(verb)} data-testid={`computer-${verb}`}>
                {run?.kind === verb ? t(RUNNING[verb]) : t(PRESS[verb])}
              </button>
            ))}
            <button type="button" className="st-btn" disabled={busy} onClick={() => void check()} data-testid="computer-check-again">
              {run?.kind === "check" || elsewhere ? t("cu.checking") : t("cu.checkAgain")}
            </button>
          </span>
        </div>
      </div>
      {elsewhere && status !== null && (
        <p className="pg-note" role="status" data-testid="computer-elsewhere">
          {t("cu.busyElsewhere")}
        </p>
      )}
      {(run?.kind === "grant" || (grantAsked && grantsMissing(status))) && (
        <p className="pg-note" role="status" data-testid="computer-granting">
          {t("cu.grantDialog")}
        </p>
      )}
      {unconfirmed && (
        <p className="pg-note" role="status" data-testid="computer-unconfirmed">
          {t("cu.installUnconfirmed")}
        </p>
      )}
      {failed && (
        <div className="pg-err ap-said" role="alert" data-testid="computer-failed">
          <span>{t(failed.verb === "install" ? "cu.installFailed" : "cu.grantFailed")}</span>
          <code className="cu-said">{failed.text}</code>
        </div>
      )}

      <div className="st-gh">{t("cu.bots")}</div>
      <p className="st-note">{t("cu.when")}</p>
      <div className="st-grp" data-testid="computer-bots">
        {s.bots.map((b) => {
          const r = reads[b.name];
          const off = switchOff(b, { remote, status, state: r?.state, why: r?.why });
          const on = r?.state === "on";
          const shown = results[b.name];
          const flipping = run?.kind === "toggle" && run.bot === b.name;
          const hintId = `computer-why-${b.name}`;
          const hint = off
            ? t(off.key, off.vars)
            : flipping
              ? t("cu.changing")
              : r === undefined
                ? t("cu.reading")
                : r.why === "disabled"
                  ? t("cu.offDisabled", { bot: b.display_name })
                  : t(on ? "cu.botOn" : "cu.botOff");
          return (
            <div key={b.name} className="cu-bot" data-testid={`computer-bot-${b.name}`}>
              <Row
                title={b.display_name}
                icon={<Avatar bot={b.name} size={18} />}
                hintId={hintId}
                hint={<span data-testid={hintId}>{hint}</span>}
              >
                <Toggle
                  on={on && !off}
                  mixed={r?.state === "unknown" || (r === undefined && !off)}
                  label={t("cu.switch", { bot: b.display_name })}
                  describedBy={hintId}
                  locked={!!off}
                  disabled={!off && (r === undefined || busy)}
                  onChange={(next) => void flip(b, next)}
                  testId={`computer-switch-${b.name}`}
                />
              </Row>
              {r?.code_focus && !off && (
                <p className="cu-result pg-note" data-testid={`computer-code-focus-${b.name}`}>
                  {t("cu.codeFolders", { bot: b.display_name })}
                </p>
              )}
              {shown && (
                <div className={`cu-result ${shown.ok ? "pg-note" : "pg-err ap-said"}`} role={shown.ok ? "status" : "alert"} data-testid={`computer-result-${b.name}`}>
                  <span>{shown.text}</span>
                  {shown.said && <code className="cu-said">{shown.said}</code>}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
