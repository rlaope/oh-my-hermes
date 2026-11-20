# Vendor harness review (2026-11-20)

Each model vendor's own coding client carries a prompt, a tool contract, and
a model catalog. This page records what seven of those clients say, which
pieces OMH already has, and which it adopts. The summary and the per-model
facts are in [MODEL_OPTI.md](../MODEL_OPTI.md), section "Techniques compared
(vendor harness snapshots, 2026-11-20)". This page holds the per-vendor
tables and the follow-up list.

## Sources

Every source is labelled **official-client**: it is the vendor's own client,
pinned to a tag and commit or to a binary hash. The snapshots are kept outside
this repository. Vendor text is never copied into OMH.

| vendor | client and ref | licence |
| --- | --- | --- |
| OpenAI | Codex CLI, openai/codex `rust-v0.169.1` @ `c376cf7396eff83ce4c6ac61b9553df142e7a0be` (diff base `rust-v0.169.0` @ `d32063f9`) | Apache-2.0 |
| Anthropic | Claude Code 2.1.329, binary sha256 `8c1729568b19cdadedd0a978bf692f9f279ef554c8a333c4e132b94fd8725550` (diff base 2.1.327, sha256 `76d48205c926c8a6978cfc2171b631bcd01e20bbadd085638bb2ec57bea91c5b`) | proprietary: paraphrased only, cited by version and hash |
| Google | Gemini CLI, google-gemini/gemini-cli `v0.70.0` @ `8468962e` | Apache-2.0 |
| Alibaba | Qwen Code, QwenLM/qwen-code `v0.28.0` @ `895dfca8` | Apache-2.0 |
| Moonshot | Kimi CLI (legacy, archived), MoonshotAI/kimi-cli `1.52.0` @ `9ab1286b` | Apache-2.0 |
| Z.ai | ZCode, zai-org/ZCode `v3.18.2` @ `fec97590` | Apache-2.0 |
| DeepSeek | DeepSeek Harness, deepseek-ai/deepseek-harness `master` @ `2e39e704` (2026-11-18). This re-read covers only the policy and prompt deltas since the `3a46bd6` review. | MIT |

Grok has no row because xAI publishes no harness source. Kimi's maintained
successor, MoonshotAI/kimi-code (MIT), is follow-up 6.

Codex's tool list is not a static file. It is rebuilt from the Rust source,
and 17 of its descriptions are assembled at runtime, so those are cited as
templates. Claude Code's main prompt is likewise assembled at runtime from
about 40 sections, and the order of assembly was not reconstructed.

## Decision key

- **already**: OMH carries the same rule; the OMH column names where.
- **adopted**: lands in this change (docs), or is a numbered follow-up below
  when it needs a prompt-code change.
- **not adopted**: deliberately left out; the reason is in the row.
- **candidate**: recorded in MODEL_OPTI.md as unmeasured; no prompt change.

The persistence push ("keep going until done", "don't stop") is never
adopted. On 2026-09-05 a measurement on GPT-6 Astra found that one such
sentence added +5,419 tokens per instance with no change in pass rate
(MODEL_OPTI.md).

## Codex CLI 0.169.1

| item | vendor text location | OMH equivalent or gap | decision |
| --- | --- | --- | --- |
| The user's instruction outranks skill guidance | every GPT-6.x base prompt | the `gpt-6-astra` override's precedence sentence | already |
| Assume rather than stop to ask | collaboration-mode default template | the `gpt-6-astra` override; `PARENT_CLARIFICATION_PROTOCOL` | already |
| Size tests to the risk (6.2: new tests only when requested, required by the repo, or catching a specific regression) | `prompts/gpt-6.2-astra.md` L98; the older GPT-6.x prompts | the `gpt-6-astra` override's test-sizing sentence | already |
| A rejected action gets a safer alternative or shown authorisation, never a workaround | auto-review rejection instructions | `ENGINE_FOLLOW_UP_AUTHORITY_RULE` (refused escalation) | already |
| Parallelize independent calls; serialize dependent, approval or mutating ones | `prompts/gpt-6.2-astra.md` L145 | `TOOL_BATCHING_PROTOCOL` | already |
| Before calling work complete, check each deliverable against the goal; say clearly when blocked | `prompts/gpt-6.2-astra.md` L53 | `GOAL_ECHO_PROTOCOL`, `VERIFICATION_STOP_PROTOCOL`, `FAILURE_KIND_PROTOCOL` | already |
| No contrastive "X, not Y" framing | `prompts/gpt-6.2-astra.md` L17 | house reply-style rule (no staged contrasts) | already |
| When stopping for confirmation, explain why and name where the requirement came from | `prompts/gpt-6.2-astra.md` L63 | gap: `ENGINE_FOLLOW_UP_AUTHORITY_RULE` names when to stop, not to cite the source of the requirement | adopted (follow-up 1) |
| Browser-use confirmation-policy tiers | `model_messages/confirmation_policies.browser_use.*` (new in 0.169.1) | gap: the browser skills' boundaries have no tiering | adopted (follow-up 5) |
| Catalog: efforts, default, context, shared base prompt, multi-agent effort | `codex-rs/models-manager/models.json` at the tag | `gpt-6.2-astra` surfaces line in MODEL_OPTI.md | adopted (this change) |
| End-to-end ownership until the completion condition; do not stop after describing what you could do | `prompts/gpt-6.2-astra.md` L45, L77 | persistence push | not adopted (measured cost, no pass gain) |
| `ultra` effort with automatic task delegation | catalog `effort_descriptions` | Codex-only rung; OMH ladders stop at `max` | not adopted |
| Compaction and summary prompts | `prompts/templates/compact/*` | host/executor surface | not adopted (outside OMH) |

## Claude Code 2.1.329 (paraphrased)

Locations are absolute byte offsets into the binary.

| item | vendor text location | OMH equivalent or gap | decision |
| --- | --- | --- | --- |
| Confirm hard-to-reverse or outward-facing actions unless durably authorised; an approval does not carry to another context | system section @300026476; "executing actions with care" @300048088 | `ENGINE_FOLLOW_UP_AUTHORITY_RULE`, `ENGINE_ENTRY_CONFIRMATION_RULE` | already |
| Report faithfully: failed checks with output, skipped steps named, verified work stated plainly | system section @300026476 | the delegated-child calibration (`src/plugin_bundle/omh/delegation_protocol.py`) | already |
| Do not move work to a weaker model on your own initiative | coordinator @296651432 | structural: routing chains pick the model, and a unit cannot | already |
| Per-model prompt variants gated on catalog capability flags | model bundle gates @287440610 | `MODEL_HIGH_EFFORT_CALIBRATIONS` resolved before the family block | already |
| Short progress updates, an end-of-turn summary sized to the change, no planning documents unless asked | output rules @300025067 | `ENGINE_CLOSING_BRIEF_RULE` | already |
| Fix the root cause; do not bypass a check (for example by skipping commit hooks) | "executing actions with care" @300048088 | gap: `FAILURE_KIND_PROTOCOL` covers denials, not a failing check | adopted (follow-up 2) |
| Passing type checks and tests prove the code, not the feature; say when a surface could not be exercised | system section @300045705 | gap: `VERIFICATION_STOP_PROTOCOL` does not separate the two | adopted (follow-up 3) |
| A delegated agent does its assignment itself and does not hand all of it to another agent | subagent prompt @297468402 | gap: the child section has no such line | adopted (follow-up 4) |
| Catalog: aliases per provider, windows, output limits, effort ladders, thinking flags | bundled catalog @287416446 | `claude` surfaces line in MODEL_OPTI.md | adopted (this change) |
| Haiku 5.5 has an early-stopping-guidance flag and a gated prompt section | catalog capability flag; system section @300034680 | the trait is documented in `claude-haiku-5-5`, and no counter ships | candidate (text not reconstructed; a keep-working push would stay out) |
| Text between tool calls may never reach the user, so the final message must stand alone | system section @300022162 | host channel surface (Hermes) | not adopted (outside OMH) |
| Security refusal scope | identity/security section @300020845 | provider and host safety surface | not adopted (outside OMH) |

## Gemini CLI 0.70.0

| item | vendor text location | OMH equivalent or gap | decision |
| --- | --- | --- | --- |
| Do not act beyond the clear scope without confirming | `prompts.test.ts.snap`:4316 | `ENGINE_FOLLOW_UP_AUTHORITY_RULE` (material scope expansion) | already |
| Non-interactive mode: do not ask the user, use best judgement | `prompts.test.ts.snap`:4164 | `PARENT_CLARIFICATION_PROTOCOL` | already |
| Model table: no Gemini 4 id, 1,048,576-token limits, thinking per alias | `packages/core/src/config/models.ts` | `gemini-4-argon` surfaces line in MODEL_OPTI.md | adopted (this change) |
| Persist through errors, backtracking to research or strategy | `prompts.test.ts.snap`:4313 | persistence push | not adopted (measured cost) |
| Always search for and update related tests after a change | `prompts.test.ts.snap`:4314 | contradicts the test-sizing rule, which Codex narrowed further in 6.2 | not adopted |
| Never log, print, or commit secrets | `prompts.test.ts.snap`:4271 | the executor's own safety prompt; OMH metadata contracts are secret-free | not adopted (executor surface) |

## Qwen Code 0.28.0

| item | vendor text location | OMH equivalent or gap | decision |
| --- | --- | --- | --- |
| Verify with the project's own test, build, lint and type-check commands | `prompts.test.ts.snap`:1032 | `VERIFICATION_STOP_PROTOCOL`; unit gates come from the brief | already |
| Report outcomes faithfully; say when a step was not run | `prompts.test.ts.snap`:1033 | delegated-child calibration | already |
| A denied tool call is not completed through another tool or shell indirection | `prompts.test.ts.snap`:1021 | `FAILURE_KIND_PROTOCOL` | already |
| No destructive shortcut to make an obstacle go away | `prompts.test.ts.snap`:1098 | gap (same as Claude Code's no-bypass line) | adopted (follow-up 2) |
| Qwen Cloud preset: `qwen4-max`, `qwen3.8-max`, `kimi-k3`, `glm-5.3`, DeepSeek rows | `providers/presets/qwencloud-standard.ts` | surfaces lines for `qwen4-max`, `kimi-k3.1-pro`, `glm`, `deepseek` | adopted (this change) |
| Keep going until the query is completely resolved | `prompts.test.ts.snap`:1142 | persistence push | not adopted (measured cost) |

## Kimi CLI 1.52.0 (archived)

| item | vendor text location | OMH equivalent or gap | decision |
| --- | --- | --- | --- |
| Be thorough in actions (test, verify), not in explanations | `agents/default/system.md`:152 | `VERIFICATION_STOP_PROTOCOL`, `ENGINE_CLOSING_BRIEF_RULE` | already |
| Ask before installing or deleting outside the working directory | `agents/default/system.md`:65 | `ENGINE_FOLLOW_UP_AUTHORITY_RULE` (unauthorised external state) | already |
| A sub-agent's last message is all the parent sees; it does not ask the end user | `agents/default/coder.yaml`:6 | `UNIT_RESULT_RETURN_PROTOCOL`, `PARENT_CLARIFICATION_PROTOCOL` | already |
| No static model table (runtime listing, `kimi-k` prefix filter) | `auth/platforms.py`:298 | `kimi-k3.1-pro` surfaces line in MODEL_OPTI.md | adopted (this change) |
| Do not give up too early | `agents/default/system.md`:158 | persistence push | not adopted (measured cost) |
| No git commit, push or other mutation unless asked | `agents/default/system.md`:54 | an OMH unit's brief owns local commits; external state is already gated | not adopted |

## ZCode 3.18.2

| item | vendor text location | OMH equivalent or gap | decision |
| --- | --- | --- | --- |
| Complete the task fully without gold-plating | `subagent/general-purpose.ts`:9 | numbered criteria as the complete checklist; no helpers beyond them (child calibration) | already |
| Confirm hard-to-reverse or outward-facing actions; approval does not carry over | `context/dynamic-sections.ts`:12 | `ENGINE_FOLLOW_UP_AUTHORITY_RULE` | already |
| GLM id → display map (22 ids, no context or effort table) | session-store migration 0021 | `glm` surfaces line in MODEL_OPTI.md | adopted (this change) |
| Do not re-read a file just edited to verify it | `tool/handlers/read.ts`:78 | executor tool description | not adopted (executor surface) |
| Resume after compaction without acknowledging or recapping | `compact/prompt.ts`:172 | host compaction surface | not adopted (outside OMH) |
| Security refusal scope | `context/sections/identity.ts`:16 | provider and host safety surface | not adopted (outside OMH) |

## DeepSeek Harness master @ 2e39e704 (deltas since 3a46bd6)

| item | vendor text location | OMH equivalent or gap | decision |
| --- | --- | --- | --- |
| Start independent delegations together; end the turn while waiting instead of polling | `snapshots/sdk/command-attachments/system-prompt.expected.md`:46 | `TOOL_BATCHING_PROTOCOL`; the armed-wait clause of `ENGINE_INTERJECTION_RESUME_RULE` | already |
| Resolve discoverable facts by inspection; ask only for user-owned choices | same file :11 | the `gpt-6-astra` assumptions sentence; `PARENT_CLARIFICATION_PROTOCOL` (blocking decisions only) | already |
| Verify by running the code or tests | `snapshots/acp/escalation-approved/system-prompt.expected.md`:5 | `VERIFICATION_STOP_PROTOCOL` | already |
| Model declarations: `deepseek-flash` / `deepseek-v4-pro`, 1,048,576 window, in-history system-prompt updates, addition-only tool updates | `packages/llm/llm-deepseek/src/models.ts` | `deepseek` surfaces line; corroborates `PROMPT_CACHE_COMPOSITION_PROTOCOL` | adopted (this change) |
| Check the exit-code marker on every shell result | same file :21 | the harness's own shell-tool output format | not adopted (executor surface) |
| Treat a compaction summary as background without restating it | `packages/compaction/compaction-basic/src/summarizer.ts`:74 | host compaction surface | not adopted (outside OMH) |

## Counts

| vendor | already | adopted (this change) | adopted (follow-up) | not adopted | candidate |
| --- | --- | --- | --- | --- | --- |
| Codex CLI 0.169.1 | 7 | 1 | 2 | 3 | 0 |
| Claude Code 2.1.329 | 5 | 1 | 3 | 2 | 1 |
| Gemini CLI 0.70.0 | 2 | 1 | 0 | 3 | 0 |
| Qwen Code 0.28.0 | 3 | 1 | 1 | 1 | 0 |
| Kimi CLI 1.52.0 | 3 | 1 | 0 | 2 | 0 |
| ZCode 3.18.2 | 2 | 1 | 0 | 3 | 0 |
| DeepSeek Harness 2e39e704 | 3 | 1 | 0 | 2 | 0 |

## Follow-ups

Each follow-up needs its own change. Every one except 6 to 8 touches a
byte-budgeted or pinned prompt surface. In that change, measure the byte
budget, regenerate the skill pack where needed, and re-pin the digests.

1. **When stopping for approval, name the source of the requirement** (Codex
   6.2 L63). Touches: `ENGINE_FOLLOW_UP_AUTHORITY_RULE` in
   `src/skills/catalog_types.py`, plus the regenerated `skills/**` and
   `agent-skills/**`.
2. **Do not bypass a failing check or take a destructive shortcut** (Claude
   Code, Qwen Code). Touches: `FAILURE_KIND_PROTOCOL` in
   `src/coding/unit_prompt_protocol.py`, inside the shared-head budget that
   `src/quality/small_model_prompt_budget.py` enforces.
3. **A passing test is evidence about the code, not the feature; name the
   surface that was not exercised** (Claude Code). Touches:
   `VERIFICATION_STOP_PROTOCOL` in `src/plugin_bundle/omh/delegation_protocol.py`.
4. **A delegated child does its assignment itself** (Claude Code). Touches:
   the child section in `src/plugin_bundle/omh/delegation_protocol.py`.
5. **Browser confirmation-policy tiers** (Codex 0.169.1). Touches: the
   `omh-browser` boundaries in `src/skills/catalog_definitions.py`.
6. **Snapshot MoonshotAI/kimi-code**, the maintained Kimi client (MIT).
   Touches: the vendor table of the maintainer's snapshot extractor. That is
   outside this repository; see `docs/MODEL-ONBOARDING.md` §2.
7. **Reconstruct and classify Claude Code's Haiku 5.5 early-stopping
   section.** If it is not a keep-working push, propose it as a `family` vs
   `optimized` pair. Touches: MODEL_OPTI.md `claude-haiku-5-5`, plus a
   calibration row only after a measurement.
8. **Dump Codex's runtime tool list** to replace the 17 templated
   descriptions. Touches: the maintainer's snapshot only. `codex debug
   prompt-input` reads the user's own config, so its output is not
   reproducible as-is.
