"""#803: reviewed, tamper-evident integrity records for the native OMH hooks.

A sibling record, not more fields on `hook_manifest()`. That choice is the
whole shape of this module, so here is why it went that way.

`capabilities.hooks.hook_manifest()` is a *static* projection. It is folded into
`capability_snapshot()` behind an `lru_cache`, which advertises itself as
`static_projection_no_runtime_clock`, and it is mirrored byte-for-byte by a
standalone copy inside the vendored bundle
(`plugin_bundle/omh/tools/capability_tool.py`) so the plugin can answer without
importing the omh package. Integrity is the opposite kind of fact: it needs
`OmhPaths`, it reads the installed plugin directory, and it reads a local
revocation ledger. Folding disk state into the manifest would make a cached,
environment-independent payload depend on the environment, and would force the
vendored mirror to grow a filesystem dependency it deliberately does not have.

So this is one hook concept with two projections, not two hook concepts. The
vocabulary of hooks is still `plugin_bundle.omh.metadata.PROVIDED_HOOKS`; every
record here names a hook the manifest already declares, and the status carries
`hook_manifest_schema_version` so a reader can see which manifest it refines.
Nothing here invents a hook.

Four rules the rest of the file follows:

1. The digest is the one `install.plugin_pack` already computes. The reviewed
   value comes straight out of `bundled_plugin_records()` -- the same
   `sha256_text` over the same packaged resource -- and the installed value is
   `sha256_file` over the file that record was copied to. There is no second
   hashing scheme, and the bundle writer's `newline=""` is what keeps the two
   comparable on Windows.
2. Trust is scoped to the hook's own entry module. Whole-bundle staleness is
   already owned by doctor's `plugin_bundle_current` check; duplicating it here
   would report the same drift twice under two different repairs.
3. A changed or revoked hook is dropped from `managed_hooks` *and* listed in
   `excluded_hooks` with the capability it takes down and the command that
   brings it back. Dropping it quietly is the bug this record exists to stop.
4. Installation is never observation. Every record carries
   `observed_in_this_environment: False` and the status says so in its claim
   boundary. A reviewed digest on disk proves a file, not a Hermes invocation;
   only `install.plugin_observations` records the latter.

Revocation is data, never absence. A revoked hook stays in `records` marked
`revoked` with its reason, so an operator reading the projection sees a hook
that was deliberately taken out rather than a hook that silently vanished, and
it stays revoked until the ledger entry is removed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..capabilities.schema import HOOK_EVENT_CAPABILITY_SCHEMA_VERSION
from ..hashutil import sha256_file
from ..local_store import read_json_object_result
from ..paths import OmhPaths
from ..plugin_bundle.omh.metadata import PROVIDED_HOOKS, REQUIRED_HOOKS
from .plugin_pack import bundled_plugin_records

HOOK_INTEGRITY_SCHEMA_VERSION = "omh_hook_integrity/v1"
HOOK_REVOCATION_LEDGER_SCHEMA_VERSION = "omh_hook_revocations/v1"

# The only host surface OMH registers a hook into. It is recorded per hook
# rather than assumed, because a future second target must be a visible change
# to a reviewed record, not a silent widening of where a hook can run.
HOOK_HOST_TARGET = "hermes_plugin_host"

# The event vocabulary a reviewed record may claim scope over. Hermes exposes
# its own `VALID_HOOKS` at runtime -- `plugin_bundle/omh/__init__.py` consults
# it before registering an optional hook -- and this is the packaged mirror of
# the subset OMH ships. A record naming anything outside it is refused rather
# than trusted, so a typo or a widened matcher cannot arrive as a reviewed fact.
VALID_HOOK_EVENTS = frozenset(PROVIDED_HOOKS)

# Per-record axes.
HOOK_DIGEST_STATES = ("matches", "changed", "missing", "not_installed", "not_reviewed")
HOOK_REVIEW_STATES = ("reviewed", "unreviewed")
HOOK_REVOCATION_STATES = ("active", "revoked")
HOOK_HOST_REGISTRATION_STATES = ("required", "optional")
# Status-level aggregates. Separate vocabularies from the per-record ones on
# purpose: "one hook changed" and "this hook changed" are different sentences.
DIGEST_AGGREGATE_STATES = ("matches", "changed", "not_installed")
REVIEW_AGGREGATE_STATES = ("all_reviewed", "unreviewed_present")
REVOCATION_AGGREGATE_STATES = ("none", "revoked_present")
REVOCATION_LEDGER_STATES = ("absent", "loaded", "unreadable")

HOOK_INTEGRITY_RECORD_KEYS = (
    "capability",
    "digest",
    "event_scope",
    "exclusion_reason",
    "host_registration",
    "host_target",
    "installed_digest",
    "name",
    "observed_in_this_environment",
    "repair",
    "review",
    "reviewed_digest",
    "reviewed_timeout_ms",
    "revocation",
    "revocation_reason",
    "source_path",
    "trusted",
)

HOOK_INTEGRITY_STATUS_KEYS = (
    "claim_boundary",
    "digest_state",
    "excluded_hooks",
    "hook_manifest_schema_version",
    "managed_hooks",
    "next_action",
    "observed_in_this_environment",
    "plugin_dir",
    "plugin_installed",
    "records",
    "review_state",
    "revocation_ledger",
    "revocation_ledger_path",
    "revocation_state",
    "schema_version",
)

HOOK_INTEGRITY_CLAIM_BOUNDARY = (
    "This is the local integrity state of the reviewed OMH hooks. A matching digest proves the "
    "installed file is the reviewed one; it is not evidence that Hermes loaded, registered, or "
    "invoked the hook. Registration, load, and invocation stay separate axes recorded only by "
    "omh_plugin_host_observation records."
)

# `reviewed_timeout_ms` is the review budget for a hook, not an enforced limit:
# Hermes owns hook execution and OMH never times one out. It is recorded so a
# change in a hook's expected cost is a reviewable change to this table rather
# than an invisible one. 2000 for the hooks that assemble context and write a
# local record, 1000 for the ones that only classify their input.
HOOK_REVIEWS: dict[str, dict[str, Any]] = {
    "on_session_end": {
        "source_path": "hooks/session_hooks.py",
        "event_scope": ("on_session_end",),
        "reviewed_timeout_ms": 2000,
        "capability": "the OMH end-of-session summary record",
    },
    "pre_llm_call": {
        "source_path": "hooks/llm_hooks.py",
        "event_scope": ("pre_llm_call",),
        "reviewed_timeout_ms": 2000,
        "capability": "OMH awareness, context brief, and route hint injection before a Hermes LLM call",
    },
    "pre_tool_call": {
        "source_path": "hooks/tool_hooks.py",
        "event_scope": ("pre_tool_call",),
        "reviewed_timeout_ms": 1000,
        "capability": (
            "user-authored toolcall-rule block directives and the OMH "
            "unknown-role warning before a Hermes tool call"
        ),
    },
    "post_tool_call": {
        "source_path": "hooks/tool_hooks.py",
        "event_scope": ("post_tool_call",),
        "reviewed_timeout_ms": 1000,
        "capability": (
            "closing the in-flight tool-call ledger entry that backs the OMH "
            "HUD's liveness signal (open-call count, stalled-todo warning, "
            "parallel-shot lifetime)"
        ),
    },
    "pre_verify": {
        "source_path": "hooks/verify_hooks.py",
        "event_scope": ("pre_verify",),
        "reviewed_timeout_ms": 1000,
        "capability": (
            "the OMH served-surface verification nudge and the open-plan "
            "continuation directive before a Hermes coding verification"
        ),
    },
    "subagent_start": {
        "source_path": "hooks/session_hooks.py",
        "event_scope": ("subagent_start",),
        "reviewed_timeout_ms": 1000,
        "capability": (
            "recording the delegated child's session id in process memory so "
            "the engagement nudges can tell a subagent from the session that "
            "spawned it (no file write, no runtime read, never blocks a spawn)"
        ),
    },
    "transform_tool_result": {
        "source_path": "hooks/result_transforms.py",
        "event_scope": ("transform_tool_result",),
        "reviewed_timeout_ms": 1000,
        "capability": (
            "once-per-session code-mode discipline annotation of execute_code "
            "results, bounded self-latching plan and delegation nudges on "
            "file-mutating and search/read results, plus full-width diff band "
            "padding of tool-result diffs (non-matching results pass through "
            "untouched)"
        ),
    },
}

# An operator-written reason can be any length; the doctor line that quotes it
# cannot. Truncating on read keeps one bad ledger entry from swamping the
# summary an operator reads to find the repair.
REVOCATION_REASON_LIMIT = 200


def revocation_ledger_path(paths: OmhPaths) -> Path:
    return paths.runtime_dir / "hook_revocations.json"


def read_hook_revocations(paths: OmhPaths) -> tuple[dict[str, str], str]:
    """Read the local revocation ledger as `{hook name: reason}` plus its state.

    An unreadable ledger returns `unreadable` with no revocations rather than
    revoking everything. Fail-closed would be a nice slogan and a bad rule: a
    corrupt file is not evidence that any particular hook was withdrawn, and
    the honest report is that the ledger needs repairing, which the doctor
    check raises on its own.
    """
    path = revocation_ledger_path(paths)
    if not path.exists():
        return {}, "absent"
    payload, error = read_json_object_result(path)
    if error or payload is None:
        return {}, "unreadable"
    if payload.get("schema_version") != HOOK_REVOCATION_LEDGER_SCHEMA_VERSION:
        # A ledger written for a version this OMH does not understand is not an
        # empty ledger. Reading it as one would answer "nothing is revoked"
        # about a file that may say the opposite.
        return {}, "unreadable"
    entries = payload.get("revoked")
    if not isinstance(entries, list):
        return {}, "unreadable"
    revoked: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("hook", "")).strip()
        if not name:
            continue
        revoked[name] = str(entry.get("reason", "")).strip()[:REVOCATION_REASON_LIMIT]
    return revoked, "loaded"


def build_hook_integrity_status(paths: OmhPaths) -> dict[str, Any]:
    """Project every declared hook as one reviewed, tamper-evident record.

    A hook the plugin bundle has not been installed for is not distrusted. It
    keeps its reviewed digest and reports `not_installed`, because nothing has
    changed anything -- treating an absent install as tampering would make a
    fresh machine look compromised and would fail doctor for every operator who
    has not run `omh setup` yet.
    """
    plugin_dir = paths.hermes_plugin_dir
    plugin_installed = plugin_dir.is_dir()
    reviewed_digests = _packaged_file_digests()
    revoked, ledger_state = read_hook_revocations(paths)

    records = [
        _hook_record(
            name,
            plugin_dir=plugin_dir,
            plugin_installed=plugin_installed,
            reviewed_digests=reviewed_digests,
            revoked=revoked,
        )
        for name in sorted(PROVIDED_HOOKS)
    ]
    managed = sorted(record["name"] for record in records if record["trusted"])
    excluded = [
        {
            "name": record["name"],
            "reason": record["exclusion_reason"],
            "capability": record["capability"],
            "repair": record["repair"],
        }
        for record in records
        if not record["trusted"]
    ]
    return {
        "schema_version": HOOK_INTEGRITY_SCHEMA_VERSION,
        "hook_manifest_schema_version": HOOK_EVENT_CAPABILITY_SCHEMA_VERSION,
        "plugin_dir": str(plugin_dir),
        "plugin_installed": plugin_installed,
        "records": records,
        "managed_hooks": managed,
        "excluded_hooks": excluded,
        "digest_state": _digest_aggregate(records, plugin_installed=plugin_installed),
        "review_state": _review_aggregate(records),
        "revocation_state": _revocation_aggregate(records),
        "revocation_ledger": ledger_state,
        "revocation_ledger_path": str(revocation_ledger_path(paths)),
        "next_action": _next_action(records, ledger_state=ledger_state),
        "observed_in_this_environment": False,
        "claim_boundary": HOOK_INTEGRITY_CLAIM_BOUNDARY,
    }


def validate_hook_integrity_status(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["hook_integrity_status must be an object"]
    errors: list[str] = []
    extra = sorted(set(payload) - set(HOOK_INTEGRITY_STATUS_KEYS))
    if extra:
        errors.append(f"hook_integrity_status has unsupported keys: {extra}")
    missing = sorted(set(HOOK_INTEGRITY_STATUS_KEYS) - set(payload))
    if missing:
        errors.append(f"hook_integrity_status is missing keys: {missing}")
    if payload.get("schema_version") != HOOK_INTEGRITY_SCHEMA_VERSION:
        errors.append(f"hook_integrity_status schema_version must be {HOOK_INTEGRITY_SCHEMA_VERSION}")
    if payload.get("hook_manifest_schema_version") != HOOK_EVENT_CAPABILITY_SCHEMA_VERSION:
        errors.append(
            f"hook_integrity_status hook_manifest_schema_version must be {HOOK_EVENT_CAPABILITY_SCHEMA_VERSION}"
        )
    for key, vocabulary in (
        ("digest_state", DIGEST_AGGREGATE_STATES),
        ("review_state", REVIEW_AGGREGATE_STATES),
        ("revocation_state", REVOCATION_AGGREGATE_STATES),
        ("revocation_ledger", REVOCATION_LEDGER_STATES),
    ):
        if payload.get(key) not in vocabulary:
            errors.append(f"hook_integrity_status {key} must be one of {list(vocabulary)}")
    if payload.get("observed_in_this_environment") is not False:
        # AC3, at the schema level: nothing this record can see is invocation
        # evidence, so there is no value other than False for it to carry.
        errors.append("hook_integrity_status observed_in_this_environment must be False")
    records = payload.get("records")
    if not isinstance(records, list):
        return errors + ["hook_integrity_status records must be a list"]
    managed = payload.get("managed_hooks")
    if not isinstance(managed, list) or not all(isinstance(item, str) for item in managed):
        errors.append("hook_integrity_status managed_hooks must be a list of strings")
        managed = []
    elif list(managed) != sorted(managed):
        errors.append("hook_integrity_status managed_hooks must be sorted")
    errors.extend(_record_errors(records, managed=[str(item) for item in managed]))
    errors.extend(_exclusion_errors(payload.get("excluded_hooks"), records))
    return errors


def _record_errors(records: list[Any], *, managed: list[str]) -> list[str]:
    errors: list[str] = []
    trusted_names: list[str] = []
    for index, record in enumerate(records):
        label = f"hook_integrity_status records[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{label} must be an object")
            continue
        name = str(record.get("name", ""))
        extra = sorted(set(record) - set(HOOK_INTEGRITY_RECORD_KEYS))
        if extra:
            errors.append(f"{label} has unsupported keys: {extra}")
        missing = sorted(set(HOOK_INTEGRITY_RECORD_KEYS) - set(record))
        if missing:
            errors.append(f"{label} is missing keys: {missing}")
        for key, vocabulary in (
            ("digest", HOOK_DIGEST_STATES),
            ("review", HOOK_REVIEW_STATES),
            ("revocation", HOOK_REVOCATION_STATES),
            ("host_registration", HOOK_HOST_REGISTRATION_STATES),
        ):
            if record.get(key) not in vocabulary:
                errors.append(f"{label} {key} must be one of {list(vocabulary)}")
        if record.get("host_target") != HOOK_HOST_TARGET:
            errors.append(f"{label} host_target must be {HOOK_HOST_TARGET}")
        if record.get("observed_in_this_environment") is not False:
            errors.append(f"{label} observed_in_this_environment must be False")
        scope = record.get("event_scope")
        if not isinstance(scope, list) or not all(isinstance(item, str) for item in scope):
            errors.append(f"{label} event_scope must be a list of strings")
        else:
            unknown = sorted(set(scope) - VALID_HOOK_EVENTS)
            if unknown:
                errors.append(f"{label} event_scope names events outside VALID_HOOK_EVENTS: {unknown}")
        if record.get("trusted") is True:
            trusted_names.append(name)
            errors.extend(_managed_record_errors(record, label=label))
        elif record.get("trusted") is not False:
            errors.append(f"{label} trusted must be a boolean")
        else:
            if not str(record.get("exclusion_reason", "")):
                errors.append(f"{label} is excluded and must carry an exclusion_reason")
            if not str(record.get("repair", "")):
                errors.append(f"{label} is excluded and must carry a repair")
            if not str(record.get("capability", "")):
                errors.append(f"{label} is excluded and must name the unavailable capability")
    if sorted(trusted_names) != sorted(managed):
        errors.append("hook_integrity_status managed_hooks must list exactly the trusted records")
    return errors


def _managed_record_errors(record: dict[str, Any], *, label: str) -> list[str]:
    """AC1: a managed hook without a reviewed digest and an event scope is invalid."""
    errors: list[str] = []
    digest = str(record.get("reviewed_digest", ""))
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        errors.append(f"{label} is managed and must carry a reviewed sha256 digest")
    scope = record.get("event_scope")
    if not isinstance(scope, list) or not scope:
        errors.append(f"{label} is managed and must declare a non-empty event scope")
    if record.get("review") != "reviewed":
        errors.append(f"{label} is managed and must be reviewed")
    if record.get("revocation") != "active":
        errors.append(f"{label} is managed and must not be revoked")
    if str(record.get("exclusion_reason", "")) or str(record.get("repair", "")):
        errors.append(f"{label} is managed and must not carry an exclusion_reason or repair")
    return errors


def _exclusion_errors(excluded: Any, records: list[Any]) -> list[str]:
    if not isinstance(excluded, list):
        return ["hook_integrity_status excluded_hooks must be a list"]
    errors: list[str] = []
    untrusted = sorted(
        str(record.get("name", ""))
        for record in records
        if isinstance(record, dict) and record.get("trusted") is not True
    )
    listed = sorted(str(item.get("name", "")) for item in excluded if isinstance(item, dict))
    if listed != untrusted:
        errors.append("hook_integrity_status excluded_hooks must list exactly the untrusted records")
    for index, item in enumerate(excluded):
        label = f"hook_integrity_status excluded_hooks[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        if sorted(item) != ["capability", "name", "reason", "repair"]:
            errors.append(f"{label} must carry name, reason, capability, and repair")
            continue
        for key in ("capability", "reason", "repair"):
            if not str(item.get(key, "")):
                errors.append(f"{label} {key} must not be empty")
    return errors


def _hook_record(
    name: str,
    *,
    plugin_dir: Path,
    plugin_installed: bool,
    reviewed_digests: dict[str, str],
    revoked: dict[str, str],
) -> dict[str, Any]:
    review = HOOK_REVIEWS.get(name)
    source_path = str(review["source_path"]) if review else ""
    reviewed_digest = reviewed_digests.get(source_path, "") if review else ""
    digest, installed_digest = _digest_state(
        source_path,
        reviewed_digest,
        plugin_dir=plugin_dir,
        plugin_installed=plugin_installed,
        reviewed=review is not None,
    )
    record: dict[str, Any] = {
        "name": name,
        "event_scope": list(review["event_scope"]) if review else [],
        "host_target": HOOK_HOST_TARGET,
        "host_registration": "required" if name in REQUIRED_HOOKS else "optional",
        "source_path": source_path,
        "review": "reviewed" if review else "unreviewed",
        "reviewed_digest": reviewed_digest,
        "installed_digest": installed_digest,
        "digest": digest,
        "reviewed_timeout_ms": int(review["reviewed_timeout_ms"]) if review else 0,
        "revocation": "revoked" if name in revoked else "active",
        "revocation_reason": revoked.get(name, ""),
        "capability": str(review["capability"]) if review else f"the OMH `{name}` hook",
        "trusted": True,
        "exclusion_reason": "",
        "repair": "",
        "observed_in_this_environment": False,
    }
    reason, repair = _exclusion(record)
    if reason:
        record["trusted"] = False
        record["exclusion_reason"] = reason
        record["repair"] = repair
    return record


def _exclusion(record: dict[str, Any]) -> tuple[str, str]:
    """Why this hook is not in the managed projection, and what brings it back.

    Ordered by which fact wins. A revoked hook is a decision an operator made,
    so it is reported as revocation even when the file also drifted; telling
    them to reinstall a hook they deliberately withdrew would be the wrong
    repair.
    """
    name = record["name"]
    capability = record["capability"]
    if record["revocation"] == "revoked":
        reason = str(record["revocation_reason"]) or "no reason recorded"
        return (
            f"revoked locally ({reason})",
            f"Hook `{name}` is revoked locally, so {capability} is unavailable. "
            f"Remove its entry from the OMH hook revocation ledger, then rerun `omh doctor`.",
        )
    if record["review"] == "unreviewed":
        return (
            "no reviewed digest for this hook",
            f"Hook `{name}` carries no reviewed digest, so {capability} is unavailable. "
            f"Upgrade OMH to a release that reviews `{name}`, then rerun `omh doctor`.",
        )
    if record["digest"] == "changed":
        return (
            "installed file no longer matches the reviewed digest",
            f"Hook `{name}` no longer matches its reviewed digest, so {capability} is unavailable. "
            f"Run `omh setup --force` to restore the reviewed hook, then rerun `omh doctor`.",
        )
    if record["digest"] == "missing":
        return (
            "installed file is missing",
            f"Hook `{name}` is missing from the installed plugin bundle, so {capability} is unavailable. "
            f"Run `omh setup --force` to restore the reviewed hook, then rerun `omh doctor`.",
        )
    return "", ""


def _digest_state(
    source_path: str,
    reviewed_digest: str,
    *,
    plugin_dir: Path,
    plugin_installed: bool,
    reviewed: bool,
) -> tuple[str, str]:
    if not reviewed or not reviewed_digest:
        return "not_reviewed", ""
    if not plugin_installed:
        return "not_installed", ""
    # `source_path` is stored POSIX-style; splitting it rebuilds the path with
    # the separator this OS uses instead of asserting one.
    installed = plugin_dir.joinpath(*source_path.split("/"))
    if not installed.is_file():
        return "missing", ""
    installed_digest = sha256_file(installed)
    return ("matches" if installed_digest == reviewed_digest else "changed", installed_digest)


def _packaged_file_digests() -> dict[str, str]:
    """The reviewed digest of every packaged bundle file, keyed POSIX-style.

    `bundled_plugin_records()` builds its paths with `pathlib`, so they arrive
    separated by `\\` on Windows and `/` elsewhere. Normalizing here is what
    lets `HOOK_REVIEWS` name one source path per hook.
    """
    return {
        str(record.get("path", "")).replace("\\", "/"): str(record.get("sha256", ""))
        for record in bundled_plugin_records()
    }


def _digest_aggregate(records: list[dict[str, Any]], *, plugin_installed: bool) -> str:
    if any(record["digest"] in {"changed", "missing"} for record in records):
        return "changed"
    if not plugin_installed:
        return "not_installed"
    return "matches"


def _review_aggregate(records: list[dict[str, Any]]) -> str:
    return "unreviewed_present" if any(record["review"] == "unreviewed" for record in records) else "all_reviewed"


def _revocation_aggregate(records: list[dict[str, Any]]) -> str:
    return "revoked_present" if any(record["revocation"] == "revoked" for record in records) else "none"


def _next_action(records: list[dict[str, Any]], *, ledger_state: str) -> str:
    # Ordered by which repair unblocks the others: a ledger nobody can read
    # hides revocations, and a revocation an operator chose outranks a
    # reinstall they did not ask for.
    if ledger_state == "unreadable":
        return "Repair or remove the OMH hook revocation ledger, then rerun `omh doctor`."
    revoked = [record["name"] for record in records if record["revocation"] == "revoked"]
    if revoked:
        return (
            f"Remove {', '.join(sorted(revoked))} from the OMH hook revocation ledger to restore "
            "the revoked hook(s), then rerun `omh doctor`."
        )
    if any(record["digest"] in {"changed", "missing"} for record in records):
        return "Run `omh setup --force` to restore the reviewed OMH hooks, then rerun `omh doctor`."
    if any(record["review"] == "unreviewed" for record in records):
        return "Upgrade OMH to a release that reviews every provided hook, then rerun `omh doctor`."
    return "No repair needed. Hermes hook registration and invocation stay unobserved until a host observation records them."
