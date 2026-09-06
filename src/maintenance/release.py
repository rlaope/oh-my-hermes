from __future__ import annotations

from ..skills.catalog import omh_skill_display_name

from dataclasses import dataclass
import importlib.resources as resources
import json
from pathlib import Path
import re
import shlex
import shutil
from typing import Callable, Mapping, Sequence

from ..version import __version__
from ..capabilities.playbooks import playbook_capabilities
from ..capabilities.skills import skill_capabilities
from ..catalogs.roles import role_definitions, role_file_markdown
from ..command_path import (
    installed_command_path_check_plan,
    inspect_installed_command_path,
    path_check_kind,
)
from ..local_store import atomic_write_json, read_json_object_result, utc_now
from .release_identity import (
    RELEASE_EVIDENCE_BUNDLE_SCHEMA_V2,
    build_input_manifest,
    probe_source_identity,
)
from ..plugin_bundle.omh.awareness import (
    awareness_primer_context,
    awareness_primer_markdown,
    awareness_primer_payload,
    awareness_workflow_context_markdown,
)
from ..plugin_bundle.omh.tools.capability_tool import (
    standalone_playbook_capability_items,
    standalone_skill_capability_ids,
    standalone_skill_capability_items,
)
from ..parity import build_parity_matrix
from ..quality.chat_card_coverage import build_chat_card_coverage_demo
from ..quality.common_request_coverage import build_common_request_coverage_demo, common_request_coverage_errors
from ..quality.context_brief_coverage import build_context_brief_coverage_demo
from ..quality.grounded_score import build_grounded_score_demo
from ..quality.hermes_ux_quality import build_hermes_ux_quality_demo, hermes_ux_quality_errors
from ..quality.localized_chat_copy import build_localized_chat_copy_demo, localized_chat_copy_errors
from ..quality.native_skill_competition import (
    build_native_skill_competition_report,
    native_skill_competition_errors,
)
from ..quality.route_hint_alignment import build_route_hint_alignment_demo
from ..quality.router_fast_path import build_router_fast_path_demo, router_fast_path_errors
from ..quality.routing_precision import build_routing_precision_demo, routing_precision_errors
from ..release_smoke_core import Runner, bounded_text, expand_home, subprocess_runner
from ..skill_pack import builtin_skill_templates
from ..skills.catalog import builtin_definitions
from ..system.paths import OmhPaths
from ..use_cases import (
    USE_CASES,
    build_all_use_case_artifacts,
    demo_all_use_cases,
    replay_use_case_fixtures,
    use_case_readiness,
    validate_use_case_artifact,
)

REPOSITORY_ARCHIVE_ROOT = "https://github.com/rlaope/oh-my-hermes/archive/refs"
RELEASE_ASSET_ROOT = "https://github.com/rlaope/oh-my-hermes/releases/download"
RELEASE_CHANNELS = ("stable", "preview", "local")
# `.github/workflows/release.yml` refuses any tag that is not `vX.Y.Z` and
# names the wheel it uploads after that version, so a stable version of this
# shape has a predictable release-asset URL. Anything else does not, and falls
# back to the repository archive rather than pointing pip at a guess.
RELEASE_WHEEL_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
# Measured 2026-08-15 with `curl -sL -o /dev/null -w '%{size_download}'`: the
# v1.0.6 tag archive is 45,921,555 bytes and the main branch archive is
# 46,012,605 bytes, against 2,714,885 bytes for the published v1.0.6 wheel.
# The archive carries assets/, tests/, and site/; none of the three is needed
# to run omh, and downloading them is what made `omh update` take minutes.
RELEASE_ARCHIVE_APPROX_SIZE = "~44 MB"
RELEASE_WHEEL_APPROX_SIZE = "~2.7 MB"
HERMES_SMOKE_SCHEMA = "hermes_release_smoke/v1"
RELEASE_CHECKLIST_SCHEMA = "release_readiness_checklist/v1"
INSTALLED_COMMAND_SMOKE_SCHEMA = "installed_omh_command_smoke/v1"
FIRST_USE_STATUS_SMOKE_SCHEMA = "first_use_status_smoke/v1"
SKILL_CONTENT_SMOKE_SCHEMA = "skill_content_smoke/v1"
PRODUCT_READINESS_SCHEMA = "omh_product_readiness/v1"
RELEASE_EVIDENCE_BUNDLE_SCHEMA = RELEASE_EVIDENCE_BUNDLE_SCHEMA_V2
RELEASE_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:[-_+.]?[A-Za-z0-9][A-Za-z0-9._+-]*)?$")
DEFAULT_HERMES_TAP = "rlaope/oh-my-hermes"
DEFAULT_HERMES_SKILL = "oh-my-hermes"
DEFAULT_FIRST_USE_MESSAGE = "I want to safely add a feature to this repo"
INSTALL_PATHS = ("tap", "setup")
REPRESENTATIVE_CONTEXT_RAIL_SKILLS = (
    "img-summary",
    "frontend",
    "visual-qa",
    "loop",
    "ultrawork",
    "research",
    "materials-package",
)
ROUTER_CONTENT_MARKERS = ("OMH Awareness Primer", "img-summary", "Normal users should talk to Hermes Agent")
WORKFLOW_CONTEXT_MARKERS = (
    "Workflow Lane",
    "Shared product, routing, compatibility, and evidence rules",
    "Prepared OMH routing",
)
ROLE_CONTEXT_MARKERS = ("OMH Role Context", "OMH workflow-layer responsibility context", "prepared guidance only")
CONCEPTUAL_AWARENESS_SURFACES = ("request-to-handoff", "executor selection", "coding runtime handoff")
AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT = 900
AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT = 3210
AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT = 1500
ROLE_CONTEXT_CHAR_LIMIT = 2600
# 340000 -> 349637: three capability-skill sections were added by the domain
# skill pack (`backend`, `rust`, `native-debugging`), on top of the
# `llm-app-dev` section that landed on main under the old ceiling. Each section
# is well under the per-item ceiling below; the growth is one section per new
# workflow, not per-section padding. Re-measured on the merged tree after
# #1181, #1183, and #1182 rather than carried over from this branch's base.
# 349637 -> 349663: the trigger language packs put the first Japanese and
# Chinese trigger phrases into the catalog, and a handful reach the picker
# description of skills whose English trigger list did not already fill the
# eight-phrase budget (+26 chars). Recognising a language is what the growth
# buys; it is one line-tail per affected skill, not per-section padding;
# warranted growth.
# 349663 -> 353786: `model-optimization` is a new installable skill (the
# model-onboarding process contract distilled from the GLM 5.3 run); one new
# capability section for one new workflow, not per-section padding; warranted
# growth.
# 353786 -> CAPLIMIT: the memory-sync boundary/safety sentences now name who
# applies a user-approved diff (Hermes's own native memory tool). The
# capability section truncates safety rules and caps triggers, so the delta
# here is truncation-boundary jitter from those rewordings, not the full
# sentence growth; measured live, warranted growth.
# 353787 -> 356826: `web-research` is a new installable skill -- the web lookup
# lane split out of the `research` engine so a cited one-round lookup stops
# paying the engine's declared depth budget and reference-implementation
# study. One section for one new workflow, not per-section padding;
# the engine's own section shrank by the triggers that left it.
# 356826 -> 357345: `research` gained the audience branch -- three required
# inputs (audience, format, language), the briefing artifact in its outputs,
# and the three quality-bar rules that make Hermes ask before retrieval
# rather than after. The document standard itself is a reference file, so it
# costs progressive disclosure rather than the always-loaded body; what is
# counted here is the asking, not the standard.
# 357345 -> 358092: ai-slop-cleaner's capability section grew its taxonomy,
# ordered-pass, detection, and closing-report rules; instruction lines on one
# existing skill, not padding; warranted growth.
# 358092 -> 358305: the code-review capability section grew its two-axis
# (correctness/spec) and checked-and-clean closing rules; instruction lines on
# one existing skill, not padding; warranted growth.
# 358305 -> 362620: `codebase-uml` is a new installable skill (the
# interface-level PlantUML diagram workflow over `omh codegraph uml`); one new
# capability section for one new workflow, not per-section padding; warranted
# growth.
# 362620 -> 366626: `frontend-refactor` is a new installable skill (the
# behavior-preserving UI refactor workflow); one new capability section for
# one new workflow, not per-section padding; warranted growth.
# 366626 -> 370598: `refactor-plan` is a new installable skill (the phased
# refactor planning workflow); one new capability section for one new
# workflow, not per-section padding; warranted growth.
# 370598 -> 375067: `inference-serving` is a new installable skill (engine
# decision, gated deploy runbooks, benchmark protocol); one new capability
# section for one new workflow, not per-section padding; warranted growth.
# 375067 -> 375623: agent-ops-review, ops-observability-card, and
# llm-app-dev grew instrumentation-ladder, span-vocabulary, and
# budget-discipline rules; instruction lines on three existing skills, not
# padding; warranted growth.
# 375623 -> 379709: `tech-debt-audit` is a new installable skill (the
# severity-by-effort debt ledger with rerun reconciliation); one new
# capability section for one new workflow, not per-section padding;
# warranted growth.
# 379709 -> 379904: `strategy-brief` grew the decision-record discipline
# (three-condition trigger, docs/adr/ convention pointer, never-edit-accepted
# lifecycle rule); instruction lines on one existing skill, not padding;
# warranted growth.
# 379904 -> 383766: `award-bar-score` is a new installable skill (scoring a
# web surface against published award axes); one new capability section for
# one new workflow, not per-section padding; warranted growth.
# 383766 -> 384097: the axis-spread and reduced-motion quality-bar lines
# were corrected against measured entry data; bounds and a counter-claim
# replacing a wrong rule, not padding; warranted growth.
# 384097 -> 387367: omh-docs adds one measured full capability section for
# current-source product documentation; one row, not per-section padding.
# 387367 -> 387378: use the unambiguous `product-docs` canonical identifier
# while keeping `omh-docs` as the public label.
# 387378 -> 390713: `github-issue-intake` is a new installable skill (the
# public-chat issue intake workflow with a bounded interview, duplicate
# search, and confirmation-gated connector handoff); one new capability
# section for one new workflow, not per-section padding; warranted growth.
# 390713 -> 394961: apple-design adds one platform-aware design/review/improve capability row.
FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT = 394961
FULL_CAPABILITY_SKILL_ITEM_CHAR_LIMIT = 9000
# 100000 -> 102070: the same three domain workflows each add one standalone
# capability row, again measured on the merged tree; warranted growth for three
# new workflows.
# 102070 -> 103020: one standalone capability row for the new
# `model-optimization` skill; warranted growth.
# 103020 -> 103952: `web-research` is a new installable skill -- the web lookup
# lane split out of the `research` engine so a cited one-round lookup stops
# paying the engine's declared depth budget and reference-implementation
# study. One row for one new workflow, not per-row padding;
# the engine's own row shrank by the triggers that left it.
# 103952 -> 104866: one standalone capability row for the new `codebase-uml`
# skill; warranted growth.
# 104866 -> 105813: one standalone capability row for the new
# `frontend-refactor` skill; warranted growth.
# 105813 -> 106730: one standalone capability row for the new
# `refactor-plan` skill; warranted growth.
# 106730 -> 107677: one standalone capability row for the new
# `inference-serving` skill; warranted growth.
# 107677 -> 108618: one standalone capability row for the new
# `tech-debt-audit` skill; warranted growth.
# 108618 -> 109590: one standalone capability row for the new
# `award-bar-score` skill; warranted growth.
# 109590 -> 110495: one measured standalone capability row for omh-docs.
# 110495 -> 110519: the canonical `product-docs` identifier removes the generic
# `docs` routing exception and preserves display-name symmetry.
# 110519 -> 111483: one standalone capability row for the new
# `github-issue-intake` skill; warranted growth.
# 111483 -> 112443: apple-design adds one standalone capability row.
STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT = 112443
STANDALONE_CAPABILITY_SKILL_ITEM_CHAR_LIMIT = 2200
# ULW fold context ceiling (issue #954, PR D). The limit is the pre-D measured
# value of the full profile's `skill_body` chars on `main` @ acb9a060, in the
# producer's own unit (Python str length; the payload field is named `bytes`
# but counts characters). PR D's fold growth is a reviewed exception recorded
# in the PR body -- `ultrawork` absorbs four contracts while the four retiring
# skills still ship, so cost rises until PR G removes them. PR G re-measures
# and lowers the limit; it must not be bumped silently.
# Re-tightened to the measured post-retirement value when the four folded ULW
# engines left the installable surface (#954 stage 5): the PR D reviewed
# exception is retired with them, per plan §1.2 (the ceiling is relaxed exactly
# once and re-tightened at retirement). Re-measured after the retirement
# review repointed the remaining retired-name recommendation copy to
# `ultrawork` capability phrasing (the fit-recommendation rule grew by the
# capability wording); the ceiling stays exactly the measured value.
# Re-measured when the owner made the Hermes coding harness the default
# implementation owner for ulw-work (#1001): the handoff policy and
# delivery-boundary quality bar grew by the per-lane `omh_delegate_route`
# mixture-routing guidance and the inherit-wave rule. Deliberate product
# copy, not drift; the ceiling stays exactly the measured value.
# Re-measured for the phase-todo discipline (todo init before engine work,
# bounded HUD-visible checklist instead of an open-ended reasoning loop) added
# to the same quality bar. Deliberate; the ceiling stays the measured value.
# 700058 -> 700304: ralplan gained a state-root guard safety rule (+246
# chars) pinning plan artifacts to <repo>/.omh/plans/ and forbidding .omc/**
# after observed cross-product drift; warranted growth, not padding.
# 700304 -> 700586: ultrawork gained the localized run-summary closing rule
# (+282 chars, omh_run_summary elapsed/tokens/models block); warranted growth.
# 700586 -> 701609: model-setup gained the OAuth-login/quota-recovery
# guidance (+1023 chars: TUI /setup vs hermes model paths, pooled
# credentials, refreshed chain prose); warranted growth.
# 701609 -> 704819: the six executing ULW engines gained the shared
# interjection-resume rule (#1033, +535 chars each: answer a mid-run user
# message briefly, then continue the run in the same reply); warranted growth.
# 704819 -> 705236: the architect mixture category (ultrawork routing prose
# plus the user-named model pin instruction, and model-setup's chain line);
# warranted growth.
# 705236 -> 705462: model-setup names ~/.omh/routing/model-chains.json as the
# no-code chain customization surface; warranted growth.
# 705462 -> 705999: model-setup gained the chain-interview contract (numbered
# per-category options applied via `omh model-chains`) and its trigger
# vocabulary; warranted growth.
# 705999 -> 706033: DeepSeek V3.2 joined the deep and unspecified-low shipped
# chains, so model-setup's chain line names it; warranted growth.
# 706033 -> 706701: the router body gained two structural-code-search pointer
# lines (+220 chars) and the two code-exploration skills gained a Structural
# Code Search pointer block (+224 chars each); warranted growth.
# 706701 -> 707667: the loop skill gained the /goal driver contract (+966
# chars: goal-driver-handoff outputs, gate registration before the judge,
# judge-done-is-narration, and the gates-discarded-on-reset recovery note);
# warranted growth.
# 707667 -> 709511: the loop skill gained the constraint-discipline section
# (+1844 chars: five focusing steps in OMH vocabulary, the
# loop_constraint_assessment/v1 pointer, the next_action precedence sentence,
# and the reference pointer) plus one constraint-first quality-bar bullet, and
# ultrawork gained one durable-checkpoint quality-bar bullet pointing at the
# same reference; warranted growth.
# 709511 -> 711787: the loop skill gained the measured-loop discipline
# (+2276 chars: five quality-bar rules for the evaluation contract, the
# attempt-commit cycle, the experiment ledger, the log rail, and the
# simplicity tiebreaker, one idea-exhaustion recovery note, and a connective
# section carrying the constraint-versus-metric precedence and the completion
# boundary); the full method and the attribution live in the on-demand
# reference; warranted growth.
# 711787 -> 712692: the loop skill gained metadata-only native /goal
# observation and evidence-backed phase-transition contracts (+905 chars:
# schema names, same-session turn evidence, prepared-versus-observed guidance,
# and generated output/artifact pointers); warranted growth.
# 712692 -> 713238: the loop skill gained future-default promotion governance
# (+546 chars: maintainer ownership, matched observed comparison conditions,
# unresolved-evidence fallback, and separation from runtime/completion and
# measured-loop keep/discard decisions); warranted growth.
# 713238 -> 714446: the deep-interview skill gained the answer-options
# contract (+1208 chars: the candidate-list block with a free-input entry,
# the bare-number collision rule, the mid-interview option shape, and one
# quality-bar bullet), replacing free-text-only replies with an
# AskUserQuestion-shaped numbered list; warranted growth.
# 714446 -> 715255: the ralplan skill gained the plan-todo checklist rule
# (`omh_todo` stage declaration with the declarations-not-evidence boundary,
# HUD-panel wording, and the rewrite-on-evidence-gap step) and the bounded
# in-plan research stage rule with its dossier-recording obligation, minus
# one subsumed recovery note (net +809 chars); warranted growth.
# 715255 -> 715434: the ultrawork skill's todo-init rule grew into a
# plan-structure contract on owner direction (+179 chars: numbered phases in
# delivery order, one implement/verify/deliver task per work unit,
# independent review lanes, an evidence-and-cleanup close, one task per
# observable outcome); warranted growth.
# 715434 -> 716418: the shared delegate model-label rule now tells lanes
# to show `(model)` alone when the host exposes no reasoning effort instead
# of printing a literal `unknown` placeholder beside a known model, scoped to
# narration lines (board columns keep their `unknown` cells) with a
# say-not-observed carve-out for directly asked figures (renders into all
# three handoff-guide skill bodies; the common rail carries the same text but
# sits outside this metric); warranted growth.
# 716418 -> 716734: JSON-compatible YAML quoting protects every emitted
# frontmatter name and description from mapping, comment, and delimiter syntax
# (+316 chars across the generated skill bodies); warranted growth.
# 716734 -> 717343: visual-qa replaced timestamp freshness prose with exact
# source-lineage and required-viewport contracts (+609 chars across the
# generated skill body); warranted growth.
# 717343 -> 717473: the three specialist workflows gained normalized routing
# cues for local-negation and compound-intent handling (#1112, +130 chars);
# warranted growth.
# 717473 -> 718545: the design family gained its named craft bar and pointers
# into four on-demand references (+1072 chars across the frontend,
# design-quality-gate, and design-orchestration quality bars: the named
# senior-designer bar with flat-output-fails, the DESIGN.md-before-code
# contract gate, primary-taste-direction selection, and reference-token
# extraction). The reference bodies themselves load on demand and sit outside
# this always-loaded budget; warranted growth.
# 718545 -> 719033: the ultrawork and ralplan todo-init quality-bar rules
# gained an English-labels clause (+488 chars: phase names and task titles
# stay English even in a non-English conversation, since the HUD todo
# checklist is an operator surface under the repo's English-by-default
# output contract); warranted growth.
# 719033 -> 721424: ten operations skills now expose their artifact contract
# id, machine-enforcement level, resolvable consumer (when validated), and the
# enforcement-versus-evidence boundary (#1119; +2391 chars in the merged
# renderer); warranted growth.
# 721424 -> 721472: the agent-evaluation contract now names per-task input
# digests, per-dispatch time bounds, receipt-authenticated observed_at, and
# the owning-OS-user limitation while replacing the older generic
# provenance sentence (net +48 chars); warranted growth.
# 721472 -> 723197: ultrawork gained the tests-first delivery contract
# (+1725 chars: the red-before-green observed rule with pasted-output
# evidence, forbidden test-weakening moves, the red-commit checkpoint, and
# the pointer to the on-demand references/tdd-red-green.md discipline; the
# reference body loads on demand and sits outside this always-loaded
# budget); warranted growth.
# 723197 -> 724180: context-budget-review gained the cache-placement
# discipline (+983 chars: three prompt-cache triggers, the cache-stable
# prefix-placement quality-bar rule, and the pointer to the on-demand
# references/cache-placement.md card; the reference body loads on demand
# and sits outside this always-loaded budget); warranted growth.
# 724180 -> 725734: agent-debug and failure-signal-audit gained real
# debugging-methodology quality bars (+1554 chars: competing hypotheses
# held with evidence for and against, cheapest-discriminating-probe-first
# ordering, last-known-good-to-first-bad bisect discipline, revert-verify
# before causation claims, and no fix or remediation without a reproduced
# failure first); warranted growth.
# 725734 -> 726112: the frontend quality bar wired the screenshot iteration
# loop into the web build path (+378 chars: the live-environment-first
# capture-at-1440/768/375 rule with Blocker/High/Medium/Nit triage and the
# recapture-until-the-difference-list-is-empty contract, plus the pointer to
# the on-demand references/screenshot-loop.md; the reference body loads on
# demand and sits outside this always-loaded budget); warranted growth.
# 726112 -> 726847: idea-to-deploy gained the greenfield project-bootstrap
# pass (+735 chars: six new trigger phrases, a widened use-when clause naming
# a fresh or empty repository, and the quality-bar rule requiring the
# bootstrap pass before delivery planning with the explicit throwaway-work
# skip, plus the pointer to the on-demand references/project-bootstrap.md;
# the reference body loads on demand and sits outside this always-loaded
# budget); warranted growth.
# 726847 -> 726824: the bare-noun "project scaffolding" trigger was dropped
# from idea-to-deploy after review showed it dispatched read-only questions
# about existing repos into the delivery loop (-23 chars; the imperative
# bootstrap/scaffold phrases remain); warranted shrink.
# 726824 -> 727188: ultrawork's run-summary closing rule gained the
# non-observed-status fallback (print an explicit not_available line instead
# of omitting or estimating) and a matching final-checklist item pinning the
# closing brief to the observed `omh_run_summary` line or that fallback
# (+364 chars); warranted growth.
# 727188 -> 741811: the new `maestro` (`ulw-maestro`) skill was added
# (+14623 chars total): its own catalog body -- explicit-owner precondition,
# handoff-mode statement, skill-set-informed prompt composition, and
# readiness/session-capture rules -- plus the one-clause `ulw-maestro`
# composition pointer added to `ultrawork`'s quality bar; warranted growth
# for a wholly new engine. (The coding_handoff lane's `+N more` bump is
# byte-neutral and contributes nothing here.)
# 741811 -> 741942: review fixes on the maestro engine (+131 chars): the two
# handoff schema identifiers corrected to the real
# `coding_executor_handoff/v1` / `coding_runtime_handoff/v1` constants, the
# prepared-record-vs-fanout-dispatch qualifier on the mode-statement rule, and
# the de-defaulted handoff_policy closing clause; warranted correction.
# 741942 -> 744243: ultrawork gained dependency-topology selection, standalone
# node and verification-fan-in contracts, PIN/RED/GREEN/SURFACE/CLEAN evidence
# discipline, real-surface QA and cleanup receipts, and guarded natural
# nomination for parallel-then-integrate work (+2301 chars); warranted growth.
# 744243 -> 744060: maestro's own final checklist replaced the generic
# Hermes-owner harness line -- which told an engine that structurally cannot
# have Hermes as owner to consult `hermes_coding_harness/v1` -- with one line
# stating that this engine does not apply when Hermes is the coding owner
# (-183 chars); warranted correction, not growth.
# 744060 -> 744066: `ask`'s retired bare `claude`/`gemini` trigger tokens (two
# short entries) were replaced by a slightly longer explanatory comment in the
# same trigger tuple (+6 chars net); warranted, one-time bookkeeping.
# 744066 -> 744973: maestro gained one final-checklist note naming the
# post-dispatch result-integration procedure -- collect each unit's
# `fanout_unit_result/v1` evidence, verify the integrated combination (not
# just each unit alone), and report merged/unmerged per unit, since merging
# stays an explicit operator/reviewing-agent action dispatch never performs
# (the full collect/verify/merge/report walkthrough lives in
# `references/executor-prompt-composition.md`, outside this always-loaded
# budget); model-setup gained one closing-step quality-bar line pointing a
# finished model-setup pass at the same maestro-delegation setup surfaces
# (+907 chars total); warranted growth.
# 744973 -> 745687: maestro's quality bar and safety rules gained the
# fanout-dispatch single-run entry point (`omh coding run`): the mode-statement
# rule and the "only executing surface" rule now name it alongside `omh coding
# fanout dispatch`, and a new rule states that an explicitly-named owner
# proceeds automatically through compose, readiness/permission probes, and
# dispatch with no second confirmation (the no-owner/ambiguous-owner
# ask-and-stop rule is unchanged) (+714 chars); warranted growth for a real
# new dispatch surface and its automatic-flow contract.
# 745687 -> 746326: `omh coding run` gained `--model`/`--effort` flags for a
# per-run model choice (precedence: the flag beats a routed handoff model,
# which beats the dispatch-models.json preference, which beats the executor
# CLI's own default); maestro's quality bar gained two matching rules naming
# the operator's model-choice phrasing and the flag's unvalidated,
# never-silently-falls-back passthrough to the executor (+639 chars);
# warranted growth for a real per-run model-override capability.
# 746326 -> 756725: the new `adversarial-consensus` (`omh-adversarial-consensus`)
# skill was added -- an independent-perspectives / cross-attack / distill-only
# planning contract whose always-loaded body is 10441 chars, close to
# `ralplan`'s 9616 and well under `ultrawork`'s 23879. The round-by-round
# procedure, the per-seat angle table, and the failure-mode table live in the
# on-demand `references/consensus-protocol.md` (6894 chars), outside this
# budget; what is always loaded is the roster bound, the round order, the
# independence and no-self-defense rules, the closed bucket set, and the
# mandatory planner handoff -- the rules that are wrong to discover late. The
# remainder of the delta is the `+N more` lane line regenerating across the
# eleven other `intent_to_plan` skills; warranted growth for a new workflow.
# 756725 -> 756890: `verification-gate`'s safety_rules gained one rule stating
# that a change touching an authentication, secrets/config, schema/migration,
# or payment/crypto path escalates to the thorough verification lane
# regardless of diff size (+165 chars); warranted growth documenting the new
# deterministic sensitive-path escalation (`quality/verification_tiering.py`)
# absorbed into `_verification` in `coding_delegation.py`.
# 756890 -> 758447: design-lane hardening across three existing skills. `visual-qa`
# gained the scored-verdict stopping rule (integer 0-100 score, 90 pass line, a
# mandatory edit-and-recapture round under it) plus the pixel-diff demotion, and
# `frontend` gained the model-default-aesthetic rule (the editorial prior, the
# briefs it suits and the ones it fails, and the tokens-not-negations override
# test) with the review-prompt sweep. The verdict JSON shape, the three-state
# loop exit, the default-prior sections, and the eight review prompts all live in
# the on-demand references -- the new `omh-visual-qa/references/
# visual-verdict-contract.md` (4898 chars) and the grown `taste-foundations.md`
# (+3838) and `design-critique-rubric.md` (+1122) -- outside this budget; what is
# always loaded is the threshold, the rerun obligation, and the two-line override
# test, the rules that are wrong to discover after a surface has shipped
# (+1557 chars); warranted growth.
# 758447 -> 770048: the new `llm-app-dev` (`omh-llm-app-dev`) skill was added --
# the build-discipline contract for an LLM-powered feature, whose always-loaded
# body is 11577 chars, between `adversarial-consensus`'s 10355 and
# `ultrawork`'s 23881. The per-rail decisions and the eval-harness procedure
# live in the two on-demand references (`build-rails.md` 6348 chars,
# `eval-harness.md` 4744), outside this budget; what is always loaded is the
# rail order, the one-client-boundary and exact-model-ID rules, the
# schema-first validate-and-repair rule, the prompt-artifact separation, the
# retrieval-before-generation order, and the eval deliverables -- the rules that
# are expensive to discover after the call sites exist. The remainder of the
# delta is the `+N more` lane line regenerating across the twelve other
# `coding_handoff` skills. Value re-measured on each merge of origin/main this
# branch has taken (#1181, then #1183): the delta is +11601 every time, so this
# ratchet move is additive to the ones below it rather than overlapping any of
# them; warranted growth for a new workflow.
# 770048 -> 795266: the domain skill pack added `backend`, `rust`, and
# `native-debugging` -- OMH's first technical-domain workflows, closing its two
# zero-coverage engineering domains. Each always-loaded body is smaller than
# `frontend`'s and than `llm-app-dev`'s; the per-stack pointer table, the
# migration order, the UB category table, and the debugger session recipes live
# in five on-demand references, outside this budget. What is always loaded is
# only what is wrong to discover late -- the auth boundary before endpoints, the
# deterministic unsafe/FFI/lock-free escalation trigger, and the
# three-hypotheses-on-distinct-axes floor. The remainder of the delta is the
# `+N more` lane line regenerating across the other `coding_handoff` skills.
# Re-measured on the merged tree after #1181, #1183, and #1182 rather than
# carried over from this branch's pre-merge base; warranted growth for three
# workflows closing two zero-coverage technical domains.
# 795266 -> 795558: the `frontend` quality bar gained the design-reference-data
# lookup line (+292 chars: `omh design data --kind palette|font|ux --context`
# with the rows-inform-DESIGN.md-but-the-contract-gates-the-code boundary);
# warranted growth.
# 795558 -> 795956: `verification-gate` gained the completion-integrity refusal
# rule (+398 chars) naming the four things that make a completion claim refuse
# rather than report -- an unlinked TODO/FIXME/stub marker in changed code, a
# suppressed test with no linked reason, placeholder or self-referential
# evidence, and a proof word with no command behind it. It belongs in the
# always-loaded body because it changes the verdict the skill issues, and a
# gate that only reports its verdict after the claim is written is the failure
# this rule exists to stop; warranted growth.
# 795956 -> 797568: the seed `ja` and `zh` trigger language packs put their
# phrases into the catalog, so the always-loaded "Strong routing signals" line
# of nineteen skills now also carries the Japanese and Chinese phrasings for
# that skill (+1612 chars across all of them). It belongs in the always-loaded
# body for exactly the reason the English and Korean phrases do: the routing
# signal list is what a host's picker and the skill body both read to decide
# whether this workflow is the one, and a phrase that is not there is a
# language the skill cannot be asked for. The number grows with languages
# rather than with prose -- no skill's own contract changed by a character;
# warranted growth.
# 797568 -> 798042: `verification-gate` gained the guard-deletion regression
# rule (+474 chars) requiring a named adversarial or regression case before a
# diff that deletes a validation/refusal/sanitization/permission/allowlist
# check, or the negative test that proved it, can be claimed complete. It
# belongs in the always-loaded body for the same reason the completion-
# integrity rule above does: it changes the verdict the skill issues, and a
# gate that reports a lost guard instead of refusing the claim is the failure
# this rule exists to stop; warranted growth.
# 798042 -> 798440: `codebase-onboarding` and `codegraph-refresh` each gained
# one sentence (+199 chars x2) in their spliced Structural Code Search section
# prescribing a capped search budget -- a few bounded, targeted queries before
# a full-file read, escalate only when a bounded pass finds nothing or stays
# ambiguous, and stop once the target is found. It belongs in the always-
# loaded body for the same reason the tool-preference sentence beside it does:
# it is search discipline the skill states up front, not a fact worth an
# on-demand reference lookup; warranted growth.
# 798440 -> 798464: `model-setup` names the shipped editorial chains verbatim,
# and the unspecified-low / quick chains each gained a GLM 5.3-generation head
# (owner decision, 2026-08-31: glm-5.3 and glm-5.3-flash lead, the 5.2
# entries stay as fall-through). +24 chars of chain names, not new prose;
# warranted growth.
# 798464 -> 806869: `model-optimization` is a new installable skill carrying
# the model-onboarding process contract (recognition probe -> official-first
# research -> trait-to-counter calibration -> config-first routing placement
# -> documented-price-only cost -> measurement close). One new skill body for
# one new workflow; warranted growth.
# 806869 -> 808826: the memory-sync interview protocol gains candidate
# selection (top-~5 per pass from dreaming/similarity signals), a resume
# cursor whose resume point is named as conversation-only, the
# apply-after-approval close (explicit diff approval, tool-unavailable
# branch, no raw file edits) that stops interviews from ending at an
# unapplied diff, and the natural interview trigger phrases (with their Korean pack forms); the boundary
# sentences across the pack now name who applies an approved diff. Protocol
# and boundary text that change the interview's verdict and completion, not
# padding; warranted growth.
# 808826 -> 814951: `web-research` is a new installable skill -- the web lookup
# lane split out of the `research` engine so a cited one-round lookup stops
# paying the engine's declared depth budget and reference-implementation
# study. One body for one new workflow, not per-body padding;
# the engine's own body shrank by the triggers that left it.
# 814951 -> 815057: `best-practice-research`'s single boundary statement
# became two once the lookup half of it stopped belonging to the engine.
# The split is what removed a deference inversion the policy test had been
# carrying; 106 chars is the sentence that did it.
# 815057 -> 816478: `research` gained the audience branch -- three required
# inputs (audience, format, language), the briefing artifact in its outputs,
# and the three quality-bar rules that make Hermes ask before retrieval
# rather than after. The document standard itself is a reference file, so it
# costs progressive disclosure rather than the always-loaded body; what is
# counted here is the asking, not the standard.
# 816478 -> 817601: ai-slop-cleaner gained the classify-first taxonomy line,
# the fixed pass order, the detection-first rule, the scope boundary, and the
# four-part closing report; the taxonomy and command tables live in the new
# on-demand cleanup-passes reference outside this count; warranted growth.
# 817601 -> 819169: code-review gained the spec-conformance axis, the
# smell-baseline pointer, and the checked-and-clean / could-not-assess closing
# contract; the twelve-smell table itself lives in an on-demand reference
# outside this body count; warranted growth.
# 819169 -> 827737: `codebase-uml` is one new installable skill body (the
# interface-level diagram workflow: scope, generate from the tree, render with
# the plan's command, read the omissions legend back), plus its lane name on
# the intent_to_plan skills' Workflow Lane lines; warranted growth.
# 827737 -> 838981: `frontend-refactor` is one new installable skill body
# (preview-first, impact-ordered, behavior-locked UI refactor), plus its lane
# name on the coding-handoff skills' Workflow Lane lines; the pass and
# state-discipline tables live in two on-demand references outside this
# count; warranted growth.
# 838981 -> 846063: `refactor-plan` is one new installable skill body
# (recon, contracts-first phases, files table, approval gate), plus its lane
# name on the intent_to_plan skills' Workflow Lane lines; the phase contract
# lives in an on-demand reference outside this count; warranted growth.
# 846063 -> 854431: `inference-serving` is one new installable skill body
# (decide-deploy-measure with observed-only gates), plus its lane name on the
# research_and_ops skills' Workflow Lane lines; the runbook and benchmark
# tables live in two on-demand references outside this count; warranted
# growth.
# 854431 -> 856342: the observability extension adds the tier-audit,
# span-vocabulary, and harness-budget quality-bar rules to three existing
# skills; the ladder, audit rubric, and anti-pattern tables live in the new
# on-demand instrumentation-ladder reference outside this count; warranted
# growth.
# 856342 -> 856696: `model-setup` names the shipped editorial chains verbatim,
# and the four Claude-headed chains each gained the Fable 5.1 -> Mythos 5.1
# pair ahead of Fable 5 (owner decision, 2026-09-02), plus the one sentence
# that states the Claude vendor order and why Mythos never heads a chain.
# +354 chars of chain names and one rule, not new prose; warranted growth.
# 856696 -> 864516: `tech-debt-audit` is one new installable skill body
# (orient, nine-dimension audit, severity-by-effort ledger, rerun
# reconciliation), plus its lane name on the coding_handoff skills' Workflow
# Lane lines; the dimension and reconciliation tables live in one on-demand
# reference outside this count; warranted growth.
# 864516 -> 865332: `strategy-brief` grew the decision-record discipline
# (three-condition trigger, record convention and approval gate, lifecycle
# and supersession rules, the decision-recall wiring); the file convention,
# lifecycle table, and review checklists live in the new on-demand
# decision-records reference outside this count; warranted growth.
# 865332 -> 865700: `model-setup` names the provider-entitlement document the
# interactive setup writes (~/.omh/routing/providers.json) and the one rule
# it implies — served entries lead, nothing is removed, a CLI subscription
# only seeds the Maestro lane — so Hermes explains the reordered chains it
# will see instead of calling them drift; one sentence, warranted growth.
# 865700 -> 866062: the refactor-plan repointing lengthens two existing
# boundary lines (frontend-refactor, ai-slop-cleaner) and adds one to
# ralplan, so each side of the phase-planning boundary names the other;
# three boundary sentences, not new prose; warranted growth.
# 866062 -> 867189: `accessibility-audit` gains the rule-ID, fix-partition,
# and report-shape rules plus the fix-class safety line; four instruction
# lines on one existing skill, with the rule table and its WCAG mappings in
# a new on-demand reference outside this count; warranted growth.
# 867189 -> 868268: `frontend` gains the web-vitals budget, attribution, and
# field-vs-lab rules plus the measurement-conditions safety line; four
# instruction lines on one existing skill, with the threshold and
# attribution tables in a new on-demand reference outside this count;
# warranted growth.
# 868268 -> 869354: `agent-evaluation` gains the loop-shape, stop-rule, and
# criteria-before-generation rules plus the judge-score safety line; four
# instruction lines on one existing skill, with the shape table and judging
# rules in a new on-demand reference outside this count; warranted growth.
# 869354 -> 876865: `award-bar-score` is one new installable skill body
# (per-axis scoring, the weighted total against the published threshold, the
# binding-constraint call, and the accessibility/performance tradeoff
# ledger), plus its lane name on the materials_and_visuals skills' Workflow
# Lane lines; the judging model, weights, thresholds, and the worked
# arithmetic live in one on-demand reference outside this count; warranted
# growth.
# 876865 -> 877208: same measured correction reaching the always-loaded
# body; warranted growth.
# 877208 -> 882271: measured full-profile output after adding the 5,295-byte
# omh-docs body and projecting its research-and-ops lane membership; its four
# progressive references remain outside the always-loaded body count.
# 882271 -> 882729: source-accuracy fixes document project-scoped OMH homes,
# the doctor state-write side effect, and the metadata-only Hermes-memory
# comparison boundary; this is measured product documentation, not padding.
# 882729 -> 890353: `github-issue-intake` is one new installable skill body
# (classification, the three-question bounded interview, duplicate search,
# the confirmation gate, and the connector read-back boundary), plus its
# lane name on the automation_and_status skills' Workflow Lane lines;
# warranted growth.
# 890353 -> 890777: one safety rule on `github-issue-intake` encoding the
# hardened lifecycle (confirmation requires a complete direction check plus
# a completed duplicate search; any blocker stops confirmation and handoff
# and cannot be cleared by a later observed result); one rule, not padding;
# warranted growth.
# 890777 -> 891138: the final template, security-redirect, privacy-projection,
# authenticated-maintainer, and idempotent-handoff rules complete that same
# workflow contract; one bounded workflow correction, not padding.
# 891138 -> 899556: apple-design adds a concise platform brief and progressive
# references; detailed production and library guidance stays out of the body.
# 899556 -> 901000: `llm-app-dev` gains the public-board communication contract
# -- one quality-bar rule naming the six action classes and the show-then-
# approve step, one safety rule on authenticated-is-not-private and untrusted
# peer approval, one final-checklist line, one recovery note on ambiguous
# delivery, and the public-board clause in its use-when. The per-action
# authority table, the approval record, the compaction/handoff rules, and the
# anti-patterns live in the new on-demand `references/public-board.md` outside
# this count; what is always loaded is only what is wrong to discover after a
# post has already been read; warranted growth.
FULL_PROFILE_SKILL_BODY_CHAR_LIMIT = 901000
FULL_PROFILE_SKILL_BODY_REVIEWED_EXCEPTION_CHARS = 0


@dataclass(frozen=True)
class ReleaseSelection:
    channel: str
    version: str
    package_url: str
    source_label: str
    artifact_kind: str = "repository-archive"


def release_tag_for(version: str) -> str:
    return version if version.startswith("v") else f"v{version}"


def release_wheel_name(release_version: str) -> str:
    return f"oh_my_hermes-{release_version}-py3-none-any.whl"


def repository_archive_url(tag: str) -> str:
    return f"{REPOSITORY_ARCHIVE_ROOT}/tags/{tag}.zip"


def package_url_for(channel: str, version: str = "", package_url: str = "") -> ReleaseSelection:
    if channel not in RELEASE_CHANNELS:
        raise ValueError(f"unsupported release channel: {channel}")
    if package_url:
        return ReleaseSelection(channel, version, package_url, "custom-url", "custom-url")
    if channel == "stable":
        if not version:
            raise ValueError("stable channel requires --version or OMH_VERSION")
        tag = release_tag_for(version)
        release_version = tag[1:]
        if RELEASE_WHEEL_VERSION_RE.fullmatch(release_version):
            wheel_url = f"{RELEASE_ASSET_ROOT}/{tag}/{release_wheel_name(release_version)}"
            return ReleaseSelection(channel, version, wheel_url, tag, "release-wheel")
        return ReleaseSelection(channel, version, repository_archive_url(tag), tag, "repository-archive")
    if channel == "preview":
        # Preview tracks branch `main`, and GitHub publishes release assets per
        # tag only, so there is no slim artifact to point at here. The branch
        # archive stays, labelled with what it costs, rather than inventing an
        # endpoint the release workflow does not produce.
        return ReleaseSelection(channel, version, f"{REPOSITORY_ARCHIVE_ROOT}/heads/main.zip", "main", "repository-archive")
    return ReleaseSelection(channel, version, "local", "local", "local")


def release_artifact_note(selection: ReleaseSelection) -> str:
    """Say what the resolved artifact is and what downloading it costs."""
    if selection.artifact_kind == "release-wheel":
        return f"release wheel, {RELEASE_WHEEL_APPROX_SIZE}"
    if selection.artifact_kind == "repository-archive":
        return (
            f"full repository archive, {RELEASE_ARCHIVE_APPROX_SIZE} "
            "including assets, tests, and site; this download can take minutes"
        )
    return ""


def missing_release_asset_hint(selection: ReleaseSelection) -> str:
    """Name the fallback when a stable version has no published wheel asset.

    Releases before the wheel-publishing workflow existed carry no asset, and
    v1.0.3 through v1.0.5 carry none either. pip reports those as a bare 404
    against a URL nobody typed, so the failure has to name the archive that
    does exist for the same tag.
    """
    if selection.artifact_kind != "release-wheel":
        return ""
    tag = selection.source_label
    return (
        f"if {tag} has no published wheel asset, install from the full repository archive instead: "
        f"--package-url {repository_archive_url(tag)}"
    )


@dataclass(frozen=True)
class HermesSmokeStep:
    name: str
    command: tuple[str, ...]
    phase: str
    mutates_profile: bool
    required: bool = True
    proof_boundary: str = ""

    def to_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "command": list(self.command),
            "phase": self.phase,
            "mutates_profile": self.mutates_profile,
            "required": self.required,
            "proof_boundary": self.proof_boundary,
        }


@dataclass(frozen=True)
class ReleaseChecklistItem:
    item_id: str
    title: str
    command: str
    phase: str
    required: bool
    mutates_profile: bool
    evidence_required: str
    proof_boundary: str
    requires_release_authority: bool = False

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.item_id,
            "title": self.title,
            "command": self.command,
            "phase": self.phase,
            "required": self.required,
            "observed": False,
            "mutates_profile": self.mutates_profile,
            "requires_release_authority": self.requires_release_authority,
            "evidence_required": self.evidence_required,
            "proof_boundary": self.proof_boundary,
        }


@dataclass(frozen=True)
class ReleaseQualityEvidence:
    skill_content: dict[str, object]
    parity: dict[str, object]
    grounded_score: dict[str, object]
    chat_cards: dict[str, object]
    route_hints: dict[str, object]
    context_briefs: dict[str, object]
    routing_precision: dict[str, object]
    native_competition: dict[str, object]
    localized_chat_copy: dict[str, object]
    router_fast_path: dict[str, object]
    common_request_coverage: dict[str, object]
    hermes_ux: dict[str, object]
    checklist: dict[str, object]


def release_readiness_checklist(
    *,
    version: str = __version__,
    omh_command: str = "omh",
) -> dict[str, object]:
    release_version = _normalize_release_version(version)
    tag = f"v{release_version}"
    wheel = f"dist/oh_my_hermes-{release_version}-py3-none-any.whl"
    omh_display = _shell_word(omh_command or "omh")
    items = [
        ReleaseChecklistItem(
            "unit_tests",
            "Run the full unittest suite",
            "PYTHONPATH=tests uv run python -m unittest discover -s tests -v",
            "local-quality",
            True,
            False,
            "All tests pass locally or in CI.",
            "Unit tests prove local contracts only; they do not prove Hermes loaded the installed skills.",
        ),
        ReleaseChecklistItem(
            "compileall",
            "Compile Python sources",
            "uv run python -m compileall -q src tests",
            "local-quality",
            True,
            False,
            "compileall exits successfully.",
            "Syntax/import compilation is local source evidence only.",
        ),
        ReleaseChecklistItem(
            "docs_workflows_check",
            "Check generated workflow docs",
            "uv run python -m omh.cli docs workflows --check",
            "contract-quality",
            True,
            False,
            "Generated workflow docs match catalog data.",
            "This proves generated references are in sync, not that Hermes selected a workflow in chat.",
        ),
        ReleaseChecklistItem(
            "harness_validate",
            "Validate harness catalog contracts",
            "uv run python -m omh.cli harness validate",
            "contract-quality",
            True,
            False,
            "Harness catalog validation exits successfully.",
            "Harness validation proves local schemas and metadata, not runtime execution.",
        ),
        ReleaseChecklistItem(
            "source_checkout_command_smoke",
            "Check source-checkout console command importability",
            'uv run --no-editable omh recommend "risky refactor" --limit 1 --json',
            "local-quality",
            True,
            False,
            "The source checkout can build/install the package non-editably and run the `omh` console script.",
            "This proves console-script importability for the local checkout only; it does not prove Hermes chat visibility, plugin load, executor work, review, CI, merge, or delivery.",
        ),
        ReleaseChecklistItem(
            "use_case_demo_cards",
            "Check G1-G10 use-case demo cards",
            "uv run python -m omh.cli cases demo --all --json",
            "contract-quality",
            True,
            False,
            "Use-case demo card collection renders all ten G1-G10 cards with route, action, wrapper card, and evidence boundary metadata.",
            "Use-case demo cards prove wrapper-renderable projections only; they do not prove cron, connector, file, memory, executor, review, CI, merge, or delivery work happened.",
        ),
        ReleaseChecklistItem(
            "use_case_artifact_bundle",
            "Check G1-G10 use-case artifact bundle",
            "uv run python -m omh.cli cases artifact --all --json",
            "contract-quality",
            True,
            False,
            "Use-case artifact bundle renders all ten G1-G10 prepared artifacts with route, operator-step, proof-surface, wrapper-card, and evidence-boundary metadata.",
            "Use-case artifacts prove prepared runbook projection only; they do not prove runtime execution, connector invocation, delivery, file generation, memory mutation, executor dispatch, review, CI, merge, or billing evidence.",
        ),
        ReleaseChecklistItem(
            "use_case_replay",
            "Replay G1-G10 natural-language use-case fixtures",
            "uv run python -m omh.cli cases replay --json",
            "contract-quality",
            True,
            False,
            "Use-case replay passes deterministic English and Korean operator fixtures for every G1-G10 application case.",
            "Use-case replay proves deterministic recommendation routing for synthetic fixtures only; it does not prove live Hermes chat behavior or any runtime execution.",
        ),
        ReleaseChecklistItem(
            "use_case_readiness",
            "Check G1-G10 use-case readiness rollup",
            "uv run python -m omh.cli cases readiness --json",
            "contract-quality",
            True,
            False,
            "Use-case readiness reports catalog, demo-card, artifact-bundle, and replay gates as passing while separating optional local artifact-store state.",
            "Use-case readiness proves deterministic local use-case contracts only; it does not prove live Hermes chat behavior, connector work, executor work, review, CI, merge, delivery, or billing evidence.",
        ),
        ReleaseChecklistItem(
            "grounded_score",
            "Check grounded routing score",
            "uv run python -m omh.cli demo grounded-score --json",
            "contract-quality",
            True,
            False,
            "Grounded score reports every representative operator scenario at 10/10.",
            "Grounded score proves deterministic local route, response-kind, next-action, playbook, and boundary checks only; it does not prove live Hermes chat rendering, executor work, review, CI, merge, delivery, or plugin-load evidence.",
        ),
        ReleaseChecklistItem(
            "chat_card_coverage",
            "Check wrapper chat card coverage",
            "uv run python -m omh.cli demo chat-card-coverage --json",
            "contract-quality",
            True,
            False,
            "Chat card coverage reports all dedicated workflow cards passing with generic ack count 0.",
            "Chat card coverage proves deterministic local wrapper-card contracts only; it does not prove live Hermes chat rendering, platform delivery, executor work, review, CI, merge, or plugin-load evidence.",
        ),
        ReleaseChecklistItem(
            "route_hint_alignment",
            "Check route and awareness hint alignment",
            "uv run python -m omh.cli demo route-hint-alignment --json",
            "contract-quality",
            True,
            False,
            "Route hint alignment reports every representative grounded-score and chat-card scenario with a primary plugin awareness hint that matches the selected workflow.",
            "Route hint alignment proves deterministic local router/hint agreement only; it does not prove live Hermes chat rendering, platform delivery, executor work, review, CI, merge, or plugin-load evidence.",
        ),
        ReleaseChecklistItem(
            "context_brief_coverage",
            "Check Hermes context brief coverage",
            "uv run python -m omh.cli demo context-brief-coverage --json",
            "contract-quality",
            True,
            False,
            "Context brief coverage reports every representative first-turn context case with metadata-only OMH mental model, route hint or picker hint, generic-tool checkpoint, and evidence boundary.",
            "Context brief coverage proves deterministic local Hermes-facing context only; it does not prove live Hermes chat rendering, plugin load, platform delivery, generic tool invocation, executor work, review, CI, merge, or delivery.",
        ),
        ReleaseChecklistItem(
            "routing_precision",
            "Check routing precision boundaries",
            "uv run python -m omh.cli demo routing-precision --json",
            "contract-quality",
            True,
            False,
            "Routing precision reports ordinary direct-answer and file-lookup prompts with overroute count 0, plus expected OMH prompts with missed intervention count 0.",
            "Routing precision proves deterministic local over-intervention and missed-intervention guards only; it does not prove live Hermes chat rendering, platform delivery, source retrieval, file inspection, executor work, review, CI, merge, or plugin-load evidence.",
        ),
        ReleaseChecklistItem(
            "native_competition",
            "Check native-skill competition boundaries",
            "uv run python -m omh.cli demo native-competition --json",
            "contract-quality",
            True,
            False,
            "Native competition reports all generated-frontmatter pairwise cases passing with no ties.",
            "Native competition is a deterministic local lexical heuristic; it does not prove live Hermes picker ranking or installed native inventory.",
        ),
        ReleaseChecklistItem(
            "localized_chat_copy",
            "Check localized chat-card framing",
            "uv run python -m omh.cli demo localized-chat-copy --json",
            "contract-quality",
            True,
            False,
            "Localized chat copy reports common non-English operator prompts with expected locale, card kind, next action, and no English catalog fallback.",
            "Localized chat copy proves deterministic local copy framing only; it does not prove live Hermes chat rendering, translation service quality, platform delivery, source retrieval, executor work, review, CI, merge, or plugin-load evidence.",
        ),
        ReleaseChecklistItem(
            "router_fast_path",
            "Check router fast-path quality",
            "uv run python -m omh.cli demo router-fast-path --json",
            "contract-quality",
            True,
            False,
            "Router fast-path quality reports high-frequency chat turns with explicit fast-path markers and no route or next-action drift.",
            "Router fast-path quality proves deterministic local fast-path route markers only; it does not prove wall-clock latency, live Hermes chat rendering, platform delivery, executor work, review, CI, merge, or plugin-load evidence.",
        ),
        ReleaseChecklistItem(
            "common_request_coverage",
            "Check common Hermes-agent request coverage",
            "uv run python -m omh.cli demo common-request-coverage --json",
            "contract-quality",
            True,
            False,
            "Common request coverage reports the curated ordinary Hermes-agent request corpus at or above the 95% target.",
            "Common request coverage proves deterministic local routing breadth only; it does not prove live Hermes chat rendering, external plugin telemetry, connector work, executor work, review, CI, merge, delivery, or market-share evidence.",
        ),
        ReleaseChecklistItem(
            "hermes_ux_quality",
            "Check Hermes-facing UX quality rollup",
            "uv run python -m omh.cli demo hermes-ux-quality --json",
            "contract-quality",
            True,
            False,
            "Hermes UX quality reports routing score, dedicated chat-card coverage, route-hint alignment, context-brief coverage, routing precision, native-skill competition, localized chat copy, router fast-path quality, and common request coverage as passing in one user-facing rollup.",
            "Hermes UX quality proves deterministic local routing, card, hint, context, precision, native-competition, localized-copy, fast-path, and common-request contracts only; it does not prove live Hermes chat rendering, picker ranking, platform delivery, plugin load, generic tool invocation, executor work, review, CI, merge, or delivery.",
        ),
        ReleaseChecklistItem(
            "product_readiness",
            "Check product readiness rollup",
            f"{omh_display} release product-readiness --version {release_version} --json",
            "contract-quality",
            True,
            False,
            "Product readiness reports skill-content, G1-G10 use-case, grounded score, wrapper chat card coverage, route hint alignment, context brief coverage, routing precision, native-skill competition, localized chat copy, router fast-path quality, common request coverage, Hermes UX quality, parity, and release checklist gates as passing.",
            "Product readiness proves deterministic local package and product contracts only; it does not prove live Hermes chat behavior, connector work, executor work, review, CI, merge, delivery, or billing evidence.",
        ),
        ReleaseChecklistItem(
            "release_evidence_bundle",
            "Write the local release evidence bundle",
            f"{omh_display} release evidence-bundle --version {release_version} --write --json",
            "evidence-packaging",
            True,
            False,
            "A local `omh_release_evidence_bundle/v2` artifact is written with checklist, product readiness, skill content, use-case readiness, grounded score, chat card coverage, route hint alignment, context brief coverage, routing precision, native-skill competition, localized chat copy, router fast-path quality, common request coverage, Hermes UX quality, and parity snapshots.",
            "The evidence bundle packages local deterministic evidence only; it is not live Hermes runtime use, connector execution, executor dispatch, review, CI, merge, delivery, or release publication evidence.",
        ),
        ReleaseChecklistItem(
            "stable_install_dry_run",
            "Dry-run stable install metadata",
            (
                "uv run python -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke "
                f"install --dry-run --channel stable --version {release_version}"
            ),
            "install-plan",
            True,
            False,
            "Dry-run payload names the stable channel, version, source ref, and package URL.",
            "Dry-run install is not evidence that files were written or Hermes reloaded.",
        ),
        ReleaseChecklistItem(
            "stable_setup_dry_run",
            "Dry-run stable setup metadata",
            (
                "uv run python -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke "
                f"setup --dry-run --channel stable --version {release_version}"
            ),
            "install-plan",
            True,
            False,
            "Dry-run setup shows the managed skill and Hermes registration plan.",
            "Dry-run setup does not mutate Hermes and is not native runtime-load evidence.",
        ),
        ReleaseChecklistItem(
            "probe_smoke",
            "Run local capability probe",
            "uv run python -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke probe",
            "local-quality",
            True,
            False,
            "Capability probe exits successfully.",
            "Probe output is local capability evidence, not observed Hermes chat behavior.",
        ),
        ReleaseChecklistItem(
            "release_smoke_plan",
            "Render Hermes release smoke plan",
            "uv run python -m omh.cli release hermes-smoke",
            "release-smoke",
            True,
            False,
            "Release smoke plan renders with plan-only evidence boundaries.",
            "Plan mode does not touch the current Hermes profile.",
        ),
        ReleaseChecklistItem(
            "installed_command_path",
            "Check installed omh command is on PATH",
            f"command -v {omh_display}",
            "installed-command",
            True,
            False,
            "The shell resolves the installed OMH command before any nested smoke uses it.",
            "PATH resolution proves command discoverability only; it does not prove console-script importability.",
        ),
        ReleaseChecklistItem(
            "installed_command_help",
            "Check installed omh command help",
            f"{omh_display} --help",
            "installed-command",
            True,
            False,
            "Installed command prints help successfully.",
            "This proves console-script importability only.",
        ),
        ReleaseChecklistItem(
            "skill_content_smoke",
            "Check installed command package skill content",
            f"{omh_display} release skill-content-smoke --json",
            "installed-command",
            True,
            False,
            "Skill content smoke reports ok=true for router awareness, generated workflow context rails, bundled role context, all-skill awareness lane coverage, full capability manifest context, playbook capability context, standalone plugin capability fallback coverage, G1-G10 use-case demo cards, G1-G10 use-case artifact bundles, G1-G10 natural-language use-case replay, bounded prompt context budgets, and bounded capability payload budgets.",
            "This proves the installed OMH command package can render expected skill guidance; it does not prove Hermes loaded or selected it in chat.",
        ),
        ReleaseChecklistItem(
            "installed_command_smoke",
            "Observe installed command smoke without Hermes mutation",
            (
                f"{omh_display} --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke "
                f"release hermes-smoke --install-path setup --omh-command {omh_display} --include-command-smoke"
            ),
            "installed-command",
            True,
            False,
            "Nested installed_command_smoke is mode=live, observed=true, ok=true, and includes installed skill content smoke.",
            "This observes the installed OMH command path and generated skill guidance while keeping the outer Hermes profile smoke plan-only.",
        ),
        ReleaseChecklistItem(
            "build_artifacts",
            "Build sdist and wheel",
            "uv build",
            "package-build",
            True,
            False,
            "sdist and wheel are built without packaging warnings or errors.",
            "Build output proves package construction, not install success.",
        ),
        ReleaseChecklistItem(
            "wheel_install",
            "Install the built wheel into an isolated venv",
            (
                "python3 -m venv /tmp/omh-wheel-smoke && "
                f"/tmp/omh-wheel-smoke/bin/python -m pip install --upgrade {wheel}"
            ),
            "package-build",
            True,
            False,
            "The isolated venv installs the built wheel successfully.",
            "Wheel install is isolated package evidence, not target Hermes profile evidence.",
        ),
        ReleaseChecklistItem(
            "wheel_command_smoke",
            "Run the wheel-installed command smoke",
            (
                "/tmp/omh-wheel-smoke/bin/omh --omh-home /tmp/omh-wheel-home --hermes-home /tmp/hermes-wheel-home "
                "release hermes-smoke --install-path setup --omh-command /tmp/omh-wheel-smoke/bin/omh --include-command-smoke"
            ),
            "package-build",
            True,
            False,
            "Wheel-installed command smoke reports nested installed_command_smoke ok=true.",
            "This still does not mutate a real Hermes profile.",
        ),
        ReleaseChecklistItem(
            "wheel_setup_dry_run",
            "Run wheel-installed setup dry-run for the stable release",
            (
                "/tmp/omh-wheel-smoke/bin/omh --omh-home /tmp/omh-wheel-home --hermes-home /tmp/hermes-wheel-home "
                f"setup --dry-run --channel stable --version {release_version}"
            ),
            "package-build",
            True,
            False,
            "Wheel-installed setup dry-run renders the stable bootstrap plan successfully.",
            "The setup dry-run does not install skills, reload Hermes, or mutate a target profile.",
        ),
        ReleaseChecklistItem(
            "installer_smoke",
            "Run the install.sh smoke in an isolated temp home",
            f"{omh_display} release install-smoke --live --repo-root \"$PWD\" --install-script \"$PWD/install.sh\"",
            "installer",
            True,
            False,
            "install_script_smoke reports ok=true after install.sh creates a temp venv/bin command without running setup or doctor, then proves the installed command can render release smoke.",
            "Install script smoke mutates only its isolated temp HOME/venv/bin unless --work-dir points elsewhere; it is not live Hermes runtime-use evidence.",
        ),
        ReleaseChecklistItem(
            "live_tap_smoke",
            "Run exactly one live Hermes tap smoke before tagging",
            f"{omh_display} release hermes-smoke --live --install-path tap --target-confirmed",
            "manual-release-candidate",
            True,
            True,
            "Hermes CLI install/list/check/inspect commands succeed for the target profile.",
            "This mutates the target Hermes profile and still does not prove later chat selection without wrapper evidence.",
            True,
        ),
        ReleaseChecklistItem(
            "tag_and_publish",
            "Tag and publish only after all required evidence is attached",
            f'git tag -a {tag} -m "Release {tag}" && git push origin {tag}',
            "release-authority",
            False,
            False,
            "Maintainer explicitly approves tag/release publication after local and live evidence are recorded.",
            "This checklist does not create tags, GitHub releases, or production artifacts by itself.",
            True,
        ),
        ReleaseChecklistItem(
            "machine_sync_after_cut",
            "Sync each machine to the published release and confirm the version it reports",
            f"{omh_display} update && {omh_display} --version && {omh_display} doctor",
            "post-release-sync",
            False,
            True,
            (
                f"The installed command reports {release_version}, doctor passes, and the Hermes TUI HUD footer shows "
                f"v{release_version} after the terminal is restarted."
            ),
            (
                "Tagging and publishing move the tag and the package registries only; no installed machine changes until it "
                "updates itself. Every version an operator sees -- `omh --version`, the plugin manifest, and the TUI HUD "
                "footer -- is the installed version, never the newest published tag. Never hand-copy files into "
                "~/.hermes/plugins or ~/.hermes/tui-widgets to close the gap: that drifts from the install manifests and "
                "makes the next update refuse."
            ),
        ),
    ]
    return {
        "schema_version": RELEASE_CHECKLIST_SCHEMA,
        "mode": "plan",
        "ok": True,
        "observed": False,
        "version": release_version,
        "tag": tag,
        "proof_boundary": (
            "This checklist is a deterministic release plan. It does not run commands, create tags, publish GitHub releases, "
            "or prove Hermes runtime use until the listed evidence is observed separately."
        ),
        "items": [item.to_payload() for item in items],
        "required_item_count": sum(1 for item in items if item.required),
        "manual_authority_item_count": sum(1 for item in items if item.requires_release_authority),
        "recommended_next_action": (
            "Run the required local gates, record one live Hermes smoke from the target profile, then request explicit "
            "release authority before tagging or publishing."
        ),
    }


def product_readiness_report(
    *,
    version: str = __version__,
    omh_command: str = "omh",
    paths: OmhPaths | None = None,
) -> dict[str, object]:
    release_version = _normalize_release_version(version)
    resolved_paths = paths or OmhPaths(omh_home=Path("~/.omh").expanduser(), hermes_home=Path("~/.hermes").expanduser())
    evidence = _build_release_quality_evidence(release_version=release_version, omh_command=omh_command)
    return _product_readiness_report_from_evidence(
        release_version=release_version,
        omh_command=omh_command,
        evidence=evidence,
        paths=resolved_paths,
    )


def _build_release_quality_evidence(*, release_version: str, omh_command: str) -> ReleaseQualityEvidence:
    skill_content = skill_content_smoke()
    parity = build_parity_matrix()
    grounded_score = build_grounded_score_demo()
    chat_cards = build_chat_card_coverage_demo()
    route_hints = build_route_hint_alignment_demo(
        grounded_score=grounded_score,
        chat_card_coverage=chat_cards,
    )
    context_briefs = build_context_brief_coverage_demo()
    routing_precision = build_routing_precision_demo()
    native_competition = build_native_skill_competition_report()
    localized_chat_copy = build_localized_chat_copy_demo()
    router_fast_path = build_router_fast_path_demo()
    common_request_coverage = build_common_request_coverage_demo()
    hermes_ux = build_hermes_ux_quality_demo(
        grounded_score=grounded_score,
        chat_card_coverage=chat_cards,
        route_hint_alignment=route_hints,
        context_brief_coverage=context_briefs,
        routing_precision=routing_precision,
        native_competition=native_competition,
        localized_chat_copy=localized_chat_copy,
        router_fast_path=router_fast_path,
        common_request_coverage=common_request_coverage,
    )
    checklist = release_readiness_checklist(version=release_version, omh_command=omh_command)
    return ReleaseQualityEvidence(
        skill_content=skill_content,
        parity=parity,
        grounded_score=grounded_score,
        chat_cards=chat_cards,
        route_hints=route_hints,
        context_briefs=context_briefs,
        routing_precision=routing_precision,
        native_competition=native_competition,
        localized_chat_copy=localized_chat_copy,
        router_fast_path=router_fast_path,
        common_request_coverage=common_request_coverage,
        hermes_ux=hermes_ux,
        checklist=checklist,
    )


def _product_readiness_report_from_evidence(
    *,
    release_version: str,
    omh_command: str,
    evidence: ReleaseQualityEvidence,
    paths: OmhPaths,
) -> dict[str, object]:
    omh_display = _shell_word(omh_command)
    skill_content = evidence.skill_content
    parity = evidence.parity
    grounded_score = evidence.grounded_score
    chat_cards = evidence.chat_cards
    route_hints = evidence.route_hints
    context_briefs = evidence.context_briefs
    routing_precision = evidence.routing_precision
    native_competition = evidence.native_competition
    localized_chat_copy = evidence.localized_chat_copy
    router_fast_path = evidence.router_fast_path
    common_request_coverage = evidence.common_request_coverage
    hermes_ux = evidence.hermes_ux
    checklist = evidence.checklist
    use_case_readiness_payload = use_case_readiness(paths)
    use_case_readiness_failures = _blocking_gate_messages(use_case_readiness_payload)
    use_case_readiness_warnings = _warning_gate_messages(use_case_readiness_payload)
    local_store_status = _release_local_store_status(use_case_readiness_payload)

    checklist_items = checklist.get("items", [])
    checklist_ids = {
        str(item.get("id"))
        for item in checklist_items
        if isinstance(item, dict) and item.get("id")
    }
    required_checklist_ids = {
        "unit_tests",
        "docs_workflows_check",
        "harness_validate",
        "skill_content_smoke",
        "use_case_readiness",
        "grounded_score",
        "chat_card_coverage",
        "route_hint_alignment",
        "context_brief_coverage",
        "routing_precision",
        "native_competition",
        "localized_chat_copy",
        "router_fast_path",
        "common_request_coverage",
        "hermes_ux_quality",
        "product_readiness",
        "release_evidence_bundle",
        "installed_command_smoke",
        "installer_smoke",
        "live_tap_smoke",
    }
    missing_checklist_ids = sorted(required_checklist_ids - checklist_ids)

    parity_summary = parity.get("summary", {}) if isinstance(parity.get("summary"), dict) else {}
    parity_errors = []
    for status_key in ("partial", "planned", "deferred"):
        count = int(parity_summary.get(status_key, 0) or 0)
        if count:
            parity_errors.append(f"{status_key}: {count}")

    grounded_score_errors = _grounded_score_errors(grounded_score)
    chat_card_summary = chat_cards.get("summary", {}) if isinstance(chat_cards.get("summary"), Mapping) else {}
    chat_card_errors = _chat_card_coverage_errors(chat_cards)
    route_hint_summary = route_hints.get("summary", {}) if isinstance(route_hints.get("summary"), Mapping) else {}
    route_hint_errors = _route_hint_alignment_errors(route_hints)
    context_brief_summary = (
        context_briefs.get("summary", {}) if isinstance(context_briefs.get("summary"), Mapping) else {}
    )
    context_brief_errors = _context_brief_coverage_errors(context_briefs)
    routing_precision_summary = (
        routing_precision.get("summary", {}) if isinstance(routing_precision.get("summary"), Mapping) else {}
    )
    routing_precision_gate_errors = routing_precision_errors(routing_precision)
    native_competition_gate_errors = native_skill_competition_errors(native_competition)
    localized_chat_copy_summary = (
        localized_chat_copy.get("summary", {}) if isinstance(localized_chat_copy.get("summary"), Mapping) else {}
    )
    localized_chat_copy_gate_errors = localized_chat_copy_errors(localized_chat_copy)
    router_fast_path_summary = (
        router_fast_path.get("summary", {}) if isinstance(router_fast_path.get("summary"), Mapping) else {}
    )
    router_fast_path_gate_errors = router_fast_path_errors(router_fast_path)
    common_request_summary = (
        common_request_coverage.get("summary", {})
        if isinstance(common_request_coverage.get("summary"), Mapping)
        else {}
    )
    common_request_gate_errors = common_request_coverage_errors(common_request_coverage)
    hermes_ux_summary = hermes_ux.get("summary", {}) if isinstance(hermes_ux.get("summary"), Mapping) else {}
    hermes_ux_errors = hermes_ux_quality_errors(hermes_ux)
    gates = [
        _product_readiness_gate(
            "skill_content",
            "Installed package skill content",
            "passed" if skill_content.get("ok") else "failed",
            True,
            (
                f"{skill_content.get('skill_count')} skill surface(s), "
                f"{skill_content.get('checked_marker_count')} marker(s), "
                f"{len(skill_content.get('failed_checks', [])) if isinstance(skill_content.get('failed_checks'), list) else 0} failed marker(s)"
            ),
            "omh release skill-content-smoke --json",
            _skill_content_product_errors(skill_content),
            [],
            str(skill_content.get("proof_boundary", "")),
        ),
        _product_readiness_gate(
            "use_cases",
            "G1-G10 application use cases",
            "passed" if use_case_readiness_payload.get("blocking_failures") == 0 else "failed",
            True,
            (
                f"score {use_case_readiness_payload.get('score')}/100; "
                f"blocking {use_case_readiness_payload.get('blocking_failures')}; "
                f"warnings {use_case_readiness_payload.get('warning_count')}; "
                f"local artifact store {local_store_status}"
            ),
            "omh cases readiness --json",
            use_case_readiness_failures,
            use_case_readiness_warnings,
            str(use_case_readiness_payload.get("boundary", "")),
        ),
        _product_readiness_gate(
            "grounded_score",
            "Grounded routing score",
            "passed" if not grounded_score_errors else "failed",
            True,
            _grounded_score_summary_text(grounded_score),
            "omh demo grounded-score --json",
            grounded_score_errors,
            [],
            str(grounded_score.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "chat_card_coverage",
            "Wrapper chat card coverage",
            "passed" if not chat_card_errors else "failed",
            True,
            (
                f"{chat_card_summary.get('passing_count', 0)}/{chat_card_summary.get('case_count', 0)} "
                f"dedicated workflow cards; generic ack {chat_card_summary.get('generic_ack_count', 0)}"
            ),
            "omh demo chat-card-coverage --json",
            chat_card_errors,
            [],
            str(chat_cards.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "route_hint_alignment",
            "Route and awareness hint alignment",
            "passed" if not route_hint_errors else "failed",
            True,
            (
                f"{route_hint_summary.get('aligned_count', 0)}/{route_hint_summary.get('case_count', 0)} "
                f"route hints aligned; missing {route_hint_summary.get('missing_hint_count', 0)}; "
                f"mismatches {route_hint_summary.get('mismatch_count', 0)}"
            ),
            "omh demo route-hint-alignment --json",
            route_hint_errors,
            [],
            str(route_hints.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "context_brief_coverage",
            "Hermes context brief coverage",
            "passed" if not context_brief_errors else "failed",
            True,
            (
                f"{context_brief_summary.get('passing_count', 0)}/{context_brief_summary.get('case_count', 0)} "
                f"context brief cases passing; route hints {context_brief_summary.get('route_hint_count', 0)}; "
                f"catalog picker hints {context_brief_summary.get('catalog_question_count', 0)}"
            ),
            "omh demo context-brief-coverage --json",
            context_brief_errors,
            [],
            str(context_briefs.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "routing_precision",
            "Routing precision boundaries",
            "passed" if not routing_precision_gate_errors else "failed",
            True,
            (
                f"{routing_precision_summary.get('passing_count', 0)}/{routing_precision_summary.get('case_count', 0)} "
                f"negative-control cases; "
                f"{routing_precision_summary.get('intervention_passing_count', 0)}/"
                f"{routing_precision_summary.get('intervention_case_count', 0)} interventions; "
                f"overroutes {routing_precision_summary.get('overroute_count', 0)}; "
                f"catalog pickers {routing_precision_summary.get('catalog_picker_count', 0)}; "
                f"generic ack {routing_precision_summary.get('generic_ack_count', 0)}; "
                f"missed interventions {routing_precision_summary.get('missed_intervention_count', 0)}"
            ),
            "omh demo routing-precision --json",
            routing_precision_gate_errors,
            [],
            str(routing_precision.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "native_competition",
            "Native skill competition",
            "passed" if not native_competition_gate_errors else "failed",
            True,
            (
                f"{native_competition.get('passed_count', 0)}/{native_competition.get('case_count', 0)} "
                "generated-frontmatter comparisons passing"
            ),
            "omh demo native-competition --json",
            native_competition_gate_errors,
            [],
            str(native_competition.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "localized_chat_copy",
            "Localized chat-card framing",
            "passed" if not localized_chat_copy_gate_errors else "failed",
            True,
            (
                f"{localized_chat_copy_summary.get('passing_count', 0)}/"
                f"{localized_chat_copy_summary.get('case_count', 0)} localized card cases; "
                f"locales {localized_chat_copy_summary.get('locale_count', 0)}"
            ),
            "omh demo localized-chat-copy --json",
            localized_chat_copy_gate_errors,
            [],
            str(localized_chat_copy.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "router_fast_path",
            "Router fast-path quality",
            "passed" if not router_fast_path_gate_errors else "failed",
            True,
            (
                f"{router_fast_path_summary.get('passing_count', 0)}/"
                f"{router_fast_path_summary.get('case_count', 0)} fast-path cases; "
                f"missing markers {router_fast_path_summary.get('missing_marker_count', 0)}; "
                f"route mismatches {router_fast_path_summary.get('route_mismatch_count', 0)}"
            ),
            "omh demo router-fast-path --json",
            router_fast_path_gate_errors,
            [],
            str(router_fast_path.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "common_request_coverage",
            "Common Hermes-agent request coverage",
            "passed" if not common_request_gate_errors else "failed",
            True,
            (
                f"{common_request_summary.get('passing_count', 0)}/"
                f"{common_request_summary.get('case_count', 0)} common request cases; "
                f"coverage {common_request_summary.get('coverage_percent', 0)}%; "
                f"target {common_request_coverage.get('target_percent', 0)}%; "
                f"generic ack {common_request_summary.get('generic_ack_count', 0)}; "
                f"popular plugin families {common_request_summary.get('popular_plugin_covered_family_count', 0)}/"
                f"{common_request_summary.get('popular_plugin_family_count', 0)} "
                f"({common_request_summary.get('popular_plugin_weighted_coverage_percent', 0)}%)"
            ),
            "omh demo common-request-coverage --json",
            common_request_gate_errors,
            [],
            str(common_request_coverage.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "hermes_ux_quality",
            "Hermes-facing UX quality",
            "passed" if not hermes_ux_errors else "failed",
            True,
            (
                f"{hermes_ux_summary.get('passing_gate_count', 0)}/{hermes_ux_summary.get('gate_count', 0)} "
                f"UX gates passing; routing avg {hermes_ux_summary.get('grounded_score_average', 0)}; "
                f"generic ack {hermes_ux_summary.get('chat_card_generic_ack_count', 0)}; "
                f"route mismatches {hermes_ux_summary.get('route_hint_mismatch_count', 0)}; "
                f"context {hermes_ux_summary.get('context_brief_passing_count', 0)}/"
                f"{hermes_ux_summary.get('context_brief_cases', 0)}; "
                f"localized {hermes_ux_summary.get('localized_chat_copy_passing_count', 0)}/"
                f"{hermes_ux_summary.get('localized_chat_copy_cases', 0)}; "
                f"fast paths {hermes_ux_summary.get('router_fast_path_passing_count', 0)}/"
                f"{hermes_ux_summary.get('router_fast_path_cases', 0)}; "
                f"common requests {hermes_ux_summary.get('common_request_passing_count', 0)}/"
                f"{hermes_ux_summary.get('common_request_cases', 0)}"
            ),
            "omh demo hermes-ux-quality --json",
            hermes_ux_errors,
            [],
            str(hermes_ux.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "parity_contracts",
            "Common runtime parity contract coverage",
            "passed" if not parity_errors else "failed",
            True,
            (
                f"{parity_summary.get('available', 0)}/{parity_summary.get('capability_count', 0)} "
                "capability axis/axes available"
            ),
            "omh probe --parity --json",
            parity_errors,
            [],
            str(parity.get("claim_boundary", "")),
        ),
        _product_readiness_gate(
            "release_checklist",
            "Release checklist shape",
            "passed" if not missing_checklist_ids and checklist.get("ok") else "failed",
            True,
            f"{checklist.get('required_item_count')} required release gate(s) indexed",
            f"{omh_display} release checklist --version {release_version} --json",
            [f"missing checklist id: {item_id}" for item_id in missing_checklist_ids],
            [],
            str(checklist.get("proof_boundary", "")),
        ),
    ]
    blocking_failures = [gate for gate in gates if gate["blocking"] and gate["status"] != "passed"]
    warnings = [
        str(warning)
        for gate in gates
        for warning in gate.get("warnings", [])
        if warning
    ]
    return {
        "schema_version": PRODUCT_READINESS_SCHEMA,
        "status": "ready" if not blocking_failures else "needs_attention",
        "score": 100 if not blocking_failures else round(((len(gates) - len(blocking_failures)) / max(1, len(gates))) * 100),
        "mode": "live",
        "observed": True,
        "version": release_version,
        "blocking_failures": len(blocking_failures),
        "warning_count": len(warnings),
        "warnings": warnings,
        "local_artifact_store": local_store_status,
        "gates": gates,
        "next_actions": _product_readiness_next_actions(blocking_failures, warnings),
        "boundary": (
            "Product readiness proves deterministic local OMH package and product contracts only. "
            "It does not run the release checklist, mutate Hermes, prove live Hermes chat selection, "
            "run connectors, dispatch executors, review code, pass CI, merge, deliver messages, or spend provider budget."
        ),
    }


def hermes_release_smoke_steps(
    *,
    install_path: str,
    skill: str = DEFAULT_HERMES_SKILL,
    tap: str = DEFAULT_HERMES_TAP,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> list[HermesSmokeStep]:
    if install_path not in INSTALL_PATHS:
        raise ValueError(f"unsupported Hermes install path: {install_path}")
    if not skill:
        raise ValueError("Hermes smoke skill must not be empty")
    if install_path == "tap" and not tap:
        raise ValueError("Hermes smoke tap must not be empty for tap installs")
    skill_name = _skill_name_for_hermes(skill)
    tap_identifier = _tap_skill_identifier(tap=tap, skill=skill)
    setup_command = _omh_scoped_command(
        omh_command,
        "setup",
        omh_home=omh_home,
        hermes_home=hermes_home,
    )
    doctor_command = _omh_scoped_command(
        omh_command,
        "doctor",
        omh_home=omh_home,
        hermes_home=hermes_home,
    )
    install_steps = (
        [
            HermesSmokeStep(
                "tap_add",
                ("hermes", "skills", "tap", "add", tap),
                "install",
                True,
                proof_boundary="Registers the OMH GitHub tap in the current Hermes profile; this is setup evidence only.",
            ),
            HermesSmokeStep(
                "skill_install",
                ("hermes", "skills", "install", tap_identifier, "--yes"),
                "install",
                True,
                proof_boundary=(
                    "Installs the router skill by full GitHub identifier in the current Hermes profile; "
                    "this does not prove chat usage."
                ),
            ),
        ]
        if install_path == "tap"
        else [
            HermesSmokeStep(
                "omh_setup",
                setup_command,
                "install",
                True,
                proof_boundary="Bootstraps generated skills and skills.external_dirs for the current Hermes home.",
            )
        ]
    )
    check_steps = [
        HermesSmokeStep(
            "tap_list",
            ("hermes", "skills", "tap", "list"),
            "verify",
            False,
            proof_boundary="Shows configured taps; absence means tap install has not been observed.",
        ),
        HermesSmokeStep(
            "skills_list",
            ("hermes", "skills", "list", "--enabled-only"),
            "verify",
            False,
            proof_boundary="Shows enabled Hermes skills; the OMH router should be visible after install/reload.",
        ),
        HermesSmokeStep(
            "skill_check",
            ("hermes", "skills", "check", skill_name),
            "verify",
            False,
            proof_boundary="Runs Hermes skill validation for the OMH router skill.",
        ),
    ]
    if install_path == "tap":
        check_steps.append(
            HermesSmokeStep(
                "skill_inspect",
                ("hermes", "skills", "inspect", tap_identifier),
                "verify",
                False,
                proof_boundary="Prints Hermes-visible skill metadata/content for operator confirmation.",
            )
        )
    else:
        check_steps.append(
            HermesSmokeStep(
                "setup_doctor",
                doctor_command,
                "verify",
                False,
                proof_boundary=(
                    "Checks OMH-managed local skill registration. Hermes v0.15.1 does not reliably inspect "
                    "skills.external_dirs local skills by short name, so setup-path smoke uses list/check plus OMH doctor."
                ),
            )
        )
    return install_steps + check_steps


def _skill_name_for_hermes(skill: str) -> str:
    return skill.rstrip("/").split("/")[-1]


def _normalize_release_version(version: str) -> str:
    value = str(version or "").strip()
    if value.startswith("v"):
        value = value[1:]
    if not value:
        raise ValueError("release checklist version must not be empty")
    if not RELEASE_VERSION_RE.fullmatch(value):
        raise ValueError("release checklist version must be a tag-safe version like 1.0.0")
    return value


def _shell_word(value: str) -> str:
    stripped = str(value or "").strip()
    if not stripped:
        raise ValueError("release checklist omh command must not be empty")
    return shlex.quote(stripped)


def _tap_skill_identifier(*, tap: str, skill: str) -> str:
    if "/" in skill:
        return skill
    # The tap path is a real directory in the published repo, and those carry
    # display labels, so a canonical name here would point at nothing.
    return f"{tap.rstrip('/')}/skills/{omh_skill_display_name(skill)}"


def hermes_release_smoke_plan(
    *,
    install_path: str = "tap",
    skill: str = DEFAULT_HERMES_SKILL,
    tap: str = DEFAULT_HERMES_TAP,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    installed_command_smoke: Mapping[str, object] | None = None,
) -> dict[str, object]:
    target = _target_binding(omh_home=omh_home, hermes_home=hermes_home)
    steps = hermes_release_smoke_steps(
        install_path=install_path,
        skill=skill,
        tap=tap,
        omh_command=omh_command,
        omh_home=target["omh_home"],
        hermes_home=target["hermes_home"],
    )
    command_smoke = (
        dict(installed_command_smoke)
        if installed_command_smoke is not None
        else installed_command_smoke_plan(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
        )
    )
    ok = bool(command_smoke.get("ok", True))
    return {
        "schema_version": HERMES_SMOKE_SCHEMA,
        "mode": "plan",
        "ok": ok,
        "observed": False,
        "install_path": install_path,
        "skill": skill,
        "tap": tap,
        "target_binding": target,
        "proof_boundary": (
            "Plan mode does not touch the current Hermes profile and is not evidence that Hermes "
            "installed, loaded, or used OMH. Run with --live against the target profile for observed smoke evidence."
        ),
        "steps": [step.to_payload() for step in steps],
        "installed_command_smoke": command_smoke,
        "first_use_status_smoke": first_use_status_smoke_plan(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
        ),
        "live_command": _live_smoke_command(install_path, target),
    }


def installed_command_smoke_plan(
    *,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> dict[str, object]:
    target = _target_binding(omh_home=omh_home, hermes_home=hermes_home)
    steps = [
        HermesSmokeStep(
            "installed_omh_help",
            (omh_command, "--help"),
            "verify",
            False,
            proof_boundary="Verifies the installed OMH console script is importable and runnable from the current PATH.",
        ),
        HermesSmokeStep(
            "installed_omh_skill_content",
            (omh_command, "release", "skill-content-smoke", "--json"),
            "verify",
            False,
            proof_boundary=(
                "Verifies the installed OMH command package can render router awareness and workflow context rails. "
                "This is package-content evidence only, not Hermes runtime-load evidence."
            ),
        ),
        HermesSmokeStep(
            "installed_omh_setup_plan",
            _omh_release_plan_command(
                omh_command,
                install_path="setup",
                omh_home=target["omh_home"],
                hermes_home=target["hermes_home"],
            ),
            "verify",
            False,
            proof_boundary=(
                "Verifies the installed OMH console script can render the setup-path Hermes smoke plan. "
                "This is still plan evidence, not live Hermes profile mutation."
            ),
        ),
    ]
    return {
        "schema_version": INSTALLED_COMMAND_SMOKE_SCHEMA,
        "mode": "plan",
        "ok": True,
        "observed": False,
        "command_under_test": omh_command,
        "target_binding": target,
        "path_check": installed_command_path_check_plan(omh_command),
        "proof_boundary": (
            "Plan mode lists installed-command checks only. Run release hermes-smoke with "
            "--include-command-smoke to observe PATH resolution and the installed OMH executable."
        ),
        "steps": [step.to_payload() for step in steps],
    }


def skill_content_smoke() -> dict[str, object]:
    templates = {template.name: template.content for template in builtin_skill_templates()}
    workflow_skill_names = set(templates) - {DEFAULT_HERMES_SKILL}
    role_contexts = {role.id: role_file_markdown(role) for role in role_definitions()}
    bundled_role_contexts = _bundled_role_contexts()
    awareness = awareness_primer_payload()
    lane_skill_names = _awareness_lane_skill_names(awareness)
    catalog_skill_names = {definition.name for definition in builtin_definitions()}
    missing_awareness_skills = sorted(workflow_skill_names - lane_skill_names)
    unexpected_awareness_surfaces = sorted(lane_skill_names - catalog_skill_names - set(CONCEPTUAL_AWARENESS_SURFACES))
    standalone_capability_skill_names = standalone_skill_capability_ids()
    standalone_capability_items = standalone_skill_capability_items()
    full_capability_items = skill_capabilities()
    full_playbook_items = playbook_capabilities()
    standalone_playbook_items = standalone_playbook_capability_items()
    full_capability_skill_names = {
        str(item.get("id") or "")
        for item in full_capability_items
        if str(item.get("id") or "")
    }
    missing_full_capability_skills = sorted(workflow_skill_names - full_capability_skill_names)
    missing_standalone_capability_skills = sorted(workflow_skill_names - standalone_capability_skill_names)
    unexpected_standalone_capability_skills = sorted(
        standalone_capability_skill_names - catalog_skill_names - set(CONCEPTUAL_AWARENESS_SURFACES)
    )
    required_standalone_context_fields = {
        "workflow_routing_hint",
        "workflow_context_rule",
        "chat_rule",
        "fallback_rule",
        "evidence_boundary",
        "cross_lane_examples",
    }
    required_playbook_context_fields = {
        "workflow_context_rule",
        "chat_rule",
        "fallback_rule",
        "evidence_boundary",
        "prepared_is_not",
        "pipeline",
        "primary_owner_role",
        "stage_owners",
        "available_wrapper_actions",
        "first_stage",
    }
    missing_standalone_capability_context_skills = sorted(
        str(item.get("id") or "")
        for item in standalone_capability_items
        if str(item.get("id") or "") in workflow_skill_names
        and any(not item.get(field) for field in required_standalone_context_fields)
    )
    missing_full_capability_context_skills = sorted(
        str(item.get("id") or "")
        for item in full_capability_items
        if str(item.get("id") or "") in workflow_skill_names
        and any(not item.get(field) for field in required_standalone_context_fields)
    )
    missing_playbook_context_playbooks = sorted(
        str(item.get("id") or "")
        for item in full_playbook_items
        if any(not item.get(field) for field in required_playbook_context_fields)
    )
    missing_standalone_playbook_context_playbooks = sorted(
        str(item.get("id") or "")
        for item in standalone_playbook_items
        if any(not item.get(field) for field in required_playbook_context_fields)
    )
    required_playbook_ids = {
        "request-to-handoff",
        "safe-feature-change",
        "feedback-triage",
        "research-department",
        "materials-processing",
        "idea-to-deploy",
    }
    full_playbook_ids = {str(item.get("id") or "") for item in full_playbook_items}
    standalone_playbook_ids = {str(item.get("id") or "") for item in standalone_playbook_items}
    missing_required_playbook_capabilities = sorted(required_playbook_ids - full_playbook_ids)
    missing_required_standalone_playbook_capabilities = sorted(required_playbook_ids - standalone_playbook_ids)
    full_capability_skill_section_chars = len(json.dumps(full_capability_items, sort_keys=True, ensure_ascii=False))
    standalone_capability_skill_section_chars = len(
        json.dumps(standalone_capability_items, sort_keys=True, ensure_ascii=False)
    )
    use_case_demo_cards = demo_all_use_cases()
    use_case_demo_failures = _use_case_demo_card_failures(use_case_demo_cards)
    use_case_artifact_bundle = build_all_use_case_artifacts()
    use_case_artifact_failures = _use_case_artifact_failures(use_case_artifact_bundle)
    use_case_replay = replay_use_case_fixtures()
    use_case_replay_failures = _use_case_replay_failures(use_case_replay)
    use_case_readiness_payload = use_case_readiness(None)
    use_case_readiness_failures = _blocking_gate_messages(use_case_readiness_payload)
    use_case_readiness_warnings = _warning_gate_messages(use_case_readiness_payload)
    max_full_capability_skill_chars = max(
        (len(json.dumps(item, sort_keys=True, ensure_ascii=False)) for item in full_capability_items),
        default=0,
    )
    max_standalone_capability_skill_chars = max(
        (len(json.dumps(item, sort_keys=True, ensure_ascii=False)) for item in standalone_capability_items),
        default=0,
    )
    primer_context_chars = len(awareness_primer_context())
    primer_markdown_chars = len(awareness_primer_markdown())
    workflow_context_chars = {
        name: len(awareness_workflow_context_markdown(name))
        for name in sorted(workflow_skill_names)
    }
    role_context_chars = {name: len(context) for name, context in role_contexts.items()}
    oversized_role_contexts = [
        name
        for name, char_count in role_context_chars.items()
        if char_count > ROLE_CONTEXT_CHAR_LIMIT
    ]
    missing_role_context_roles = sorted(
        name
        for name, context in role_contexts.items()
        if any(marker not in context for marker in ROLE_CONTEXT_MARKERS)
    )
    missing_bundled_role_context_roles = sorted(
        name
        for name, context in bundled_role_contexts.items()
        if any(marker not in context for marker in ROLE_CONTEXT_MARKERS)
    )
    missing_bundled_role_files = sorted(set(role_contexts) - set(bundled_role_contexts))
    unexpected_bundled_role_files = sorted(set(bundled_role_contexts) - set(role_contexts))
    stale_bundled_role_context_roles = sorted(
        name
        for name, context in role_contexts.items()
        if bundled_role_contexts.get(name) is not None and bundled_role_contexts[name] != context
    )
    oversized_awareness_contexts = [
        name
        for name, char_count in workflow_context_chars.items()
        if char_count > AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT
    ]
    awareness_budget_failures = []
    if primer_context_chars > AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT:
        awareness_budget_failures.append("awareness_primer_context")
    if primer_markdown_chars > AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT:
        awareness_budget_failures.append("awareness_primer_markdown")
    if oversized_awareness_contexts:
        awareness_budget_failures.append("workflow_context_rail")
    role_context_budget_failures = []
    if oversized_role_contexts:
        role_context_budget_failures.append("role_context")
    capability_budget_failures = []
    if full_capability_skill_section_chars > FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT:
        capability_budget_failures.append("full_capability_skill_section")
    if max_full_capability_skill_chars > FULL_CAPABILITY_SKILL_ITEM_CHAR_LIMIT:
        capability_budget_failures.append("full_capability_skill_item")
    if standalone_capability_skill_section_chars > STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT:
        capability_budget_failures.append("standalone_capability_skill_section")
    if max_standalone_capability_skill_chars > STANDALONE_CAPABILITY_SKILL_ITEM_CHAR_LIMIT:
        capability_budget_failures.append("standalone_capability_skill_item")
    checks: list[dict[str, object]] = []

    def add_check(name: str, marker: str, ok: bool, *, scope: str) -> None:
        checks.append(
            {
                "scope": scope,
                "skill": name,
                "marker": marker,
                "ok": ok,
            }
        )

    router = templates.get(DEFAULT_HERMES_SKILL, "")
    for marker in ROUTER_CONTENT_MARKERS:
        add_check(DEFAULT_HERMES_SKILL, marker, marker in router, scope="router_awareness")

    missing_representative = [name for name in REPRESENTATIVE_CONTEXT_RAIL_SKILLS if name not in templates]
    for name, content in sorted(templates.items()):
        if name == DEFAULT_HERMES_SKILL:
            continue
        for marker in WORKFLOW_CONTEXT_MARKERS:
            add_check(name, marker, marker in content, scope="workflow_context_rail")

    failed_checks = [check for check in checks if not check["ok"]]
    ok = (
        not failed_checks
        and not missing_representative
        and not missing_awareness_skills
        and not unexpected_awareness_surfaces
        and not missing_full_capability_skills
        and not missing_full_capability_context_skills
        and not missing_playbook_context_playbooks
        and not missing_required_playbook_capabilities
        and not missing_standalone_capability_skills
        and not unexpected_standalone_capability_skills
        and not missing_standalone_capability_context_skills
        and not missing_standalone_playbook_context_playbooks
        and not missing_required_standalone_playbook_capabilities
        and not missing_role_context_roles
        and not missing_bundled_role_context_roles
        and not missing_bundled_role_files
        and not unexpected_bundled_role_files
        and not stale_bundled_role_context_roles
        and not awareness_budget_failures
        and not role_context_budget_failures
        and not capability_budget_failures
        and not use_case_demo_failures
        and not use_case_artifact_failures
        and not use_case_replay_failures
        and not use_case_readiness_failures
    )
    return {
        "schema_version": SKILL_CONTENT_SMOKE_SCHEMA,
        "mode": "live",
        "ok": ok,
        "observed": True,
        "skill_count": len(templates),
        "catalog_skill_count": len(catalog_skill_names),
        "router_skill": DEFAULT_HERMES_SKILL,
        "workflow_skill_count": max(len(templates) - 1, 0),
        "non_installed_catalog_surface_count": len(catalog_skill_names - set(templates)),
        "representative_skills": list(REPRESENTATIVE_CONTEXT_RAIL_SKILLS),
        "missing_representative_skills": missing_representative,
        "awareness_lane_skill_count": len(lane_skill_names),
        "missing_awareness_lane_skills": missing_awareness_skills,
        "unexpected_awareness_surfaces": unexpected_awareness_surfaces,
        "allowed_conceptual_awareness_surfaces": list(CONCEPTUAL_AWARENESS_SURFACES),
        "full_capability_skill_count": len(full_capability_skill_names),
        "missing_full_capability_skills": missing_full_capability_skills,
        "missing_full_capability_context_skills": missing_full_capability_context_skills,
        "playbook_capability_count": len(full_playbook_items),
        "standalone_playbook_capability_count": len(standalone_playbook_items),
        "required_playbook_capability_ids": sorted(required_playbook_ids),
        "missing_required_playbook_capabilities": missing_required_playbook_capabilities,
        "missing_required_standalone_playbook_capabilities": missing_required_standalone_playbook_capabilities,
        "missing_playbook_context_playbooks": missing_playbook_context_playbooks,
        "missing_standalone_playbook_context_playbooks": missing_standalone_playbook_context_playbooks,
        "standalone_capability_skill_count": len(standalone_capability_skill_names),
        "missing_standalone_capability_skills": missing_standalone_capability_skills,
        "unexpected_standalone_capability_skills": unexpected_standalone_capability_skills,
        "missing_standalone_capability_context_skills": missing_standalone_capability_context_skills,
        "role_context_count": len(role_contexts),
        "missing_role_context_roles": missing_role_context_roles,
        "bundled_role_context_count": len(bundled_role_contexts),
        "missing_bundled_role_context_roles": missing_bundled_role_context_roles,
        "missing_bundled_role_files": missing_bundled_role_files,
        "unexpected_bundled_role_files": unexpected_bundled_role_files,
        "stale_bundled_role_context_roles": stale_bundled_role_context_roles,
        "required_role_context_markers": list(ROLE_CONTEXT_MARKERS),
        "required_capability_context_fields": sorted(required_standalone_context_fields),
        "required_standalone_capability_context_fields": sorted(required_standalone_context_fields),
        "required_playbook_context_fields": sorted(required_playbook_context_fields),
        "capability_context_char_limits": {
            "full_skill_section": FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
            "full_skill_item": FULL_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
            "standalone_skill_section": STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
            "standalone_skill_item": STANDALONE_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
        },
        "full_capability_skill_section_chars": full_capability_skill_section_chars,
        "max_full_capability_skill_chars": max_full_capability_skill_chars,
        "standalone_capability_skill_section_chars": standalone_capability_skill_section_chars,
        "max_standalone_capability_skill_chars": max_standalone_capability_skill_chars,
        "capability_budget_failures": capability_budget_failures,
        "use_case_demo_collection_schema": use_case_demo_cards.get("schema_version"),
        "use_case_demo_card_count": len(use_case_demo_cards.get("cards", []))
        if isinstance(use_case_demo_cards.get("cards"), list)
        else 0,
        "expected_use_case_demo_card_count": len(USE_CASES),
        "use_case_demo_failures": use_case_demo_failures,
        "use_case_artifact_collection_schema": use_case_artifact_bundle.get("schema_version"),
        "use_case_artifact_count": len(use_case_artifact_bundle.get("artifacts", []))
        if isinstance(use_case_artifact_bundle.get("artifacts"), list)
        else 0,
        "expected_use_case_artifact_count": len(USE_CASES),
        "use_case_artifact_failures": use_case_artifact_failures,
        "use_case_replay_schema": use_case_replay.get("schema_version"),
        "use_case_replay_status": use_case_replay.get("status"),
        "use_case_replay_total": use_case_replay.get("total"),
        "use_case_replay_passed": use_case_replay.get("passed"),
        "expected_use_case_replay_total": use_case_replay.get("expected_total"),
        "use_case_replay_failures": use_case_replay_failures,
        "use_case_readiness_schema": use_case_readiness_payload.get("schema_version"),
        "use_case_readiness_status": use_case_readiness_payload.get("status"),
        "use_case_readiness_score": use_case_readiness_payload.get("score"),
        "use_case_readiness_blocking_failures": use_case_readiness_payload.get("blocking_failures"),
        "use_case_readiness_warning_count": use_case_readiness_payload.get("warning_count"),
        "use_case_readiness_failures": use_case_readiness_failures,
        "use_case_readiness_warnings": use_case_readiness_warnings,
        "use_case_readiness_boundary": use_case_readiness_payload.get("boundary"),
        "awareness_context_char_limits": {
            "primer_context": AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT,
            "primer_markdown": AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT,
            "workflow_context": AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT,
            "role_context": ROLE_CONTEXT_CHAR_LIMIT,
        },
        "awareness_primer_context_chars": primer_context_chars,
        "awareness_primer_markdown_chars": primer_markdown_chars,
        "max_workflow_context_chars": max(workflow_context_chars.values(), default=0),
        "max_role_context_chars": max(role_context_chars.values(), default=0),
        "oversized_awareness_contexts": oversized_awareness_contexts,
        "awareness_budget_failures": awareness_budget_failures,
        "oversized_role_contexts": oversized_role_contexts,
        "role_context_budget_failures": role_context_budget_failures,
        "checked_marker_count": len(checks),
        "failed_checks": failed_checks,
        "proof_boundary": (
            "This validates generated skill guidance inside the current OMH command package. "
            "It does not prove the target Hermes profile installed, loaded, selected, or used those skills in chat."
        ),
    }


def _product_readiness_gate(
    gate_id: str,
    title: str,
    status: str,
    blocking: bool,
    summary: str,
    command: str,
    errors: Sequence[object] | None,
    warnings: Sequence[object] | None,
    proof_boundary: str,
) -> dict[str, object]:
    return {
        "id": gate_id,
        "title": title,
        "status": status,
        "blocking": blocking,
        "summary": summary,
        "command": command,
        "errors": [str(error) for error in errors or []],
        "warnings": [str(warning) for warning in warnings or []],
        "proof_boundary": proof_boundary,
    }


def _skill_content_product_errors(payload: Mapping[str, object]) -> list[str]:
    keys = (
        "failed_checks",
        "missing_representative_skills",
        "missing_awareness_lane_skills",
        "unexpected_awareness_surfaces",
        "missing_full_capability_skills",
        "missing_full_capability_context_skills",
        "missing_playbook_context_playbooks",
        "missing_required_playbook_capabilities",
        "missing_standalone_capability_skills",
        "unexpected_standalone_capability_skills",
        "missing_standalone_capability_context_skills",
        "missing_standalone_playbook_context_playbooks",
        "missing_required_standalone_playbook_capabilities",
        "missing_role_context_roles",
        "missing_bundled_role_context_roles",
        "missing_bundled_role_files",
        "unexpected_bundled_role_files",
        "stale_bundled_role_context_roles",
        "awareness_budget_failures",
        "role_context_budget_failures",
        "capability_budget_failures",
        "use_case_demo_failures",
        "use_case_artifact_failures",
        "use_case_replay_failures",
        "use_case_readiness_failures",
    )
    errors: list[str] = []
    for key in keys:
        values = payload.get(key, [])
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) and values:
            errors.append(f"{key}: {len(values)}")
    if not payload.get("ok"):
        errors.append("skill_content_smoke_ok_false")
    return errors


def _chat_card_coverage_ready(payload: Mapping[str, object]) -> bool:
    return not _chat_card_coverage_errors(payload)


def _grounded_score_ready(payload: Mapping[str, object]) -> bool:
    return not _grounded_score_errors(payload)


def _route_hint_alignment_ready(payload: Mapping[str, object]) -> bool:
    return not _route_hint_alignment_errors(payload)


def _context_brief_coverage_ready(payload: Mapping[str, object]) -> bool:
    return not _context_brief_coverage_errors(payload)


def _grounded_score_summary_text(payload: Mapping[str, object]) -> str:
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return "grounded score summary missing"
    total = int(summary.get("scenario_count", 0) or 0)
    minimum = summary.get("minimum_score", 0)
    average = summary.get("average_score", 0)
    maximum = summary.get("maximum_score", 0)
    perfect_count = sum(
        1
        for scenario in _mapping_rows(payload.get("scenarios"))
        if int(scenario.get("score", 0) or 0) == 10
    )
    return f"{perfect_count}/{total} scenarios at 10/10; min {minimum}, avg {average}, max {maximum}"


def _grounded_score_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return ["summary_missing"]
    if not bool(summary.get("all_10")):
        errors.append("not_all_grounded_scenarios_scored_10")
    if str(summary.get("score_scale") or "") != "0_to_10":
        errors.append(f"unexpected_score_scale: {summary.get('score_scale')}")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, Sequence) or isinstance(scenarios, (str, bytes)):
        errors.append("scenarios_not_sequence")
        return errors
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            errors.append("scenario_not_mapping")
            continue
        score = int(scenario.get("score", 0) or 0)
        if score == 10:
            continue
        scenario_id = str(scenario.get("id") or "unknown")
        failed_checks = [
            str(check.get("name", "unknown"))
            for check in _mapping_rows(scenario.get("checks"))
            if not bool(check.get("passed"))
        ]
        errors.append(f"{scenario_id}: score {score}/10 ({', '.join(failed_checks) or 'unknown check failure'})")
    return errors


def _chat_card_coverage_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return ["summary_missing"]
    if not bool(summary.get("all_passing")):
        errors.append("not_all_card_coverage_cases_passed")
    if int(summary.get("generic_ack_count", 0) or 0) != 0:
        errors.append(f"generic_ack_count: {summary.get('generic_ack_count')}")
    cases = payload.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        errors.append("cases_not_sequence")
        return errors
    for case in cases:
        if not isinstance(case, Mapping) or bool(case.get("passed")):
            continue
        case_id = str(case.get("id") or "unknown")
        issues = case.get("issues")
        if isinstance(issues, Sequence) and not isinstance(issues, (str, bytes)):
            issue_text = ", ".join(str(issue) for issue in issues) or "unknown issue"
        else:
            issue_text = "unknown issue"
        errors.append(f"{case_id}: {issue_text}")
    return errors


def _route_hint_alignment_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return ["summary_missing"]
    if not bool(summary.get("all_aligned")):
        errors.append("not_all_route_hints_aligned")
    if int(summary.get("missing_hint_count", 0) or 0):
        errors.append(f"missing_hint_count: {summary.get('missing_hint_count')}")
    if int(summary.get("mismatch_count", 0) or 0):
        errors.append(f"mismatch_count: {summary.get('mismatch_count')}")
    cases = payload.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        errors.append("cases_not_sequence")
        return errors
    for case in cases:
        if not isinstance(case, Mapping) or bool(case.get("aligned")):
            continue
        errors.append(
            f"{case.get('corpus', 'unknown')}:{case.get('id', 'unknown')}: "
            f"{', '.join(_string_list(case.get('issues'))) or 'unknown alignment failure'}"
        )
    return errors


def _context_brief_coverage_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return ["summary_missing"]
    if not bool(summary.get("all_passing")):
        errors.append("not_all_context_brief_cases_passed")
    if int(summary.get("route_hint_count", 0) or 0) < 1:
        errors.append("route_hint_count_zero")
    if int(summary.get("catalog_question_count", 0) or 0) < 1:
        errors.append("catalog_question_count_zero")
    cases = payload.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        errors.append("cases_not_sequence")
        return errors
    for case in cases:
        if not isinstance(case, Mapping) or bool(case.get("passed")):
            continue
        case_id = str(case.get("id") or "unknown")
        errors.append(f"{case_id}: {', '.join(_string_list(case.get('issues'))) or 'unknown context failure'}")
    return errors


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _blocking_gate_messages(payload: Mapping[str, object]) -> list[str]:
    gates = payload.get("gates", [])
    if not isinstance(gates, Sequence) or isinstance(gates, (str, bytes)):
        return ["gates_not_sequence"]
    messages = []
    for gate in gates:
        if not isinstance(gate, Mapping):
            messages.append("gate_not_mapping")
            continue
        if gate.get("blocking") and gate.get("status") != "passed":
            messages.append(f"{gate.get('id', 'unknown')}: {gate.get('summary', gate.get('status', 'failed'))}")
    return messages


def _warning_gate_messages(payload: Mapping[str, object]) -> list[str]:
    gates = payload.get("gates", [])
    if not isinstance(gates, Sequence) or isinstance(gates, (str, bytes)):
        return []
    messages = []
    for gate in gates:
        if not isinstance(gate, Mapping):
            continue
        if not gate.get("blocking") and gate.get("status") != "passed":
            messages.append(f"{gate.get('id', 'unknown')}: {gate.get('status', 'warning')}")
    return messages


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value]


def _product_readiness_next_actions(blocking_failures: Sequence[Mapping[str, object]], warnings: Sequence[str]) -> list[str]:
    if blocking_failures:
        return [
            "Fix blocking product readiness gates, then rerun `omh release product-readiness --json`.",
            "Use the per-gate command to inspect the failing contract before tagging.",
        ]
    actions = [
        "Write `omh release evidence-bundle --version <version> --write --json` and attach it to the release notes or PR.",
        "Attach observed evidence for each required release checklist item before tagging or publishing.",
        "Run one live Hermes tap smoke from the target profile before treating Hermes runtime visibility as observed.",
        "Use `omh release product-readiness --json` when a wrapper or release note needs the full machine-readable payload.",
    ]
    if any(warning.startswith("local_artifact_store:") for warning in warnings):
        actions.insert(0, "Optional: write local use-case artifacts with `omh cases artifact --all --write --json`.")
    elif warnings:
        actions.insert(0, "Review non-blocking warnings; they should be acknowledged but do not block local product readiness.")
    return actions


def release_evidence_bundle(
    *,
    version: str = __version__,
    omh_command: str = "omh",
    paths: OmhPaths | None = None,
    write: bool = False,
    repo_root: str | Path | None = None,
    artifact: str | Path | None = None,
    archive_digest: str = "",
    artifact_digest: str = "",
    runner: Callable[..., object] | None = None,
) -> dict[str, object]:
    release_version = _normalize_release_version(version)
    resolved_paths = paths or OmhPaths(omh_home=Path("~/.omh").expanduser(), hermes_home=Path("~/.hermes").expanduser())
    probe_kwargs: dict[str, object] = {}
    if runner is not None:
        probe_kwargs["runner"] = runner
    source_identity = probe_source_identity(
        repo_root,
        archive_digest=archive_digest,
        artifact_digest=artifact_digest,
        **probe_kwargs,
    )
    source_identity["input_manifest"] = build_input_manifest(
        source_identity=source_identity,
        paths=resolved_paths,
        artifact=artifact,
    )
    quality_evidence = _build_release_quality_evidence(release_version=release_version, omh_command=omh_command)
    checklist = quality_evidence.checklist
    product = _product_readiness_report_from_evidence(
        release_version=release_version,
        omh_command=omh_command,
        evidence=quality_evidence,
        paths=resolved_paths,
    )
    skill_content = quality_evidence.skill_content
    use_cases = use_case_readiness(resolved_paths)
    grounded_score = quality_evidence.grounded_score
    chat_cards = quality_evidence.chat_cards
    route_hints = quality_evidence.route_hints
    context_briefs = quality_evidence.context_briefs
    routing_precision = quality_evidence.routing_precision
    native_competition = quality_evidence.native_competition
    localized_chat_copy = quality_evidence.localized_chat_copy
    router_fast_path = quality_evidence.router_fast_path
    common_request_coverage = quality_evidence.common_request_coverage
    hermes_ux = quality_evidence.hermes_ux
    parity = quality_evidence.parity
    local_store_status = _release_local_store_status(use_cases)
    required_status = {
        "release_checklist": "passed" if checklist.get("ok") else "failed",
        "product_readiness": "passed" if product.get("status") == "ready" else "failed",
        "skill_content": "passed" if skill_content.get("ok") else "failed",
        "use_case_readiness": "passed" if use_cases.get("blocking_failures") == 0 else "failed",
        "grounded_score": "passed" if _grounded_score_ready(grounded_score) else "failed",
        "chat_card_coverage": "passed" if _chat_card_coverage_ready(chat_cards) else "failed",
        "route_hint_alignment": "passed" if _route_hint_alignment_ready(route_hints) else "failed",
        "context_brief_coverage": "passed" if _context_brief_coverage_ready(context_briefs) else "failed",
        "routing_precision": "passed" if not routing_precision_errors(routing_precision) else "failed",
        "native_competition": "passed" if not native_skill_competition_errors(native_competition) else "failed",
        "localized_chat_copy": "passed" if not localized_chat_copy_errors(localized_chat_copy) else "failed",
        "router_fast_path": "passed" if not router_fast_path_errors(router_fast_path) else "failed",
        "common_request_coverage": "passed" if not common_request_coverage_errors(common_request_coverage) else "failed",
        "hermes_ux_quality": "passed" if not hermes_ux_quality_errors(hermes_ux) else "failed",
        "parity_contracts": "passed" if _parity_contracts_ready(parity) else "failed",
    }
    blocking_failures = [
        f"{gate_id}: {status}"
        for gate_id, status in required_status.items()
        if status != "passed"
    ]
    warnings = []
    if local_store_status != "passed":
        warnings.append(f"local_artifact_store: {local_store_status}")
    identity_available = source_identity.get("identity_status") == "available"
    if not identity_available:
        warnings.append(
            "source_identity: unavailable; pass --repo-root, --archive-digest, or --artifact-digest "
            "so the bundle is bound to an immutable source revision"
        )
    publication_ready = not blocking_failures and identity_available
    grounded_score_summary = grounded_score.get("summary", {}) if isinstance(grounded_score.get("summary"), Mapping) else {}
    chat_card_summary = chat_cards.get("summary", {}) if isinstance(chat_cards.get("summary"), Mapping) else {}
    route_hint_summary = route_hints.get("summary", {}) if isinstance(route_hints.get("summary"), Mapping) else {}
    context_brief_summary = (
        context_briefs.get("summary", {}) if isinstance(context_briefs.get("summary"), Mapping) else {}
    )
    routing_precision_summary = (
        routing_precision.get("summary", {}) if isinstance(routing_precision.get("summary"), Mapping) else {}
    )
    localized_chat_copy_summary = (
        localized_chat_copy.get("summary", {}) if isinstance(localized_chat_copy.get("summary"), Mapping) else {}
    )
    router_fast_path_summary = (
        router_fast_path.get("summary", {}) if isinstance(router_fast_path.get("summary"), Mapping) else {}
    )
    common_request_summary = (
        common_request_coverage.get("summary", {})
        if isinstance(common_request_coverage.get("summary"), Mapping)
        else {}
    )
    hermes_ux_summary = hermes_ux.get("summary", {}) if isinstance(hermes_ux.get("summary"), Mapping) else {}
    payload: dict[str, object] = {
        "schema_version": RELEASE_EVIDENCE_BUNDLE_SCHEMA,
        "mode": "live",
        "observed": True,
        "written": False,
        "version": release_version,
        "tag": f"v{release_version}",
        "created_at": utc_now(),
        "status": "ready" if not blocking_failures and (identity_available or not write) else "needs_attention",
        "publication_ready": publication_ready,
        "blocking_failures": blocking_failures,
        "warnings": warnings,
        "source_identity": source_identity,
        "summary": {
            "release_checklist_required_items": checklist.get("required_item_count"),
            "product_readiness_status": product.get("status"),
            "product_readiness_score": product.get("score"),
            "skill_content_ok": skill_content.get("ok"),
            "use_case_readiness_status": use_cases.get("status"),
            "use_case_readiness_score": use_cases.get("score"),
            "grounded_score_perfect": sum(
                1
                for scenario in _mapping_rows(grounded_score.get("scenarios"))
                if int(scenario.get("score", 0) or 0) == 10
            ),
            "grounded_score_total": grounded_score_summary.get("scenario_count"),
            "grounded_score_average": grounded_score_summary.get("average_score"),
            "chat_card_coverage_passing": chat_card_summary.get("passing_count"),
            "chat_card_coverage_total": chat_card_summary.get("case_count"),
            "chat_card_generic_ack_count": chat_card_summary.get("generic_ack_count"),
            "route_hint_alignment_aligned": route_hint_summary.get("aligned_count"),
            "route_hint_alignment_total": route_hint_summary.get("case_count"),
            "route_hint_missing_count": route_hint_summary.get("missing_hint_count"),
            "route_hint_mismatch_count": route_hint_summary.get("mismatch_count"),
            "context_brief_coverage_passing": context_brief_summary.get("passing_count"),
            "context_brief_coverage_total": context_brief_summary.get("case_count"),
            "context_brief_route_hint_count": context_brief_summary.get("route_hint_count"),
            "context_brief_catalog_question_count": context_brief_summary.get("catalog_question_count"),
            "routing_precision_passing": routing_precision_summary.get("passing_count"),
            "routing_precision_total": routing_precision_summary.get("case_count"),
            "routing_precision_overroute_count": routing_precision_summary.get("overroute_count"),
            "routing_precision_catalog_picker_count": routing_precision_summary.get("catalog_picker_count"),
            "routing_precision_generic_ack_count": routing_precision_summary.get("generic_ack_count"),
            "routing_precision_intervention_passing": routing_precision_summary.get("intervention_passing_count"),
            "routing_precision_intervention_total": routing_precision_summary.get("intervention_case_count"),
            "routing_precision_missed_intervention_count": routing_precision_summary.get("missed_intervention_count"),
            "native_competition_passing_cases": native_competition.get("passed_count"),
            "native_competition_total_cases": native_competition.get("case_count"),
            "localized_chat_copy_passing": localized_chat_copy_summary.get("passing_count"),
            "localized_chat_copy_total": localized_chat_copy_summary.get("case_count"),
            "localized_chat_copy_locale_count": localized_chat_copy_summary.get("locale_count"),
            "router_fast_path_passing": router_fast_path_summary.get("passing_count"),
            "router_fast_path_total": router_fast_path_summary.get("case_count"),
            "router_fast_path_missing_marker_count": router_fast_path_summary.get("missing_marker_count"),
            "common_request_coverage_passing": common_request_summary.get("passing_count"),
            "common_request_coverage_total": common_request_summary.get("case_count"),
            "common_request_coverage_percent": common_request_summary.get("coverage_percent"),
            "common_request_coverage_target": common_request_coverage.get("target_percent"),
            "common_request_generic_ack_count": common_request_summary.get("generic_ack_count"),
            "popular_plugin_family_covered": common_request_summary.get("popular_plugin_covered_family_count"),
            "popular_plugin_family_total": common_request_summary.get("popular_plugin_family_count"),
            "popular_plugin_weighted_coverage_percent": common_request_summary.get(
                "popular_plugin_weighted_coverage_percent"
            ),
            "hermes_ux_quality_score": hermes_ux.get("score"),
            "hermes_ux_quality_passing_gates": hermes_ux_summary.get("passing_gate_count"),
            "hermes_ux_quality_total_gates": hermes_ux_summary.get("gate_count"),
            "local_artifact_store": local_store_status,
            "parity_available": (parity.get("summary") or {}).get("available")
            if isinstance(parity.get("summary"), Mapping)
            else None,
            "parity_capability_count": (parity.get("summary") or {}).get("capability_count")
            if isinstance(parity.get("summary"), Mapping)
            else None,
        },
        "evidence": {
            "release_checklist": checklist,
            "product_readiness": product,
            "skill_content": skill_content,
            "use_case_readiness": use_cases,
            "grounded_score": grounded_score,
            "chat_card_coverage": chat_cards,
            "route_hint_alignment": route_hints,
            "context_brief_coverage": context_briefs,
            "routing_precision": routing_precision,
            "native_competition": native_competition,
            "localized_chat_copy": localized_chat_copy,
            "router_fast_path": router_fast_path,
            "common_request_coverage": common_request_coverage,
            "hermes_ux_quality": hermes_ux,
            "parity_contracts": parity,
        },
        "claims": [
            "deterministic_local_package_contracts_checked",
            "release_checklist_indexed",
            "product_readiness_rollup_ready",
            "skill_content_smoke_ready",
            "g1_to_g10_use_case_readiness_ready",
            "grounded_score_ready",
            "chat_card_coverage_ready",
            "route_hint_alignment_ready",
            "context_brief_coverage_ready",
            "routing_precision_ready",
            "native_competition_ready",
            "localized_chat_copy_ready",
            "router_fast_path_ready",
            "common_request_coverage_ready",
            "hermes_ux_quality_ready",
            "parity_contract_matrix_ready",
            "source_revision_bound",
            "input_manifest_digest_recorded",
        ],
        "not_evidence_for": [
            "live_hermes_chat_selection",
            "connector_execution",
            "executor_dispatch",
            "implementation",
            "review",
            "ci",
            "merge",
            "delivery",
            "billing_or_provider_budget",
            "github_release_publication",
        ],
        "next_actions": _release_evidence_next_actions(blocking_failures, local_store_status),
        "boundary": (
            "A release evidence bundle packages deterministic local OMH evidence and optional local artifact-store state, "
            "bound to the recorded source revision and declared input digests. It proves evidence provenance for the "
            "recorded revision; it does not prove deployment, adoption, or runtime behavior outside the executed gates, "
            "and it does not mutate Hermes, run live profile smoke, call connectors, dispatch executors, review code, "
            "pass CI, merge, deliver messages, publish GitHub releases, or prove provider billing/quota truth."
        ),
    }
    if write:
        artifact_path = resolved_paths.release_evidence_dir / f"{release_version}.json"
        payload["written"] = True
        payload["artifact_path"] = str(artifact_path)
        # The persisted bundle names its artifact by basename only: the file is
        # meant to be attached to release PRs and published as a release asset,
        # so the maintainer's absolute home path must not leak into it. The
        # absolute path stays in the returned (stdout) payload only.
        persisted = dict(payload)
        persisted["artifact_path"] = artifact_path.name
        atomic_write_json(artifact_path, persisted, private=True)
        _write_release_evidence_index(resolved_paths, persisted)
    else:
        payload["artifact_path"] = str(resolved_paths.release_evidence_dir / f"{release_version}.json")
    return payload


def _release_evidence_next_actions(blocking_failures: Sequence[str], local_store_status: str) -> list[str]:
    if blocking_failures:
        return [
            "Fix blocking bundle gates, then rerun `omh release evidence-bundle --write --json`.",
            "Inspect the nested evidence payload for the failing gate before tagging.",
        ]
    actions = [
        "Attach this bundle to the release PR or release notes as local deterministic evidence.",
        "Run the required CI and live Hermes smoke separately; this bundle does not observe those remote/runtime gates.",
    ]
    if local_store_status != "passed":
        actions.insert(0, "Run `omh cases artifact --all --write --json` if you want the optional local use-case artifact store populated.")
    return actions


def _release_local_store_status(use_case_payload: Mapping[str, object]) -> str:
    gates = use_case_payload.get("gates", [])
    if not isinstance(gates, Sequence) or isinstance(gates, (str, bytes)):
        return "unknown"
    for gate in gates:
        if isinstance(gate, Mapping) and gate.get("id") == "local_artifact_store":
            return str(gate.get("status") or "unknown")
    return "missing"


def _parity_contracts_ready(payload: Mapping[str, object]) -> bool:
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return False
    for key in ("partial", "planned", "deferred"):
        if int(summary.get(key, 0) or 0) != 0:
            return False
    return int(summary.get("available", 0) or 0) == int(summary.get("capability_count", 0) or 0)


def _write_release_evidence_index(paths: OmhPaths, payload: Mapping[str, object]) -> None:
    version = str(payload.get("version") or "")
    artifact_path = str(payload.get("artifact_path") or "")
    existing, _ = read_json_object_result(paths.release_evidence_index_path)
    entries = []
    if existing and isinstance(existing.get("entries"), list):
        entries = [entry for entry in existing["entries"] if isinstance(entry, dict) and entry.get("version") != version]
    source_identity = payload.get("source_identity")
    if not isinstance(source_identity, Mapping):
        source_identity = {}
    entries.append(
        {
            "version": version,
            "tag": payload.get("tag"),
            "status": payload.get("status"),
            "created_at": payload.get("created_at"),
            "artifact_path": artifact_path,
            "schema_version": payload.get("schema_version"),
            "commit_sha": source_identity.get("commit_sha"),
            "tree_sha": source_identity.get("tree_sha"),
        }
    )
    entries.sort(key=lambda entry: str(entry.get("created_at") or ""))
    index = {
        "schema_version": "omh_release_evidence_index/v1",
        "latest_version": version,
        "latest_artifact_path": artifact_path,
        "count": len(entries),
        "entries": entries,
    }
    atomic_write_json(paths.release_evidence_index_path, index, private=True)


def _use_case_demo_card_failures(payload: Mapping[str, object]) -> list[str]:
    failures: list[str] = []
    if payload.get("schema_version") != "omh_use_case_demo_collection/v1":
        failures.append("collection_schema")
    cards = payload.get("cards", [])
    if not isinstance(cards, Sequence) or isinstance(cards, (str, bytes)):
        return failures + ["cards_not_sequence"]
    if len(cards) != len(USE_CASES):
        failures.append("card_count")
    expected_goals = [case.goal for case in USE_CASES]
    observed_goals: list[str] = []
    for index, card in enumerate(cards):
        if not isinstance(card, Mapping):
            failures.append(f"card_{index}_not_mapping")
            continue
        goal = str(card.get("goal") or "")
        observed_goals.append(goal)
        if card.get("schema_version") != "omh_use_case_demo_card/v1":
            failures.append(f"{goal or index}_schema")
        route = card.get("route")
        wrapper_card = card.get("wrapper_card")
        evidence = card.get("evidence")
        actions = card.get("actions")
        chat_surface = card.get("chat_surface")
        if not isinstance(route, Mapping) or not route.get("primary_skill") or not route.get("next_action"):
            failures.append(f"{goal or index}_route")
        if not isinstance(wrapper_card, Mapping) or wrapper_card.get("component") != "omh_use_case_card":
            failures.append(f"{goal or index}_wrapper_card")
        if isinstance(wrapper_card, Mapping) and wrapper_card.get("status") != "prepared_not_observed":
            failures.append(f"{goal or index}_wrapper_status")
        if not isinstance(evidence, Mapping) or evidence.get("state") != "prepared_not_observed":
            failures.append(f"{goal or index}_evidence_state")
        boundary = str(evidence.get("claim_boundary") if isinstance(evidence, Mapping) else "")
        if "not " not in boundary.casefold() or "evidence" not in boundary.casefold():
            failures.append(f"{goal or index}_boundary")
        if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)) or not actions:
            failures.append(f"{goal or index}_actions")
        elif isinstance(route, Mapping) and isinstance(actions[0], Mapping) and actions[0].get("id") != route.get("next_action"):
            failures.append(f"{goal or index}_primary_action")
        if not isinstance(chat_surface, Mapping) or not str(chat_surface.get("headline") or "").startswith("[omh] "):
            failures.append(f"{goal or index}_chat_surface")
    if observed_goals != expected_goals:
        failures.append("goal_order")
    return failures


def _use_case_artifact_failures(payload: Mapping[str, object]) -> list[str]:
    failures: list[str] = []
    if payload.get("schema_version") != "omh_use_case_artifact_collection/v1":
        failures.append("collection_schema")
    artifacts = payload.get("artifacts", [])
    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        return failures + ["artifacts_not_sequence"]
    if len(artifacts) != len(USE_CASES):
        failures.append("artifact_count")
    expected_goals = [case.goal for case in USE_CASES]
    observed_goals: list[str] = []
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            failures.append(f"artifact_{index}_not_mapping")
            continue
        goal = str(artifact.get("goal") or "")
        observed_goals.append(goal)
        for error in validate_use_case_artifact(artifact):
            failures.append(f"{goal or index}: {error}")
        steps = artifact.get("operator_steps", [])
        if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
            failures.append(f"{goal or index}_operator_steps")
        elif not any(isinstance(step, Mapping) and step.get("kind") == "hermes_prompt" for step in steps):
            failures.append(f"{goal or index}_missing_hermes_prompt_step")
        proof_surfaces = artifact.get("proof_surfaces", [])
        if not isinstance(proof_surfaces, Sequence) or isinstance(proof_surfaces, (str, bytes)):
            failures.append(f"{goal or index}_proof_surfaces")
        elif "omh cases validate --json" not in proof_surfaces:
            failures.append(f"{goal or index}_missing_validate_surface")
    if observed_goals != expected_goals:
        failures.append("goal_order")
    return failures


def _use_case_replay_failures(payload: Mapping[str, object]) -> list[str]:
    failures: list[str] = []
    if payload.get("schema_version") != "omh_use_case_replay/v1":
        failures.append("schema")
    if payload.get("status") != "passed":
        failures.append("status")
    results = payload.get("results", [])
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        return failures + ["results_not_sequence"]
    expected_goals = {case.goal for case in USE_CASES}
    covered_goals = {str(result.get("goal", "")) for result in results if isinstance(result, Mapping)}
    if covered_goals != expected_goals:
        failures.append("goal_coverage")
    if len(results) < len(USE_CASES):
        failures.append("fixture_count")
    for index, result in enumerate(results):
        if not isinstance(result, Mapping):
            failures.append(f"result_{index}_not_mapping")
            continue
        if result.get("status") != "passed":
            failures.append(f"{result.get('fixture_id', index)}_failed")
        expected = result.get("expected", {})
        observed = result.get("observed", {})
        if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
            failures.append(f"{result.get('fixture_id', index)}_route_shape")
            continue
        if expected.get("goal") != observed.get("goal"):
            failures.append(f"{result.get('fixture_id', index)}_goal")
        if expected.get("primary_skill") != observed.get("primary_skill"):
            failures.append(f"{result.get('fixture_id', index)}_primary_skill")
    return failures


def _bundled_role_contexts() -> dict[str, str]:
    try:
        root = resources.files("omh.plugin_bundle.omh.references")
    except (ModuleNotFoundError, FileNotFoundError):
        return {}
    contexts: dict[str, str] = {}
    for path in root.iterdir():
        if not path.is_file() or not path.name.startswith("role-") or path.name == "role-.md":
            continue
        role_id = path.name.removeprefix("role-").removesuffix(".md")
        try:
            contexts[role_id] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return contexts


def _awareness_lane_skill_names(payload: Mapping[str, object]) -> set[str]:
    names: set[str] = set()
    lanes = payload.get("lanes", [])
    if not isinstance(lanes, Sequence) or isinstance(lanes, (str, bytes)):
        return names
    for lane in lanes:
        if not isinstance(lane, Mapping):
            continue
        skills = lane.get("skills", [])
        if not isinstance(skills, Sequence) or isinstance(skills, (str, bytes)):
            continue
        names.update(str(skill) for skill in skills)
    return names


def first_use_status_smoke_plan(
    *,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    message: str = DEFAULT_FIRST_USE_MESSAGE,
) -> dict[str, object]:
    target = _target_binding(omh_home=omh_home, hermes_home=hermes_home)
    session_id = "<session_id>"
    return {
        "schema_version": FIRST_USE_STATUS_SMOKE_SCHEMA,
        "mode": "plan",
        "ok": True,
        "observed": False,
        "example_message": message,
        "target_binding": target,
        "proof_boundary": (
            "This first-use smoke is fixture-backed guidance for wrapper/Hermes status UX. It does not prove "
            "a live chat selected OMH unless the wrapper records that chat response."
        ),
        "steps": [
            {
                "name": "chat_session_start",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "start",
                        "--source",
                        "hermes",
                        "--source-event-id",
                        "release-smoke-message",
                        "--channel-ref",
                        "release-smoke",
                        message,
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "Creates or resumes a metadata-only wrapper session and returns a status card without executor open/result actions.",
                "proof_boundary": "Starting a wrapper session is routing/status evidence only; it is not execution evidence.",
            },
            {
                "name": "chat_session_accept_plan",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "accept-plan",
                        session_id,
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "Records explicit plan acceptance before any coding handoff can be prepared.",
                "proof_boundary": "Plan acceptance is a wrapper decision; it is still not dispatch or execution evidence.",
            },
            {
                "name": "chat_session_select_executor",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "select-executor",
                        session_id,
                        "codex",
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "Records the selected coding agent before backend open/attach actions become visible.",
                "proof_boundary": "Executor selection is not executor dispatch; it only chooses the handoff target.",
            },
            {
                "name": "chat_session_prepare_handoff",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "prepare-handoff",
                        session_id,
                        message,
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "Prepares the coding handoff while keeping dispatch/result/verification not observed.",
                "proof_boundary": "A prepared handoff is not an observed executor open, result, review, CI, or merge.",
            },
            {
                "name": "chat_session_status_after_handoff",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "status",
                        session_id,
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "After plan acceptance, executor selection, and handoff preparation, status shows prepared handoff without observed dispatch/result.",
                "proof_boundary": "Prepared handoff status remains prepared_not_observed until dispatch/result evidence is recorded.",
            },
        ],
        "expected_status_boundary": {
            "before_handoff": {
                "executor_actions_visible": False,
                "forbidden_action_ids": [
                    "open_executor_session",
                    "attach_executor_session",
                    "record_executor_completed",
                    "record_executor_blocked",
                    "record_executor_failed",
                    "ask_hermes_verify",
                ],
            },
            "after_handoff": {
                "handoff": "prepared",
                "dispatch": "not_observed",
                "result": "not_observed",
                "verification": "not_requested",
            },
        },
    }


def run_hermes_release_smoke(
    *,
    install_path: str = "tap",
    skill: str = DEFAULT_HERMES_SKILL,
    tap: str = DEFAULT_HERMES_TAP,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    timeout_seconds: int = 30,
    runner: Runner | None = None,
    include_command_smoke: bool = False,
) -> dict[str, object]:
    if timeout_seconds < 1:
        raise ValueError("Hermes smoke timeout must be at least one second")
    target = _target_binding(omh_home=omh_home, hermes_home=hermes_home)
    steps = hermes_release_smoke_steps(
        install_path=install_path,
        skill=skill,
        tap=tap,
        omh_command=omh_command,
        omh_home=target["omh_home"],
        hermes_home=target["hermes_home"],
    )
    execute = runner or subprocess_runner
    command_smoke = (
        run_installed_command_smoke(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
            timeout_seconds=timeout_seconds,
            runner=execute,
        )
        if include_command_smoke
        else installed_command_smoke_plan(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
        )
    )
    hermes_path = shutil.which("hermes")
    if include_command_smoke and not bool(command_smoke.get("ok", False)):
        return {
            "schema_version": HERMES_SMOKE_SCHEMA,
            "mode": "live",
            "ok": False,
            "observed": bool(command_smoke.get("observed", False)),
            "install_path": install_path,
            "skill": skill,
            "tap": tap,
            "target_binding": target,
            "hermes_cli": {"found": bool(hermes_path), "path": hermes_path},
            "results": [],
            "installed_command_smoke": command_smoke,
            "first_use_status_smoke": first_use_status_smoke_plan(
                omh_command=omh_command,
                omh_home=target["omh_home"],
                hermes_home=target["hermes_home"],
            ),
            "failed_step": "installed_command_smoke",
            "recommended_next_action": _hermes_smoke_next_action(False, "installed_command_smoke"),
            "proof_boundary": (
                "Installed command smoke failed before live Hermes profile mutation. No Hermes install, list, "
                "check, or inspect command was run."
            ),
        }
    results: list[dict[str, object]] = []
    smoke_env = {"HERMES_HOME": str(target["hermes_home"])}
    if not hermes_path:
        return {
            "schema_version": HERMES_SMOKE_SCHEMA,
            "mode": "live",
            "ok": False,
            "observed": False,
            "install_path": install_path,
            "skill": skill,
            "tap": tap,
            "target_binding": target,
            "hermes_cli": {"found": False, "path": None},
            "results": [],
            "installed_command_smoke": command_smoke,
            "first_use_status_smoke": first_use_status_smoke_plan(
                omh_command=omh_command,
                omh_home=target["omh_home"],
                hermes_home=target["hermes_home"],
            ),
            "failed_step": "hermes_cli",
            "recommended_next_action": "Install Hermes Agent CLI or run this smoke from the target Hermes profile.",
            "proof_boundary": "No Hermes CLI was observed, so no Hermes install, list, check, or inspect evidence exists.",
        }
    ok = True
    failed_step = ""
    for step in steps:
        result = execute(step.command, timeout_seconds, smoke_env)
        step_ok = result.returncode == 0
        ok = ok and step_ok
        results.append(
            {
                **step.to_payload(),
                "returncode": result.returncode,
                "ok": step_ok,
                "environment": {"HERMES_HOME": smoke_env["HERMES_HOME"]},
                "stdout_excerpt": bounded_text(result.stdout),
                "stderr_excerpt": bounded_text(result.stderr),
            }
        )
        if not step_ok and not failed_step:
            failed_step = step.name
            if step.required:
                break
    if include_command_smoke and not bool(command_smoke.get("ok", False)):
        ok = False
        if not failed_step:
            failed_step = "installed_command_smoke"
    return {
        "schema_version": HERMES_SMOKE_SCHEMA,
        "mode": "live",
        "ok": ok,
        "observed": bool(results),
        "install_path": install_path,
        "skill": skill,
        "tap": tap,
        "target_binding": target,
        "hermes_cli": {"found": True, "path": hermes_path},
        "results": results,
        "installed_command_smoke": command_smoke,
        "first_use_status_smoke": first_use_status_smoke_plan(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
        ),
        "failed_step": failed_step,
        "recommended_next_action": _hermes_smoke_next_action(ok, failed_step),
        "proof_boundary": (
            "Live smoke observes Hermes CLI install/list/check/inspect command results only. "
            "It still does not prove a later chat session selected OMH unless that session is observed separately."
        ),
    }


def run_installed_command_smoke(
    *,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    timeout_seconds: int = 30,
    runner: Runner | None = None,
) -> dict[str, object]:
    if timeout_seconds < 1:
        raise ValueError("Installed command smoke timeout must be at least one second")
    plan = installed_command_smoke_plan(omh_command=omh_command, omh_home=omh_home, hermes_home=hermes_home)
    target = plan["target_binding"]
    execute = runner or subprocess_runner
    path_check = inspect_installed_command_path(omh_command)
    if not bool(path_check["ok"]):
        return {
            "schema_version": INSTALLED_COMMAND_SMOKE_SCHEMA,
            "mode": "live",
            "ok": False,
            "observed": False,
            "command_under_test": omh_command,
            "target_binding": target,
            "path_check": path_check,
            "results": [],
            "failed_step": "installed_omh_path",
            "recommended_next_action": _installed_command_smoke_next_action(
                False,
                "installed_omh_path",
                command_under_test=omh_command,
            ),
            "proof_boundary": (
                "Installed command smoke did not execute because the OMH command was not discoverable or "
                "executable. PATH resolution is recorded separately in path_check."
            ),
        }
    results: list[dict[str, object]] = []
    ok = True
    failed_step = ""
    for raw_step in plan["steps"]:
        step = HermesSmokeStep(
            str(raw_step["name"]),
            tuple(str(part) for part in raw_step["command"]),
            str(raw_step["phase"]),
            bool(raw_step["mutates_profile"]),
            required=bool(raw_step["required"]),
            proof_boundary=str(raw_step["proof_boundary"]),
        )
        result = execute(step.command, timeout_seconds, None)
        step_ok = result.returncode == 0
        ok = ok and step_ok
        results.append(
            {
                **step.to_payload(),
                "returncode": result.returncode,
                "ok": step_ok,
                "stdout_excerpt": bounded_text(result.stdout),
                "stderr_excerpt": bounded_text(result.stderr),
            }
        )
        if not step_ok and not failed_step:
            failed_step = step.name
            if step.required:
                break
    return {
        "schema_version": INSTALLED_COMMAND_SMOKE_SCHEMA,
        "mode": "live",
        "ok": ok,
        "observed": bool(results),
        "command_under_test": omh_command,
        "target_binding": target,
        "path_check": path_check,
        "results": results,
        "failed_step": failed_step,
        "recommended_next_action": _installed_command_smoke_next_action(
            ok,
            failed_step,
            command_under_test=omh_command,
        ),
        "proof_boundary": (
            "Installed command smoke observes the OMH console script, generated skill guidance, and plan rendering only. "
            "It does not mutate Hermes or prove live chat usage."
        ),
    }


def _target_binding(*, omh_home: str | Path | None = None, hermes_home: str | Path | None = None) -> dict[str, object]:
    omh = expand_home(omh_home, "OMH_HOME", "~/.omh")
    hermes = expand_home(hermes_home, "HERMES_HOME", "~/.hermes")
    return {
        "omh_home": str(omh),
        "hermes_home": str(hermes),
        "explicit_omh_home": omh_home is not None,
        "explicit_hermes_home": hermes_home is not None,
        "hermes_env_key": "HERMES_HOME",
        "proof_boundary": "Live smoke binds Hermes CLI subprocesses to this HERMES_HOME; it does not prove another profile was checked.",
    }

def _omh_scoped_command(
    omh_command: str,
    *command_parts: str,
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> tuple[str, ...]:
    command = list(_omh_base_command(omh_command, omh_home=omh_home, hermes_home=hermes_home))
    command.extend(command_parts)
    return tuple(command)


def _omh_base_command(
    omh_command: str,
    *,
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> tuple[str, ...]:
    command = [omh_command]
    if omh_home is not None:
        command.extend(["--omh-home", str(omh_home)])
    if hermes_home is not None:
        command.extend(["--hermes-home", str(hermes_home)])
    return tuple(command)


def _omh_release_plan_command(
    omh_command: str,
    *,
    install_path: str,
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> tuple[str, ...]:
    return (
        *_omh_base_command(omh_command, omh_home=omh_home, hermes_home=hermes_home),
        "release",
        "hermes-smoke",
        "--install-path",
        install_path,
        "--omh-command",
        omh_command,
    )


def _live_smoke_command(install_path: str, target: Mapping[str, object]) -> list[str]:
    command = ["omh"]
    if target["explicit_omh_home"]:
        command.extend(["--omh-home", str(target["omh_home"])])
    if target["explicit_hermes_home"]:
        command.extend(["--hermes-home", str(target["hermes_home"])])
    command.extend(["release", "hermes-smoke", "--install-path", install_path, "--live"])
    if not target["explicit_hermes_home"]:
        command.append("--target-confirmed")
    return command


def _hermes_smoke_next_action(ok: bool, failed_step: str) -> str:
    if ok:
        return "Restart or refresh Hermes Agent if required, then try the first OMH Hermes prompt and record the observed response."
    if failed_step == "tap_add":
        return "Check Hermes tap support, network access, and whether the tap is already configured; rerun the smoke after repair."
    if failed_step == "skill_install":
        return (
            "Check tap visibility and Hermes skill scan output, then rerun "
            "`hermes skills install rlaope/oh-my-hermes/skills/omh-routing --yes`."
        )
    if failed_step == "omh_setup":
        return "Run `omh setup` manually and inspect `omh doctor` for blocking setup checks."
    if failed_step == "setup_doctor":
        return "Run `omh doctor` manually and repair the OMH-managed skill registration reported there."
    if failed_step == "installed_command_smoke":
        return (
            "Inspect installed_command_smoke.failed_step, then repair the installed `omh` command path, "
            "console script importability, generated skill content, or setup plan rendering before rerunning "
            "with --include-command-smoke."
        )
    if failed_step in {"tap_list", "skills_list", "skill_check", "skill_inspect"}:
        return "Inspect the failing Hermes skills command output and confirm the target Hermes profile is the one OMH was installed into."
    return "Inspect the failed Hermes release smoke step and rerun after repair."


def _installed_command_smoke_next_action(
    ok: bool,
    failed_step: str,
    *,
    command_under_test: str = "omh",
) -> str:
    command = str(command_under_test or "omh").strip() or "omh"
    if ok:
        return (
            f"Installed `{command}` command path is runnable; "
            "continue with Hermes profile smoke or release tagging."
        )
    if failed_step == "installed_omh_path":
        if path_check_kind(command) == "direct_path":
            return f"Make {shlex.quote(command)} executable, or pass --omh-command with an executable OMH path."
        return (
            f"Install OMH so `command -v {shlex.quote(command)}` resolves, "
            "or pass --omh-command with an executable OMH path."
        )
    if failed_step == "installed_omh_help":
        return "Check PATH, package installation, and console-script importability for `omh`."
    if failed_step == "installed_omh_skill_content":
        return "Run `omh release skill-content-smoke --json` directly and inspect missing router awareness or workflow context rail markers."
    if failed_step == "installed_omh_setup_plan":
        return "Run `omh release hermes-smoke --install-path setup` directly and inspect the console-script error."
    return "Inspect the failed installed command smoke step and rerun after repair."
