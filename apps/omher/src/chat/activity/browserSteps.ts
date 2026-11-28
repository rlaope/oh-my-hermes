// A browser step in words (BOUNDARY rule 53). The bridge sends a `browser_exec` call's own `# label` as its `detail`, a
// `browser_dialog` or `browser_vault` call's action as `action`, and a `browser_cdp` call's method as its `detail`; the
// code, the CDP params and the text typed into a dialog never reach the page, so nothing here could show them.
import { t, type Key } from "../../i18n";

/** The browser tools whose step reads as one sentence (`browser_cdp` reads as a verb and its method, see VERBS). */
const SENTENCE = new Set(["browser_exec", "browser_dialog", "browser_vault"]);

export const isBrowserSentence = (name: string) => SENTENCE.has(name);

/** Hermes' dialog and vault actions (tools/browser_dialog_tool.py, tools/browser_vault_tool.py) by their phrase. */
const DIALOG: Record<string, string> = { accept: "accept", dismiss: "dismiss" };
const VAULT: Record<string, string> = { list: "list", fill: "fill", save_login: "save", enter_code: "code", unlock: "unlock" };

/** One step's line: past tense in the step list, `live` for the running line. A `browser_exec` with a label reads as the
 *  label the model wrote for this step; without one, "Used the browser". */
export function browserLine(name: string, action: string | undefined, detail: string, live: boolean): string {
  const tense = live ? "live" : "act";
  if (name === "browser_exec") return (detail ?? "").trim() || t(`${tense}.br.exec` as Key);
  if (name === "browser_dialog") return t(`${tense}.br.dialog.${DIALOG[action ?? ""] ?? "other"}` as Key);
  return t(`${tense}.br.vault.${VAULT[action ?? ""] ?? "other"}` as Key);
}
