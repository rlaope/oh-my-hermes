// A link in a message, drawn as a quiet inline chip: the service's mark and a short label for what it points
// at ("rlaope/oh-my-hermes#2657", "#docs-harness", "Meet · abc-defg-hij"), the full URL in the tooltip. A
// markdown link with its own text keeps that text, with the small mark before it. A link to anything not
// recognised (or a lookalike host) stays a plain link, shortened to its real host and path. Clicking opens
// the link through the system (the desktop app's opener; a new tab in the browser build).
import { memo, useEffect, useState, useSyncExternalStore, type MouseEvent, type ReactNode } from "react";
import { BrandIcon } from "../../ui/brandIcons";
import { PrIcon } from "../../ui/PrIcon";
import type { NodePr, PrState } from "../../lib/runs";
import type { LinkPlaces } from "../../lib/protocol";
import { openExternal } from "../../lib/openExternal";
import { getStore } from "../../state/store";
import { classifyLink, findUrls, type LinkInfo } from "./linkKinds";
import "./links.css";
import { t } from "../../i18n";

// ---- channel names the bot already knows (links.places, read once per bot) ---------------------------

const EMPTY: LinkPlaces = { slack: {}, discord: {} };
const places = new Map<string, LinkPlaces>();
const asked = new Set<string>();
const listeners = new Set<() => void>();
let version = 0;

function currentBot(): string | null {
  try {
    return getStore().getState().selectedBot;
  } catch {
    return null;
  }
}

function ask(bot: string) {
  if (asked.has(bot)) return;
  asked.add(bot);
  void getStore()
    .actions.linkPlaces(bot)
    .then((p) => {
      places.set(bot, p ?? EMPTY);
      version += 1;
      for (const f of listeners) f();
    });
}

function usePlaces(needed: boolean): LinkPlaces {
  useSyncExternalStore(
    (f) => {
      listeners.add(f);
      return () => listeners.delete(f);
    },
    () => version,
    () => version,
  );
  const bot = needed ? currentBot() : null;
  useEffect(() => {
    if (bot) ask(bot);
  }, [bot]);
  return (bot && places.get(bot)) || EMPTY;
}

/** The label with a channel name swapped in when the bot knows the channel. */
export function placedLabel(info: LinkInfo, p: LinkPlaces): string {
  if (info.service === "slack" && info.meta.channel) {
    const name = p.slack[info.meta.channel];
    if (name) return info.kind === "thread" ? t("lk.thread", { name }) : name;
  }
  if (info.service === "discord" && info.meta.channel) {
    const name = p.discord[info.meta.channel];
    if (name) return name;
  }
  return info.label;
}

// ---- the chip ------------------------------------------------------------------------------------------

function open(e: MouseEvent<HTMLAnchorElement>, url: string) {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  void openExternal(url).catch(() => {});
}

/** `children` given (a markdown link with its own text): that text after the mark. Otherwise the label. A GitHub
 * pull request whose state is known (`prState`, from the plan's own `runs.prs`) leads with GitHub's state mark. */
export const LinkChip = memo(function LinkChip({ url, children, prState }: { url: string; children?: ReactNode; prState?: PrState }) {
  const info = classifyLink(url);
  const named = !!info && (info.service === "slack" || info.service === "discord") && !children;
  const p = usePlaces(named);
  if (!info) return <a href={url} title={url} target="_blank" rel="noreferrer">{children ?? url}</a>;
  const common = {
    href: url,
    title: url,
    target: "_blank",
    rel: "noreferrer",
    "data-service": info.service,
    "data-kind": info.kind,
    onClick: (e: MouseEvent<HTMLAnchorElement>) => open(e, url),
  };
  if (info.service === "web") {
    return (
      <a {...common} className="lk-web" data-testid="link-plain">
        {children ?? info.label}
      </a>
    );
  }
  if (children !== undefined) {
    return (
      <a {...common} className="lk-text" data-testid="link-text">
        <BrandIcon service={info.service} size={12} />
        <span className="lk-u">{children}</span>
      </a>
    );
  }
  const pr = info.kind === "pr" && prState && prState !== "unknown" ? prState : null;
  return (
    <a {...common} className="lk" data-testid="link-chip" data-pr-state={pr ?? undefined}>
      {pr ? <PrIcon state={pr} size={12} /> : <BrandIcon service={info.service} size={12} />}
      <span className="lk-t">{placedLabel(info, p)}</span>
    </a>
  );
});

/** True when a markdown link's text is just its URL (a bare or autolinked URL). */
export function isBare(href: string, text: string): boolean {
  const t = text.trim();
  if (!t) return true;
  if (t === href) return true;
  const strip = (s: string) => s.replace(/^https?:\/\//, "").replace(/^mailto:/, "").replace(/\/$/, "");
  try {
    return strip(t) === strip(href) || strip(decodeURI(href)) === strip(t);
  } catch {
    return strip(t) === strip(href);
  }
}

/** Plain text (a sent message) with each http(s) URL drawn as a chip. */
export function withLinks(text: string, key = "l"): ReactNode[] {
  const urls = findUrls(text);
  if (!urls.length) return [text];
  const out: ReactNode[] = [];
  let at = 0;
  urls.forEach((u, i) => {
    out.push(text.slice(at, u.start), <LinkChip key={`${key}${i}`} url={u.url} />);
    at = u.end;
  });
  out.push(text.slice(at));
  return out;
}

const BLOCK_FIRST = 10;

/** The state of `url` when it is the node's own pull request (same repo and number) and GitHub said it. */
export function prStateFor(url: string, pr: NodePr | undefined): PrState | undefined {
  if (!pr?.state || !pr.repo) return undefined;
  const info = classifyLink(url);
  if (info?.kind !== "pr") return undefined;
  const same = `${info.meta.owner}/${info.meta.repo}`.toLowerCase() === pr.repo.toLowerCase() && Number(info.meta.number) === pr.number;
  return same ? pr.state : undefined;
}

/** A plan node's links, one chip each, under a small "Links" title: the first 10, then "Show all N". Nothing
 * when there are none. The node's own pull request shows its GitHub state, as the node's PR badge does. */
export function LinksBlock({ urls, pr }: { urls: string[]; pr?: NodePr }) {
  const [all, setAll] = useState(false);
  if (!urls.length) return null;
  const shown = all ? urls : urls.slice(0, BLOCK_FIRST);
  return (
    <div className="lk-block" data-testid="run-links">
      <div className="lk-bt">{t("lk.links")}</div>
      <div className="lk-list">
        {shown.map((u) => (
          <LinkChip key={u} url={u} prState={prStateFor(u, pr)} />
        ))}
        {shown.length < urls.length && (
          <button type="button" className="lk-more" onClick={() => setAll(true)} data-testid="run-links-more">
            {t("lk.showAll", { n: urls.length })}
          </button>
        )}
      </div>
    </div>
  );
}
