// The one icon slot of a TERMINALS row (and of a terminal's dock tile): the running CLI's official mark from the
// harness registry (src/harness/registry.ts through HarnessMark), or the shell icon when no CLI is known. `agent` is
// the session's `fgAgent` (the foreground CLI the shell reports) or its own agent; a name the registry does not know
// gets the neutral mark, never another company's logo. `live` adds a thin ring while the program runs.
import { HarnessMark } from "../harness/HarnessMark";
import { harnessByName } from "../harness/registry";
import { TerminalIcon } from "../ui";

export function TermRowMark({ agent, live = false, size = 16 }: { agent: string | null; live?: boolean; size?: number }) {
  const id = agent ? (harnessByName(agent) ?? "generic") : null;
  return (
    <span className={`trm${live ? " live" : ""}`} data-testid="term-row-mark" data-agent={id ?? "shell"} data-live={live ? "true" : undefined} style={{ width: size, height: size }}>
      {id ? <HarnessMark id={id} size={size} /> : <TerminalIcon size={size} />}
    </span>
  );
}
