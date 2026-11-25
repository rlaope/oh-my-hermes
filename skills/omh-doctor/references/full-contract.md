# Doctor

Load this on-demand contract after the compact `doctor` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user is asking for a general product explanation rather than local health diagnostics.
- The requested change is a repository bug fix, not an installed-environment check.
- The wrapper wants to claim Hermes reload, skill execution, or plugin behavior that was not observed.
- The user is asking how Hermes Agent itself works, its built-in config keys, or upstream Hermes features with no OMH install/plugin health issue; load Hermes' bundled `hermes-agent` skill instead of this one.

## Examples

Good example:

- Prompt: doctor after omh update says setup is next but Hermes skills still look stale.
- Expected behavior: Inspect managed skills, Hermes registration, runtime state, and next repair action with explicit proof boundaries.
- Why: The issue is local installation health and needs grouped diagnostic evidence.

Bad example:

- Prompt: doctor implement a new uninstall command UX.
- Expected behavior: Route to planning or implementation instead of health diagnostics.
- Why: That is product development work, not a local health check.

## Full Input, Output, and Artifact Expectations

Required inputs:

- omh home
- Hermes home
- observed issue

Expected outputs:

- health checks
- fix guidance
- known proof boundary

Artifact expectations:

- doctor state summary when runtime artifacts are writable
