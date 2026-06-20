# Roadmap

## Near Term

- Package release flow
- More complete `doctor` checks
- Uninstall and snippet command tests
- Imported skill conflict fixtures
- Richer routing catalog fields
- More playbook-backed situation pipelines for wrapper UX, research, planning,
  and release flows
- More artifact-backed application case fixtures beyond the prepared G1-G10
  runbook bundle
- Broader multilingual and platform-shaped replay fixtures beyond the initial
  English/Korean G1-G10 operator corpus
- More public-site examples that mirror wrapper contracts without becoming a
  separate documentation source
- Optional `~/.hermes/plugins/omh` bridge hardening after v1 install smoke

## Mid Term

- File-backed workflow state beyond the current runtime metadata layer
- Generated reference docs for installed workflows
- Safer config parsing for more Hermes config shapes
- Tagged release archives for stable installer targets
- Generalized lifecycle reporting if a second executor target is introduced

## Long Term

- Hermes plugin enablement automation when the runtime contract is stable
- Deeper workflow telemetry that remains local and inspectable
- Richer plugin hooks and tools after enough host-observed plugin load/use
  evidence exists across real Hermes environments

## Recently Landed

- Explicit Codex executor handoff contracts for delegation-first coding flows
- Wrapper-facing delegated coding status summaries that separate prepared
  handoff from observed execution, review, CI, and merge evidence
- Hermes-facing `chat_interaction/v1` and `chat_response/v1` contracts for
  hosted chat surfaces
- Plugin-native `omh_interact` chat/session observation for Hermes-hosted
  surfaces
- Fixture-backed Hermes Agent wrapper examples that consume plugin
  `omh_interact` and render the resulting `chat_interaction/v1` without
  touching real user state
- G1-G10 use-case demo cards through `omh cases demo`, including a checked-in
  `omh_use_case_demo_collection/v1` fixture for wrapper rendering
- Release and skill-content smoke now gate those G1-G10 demo cards so route,
  action, wrapper-card, and evidence-boundary drift fails before release
- G1-G10 use-case artifact bundles through `omh cases artifact`, including
  local `.omh/use-cases/artifacts/` writes, cache-only validation, and release
  smoke coverage
- G1-G10 use-case replay through `omh cases replay`, including English/Korean
  synthetic operator fixtures and release smoke coverage for deterministic
  recommendation routing
- G1-G10 use-case readiness through `omh cases readiness`, rolling catalog,
  demo-card, artifact-bundle, replay, and optional local artifact-store states
  into one operator-facing release card
- Codex lifecycle helper commands over existing local runtime artifacts
- Wrapper session plan decisions and restart recovery for accepted handoffs
- Review, CI, merge-readiness, and merge observation records for delegated
  coding lifecycles
- Harness catalog inspection and validation through `omh harness list`,
  `omh harness inspect`, and `omh harness validate`
- GitHub Pages source for the public OMH entry point
- Situation playbooks exposed through `omh playbook list`, `inspect`, and
  `recommend`
- Default plugin distribution path through `omh setup`, with local
  import/register smoke and conservative runtime-claim boundaries
- Host-observed plugin load/use records through `omh plugin observe-host`, kept
  separate from local install smoke and from execution/review/CI evidence
- Plugin tool/hook self-observation when a Hermes host supplies bounded
  observation metadata, using the same runtime evidence boundary
