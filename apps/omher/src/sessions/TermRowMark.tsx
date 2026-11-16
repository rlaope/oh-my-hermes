// The one icon slot of a TERMINALS row (and of a terminal's dock tile and a bottom-panel tab): the running CLI's
// official mark from the harness registry (src/harness/registry.ts through HarnessMark), or the shell icon when no CLI
// is known. `agent` is the session's `fgAgent` (the foreground CLI the shell reports in its `session-fg` event) or its
// own agent; a name the registry does not know gets the neutral mark, never another company's logo. `live` adds a
// thin ring while the program runs (still under reduced motion: the ring never moves), and the tooltip
// "<Name> running". Every mark is drawn bare at the same size, framed by the same slot, so a full-colour image mark
// (pi, omh) and a line mark (Codex, the shell) read as one set.
import { HarnessMark } from "../harness/HarnessMark";
import { harness, harnessByName } from "../harness/registry";
import { TerminalIcon } from "../ui";
import { t } from "../i18n";

/** A foreground CLI's display name: the registry's label, else the program name as the shell reported it. */
export function fgName(agent: string): string {
  const id = harnessByName(agent);
  return id && id !== "generic" ? harness(id).label : agent;
}

export function TermRowMark({ agent, live = false, size = 16 }: { agent: string | null; live?: boolean; size?: number }) {
  const id = agent ? (harnessByName(agent) ?? "generic") : null;
  const tip = agent && live ? t("term.fgRunning", { name: fgName(agent) }) : undefined;
  return (
    <span
      className={`trm${live ? " live" : ""}`}
      data-testid="term-row-mark"
      data-agent={id ?? "shell"}
      data-live={live ? "true" : undefined}
      title={tip}
      style={{ width: size, height: size }}
    >
      {id ? <HarnessMark id={id} size={size} /> : <TerminalIcon size={size} />}
    </span>
  );
}
