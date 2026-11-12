// The header's one button for the right panel, right of the model control. Closed: it opens the panel, on Plans
// when the bot has live work or when the person never picked a tab, else on the tab they used last. Open: it closes
// it. While the bot's runs have subagents at work it carries the live dot and says how many in its tooltip.
import { useStore } from "../../state/store";
import type { Bot } from "../../lib/protocol";
import { IconButton, PanelIcon } from "../../ui";
import { isMac } from "../../app/shortcuts";
import { t } from "../../i18n";
import { useBotRuns, useRunsPoll, workingCount } from "../../runs/live";

/** Set once the person picks a panel tab themselves; until then the button opens on Plans. */
export const PICKED_KEY = "omher.panelPicked";
export const tabPicked = () => {
  try {
    return typeof localStorage !== "undefined" && localStorage.getItem(PICKED_KEY) === "1";
  } catch {
    return false;
  }
};
export const markTabPicked = () => {
  try {
    if (typeof localStorage !== "undefined") localStorage.setItem(PICKED_KEY, "1");
  } catch {
    /* no storage: the button keeps opening on Plans */
  }
};

export function PanelButton({ bot }: { bot: Bot }) {
  useRunsPoll(bot.name);
  return <PanelToggle working={workingCount(useBotRuns(bot.name).runs)} />;
}

/** The button itself: a bot's chat counts the subagents of its runs, a SESSIONS chat those of its own run. */
export function PanelToggle({ working: n }: { working: number }) {
  const s = useStore();
  const open = s.ui.panelOpen;
  const key = isMac() ? "⌘." : "Ctrl+.";
  const label = n > 0 ? t(n === 1 ? "head.panelLive1" : "head.panelLive", { n, key }) : t("head.panel", { key });
  return (
    <IconButton
      label={label}
      className={`head-pb${open ? " on" : ""}`}
      aria-pressed={open}
      data-testid="panel-button"
      data-working={n}
      onClick={() => {
        if (open) s.togglePanel(false);
        else if (n > 0 || !tabPicked()) s.setPanelTab("runs");
        else s.togglePanel(true);
      }}
    >
      <PanelIcon />
      {n > 0 && <i className="head-pb-dot" data-testid="panel-button-live" aria-hidden="true" />}
    </IconButton>
  );
}
