// Settings > General > Appearance: theme, colour set, bubble style and text size, with a live preview.
// The choices only change how omher looks on this computer (saved in localStorage); nothing goes to Hermes.
import { useStore, PALETTES, BUBBLE_STYLES, type BubbleStyle, type Palette, type TextSize, type Theme } from "../state/store";
import { Seg } from "../chat/model/Seg";

const PALETTE_NAME: Record<Palette, string> = {
  omh: "OMH",
  graphite: "Graphite",
  ocean: "Ocean",
  forest: "Forest",
  sunset: "Sunset",
  rose: "Rose",
};
const BUBBLE_NAME: Record<BubbleStyle, string> = { soft: "Soft", solid: "Solid", open: "Open" };
const BUBBLE_HINT: Record<BubbleStyle, string> = {
  soft: "Both sides in quiet tinted bubbles",
  solid: "Your messages in the accent colour",
  open: "The bot writes on the page; only you are in bubbles",
};
const THEMES: { value: Theme; label: string }[] = [
  { value: "system", label: "System" },
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
];
const SIZES: { value: TextSize; label: string }[] = [
  { value: "small", label: "Small" },
  { value: "medium", label: "Medium" },
  { value: "large", label: "Large" },
];

export function Appearance() {
  const s = useStore();
  const look = s.ui.look;
  return (
    <div className="ap" data-testid="appearance">
      <div className="ap-preview" aria-hidden="true" data-testid="appearance-preview">
        <div className="msg u">
          <div className="b">Can you check the 502s?</div>
        </div>
        <div className="msg a">
          <div className="b md">
            <p>
              Found it: expired keep-alive connections on <code>/v1/responses</code>. Details in{" "}
              <a href="#preview">the runbook</a>.
            </p>
          </div>
        </div>
        <div className="ap-pv-foot">
          <span className="ap-pv-chip">/plan</span>
          <span className="ap-pv-dot" />
          <span className="ap-pv-send">↑</span>
        </div>
      </div>

      <div className="st-grp">
        <div className="st-row">
          <div className="st-k">
            <b>Theme</b>
            <span>System follows your computer</span>
          </div>
          <div className="st-v">
            <Seg small label="Theme" value={s.ui.theme} options={THEMES} onChange={(t) => s.setTheme(t as Theme)} testId="theme-seg" />
          </div>
        </div>
        <div className="st-row ap-row-col">
          <div className="st-k">
            <b>Colour</b>
            <span>Your bubble, links, the send button and live dots. The logo keeps its colours.</span>
          </div>
          <div className="ap-sw" role="radiogroup" aria-label="Colour" data-testid="palette">
            {PALETTES.map((p) => {
              const on = look.palette === p;
              return (
                <button
                  key={p}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  className={`ap-swb${on ? " on" : ""}`}
                  onClick={() => s.setLook({ palette: p })}
                  data-testid={`palette-${p}`}
                >
                  <span className="ap-swc" data-palette={p} />
                  {PALETTE_NAME[p]}
                </button>
              );
            })}
          </div>
        </div>
        <div className="st-row">
          <div className="st-k">
            <b>Bubbles</b>
            <span data-testid="bubbles-hint">{BUBBLE_HINT[look.bubbles]}</span>
          </div>
          <div className="st-v">
            <Seg
              small
              label="Bubbles"
              value={look.bubbles}
              options={BUBBLE_STYLES.map((b) => ({ value: b, label: BUBBLE_NAME[b] }))}
              onChange={(b) => s.setLook({ bubbles: b as BubbleStyle })}
              testId="bubbles-seg"
            />
          </div>
        </div>
        <div className="st-row">
          <div className="st-k">
            <b>Text size</b>
            <span>Messages and the composer</span>
          </div>
          <div className="st-v">
            <Seg
              small
              label="Text size"
              value={look.text}
              options={SIZES}
              onChange={(t) => s.setLook({ text: t as TextSize })}
              testId="text-seg"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
