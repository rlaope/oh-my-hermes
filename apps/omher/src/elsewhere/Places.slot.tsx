// Header chip: "3 other places" with the app mark of each place the bot is in (Slack, Discord, …);
// toggles the Details panel.
import type { SlotProps } from "../features";
import { useStore } from "../state/store";
import { SourceIcon } from "../ui";
import { sourceName } from "./format";
import "./elsewhere.css";

export const slot = "headerPlaces";

export default function Places({ bot }: SlotProps["headerPlaces"]) {
  const s = useStore();
  const away = s.elsewhere[bot.name] ?? [];
  if (away.length === 0) return null;
  const open = s.ui.panelOpen;
  const sources = [...new Set(away.map((a) => a.source))];
  return (
    <button
      type="button"
      className={`ew-places${open ? " on" : ""}`}
      onClick={() => s.togglePanel()}
      aria-expanded={open}
      title={`Where ${bot.display_name} is`}
      data-testid="places"
    >
      <span className="ew-pd" title={sources.map(sourceName).join(", ")}>
        {sources.map((src) => (
          <SourceIcon key={src} source={src} size={12} />
        ))}
      </span>
      <span data-testid="places-label">
        {away.length} other place{away.length === 1 ? "" : "s"}
      </span>
    </button>
  );
}
