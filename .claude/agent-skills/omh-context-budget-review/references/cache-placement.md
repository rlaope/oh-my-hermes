# Cache Placement Discipline

Every major serving stack caches prompt prefixes by exact bytes: Anthropic prefix caching (explicit breakpoints, discounted reads), OpenAI automatic prefix caching, Gemini implicit caching, DeepSeek context caching. A single changed byte at position N re-bills everything at and after N. OMH never calls a provider; this card disciplines the text OMH generates and the guidance it prepares for the host.

## Placement rules

1. **Stable prefix ordering.** Assemble every instruction surface in a fixed section order, most-stable content first. Regeneration must be byte-stable: same inputs, same bytes.
2. **Volatile bytes never above the fold.** Dates, token counts, git state, status lines, and per-session values never belong in files loaded at session start; they ride the first user turn or the message tail.
3. **Changes travel as appended messages.** Mid-run skill, state, or instruction changes are appended conversation messages, never edits to the system prompt or to a session-start file — a mid-run system-prompt rewrite rebuilds the whole cache (the failure mode behind NousResearch/hermes-agent#13631 and #4319).
4. **Tool surface stays stable mid-session.** Choose the tool set at session start; avoid mid-session connect/disconnect of tool servers; prefer deferred tool loading where the host supports it; serialize tool payloads deterministically (sorted keys).
5. **Fan-outs share a byte-identical preamble.** Sibling prompts lead with the same shared bytes, unit-specific content appended after; stagger dispatch so the first request writes the cache the siblings read.

## Evidence boundary

Cache hit and creation counters are provider or host telemetry. Never claim a hit rate, a saving, or "cache-safe" as observed fact without the host's usage counters; prepared placement is prepared_not_observed.
