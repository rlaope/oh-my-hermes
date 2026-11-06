"""Shared calibration data and exact-model -> family -> generic resolution.

Owned by the standalone stdlib-only bundle; the coding control plane re-exports
these objects. Native children apply the matching worker block at every effort;
fanout retains its high-effort gate in ``unit_prompt_protocol``. The historical
``High-effort calibration:`` text is kept byte-stable on both delivery paths.
"""

from __future__ import annotations

from typing import Final

from .hermes_delegation import _projected_model_alias, _unqualified_model_alias

# Per-family counters to the over-verification inertia of high-effort routes.
# Keyed by `model_family()` output; "generic" is the mandatory fallback so an
# unknown family never gets weaker discipline than a known one.
HIGH_EFFORT_CALIBRATIONS: Final[dict[str, str]] = {
    "gpt": (
        "High-effort calibration: your reasoning depth is for the hard parts of THIS unit, not for "
        "re-deriving settled facts. Once the decisive fact is in view, act on it; once a criterion has "
        "passed, it is settled evidence — reopen it only when new output contradicts it, never to "
        "reassure yourself."
    ),
    "claude": (
        "High-effort calibration: follow the numbered criteria as the complete checklist — do not grow "
        "the checklist mid-run, and once you have enough to act, act instead of gathering more context. "
        "Deliberate deeply only where correctness is genuinely at risk; mechanical steps run directly and "
        "the single verification pass proves them. Edit surgically rather than rewriting a file; fix "
        "only what the criteria name and report adjacent findings instead of changing them; keep scratch "
        "checks out of the repository, and commit tests only where a criterion asks for them or the repo "
        "already keeps tests for this kind of change, sized like their neighbors. Add no helpers, "
        "fallbacks, validation, flags, or shims beyond what the criteria name; when you can just change "
        "the code, change it. Every progress claim points at a tool result from this run — a failed "
        "check is reported with its output, a skipped step as skipped."
    ),
    "gemini": (
        "High-effort calibration: a claim without the tool output that proves it is not evidence — "
        "run the actual check and report from its output, never from memory. Done-sounding language "
        "before the single mandatory verification pass is a failure, not optimism, and creative "
        "expansion outside the declared boundary is a defect here, not an improvement."
    ),
    "grok": (
        "High-effort calibration: speed is your default; the numbered criteria are the brake. A fast "
        "first answer never skips the single mandatory verification pass, and a quicker path never "
        "trades away the declared boundary. When search surfaces many candidates, pick by the stated "
        "criteria once and act instead of re-querying for reassurance."
    ),
    "kimi": (
        "High-effort calibration: reserve the decompose-compare-verify loop for the genuinely hard "
        "parts; mechanical steps are low-entropy — execute them directly without enumerating "
        "alternatives. Decide each approach once and reopen it only when new output contradicts it. "
        "If you catch yourself listing options for a step no criterion distinguishes, stop analyzing "
        "and act."
    ),
    "glm": (
        "High-effort calibration: use interleaved reasoning only where it improves a tool decision: "
        "interpret each result, choose the next bounded action, and preserve prior reasoning context "
        "when the runtime exposes it — returned complete and unmodified, in its original order, as "
        "this family's preserved-thinking contract expects. The 5.3 generation cannot disable "
        "thinking, so reasoning depth is the routed effort level, never a request for no thinking. "
        "Mechanical steps need no extended plan. Keep the change goal-shaped, and let the single "
        "verification pass prove it."
    ),
    "qwen": (
        "High-effort calibration: current Qwen3-Coder is a non-thinking coding-agent model, so do not "
        "ask it to emit reasoning or thinking tags. Give the exact goal, repository state, allowed "
        "boundaries, tool schemas, and completion criteria, then follow one explicit plan. Recover "
        "from failures using observed tool output and stop after one passing verification run."
    ),
    "deepseek": (
        "High-effort calibration: treat the model version and declared thinking mode as contract "
        "fields; never apply legacy R1 prompting to every DeepSeek model. Preserve runtime-provided "
        "reasoning context across tool results only on a reasoning-capable route; otherwise use the "
        "same explicit goal, boundaries, and completion criteria without thinking tags. Edit by exact "
        "literal strings — a unique match with exact whitespace — as this family's edit training "
        "expects. Make the smallest correct change, verify once, and stop."
    ),
    "mistral": (
        "High-effort calibration: instructions are followed literally here, so the stated criteria "
        "are the whole contract — check every one even when the change looks obviously right. "
        "Concision is for the output, never for the evidence: the single mandatory verification "
        "pass runs regardless of how small the diff is."
    ),
    "llama": (
        "High-effort calibration: the serving deployment is part of the contract — tool-calling "
        "support, context limits, and output limits come from the host, not the model name. Prove a "
        "capability with a real call before depending on it, fall back to explicit step-by-step "
        "tool use when structured calling is unreliable, and stop after one passing verification run."
    ),
    "codestral": (
        "High-effort calibration: this is a code-completion specialist — work in file-scoped, "
        "concrete edits rather than open-ended investigation, keep each step's expected output "
        "small and explicit, and prove the change with the repository's own check commands instead "
        "of prose explanation."
    ),
    "solar": (
        "High-effort calibration: an efficient instruction-follower, not a long-horizon reasoner — "
        "follow the one explicit plan you were given in bounded steps instead of deriving a new "
        "one, report a missing constraint rather than inferring it, and verify once against the "
        "stated criteria before stopping."
    ),
    "generic": (
        "High-effort calibration: reserve extended reasoning for genuine ambiguity with materially "
        "different outcomes. Decide once, act, verify once against the criteria, and stop — speed is "
        "never a reason to skip the verification pass, and thoroughness is never a reason to repeat it."
    ),
}


# Calibration for the MAIN agent — the one COMPOSING the split, the unit
# prompts, and the briefings — keyed by ITS OWN model family. The user picks
# what Hermes runs on (a claude-family fable/opus, a gpt-family sol/terra, a
# gemini, a kimi, a qwen, ...), and each family fails composition differently: the
# guidance counters the composer's own defaults, never the subagents'.
# Same key set as HIGH_EFFORT_CALIBRATIONS (parity-tested) so no family gets
# subagent discipline without composer discipline, and "generic" stays the
# mandatory fallback for families the table has not met.
MAIN_AGENT_COMPOSITION_CALIBRATIONS: Final[dict[str, str]] = {
    "gpt": (
        "Composition calibration: compose outcome-first, but never compress the contract away — "
        "every unit prompt keeps its declared boundary, dependencies, numbered criteria, and the "
        "one-pass verification floor spelled out. A tighter prompt that drops a stated invariant is "
        "a worse prompt."
    ),
    "claude": (
        "Composition calibration: split only what the goal requires — no speculative units, and no unit "
        "whose only job is re-checking the split itself; a fresh-context review of a unit's deliverable "
        "against its criteria is a legitimate unit. Delegate a unit when it is independent of the work "
        "you keep and its completion can be judged from the evidence it returns; keep in line anything "
        "that finishes in a handful of tool calls. The "
        "criteria you write are a closed checklist: state them once, completely, and freeze. Your closing report is "
        "the reader's first look at the run — lead with the outcome in plain sentences, drop the "
        "working shorthand, and give the one or two things you need from them."
    ),
    "gemini": (
        "Composition calibration: compose from tool-verified facts, not recall — run the inventory "
        "and readiness commands before naming owners or models, and never describe a unit as "
        "prepared until the actual prepare command produced its artifact. A split narrated without "
        "the commands behind it is not a split."
    ),
    "kimi": (
        "Composition calibration: partitioning work is mostly low-entropy — decide the split once, "
        "freeze it, and reserve deep reasoning for boundary overlaps and dependency cycles. Do not "
        "enumerate alternative splits nobody asked for; if two partitions both satisfy the "
        "boundaries, take the first and move."
    ),
    "glm": (
        "Composition calibration: use interleaved reasoning only to interpret evidence between "
        "contract-building tools; mechanical field assembly needs no extra planning. This family "
        "rewards lean, mechanically explicit unit prompts — exact schemas and invocation rules over "
        "narrative instruction — and its tool-call formatting decays in very long contexts, so keep "
        "each unit's scope bounded rather than letting one unit sprawl. Every unit carries its owner, "
        "boundary, and known route fields. Once boundaries are clean and dependencies acyclic, freeze "
        "the smallest split that covers the goal."
    ),
    "grok": (
        "Composition calibration: pick the partition once by the stated boundaries and dispatch; "
        "re-querying for a better split is re-verifying a settled decision."
    ),
    "qwen": (
        "Composition calibration: current Qwen3-Coder is non-thinking; freeze one ordered split with "
        "exact owners, boundaries, tool contracts, dependencies, roles, and verification commands "
        "instead of requesting reasoning tags. Validate once and move to dispatch."
    ),
    "deepseek": (
        "Composition calibration: keep the DeepSeek model version and thinking mode explicit in the "
        "prepared route. Preserve runtime reasoning context only when the selected model and executor "
        "support it; otherwise compose exact owners, scopes, dependencies, and verification commands "
        "without synthetic thinking instructions. Validate once and stop."
    ),
    "mistral": (
        "Composition calibration: write unit prompts literally and completely — a Mistral-family "
        "executor follows what is written, not what was implied, so every boundary, dependency, "
        "criterion, and verification command must be stated; never rely on the unit inferring an "
        "unstated invariant."
    ),
    "llama": (
        "Composition calibration: compose for the deployment, not the brand — confirm the served "
        "variant's tool contract and context budget before assigning units, and keep each unit "
        "prompt self-contained so a host with a smaller context window still receives the full "
        "contract."
    ),
    "codestral": (
        "Composition calibration: route codestral units as narrow, file-scoped implementation "
        "slices with exact verification commands; investigation, review, and synthesis belong on a "
        "generalist lane, and a unit that mixes them belongs split."
    ),
    "solar": (
        "Composition calibration: put the depth in the composition, not the unit — give each solar "
        "unit one explicit plan with short bounded steps, exact criteria, and its verification "
        "command, because the unit will execute the plan it is given rather than derive a better one."
    ),
    "generic": (
        "Composition calibration: compose the contract fields exactly, validate the split once with "
        "the validation command, and stop — composing is preparing evidence, and a prepared "
        "contract is the only proof a split exists."
    ),
}


# Exact-model overrides, resolved BEFORE the family tables. A generation whose
# documented traits differ from its family's (GPT-6 Astra against the GPT-5.6
# guidance) gets its own counter here without touching the family block, so
# the older generation's prompts stay byte-stable. Keyed by the exact model
# id after the provider prefix is stripped (`contract_model_id`); the two
# tables share one key set (parity-tested) for the same reason the family
# tables do. Resolution order everywhere: exact model -> family -> generic.
MODEL_HIGH_EFFORT_CALIBRATIONS: Final[dict[str, str]] = {
    # GPT-6 Astra, per OpenAI's latest-model guide (2026-09): asks more
    # readily, follows instructions more strictly and pauses on conflicting
    # skill text, delegates less than a harness expects, and tests more
    # broadly than a change needs. Each sentence counters one of those; the
    # universal echo-back, criteria, one-pass verification, and repair caps
    # are not restated. No monitoring language, no chain-of-thought requests.
    "gpt-6-astra": (
        "High-effort calibration: the user's instructions outrank any skill or guideline text, and "
        "the numbered criteria are the complete task — nothing outside them is owed. Ask one focused "
        "question only when a missing input would materially change the result; otherwise state the "
        "assumption and proceed. Size tests to the change: a reversible, low-impact edit that mirrors "
        "its implementation needs no new test, and a green check is re-run only when its inputs changed."
    ),
    # GPT-6 Cyber: Astra's wording, byte for byte. The system card calls it
    # "a cyber-specialized variant of GPT-6 Astra", and its model page,
    # changelog entry, and system card give no prompting guidance, so the
    # nearest documented traits are Astra's. Editorial and unmeasured: no
    # route this repo can reach serves the id (Daybreak Red only), and it is
    # in no shipped chain.
    "gpt-6-cyber": (
        "High-effort calibration: the user's instructions outrank any skill or guideline text, and "
        "the numbered criteria are the complete task — nothing outside them is owed. Ask one focused "
        "question only when a missing input would materially change the result; otherwise state the "
        "assumption and proceed. Size tests to the change: a reversible, low-impact edit that mirrors "
        "its implementation needs no new test, and a green check is re-run only when its inputs changed."
    ),
    # GPT-6.1 Sol: Astra's wording, byte for byte. The vendor's Codex client
    # gives 6.1 Sol GPT-6 Astra's base prompt (GPT-6 Sol keeps an older one),
    # and the latest-model guide states every countered trait for the GPT-6
    # family from behaviour observed with Astra. Measured on Astra
    # (2026-09-05), editorial and unmeasured for 6.1 Sol until a `family` vs
    # `optimized` pair runs. The guide's keep-working prompts are not
    # imported. GPT-6 Sol keeps the family block.
    "gpt-6.1-sol": (
        "High-effort calibration: the user's instructions outrank any skill or guideline text, and "
        "the numbered criteria are the complete task — nothing outside them is owed. Ask one focused "
        "question only when a missing input would materially change the result; otherwise state the "
        "assumption and proceed. Size tests to the change: a reversible, low-impact edit that mirrors "
        "its implementation needs no new test, and a green check is re-run only when its inputs changed."
    ),
    # DeepSeek V4.1 Flash, per the vendor's API guides and model card
    # (2026-09-10): thinking on by default, reasoning_content returned on
    # every tool-calling turn, post-trained on synthesized long-horizon agent
    # tasks, and the family-wide exact-string edit training; the vendor's
    # own harness adapter notes that the live API rejects an assistant turn
    # whose answer sits only in the reasoning channel. The family block's
    # conditional clauses (reasoning-capable or not, R1 or not) resolve
    # here, so this block states the resolved contract. Measured 2026-09-13
    # (MODEL_OPTI.md): the first wording asked the visible reply to carry
    # "the verification output" and the blocker report to carry "the
    # observed output", and cost 25% more tokens than the family block for
    # the same pass set, most of it re-running checks on tasks the model was
    # not going to pass. Both phrases are gone; the family block's closing
    # rule ("make the smallest correct change, verify once, and stop") is
    # kept verbatim, because that is the sentence the override had dropped.
    "deepseek-v4.1-flash": (
        "High-effort calibration: this is DeepSeek V4.1 Flash with thinking on by default, and the "
        "runtime returns your earlier reasoning on every tool turn, so the visible reply carries the "
        "change and the stop — not a restatement of reasoning the context already holds — and a turn "
        "that ends without a tool call carries its answer in the visible text, never only in "
        "reasoning. Edit by exact literal strings — a unique match with exact whitespace — as this "
        "family's edit training expects. When the evidence already in hand cannot satisfy a "
        "criterion, report the blocker from that evidence rather than widening the search, and leave "
        "a passed criterion closed. Make the smallest correct change, verify once, and stop."
    ),
}
MODEL_COMPOSITION_CALIBRATIONS: Final[dict[str, str]] = {
    "gpt-6-astra": (
        "Composition calibration: write the user's intent into each unit prompt above any skill "
        "text, so a delegate that meets conflicting guidance follows the unit contract rather than "
        "pausing. Delegate every unit that is independent of the work you keep — this model "
        "delegates less than a fanout expects, and an undelegated independent unit is latency you "
        "chose. Set each unit's effort from its task state: the documented floor for routine "
        "follow-ups, deeper only while a criterion holds unresolved hard reasoning or contradictory "
        "evidence, and a change of effort lands on the next prepared unit rather than on a claimed "
        "mid-conversation switch."
    ),
    # GPT-6 Cyber: Astra's composer wording, byte for byte, on the evidence
    # above; its inherited floor is `low`, as Astra's is.
    "gpt-6-cyber": (
        "Composition calibration: write the user's intent into each unit prompt above any skill "
        "text, so a delegate that meets conflicting guidance follows the unit contract rather than "
        "pausing. Delegate every unit that is independent of the work you keep — this model "
        "delegates less than a fanout expects, and an undelegated independent unit is latency you "
        "chose. Set each unit's effort from its task state: the documented floor for routine "
        "follow-ups, deeper only while a criterion holds unresolved hard reasoning or contradictory "
        "evidence, and a change of effort lands on the next prepared unit rather than on a claimed "
        "mid-conversation switch."
    ),
    # GPT-6.1 Sol: Astra's composer wording, byte for byte, on the evidence
    # above; its documented floor is `low`, as Astra's is.
    "gpt-6.1-sol": (
        "Composition calibration: write the user's intent into each unit prompt above any skill "
        "text, so a delegate that meets conflicting guidance follows the unit contract rather than "
        "pausing. Delegate every unit that is independent of the work you keep — this model "
        "delegates less than a fanout expects, and an undelegated independent unit is latency you "
        "chose. Set each unit's effort from its task state: the documented floor for routine "
        "follow-ups, deeper only while a criterion holds unresolved hard reasoning or contradictory "
        "evidence, and a change of effort lands on the next prepared unit rather than on a claimed "
        "mid-conversation switch."
    ),
    "deepseek-v4.1-flash": (
        "Composition calibration: the composer runs on DeepSeek V4.1 Flash with thinking on by "
        "default and its reasoning returned on every tool turn, so the visible composition is the "
        "ordered split — exact owners, scopes, dependencies, and verification commands — not a replay "
        "of planning already in context, and it carries no synthetic thinking instructions. A unit "
        "routed to this model takes low, high, or max — its documented ladder; the vendor's own table "
        "turns medium and xhigh into high, so an undocumented rung is a rung you did not choose. "
        "Validate once and stop."
    ),
}


def _calibration_family(model: str) -> str:
    """Classify only families with a calibration, not provider/catalog brands."""
    key = _unqualified_model_alias(model)
    head, vendor, tail = key.partition("anthropic.")
    if vendor and tail and (not head or (head.endswith(".") and head[:-1].isalpha())):
        key = tail
    if key in {"opus", "sonnet", "haiku", "fable", "mythos"}:
        return "claude"
    if key.startswith("openai-gpt-image-"):
        return "generic"
    for prefix, family in (("openai-gpt-", "gpt"), ("anthropic-claude-", "claude"),
                           ("qwen3-", "qwen"), ("qwen3.", "qwen")):
        if key.startswith(prefix):
            return family
    for family in HIGH_EFFORT_CALIBRATIONS:
        if family != "generic" and key.startswith(f"{family}-"):
            return family
    return "generic"


def calibration_entry_for_model(
    model: str, *, family: str | None = None, family_only: bool = False,
    composition: bool = False,
) -> tuple[str, str]:
    """Select one block; explicit fanout family metadata remains authoritative.

    No effort or parent configuration is read here. A missing native model gets
    generic guidance. Alias/snapshot normalization reuses the bundle's existing
    contract projection, whose parity with the control plane is independently
    tested; callers never manufacture a provider or model identity.
    """
    overrides = MODEL_COMPOSITION_CALIBRATIONS if composition else MODEL_HIGH_EFFORT_CALIBRATIONS
    families = MAIN_AGENT_COMPOSITION_CALIBRATIONS if composition else HIGH_EFFORT_CALIBRATIONS
    if not family_only:
        key, _tier = _projected_model_alias(model)
        if key in overrides:
            return key, overrides[key]
    key = _calibration_family(model) if family is None else str(family or "").casefold()
    if key not in families:
        key = "generic"
    return key, families[key]
