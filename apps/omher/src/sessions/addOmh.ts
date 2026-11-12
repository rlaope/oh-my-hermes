// Adding oh-my-hermes for a person who has Hermes without it: one run of the shell's fixed installer (the same
// `install_engine` the first-run screen runs; the page sends nothing but the output channel), shared by the two
// places that offer it (the SESSIONS + menu line and the first-run card), so both show the same run. A clean exit
// reads the agents again: `omh` is then found and the + row reads "oh-my-hermes" (the offer goes with it).
import { useSyncExternalStore } from "react";
import { appendLine, gateShell, type GateShell } from "../app/BridgeGate";
import { t } from "../i18n";
import { getSessions } from "./sessions";

export type AddOmhPhase = "idle" | "running" | "failed";

export interface AddOmhState {
  phase: AddOmhPhase;
  /** The installer's output, newest last. */
  lines: string[];
  /** Why it failed, in one line: the shell's refusal, else the installer's last line, else its exit code. */
  error: string | null;
}

/** The line a failed run is summed up by: the shell's own message, else the installer's last line, else the exit. */
export function failLine(lines: string[], code: number | null, refused: string | null): string {
  if (refused) return refused;
  const last = [...lines].reverse().find((l) => l.trim());
  if (last) return last.trim();
  return code === null ? t("gate.couldNotRun") : t("omh.add.exit", { code });
}

export function createAddOmh(shell: () => Promise<GateShell | null>, reload: () => Promise<void>) {
  let state: AddOmhState = { phase: "idle", lines: [], error: null };
  const fns = new Set<() => void>();
  const set = (p: Partial<AddOmhState>) => {
    state = { ...state, ...p };
    for (const f of [...fns]) f();
  };
  /** Run the installer once; a second press while it runs does nothing. */
  const run = async (): Promise<void> => {
    if (state.phase === "running") return;
    set({ phase: "running", lines: [], error: null });
    let code: number | null = null;
    let refused: string | null = null;
    try {
      const s = await shell();
      if (!s) throw new Error(t("gate.couldNotRun"));
      code = await s.install((e) => {
        if (e.kind === "line") set({ lines: appendLine(state.lines, e.text) });
      });
    } catch (e) {
      refused = e instanceof Error ? e.message : String(e);
    }
    if (code === 0 && !refused) {
      await reload();
      set({ phase: "idle", lines: [], error: null });
    } else {
      set({ phase: "failed", error: failLine(state.lines, code, refused) });
    }
  };
  return {
    getState: () => state,
    subscribe(f: () => void) {
      fns.add(f);
      return () => {
        fns.delete(f);
      };
    },
    run,
  };
}

export type AddOmh = ReturnType<typeof createAddOmh>;

let single: AddOmh | null = null;
export function getAddOmh(): AddOmh {
  if (!single) single = createAddOmh(gateShell, () => getSessions().loadAgents());
  return single;
}

export function useAddOmh(): AddOmhState {
  const a = getAddOmh();
  return useSyncExternalStore(a.subscribe, a.getState, a.getState);
}
