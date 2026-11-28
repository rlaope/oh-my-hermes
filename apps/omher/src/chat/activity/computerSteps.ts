// A computer_use step in words (BOUNDARY rule 52): its action and the app it acts in, "Clicked in Safari", "Looked at
// the screen". The bridge sends only those two (`action`, and the app as `detail`); what the bot types never reaches
// the page, so nothing here could show it.
import { t, type Key } from "../../i18n";

export const COMPUTER_TOOL = "computer_use";

/** Hermes' actions (tools/computer_use/schema.py) by the phrase each one reads as. */
const PHRASE: Record<string, string> = {
  capture: "look",
  click: "click",
  double_click: "click",
  right_click: "click",
  middle_click: "click",
  drag: "drag",
  scroll: "scroll",
  type: "type",
  set_value: "type",
  key: "key",
  wait: "wait",
  list_apps: "apps",
  list_windows: "windows",
  focus_app: "focus",
};
/** Phrases that read the same whatever app was named. */
const NO_APP = new Set(["wait", "apps", "windows"]);
/** `app` values Hermes takes for the whole screen rather than one app (tools/computer_use/schema.py): no app. */
const WHOLE_SCREEN = new Set(["screen", "desktop"]);

/** One step's line: past tense in the step list, `live` for the running line ("Clicking in Safari"). */
export function computerLine(action: string | undefined, app: string, live: boolean): string {
  const phrase = PHRASE[action ?? ""] ?? "other";
  const tense = live ? "live" : "act";
  const given = (app ?? "").trim();
  const name = WHOLE_SCREEN.has(given.toLowerCase()) ? "" : given;
  if (phrase === "focus") return name ? t(`${tense}.cu.focus` as Key, { app: name }) : t(`${tense}.cu.focusNone` as Key);
  const verb = t(`${tense}.cu.${phrase}` as Key);
  return name && !NO_APP.has(phrase) ? t("cu.in", { verb, app: name }) : verb;
}
