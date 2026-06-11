# Roadmap

## Near Term

- Package release flow
- More complete `doctor` checks
- Uninstall and snippet command tests
- Imported skill conflict fixtures
- Richer routing catalog fields
- More playbook-backed situation pipelines for wrapper UX, research, planning,
  and release flows
- More artifact-backed application cases for Hermes-hosted chat surfaces
- More fixture-backed Hermes Agent wrapper examples that consume
  `chat_interaction/v1`
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
- Richer plugin hooks and tools after observed runtime-load evidence exists

## Recently Landed

- Explicit Codex executor handoff contracts for delegation-first coding flows
- Wrapper-facing delegated coding status summaries that separate prepared
  handoff from observed execution, review, CI, and merge evidence
- Hermes-facing `chat_interaction/v1` and `chat_response/v1` contracts for
  hosted chat surfaces
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
