// A bot's messaging platforms in front of the person: a small state in its sidebar row when a platform is known not
// to be connected (words and a mark, never colour alone), and a section of its page with each platform's state, since
// when, why in plain words, Hermes' own words, and the fix. Read-only (BOUNDARY rule 43): the fix is text, a link the
// person opens and Hermes' restart command to copy; omher runs none of it and changes nothing here.
import type { Bot, PlatformState, PlatformsRead } from "../lib/protocol";
import { useStore } from "../state/store";
import { t } from "../i18n";
import { Spinner } from "../ui";
import { openExternal } from "../lib/openExternal";
import { CopyButton } from "../chat/parts/Copy";
import { DISCORD_PORTAL, NOT_CONNECTED, fixSteps, platformName, rowWords, statusWords, whenText, whyWords, type FixStep } from "./platforms";
import "./platforms.css";

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
export function PlatformsBody({ bot, read }: { bot: Bot; read: PlatformsRead | null }) {
  const mine = read?.bots[bot.name];
  const rows = mine?.platforms ?? [];
  // "no platform" only when OMH reported this bot and the logs its lines can be in were read (or are not there)
  const blind = read?.available && (!mine || (rows.length === 0 && mine.log !== "read" && mine.log !== "missing"));
  return (
    <>
      <div className="st-gh">{t("pf.title")}</div>
      <div className="st-grp bp-grp" data-testid="bp-platforms">
        {bot.host ? (
          <p className="bp-empty">{t("pf.remote")}</p>
        ) : read === null ? (
          <div className="bp-empty">
            <Spinner size={12} label={t("id.loading")} />
          </div>
        ) : !read.available ? (
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
              <PlatformItem key={p.platform} p={p} bot={bot.name} />
            ))}
          </ul>
        )}
        {!bot.host && read?.available && <p className="bp-note">{t("pf.source")}</p>}
      </div>
    </>
  );
}

export function PlatformItem({ p, bot }: { p: PlatformState; bot: string }) {
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
            <Step key={i} step={step} />
          ))}
        </ol>
      )}
    </li>
  );
}

function Step({ step }: { step: FixStep }) {
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
      {step.gateway && <span className="pf-host">{t("pf.fix.host", { gateway: step.gateway })}</span>}
    </li>
  );
}
