// One quiet line under an empty sidebar section ("Each bot is a Hermes profile. Add one with + above."). There is no
// first-run panel over the chat: an empty chat shows just the chat. The language still follows the system on a first
// launch (i18n `readLang`) and is changed in Settings › General.
import "./firstrun.css";

/** One muted line under an empty sidebar section. */
export function FirstRunHint({ text, testId }: { text: string; testId: string }) {
  return (
    <div className="onb-hint" data-testid={testId}>
      {text}
    </div>
  );
}
