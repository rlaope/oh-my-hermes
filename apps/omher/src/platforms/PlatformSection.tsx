// A bot's messaging platforms in front of the person: a small state in its sidebar row when a platform is known not
// to be connected (words and a mark, never colour alone), and a section of its page with each platform's state, since
// when, why in plain words, Hermes' own words, and the fix. Read-only (BOUNDARY rule 43): the fix is text, a link the
// person opens and Hermes' restart command to copy; omher runs none of it and changes nothing here. A bot on another
// computer shows what that computer's own bridge read there (rule 45), and says so; when it could not say, the page
// says it cannot tell.
import type { Bot, PlatformState, PlatformsRead } from "../lib/protocol";
import { useStore } from "../state/store";
import { t, type Key } from "../i18n";
import { Spinner } from "../ui";
import { openExternal } from "../lib/openExternal";
import { CopyButton } from "../chat/parts/Copy";
import { useNow } from "../elsewhere/useNow";
import { DISCORD_PORTAL, NOT_CONNECTED, PLATFORMS_POLL_MS, botRead, fixSteps, platformName, rowDown, rowWords, statusWords, whenText, whyWords, type FixStep, type PeerWhy } from "./platforms";
import "./platforms.css";

/** The sidebar row's platforms from what OMH last said, judged against the clock: it re-renders every
 *  PLATFORMS_POLL_MS, so a reconnect crosses ROW_RECONNECT_MS onto the row with no new answer. */
export function RowPlatforms({ bot, read }: { bot: string; read: PlatformsRead | null }) {
  const now = useNow(true, PLATFORMS_POLL_MS);
  return <PlatformChip bot={bot} down={rowDown(read, bot, now)} />;
}

/** The row's state: the first platform that needs the person (else the first not connected), and how many more. */
export function PlatformChip({ bot, down }: { bot: string; down: PlatformState[] }) {
  if (!down.length) return null;
  const first = down.find((p) => p.attention) ?? down[0];
  const words = down.length > 1 ? t("pf.rowMore", { state: rowWords(first), n: down.length - 1 }) : rowWords(first);
  const bad = first.attention || first.status !== "reconnecting";
  return (
    <span
      className={`bot-pf${bad ? " bad" : ""}`}
      role="status"
      title={t("pf.rowTip", { state: words })}
      data-testid={`platform-down-${bot}`}
      data-status={first.status}
    >
      <span className="bot-pf-m" aria-hidden="true">
        !
      </span>
      <span className="bot-pf-t">{words}</span>
    </span>
  );
}

export function PlatformsSection({ bot }: { bot: Bot }) {
  return <PlatformsBody bot={bot} read={useStore().platforms} />;
}

/** The section for what was read: null while the first read is under way. */
const PEER_WHY: Record<Exclude<PeerWhy, "">, Key> = { offline: "pf.peerOffline", unread: "pf.peerUnread", unasked: "pf.peerUnasked" };

export function PlatformsBody({ bot, read }: { bot: Bot; read: PlatformsRead | null }) {
  const r = botRead(read, bot.name);
  const mine = r.entry;
  const rows = mine?.platforms ?? [];
  // "no platform" only when OMH reported this bot and the logs its lines can be in were read (or are not there)
  const blind = r.available && (!mine || (rows.length === 0 && mine.log !== "read" && mine.log !== "missing"));
  const label = bot.host?.label ?? "";
  const there = r.peer !== null;
  return (
    <>
      <div className="st-gh">{t("pf.title")}</div>
      <div className="st-grp bp-grp" data-testid="bp-platforms">
        {read === null ? (
          <div className="bp-empty">
            <Spinner size={12} label={t("id.loading")} />
          </div>
        ) : there && !r.available ? (
          <p className="bp-empty" data-testid="pf-peer-cannot-tell" data-why={r.why}>
            {t(PEER_WHY[r.why || "unread"], { label })}
          </p>
        ) : !r.available ? (
          <p className="bp-empty" data-testid="pf-unavailable">
            {t("pf.unavailable")}
          </p>
        ) : blind ? (
          <p className="bp-empty" data-testid="pf-cannot-tell">
            {mine ? t("pf.logUnread") : t("pf.notReported")}
          </p>
        ) : rows.length === 0 ? (
          <p className="bp-empty" data-testid="pf-none">
            {t("pf.none")}
          </p>
        ) : (
          <ul className="pf-list">
            {rows.map((p) => (
              <PlatformItem key={p.platform} p={p} bot={r.bare} on={there ? label : ""} />
            ))}
          </ul>
        )}
        {r.available && <p className="bp-note pf-source">{there ? t("pf.sourcePeer", { label }) : t("pf.source")}</p>}
      </div>
    </>
  );
}

/** `bot` is the profile name on its own computer; `on` names that computer for a bot on another one ("" here). */
export function PlatformItem({ p, bot, on = "" }: { p: PlatformState; bot: string; on?: string }) {
  const down = NOT_CONNECTED.has(p.status);
  const since = down ? whenText(p.since) : "";
  const why = whyWords(p);
  const steps = fixSteps(p, bot);
  const quote = (down || p.attention || p.unknown_why === "ambiguous") && p.reason;
  return (
    <li className="pf-row" data-testid={`pf-${p.platform}`} data-status={p.status}>
      <div className="pf-h">
        <b>{platformName(p.platform)}</b>
        <span className={`pf-st st-${p.status}${down ? " down" : ""}${p.attention ? " bad" : ""}`} data-testid={`pf-state-${p.platform}`}>
          {down && (
            <span className="pf-m" aria-hidden="true">
              !
            </span>
          )}
          {statusWords(p)}
        </span>
        {since && <span className="pf-since">{t("pf.since", { time: since })}</span>}
      </div>
      {why && <p className="pf-why">{why}</p>}
      {quote && (
        <p className="pf-quote" data-testid={`pf-reason-${p.platform}`}>
          <span className="pf-ql">{t("pf.hermesSays")}</span> {p.reason}
        </p>
      )}
      {down && p.guidance && p.guidance !== p.reason && (
        <p className="pf-quote" data-testid={`pf-guidance-${p.platform}`}>
          <span className="pf-ql">{t("pf.hermesGuide")}</span> {p.guidance}
        </p>
      )}
      {steps.length > 0 && (
        <ol className="pf-fix" data-testid={`pf-fix-${p.platform}`}>
          {steps.map((step, i) => (
            <Step key={i} step={step} on={on} />
          ))}
        </ol>
      )}
    </li>
  );
}

function Step({ step, on }: { step: FixStep; on: string }) {
  if (step.kind === "text") return <li>{step.text}</li>;
  if (step.kind === "portal")
    return (
      <li>
        <a
          href={DISCORD_PORTAL}
          className="bp-link"
          data-testid="pf-portal"
          onClick={(e) => {
            e.preventDefault();
            void openExternal(DISCORD_PORTAL);
          }}
        >
          {t("pf.fix.portal")}
        </a>
      </li>
    );
  return (
    <li>
      {step.lead === "then" ? t("pf.fix.restartThen") : t("pf.fix.restartMaybe")}
      <span className="pf-cmd">
        <code data-testid="pf-restart">{step.command}</code>
        <CopyButton text={() => step.command} className="pf-copy" testId="pf-copy" />
      </span>
      {on && <span className="pf-host">{t("pf.fix.onPeer", { label: on })}</span>}
      {step.gateway && <span className="pf-host">{t("pf.fix.host", { gateway: step.gateway })}</span>}
    </li>
  );
}
