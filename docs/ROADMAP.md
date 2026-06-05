# Roadmap

## Near Term

- Package release flow
- More complete `doctor` checks
- Uninstall and snippet command tests
- Imported skill conflict fixtures
- Richer routing catalog fields
- More artifact-backed application cases for bot wrappers
- Example Discord/Slack adapter shims that consume `chat_interaction/v1`
- Durable plan-acceptance records for wrapper restart recovery
- First-class review, CI, and merge observation records for delegated coding
  lifecycles

## Mid Term

- File-backed workflow state beyond the current runtime metadata layer
- Generated reference docs for installed workflows
- Safer config parsing for more Hermes config shapes
- Release archives and update channels
- Golden JSON fixtures for wrapper-native chat responses and status updates
- Generalized lifecycle reporting if a second executor target is introduced

## Long Term

- Hermes-native runtime hooks if Hermes exposes a stable extension surface
- Deeper workflow telemetry that remains local and inspectable
- Plugin-style distribution if Hermes supports plugin bundles

## Recently Landed

- Explicit Codex executor handoff contracts for delegation-first coding flows
- Wrapper-facing delegated coding status summaries that separate prepared
  handoff from observed execution, review, CI, and merge evidence
- Wrapper-native `chat_interaction/v1` and `chat_response/v1` contracts for
  Discord, Slack, and hosted Hermes adapters
- Codex lifecycle helper commands over existing local runtime artifacts
