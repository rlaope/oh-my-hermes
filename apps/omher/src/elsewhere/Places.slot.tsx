// Header chip: "3 other places" with one source square per session; toggles the Details panel.
import type { SlotProps } from "../features";
import { useStore } from "../state/store";
import "./elsewhere.css";

export const slot = "headerPlaces";

const MAX_SQUARES = 4;

export default function Places({ bot }: SlotProps["headerPlaces"]) {
  const s = useStore();
  const away = s.elsewhere[bot.name] ?? [];
  if (away.length === 0) return null;
  const open = s.ui.panelOpen;
  return (
    <button
      type="button"
      className={`ew-places${open ? " on" : ""}`}
      onClick={() => s.togglePanel()}
      aria-expanded={open}
      title={`Where ${bot.display_name} is`}
      data-testid="places"
    >
      <span className="ew-pd" aria-hidden="true">
        {away.slice(0, MAX_SQUARES).map((a) => (
          <i key={a.id} className={`src-sq src-${a.source}`} />
        ))}
      </span>
      <span data-testid="places-label">
        {away.length} other place{away.length === 1 ? "" : "s"}
      </span>
    </button>
  );
}
