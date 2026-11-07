# Composing with Hermes' Debugging Skills

Hermes bundles `systematic-debugging` (MIT, adapted from obra/superpowers), a four-phase root-cause method. Two debugger guides, `python-debugpy` for pdb and debugpy and `node-inspect-debugger` for Node's inspector, are optional official skills that are not active unless installed; check `skills_list`, and when one is absent use `pdb` or `node inspect` directly as an observation. When one of them is loaded beside `app-debugging`, follow its method; this skill adds its records and its gates, never a second method.

## `systematic-debugging`, phase by phase

| Its phase | What this skill records there |
| --- | --- |
| Root cause investigation, around one tight command that goes red on the symptom | `reproduction_record/v1`: the command, its observed output, the hit rate over N runs, `symptom_match`, `loop_cost`, and the `minimised` form |
| Pattern analysis | nothing of its own; working examples and differences feed the hypotheses |
| Hypothesis and testing | `competing_hypotheses/v1` with at least three hypotheses on distinct axes, then `discriminating_observation_plan/v1`, then `root_cause_record/v1` citing the observation that decided it |
| Implementation | `fix_handoff/v1`, still blocked until the reproduction reads observed, then `observed_fix_verification/v1` |

Both skills stop after three failed fixes and question the architecture instead of trying a fourth. Count failures by this skill's rule: the same reproduction command, executed, still showing the symptom or a new one the fix caused.

## The debuggers are observations

- A breakpoint stop, a stepped call, or a post-mortem frame is one discriminating observation: record what it showed and which hypotheses it ruled out, as for a log line.
- Stopping at a breakpoint changes timing. For a hypothesis about ordering or timing, a bug that does not appear under the debugger is still open; observe the interleaving another way, such as a log of it or a forced order.
- Attaching to a process that is already running acts on a live service and needs the same authority as any other command against it.

Without these skills loaded, `references/hypothesis-and-race-method.md` is the method, as before.
