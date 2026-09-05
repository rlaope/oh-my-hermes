"""Deterministic, fail-closed safety preflight for prepared coding work.

A deliberate sibling of `skill_governance.py`, built in its idiom: ordered
precedence levels, a closed reason-code vocabulary, and a content digest that
pins the decision. The direction is inverted. `skill_governance` resolves what
a policy SELECTS, so a later level overrides an earlier one. Safety preflight
resolves what a request is PERMITTED to prepare, so no level may widen what
`builtin_omh` denies -- a level can only add denials.

Naming, on purpose: there is no "guard" anywhere in this module. `routing/
policy.py` owns ~60 `*_guard_applies` helpers and every one of them keys off
words in a user message. A safety rule wired into that vocabulary would make a
safety decision depend on user text. Rules, preflight, and verdicts live here;
guards stay in routing.

Pre-expansion by construction. Every input is a bounded metadata field that
exists BEFORE a prompt template is expanded. `coding_delegation`'s
`message_context_mode="full"` path can interpolate the raw user message
verbatim into the prompt; a check that inspected the emitted `*_preview` fields
would be blind exactly there. So the mode and the raw-content admission flag
are inputs, and the raw text never is -- a request carrying message bodies,
code, or credentials is denied before any rule reads it.

Each rule reads one field class, not every string. `FIELD_CLASSES` says which
class each request field belongs to, and the classes are what make the rules
mean anything: an opaque metadata ref is free-form caller text, so
credential-shape detection belongs there; a target path is a source location
the user named, so `token_store.py` is a filename and not a credential; a
closed vocabulary already denies every value outside it. Only the body-shape
bound is universal, because a body is a body in any field.

The data boundary (issue #801) lives here rather than in a module of its own.
`REQUEST_FIELDS` already carried the owner, the approved scope, the target
paths, the remote targets, the persisted content refs, and the raw-content
admission -- most of "which roots, which intent, which destinations, which
prohibited content" was already a pre-expansion field on this request. A
parallel data-boundary evaluator would have given the tree two answers to "what
may this work touch" and only one of them would sit inside
`safety_profile_revision`, so the boundary is expressed as four more closed
fields and four more rules on the evaluator that already pins itself.

No model, no network, no new dependency: the whole evaluator is stdlib
`hashlib` plus `re` over caller-supplied metadata, plus the prohibited-content
detectors this tree already owns. `data_boundary_enforcement_facts()` is the
one host-dependent surface, it is not part of the profile, and no rule reads
it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import os
import re
import sys
from typing import Final

from ..coding.project_governance import ORG_SAFETY_RULE_SOURCE_REASON_CODES
from ..system.metadata_safety import (
    is_body_shaped_metadata_text,
    is_sensitive_metadata_text,
    require_opaque_metadata_ref,
)
from ..workflows.domain_intelligence_admission import ensure_safe_opaque_ref_content

SAFETY_PROFILE_SCHEMA_VERSION: Final = "omh_safety_profile/v1"
SAFETY_PREFLIGHT_VERDICT_SCHEMA_VERSION: Final = "omh_safety_preflight_verdict/v1"
SAFETY_PREFLIGHT_RECHECK_SCHEMA_VERSION: Final = "omh_safety_preflight_recheck/v1"
DATA_BOUNDARY_ENFORCEMENT_SCHEMA_VERSION: Final = "omh_data_boundary_enforcement/v1"

SAFETY_PREFLIGHT_CLAIM_BOUNDARY: Final = (
    "Passing safety preflight is permission to prepare this work; it is not compliance, "
    "execution, review, CI, or merge evidence."
)

# Strongest first. `builtin_omh` is the floor and the only level that can
# allow; `org` (issue #802) is opt-in and deny-only; `native_hermes` is a
# recommendation surface that never decides, exactly as in `skill_governance`.
SAFETY_PREFLIGHT_PRECEDENCE: Final = ("builtin_omh", "org", "native_hermes")

MAX_FIELD_CHARS: Final = 200
MAX_PATH_CHARS: Final = 240
MAX_TARGET_PATHS: Final = 32
MAX_REMOTE_TARGETS: Final = 8
MAX_PERSISTED_CONTENT_REFS: Final = 8
MAX_EVIDENCE_CLAIMS: Final = 8
MAX_OBSERVED_RECORD_REFS: Final = 8
MAX_WORKSPACE_ROOTS: Final = 8
MAX_APPROVED_DESTINATIONS: Final = 8
MAX_DATA_CLASSES: Final = 8

MESSAGE_CONTEXT_MODES: Final = ("bounded", "full")
REMOTE_TARGET_KINDS: Final = ("git_remote", "issue_tracker", "package_registry", "public_internet")

# Read, write, and share, the three intents issue #801 names. Kept to three on
# purpose: an intent nothing can distinguish is a label, not a boundary.
ACCESS_INTENTS: Final = ("read", "write", "share")
MAX_ACCESS_INTENTS: Final = len(ACCESS_INTENTS)

# The data classes a prepared coding handoff can actually name today, split by
# whether the class may cross the handoff boundary at all.
#
# Each permitted class is something this lane really produces: the workspace
# files the request names, the bounded references and digests a prepared
# artifact stores instead of content, and -- only under the full message
# context mode -- the user's own request text.
#
# Each prohibited class is something the tree already has a detector for, so
# the vocabulary is a name for an existing refusal rather than a new taxonomy:
# `metadata_safety.is_sensitive_metadata_text` for credential material, and
# `domain_intelligence_admission.ensure_safe_opaque_ref_content` for the
# personal-data (SSN, email) and transcript (role marker, sensitive
# assignment, bidi/control unicode) shapes. Nothing here invents a regex.
PERMITTED_DATA_CLASSES: Final = ("workspace_source", "workspace_metadata", "user_request_text")
PROHIBITED_DATA_CLASSES: Final = ("credential_material", "personal_data", "conversation_transcript")
DATA_CLASSES: Final = (*PERMITTED_DATA_CLASSES, *PROHIBITED_DATA_CLASSES)

EVIDENCE_CLAIMS: Final = (
    "prepared_not_observed",
    "dispatch_observed",
    "result_observed",
    "review_observed",
    "ci_observed",
    "merge_observed",
)
_OBSERVED_EVIDENCE_CLAIMS: Final = frozenset(EVIDENCE_CLAIMS) - {"prepared_not_observed"}

# The closed request shape. A key outside this set is a denial, which is what
# keeps code bodies, credentials, and raw prompts from ever reaching a rule.
REQUEST_FIELDS: Final = (
    "owner",
    "approved_scope",
    "message_context_mode",
    "raw_content_included",
    "data_classes",
    "workspace_roots",
    "target_paths",
    "remote_targets",
    "approved_destinations",
    "access_intents",
    "persisted_content_refs",
    "evidence_claims",
    "observed_record_refs",
)

# The boundary half of the request against the claim half. `workspace_roots`
# and `approved_destinations` are what the approval covers; `target_paths`,
# `remote_targets`, and `access_intents` are what the prepared action says it
# will do. Every #801 rule is one comparison between the two halves, which is
# why they are fields on this request and not a second artifact.
BOUNDARY_FIELDS: Final = ("workspace_roots", "approved_destinations", "data_classes")
CLAIM_FIELDS: Final = ("target_paths", "remote_targets", "access_intents")

# The field classes. `opaque_ref` is free-form caller text carrying an
# identifier, `path` is a source location the caller named, `vocabulary` is a
# closed value set whose own rule denies every non-member. Every request field
# has exactly one class, and an unclassified string is read as `opaque_ref`,
# the strictest of the three.
FIELD_CLASS_OPAQUE_REF: Final = "opaque_ref"
FIELD_CLASS_PATH: Final = "path"
FIELD_CLASS_VOCABULARY: Final = "vocabulary"

FIELD_CLASSES: Final = {
    "owner": FIELD_CLASS_OPAQUE_REF,
    "approved_scope": FIELD_CLASS_OPAQUE_REF,
    "message_context_mode": FIELD_CLASS_VOCABULARY,
    "raw_content_included": FIELD_CLASS_OPAQUE_REF,
    # A declared data class and a declared access intent are closed value sets
    # whose own rules deny every non-member, exactly like `evidence_claims`.
    # Classing them as opaque refs would run credential shape over the literal
    # word `credential_material` and deny the request that correctly declares
    # what it must not carry.
    "data_classes": FIELD_CLASS_VOCABULARY,
    "access_intents": FIELD_CLASS_VOCABULARY,
    # A workspace root is a source location the caller named, same as a target
    # path: it takes the longer path bound and is exempt from credential shape,
    # because `src/auth/` is a directory and not a secret.
    "workspace_roots": FIELD_CLASS_PATH,
    "target_paths": FIELD_CLASS_PATH,
    # Both destination lists are objects whose nested keys carry their own
    # classes; the field-level class covers any other string in them.
    "remote_targets": FIELD_CLASS_OPAQUE_REF,
    "approved_destinations": FIELD_CLASS_OPAQUE_REF,
    "persisted_content_refs": FIELD_CLASS_OPAQUE_REF,
    "evidence_claims": FIELD_CLASS_VOCABULARY,
    "observed_record_refs": FIELD_CLASS_OPAQUE_REF,
}
# Destination entries are objects: the kind is a closed vocabulary, the ref is
# an opaque metadata ref. Any other key inherits the field's own class. The two
# destination fields share one shape so a declared destination and a claimed
# one are compared like against like.
DESTINATION_FIELDS: Final = ("remote_targets", "approved_destinations")
DESTINATION_FIELD_CLASSES: Final = {
    "kind": FIELD_CLASS_VOCABULARY,
    "ref": FIELD_CLASS_OPAQUE_REF,
}

# Credential shape is read on caller-supplied identifiers only. A path is a
# file the caller named, and a closed vocabulary denies non-members by
# membership, so reading either as a possible credential denies ordinary work
# without adding any protection.
SECRET_SHAPE_FIELD_CLASSES: Final = (FIELD_CLASS_OPAQUE_REF,)
# The wider prohibited-content scan reads the same class, and for the same
# reason. SSN and email shapes over a user-named path would deny
# `src/api/credentials_loader.py`-class work all over again; over a closed
# vocabulary they can never fire. Only free-form caller text can carry them.
PROHIBITED_CONTENT_FIELD_CLASSES: Final = (FIELD_CLASS_OPAQUE_REF,)

RULE_INPUT_METADATA_BOUNDED: Final = "input_metadata_bounded"
RULE_OWNER_DECLARED: Final = "owner_declared"
RULE_APPROVED_SCOPE_DECLARED: Final = "approved_scope_declared"
RULE_RAW_CONTEXT_DECLARED: Final = "raw_context_declared"
RULE_TARGET_PATHS_BOUNDED: Final = "target_paths_bounded"
RULE_SECRETS_ABSENT: Final = "secrets_absent"
RULE_REMOTE_TARGETS_DECLARED: Final = "remote_targets_declared"
RULE_PERSISTED_CONTENT_REFERENCED: Final = "persisted_content_referenced"
RULE_EVIDENCE_CLAIM_BOUNDED: Final = "evidence_claim_bounded"
RULE_ORG_RULE_SOURCE: Final = "org_rule_source"
RULE_DATA_CLASSES_PERMITTED: Final = "data_classes_permitted"
RULE_WORKSPACE_ROOTS_DECLARED: Final = "workspace_roots_declared"
RULE_DESTINATIONS_APPROVED: Final = "destinations_approved"
RULE_ACCESS_INTENT_DECLARED: Final = "access_intent_declared"

# (rule id, axis, level, reason codes). Rule ids are stable strings and the
# order is the denial precedence: the first rule that denies is the
# responsible rule, so the same input always names the same rule.
_RULES: Final = (
    (
        RULE_INPUT_METADATA_BOUNDED,
        "input",
        "builtin_omh",
        ("request_not_an_object", "unknown_request_field", "body_shaped_request_value"),
    ),
    (RULE_SECRETS_ABSENT, "secrets", "builtin_omh", ("secret_shaped_value",)),
    (
        RULE_DATA_CLASSES_PERMITTED,
        "data_classes",
        "builtin_omh",
        (
            "data_class_not_bounded",
            "data_class_count_exceeded",
            "data_class_unknown",
            "data_class_prohibited",
            "prohibited_data_class_content",
        ),
    ),
    (RULE_OWNER_DECLARED, "owner", "builtin_omh", ("owner_missing", "owner_not_opaque_ref")),
    (
        RULE_APPROVED_SCOPE_DECLARED,
        "approved_scope",
        "builtin_omh",
        ("approved_scope_missing", "approved_scope_not_opaque_ref"),
    ),
    (
        RULE_RAW_CONTEXT_DECLARED,
        "raw_context",
        "builtin_omh",
        ("raw_context_mode_unknown", "raw_context_undeclared"),
    ),
    (
        RULE_WORKSPACE_ROOTS_DECLARED,
        "workspace_roots",
        "builtin_omh",
        (
            "workspace_root_not_bounded",
            "workspace_root_count_exceeded",
            "workspace_root_absolute",
            "workspace_root_escapes_project",
        ),
    ),
    (
        RULE_TARGET_PATHS_BOUNDED,
        "paths",
        "builtin_omh",
        (
            "target_path_not_bounded",
            "target_path_count_exceeded",
            "target_path_absolute",
            "target_path_escapes_project",
            # #801 extends this rule rather than adding a second path rule: an
            # out-of-workspace path is one more way a target leaves the
            # approved boundary, and one rule id keeps the answer single.
            "target_path_outside_workspace_roots",
        ),
    ),
    (
        RULE_REMOTE_TARGETS_DECLARED,
        "remote_targets",
        "builtin_omh",
        (
            "remote_target_not_bounded",
            "remote_target_count_exceeded",
            "remote_target_kind_unknown",
            "remote_target_ref_missing",
        ),
    ),
    (
        RULE_DESTINATIONS_APPROVED,
        "destinations",
        "builtin_omh",
        (
            "approved_destination_not_bounded",
            "approved_destination_count_exceeded",
            "approved_destination_kind_unknown",
            "approved_destination_ref_missing",
            "destination_not_declared",
        ),
    ),
    (
        RULE_ACCESS_INTENT_DECLARED,
        "access_intent",
        "builtin_omh",
        (
            "access_intent_not_bounded",
            "access_intent_count_exceeded",
            "access_intent_unknown",
            "access_intent_undeclared",
            "access_intent_unapproved",
        ),
    ),
    (
        RULE_PERSISTED_CONTENT_REFERENCED,
        "persisted_content",
        "builtin_omh",
        ("persisted_content_count_exceeded", "persisted_content_inline"),
    ),
    (
        RULE_EVIDENCE_CLAIM_BOUNDED,
        "evidence_claims",
        "builtin_omh",
        (
            "evidence_claim_count_exceeded",
            "evidence_claim_unknown",
            "evidence_claim_unobserved",
            "observed_record_ref_invalid",
        ),
    ),
    (
        RULE_ORG_RULE_SOURCE,
        "org_rules",
        "org",
        (
            *(code for code in ORG_SAFETY_RULE_SOURCE_REASON_CODES if code != "org_source_available"),
            "org_rule_unknown_value",
            "org_rule_denied",
            "org_widening_ignored",
        ),
    ),
)

# One correction per reason code: what the caller must change to be allowed.
_CORRECTIONS: Final = {
    "request_not_an_object": "Pass a safety preflight request object with the declared metadata fields.",
    "unknown_request_field": f"Remove the field; only {', '.join(REQUEST_FIELDS)} may be evaluated.",
    "body_shaped_request_value": f"Replace the body with a single bounded reference of at most {MAX_FIELD_CHARS} characters.",
    "secret_shaped_value": "Remove the credential-shaped value and pass an opaque reference instead.",
    "owner_missing": "Name the responsible owner in the owner field.",
    "owner_not_opaque_ref": "Use a short opaque owner reference without spaces, bodies, or credentials.",
    "approved_scope_missing": "Declare the approved scope this work is permitted to touch.",
    "approved_scope_not_opaque_ref": "Use a short opaque approved-scope reference.",
    "raw_context_mode_unknown": f"Set message_context_mode to one of {', '.join(MESSAGE_CONTEXT_MODES)}.",
    "raw_context_undeclared": "Declare raw_content_included as a boolean, and declare it true only under the full message context mode.",
    "data_class_not_bounded": "Pass data_classes as a list of declared data class names.",
    "data_class_count_exceeded": f"Reduce data_classes to at most {MAX_DATA_CLASSES} entries.",
    "data_class_unknown": f"Declare a data class from {', '.join(DATA_CLASSES)}.",
    "data_class_prohibited": f"Remove the prohibited data class; {', '.join(PROHIBITED_DATA_CLASSES)} may not cross a prepared handoff.",
    "prohibited_data_class_content": "Remove the prohibited-class content from the metadata value and pass an opaque reference instead.",
    "workspace_root_not_bounded": f"Pass workspace roots as bounded strings of at most {MAX_PATH_CHARS} characters.",
    "workspace_root_count_exceeded": f"Reduce workspace_roots to at most {MAX_WORKSPACE_ROOTS} entries.",
    "workspace_root_absolute": "Use a project-relative workspace root instead of an absolute or home-anchored path.",
    "workspace_root_escapes_project": "Remove the parent-directory segment so the workspace root stays inside the project.",
    "target_path_not_bounded": f"Pass target paths as bounded strings of at most {MAX_PATH_CHARS} characters.",
    "target_path_count_exceeded": f"Reduce target_paths to at most {MAX_TARGET_PATHS} entries.",
    "target_path_absolute": "Use a project-relative target path instead of an absolute or home-anchored path.",
    "target_path_escapes_project": "Remove the parent-directory segment so the path stays inside the project.",
    "target_path_outside_workspace_roots": "Move the target inside a declared workspace root, or widen workspace_roots and get that approved.",
    "approved_destination_not_bounded": "Pass each approved destination as an object with exactly a kind and a ref.",
    "approved_destination_count_exceeded": f"Reduce approved_destinations to at most {MAX_APPROVED_DESTINATIONS} entries.",
    "approved_destination_kind_unknown": f"Declare an approved destination kind from {', '.join(REMOTE_TARGET_KINDS)}.",
    "approved_destination_ref_missing": "Give the approved destination a short opaque reference.",
    "destination_not_declared": "Declare this destination in approved_destinations before the work may reach it.",
    "access_intent_not_bounded": "Pass access_intents as a list of declared access intent names.",
    "access_intent_count_exceeded": f"Reduce access_intents to at most {MAX_ACCESS_INTENTS} entries.",
    "access_intent_unknown": f"Declare an access intent from {', '.join(ACCESS_INTENTS)}.",
    "access_intent_undeclared": "Declare the share intent before naming a remote target, or drop the remote target.",
    "access_intent_unapproved": "Declare the approved destination the share intent covers, or drop the share intent.",
    "remote_target_not_bounded": "Pass each remote target as an object with exactly a kind and a ref.",
    "remote_target_count_exceeded": f"Reduce remote_targets to at most {MAX_REMOTE_TARGETS} entries.",
    "remote_target_kind_unknown": f"Declare a remote target kind from {', '.join(REMOTE_TARGET_KINDS)}.",
    "remote_target_ref_missing": "Give the remote target a short opaque reference.",
    "persisted_content_count_exceeded": f"Reduce persisted_content_refs to at most {MAX_PERSISTED_CONTENT_REFS} entries.",
    "persisted_content_inline": "Persist the content separately and pass its opaque reference, not the content.",
    "evidence_claim_count_exceeded": f"Reduce evidence_claims to at most {MAX_EVIDENCE_CLAIMS} entries.",
    "evidence_claim_unknown": f"Use an evidence claim from {', '.join(EVIDENCE_CLAIMS)}.",
    "evidence_claim_unobserved": "Attach the observed record reference that backs the claim, or claim prepared_not_observed.",
    "observed_record_ref_invalid": f"Pass at most {MAX_OBSERVED_RECORD_REFS} short opaque observed record references.",
    "org_source_missing": "Create the configured org rule source file or turn the org rule source off.",
    "org_source_unsafe": "Point the org rule source at a regular file that is not a symlink.",
    "org_source_unreadable": "Grant read access to the configured org rule source file.",
    "org_source_oversized": "Shrink the org rule source below the configured byte bound.",
    "org_source_timed_out": "Serve the org rule source from local storage that reads within the time bound.",
    "org_source_malformed": "Fix the org rule source so it parses as the bounded rule document.",
    "org_source_unknown_version": "Set the org rule source schema_version to the supported version.",
    "org_source_unknown_fields": "Remove the unsupported field from the org rule source.",
    "org_source_unsafe_metadata": "Remove the credential-shaped or body-shaped value from the org rule source.",
    # The local attestation refusals (issue #805). Each names the operator
    # action for one distinct failure, because "the tag did not verify" is not
    # one problem: no tag was written, the bytes no longer match the tag, or the
    # key itself could not be read.
    "org_source_attestation_missing": "Write the local attestation tag beside the org rule source, or clear the configured attestation key.",
    "org_source_attestation_invalid": "Re-attest the org rule source with the local key, or restore the bytes the existing tag covers.",
    "org_source_attestation_key_unreadable": "Grant read access to the configured local attestation key, or clear it.",
    "org_rule_unknown_value": "Use an org rule value this profile revision understands, or the rule cannot be honoured.",
    "org_rule_denied": "The org rule source narrows this profile; change the request or the org rule source.",
    "org_widening_ignored": "No change is required; a wider org value was discarded because the org level can only narrow.",
    "allowed": "",
}


def correction_reason_codes() -> tuple[str, ...]:
    """Every reason code a verdict can carry, `allowed` included.

    The read-only accessor a durable decision record joins on. `_CORRECTIONS`
    stays private because it is a rendering table and not a contract, but the
    *code set* becomes a contract the moment a record on disk cites one: a code
    that no longer exists must be reportable as unexplainable rather than
    silently rendered as a blank line.

    `allowed` is a member because `_verdict` emits it on every pass, and a
    decision history that records allows has to be able to cite the code its
    own verdict carried. Its correction is empty for the obvious reason -- there
    is nothing to correct -- which is why explainability is measured over
    blocked entries and not over every entry.
    """
    return tuple(sorted(_CORRECTIONS))


def correction_for_reason_code(reason_code: str) -> str:
    """The constant correction line for one reason code, or empty.

    Constant, never interpolated: a correction is rendered to operators, and a
    line built from request values would be one more path for caller-controlled
    text to reach a terminal.
    """
    return str(_CORRECTIONS.get(str(reason_code or ""), ""))


# How a data-boundary limit can be enforced at all.
#
# `refused_before_handoff` is omh refusing to prepare the artifact, so it holds
# on every host and needs nothing from the executor. `host_confinement` is an
# OS-level confinement the host either can or cannot provide. `advisory` is a
# declaration the executor is trusted to honour and nothing checks. The three
# are deliberately not interchangeable: only the middle one is host-dependent,
# and that is the distinction issue #801 asks OMH to surface.
DATA_BOUNDARY_ENFORCEMENT_KINDS: Final = ("refused_before_handoff", "host_confinement", "advisory")

# Why each unenforced kind is unenforced. Reason strings rather than issue
# numbers, on the `action_gate.ACCOUNT_AUTHORIZATION_BLOCKER` precedent: a
# blocker names a ticket only when landing that ticket would close it.
#
# Both of these used to name `#820`, which was a mis-citation even before that
# issue landed. #820 is about two handoffs sharing one workspace, and it shipped
# `workspace_binding_guard/v1` for exactly that -- a pre-dispatch reservation.
# The fanout lane now places its owner and dispatcher verification processes
# under the existing sandbox. A process-neutral handoff record still cannot
# claim that a particular run was confined: only its same-run probe receipt can
# do that. Network is deliberately separate because the fanout owner retains
# its existing network behavior.
_FANOUT_FILESYSTEM_CONFINEMENT_BLOCKER: Final = "no_observed_fanout_filesystem_confinement_probe_receipt"
_RUNTIME_NETWORK_CONFINEMENT_BLOCKER: Final = "fanout_lane_does_not_request_network_confinement"
# The advisory limit is not fileable at all. Measuring whether a running
# executor stayed inside its declared targets needs the same OS-level
# confinement the host owns; on this side of the wall there is nothing to
# observe, on any host.
_ADVISORY_LIMIT_BLOCKER: Final = "no_omh_side_measurement_observes_whether_an_executor_honoured_its_targets"

# (limit id, enforcement kind, enforcer symbols, blocker).
#
# The symbols are dotted import paths in `omh.coding.action_gate`'s
# `enforced_by` format, so a boundary table can consume them directly instead
# of restating them. A limit is only ever reported as enforced on a host where
# something really refuses; see `data_boundary_enforcement_facts`.
DATA_BOUNDARY_LIMITS: Final = (
    (
        "workspace_root_claim",
        "refused_before_handoff",
        (
            "omh.quality.safety_preflight.RULE_TARGET_PATHS_BOUNDED",
            "omh.quality.safety_preflight.evaluate_safety_preflight",
        ),
        "",
    ),
    (
        "prohibited_data_class",
        "refused_before_handoff",
        (
            "omh.quality.safety_preflight.RULE_DATA_CLASSES_PERMITTED",
            "omh.system.metadata_safety.is_sensitive_metadata_text",
            "omh.workflows.domain_intelligence_admission.ensure_safe_opaque_ref_content",
        ),
        "",
    ),
    (
        "declared_destination",
        "refused_before_handoff",
        (
            "omh.quality.safety_preflight.RULE_DESTINATIONS_APPROVED",
            "omh.quality.safety_preflight.RULE_ACCESS_INTENT_DECLARED",
        ),
        "",
    ),
    (
        "runtime_filesystem_confinement",
        "host_confinement",
        (
            "omh.quality.cross_harness_adapter_sandbox.sandbox_command",
            "omh.quality.cross_harness_adapter_sandbox.read_roots_are_safe",
            "omh.coding.fanout_confinement.prepare_fanout_filesystem_confinement",
        ),
        _FANOUT_FILESYSTEM_CONFINEMENT_BLOCKER,
    ),
    (
        "runtime_network_confinement",
        "host_confinement",
        ("omh.quality.cross_harness_adapter_sandbox.sandbox_command",),
        _RUNTIME_NETWORK_CONFINEMENT_BLOCKER,
    ),
    (
        "executor_honours_declared_targets",
        "advisory",
        (),
        _ADVISORY_LIMIT_BLOCKER,
    ),
)
DATA_BOUNDARY_LIMIT_NAMES: Final = tuple(entry[0] for entry in DATA_BOUNDARY_LIMITS)

# The confinement tool each platform would use, and the reason a platform with
# neither can never enforce a runtime limit no matter what else lands.
_MACOS_CONFINEMENT_TOOL: Final = "/usr/bin/sandbox-exec"
_NO_HOST_BACKEND_REASON: Final = "no_os_confinement_backend_on_this_platform"


def safety_rule_profile() -> dict[str, object]:
    """The full rule profile: the content the safety-profile revision pins."""
    return {
        "schema_version": SAFETY_PROFILE_SCHEMA_VERSION,
        "precedence": list(SAFETY_PREFLIGHT_PRECEDENCE),
        "rules": [
            {"id": rule_id, "axis": axis, "level": level, "reason_codes": list(codes)}
            for rule_id, axis, level, codes in _RULES
        ],
        "corrections": {code: _CORRECTIONS[code] for code in sorted(_CORRECTIONS)},
        "bounds": {
            "max_field_chars": MAX_FIELD_CHARS,
            "max_path_chars": MAX_PATH_CHARS,
            "max_target_paths": MAX_TARGET_PATHS,
            "max_remote_targets": MAX_REMOTE_TARGETS,
            "max_persisted_content_refs": MAX_PERSISTED_CONTENT_REFS,
            "max_evidence_claims": MAX_EVIDENCE_CLAIMS,
            "max_observed_record_refs": MAX_OBSERVED_RECORD_REFS,
            "max_workspace_roots": MAX_WORKSPACE_ROOTS,
            "max_approved_destinations": MAX_APPROVED_DESTINATIONS,
            "max_access_intents": MAX_ACCESS_INTENTS,
            "max_data_classes": MAX_DATA_CLASSES,
        },
        "vocabularies": {
            "request_fields": list(REQUEST_FIELDS),
            "message_context_modes": list(MESSAGE_CONTEXT_MODES),
            "remote_target_kinds": list(REMOTE_TARGET_KINDS),
            "evidence_claims": list(EVIDENCE_CLAIMS),
            "access_intents": list(ACCESS_INTENTS),
            "data_classes": list(DATA_CLASSES),
            "permitted_data_classes": list(PERMITTED_DATA_CLASSES),
            "prohibited_data_classes": list(PROHIBITED_DATA_CLASSES),
            "data_boundary_enforcement_kinds": list(DATA_BOUNDARY_ENFORCEMENT_KINDS),
        },
        # Pinned by the digest on purpose: which rule reads which field is part
        # of the profile a prepared artifact was cleared under, not an
        # implementation detail a later revision can change silently.
        "field_classes": dict(FIELD_CLASSES),
        "destination_fields": list(DESTINATION_FIELDS),
        "destination_field_classes": dict(DESTINATION_FIELD_CLASSES),
        "secret_shape_field_classes": list(SECRET_SHAPE_FIELD_CLASSES),
        "prohibited_content_field_classes": list(PROHIBITED_CONTENT_FIELD_CLASSES),
        "boundary_fields": list(BOUNDARY_FIELDS),
        "claim_fields": list(CLAIM_FIELDS),
        # Which limits exist and how each one *can* be enforced is profile
        # content. Whether a given host actually enforces one is not: a
        # host-dependent digest would read as drift on every second machine and
        # make `recheck_safety_preflight_revision` useless. The per-host answer
        # lives in `data_boundary_enforcement_facts()` and never reaches here.
        "data_boundary_limits": [
            {"limit": limit, "enforcement_kind": kind, "enforced_by": list(symbols), "blocked_by": blocker}
            for limit, kind, symbols, blocker in DATA_BOUNDARY_LIMITS
        ],
        "claim_boundary": SAFETY_PREFLIGHT_CLAIM_BOUNDARY,
    }


def safety_profile_digest(profile: Mapping[str, object]) -> str:
    """Content hash of a rule profile, used as the safety-profile revision."""
    # Stable recursive encoding rather than json.dumps, for the reason
    # `skill_governance.policy_decision_digest` records: this digest runs on
    # the prepared-artifact path and the efficiency contract forbids JSON
    # serialization there. Sorted keys keep it order-independent.
    return hashlib.sha256(_stable_encode(profile).encode("utf-8")).hexdigest()


def safety_profile_revision() -> str:
    """The revision a prepared artifact pins so drift is detectable later."""
    return safety_profile_digest(safety_rule_profile())


def evaluate_safety_preflight(
    request: Mapping[str, object] | None,
    *,
    org_rule_source: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return one verdict for a pre-expansion request.

    `request` is bounded metadata only (see `REQUEST_FIELDS`). `org_rule_source`
    is the result of `project_governance.read_org_safety_rule_source`, or None
    when the org level is not opted in. A denial names the responsible rule, the
    offending field, and the correction. Passing is permission to prepare, never
    evidence that anything ran.
    """
    revision = safety_profile_revision()
    levels = ["builtin_omh"]
    org_codes: list[str] = []
    org_denial: _Denial | None = None
    limits = _default_limits()
    if org_rule_source is not None:
        levels.append("org")
        org_denial, org_codes, limits = _org_level(org_rule_source)
    denial = _builtin_denial(request)
    if denial is None:
        denial = org_denial
    # Narrowing runs only when the org level participated, so a verdict can
    # never name a level that `levels_applied` does not list.
    if denial is None and org_rule_source is not None and isinstance(request, Mapping):
        denial = _org_narrowing_denial(request, limits)
        if denial is not None:
            org_codes = [*org_codes, denial[2]]
    return _verdict(denial, revision=revision, levels=levels, org_reason_codes=org_codes)


def recheck_safety_preflight_revision(carried: object) -> dict[str, object]:
    """Cheap drift check for a later boundary such as dispatch.

    Compares a carried revision -- either a verdict or the revision string --
    against the live profile without re-running any rule. `dispatchable` here
    means only that the revision still matches; the carried verdict's own
    `status` still has to be an allow.
    """
    live = safety_profile_revision()
    value = carried.get("safety_profile_revision") if isinstance(carried, Mapping) else carried
    text = value if isinstance(value, str) else ""
    if not text:
        status, reason_code = "missing", "revision_missing"
    elif text == live:
        status, reason_code = "current", "revision_current"
    else:
        status, reason_code = "drifted", "revision_drifted"
    return {
        "schema_version": SAFETY_PREFLIGHT_RECHECK_SCHEMA_VERSION,
        "status": status,
        "reason_code": reason_code,
        "carried_revision": text,
        "live_revision": live,
        "dispatchable": status == "current",
        "claim_boundary": SAFETY_PREFLIGHT_CLAIM_BOUNDARY,
    }


def data_boundary_enforcement_facts() -> dict[str, object]:
    """Which data-boundary limits *this host* can enforce, as facts not prose.

    Issue #801 asks OMH to label which limits the selected host can enforce.
    This is the fact surface that labelling reads: for every limit in
    `DATA_BOUNDARY_LIMITS` it reports whether the host is capable of enforcing
    it at all, whether anything refuses today, the enforcing symbols when
    something does, and the blocker when nothing does. `enforced_by` is empty
    exactly when `enforced_here` is false, and `blocked_by` is non-empty
    exactly then, which is the shape `action_gate`'s boundary validator already
    requires -- a caller cannot build a decorated entry out of this.

    Three genuine differences, and no others:

    * `refused_before_handoff` limits hold identically on every host, because
      the refusal is OMH declining to prepare the artifact. No executor and no
      OS feature is involved, so there is nothing for a host to lack.
    * `host_confinement` limits need an OS-level confinement backend. macOS has
      `sandbox-exec` in the base system; Linux needs a root-owned, non
      group/other-writable `bwrap` actually present on disk; every other
      platform has neither. That probe is real: the Linux half asks the same
      trust snapshot the sandbox lane spawns under, so a host that would be
      refused there is not reported as capable here.
    * `advisory` limits are enforced nowhere, on any host, and report the same
      blocker on every host: no host fact bears on them, so a missing
      confinement backend is not an explanation for one.

    Fanout now supplies filesystem confinement, but this process-neutral fact
    surface has no run receipt to inspect. Its filesystem row therefore remains
    declared until a particular dispatch records a successful same-run probe;
    the network row remains declared because fanout preserves network access.
    The capability flag separates a host that can produce such a receipt from
    one that cannot.

    Deliberately not part of `safety_rule_profile()`: the answer differs per
    machine, and a host-dependent digest would read as profile drift on every
    second host. No rule reads this, and no verdict changes because of it.
    """
    backend, capable, unavailable_reason = _host_confinement_backend()
    limits: list[dict[str, object]] = []
    for limit, kind, symbols, blocker in DATA_BOUNDARY_LIMITS:
        host_can_enforce = kind == "refused_before_handoff" or (kind == "host_confinement" and capable)
        enforced_here = kind == "refused_before_handoff"
        # A missing confinement backend explains a `host_confinement` limit and
        # nothing else. Substituting it wherever `host_can_enforce` was false
        # made the `advisory` row report an OS-confinement blocker for a limit
        # no OS feature could ever enforce, and turned a host-independent answer
        # into a host-dependent one.
        if enforced_here:
            blocked_by = ""
        elif kind == "host_confinement" and not capable:
            blocked_by = unavailable_reason or blocker
        else:
            blocked_by = blocker
        limits.append(
            {
                "limit": limit,
                "enforcement_kind": kind,
                "host_can_enforce": host_can_enforce,
                "enforced_here": enforced_here,
                "enforced_by": list(symbols) if enforced_here else [],
                "blocked_by": blocked_by,
            }
        )
    return {
        "schema_version": DATA_BOUNDARY_ENFORCEMENT_SCHEMA_VERSION,
        "host_confinement_backend": backend,
        "host_confinement_available": capable,
        "host_confinement_unavailable_reason": unavailable_reason,
        "limits": limits,
        "claim_boundary": SAFETY_PREFLIGHT_CLAIM_BOUNDARY,
    }


def _host_confinement_backend() -> tuple[str, bool, str]:
    """(backend name, usable here, reason it is not) -- probed, never assumed."""
    if sys.platform == "darwin":
        present = os.path.exists(_MACOS_CONFINEMENT_TOOL)
        return "sandbox-exec", present, "" if present else "sandbox_exec_absent"
    if sys.platform.startswith("linux"):
        present = _trusted_bwrap_present()
        return "bwrap", present, "" if present else "bwrap_absent_or_untrusted"
    return "unsupported", False, _NO_HOST_BACKEND_REASON


def _trusted_bwrap_present() -> bool:
    """The sandbox lane's own trust snapshot, or False when that lane is absent.

    Bound lazily and by relative import for the reason `coding_delegation`
    binds the evaluator lazily: an install without the cross-harness lane must
    still answer this question, and the honest answer there is "no confinement
    backend I can vouch for". Nothing here spawns a process.
    """
    try:
        from .cross_harness_adapter_backend import trusted_bwrap
    except ImportError:
        return False
    return trusted_bwrap() is not None


# (rule id, field, reason code, level)
_Denial = tuple[str, str, str, str]

_ABSOLUTE_PATH_RE: Final = re.compile(r"^(?:[/\\~]|[A-Za-z]:)")


def _default_limits() -> dict[str, object]:
    return {"max_target_paths": MAX_TARGET_PATHS, "denied_remote_target_kinds": ()}


def _verdict(
    denial: _Denial | None,
    *,
    revision: str,
    levels: list[str],
    org_reason_codes: list[str],
) -> dict[str, object]:
    rule_id, field, reason_code, level = denial if denial is not None else ("", "", "allowed", "")
    return {
        "schema_version": SAFETY_PREFLIGHT_VERDICT_SCHEMA_VERSION,
        "status": "allow" if denial is None else "deny",
        "rule_id": rule_id,
        "field": field,
        "reason_code": reason_code,
        "correction": _CORRECTIONS[reason_code],
        "level": level,
        "safety_profile_revision": revision,
        "profile_schema_version": SAFETY_PROFILE_SCHEMA_VERSION,
        "levels_applied": list(levels),
        "org_reason_codes": list(org_reason_codes),
        "claim_boundary": SAFETY_PREFLIGHT_CLAIM_BOUNDARY,
    }


def _builtin_denial(request: object) -> _Denial | None:
    if not isinstance(request, Mapping):
        return (RULE_INPUT_METADATA_BOUNDED, "request", "request_not_an_object", "builtin_omh")
    unknown = sorted(str(key) for key in request if key not in REQUEST_FIELDS)
    if unknown:
        return (RULE_INPUT_METADATA_BOUNDED, unknown[0], "unknown_request_field", "builtin_omh")
    admission = _admission_denial(request)
    if admission is not None:
        return admission
    for check in (
        _data_classes_denial,
        _owner_denial,
        _approved_scope_denial,
        _raw_context_denial,
        _workspace_roots_denial,
        _target_paths_denial,
        _remote_targets_denial,
        _destinations_denial,
        _access_intents_denial,
        _persisted_content_denial,
        _evidence_claims_denial,
    ):
        denial = check(request)
        if denial is not None:
            return denial
    return None


def _admission_denial(request: Mapping[str, object]) -> _Denial | None:
    """Refuse credentials and body-shaped values before any rule reads them.

    Credential shape is read on the opaque-ref class only. The body-shape bound
    is read on every string, with the path class carrying the longer bound. The
    prohibited-class scan is last of the three so the two older reason codes
    keep naming the same values they always did, and it reuses the detectors
    `domain_intelligence_admission` already owns rather than adding a pattern:
    an SSN, an email address, a role marker, a `password=`-shaped assignment,
    or a bidi/control character in an opaque ref is prohibited-class content
    riding in as metadata.
    """
    for field, text, field_class in _bounded_strings(request):
        if field_class in SECRET_SHAPE_FIELD_CLASSES and is_sensitive_metadata_text(text):
            return (RULE_SECRETS_ABSENT, field, "secret_shaped_value", "builtin_omh")
        limit = MAX_PATH_CHARS if field_class == FIELD_CLASS_PATH else MAX_FIELD_CHARS
        if is_body_shaped_metadata_text(text, limit=limit):
            return (RULE_INPUT_METADATA_BOUNDED, field, "body_shaped_request_value", "builtin_omh")
        if field_class in PROHIBITED_CONTENT_FIELD_CLASSES and _carries_prohibited_class_content(text):
            return (RULE_DATA_CLASSES_PERMITTED, field, "prohibited_data_class_content", "builtin_omh")
    return None


def _carries_prohibited_class_content(text: str) -> bool:
    try:
        ensure_safe_opaque_ref_content(text, "request_field")
    except ValueError:
        return True
    return False


def _bounded_strings(request: Mapping[str, object]) -> list[tuple[str, str, str]]:
    """Every string in the request, paired with the field class it belongs to."""
    found: list[tuple[str, str, str]] = []
    for field in REQUEST_FIELDS:
        field_class = FIELD_CLASSES.get(field, FIELD_CLASS_OPAQUE_REF)
        value = request.get(field)
        if isinstance(value, str):
            found.append((field, value, field_class))
        elif _is_sequence(value):
            for index, item in enumerate(value):
                if isinstance(item, str):
                    found.append((f"{field}[{index}]", item, field_class))
                elif isinstance(item, Mapping):
                    found.extend(
                        (
                            f"{field}[{index}].{key}",
                            entry,
                            DESTINATION_FIELD_CLASSES.get(str(key), field_class)
                            if field in DESTINATION_FIELDS
                            else field_class,
                        )
                        for key, entry in sorted(item.items())
                        if isinstance(entry, str)
                    )
    return found


def _owner_denial(request: Mapping[str, object]) -> _Denial | None:
    owner = request.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        return (RULE_OWNER_DECLARED, "owner", "owner_missing", "builtin_omh")
    if not _is_opaque_ref(owner, field="owner"):
        return (RULE_OWNER_DECLARED, "owner", "owner_not_opaque_ref", "builtin_omh")
    return None


def _approved_scope_denial(request: Mapping[str, object]) -> _Denial | None:
    scope = request.get("approved_scope")
    if not isinstance(scope, str) or not scope.strip():
        return (RULE_APPROVED_SCOPE_DECLARED, "approved_scope", "approved_scope_missing", "builtin_omh")
    if not _is_opaque_ref(scope, field="approved_scope"):
        return (RULE_APPROVED_SCOPE_DECLARED, "approved_scope", "approved_scope_not_opaque_ref", "builtin_omh")
    return None


def _raw_context_denial(request: Mapping[str, object]) -> _Denial | None:
    """The pre-expansion admission decision, not the post-expansion preview.

    `coding_delegation` decides verbatim interpolation here, before the prompt
    exists, so this is the only place a rule can see it.

    The check is one-directional, because `raw_content_included` is what the
    caller will actually do with the raw message rather than a restatement of
    the mode. `full` is a ceiling: a caller may prepare a narrower artifact than
    the mode permits, and the coding lane does exactly that whenever the
    prepared payload carries no verbatim message. Requiring equality would deny
    that ordinary case while proving nothing, since a value re-derived from the
    mode can never disagree with it. Declaring verbatim raw content under a
    bounded mode is the real contradiction, and it denies.
    """
    mode = request.get("message_context_mode")
    if mode not in MESSAGE_CONTEXT_MODES:
        return (RULE_RAW_CONTEXT_DECLARED, "message_context_mode", "raw_context_mode_unknown", "builtin_omh")
    included = request.get("raw_content_included")
    if not isinstance(included, bool) or (included and mode != "full"):
        return (RULE_RAW_CONTEXT_DECLARED, "raw_content_included", "raw_context_undeclared", "builtin_omh")
    return None


def _data_classes_denial(request: Mapping[str, object]) -> _Denial | None:
    """The declared half of the #801 prohibited-content rule.

    A request states which data classes the work will touch. Naming a
    prohibited class is refused here, before a handoff exists; carrying the
    content of one is refused in the admission pass above. The two halves share
    a rule id because they are one boundary: what may cross a prepared handoff.
    """
    classes = request.get("data_classes", ())
    if not _is_str_sequence(classes):
        return (RULE_DATA_CLASSES_PERMITTED, "data_classes", "data_class_not_bounded", "builtin_omh")
    if len(classes) > MAX_DATA_CLASSES:
        return (RULE_DATA_CLASSES_PERMITTED, "data_classes", "data_class_count_exceeded", "builtin_omh")
    for index, item in enumerate(classes):
        field = f"data_classes[{index}]"
        if item not in DATA_CLASSES:
            return (RULE_DATA_CLASSES_PERMITTED, field, "data_class_unknown", "builtin_omh")
        if item in PROHIBITED_DATA_CLASSES:
            return (RULE_DATA_CLASSES_PERMITTED, field, "data_class_prohibited", "builtin_omh")
    return None


def _workspace_roots_denial(request: Mapping[str, object]) -> _Denial | None:
    """The declared boundary must itself be inside the project before it bounds anything."""
    roots = request.get("workspace_roots", ())
    if not _is_str_sequence(roots):
        return (RULE_WORKSPACE_ROOTS_DECLARED, "workspace_roots", "workspace_root_not_bounded", "builtin_omh")
    if len(roots) > MAX_WORKSPACE_ROOTS:
        return (RULE_WORKSPACE_ROOTS_DECLARED, "workspace_roots", "workspace_root_count_exceeded", "builtin_omh")
    for index, item in enumerate(roots):
        field = f"workspace_roots[{index}]"
        if not item.strip():
            return (RULE_WORKSPACE_ROOTS_DECLARED, field, "workspace_root_not_bounded", "builtin_omh")
        if _ABSOLUTE_PATH_RE.match(item):
            return (RULE_WORKSPACE_ROOTS_DECLARED, field, "workspace_root_absolute", "builtin_omh")
        if ".." in _path_parts(item):
            return (RULE_WORKSPACE_ROOTS_DECLARED, field, "workspace_root_escapes_project", "builtin_omh")
    return None


def _target_paths_denial(request: Mapping[str, object]) -> _Denial | None:
    """Every target is bounded, project-relative, contained -- and inside the approved roots.

    The containment check runs last so an absolute or escaping path keeps
    naming the reason code it always named; only a path that is already
    project-relative can be outside a declared root. Declaring no root leaves
    the project itself as the boundary, which is what the absolute and escape
    checks above already enforce, so an undeclared boundary narrows nothing and
    widens nothing.
    """
    paths = request.get("target_paths", ())
    if not _is_str_sequence(paths):
        return (RULE_TARGET_PATHS_BOUNDED, "target_paths", "target_path_not_bounded", "builtin_omh")
    if len(paths) > MAX_TARGET_PATHS:
        return (RULE_TARGET_PATHS_BOUNDED, "target_paths", "target_path_count_exceeded", "builtin_omh")
    roots = request.get("workspace_roots", ())
    root_parts = [_path_parts(root) for root in roots] if _is_str_sequence(roots) else []
    for index, item in enumerate(paths):
        field = f"target_paths[{index}]"
        if not item.strip():
            return (RULE_TARGET_PATHS_BOUNDED, field, "target_path_not_bounded", "builtin_omh")
        if _ABSOLUTE_PATH_RE.match(item):
            return (RULE_TARGET_PATHS_BOUNDED, field, "target_path_absolute", "builtin_omh")
        if ".." in _path_parts(item):
            return (RULE_TARGET_PATHS_BOUNDED, field, "target_path_escapes_project", "builtin_omh")
        if root_parts and not _within_roots(item, root_parts):
            return (RULE_TARGET_PATHS_BOUNDED, field, "target_path_outside_workspace_roots", "builtin_omh")
    return None


def _remote_targets_denial(request: Mapping[str, object]) -> _Denial | None:
    return _destination_shape_denial(
        request,
        field="remote_targets",
        rule_id=RULE_REMOTE_TARGETS_DECLARED,
        limit=MAX_REMOTE_TARGETS,
        not_bounded="remote_target_not_bounded",
        count_exceeded="remote_target_count_exceeded",
        kind_unknown="remote_target_kind_unknown",
        ref_missing="remote_target_ref_missing",
    )


def _destinations_denial(request: Mapping[str, object]) -> _Denial | None:
    """A prepared action may only reach a destination the boundary declared.

    Fail-closed by construction: an empty `approved_destinations` approves
    nothing, so naming any remote target without declaring it is a denial
    rather than a default-allow. The comparison is on the whole (kind, ref)
    pair -- approving `git_remote` in the abstract would approve every git
    remote, which is not a boundary.
    """
    shape = _destination_shape_denial(
        request,
        field="approved_destinations",
        rule_id=RULE_DESTINATIONS_APPROVED,
        limit=MAX_APPROVED_DESTINATIONS,
        not_bounded="approved_destination_not_bounded",
        count_exceeded="approved_destination_count_exceeded",
        kind_unknown="approved_destination_kind_unknown",
        ref_missing="approved_destination_ref_missing",
    )
    if shape is not None:
        return shape
    approved = {
        (str(item["kind"]), str(item["ref"]))
        for item in request.get("approved_destinations", ())
        if isinstance(item, Mapping) and "kind" in item and "ref" in item
    }
    for index, item in enumerate(request.get("remote_targets", ())):
        if not isinstance(item, Mapping):
            continue
        if (str(item.get("kind")), str(item.get("ref"))) not in approved:
            return (RULE_DESTINATIONS_APPROVED, f"remote_targets[{index}]", "destination_not_declared", "builtin_omh")
    return None


def _destination_shape_denial(
    request: Mapping[str, object],
    *,
    field: str,
    rule_id: str,
    limit: int,
    not_bounded: str,
    count_exceeded: str,
    kind_unknown: str,
    ref_missing: str,
) -> _Denial | None:
    """One shape check for both destination lists, so they cannot drift apart."""
    entries = request.get(field, ())
    if not _is_sequence(entries):
        return (rule_id, field, not_bounded, "builtin_omh")
    if len(entries) > limit:
        return (rule_id, field, count_exceeded, "builtin_omh")
    for index, item in enumerate(entries):
        entry_field = f"{field}[{index}]"
        if not isinstance(item, Mapping) or set(item) != {"kind", "ref"}:
            return (rule_id, entry_field, not_bounded, "builtin_omh")
        if item["kind"] not in REMOTE_TARGET_KINDS:
            return (rule_id, f"{entry_field}.kind", kind_unknown, "builtin_omh")
        if not _is_opaque_ref(item["ref"], field=f"{entry_field}.ref"):
            return (rule_id, f"{entry_field}.ref", ref_missing, "builtin_omh")
    return None


def _access_intents_denial(request: Mapping[str, object]) -> _Denial | None:
    """Read, write, and share, checked against what the boundary actually approves.

    Only the share axis carries a denial, and that is deliberate. `read` and
    `write` stay inside the workspace, where `workspace_roots` and the path
    rules above are the whole boundary, so a separate intent check there would
    refuse nothing the path rules do not already refuse. Sharing is the axis
    that leaves the workspace, so it is checked in both directions: reaching a
    destination without declaring the intent, and declaring the intent with no
    destination the boundary approved.
    """
    intents = request.get("access_intents", ())
    if not _is_str_sequence(intents):
        return (RULE_ACCESS_INTENT_DECLARED, "access_intents", "access_intent_not_bounded", "builtin_omh")
    if len(intents) > MAX_ACCESS_INTENTS:
        return (RULE_ACCESS_INTENT_DECLARED, "access_intents", "access_intent_count_exceeded", "builtin_omh")
    for index, item in enumerate(intents):
        if item not in ACCESS_INTENTS:
            return (RULE_ACCESS_INTENT_DECLARED, f"access_intents[{index}]", "access_intent_unknown", "builtin_omh")
    # Both destination lists are already shape-valid here: `_remote_targets_denial`
    # and `_destinations_denial` run before this check.
    shares = "share" in intents
    if request.get("remote_targets", ()) and not shares:
        return (RULE_ACCESS_INTENT_DECLARED, "access_intents", "access_intent_undeclared", "builtin_omh")
    if shares and not request.get("approved_destinations", ()):
        return (RULE_ACCESS_INTENT_DECLARED, "access_intents", "access_intent_unapproved", "builtin_omh")
    return None


def _persisted_content_denial(request: Mapping[str, object]) -> _Denial | None:
    refs = request.get("persisted_content_refs", ())
    if not _is_str_sequence(refs):
        return (RULE_PERSISTED_CONTENT_REFERENCED, "persisted_content_refs", "persisted_content_inline", "builtin_omh")
    if len(refs) > MAX_PERSISTED_CONTENT_REFS:
        return (
            RULE_PERSISTED_CONTENT_REFERENCED,
            "persisted_content_refs",
            "persisted_content_count_exceeded",
            "builtin_omh",
        )
    for index, item in enumerate(refs):
        field = f"persisted_content_refs[{index}]"
        if not _is_opaque_ref(item, field=field):
            return (RULE_PERSISTED_CONTENT_REFERENCED, field, "persisted_content_inline", "builtin_omh")
    return None


def _evidence_claims_denial(request: Mapping[str, object]) -> _Denial | None:
    observed_refs = request.get("observed_record_refs", ())
    if not _is_str_sequence(observed_refs) or len(observed_refs) > MAX_OBSERVED_RECORD_REFS:
        return (RULE_EVIDENCE_CLAIM_BOUNDED, "observed_record_refs", "observed_record_ref_invalid", "builtin_omh")
    for index, item in enumerate(observed_refs):
        field = f"observed_record_refs[{index}]"
        if not _is_opaque_ref(item, field=field):
            return (RULE_EVIDENCE_CLAIM_BOUNDED, field, "observed_record_ref_invalid", "builtin_omh")
    claims = request.get("evidence_claims", ())
    if not _is_str_sequence(claims):
        return (RULE_EVIDENCE_CLAIM_BOUNDED, "evidence_claims", "evidence_claim_unknown", "builtin_omh")
    if len(claims) > MAX_EVIDENCE_CLAIMS:
        return (RULE_EVIDENCE_CLAIM_BOUNDED, "evidence_claims", "evidence_claim_count_exceeded", "builtin_omh")
    for index, claim in enumerate(claims):
        field = f"evidence_claims[{index}]"
        if claim not in EVIDENCE_CLAIMS:
            return (RULE_EVIDENCE_CLAIM_BOUNDED, field, "evidence_claim_unknown", "builtin_omh")
        if claim in _OBSERVED_EVIDENCE_CLAIMS and not observed_refs:
            return (RULE_EVIDENCE_CLAIM_BOUNDED, field, "evidence_claim_unobserved", "builtin_omh")
    return None


def _org_level(org_rule_source: object) -> tuple[_Denial | None, list[str], dict[str, object]]:
    """Apply the opt-in org level: deny-only, never widening, fail-closed."""
    limits = _default_limits()
    if not isinstance(org_rule_source, Mapping):
        return _org_unavailable("org_source_malformed", "org_rule_source"), ["org_source_malformed"], limits
    reason = org_rule_source.get("reason_code")
    if reason not in ORG_SAFETY_RULE_SOURCE_REASON_CODES:
        return (
            _org_unavailable("org_source_malformed", "org_rule_source.reason_code"),
            ["org_source_malformed"],
            limits,
        )
    codes = [str(reason)]
    if org_rule_source.get("status") != "available":
        field = str(org_rule_source.get("field") or "org_rule_source")
        return (RULE_ORG_RULE_SOURCE, field, str(reason), "org"), codes, limits
    rules = org_rule_source.get("rules")
    if not isinstance(rules, Mapping):
        return _org_unavailable("org_source_malformed", "org_rule_source.rules"), [*codes, "org_source_malformed"], limits
    kinds = rules.get("denied_remote_target_kinds", ())
    if not _is_str_sequence(kinds) or any(kind not in REMOTE_TARGET_KINDS for kind in kinds):
        return (
            (RULE_ORG_RULE_SOURCE, "org_rule_source.denied_remote_target_kinds", "org_rule_unknown_value", "org"),
            [*codes, "org_rule_unknown_value"],
            limits,
        )
    cap = rules.get("max_target_paths")
    if cap is not None and (not isinstance(cap, int) or isinstance(cap, bool) or cap < 0):
        return (
            (RULE_ORG_RULE_SOURCE, "org_rule_source.max_target_paths", "org_rule_unknown_value", "org"),
            [*codes, "org_rule_unknown_value"],
            limits,
        )
    if isinstance(cap, int) and not isinstance(cap, bool):
        # Narrowing only. A larger org cap is recorded and discarded, so the
        # org level can never widen what the built-in profile allows.
        if cap > MAX_TARGET_PATHS:
            codes.append("org_widening_ignored")
        else:
            limits["max_target_paths"] = cap
    limits["denied_remote_target_kinds"] = tuple(kinds)
    return None, codes, limits


def _org_narrowing_denial(request: Mapping[str, object], limits: Mapping[str, object]) -> _Denial | None:
    paths = request.get("target_paths", ())
    cap = limits["max_target_paths"]
    if _is_str_sequence(paths) and isinstance(cap, int) and len(paths) > cap:
        return (RULE_ORG_RULE_SOURCE, "target_paths", "org_rule_denied", "org")
    denied = set(limits["denied_remote_target_kinds"])
    remotes = request.get("remote_targets", ())
    if denied and _is_sequence(remotes):
        for index, item in enumerate(remotes):
            if isinstance(item, Mapping) and item.get("kind") in denied:
                return (RULE_ORG_RULE_SOURCE, f"remote_targets[{index}].kind", "org_rule_denied", "org")
    return None


def _org_unavailable(reason_code: str, field: str) -> _Denial:
    return (RULE_ORG_RULE_SOURCE, field, reason_code, "org")


def _is_opaque_ref(value: object, *, field: str) -> bool:
    try:
        require_opaque_metadata_ref(value, field=field)
    except ValueError:
        return False
    return True


def _path_parts(value: str) -> tuple[str, ...]:
    """A declared path as comparable segments, on every host.

    Both separators are folded and empty and `.` segments dropped, so
    `src/quality`, `src\\quality`, and `./src/quality/` are the same boundary.
    The comparison stays case-sensitive on purpose: a case-insensitive answer
    would depend on which machine evaluated the request, and a verdict that
    differs by host is not a verdict.
    """
    return tuple(part for part in value.replace("\\", "/").split("/") if part not in ("", "."))


def _within_roots(path: str, root_parts: Sequence[tuple[str, ...]]) -> bool:
    # A root that normalises to no segments is the project root, and an empty
    # prefix matches every path, so declaring `.` is the same boundary as
    # declaring none rather than a boundary nothing can satisfy.
    parts = _path_parts(path)
    return any(parts[: len(root)] == root for root in root_parts)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _is_str_sequence(value: object) -> bool:
    return _is_sequence(value) and all(isinstance(item, str) for item in value)


def _stable_encode(value: object) -> str:
    if isinstance(value, Mapping):
        return "{" + "\x1f".join(f"{key}\x1e{_stable_encode(value[key])}" for key in sorted(value)) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + "\x1f".join(_stable_encode(item) for item in value) + "]"
    return f"{type(value).__name__}:{value}"
