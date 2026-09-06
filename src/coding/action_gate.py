"""One decision path for task-scoped authority on the coding delegation lane.

Four independent "ask the user" ladders used to live side by side and none of
them knew about the others:

1. ``executor_selection.choice_required`` -> ``choose_executor``
2. ``permission_profile_required`` -> ``choose_permission_profile``
3. the risky-action confirmation (#800) -> ``confirm_risky_action``
4. the operator-card ``confirm_*`` family (and, on the delegation lane, the
   ``send_to_executor`` go-ahead that ``ask_before_dispatch`` implies)

``evaluate_action_gate`` is the only place that decides. It runs exactly once
per delegation build and returns one verdict carrying:

* the safety preflight outcome (allow/deny plus rule id, field, correction),
* the derived task-scoped authority envelope (#811),
* the action-risk verdict and, per risky class, the approval that does or does
  not cover it (#800),
* the account-authorization projection (#799), and
* which single confirmation ladder — at most one — is armed, and why the
  others are suppressed.

``dispatchable`` and ``executor_selection.choice_required`` are then *derived
from* that verdict rather than recomputed, so a denial and a selection can
never disagree into an unconstructible record.

The envelope reuses the goal-loop vocabulary (``PERMISSION_PROFILES``,
``LOOP_ACTIONS``, ``merge_authority``, ``external_action_authority``) so the
loop lane and the handoff lane speak one language. ``omh.workflows.goal_loop``
is imported lazily because ``omh.runtime.records`` imports this module for
validation and the goal-loop import chain reaches ``omh.runtime.artifacts``,
which imports records back.

Authority is derived from user intent plus workspace policy only. Message text,
context packs, and recall packs are inspected for authority-shaped content and
the finding is reported as a surface name — never echoed back, never fed into
the allowed action set.

The same evaluation also produces the *handoff safety contract* (#818): the
task-scoped statement of what this delegation may touch, what it may never do,
and which of those boundaries is actually enforced today. Every boundary entry
carries an ``enforcement`` verdict plus either a real enforcing symbol or the
issue that must land first, because a contract that lists nine boundaries and
guards four reads as coverage that does not exist — strictly worse than no
contract at all.

A boundary is never justified by "no such capability exists". That claim cannot
be enforced and the tree can contradict it: ``omh setup --star`` really does
shell out to ``gh`` to star the repository. Every statement here is therefore
scoped to the surface it actually governs, and a real exception outside that
surface is named in the statement rather than left for a reader to discover.

What action risk reads, and what that does not promise (#800)
-------------------------------------------------------------

``classify_action_risk`` answers "may this act proceed without asking". It
reads the isolation plan's *strategy*, the authority envelope's granted actions,
and the declared safety-preflight request's access intents and target paths. It
never reads message text, a context pack, or a recall pack, and there is no
parameter through which one could arrive — ``safety_preflight``'s own docstring
forbids making a safety decision depend on user text, and
``isolation._risk_level`` is exactly such a decision because it matches
``message.lower()`` against term tables.

That bounds this function and says nothing about how a caller built the request
it hands in. ``external_mutation`` and ``publication`` are decided by the
envelope alone, so no phrasing moves them. ``broad_write`` is decided by
declared request fields, and on the coding-delegation lane those fields are
scraped out of the user's message — so end to end that class *is*
message-sensitive. ``ACTION_RISK_TEXT_POLICY`` names the scraper and the evasion
in those words rather than claiming a property the pipeline does not have.

The two risk levels are named apart and never compared; see
``ACTION_RISK_VS_ISOLATION_RISK``.

Consent is per risky class, and on the shipped lane it is reported (#800/#807)
------------------------------------------------------------------------------

An armed ladder proves a question was asked. ``omh.workflows.approval_receipts``
proves an operator answered it. The gate consults
``approval_satisfies_request_in`` — the pure, already-read-receipts form, so the
gate stays free of I/O — once per (present class, granted action that carries
it), and withholds every action whose approval is missing. There is deliberately
no single collapsed "the approvable action": one answer covering several classes
is several approvals wearing one answer. Matching is equality on all five
dimensions inside that module; there is no containment rule here either, because
there is none to call.

That refusal fires only when the confirmation can be answered. An approval binds
to a run, ``build_approval_receipt`` refuses an empty one, and this module's only
production caller builds its payload before any runtime run exists — so on that
lane no receipt that could release the work is constructible, and withholding
would end the request rather than gate it. ``evaluate_action_gate`` therefore
withholds and arms only when ``run_id`` is set; everywhere else the
classification rides as a report and ``action_risk.enforcement`` /
``action_risk.blocked_by`` say so on the record, and the
``confirmation_answered`` boundary stays ``declared_not_enforced``.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from ..plugin_bundle.omh._governance_safety import classify_memory_admission
from ..system.metadata_safety import is_secret_value_shaped
from ..workflows.approval_receipts import (
    APPROVABLE_ACTIONS,
    REFUSAL_DENIED,
    REFUSAL_REVOKED,
    SCOPE_CLASSES,
    approval_satisfies_request_in,
)
from ..workflows.domain_intelligence_admission import ensure_safe_opaque_ref_content


TASK_AUTHORITY_ENVELOPE_SCHEMA_VERSION = "task_authority_envelope/v1"
ACTION_GATE_SCHEMA_VERSION = "coding_action_gate/v1"
HANDOFF_SAFETY_CONTRACT_SCHEMA_VERSION = "handoff_safety_contract/v1"

AUTHORITY_SOURCES = ("user_intent", "workspace_policy")
UNTRUSTED_SURFACES = ("context_pack", "memory_recall_pack", "message")
AUTHORITY_CLASSIFIERS = (
    "plugin_bundle.omh._governance_safety.classify_memory_admission",
    "workflows.domain_intelligence_admission.ensure_safe_opaque_ref_content",
)
MUTATING_ACTIONS = ("external_posting", "merge", "pr_creation", "pr_revision", "repo_edit")
EXCLUSION_REASON_CODES = (
    "narrowed_by_request",
    "not_required_by_task",
    "outside_permission_profile",
    "safety_preflight_denied",
    "user_authorized_pending_verification",
    "withheld_pending_approval",
)
# A prepared post-verification INTENT record, never an authority grant. When the
# user explicitly asks for a merge or a deploy as the final step, OMH preserves
# that intent through the delegation boundary so a downstream owner stops
# downgrading "user wants merge" into "no merge". It changes no allowed action:
# `merge_authority` stays disabled, `merge` stays blocked, and the receipt gate
# in `runtime.claims` still governs whether anything actually merged. `deploy`
# has no `LOOP_ACTIONS` action, so a deploy directive lives only in the field.
POST_COMPLETION_DIRECTIVE_ACTIONS = ("merge", "deploy")
POST_COMPLETION_DIRECTIVE_STATE = "user_authorized_pending_verification"
# Precedence order, not an alphabetical list. `risky_action` sits between the
# profile question and the dispatch go-ahead on purpose: widening the envelope
# is a bigger question than confirming one risky act inside it, and confirming
# the act is a bigger question than confirming the dispatch that carries it.
CONFIRMATION_LADDERS = (
    "executor_selection",
    "permission_profile",
    "risky_action",
    "operator_confirmation",
)
LADDER_ACTION_IDS = {
    "executor_selection": "choose_executor",
    "permission_profile": "choose_permission_profile",
    "risky_action": "confirm_risky_action",
    "operator_confirmation": "send_to_executor",
}
SINGLE_PROMPT_RULE = (
    "One intent arms at most one confirmation ladder. Precedence: a denial asks nothing, "
    "then executor_selection, then permission_profile, then risky_action, then "
    "operator_confirmation. Every ladder that could have fired is recorded as suppressed "
    "with the winner named. A risky action is never a fourth prompt beside the others: it "
    "is a ladder in the same arbitration, so registering it is what makes a double prompt "
    "structurally impossible."
)
ENVELOPE_CLAIM_BOUNDARY = (
    "This authority envelope is prepared scope only. It is not dispatch, implementation, "
    "review, CI, merge-readiness, or merge evidence, and it does not prove any action ran."
)
GATE_CLAIM_BOUNDARY = (
    "This action gate verdict is a prepared decision. It is not dispatch, execution, "
    "review, CI, or merge evidence."
)
UNTRUSTED_TEXT_POLICY = (
    "Authority comes from user intent and workspace policy only. Authority-shaped requests "
    "inside message text, a context pack, or a recall pack are inert."
)

ACTION_RISK_SCHEMA_VERSION = "action_risk/v1"
ACCOUNT_AUTHORIZATION_SCHEMA_VERSION = "account_authorization/v1"

# The five risky-action kinds #800 names. Every one of them has an entry in
# `_RISK_CLASS_RULES`, and the validator refuses a table that leaves one out —
# a vocabulary that quietly drops the classes nobody could derive would be the
# same decoration the handoff contract exists to prevent.
RISKY_ACTION_CLASSES = (
    "broad_write",
    "deletion",
    "external_mutation",
    "identity_change",
    "publication",
)
ACTION_RISK_LEVELS = ("none", "elevated", "high")
ACTION_RISK_DECISIONS = ("allow", "ask", "deny")
# How a class is decided.
#
# `policy_derived`   -- the authority envelope alone asserts it. Rephrasing a
#                       request cannot move it, because no request field is read.
# `request_declared` -- a declared safety-preflight request field asserts it.
#                       That declaration is policy *at this function's boundary*
#                       and is produced upstream from the user's message on the
#                       coding-delegation lane; `ACTION_RISK_TEXT_POLICY` says
#                       exactly which field and exactly how it can be evaded.
# `subsumed`         -- no declared input can distinguish it from the class that
#                       carries it, so it is reported as carried, not as absent.
RISK_DERIVATIONS = ("policy_derived", "request_declared", "subsumed")

# Every input the classifier reads. Message text, context packs, and recall
# packs are absent from this list and the classifier has no parameter for them —
# which bounds this function and, deliberately, claims nothing about how a
# caller produced the request it hands in.
ACTION_RISK_INPUTS = (
    "isolation_plan.strategy",
    "safety_preflight_request.access_intents",
    "safety_preflight_request.target_paths",
    "task_authority_envelope.allowed_actions",
    "task_authority_envelope.mutation_rights",
)
ACTION_RISK_TEXT_POLICY = (
    "This classifier reads the isolation strategy, the authority envelope, and the declared "
    "safety-preflight request. No message, context pack, or recall pack reaches it and there is no "
    "parameter through which one could, so the same envelope and the same declared request always "
    "yield an identical verdict whatever the message said. That bounds the classifier, not the "
    "pipeline. `external_mutation` and `publication` are decided by the envelope alone and no "
    "phrasing can move them. `broad_write` is decided by the declared `target_paths` and "
    "`access_intents`, and on the coding-delegation lane those paths are scraped out of the user's "
    "message by `coding_delegation._safety_preflight_target_paths` — so end to end that class is "
    "message-sensitive: two phrasings of one intent classify differently, a pasted traceback naming "
    "files raises the count, and a request that names no path at all (\"rewrite everything under "
    "src/\") declares zero targets and classifies as no risk."
)
ACTION_RISK_VS_ISOLATION_RISK = (
    "action_risk.level and isolation_plan.risk_level are different measurements and are never "
    "compared. isolation.risk_level is matched from message.lower() against term tables and answers "
    "'how much should this work be isolated'; it is advisory routing and may not decide authority. "
    "action_risk.level is derived from the authority envelope and the declared safety-preflight "
    "request and answers 'may this act proceed without asking'; text_policy states what that "
    "declared half does and does not promise. The two can disagree without either being wrong, "
    "which is why they carry different names on one record and why nothing reads one to compute "
    "the other."
)

# A write is broad once the operator can no longer read what it will change.
# The bound is a count of *declared* target paths. That declaration is policy at
# this module's boundary and is produced upstream from the user's message on the
# coding-delegation lane, so rephrasing a request really can move this class;
# `ACTION_RISK_TEXT_POLICY` names the scraper and the evasion. Well inside
# `safety_preflight.MAX_TARGET_PATHS` (32), which is the point at which the
# preflight denies outright rather than asking.
MAX_UNCONFIRMED_TARGET_PATHS = 8

# (class, derivation, approvable actions, carrier, statement).
#
# `approvable actions` are the `approval_receipts.APPROVABLE_ACTIONS` members
# that *carry* that class's risk — every envelope action whose grant is what
# makes the class present. A class is only ever present when the envelope grants
# at least one of them, which is what stops a confirmation naming an action
# nobody could have granted and nobody can approve. `carrier` is the class that
# carries a subsumed one and is empty otherwise.
_RISK_CLASS_RULES: tuple[tuple[str, str, tuple[str, ...], str, str], ...] = (
    (
        "broad_write",
        "request_declared",
        ("repo_edit",),
        "",
        "The envelope grants repo_edit, the request declares a write intent, and it names more "
        f"than {MAX_UNCONFIRMED_TARGET_PATHS} target paths, so the operator can no longer read "
        "what the write will change from the request itself. The path count is a declared request "
        "field; on the coding-delegation lane it is scraped from the user's message, so this class "
        "is the one that moves when a request is rephrased.",
    ),
    (
        "deletion",
        "subsumed",
        ("repo_edit",),
        "broad_write",
        "safety_preflight.ACCESS_INTENTS is read, write, and share. Nothing declares a delete, so a "
        "deletion cannot be distinguished from the write that performs it and is classified as that "
        "write rather than as a class nothing can assert.",
    ),
    (
        "external_mutation",
        "policy_derived",
        ("merge", "pr_creation", "pr_revision"),
        "",
        "The envelope grants merge or a pull-request action, so the act changes state outside the "
        "workspace. A request that merely declares a destination does not raise this class: with "
        "none of these actions granted the handoff cannot reach one, and the preflight's own "
        "destination rule is what refuses an undeclared reach.",
    ),
    (
        "identity_change",
        "subsumed",
        ("merge", "pr_creation", "pr_revision"),
        "external_mutation",
        "No request field names an account, an identity, or a credential rotation, so an identity "
        "change cannot be distinguished from the external mutation that performs it. The "
        "account_authorization projection is what would make it derivable, and that projection is "
        "declared and not enforced.",
    ),
    (
        "publication",
        "policy_derived",
        ("external_posting",),
        "",
        "The envelope grants external_posting, so the act makes something visible outside the "
        "workspace. A declared share intent alone does not raise this class: without the grant "
        "nothing can publish, and the preflight refuses a share intent no approved destination "
        "covers.",
    ),
)
RISK_CLASS_NAMES = tuple(entry[0] for entry in _RISK_CLASS_RULES)
# Classes something can actually assert. A subsumed class must name one of these
# as its carrier; a derivable class must not name a carrier at all.
_DERIVABLE_CLASSES = tuple(entry[0] for entry in _RISK_CLASS_RULES if entry[1] != "subsumed")
_RISK_CLASS_ACTIONS = {name: actions for name, _d, actions, _c, _s in _RISK_CLASS_RULES}
# Classes that leave the workspace. Their presence is what separates `high` from
# `elevated`: a broad write is recoverable inside the repository, a publication
# or an external mutation is not.
_ESCAPING_CLASSES = frozenset({"external_mutation", "publication"})

# Why an unanswered risky action is reported and not refused on the shipped
# lane. Not an issue number, for the reason `ACCOUNT_AUTHORIZATION_BLOCKER` is
# not one: nothing that could be filed closes it on its own. `build_approval_
# receipt` requires a non-empty run id, and `evaluate_action_gate`'s only
# production caller — `coding_delegation.build_coding_delegation_payload` —
# runs before any runtime run exists, so on that lane no receipt that could
# satisfy the request is constructible at all. Arming a ladder whose answer
# cannot be recorded would leave a user permanently blocked with no route
# forward, so the classification rides as a report there and the gate withholds
# nothing.
RISK_CONSENT_BLOCKER = "no_confirmation_answer_intake_mints_a_run_bound_approval"
RISK_CONSENT_ENFORCERS = (
    "omh.coding.action_gate.classify_action_risk",
    "omh.workflows.approval_receipts.approval_satisfies_request_in",
)

ACTION_RISK_KEYS = (
    "schema_version",
    "status",
    "level",
    "decision",
    "reason",
    "classes",
    "subsumed_classes",
    "consent",
    "withheld_actions",
    "narrowing_route",
    "inputs",
    "text_policy",
    "isolation_risk_relationship",
    "enforcement",
    "enforced_by",
    "blocked_by",
    "claim_boundary",
)
RISK_CLASS_ENTRY_KEYS = ("class", "derivation", "approvable_actions", "carrier", "statement")
APPROVAL_REQUEST_KEYS = (
    "approved_action",
    "scope_class",
    "scope_ref",
    "owner",
    "run_id",
    "safety_profile_revision",
)
# One entry per (present class, action that carries it). There is deliberately
# no collapsed "the approvable action" field: one answer covering several
# classes is several approvals wearing one answer, which is the shape that let a
# receipt naming one action release the rest.
CONSENT_ENTRY_KEYS = ("class", "approved_action", "decision", "approval_request", "approval")
NARROWING_ROUTE_KEYS = ("parameter", "narrowed_actions", "explanation")
ACTION_RISK_CLAIM_BOUNDARY = (
    "This action-risk verdict is a prepared decision. It is not dispatch, execution, review, CI, or "
    "merge evidence, and an approval it cites proves consent was given, never that anything ran."
)
# One scope for every class on purpose. The permission profile is the only scope
# that is stable across a rebuild of the same delegation: target paths and
# destinations are re-derived from the request every build, so an approval bound
# to them would either stop matching or silently cover a changed set.
RISK_APPROVAL_SCOPE_CLASS = "permission_profile"

ACCOUNT_ACCESS_STATES = ("missing", "authorized-unverified", "observed-ready", "expired")
ACCOUNT_REFERENCE_KINDS = ("env_var_name", "opaque_handle")
# The actions that cannot run without an account the operator owns: spawning a
# vendor CLI that authenticates as them, or reaching a git host.
ACCOUNT_BACKED_ACTIONS = ("executor_dispatch", "external_posting", "merge", "pr_creation", "pr_revision")
# Same horizon `executor_auth_signals.LIMIT_SIGNAL_STALE_AFTER_SECONDS` uses,
# and for the same reason: past it a locally observed provider signal is history
# rather than current state. Mirrored rather than imported because that module
# reads files and this one must not.
ACCOUNT_SIGNAL_STALE_AFTER_SECONDS = 6 * 60 * 60
ACCOUNT_AUTHORIZATION_KEYS = (
    "schema_version",
    "status",
    "required",
    "reason",
    "accounts",
    "enforcement",
    "enforced_by",
    "blocked_by",
    "blockers",
    "credential_boundary",
    "claim_boundary",
)
ACCOUNT_ENTRY_KEYS = (
    "account_ref",
    "reference_kind",
    "minimum_scopes",
    "state",
    "state_source",
)
ACCOUNT_BLOCKER_KEYS = ("blocker", "statement", "cites")
# Not an issue number. Nothing that can be filed would close it: OMH cannot
# observe that a person completed a flow owned by someone else's website, and
# `data_boundary_enforcement_facts` already sets the precedent of a `blocked_by`
# that names the reason rather than a ticket.
ACCOUNT_AUTHORIZATION_BLOCKER = "host_owned_consent_flow_is_not_observable_by_omh"
# Also not an issue number, on the same precedent. #820 delivered the half OMH
# owns -- `workspace_binding_guard/v1` refuses a second workspace-bound handoff
# on a reserved workspace or branch before one is enabled -- and closing it does
# not close this boundary, because the other half is confining a process that is
# already running. That needs an OS-level confinement backend the host owns; no
# change on this side of the wall can do it, so naming a ticket here would
# promise a fix nobody can ship.
WORKSPACE_RUNTIME_BLOCKER = "no_omh_side_constraint_can_bind_a_running_executor_process"
ACCOUNT_AUTHORIZATION_CLAIM_BOUNDARY = (
    "This account-authorization projection is prepared metadata. It is not dispatch, execution, or "
    "evidence that any account is usable: a login marker means a local file exists, never that a "
    "provider would accept the credential behind it."
)
# Cited, never restated. The credential boundary already refuses credential
# material in the field class every one of these references travels in; writing
# a second rule here would give the tree two answers to one question.
ACCOUNT_CREDENTIAL_BOUNDARY = (
    "No credential value is read, stored, or echoed. Only a reference is carried — an environment "
    "variable *name* matching the provider-posture shape, or an opaque handle — and the credential "
    "boundary of handoff_safety_contract/v1 is what refuses anything else."
)
_ACCOUNT_CREDENTIAL_ENFORCERS = (
    "omh.quality.safety_preflight.RULE_SECRETS_ABSENT",
    "omh.system.metadata_safety.is_sensitive_metadata_text",
)
# Rendered onto chat cards, so the statements never carry a bare `omh ` token:
# the card tests assert that no internal command-shaped string reaches a user,
# and "OMH cannot..." reads as one. The wrapper is named as "this wrapper"
# here and as OMH only in the handoff contract, which is not rendered.
_ACCOUNT_BLOCKERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "consent_required_is_not_observable",
        "`consent-required` is not a state this wrapper can observe. Completing a provider's consent "
        "flow happens on that provider's site, and nothing local reports it. The approval receipt "
        "closes the adjacent gap and not this one: it proves the operator consented to this "
        "wrapper's own escalation, which is a different question from whether a provider granted a "
        "scope.",
        ("omh.workflows.approval_receipts.approval_satisfies_request_in",),
    ),
    (
        "guided_consent_flow_is_rendered_only",
        "Guiding an operator through the host-owned consent flow can only ever be rendered "
        "instructions. This wrapper may not launch a browser or run an auth CLI, and the "
        "enforcement tests make that a test failure rather than a choice.",
        (),
    ),
)
ACCOUNT_BLOCKER_NAMES = tuple(entry[0] for entry in _ACCOUNT_BLOCKERS)

TASK_AUTHORITY_ENVELOPE_KEYS = (
    "schema_version",
    "status",
    "permission_profile",
    "allowed_actions",
    "blocked_actions",
    "exclusions",
    "allowed_executors",
    "allowed_targets",
    "mutation_rights",
    "merge_authority",
    "external_action_authority",
    "expansion_policy",
    "untrusted_input_policy",
    "safety_profile_revision",
    "claim_boundary",
)
EXPANSION_POLICY_KEYS = (
    "widening_route",
    "confirmation_action",
    "authority_sources",
    "self_expansion_allowed",
)
UNTRUSTED_INPUT_POLICY_KEYS = (
    "policy",
    "text_cannot_expand_authority",
    "inspected_surfaces",
    "flagged_surfaces",
    "effect_on_authority",
    "classifiers",
)
EXCLUSION_KEYS = ("action", "reason_code", "explanation")
ACTION_GATE_KEYS = (
    "schema_version",
    "status",
    "outcome",
    "dispatchable",
    "choice_required",
    "executor_selection_status",
    "work_owner_mode",
    "selected_executor_profile",
    "dispatch_policy",
    "confirmation",
    "authority_envelope",
    "action_risk",
    "account_authorization",
    "denial",
    "safety_profile_revision",
    "claim_boundary",
    # Transport only. `evaluate_action_gate` is the one place that runs per
    # delegation build, so the contract rides back on the verdict — but it is
    # *stored* once, beside `action_gate` on the delegation, never inside it.
    # `records._validate_coding_action_gate` refuses a stored gate that still
    # carries one, because two copies can disagree.
    "handoff_safety_contract",
)
CONFIRMATION_KEYS = (
    "required",
    "ladder",
    "action_id",
    "reason",
    "arbitration_rule",
    "candidate_ladders",
    "armed_ladders",
    "suppressed_ladders",
)
DENIAL_KEYS = ("rule_id", "field", "correction", "reason_codes", "source")

HANDOFF_SAFETY_CONTRACT_KEY = "handoff_safety_contract"
HANDOFF_SAFETY_CONTRACT_KEYS = (
    "schema_version",
    "status",
    "produced_offline",
    "input_sources",
    "boundaries",
    "evidence_requirements",
    "prohibited_actions",
    "allowed_executors",
    "allowed_targets",
    "merge_authority",
    "external_action_authority",
    "safety_profile_revision",
    "claim_boundary",
)
SAFETY_BOUNDARY_KEYS = ("boundary", "statement", "enforcement", "enforced_by", "blocked_by")
EVIDENCE_REQUIREMENT_KEYS = ("stage", "claim", "observation_event", "enforcement", "enforced_by", "blocked_by")
ENFORCEMENT_LEVELS = ("declared_not_enforced", "enforced")
# Every local metadata surface the contract is derived from. Three of the four
# are already in process when `evaluate_action_gate` runs. The fourth,
# `data_boundary_enforcement_facts`, is a host-capability probe taken once per
# process and memoized by `data_boundary_facts` below; it stats local paths and
# never opens a socket, spawns a process, or consults a model, which is what
# `produced_offline` claims. It is declared here rather than left implicit
# because a surface a contract reads and does not name is exactly the kind of
# hidden input this table exists to remove.
HANDOFF_CONTRACT_INPUT_SOURCES = (
    "data_boundary_enforcement_facts",
    "isolation_plan",
    "safety_preflight_verdict",
    "task_authority_envelope",
)
HANDOFF_CONTRACT_CLAIM_BOUNDARY = (
    "This safety contract is prepared metadata. It is not dispatch, execution, review, CI, or merge "
    "evidence, and an enforced boundary means a refusing check exists — not that any action ran."
)

# Not an issue number, for the reason `RISK_CONSENT_BLOCKER` is not one: what
# blocks the `recovery` row is a property of the shipped lane, not a ticket
# waiting to be worked. #821 shipped `recovery_anchor/v1`, so the contract now
# exists and refuses to call anything recoverable without an observed baseline
# for the workspace being asked about. What it cannot do is observe that
# baseline: this lane runs no Git command and reads no working tree, so a
# baseline revision has to arrive from a surface that already observed one, and
# `build_coding_delegation_payload` builds a handoff before any run, worktree,
# or observation exists to supply it. Until a caller that holds an observed
# baseline attaches an anchor, the row stays declared.
RECOVERY_ANCHOR_BLOCKER = "no_delegation_surface_holds_an_observed_baseline_to_attach_an_anchor_from"

# Not an issue number either, and #826 is the reason it stopped being one. That
# issue shipped `run_lineage_checkpoint/v1`, whose chain refuses a dispatch
# checkpoint unless an observed start is already in it -- so an observed start
# is now a prerequisite of *a lineage chain*. It is still not a prerequisite of
# a claim. Lineage is opt-in: no claim rung, journal prerequisite, or delegation
# surface asks a run for a chain, so a run that records none reaches dispatch
# and execution exactly as before. Making the start required would mean making
# the chain required of every run, which is a different change against a
# different surface, and naming a ticket here would promise that #826 had
# already made it.
START_EVIDENCE_BLOCKER = "lineage_orders_the_start_but_no_claim_rung_requires_a_lineage_chain"

# Not an issue number either, and #835 is the reason it stopped being one. That
# issue shipped `generated_artifact/v1` and its cleanup preview, so an operator
# can now see which generated artifact is current, what replaced it, why it is
# retained, and which ones could go. What #835 deliberately did not ship is the
# going: the preview is a dry run with no delete path in the module at all, by
# design, because the issue's own out-of-scope section forbids cleanup without
# explicit confirmation and no surface in this tree can take one. Nothing
# expires a run artifact on disk either. Naming a ticket here would promise a
# reaper that is not planned; the reason string says what is actually missing.
STORAGE_RETENTION_BLOCKER = "the_preview_lists_what_could_be_removed_and_no_surface_removes_anything"

# (boundary, statement, enforcement, enforced_by, blocked_by).
#
# The `enforced_by` refs are dotted import paths that must resolve; the test
# suite imports every one of them. That is what stops this table drifting into
# fiction as the enforcing code moves or is deleted. An entry is only
# `enforced` when naming a symbol that refuses something; anything else is
# `declared_not_enforced` with the issue that must land first.
#
# Statements are scoped to the surface they govern. "No such capability exists"
# is never a justification: it cannot be enforced, and the tree can contradict
# it — `omh setup --star` really does shell out to `gh`. Where a real exception
# exists outside the governed surface, the statement names it exactly rather
# than rounding it away.
_STATIC_SAFETY_BOUNDARIES: tuple[tuple[str, str, str, tuple[str, ...], str], ...] = (
    (
        "account_authorization",
        "A task that needs account-backed access names the account and the minimum scopes by safe "
        "reference only, and reports one of missing, authorized-unverified, observed-ready, or "
        "expired. Nothing here grants, verifies, or refuses account access: `consent-required` is not "
        "a state OMH can observe, and guiding an operator through a host-owned consent flow can only "
        "ever be rendered instructions.",
        "declared_not_enforced",
        (),
        ACCOUNT_AUTHORIZATION_BLOCKER,
    ),
    (
        "confirmation_answered",
        "A risky action is classified, and every class present names the granted actions that carry "
        "it and the approval each one would need. Nothing is withheld on the shipped lane: an "
        "approval binds to a run, no surface records a confirmation answer, and the delegation is "
        "built before any run exists — so no receipt that could answer the question is "
        "constructible, and arming a ladder nobody can answer would block the work permanently "
        "instead of gating it. A caller that does hold a run and a receipt store gets the refusal; "
        "the shipped lane gets the report.",
        "declared_not_enforced",
        (),
        RISK_CONSENT_BLOCKER,
    ),
    (
        "confirmation_arming",
        "One intent arms at most one confirmation ladder, and every ladder that could have fired is "
        "recorded as suppressed with the winner named.",
        "enforced",
        (
            "omh.coding.action_gate.SINGLE_PROMPT_RULE",
            "omh.coding.action_gate.validate_action_gate_verdict",
        ),
        "",
    ),
    (
        "credential",
        "Credential-shaped values are refused in the opaque-reference field class before any rule reads "
        "them, so a secret cannot enter a prepared handoff as metadata. The chat delegation lane builds "
        "its request from closed vocabularies, so the rule is live for direct evaluator callers and "
        "structurally unreachable from a chat message.",
        "enforced",
        (
            "omh.quality.safety_preflight.RULE_SECRETS_ABSENT",
            "omh.system.metadata_safety.is_sensitive_metadata_text",
        ),
        "",
    ),
    (
        "dispatch",
        "The delegation lane spawns no executor unless the envelope allows executor_dispatch under a "
        "dispatchable parent and the owner has an entry in the local dispatch command allowlist. Every "
        "other owner receives a prepared prompt and is never spawned.",
        "enforced",
        (
            "omh.coding.action_gate.validate_task_authority_envelope",
            "omh.coding.fanout_dispatch.DISPATCH_COMMAND_TEMPLATES",
        ),
        "",
    ),
    (
        "evidence_separation",
        "Prepared metadata is not observed execution. Each claim rung requires its own observation, the "
        "observation journal refuses an out-of-order lifecycle event, and review, CI, and merge "
        "additionally require an external effect receipt that observed that effect succeed.",
        "enforced",
        (
            "omh.runtime.claims.allowed_runtime_claims",
            "omh.workflows.external_effect_receipts.receipt_satisfies_success_claim",
            "omh.workflows.observation_journal.append_observation_event",
        ),
        "",
    ),
    (
        "file",
        "Declared target paths are bounded, project-relative, and contained: an absolute or home-anchored path, a "
        "path that escapes the project, an over-long path, or more paths than the bound allows is denied "
        "before a handoff is prepared.",
        "enforced",
        (
            "omh.quality.safety_preflight.RULE_TARGET_PATHS_BOUNDED",
            "omh.quality.safety_preflight.evaluate_safety_preflight",
        ),
        "",
    ),
    (
        "merge",
        "No delegation merges anything. merge_authority is disabled on every delegation this lane builds, "
        "fanout dispatch records auto_merge false, and a merged claim is refused unless an external "
        "effect receipt observed this run's merge succeed.",
        "enforced",
        (
            "omh.coding.action_gate.validate_task_authority_envelope",
            "omh.coding.fanout_dispatch.dispatch_fanout",
            "omh.runtime.claims._receipt_cited",
        ),
        "",
    ),
    (
        "network",
        "The coding delegation lane holds no network client and no remote-mutation path: "
        "external_action_authority is pinned to prepare_only, so no prepared handoff can post, publish, "
        "or open a pull request. One executed remote call exists in the tree, outside this lane and "
        "outside any delegation: `omh setup --star` runs `gh api -X PUT "
        "/user/starred/rlaope/oh-my-hermes` from commands.setup behind an explicit --star flag. It adds "
        "only the operator's own star, cannot reach repository contents, and its exact argv is pinned by "
        "a test, so changing it fails the suite.",
        "enforced",
        ("omh.coding.action_gate.validate_task_authority_envelope",),
        "",
    ),
    (
        "profile_revision",
        "A prepared artifact pins the safety-profile revision it was cleared under, and a later boundary "
        "refuses to act once the live revision no longer matches.",
        "enforced",
        (
            "omh.coding.action_gate.recheck_safety_profile_revision",
            "omh.coding.fanout_dispatch.verify_safety_profile_matches_contract",
        ),
        "",
    ),
    (
        "prohibited_actions",
        "Blocked actions are the exact complement of the allowed set over the whole action vocabulary, and "
        "every blocked action carries a reason code and a written explanation.",
        "enforced",
        ("omh.coding.action_gate.validate_task_authority_envelope",),
        "",
    ),
    (
        "recovery",
        "The recovery_anchor/v1 contract exists and refuses to read as recoverable without an observed "
        "baseline for the workspace being asked about: an absent, prepared-only, or mismatched anchor "
        "returns a refusal and no recipe. What still does not happen is attachment. No delegation "
        "surface requests an anchor, because this lane observes no baseline to build one from — it runs "
        "no Git command and reads no working tree, and a handoff is prepared before any run, worktree, "
        "or observation exists. So risky work still carries no anchor, and a dispatched handoff still "
        "records no baseline to undo against.",
        "declared_not_enforced",
        (),
        RECOVERY_ANCHOR_BLOCKER,
    ),
    (
        "review_receipt",
        "A review claim is refused unless an external effect receipt from runtime_review_record "
        "observed this run's review succeed. A local record saying review passed is the claim, not "
        "the evidence for it, and is no longer accepted as evidence for itself.",
        "enforced",
        (
            "omh.runtime.claims._receipt_cited",
            "omh.workflows.external_effect_receipts.receipt_satisfies_success_claim",
        ),
        "",
    ),
    (
        "start_evidence",
        "runtime_start is recordable and `run_lineage_checkpoint/v1` now orders it: a lineage chain "
        "refuses a dispatch checkpoint unless an observed start is already in that chain, so a history "
        "that skips the start cannot be built. What that does not do is make the start required. A "
        "lineage chain is opt-in — no claim rung, journal prerequisite, or delegation surface asks a run "
        "for one — so a run that records no chain can still claim dispatch and execution with no "
        "observed start.",
        "declared_not_enforced",
        (),
        START_EVIDENCE_BLOCKER,
    ),
    (
        "storage_content",
        "Persisted records carry bounded metadata only — the message as a sha256 digest and a length, "
        "prompts as templates — and every record key set is closed, so a verbatim prompt or message body "
        "cannot be stored.",
        "enforced",
        (
            "omh.runtime.records.CODING_DELEGATION_RECORD_KEYS",
            "omh.runtime.records.validate_coding_delegation_record",
            "omh.workflows.observation_journal.OBSERVATION_PRIVACY",
        ),
        "",
    ),
    (
        "storage_retention",
        "Lifecycle is now readable: `generated_artifact/v1` projects each locally generated plan, plan "
        "variant, operation report, and skill draft with its provenance, the revision that replaced it, "
        "the retention window it sits in, and whether removing it would be safe, and "
        "`generated_artifact_cleanup_preview/v1` refuses to call an artifact removable while it is "
        "current, while any local artifact still points at it, or while its window is open. What still "
        "does not happen is deletion. The preview is a dry run with no removal path in it, nothing expires "
        "a run artifact, and a prepared handoff and its metadata persist until the operator deletes them.",
        "declared_not_enforced",
        (),
        STORAGE_RETENTION_BLOCKER,
    ),
    (
        "untrusted_input",
        "Authority comes from user intent and workspace policy only. Message text, context packs, and "
        "recall packs are inspected and reported as flagged surface names; nothing they contain widens "
        "the allowed action set.",
        "enforced",
        (
            "omh.coding.action_gate.flagged_untrusted_surfaces",
            "omh.coding.action_gate.validate_task_authority_envelope",
        ),
        "",
    ),
    (
        "workspace",
        "The pre-dispatch half now exists: `workspace_binding_guard/v1` reserves a canonical workspace and "
        "branch for one handoff atomically, and a second workspace-bound handoff on either is refused "
        "before it is enabled, with the owner and the recovery named. The runtime half does not. "
        "allowed_targets is derived from the isolation plan, but nothing binds a running executor to it. "
        "The target is a declaration the executor is trusted to honour, not a constraint applied to it.",
        "declared_not_enforced",
        (),
        WORKSPACE_RUNTIME_BLOCKER,
    ),
)

# The #801 data-boundary limits, by name. Mirrored rather than imported for the
# reason `approval_receipts` mirrors this module's vocabularies: the import is
# taken lazily inside `data_boundary_facts` so a probe never runs at import
# time, and `tests/test_risky_action_confirmation.py` pins the two tuples equal
# instead of letting them drift.
DATA_BOUNDARY_LIMIT_NAMES = (
    "workspace_root_claim",
    "prohibited_data_class",
    "declared_destination",
    "runtime_filesystem_confinement",
    "runtime_network_confinement",
    "executor_honours_declared_targets",
)
# One prefix so the data-boundary rows read as one family in a contract that
# already has seventeen other lines.
DATA_BOUNDARY_PREFIX = "data_"
DATA_BOUNDARY_NAMES = tuple(f"{DATA_BOUNDARY_PREFIX}{name}" for name in DATA_BOUNDARY_LIMIT_NAMES)

# What each limit governs, in the contract's own voice. The *statement* is
# host-independent; only the enforcement verdict moves per host, and that comes
# from `data_boundary_enforcement_facts()` rather than from anything written
# here.
_DATA_BOUNDARY_STATEMENTS = {
    "workspace_root_claim": (
        "A target path outside the declared workspace roots is denied before a handoff is prepared, "
        "on the same rule that already bounds absolute, escaping, and over-long paths."
    ),
    "prohibited_data_class": (
        "A request declaring credential material, personal data, or a conversation transcript — or "
        "carrying content shaped like one — is denied before any other rule reads it."
    ),
    "declared_destination": (
        "A remote target that no approved destination names is denied, and so is an access intent "
        "the approval does not cover, so a prepared handoff cannot reach somewhere nobody approved."
    ),
    "runtime_filesystem_confinement": (
        "Fanout places its owner and dispatcher verification processes under the existing OS sandbox. "
        "It confines writes, not reads, to the unit worktree and the selected owner's state directories, with any "
        "owner state file granted as an exact literal and only the two named credential mach-lookup allowances. "
        "A particular run reports confinement only after its same-run probe wrote every directory root and was refused outside them."
    ),
    "runtime_network_confinement": (
        "Fanout preserves its existing network behavior, so the OS sandbox is not requested to confine network access."
    ),
    "executor_honours_declared_targets": (
        "The declared targets are a statement the executor is trusted to honour. Nothing measures "
        "whether it did, on any host."
    ),
}

# The enforcement kind each limit reports, mapped onto the contract's existing
# ENFORCEMENT_LEVELS. There is deliberately no second label set: `enforced_here`
# is the whole mapping, and `enforcement_kind` survives only inside the
# statement, where it explains *why* a limit is or is not enforced here.
_DATA_BOUNDARY_KIND_NOTES = {
    "refused_before_handoff": (
        "Refused before the handoff is prepared, so the limit holds identically on every host."
    ),
    "host_confinement": (
        "Enforceable only through an OS-level confinement backend, so whether this host can enforce "
        "it at all is a host fact and not a policy choice."
    ),
    "advisory": "Advisory on every host: nothing checks it anywhere.",
}


@lru_cache(maxsize=1)
def data_boundary_facts() -> dict[str, Any]:
    """The #801 host-capability answer, probed once per process and memoized.

    Lazily imported for the reason `loop_actions` is: the evaluator lane owns
    the probe, and importing it at module import time would run a filesystem
    probe every time anything imports the action gate — including
    `runtime.records`, which imports this module purely to validate a stored
    verdict.

    Memoized because it is called on every delegation build and the answer
    cannot change inside one process without the host changing underneath it.
    An install without the evaluator lane returns an empty mapping and the
    contract then carries no data-boundary rows, which is the same
    fail-without-bricking rule `normalize_safety_preflight` applies to a missing
    verdict.
    """
    try:
        from ..quality.safety_preflight import data_boundary_enforcement_facts
    except ImportError:
        return {}
    facts = data_boundary_enforcement_facts()
    return facts if isinstance(facts, dict) else {}


def _data_boundary_entries() -> tuple[tuple[str, str, str, tuple[str, ...], str], ...]:
    """The data-boundary rows, mapped onto the contract's own enforcement triple.

    `enforcement_kind` is not a second label set living beside
    ENFORCEMENT_LEVELS: it selects the note appended to the statement and
    nothing else. The verdict itself is `enforced_here`, and `enforced_by` /
    `blocked_by` are taken verbatim from the facts, which already emit them in
    the exact shape `_enforcement_errors` requires.
    """
    facts = data_boundary_facts()
    limits = facts.get("limits")
    if not isinstance(limits, list):
        return ()
    entries: list[tuple[str, str, str, tuple[str, ...], str]] = []
    for limit in limits:
        if not isinstance(limit, dict):
            continue
        name = str(limit.get("limit", ""))
        statement = _DATA_BOUNDARY_STATEMENTS.get(name, "")
        if not statement:
            continue
        note = _DATA_BOUNDARY_KIND_NOTES.get(str(limit.get("enforcement_kind", "")), "")
        enforced_here = limit.get("enforced_here") is True
        entries.append(
            (
                f"{DATA_BOUNDARY_PREFIX}{name}",
                f"{statement} {note}".strip(),
                "enforced" if enforced_here else "declared_not_enforced",
                tuple(str(symbol) for symbol in limit.get("enforced_by", []) or ()) if enforced_here else (),
                "" if enforced_here else str(limit.get("blocked_by", "")),
            )
        )
    return tuple(entries)


def safety_boundaries() -> tuple[tuple[str, str, str, tuple[str, ...], str], ...]:
    """The full boundary table, static rows and data-boundary rows, in one order.

    Sorted by name so the table stays readable as it grows and so a reader
    cannot infer precedence from position; the validator compares the whole
    ordered name list, which is what makes a dropped, duplicated, or reordered
    row the same defect.
    """
    return tuple(sorted((*_STATIC_SAFETY_BOUNDARIES, *_data_boundary_entries()), key=lambda entry: entry[0]))


def safety_boundary_names() -> tuple[str, ...]:
    """The boundary names this install really produces, in table order."""
    return tuple(entry[0] for entry in safety_boundaries())


# The boundary set a complete install declares. The validator compares against
# `safety_boundary_names()` instead, so an install missing the #801 evaluator
# lane still validates its own smaller contract rather than failing on rows it
# could never have built; a test pins the two equal for a complete install.
SAFETY_BOUNDARY_NAMES = tuple(
    sorted((*(entry[0] for entry in _STATIC_SAFETY_BOUNDARIES), *DATA_BOUNDARY_NAMES))
)

_CLAIM_LADDER_ENFORCERS = (
    "omh.runtime.claims.allowed_runtime_claims",
    "omh.workflows.observation_journal.append_observation_event",
)
_RECEIPT_ENFORCERS = (
    *_CLAIM_LADDER_ENFORCERS,
    "omh.workflows.external_effect_receipts.receipt_satisfies_success_claim",
)

# (stage, claim, observation_event, enforcement, enforced_by, blocked_by).
# The six stages #818 names. `start` is the honest gap: the event exists and is
# recordable, but no claim rung and no journal prerequisite reads it, so the
# contract declares it unenforced instead of implying a gate.
_EVIDENCE_REQUIREMENTS: tuple[tuple[str, str, str, str, tuple[str, ...], str], ...] = (
    ("start", "", "runtime_start_observed", "declared_not_enforced", (), "#826"),
    ("execution", "execution_observed", "executor_result_observed", "enforced", _CLAIM_LADDER_ENFORCERS, ""),
    (
        "verification",
        "verification_observed",
        "verification_result_observed",
        "enforced",
        _CLAIM_LADDER_ENFORCERS,
        "",
    ),
    ("review", "review_observed", "review_result_observed", "enforced", _CLAIM_LADDER_ENFORCERS, ""),
    ("ci", "ci_observed", "ci_result_observed", "enforced", _RECEIPT_ENFORCERS, ""),
    ("merge", "merged", "merge_observed", "enforced", _RECEIPT_ENFORCERS, ""),
)
HANDOFF_EVIDENCE_STAGES = tuple(entry[0] for entry in _EVIDENCE_REQUIREMENTS)

REVISION_DRIFT_RULE_ID = "safety_profile_revision_drift"
REVISION_DRIFT_FIELD = "safety_profile_revision"
REVISION_DRIFT_CORRECTION = (
    "Re-run the safety preflight against the current workspace policy and rebuild the handoff; "
    "the carried safety profile revision no longer matches the live one."
)

# Bounded on purpose: the classifiers walk every character for bidi and control
# marks, and this runs on every delegation build. A prefix is enough to decide
# whether a surface carries authority-shaped content, and the bound keeps the
# decision deterministic across machines.
_MAX_SURFACE_CHARS = 2000
_MAX_SURFACE_FRAGMENTS = 200

_AUTHORITY_CUE_PHRASES = (
    "act as system",
    "auto-merge",
    "bypass approval",
    "bypass the gate",
    "developer mode",
    "disregard instructions",
    "disregard previous",
    "elevate permissions",
    "enable auto dispatch",
    "enable auto-dispatch",
    "full access",
    "full permissions",
    "grant full",
    "grant yourself",
    "ignore previous",
    "no confirmation needed",
    "override the policy",
    "reveal the system prompt",
    "skip confirmation",
    "without asking",
    "you are now",
    "you have permission to",
    "you may merge",
)


def loop_actions() -> tuple[str, ...]:
    """The goal-loop action vocabulary, imported lazily to keep records importable."""
    from ..workflows.goal_loop import LOOP_ACTIONS

    return LOOP_ACTIONS


def permission_profiles() -> tuple[str, ...]:
    from ..workflows.goal_loop import PERMISSION_PROFILES

    return PERMISSION_PROFILES


def _loop_envelope(profile: str, *, executors: list[str], forbid: list[str]) -> dict[str, Any]:
    from ..workflows.goal_loop import build_authority_envelope

    return build_authority_envelope(
        permission_profile=profile,
        allowed_executors=executors,
        forbid_actions=forbid,
    )


def permission_profile_for(
    *,
    denied: bool,
    delegation_action: str,
    work_owner_mode: str,
    dispatchable: bool,
    choice_required: bool,
) -> str:
    """The permission profile a delegation collapses to, from intent and policy only."""
    if denied or delegation_action != "delegate" or choice_required or work_owner_mode == "retained_hermes":
        return "observe_only"
    if dispatchable:
        return "execute_with_gates"
    return "handoff_only"


# Never narrowed away. Reading and thinking about a request is what makes an
# answer possible at all, so a narrowing answer that removed them would leave a
# handoff that cannot even be described.
BASELINE_ACTIONS = frozenset({"planning", "research"})


def required_actions_for(
    *,
    denied: bool,
    delegation_action: str,
    intent: str,
    review_required: bool,
    dispatchable: bool,
    choice_required: bool,
) -> set[str]:
    """The smallest action set this task needs — the "only required authority" rule."""
    required = {"research", "planning"}
    if denied or delegation_action != "delegate" or choice_required:
        return required
    required.add("executor_handoff")
    if dispatchable:
        required.add("executor_dispatch")
    if intent in {"coding", "cleanup", "docs"}:
        required.add("repo_edit")
    if review_required or intent == "review":
        required.add("review_fix_loop")
    return required


def _explanation(action: str, reason_code: str, profile: str) -> str:
    if reason_code == "withheld_pending_approval":
        return (
            f"`{action}` is held back until an approval on record covers it for this owner, run, "
            "scope, and safety profile revision."
        )
    if reason_code == "narrowed_by_request":
        return f"`{action}` was removed because the request narrowed the authority it asked for."
    if reason_code == "safety_preflight_denied":
        return f"`{action}` was withdrawn because the safety preflight denied this request."
    if reason_code == "outside_permission_profile":
        return f"`{action}` is not granted by the `{profile}` permission profile, so it stays an approval checkpoint."
    if reason_code == "user_authorized_pending_verification":
        # No "omh " token here for the same card reason as the fallthrough
        # below; "this wrapper" carries the boundary without the command-shaped
        # string. Preserving the intent is not granting the action: `merge`
        # stays blocked and gated on receipt evidence.
        return (
            f"`{action}` was authorized by the user as a post-verification step; this wrapper never "
            "merges, so it stays a separate observed action gated on receipt evidence."
        )
    # Deliberately no "omh " token: chat cards assert they never surface an
    # internal command-shaped string, and this text is rendered onto them.
    return f"`{action}` is outside the task scope derived from the request, so the handoff never carries it."


def _allowed_targets_for(isolation_plan: dict[str, Any] | None, allowed: set[str]) -> list[str]:
    if "repo_edit" not in allowed:
        return []
    strategy = str((isolation_plan or {}).get("strategy", ""))
    if strategy == "worktree_required":
        return ["isolated_worktree"]
    if strategy == "worktree_recommended":
        return ["current_workspace", "isolated_worktree"]
    return ["current_workspace"]


def _surface_fragments(value: Any, fragments: list[str]) -> None:
    if len(fragments) >= _MAX_SURFACE_FRAGMENTS:
        return
    if isinstance(value, str):
        if value.strip():
            fragments.append(value)
        return
    if isinstance(value, dict):
        for key in sorted(value):
            _surface_fragments(value[key], fragments)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _surface_fragments(item, fragments)


def surface_text(value: Any) -> str:
    """Flatten a surface into one deterministic, bounded blob for classification."""
    if value is None:
        return ""
    fragments: list[str] = []
    _surface_fragments(value, fragments)
    return "\n".join(fragments)[:_MAX_SURFACE_CHARS]


def is_authority_shaped(text: str) -> bool:
    """True when a surface carries authority-shaped or injection-shaped content.

    Purely a report: nothing downstream of this reads the result to widen the
    allowed action set.
    """
    if not text.strip():
        return False
    lowered = " ".join(text.lower().split())
    if any(cue in lowered for cue in _AUTHORITY_CUE_PHRASES):
        return True
    if classify_memory_admission(text).get("status") != "safe":
        return True
    try:
        ensure_safe_opaque_ref_content(text, "delegation_surface")
    except ValueError:
        return True
    return False


def flagged_untrusted_surfaces(
    *,
    message: str,
    context_pack: dict[str, Any] | None,
    memory_recall_pack: dict[str, Any] | None,
) -> list[str]:
    surfaces = {
        "message": message,
        "context_pack": context_pack,
        "memory_recall_pack": memory_recall_pack,
    }
    return sorted(name for name, value in surfaces.items() if is_authority_shaped(surface_text(value)))


def build_task_authority_envelope(
    *,
    denied: bool,
    delegation_action: str,
    intent: str,
    review_required: bool,
    work_owner_mode: str,
    selected_executor_profile: str | None,
    dispatchable: bool,
    choice_required: bool,
    isolation_plan: dict[str, Any] | None = None,
    message: str = "",
    context_pack: dict[str, Any] | None = None,
    memory_recall_pack: dict[str, Any] | None = None,
    safety_profile_revision: str = "",
    narrow_to: set[str] | frozenset[str] | None = None,
    withheld: set[str] | frozenset[str] | None = None,
    post_completion_directive: str = "",
) -> dict[str, Any]:
    """Derive the task-scoped authority envelope from intent and policy only.

    `narrow_to` is the "narrow" answer to a risky-action confirmation: a smaller
    requested action set, fed back through the same `requested_actions` seam a
    widening request travels on. It can only ever remove authority — the result
    is the intersection with what the task already required — so a narrowing
    answer can never become a widening one by accident.

    `withheld` is authority the task really does require and that no recorded
    approval covers. It is separated from `narrow_to` because the two mean
    opposite things to a reader: a narrowed action was not asked for, while a
    withheld one was asked for and is waiting on an answer.
    """
    profile = permission_profile_for(
        denied=denied,
        delegation_action=delegation_action,
        work_owner_mode=work_owner_mode,
        dispatchable=dispatchable,
        choice_required=choice_required,
    )
    required = required_actions_for(
        denied=denied,
        delegation_action=delegation_action,
        intent=intent,
        review_required=review_required,
        dispatchable=dispatchable,
        choice_required=choice_required,
    )
    # What the same request would have required had the preflight allowed it —
    # only used to label exclusions, never to widen the allowed set.
    undenied = required_actions_for(
        denied=False,
        delegation_action=delegation_action,
        intent=intent,
        review_required=review_required,
        dispatchable=dispatchable,
        choice_required=choice_required,
    )
    vocabulary = set(loop_actions())
    narrowed_away: set[str] = set()
    if narrow_to is not None:
        kept = required & (set(narrow_to) | BASELINE_ACTIONS)
        narrowed_away = required - kept
        required = kept
    withheld_away = (required & set(withheld)) - BASELINE_ACTIONS if withheld else set()
    required = required - withheld_away
    executors = [selected_executor_profile] if selected_executor_profile else []
    base = _loop_envelope(profile, executors=executors, forbid=sorted(vocabulary - required))
    allowed = set(base["allowed_actions"])
    blocked = sorted(vocabulary - allowed)

    exclusions: list[dict[str, str]] = []
    for action in blocked:
        if action in withheld_away:
            reason_code = "withheld_pending_approval"
        elif action in narrowed_away:
            reason_code = "narrowed_by_request"
        elif denied and action in undenied:
            reason_code = "safety_preflight_denied"
        elif action in required:
            reason_code = "outside_permission_profile"
        elif action == "merge" and post_completion_directive == "merge" and not denied:
            # Ordered below the safety and profile denials on purpose: those
            # keep precedence. A denied run never reaches the post-verification
            # step, so the directive is suppressed there too. This only relabels
            # the `not_required_by_task` case for `merge` when the user
            # explicitly asked for it. The action is still blocked; only the
            # reason it is blocked carries the intent.
            reason_code = "user_authorized_pending_verification"
        else:
            reason_code = "not_required_by_task"
        exclusions.append(
            {
                "action": action,
                "reason_code": reason_code,
                "explanation": _explanation(action, reason_code, profile),
            }
        )

    envelope: dict[str, Any] = {
        "schema_version": TASK_AUTHORITY_ENVELOPE_SCHEMA_VERSION,
        "status": "prepared_not_observed",
        "permission_profile": profile,
        "allowed_actions": sorted(allowed),
        "blocked_actions": blocked,
        "exclusions": exclusions,
        "allowed_executors": list(base["allowed_executors"]),
        "allowed_targets": _allowed_targets_for(isolation_plan, allowed),
        "mutation_rights": sorted(allowed & set(MUTATING_ACTIONS)),
        "merge_authority": str(base["merge_authority"]),
        "external_action_authority": str(base["external_action_authority"]),
        "expansion_policy": {
            "widening_route": "confirmation_required",
            "confirmation_action": LADDER_ACTION_IDS["permission_profile"],
            "authority_sources": list(AUTHORITY_SOURCES),
            "self_expansion_allowed": False,
        },
        "untrusted_input_policy": {
            "policy": UNTRUSTED_TEXT_POLICY,
            "text_cannot_expand_authority": True,
            "inspected_surfaces": list(UNTRUSTED_SURFACES),
            "flagged_surfaces": flagged_untrusted_surfaces(
                message=message,
                context_pack=context_pack,
                memory_recall_pack=memory_recall_pack,
            ),
            "effect_on_authority": "none",
            "classifiers": list(AUTHORITY_CLASSIFIERS),
        },
        "safety_profile_revision": str(safety_profile_revision or ""),
        "claim_boundary": ENVELOPE_CLAIM_BOUNDARY,
    }
    # Optional by construction. When the user gave no explicit merge/deploy
    # directive the key is omitted, so every existing envelope stays
    # byte-identical and the shape fixtures never move. When present, it is a
    # prepared post-verification intent record and nothing more: no allowed
    # action changed above, and `authority_effect` says so in the record. A
    # denied run never reaches the post-verification step, so it carries no
    # directive -- the denial is the whole story there.
    if post_completion_directive in ("merge", "deploy") and not denied:
        action_word = post_completion_directive
        envelope["post_completion_directive"] = {
            "action": action_word,
            "state": POST_COMPLETION_DIRECTIVE_STATE,
            "authority_effect": "none",
            "source": "user_intent",
            "executed_by": "operator_or_reviewing_agent",
            "requires_before_effect": ["verification", "review", "ci", "external_effect_receipt"],
            "note": (
                f"User explicitly requested {action_word} as the final step. Preserve this intent "
                "downstream; do not downgrade it to 'no merge'. This wrapper never merges; the "
                f"{action_word} stays a separate observed action gated on receipt evidence."
            ),
        }
    return envelope


_POST_COMPLETION_DIRECTIVE_KEYS = (
    "action",
    "state",
    "authority_effect",
    "source",
    "executed_by",
    "requires_before_effect",
    "note",
)


def _post_completion_directive_errors(value: Any, label: str) -> list[str]:
    """Validate the optional directive record's shape; absence is always valid."""
    if not isinstance(value, dict) or set(value) != set(_POST_COMPLETION_DIRECTIVE_KEYS):
        return [f"{label} post_completion_directive keys are invalid"]
    errors: list[str] = []
    if value.get("action") not in POST_COMPLETION_DIRECTIVE_ACTIONS:
        errors.append(f"{label} post_completion_directive.action is unsupported")
    if value.get("state") != POST_COMPLETION_DIRECTIVE_STATE:
        errors.append(f"{label} post_completion_directive.state is invalid")
    if value.get("authority_effect") != "none":
        errors.append(f"{label} post_completion_directive.authority_effect must be none")
    if value.get("source") != "user_intent":
        errors.append(f"{label} post_completion_directive.source must be user_intent")
    errors.extend(
        _string_list_errors(value.get("requires_before_effect"), f"{label} post_completion_directive.requires_before_effect")
    )
    if not str(value.get("executed_by", "")).strip():
        errors.append(f"{label} post_completion_directive.executed_by is required")
    if not str(value.get("note", "")).strip():
        errors.append(f"{label} post_completion_directive.note is required")
    return errors


def _declared_strings(request: dict[str, Any] | None, key: str) -> list[str]:
    value = (request or {}).get(key)
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def granted_risk_actions(envelope: dict[str, Any], risk_class: str) -> list[str]:
    """The actions this envelope really grants that carry one class's risk.

    The whole anti-collapse rule in one function. A confirmation may only ever
    name an action the envelope granted: an approval for an action nobody was
    ever given is unmatchable, and a class whose granted carriers are empty is
    a class the handoff cannot perform.
    """
    granted = set(_declared_strings(envelope, "allowed_actions"))
    return sorted(action for action in _RISK_CLASS_ACTIONS.get(risk_class, ()) if action in granted)


def risk_classes_present(
    *,
    envelope: dict[str, Any],
    safety_preflight_request: dict[str, Any] | None = None,
) -> list[str]:
    """The risky classes this delegation carries, sorted.

    Two inputs and no others: what the envelope granted, and what the request
    declared. Nothing here reads the message, and there is no parameter through
    which it could — see `ACTION_RISK_TEXT_POLICY` for what that does and does
    not promise about the request a caller hands in.

    Every rule is anchored on `mutation_rights`, which is the envelope's own
    grant set, so a class is present only when the envelope really grants an
    action that could perform it. `merge_authority` and
    `external_action_authority` are not read separately: on any envelope the
    validator accepts they are restatements of `merge` and `external_posting`
    being allowed, and reading them as independent triggers is what let a class
    appear with no grantable action behind it.
    """
    mutation_rights = set(_declared_strings(envelope, "mutation_rights"))
    intents = set(_declared_strings(safety_preflight_request, "access_intents"))
    target_paths = _declared_strings(safety_preflight_request, "target_paths")

    present: set[str] = set()
    if (
        "repo_edit" in mutation_rights
        and "write" in intents
        and len(target_paths) > MAX_UNCONFIRMED_TARGET_PATHS
    ):
        present.add("broad_write")
    if mutation_rights & set(_RISK_CLASS_ACTIONS["external_mutation"]):
        present.add("external_mutation")
    if "external_posting" in mutation_rights:
        present.add("publication")
    return sorted(present)


def _risk_level_for(classes: list[str]) -> str:
    if not classes:
        return "none"
    if set(classes) & _ESCAPING_CLASSES:
        return "high"
    return "elevated"


def _narrowing_route(envelope: dict[str, Any], withheld_actions: list[str]) -> dict[str, Any]:
    """The smaller action set that answers "narrow" instead of "approve".

    Fed back through `requested_authority_actions`, which is the same seam a
    widening request travels on. That seam existed with no production caller;
    this is its first one.

    Every action that still carries an unapproved class is removed, not just one
    of them: the promise in the explanation is that re-running with this set
    leaves nothing to confirm, and a set that dropped one carrier while keeping
    a sibling would ask the same question again.
    """
    allowed = set(_declared_strings(envelope, "allowed_actions"))
    narrowed = sorted((allowed - set(withheld_actions)) | BASELINE_ACTIONS)
    return {
        "parameter": "requested_authority_actions",
        "narrowed_actions": narrowed,
        "explanation": (
            "Answering narrow means asking for a smaller action set. Re-run the same request with "
            "these actions and no action carrying an unapproved risky class is granted, so nothing "
            "is left to confirm."
        ),
    }


def classify_action_risk(
    *,
    envelope: dict[str, Any],
    isolation_plan: dict[str, Any] | None = None,
    safety_preflight_request: dict[str, Any] | None = None,
    approval_receipts: Any = None,
    owner: str = "",
    run_id: str = "",
    now: str = "",
) -> dict[str, Any]:
    """Allow, ask, or deny every risky class present, each on its own consent.

    Consent is per risky class, and within a class per granted action. There is
    no single "the approvable action": one answer covering three classes is
    three approvals wearing one answer, and it was that collapse which let a
    receipt naming `merge` release a broad repo write and a publication at once.

    For every class present, every action the envelope really grants that
    carries it becomes one `consent` entry with its own five-dimension approval
    request and its own verdict:

    * a live approval naming exactly that action, scope, owner, run, and
      safety-profile revision -> **allow** for that entry.
    * an approval that was revoked or answered with a denial -> **deny**. The
      operator already said no; asking again is asking until the answer changes.
    * anything else — absent, expired, superseded, or an approval covering a
      sibling action, a different scope, another owner, another run, or another
      revision -> **ask**.

    The verdict is the aggregate: **deny** if any entry is refused, **ask** if
    any entry is unanswered, and **allow** only when every class present is
    approved on every action that carries it. `withheld_actions` is exactly the
    set of actions whose entry is not allowed.

    `enforcement` is the honest half. A receipt binds to a run, and
    `build_approval_receipt` refuses an empty one, so with no run id no receipt
    that could satisfy any of these requests is constructible and the whole
    classification is a report: `declared_not_enforced`, blocked by
    `RISK_CONSENT_BLOCKER`, and the gate withholds nothing. Given a run id the
    same refusal is real and the block reports `enforced`.

    `approval_receipts` is a sequence of receipts the caller already read, and
    the pure `approval_satisfies_request_in` form is what judges them, so this
    function opens nothing. A caller with no store passes nothing and every
    risky action is unapproved, which is the safe direction.

    One scope stays run-wide by design: the approval binds to the permission
    profile, so inside one run, one hour, and one revision, a second delegation
    for the same owner and profile is covered by the first answer for the same
    class and action. That is what a run-bound approval means; it is not a
    per-delegation consent and never claimed to be.

    `isolation_plan` is read for its *strategy* only. `isolation_plan.risk_level`
    is deliberately never touched; see `ACTION_RISK_VS_ISOLATION_RISK`.
    """
    classes = risk_classes_present(envelope=envelope, safety_preflight_request=safety_preflight_request)
    subsumed = [
        {
            "class": name,
            "derivation": derivation,
            "approvable_actions": list(actions),
            "carrier": carrier,
            "statement": statement,
        }
        for name, derivation, actions, carrier, statement in _RISK_CLASS_RULES
        if derivation == "subsumed"
    ]
    profile = str(envelope.get("permission_profile", ""))
    revision = str(envelope.get("safety_profile_revision", ""))
    strategy = str((isolation_plan or {}).get("strategy", ""))
    enforceable = bool(str(run_id).strip())
    enforcement = {
        "enforcement": "enforced" if enforceable else "declared_not_enforced",
        "enforced_by": list(RISK_CONSENT_ENFORCERS) if enforceable else [],
        "blocked_by": "" if enforceable else RISK_CONSENT_BLOCKER,
    }

    if not classes:
        return {
            "schema_version": ACTION_RISK_SCHEMA_VERSION,
            "status": "prepared_not_observed",
            "level": "none",
            "decision": "allow",
            "reason": (
                "Nothing in this handoff escalates past prepare-only, so no risky action needs "
                f"confirming under the `{strategy or 'unstated'}` isolation strategy."
            ),
            "classes": [],
            "subsumed_classes": subsumed,
            "consent": [],
            "withheld_actions": [],
            "narrowing_route": {},
            "inputs": list(ACTION_RISK_INPUTS),
            "text_policy": ACTION_RISK_TEXT_POLICY,
            "isolation_risk_relationship": ACTION_RISK_VS_ISOLATION_RISK,
            **enforcement,
            "claim_boundary": ACTION_RISK_CLAIM_BOUNDARY,
        }

    receipts = list(approval_receipts or [])
    consent: list[dict[str, Any]] = []
    for name, _derivation, _actions, _carrier, _statement in _RISK_CLASS_RULES:
        if name not in classes:
            continue
        for action in granted_risk_actions(envelope, name):
            request = {
                "approved_action": action,
                "scope_class": RISK_APPROVAL_SCOPE_CLASS,
                "scope_ref": profile,
                "owner": str(owner),
                "run_id": str(run_id),
                "safety_profile_revision": revision,
            }
            approval = approval_satisfies_request_in(
                receipts,
                approved_action=action,
                scope_class=RISK_APPROVAL_SCOPE_CLASS,
                scope_ref=profile,
                owner=str(owner),
                run_id=str(run_id),
                safety_profile_revision=revision,
                now=now,
            )
            reason_code = str(approval.get("reason_code", ""))
            if approval.get("satisfied") is True:
                entry_decision = "allow"
            elif reason_code in {REFUSAL_REVOKED, REFUSAL_DENIED}:
                entry_decision = "deny"
            else:
                entry_decision = "ask"
            consent.append(
                {
                    "class": name,
                    "approved_action": action,
                    "decision": entry_decision,
                    "approval_request": request,
                    "approval": approval,
                }
            )

    refused = [entry for entry in consent if entry["decision"] == "deny"]
    unanswered = [entry for entry in consent if entry["decision"] == "ask"]
    withheld = sorted({str(entry["approved_action"]) for entry in consent if entry["decision"] != "allow"})
    if refused:
        decision = "deny"
        reason = (
            "The operator refused or revoked the approval for "
            + _quoted_actions(refused)
            + ", so "
            + _quoted_classes(refused)
            + " stays refused. Asking again would be asking until the answer changes."
        )
    elif unanswered:
        decision = "ask"
        reason = (
            "No recorded approval covers "
            + _quoted_actions(unanswered)
            + " for this owner, run, scope, and safety profile revision, so "
            + _quoted_classes(unanswered)
            + " needs an explicit answer on every action that carries it."
        )
    elif consent:
        decision = "allow"
        reason = (
            "A recorded approval covers "
            + _quoted_actions(consent)
            + " for this owner, run, scope, and safety profile revision, so every risky class "
            "present proceeds on consent that was given rather than on a ladder that was armed."
        )
    else:
        # A class is present and the envelope grants nothing that carries it.
        # `risk_classes_present` cannot produce this today because every rule is
        # anchored on `mutation_rights`; a future rule that could would have no
        # answerable question, so it refuses rather than silently allowing.
        decision = "deny"
        reason = (
            "This handoff carries a risky class the envelope grants no action for, so there is no "
            "approval that could release it and nothing may proceed on it."
        )
    return {
        "schema_version": ACTION_RISK_SCHEMA_VERSION,
        "status": "prepared_not_observed",
        "level": _risk_level_for(classes),
        "decision": decision,
        "reason": reason.strip(),
        "classes": [
            {
                "class": name,
                "derivation": derivation,
                "approvable_actions": granted_risk_actions(envelope, name),
                "carrier": carrier,
                "statement": statement,
            }
            for name, derivation, _actions, carrier, statement in _RISK_CLASS_RULES
            if name in classes
        ],
        "subsumed_classes": subsumed,
        "consent": consent,
        "withheld_actions": withheld,
        "narrowing_route": _narrowing_route(envelope, withheld),
        "inputs": list(ACTION_RISK_INPUTS),
        "text_policy": ACTION_RISK_TEXT_POLICY,
        "isolation_risk_relationship": ACTION_RISK_VS_ISOLATION_RISK,
        **enforcement,
        "claim_boundary": ACTION_RISK_CLAIM_BOUNDARY,
    }


def _quoted_actions(entries: list[dict[str, Any]]) -> str:
    return ", ".join(f"`{action}`" for action in sorted({str(entry["approved_action"]) for entry in entries}))


def _quoted_classes(entries: list[dict[str, Any]]) -> str:
    return ", ".join(f"`{name}`" for name in sorted({str(entry["class"]) for entry in entries}))


def _account_state(signal: Any, now: str = "") -> tuple[str, str]:
    """(state, what said so) for one account, from a signal the caller already read.

    Four states and the one thing each of them means:

    * `missing` — the readiness probe found no marker at all.
    * `authorized-unverified` — a login marker is present. That is exactly what
      a marker means and `executor_auth_signals`' own claim boundary already
      says so: a local file exists, not that the provider would accept it.
    * `observed-ready` — a readiness probe reported ready *and* the process it
      ran exited 0. Either half alone is not readiness.
    * `expired` — the signal's own timestamp is older than the staleness
      horizon, derived here at read time rather than stored as a deadline.
    """
    if not isinstance(signal, dict):
        return "missing", "readiness_probe"
    observed_at = str(signal.get("observed_at", "") or "")
    if observed_at and _stamp_age_seconds(observed_at, now) > ACCOUNT_SIGNAL_STALE_AFTER_SECONDS:
        return "expired", "stored_timestamp"
    if str(signal.get("probe_status", "")) == "ready" and signal.get("exit_code") == 0:
        return "observed-ready", "probe_exit_code"
    if str(signal.get("login_marker", "")) == "present":
        return "authorized-unverified", "login_marker"
    return "missing", "readiness_probe"


def _stamp_age_seconds(observed_at: str, now: str = "") -> int:
    """Age of an ISO-8601 stamp in seconds, or a value past every horizon.

    Unreadable and future stamps both return a value larger than any horizon,
    for the reason `approval_age_seconds` returns `UNKNOWN_AGE_SECONDS`: neither
    can be shown to be fresh, and clamping would make editing a timestamp a way
    to widen a window from disk.
    """

    def _parse(value: str) -> datetime | None:
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    observed = _parse(observed_at)
    if observed is None:
        return ACCOUNT_SIGNAL_STALE_AFTER_SECONDS + 1
    reference = _parse(now) or datetime.now(timezone.utc)
    age = int((reference - observed).total_seconds())
    return ACCOUNT_SIGNAL_STALE_AFTER_SECONDS + 1 if age < 0 else age


def build_account_authorization(
    *,
    envelope: dict[str, Any],
    auth_signals: dict[str, Any] | None = None,
    account_references: dict[str, str] | None = None,
    withheld_actions: list[str] | tuple[str, ...] | None = None,
    now: str = "",
) -> dict[str, Any]:
    """The #799 projection: which accounts this task needs, and what is known.

    Honest about what it is. Roughly three quarters of #799 is a projection over
    things this tree already derives — that a task needs account-backed access,
    which account, the minimum scopes, and a readiness state — and that part is
    implemented here. The remaining quarter is not implementable: OMH cannot
    observe that a person completed a consent flow on a provider's site, and it
    may not launch a browser or run an auth CLI to move them through one. Those
    two are declared as blockers with the reason written out, and the whole
    projection reports `declared_not_enforced`.

    Never probes. `auth_signals` is an `executor_auth_signals/v1`-shaped mapping
    the caller already read, so this stays as I/O-free as the rest of the gate.
    A caller that read nothing gets `missing`, which is the safe direction.

    Never carries credential material. A reference is either an environment
    variable *name* matching the provider-posture shape or an opaque handle;
    the credential boundary is cited rather than reimplemented.

    `withheld_actions` is read for the same reason the envelope is: withholding
    an action because nobody approved it does not stop the task needing the
    account behind it. Reading `allowed_actions` alone made `required` report
    false exactly when a risky action was held back, which is the inverse of
    what a reader takes it to mean.
    """
    allowed = set(_declared_strings(envelope, "allowed_actions")) | {
        str(action) for action in (withheld_actions or [])
    }
    account_backed = sorted(allowed & set(ACCOUNT_BACKED_ACTIONS))
    executors = _declared_strings(envelope, "allowed_executors")
    profiles = (auth_signals or {}).get("profiles")
    signals = profiles if isinstance(profiles, dict) else {}
    accounts: list[dict[str, Any]] = []
    for executor in executors:
        state, source = _account_state(signals.get(executor), now)
        reference = str((account_references or {}).get(executor, "") or "")
        kind = "env_var_name" if _is_env_var_name(reference) else "opaque_handle"
        accounts.append(
            {
                "account_ref": reference if kind == "env_var_name" else _safe_account_handle(executor),
                "reference_kind": kind,
                "minimum_scopes": list(account_backed),
                "state": state,
                "state_source": source,
            }
        )
    required = bool(account_backed)
    return {
        "schema_version": ACCOUNT_AUTHORIZATION_SCHEMA_VERSION,
        "status": "prepared_not_observed",
        "required": required,
        "reason": (
            "This task needs account-backed access: the envelope allows "
            f"{', '.join(f'`{action}`' for action in account_backed)}, and none of those can run "
            "without an account the operator owns."
            if required
            else "Nothing this envelope allows reaches an account, so no account-backed access is needed."
        ),
        "accounts": accounts,
        "enforcement": "declared_not_enforced",
        "enforced_by": [],
        "blocked_by": ACCOUNT_AUTHORIZATION_BLOCKER,
        "blockers": [
            {"blocker": blocker, "statement": statement, "cites": list(cites)}
            for blocker, statement, cites in _ACCOUNT_BLOCKERS
        ],
        "credential_boundary": ACCOUNT_CREDENTIAL_BOUNDARY,
        "claim_boundary": ACCOUNT_AUTHORIZATION_CLAIM_BOUNDARY,
    }


def _is_env_var_name(value: str) -> bool:
    """The `provider_profile_posture` secret-name shape, applied to a reference.

    Same shape and the same reason: an environment variable *name* is safe to
    carry because it is not the value. The shape alone is not enough — plenty of
    issued credentials are upper-case alphanumerics too, and an `AKIA`-prefixed
    AWS access key id satisfies every character rule below — so the value is
    also screened through the credential boundary's own value detectors before
    it is accepted as a name.

    `is_secret_value_shaped` rather than `is_sensitive_metadata_text`: the wider
    predicate flags anything *named* like a secret, and an environment variable
    name legitimately is (`GITHUB_TOKEN`, `CODEX_API_KEY`). The narrow one flags
    issued material only, which is exactly the confusion this guard exists for.
    Its reach is the reach of those detectors and no further; a credential value
    none of them recognise still passes the shape.
    """
    if not 2 <= len(value) <= 96 or not value[0].isascii() or not value[0].isupper():
        return False
    if is_secret_value_shaped(value):
        return False
    return all(character.isascii() and (character.isupper() or character.isdigit() or character == "_") for character in value)


def _safe_account_handle(value: str) -> str:
    """An opaque handle for an account, or an empty string when it is not safe.

    Routed through the same admission check the envelope uses on every other
    caller-supplied reference, so an account name cannot become the one string
    on this record nobody screened.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        ensure_safe_opaque_ref_content(text, "account_ref")
    except ValueError:
        return ""
    return text


def build_task_handoff_safety_contract(envelope: dict[str, Any]) -> dict[str, Any]:
    """The task-scoped handoff safety contract, derived from the envelope and the host.

    Offline by construction: the boundary and evidence tables are module data,
    every task-specific value is read off the authority envelope this same build
    just produced, and the one host-dependent surface — whether this machine can
    enforce a #801 runtime limit — is a memoized local stat taken once per
    process through `data_boundary_facts`. Nothing here spawns a process,
    resolves a host, opens a socket, or consults a model, so the contract is
    reproducible on a machine with no network and byte-identical across repeated
    builds of the same delegation on the same host.

    That host dependence is named in `input_sources` rather than left implicit.
    It stays out of `safety_rule_profile()` for the reason that function's own
    comment gives: a host-dependent digest would read as profile drift on every
    second machine.

    Reading the envelope rather than re-deriving from intent and policy is
    deliberate: a contract that recomputed its own numbers could disagree with
    the envelope it describes, and the validator would have nothing to compare.

    The optional `post_completion_directive` rides through here too, unchanged,
    so the brief author reading the contract sees the merge boundary and the
    user's preserved intent side by side rather than only the prohibited-actions
    list. It is omitted when absent, so every existing contract stays
    byte-identical.
    """
    directive = envelope.get("post_completion_directive")
    contract: dict[str, Any] = {
        "schema_version": HANDOFF_SAFETY_CONTRACT_SCHEMA_VERSION,
        "status": "prepared_not_observed",
        "produced_offline": True,
        "input_sources": list(HANDOFF_CONTRACT_INPUT_SOURCES),
        "boundaries": [
            {
                "boundary": boundary,
                "statement": statement,
                "enforcement": enforcement,
                "enforced_by": list(enforced_by),
                "blocked_by": blocked_by,
            }
            for boundary, statement, enforcement, enforced_by, blocked_by in safety_boundaries()
        ],
        "evidence_requirements": [
            {
                "stage": stage,
                "claim": claim,
                "observation_event": observation_event,
                "enforcement": enforcement,
                "enforced_by": list(enforced_by),
                "blocked_by": blocked_by,
            }
            for stage, claim, observation_event, enforcement, enforced_by, blocked_by in _EVIDENCE_REQUIREMENTS
        ],
        "prohibited_actions": list(envelope.get("blocked_actions", [])),
        "allowed_executors": list(envelope.get("allowed_executors", [])),
        "allowed_targets": list(envelope.get("allowed_targets", [])),
        "merge_authority": str(envelope.get("merge_authority", "")),
        "external_action_authority": str(envelope.get("external_action_authority", "")),
        "safety_profile_revision": str(envelope.get("safety_profile_revision", "")),
        "claim_boundary": HANDOFF_CONTRACT_CLAIM_BOUNDARY,
    }
    if isinstance(directive, dict):
        contract["post_completion_directive"] = deepcopy(directive)
    return contract


def split_handoff_safety_contract(gate: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate the stored verdict from the safety contract it carried back.

    The contract is stored once, beside `action_gate` on the delegation, never
    inside it. Two copies of the same statement can disagree after a partial
    rebuild, and a reader has no way to tell which one is current.
    """
    verdict = {key: value for key, value in gate.items() if key != HANDOFF_SAFETY_CONTRACT_KEY}
    contract = gate.get(HANDOFF_SAFETY_CONTRACT_KEY)
    return verdict, contract if isinstance(contract, dict) else {}


_ALLOW_OUTCOMES = frozenset({"allow", "allowed", "ok", "pass", "passed"})
_DENY_OUTCOMES = frozenset({"block", "blocked", "deny", "denied", "refuse", "refused"})
_OUTCOME_KEYS = ("outcome", "status", "verdict", "allowed", "allow")


def normalize_safety_preflight(value: Any) -> dict[str, Any]:
    """Adapt the #804/#802 preflight verdict to the fields this gate consumes.

    The evaluator is owned elsewhere, so the field names are read tolerantly.
    Two different absences are treated differently on purpose: *no verdict at
    all* (no evaluator installed) allows, because a missing lane must not brick
    delegation, while a verdict whose outcome this adapter cannot read denies —
    an unrecognized outcome is the case where failing open would silently hand
    out the authority the verdict was supposed to withhold.
    """
    normalized = {
        "outcome": "allow",
        "rule_id": "",
        "field": "",
        "correction": "",
        "reason_codes": [],
        "safety_profile_revision": "",
        "claim_boundary": "",
    }
    if not isinstance(value, dict):
        return normalized
    outcome = str(value.get("outcome", value.get("status", value.get("verdict", "")))).strip().lower()
    allowed = value.get("allowed", value.get("allow"))
    if allowed is False or outcome in _DENY_OUTCOMES:
        normalized["outcome"] = "deny"
    elif allowed is True or outcome in _ALLOW_OUTCOMES:
        normalized["outcome"] = "allow"
    elif any(key in value for key in _OUTCOME_KEYS):
        normalized["outcome"] = "deny"
        normalized["rule_id"] = "safety_preflight_outcome_unreadable"
        normalized["field"] = "status"
        normalized["correction"] = (
            "The safety preflight returned an outcome this delegation lane cannot read; "
            "upgrade the lane or re-run the preflight before preparing a handoff."
        )
    normalized["rule_id"] = str(value.get("rule_id", value.get("rule", "")) or "") or normalized["rule_id"]
    normalized["field"] = str(value.get("field", value.get("field_path", "")) or "") or normalized["field"]
    normalized["correction"] = (
        str(value.get("correction", value.get("remediation", value.get("fix", ""))) or "") or normalized["correction"]
    )
    codes: list[str] = []
    single = value.get("reason_code")
    if isinstance(single, str) and single:
        codes.append(single)
    for key in ("reason_codes", "org_reason_codes", "org_source_reason_codes"):
        listed = value.get(key)
        if isinstance(listed, (list, tuple)):
            codes.extend(str(code) for code in listed)
    normalized["reason_codes"] = sorted(dict.fromkeys(codes))
    normalized["safety_profile_revision"] = str(
        value.get("safety_profile_revision", value.get("revision", "")) or ""
    )
    normalized["claim_boundary"] = str(value.get("claim_boundary", "") or "")
    return normalized


def _denial_from_preflight(preflight: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": preflight["rule_id"] or "safety_preflight_denied",
        "field": preflight["field"] or "message",
        "correction": preflight["correction"]
        or "Narrow the request to what the workspace safety policy allows, then ask again.",
        "reason_codes": list(preflight["reason_codes"]),
        "source": "safety_preflight",
    }


def _revision_drift_denial(carried: str, live: str) -> dict[str, Any]:
    return {
        "rule_id": REVISION_DRIFT_RULE_ID,
        "field": REVISION_DRIFT_FIELD,
        "correction": REVISION_DRIFT_CORRECTION,
        "reason_codes": [f"carried:{carried or 'none'}", f"live:{live or 'none'}"],
        "source": REVISION_DRIFT_RULE_ID,
    }


def _arbitrate_confirmation(
    *,
    denied: bool,
    choice_required: bool,
    expansion_requested: bool,
    risky_action_ask: bool,
    risky_action_refused: bool,
    dispatchable: bool,
) -> dict[str, Any]:
    """Pick at most one ladder and record why every other one stayed silent.

    `risky_action_ask` and `risky_action_refused` are already gated on the risk
    verdict being enforced. A ladder whose answer cannot be recorded is not
    armed here at all: asking a question nothing can answer is how a request
    ends with no route forward.
    """
    if denied:
        winner = ""
        reason = "A denied request is corrected, not confirmed; no ladder is armed."
    elif risky_action_refused:
        # A revoked or refused approval is an answer. Re-arming the ladder would
        # be asking again until the answer changes, so the refusal stands and the
        # authority it covered stays withheld.
        winner = ""
        reason = (
            "The operator already refused or revoked the approval this risky action needs, so the "
            "authority stays withheld and no ladder asks again."
        )
    elif choice_required:
        winner = "executor_selection"
        reason = "The coding agent that owns this work is not chosen yet, so nothing downstream can be confirmed."
    elif expansion_requested:
        winner = "permission_profile"
        reason = "The request asks for authority outside the derived envelope, so widening routes through one profile choice."
    elif risky_action_ask:
        winner = "risky_action"
        reason = (
            "A risky action inside the envelope has no recorded approval covering this action, scope, "
            "owner, run, and safety profile revision, so the act itself needs one answer."
        )
    elif dispatchable:
        winner = "operator_confirmation"
        reason = "The envelope already allows dispatch, so only the act itself needs a go-ahead."
    else:
        winner = ""
        reason = "Nothing in this handoff needs an authority decision from the user."

    suppressed = []
    for ladder in CONFIRMATION_LADDERS:
        if ladder == winner:
            continue
        if denied:
            suppressed.append({"ladder": ladder, "reason": "suppressed_by:denial"})
        elif risky_action_refused:
            suppressed.append({"ladder": ladder, "reason": "suppressed_by:refused_approval"})
        elif winner:
            suppressed.append({"ladder": ladder, "reason": f"superseded_by:{winner}"})
        else:
            suppressed.append({"ladder": ladder, "reason": "not_applicable_to_this_intent"})
    return {
        "required": bool(winner),
        "ladder": winner or "none",
        "action_id": LADDER_ACTION_IDS.get(winner, ""),
        "reason": reason,
        "arbitration_rule": SINGLE_PROMPT_RULE,
        "candidate_ladders": list(CONFIRMATION_LADDERS),
        "armed_ladders": [winner] if winner else [],
        "suppressed_ladders": suppressed,
    }


def evaluate_action_gate(
    *,
    message: str,
    delegation_action: str,
    intent: str,
    review_required: bool,
    work_owner_mode: str,
    selected_executor_profile: str | None,
    dispatch_policy: str,
    dispatchable: bool,
    choice_required: bool,
    executor_selection_status: str,
    isolation_plan: dict[str, Any] | None = None,
    context_pack: dict[str, Any] | None = None,
    memory_recall_pack: dict[str, Any] | None = None,
    safety_preflight: dict[str, Any] | None = None,
    safety_preflight_request: dict[str, Any] | None = None,
    live_safety_profile_revision: str | None = None,
    requested_actions: list[str] | tuple[str, ...] | None = None,
    approval_receipts: Any = None,
    executor_auth_signals: dict[str, Any] | None = None,
    account_references: dict[str, str] | None = None,
    run_id: str = "",
    now: str = "",
    post_completion_directive: str = "",
) -> dict[str, Any]:
    """The single decision path: preflight, envelope, risk, and one ladder.

    The safety-profile revision re-check runs *before* the confirmation is
    arbitrated, so a user never pays a prompt for work that then hard-fails on
    drift. The risk classification runs after the envelope and before the
    arbitration, for the same reason in the other direction: the ladder that is
    armed has to be the ladder the classified risk asks for.

    `requested_actions` is one seam with two directions. Actions outside the
    envelope widen it and route through the permission-profile ladder; actions
    inside it narrow it, which is the "narrow" answer to a risky-action
    confirmation and is #800's first real caller of that parameter.

    The risky-action ladder only arms, and authority is only withheld, when the
    confirmation can actually be answered — which means `run_id` is set, because
    an approval binds to a run and `build_approval_receipt` refuses an empty
    one. Without it no receipt that could release the work is constructible, so
    arming would leave a user permanently blocked with no route forward; the
    classification rides as a report instead and
    `action_risk.enforcement` says so on the record.

    Every new input is something the caller already holds. `approval_receipts`
    and `executor_auth_signals` are read elsewhere and handed in, so this
    function still opens nothing.
    """
    preflight = normalize_safety_preflight(safety_preflight)
    denial: dict[str, Any] | None = None
    if preflight["outcome"] == "deny":
        denial = _denial_from_preflight(preflight)
    elif live_safety_profile_revision is not None and preflight["safety_profile_revision"] and str(
        live_safety_profile_revision
    ) != preflight["safety_profile_revision"]:
        denial = _revision_drift_denial(preflight["safety_profile_revision"], str(live_safety_profile_revision))
    denied = denial is not None

    effective_dispatchable = bool(dispatchable) and not denied
    effective_choice_required = bool(choice_required) and not denied
    requested = {str(action) for action in (requested_actions or [])}
    # Widening and narrowing travel the same seam and are told apart by one
    # question: is anything asked for outside what the task already required?
    # An empty request narrows nothing, so the default path is untouched.
    unnarrowed = build_task_authority_envelope(
        denied=denied,
        delegation_action=delegation_action,
        intent=intent,
        review_required=review_required,
        work_owner_mode="retained_hermes" if denied else work_owner_mode,
        selected_executor_profile=None if denied else selected_executor_profile,
        # The *proposed* values, not the collapsed ones: a denied envelope must
        # still be able to say which actions the denial withdrew, and both the
        # profile and the required set already collapse on `denied` internally.
        dispatchable=bool(dispatchable),
        choice_required=bool(choice_required),
        isolation_plan={} if denied else isolation_plan,
        message=message,
        context_pack=context_pack,
        memory_recall_pack=memory_recall_pack,
        safety_profile_revision=preflight["safety_profile_revision"],
        post_completion_directive=post_completion_directive,
    )
    expansion_requested = bool(requested - set(unnarrowed["allowed_actions"]))
    narrow_to = None if expansion_requested or not requested else set(requested)

    def _envelope(withheld: set[str] | None = None) -> dict[str, Any]:
        return build_task_authority_envelope(
            denied=denied,
            delegation_action=delegation_action,
            intent=intent,
            review_required=review_required,
            work_owner_mode="retained_hermes" if denied else work_owner_mode,
            selected_executor_profile=None if denied else selected_executor_profile,
            dispatchable=bool(dispatchable),
            choice_required=bool(choice_required),
            isolation_plan={} if denied else isolation_plan,
            message=message,
            context_pack=context_pack,
            memory_recall_pack=memory_recall_pack,
            safety_profile_revision=preflight["safety_profile_revision"],
            narrow_to=narrow_to,
            withheld=withheld,
            post_completion_directive=post_completion_directive,
        )

    envelope = unnarrowed if narrow_to is None else _envelope()
    owner = "" if denied else str(selected_executor_profile or "")
    action_risk = classify_action_risk(
        envelope=envelope,
        isolation_plan={} if denied else isolation_plan,
        safety_preflight_request=safety_preflight_request,
        approval_receipts=approval_receipts,
        owner=owner,
        run_id=run_id,
        now=now,
    )
    # The refusal, and the one condition under which it is a refusal at all.
    # Every action carrying an unapproved class — not one collapsed stand-in for
    # all of them — plus the dispatch that would carry them, is withheld from the
    # envelope, and the verdict stops being dispatchable, so a caller cannot read
    # an armed ladder as the consent that was never given.
    #
    # `enforced` is what gates that. When the confirmation cannot be answered,
    # withholding would not gate the work, it would end it: nothing could ever
    # release the authority again. There the classification is reported, the
    # ladder stays silent, and `action_risk.blocked_by` names why.
    risk_enforced = action_risk["enforcement"] == "enforced"
    risk_allows = action_risk["decision"] == "allow"
    withheld_actions = [str(action) for action in action_risk["withheld_actions"]]
    if risk_enforced and not risk_allows:
        withheld = {*withheld_actions, "executor_dispatch"}
        envelope = _envelope(withheld={action for action in withheld if action})
        action_risk["narrowing_route"] = _narrowing_route(unnarrowed, withheld_actions)
        effective_dispatchable = False
    account_authorization = build_account_authorization(
        envelope=envelope,
        auth_signals=executor_auth_signals,
        account_references=account_references,
        # Withheld authority is authority the task still needs; see the note in
        # `build_account_authorization`. Read back off the envelope's own
        # exclusions rather than recomputed, so it is exactly what was withheld.
        withheld_actions=[
            str(entry["action"])
            for entry in envelope["exclusions"]
            if entry.get("reason_code") == "withheld_pending_approval"
        ],
        now=now,
    )
    confirmation = _arbitrate_confirmation(
        denied=denied,
        choice_required=effective_choice_required,
        expansion_requested=expansion_requested,
        risky_action_ask=risk_enforced and action_risk["decision"] == "ask",
        risky_action_refused=risk_enforced and action_risk["decision"] == "deny",
        dispatchable=effective_dispatchable,
    )
    verdict: dict[str, Any] = {
        "schema_version": ACTION_GATE_SCHEMA_VERSION,
        "status": "prepared_not_observed",
        "outcome": "deny" if denied else "allow",
        "dispatchable": effective_dispatchable,
        "choice_required": effective_choice_required,
        "executor_selection_status": "retained_hermes" if denied else executor_selection_status,
        "work_owner_mode": "retained_hermes" if denied else work_owner_mode,
        "selected_executor_profile": None if denied else selected_executor_profile,
        "dispatch_policy": "prepare_only" if denied or (risk_enforced and not risk_allows) else dispatch_policy,
        "confirmation": confirmation,
        "authority_envelope": envelope,
        "action_risk": action_risk,
        "account_authorization": account_authorization,
        "safety_profile_revision": preflight["safety_profile_revision"],
        "claim_boundary": GATE_CLAIM_BOUNDARY,
        # Built here because this is the one place that runs exactly once per
        # delegation build. The delegation lifts it out before storing, so the
        # contract lives beside the gate rather than inside it.
        HANDOFF_SAFETY_CONTRACT_KEY: build_task_handoff_safety_contract(envelope),
    }
    if denial is not None:
        verdict["denial"] = denial
    return verdict


def recheck_safety_profile_revision(carried: str, live: str | None) -> str:
    """Cheap re-check helper: return a drift reason, or "" when the revision holds."""
    carried_value = str(carried or "")
    if not carried_value:
        return ""
    live_value = str(live or "")
    if live_value == carried_value:
        return ""
    return f"safety profile revision drifted: carried {carried_value or 'none'}, live {live_value or 'none'}"


def _string_list_errors(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return [f"{label} must be a list of strings"]
    return []


def validate_task_authority_envelope(
    value: Any,
    label: str = "task_authority_envelope",
    *,
    lane: str | None = None,
    parent_dispatchable: Any = None,
) -> list[str]:
    """Validate one envelope, including the child-cannot-exceed-parent lattice."""
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    errors: list[str] = []
    # `post_completion_directive` is the one optional key: its ABSENCE must stay
    # valid and byte-identical, so it is excluded from the required-key set and
    # its shape is only checked when it is present.
    missing = set(TASK_AUTHORITY_ENVELOPE_KEYS) - set(value)
    extra = set(value) - set(TASK_AUTHORITY_ENVELOPE_KEYS) - {"post_completion_directive"}
    if missing or extra:
        errors.append(f"{label} keys are invalid")
    if "post_completion_directive" in value:
        errors.extend(_post_completion_directive_errors(value.get("post_completion_directive"), label))
    if value.get("schema_version") != TASK_AUTHORITY_ENVELOPE_SCHEMA_VERSION:
        errors.append(f"{label} schema_version is invalid")
    if value.get("status") != "prepared_not_observed":
        errors.append(f"{label} status is invalid")
    if value.get("permission_profile") not in permission_profiles():
        errors.append(f"{label} permission_profile is unsupported")
    vocabulary = set(loop_actions())
    allowed = value.get("allowed_actions")
    blocked = value.get("blocked_actions")
    if not isinstance(allowed, list) or not set(allowed) <= vocabulary or sorted(set(allowed)) != allowed:
        errors.append(f"{label} allowed_actions is invalid")
        allowed = []
    if not isinstance(blocked, list) or sorted(vocabulary - set(allowed)) != blocked:
        errors.append(f"{label} blocked_actions must be the sorted complement of allowed_actions")
        blocked = []
    exclusions = value.get("exclusions")
    if not isinstance(exclusions, list):
        errors.append(f"{label} exclusions must be a list")
    else:
        if [entry.get("action") for entry in exclusions if isinstance(entry, dict)] != blocked:
            errors.append(f"{label} exclusions must explain exactly the blocked actions")
        for index, entry in enumerate(exclusions):
            if not isinstance(entry, dict) or set(entry) != set(EXCLUSION_KEYS):
                errors.append(f"{label} exclusions[{index}] keys are invalid")
                continue
            if entry.get("reason_code") not in EXCLUSION_REASON_CODES:
                errors.append(f"{label} exclusions[{index}].reason_code is unsupported")
            if not str(entry.get("explanation", "")).strip():
                errors.append(f"{label} exclusions[{index}].explanation is required")
    errors.extend(_string_list_errors(value.get("allowed_executors"), f"{label} allowed_executors"))
    errors.extend(_string_list_errors(value.get("allowed_targets"), f"{label} allowed_targets"))
    mutation_rights = value.get("mutation_rights")
    if not isinstance(mutation_rights, list) or not set(mutation_rights) <= set(allowed) & set(MUTATING_ACTIONS):
        errors.append(f"{label} mutation_rights must be allowed mutating actions")
    if value.get("merge_authority") != ("granted" if "merge" in allowed else "disabled"):
        errors.append(f"{label} merge_authority must match the allowed action set")
    expected_external = "publish_allowed" if "external_posting" in allowed else "prepare_only"
    if value.get("external_action_authority") != expected_external:
        errors.append(f"{label} external_action_authority must match the allowed action set")
    expansion = value.get("expansion_policy")
    if not isinstance(expansion, dict) or set(expansion) != set(EXPANSION_POLICY_KEYS):
        errors.append(f"{label} expansion_policy keys are invalid")
    else:
        if expansion.get("widening_route") != "confirmation_required":
            errors.append(f"{label} expansion_policy must route widening through confirmation")
        if expansion.get("self_expansion_allowed") is not False:
            errors.append(f"{label} expansion_policy must not allow self expansion")
        if list(expansion.get("authority_sources", [])) != list(AUTHORITY_SOURCES):
            errors.append(f"{label} expansion_policy authority_sources are invalid")
    untrusted = value.get("untrusted_input_policy")
    if not isinstance(untrusted, dict) or set(untrusted) != set(UNTRUSTED_INPUT_POLICY_KEYS):
        errors.append(f"{label} untrusted_input_policy keys are invalid")
    else:
        if untrusted.get("text_cannot_expand_authority") is not True:
            errors.append(f"{label} untrusted_input_policy must mark text as unable to expand authority")
        if untrusted.get("effect_on_authority") != "none":
            errors.append(f"{label} untrusted_input_policy effect_on_authority must be none")
        if list(untrusted.get("inspected_surfaces", [])) != list(UNTRUSTED_SURFACES):
            errors.append(f"{label} untrusted_input_policy inspected_surfaces are invalid")
        flagged = untrusted.get("flagged_surfaces")
        if not isinstance(flagged, list) or not set(flagged) <= set(UNTRUSTED_SURFACES) or sorted(set(flagged)) != flagged:
            errors.append(f"{label} untrusted_input_policy flagged_surfaces are invalid")
    if not isinstance(value.get("safety_profile_revision"), str):
        errors.append(f"{label} safety_profile_revision must be a string")
    if "not dispatch" not in str(value.get("claim_boundary", "")).lower():
        errors.append(f"{label} claim_boundary must preserve the dispatch boundary")
    if "executor_dispatch" in allowed and parent_dispatchable is not True:
        errors.append(f"{label} executor_dispatch requires a dispatchable parent handoff")
    if lane in {"runtime_handoff", "prompt_handoff"} and "executor_dispatch" in allowed:
        errors.append(f"{label} {lane} cannot grant executor dispatch authority")
    return errors


def _risk_class_entry_errors(value: Any, label: str, *, expected: tuple[str, ...]) -> list[str]:
    if not isinstance(value, list):
        return [f"{label} must be a list"]
    errors: list[str] = []
    if [entry.get("class") for entry in value if isinstance(entry, dict)] != list(expected):
        errors.append(f"{label} must be exactly {list(expected)} in order")
    for index, entry in enumerate(value):
        entry_label = f"{label}[{index}]"
        if not isinstance(entry, dict) or set(entry) != set(RISK_CLASS_ENTRY_KEYS):
            errors.append(f"{entry_label} keys are invalid")
            continue
        if entry.get("derivation") not in RISK_DERIVATIONS:
            errors.append(f"{entry_label}.derivation is unsupported")
        actions = entry.get("approvable_actions")
        if not isinstance(actions, list) or not actions or not set(actions) <= set(APPROVABLE_ACTIONS):
            errors.append(f"{entry_label}.approvable_actions must be a non-empty list of approvable actions")
        if not str(entry.get("statement", "")).strip():
            errors.append(f"{entry_label}.statement is required")
        # The anti-decoration rule, applied to the risk vocabulary: a subsumed
        # class must name the class that carries it, and a class something can
        # assert must not pretend to be carried by something else.
        carrier = str(entry.get("carrier", ""))
        if entry.get("derivation") == "subsumed":
            if carrier not in _DERIVABLE_CLASSES:
                errors.append(f"{entry_label} is subsumed, so it must name a derivable carrier")
        elif carrier:
            errors.append(f"{entry_label} is derived directly, so it must not name a carrier")
    return errors


def _consent_entry_errors(value: Any, label: str, *, present: list[Any]) -> list[str]:
    """Every present class is asked about, on every action that carries it.

    The anti-collapse rule as a check. A verdict may not name one action and
    call three classes answered, and it may not quietly drop a class from the
    consent list: a class in `classes` with no consent entry is a risk nobody
    was asked about.
    """
    if not isinstance(value, list):
        return [f"{label} must be a list"]
    errors: list[str] = []
    covered: set[str] = set()
    for index, entry in enumerate(value):
        entry_label = f"{label}[{index}]"
        if not isinstance(entry, dict) or set(entry) != set(CONSENT_ENTRY_KEYS):
            errors.append(f"{entry_label} keys are invalid")
            continue
        risk_class = str(entry.get("class", ""))
        covered.add(risk_class)
        if risk_class not in present:
            errors.append(f"{entry_label}.class must be a class this verdict reports as present")
        action = entry.get("approved_action")
        if action not in APPROVABLE_ACTIONS:
            errors.append(f"{entry_label}.approved_action must be an approvable action")
        elif action not in _RISK_CLASS_ACTIONS.get(risk_class, ()):
            errors.append(f"{entry_label}.approved_action must be an action that carries its own class")
        if entry.get("decision") not in ACTION_RISK_DECISIONS:
            errors.append(f"{entry_label}.decision is unsupported")
        request = entry.get("approval_request")
        if not isinstance(request, dict) or set(request) != set(APPROVAL_REQUEST_KEYS):
            errors.append(f"{entry_label}.approval_request keys are invalid")
        else:
            if request.get("approved_action") != action:
                errors.append(f"{entry_label}.approval_request must ask about the action it names")
            if request.get("scope_class") not in SCOPE_CLASSES:
                errors.append(f"{entry_label}.approval_request.scope_class is unsupported")
        approval = entry.get("approval")
        if not isinstance(approval, dict) or approval.get("satisfied") is None:
            errors.append(f"{entry_label} must name the approval decision it acted on")
        elif (entry.get("decision") == "allow") is not (approval.get("satisfied") is True):
            errors.append(f"{entry_label} may only allow on a satisfying approval")
    missing = sorted(name for name in present if isinstance(name, str) and name not in covered)
    if missing:
        errors.append(f"{label} must ask about every present class; {missing} has no consent entry")
    return errors


def validate_action_risk(value: Any, label: str = "action_risk") -> list[str]:
    """Validate one action-risk verdict, including that it stayed explainable.

    Three failure classes, mirroring the handoff contract's. The first is an
    unexplained verdict: a decision with no reason, a present class with no
    statement, or a subsumed class with no carrier. The second is a verdict that
    asks or refuses without naming the approval it wanted, which is how "we
    checked" becomes unfalsifiable. The third is the collapse: an `allow` while
    any class present is unapproved, or a class present that no consent entry
    asks about — either one lets one answer speak for several questions.
    """
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    errors: list[str] = []
    if set(value) != set(ACTION_RISK_KEYS):
        errors.append(f"{label} keys are invalid")
    if value.get("schema_version") != ACTION_RISK_SCHEMA_VERSION:
        errors.append(f"{label} schema_version is invalid")
    if value.get("status") != "prepared_not_observed":
        errors.append(f"{label} status is invalid")
    if value.get("level") not in ACTION_RISK_LEVELS:
        errors.append(f"{label} level is unsupported")
    decision = value.get("decision")
    if decision not in ACTION_RISK_DECISIONS:
        errors.append(f"{label} decision is unsupported")
    if not str(value.get("reason", "")).strip():
        errors.append(f"{label} decision must be explained")
    classes = value.get("classes")
    present = [entry.get("class") for entry in classes if isinstance(entry, dict)] if isinstance(classes, list) else []
    errors.extend(
        _risk_class_entry_errors(
            classes,
            f"{label} classes",
            expected=tuple(name for name in RISK_CLASS_NAMES if name in present),
        )
    )
    errors.extend(
        _risk_class_entry_errors(
            value.get("subsumed_classes"),
            f"{label} subsumed_classes",
            expected=tuple(name for name, derivation, _a, _c, _s in _RISK_CLASS_RULES if derivation == "subsumed"),
        )
    )
    if (value.get("level") == "none") is not (not present):
        errors.append(f"{label} level must be none exactly when no risky class is present")
    consent = value.get("consent")
    if present:
        errors.extend(_consent_entry_errors(consent, f"{label} consent", present=present))
    elif consent:
        errors.append(f"{label} consent is only allowed when a risky class is present")
    entries = [entry for entry in consent if isinstance(entry, dict)] if isinstance(consent, list) else []
    unapproved = [entry for entry in entries if entry.get("decision") != "allow"]
    if decision == "allow" and unapproved:
        errors.append(
            f"{label} cannot allow while a present class is unapproved: "
            f"{sorted({str(entry.get('class', '')) for entry in unapproved})}"
        )
    if decision == "allow" and present and not entries:
        errors.append(f"{label} cannot allow a risky action without a satisfying approval")
    withheld = value.get("withheld_actions")
    expected_withheld = sorted({str(entry.get("approved_action", "")) for entry in unapproved})
    if not isinstance(withheld, list) or withheld != expected_withheld:
        errors.append(f"{label} withheld_actions must be exactly the unapproved actions, sorted")
    errors.extend(_enforcement_errors(value, label))
    narrowing = value.get("narrowing_route")
    if not isinstance(narrowing, dict):
        errors.append(f"{label} narrowing_route must be an object")
    elif present:
        if set(narrowing) != set(NARROWING_ROUTE_KEYS):
            errors.append(f"{label} narrowing_route keys are invalid")
        elif narrowing.get("parameter") != "requested_authority_actions":
            errors.append(f"{label} narrowing_route must route through requested_authority_actions")
    if list(value.get("inputs", [])) != list(ACTION_RISK_INPUTS):
        errors.append(f"{label} inputs must be the declared policy inputs")
    for key in ("text_policy", "isolation_risk_relationship"):
        if not str(value.get(key, "")).strip():
            errors.append(f"{label} {key} is required")
    if "not dispatch" not in str(value.get("claim_boundary", "")).lower():
        errors.append(f"{label} claim_boundary must preserve the dispatch boundary")
    return errors


def validate_account_authorization(value: Any, label: str = "account_authorization") -> list[str]:
    """Validate the #799 projection, including that it stays declared not enforced."""
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    errors: list[str] = []
    if set(value) != set(ACCOUNT_AUTHORIZATION_KEYS):
        errors.append(f"{label} keys are invalid")
    if value.get("schema_version") != ACCOUNT_AUTHORIZATION_SCHEMA_VERSION:
        errors.append(f"{label} schema_version is invalid")
    if value.get("status") != "prepared_not_observed":
        errors.append(f"{label} status is invalid")
    if not isinstance(value.get("required"), bool):
        errors.append(f"{label} required must be boolean")
    if not str(value.get("reason", "")).strip():
        errors.append(f"{label} reason is required")
    accounts = value.get("accounts")
    if not isinstance(accounts, list):
        errors.append(f"{label} accounts must be a list")
    else:
        for index, entry in enumerate(accounts):
            entry_label = f"{label} accounts[{index}]"
            if not isinstance(entry, dict) or set(entry) != set(ACCOUNT_ENTRY_KEYS):
                errors.append(f"{entry_label} keys are invalid")
                continue
            if entry.get("state") not in ACCOUNT_ACCESS_STATES:
                errors.append(f"{entry_label}.state is unsupported")
            if entry.get("reference_kind") not in ACCOUNT_REFERENCE_KINDS:
                errors.append(f"{entry_label}.reference_kind is unsupported")
            if entry.get("reference_kind") == "env_var_name" and not _is_env_var_name(str(entry.get("account_ref", ""))):
                errors.append(f"{entry_label}.account_ref must be an environment variable name, never a value")
            errors.extend(_string_list_errors(entry.get("minimum_scopes"), f"{entry_label}.minimum_scopes"))
            if not set(entry.get("minimum_scopes", []) or []) <= set(ACCOUNT_BACKED_ACTIONS):
                errors.append(f"{entry_label}.minimum_scopes must be account-backed actions")
    # The whole point of this block is that it does not enforce. A future edit
    # that flips it has to move the enforcement verdict deliberately.
    errors.extend(_enforcement_errors(value, label))
    if value.get("enforcement") != "declared_not_enforced":
        errors.append(f"{label} must stay declared_not_enforced while no host consent flow is observable")
    blockers = value.get("blockers")
    if not isinstance(blockers, list) or [
        entry.get("blocker") for entry in blockers if isinstance(entry, dict)
    ] != list(ACCOUNT_BLOCKER_NAMES):
        errors.append(f"{label} blockers must be exactly {list(ACCOUNT_BLOCKER_NAMES)} in order")
    elif any(not str(entry.get("statement", "")).strip() for entry in blockers):
        errors.append(f"{label} every blocker must state the gap in words")
    if "credential" not in str(value.get("credential_boundary", "")).lower():
        errors.append(f"{label} credential_boundary must cite the credential boundary")
    if "not dispatch" not in str(value.get("claim_boundary", "")).lower():
        errors.append(f"{label} claim_boundary must preserve the dispatch boundary")
    return errors


def _enforcement_errors(
    entry: dict[str, Any],
    label: str,
) -> list[str]:
    """The anti-decoration rule, applied to one boundary or evidence entry.

    An `enforced` entry must name at least one dotted symbol that a reader can
    open, and must not name a blocker. A `declared_not_enforced` entry must name
    a blocker and must not name an enforcer. Anything else is a claim of
    coverage nobody can check, which is what this contract exists to prevent.
    """
    errors: list[str] = []
    enforcement = entry.get("enforcement")
    if enforcement not in ENFORCEMENT_LEVELS:
        return [f"{label}.enforcement is unsupported"]
    enforced_by = entry.get("enforced_by")
    blocked_by = entry.get("blocked_by")
    if not isinstance(enforced_by, list) or not all(isinstance(item, str) for item in enforced_by):
        errors.append(f"{label}.enforced_by must be a list of strings")
        enforced_by = []
    if not isinstance(blocked_by, str):
        errors.append(f"{label}.blocked_by must be a string")
        blocked_by = ""
    if enforcement == "enforced":
        if not enforced_by:
            errors.append(f"{label} claims enforcement but names no enforcing symbol")
        if blocked_by:
            errors.append(f"{label} is enforced, so it must not name a blocker")
    else:
        if enforced_by:
            errors.append(f"{label} is not enforced, so it must not name an enforcing symbol")
        if not blocked_by.strip():
            errors.append(f"{label} is not enforced, so it must name the blocker that must land first")
    for index, symbol in enumerate(enforced_by):
        if not symbol.startswith("omh.") or symbol.count(".") < 2:
            errors.append(f"{label}.enforced_by[{index}] must be a dotted omh symbol reference")
    return errors


def _handoff_contract_boundary_errors(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{label} boundaries must be a list"]
    names = [entry.get("boundary") for entry in value if isinstance(entry, dict)]
    errors: list[str] = []
    expected = list(safety_boundary_names())
    if names != expected:
        # One message covers unknown, missing, duplicated, and reordered names:
        # the boundary set is the contract, so any difference is the same defect.
        errors.append(f"{label} boundaries must be exactly {expected} in order")
    for index, entry in enumerate(value):
        entry_label = f"{label} boundaries[{index}]"
        if not isinstance(entry, dict) or set(entry) != set(SAFETY_BOUNDARY_KEYS):
            errors.append(f"{entry_label} keys are invalid")
            continue
        if not str(entry.get("statement", "")).strip():
            errors.append(f"{entry_label}.statement is required")
        errors.extend(_enforcement_errors(entry, entry_label))
    return errors


def _handoff_contract_evidence_errors(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{label} evidence_requirements must be a list"]
    stages = [entry.get("stage") for entry in value if isinstance(entry, dict)]
    errors: list[str] = []
    if stages != list(HANDOFF_EVIDENCE_STAGES):
        errors.append(f"{label} evidence_requirements must cover exactly {list(HANDOFF_EVIDENCE_STAGES)} in order")
    for index, entry in enumerate(value):
        entry_label = f"{label} evidence_requirements[{index}]"
        if not isinstance(entry, dict) or set(entry) != set(EVIDENCE_REQUIREMENT_KEYS):
            errors.append(f"{entry_label} keys are invalid")
            continue
        if not str(entry.get("observation_event", "")).strip():
            errors.append(f"{entry_label}.observation_event is required")
        if entry.get("enforcement") == "enforced" and not str(entry.get("claim", "")).strip():
            errors.append(f"{entry_label} claims enforcement, so it must name the claim rung it gates")
        errors.extend(_enforcement_errors(entry, entry_label))
    return errors


def validate_handoff_safety_contract(
    value: Any,
    label: str = "handoff_safety_contract",
    *,
    envelope: Any = None,
) -> list[str]:
    """Validate one handoff safety contract against the envelope it describes.

    Two failure classes matter. The first is decoration: a boundary that claims
    enforcement without naming an enforcer, or a boundary name nobody has an
    entry for. The second is disagreement: a contract whose prohibited actions,
    executors, targets, or authority values no longer match the envelope stored
    beside it, which is how a stale copy is spotted.
    """
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    errors: list[str] = []
    # `post_completion_directive` is the one optional key here, mirroring the
    # envelope: absent by default (byte-identical), shape-checked when present.
    missing = set(HANDOFF_SAFETY_CONTRACT_KEYS) - set(value)
    extra = set(value) - set(HANDOFF_SAFETY_CONTRACT_KEYS) - {"post_completion_directive"}
    if missing or extra:
        errors.append(f"{label} keys are invalid")
    if "post_completion_directive" in value:
        errors.extend(_post_completion_directive_errors(value.get("post_completion_directive"), label))
    if value.get("schema_version") != HANDOFF_SAFETY_CONTRACT_SCHEMA_VERSION:
        errors.append(f"{label} schema_version is invalid")
    if value.get("status") != "prepared_not_observed":
        errors.append(f"{label} status is invalid")
    if value.get("produced_offline") is not True:
        errors.append(f"{label} produced_offline must be true")
    if list(value.get("input_sources", [])) != list(HANDOFF_CONTRACT_INPUT_SOURCES):
        errors.append(f"{label} input_sources must be the allowlisted local metadata surfaces")
    errors.extend(_handoff_contract_boundary_errors(value.get("boundaries"), label))
    errors.extend(_handoff_contract_evidence_errors(value.get("evidence_requirements"), label))
    for key in ("prohibited_actions", "allowed_executors", "allowed_targets"):
        errors.extend(_string_list_errors(value.get(key), f"{label} {key}"))
    for key in ("merge_authority", "external_action_authority", "safety_profile_revision"):
        if not isinstance(value.get(key), str):
            errors.append(f"{label} {key} must be a string")
    if "not dispatch" not in str(value.get("claim_boundary", "")).lower():
        errors.append(f"{label} claim_boundary must preserve the dispatch boundary")
    if isinstance(envelope, dict):
        for contract_key, envelope_key in (
            ("prohibited_actions", "blocked_actions"),
            ("allowed_executors", "allowed_executors"),
            ("allowed_targets", "allowed_targets"),
            ("merge_authority", "merge_authority"),
            ("external_action_authority", "external_action_authority"),
            ("safety_profile_revision", "safety_profile_revision"),
        ):
            if value.get(contract_key) != envelope.get(envelope_key):
                errors.append(f"{label} {contract_key} must match the authority envelope {envelope_key}")
        # The directive is a copy of the envelope's, so the same stale-copy rule
        # applies: it must match, and it must be present in the contract exactly
        # when the envelope carries it.
        if value.get("post_completion_directive") != envelope.get("post_completion_directive"):
            errors.append(f"{label} post_completion_directive must match the authority envelope")
    return errors


def _verdict_risk_consistency_errors(value: dict[str, Any], action_risk: Any, label: str) -> list[str]:
    """The two rules that tie a risk verdict to the envelope beside it.

    The first is the anti-phantom rule: every action a confirmation asks about
    must be one the envelope granted. A withheld action is checked against the
    envelope's own `withheld_pending_approval` exclusions, because withholding
    it is exactly what removed it from `allowed_actions`; anything else is an
    approval request for authority nobody was ever given, which no receipt can
    ever satisfy.

    The second is the refusal rule: an *enforced* unapproved risky action may
    not leave the verdict dispatchable. A verdict that reports
    `declared_not_enforced` is a report and is allowed to stay dispatchable —
    that is what the label means, and `blocked_by` has to say why.
    """
    if not isinstance(action_risk, dict):
        return []
    errors: list[str] = []
    envelope = value.get("authority_envelope")
    envelope = envelope if isinstance(envelope, dict) else {}
    allowed = set(_declared_strings(envelope, "allowed_actions"))
    exclusions = envelope.get("exclusions")
    withheld = {
        str(entry.get("action", ""))
        for entry in (exclusions if isinstance(exclusions, list) else [])
        if isinstance(entry, dict) and entry.get("reason_code") == "withheld_pending_approval"
    }
    grantable = allowed | withheld
    consent = action_risk.get("consent")
    for index, entry in enumerate(consent if isinstance(consent, list) else []):
        if not isinstance(entry, dict):
            continue
        action = str(entry.get("approved_action", ""))
        if action and action not in grantable:
            errors.append(
                f"{label} action_risk consent[{index}] asks to approve `{action}`, which the authority "
                "envelope neither allows nor withheld, so no approval could ever release it"
            )
    if (
        action_risk.get("enforcement") == "enforced"
        and action_risk.get("decision") != "allow"
        and value.get("dispatchable") is True
    ):
        errors.append(f"{label} cannot stay dispatchable while a risky action has no approval covering it")
    return errors


def validate_action_gate_verdict(value: Any, label: str = "action_gate") -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    errors: list[str] = []
    extra = sorted(set(value) - set(ACTION_GATE_KEYS))
    if extra:
        errors.append(f"{label} has unsupported keys: {extra}")
    if value.get("schema_version") != ACTION_GATE_SCHEMA_VERSION:
        errors.append(f"{label} schema_version is invalid")
    if value.get("status") != "prepared_not_observed":
        errors.append(f"{label} status is invalid")
    if value.get("outcome") not in {"allow", "deny"}:
        errors.append(f"{label} outcome is invalid")
    for key in ("dispatchable", "choice_required"):
        if not isinstance(value.get(key), bool):
            errors.append(f"{label} {key} must be boolean")
    if "not dispatch" not in str(value.get("claim_boundary", "")).lower():
        errors.append(f"{label} claim_boundary must preserve the dispatch boundary")
    errors.extend(
        validate_task_authority_envelope(
            value.get("authority_envelope"),
            f"{label} authority_envelope",
            parent_dispatchable=value.get("dispatchable"),
        )
    )
    # Optional on purpose: a verdict recorded before these blocks existed is
    # still a valid verdict, and the record validators re-read stored gates.
    action_risk = value.get("action_risk")
    if action_risk is not None:
        errors.extend(validate_action_risk(action_risk, f"{label} action_risk"))
        errors.extend(_verdict_risk_consistency_errors(value, action_risk, label))
    if value.get("account_authorization") is not None:
        errors.extend(
            validate_account_authorization(value.get("account_authorization"), f"{label} account_authorization")
        )
    confirmation = value.get("confirmation")
    if not isinstance(confirmation, dict) or set(confirmation) != set(CONFIRMATION_KEYS):
        errors.append(f"{label} confirmation keys are invalid")
    else:
        armed = confirmation.get("armed_ladders")
        suppressed = confirmation.get("suppressed_ladders")
        if not isinstance(armed, list) or len(armed) > 1 or not set(armed) <= set(CONFIRMATION_LADDERS):
            errors.append(f"{label} confirmation must arm at most one ladder")
            armed = []
        if confirmation.get("required") is not bool(armed):
            errors.append(f"{label} confirmation.required must match the armed ladder")
        if not isinstance(suppressed, list) or len(armed) + len(suppressed) != len(CONFIRMATION_LADDERS):
            errors.append(f"{label} confirmation must account for every candidate ladder")
        if confirmation.get("action_id") != (LADDER_ACTION_IDS.get(armed[0], "") if armed else ""):
            errors.append(f"{label} confirmation.action_id must match the armed ladder")
    denial = value.get("denial")
    if value.get("outcome") == "deny":
        if not isinstance(denial, dict) or set(denial) != set(DENIAL_KEYS):
            errors.append(f"{label} denial keys are invalid")
        else:
            for key in ("rule_id", "field", "correction"):
                if not str(denial.get(key, "")).strip():
                    errors.append(f"{label} denial.{key} is required")
            errors.extend(_string_list_errors(denial.get("reason_codes"), f"{label} denial.reason_codes"))
        if value.get("dispatchable") is not False or value.get("choice_required") is not False:
            errors.append(f"{label} a denied verdict must not stay dispatchable or ask for a choice")
    elif denial is not None:
        errors.append(f"{label} denial is only allowed on a denied verdict")
    return errors
