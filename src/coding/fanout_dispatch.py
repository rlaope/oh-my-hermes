from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..runtime.artifacts import append_journal_observation, create_run, show_run
from ..system.local_store import atomic_write_json, ensure_dir, locked_json_update, utc_now
from ..system.metadata_safety import redact_metadata_text
from ..system.paths import OmhPaths
from .action_gate import recheck_safety_profile_revision
from .coding_contracts import STRUCTURAL_SEARCH_GUIDANCE
from .executor_capability_snapshots import (
    complete_executor_capability_snapshot,
    validate_executor_capability_snapshot,
)
from .executor_capabilities import legacy_executor_capability_projection
from .executor_readiness import probe_executor_readiness
from .fanout_contracts import (
    FANOUT_CLAIM_BOUNDARY,
    FANOUT_CONTRACT_SCHEMA_VERSION,
    LEGACY_FANOUT_CONTRACT_SCHEMA_VERSION,
    UNIT_VERIFICATION_OBSERVATION_SOURCE,
    FanoutContractError,
    verification_command_argv,
)
from .inflight import InflightMarkerError, clear_inflight_marker, write_inflight_marker
from .unit_prompt_protocol import unit_protocol_lines
from .fanout_unit_results import validate_check_rows, validate_unit_result
from .unit_telemetry import parse_unit_telemetry

FANOUT_DISPATCH_SCHEMA_VERSION = "fanout_dispatch_summary/v1"
DISPATCH_CLAIM_BOUNDARY = (
    "A dispatch summary records observed local subprocess activity only. It is not verification, review, CI, "
    "merge-readiness, or merge evidence, and omh never merges unit branches itself."
)
UNIT_VERIFICATION_CLAIM_BOUNDARY = (
    "A dispatcher verification row records that omh itself ran one command the contract declared, in that "
    "unit's worktree, and what it exited with. It is not review, CI, merge-readiness, or merge evidence, "
    "and a passing command proves only that command."
)
# Ten minutes per command. The field exists to carry unit-test and byte-gate
# commands, which finish well inside that; the ceiling is here so one hung
# command cannot hold a whole dispatch open.
_VERIFICATION_COMMAND_TIMEOUT = 600
_MAX_VERIFICATION_OUTPUT_TAIL = 300
EXECUTOR_LIMIT_SIGNALS_SCHEMA_VERSION = "executor_limit_signals/v1"
EXECUTOR_LIMIT_SIGNALS_CLAIM_BOUNDARY = (
    "A limit signal records that one observed local dispatch failure matched a rate/usage-limit shape. "
    "It is not provider quota truth, not an entitlement statement, and it expires as evidence the moment "
    "the provider state changes."
)

# Deterministic limit-shape patterns, matched case-insensitively over the
# in-memory stdout/stderr tails of a FAILED spawn only. Only the boolean and
# the matched label are persisted — never the matched text itself. Every
# pattern is anchored to limit context: bare "429" or "quota" would match a
# stack-trace line number or a disk-quota message and fabricate provider
# evidence from unrelated text.
_LIMIT_SHAPED_PATTERNS: tuple[tuple[str, str], ...] = (
    ("rate_limit", "rate limit"),
    ("usage_limit", "usage limit"),
    ("quota_exceeded", "quota exceed"),
    ("quota_exceeded", "quota exhaust"),
    ("quota_exceeded", "api quota"),
    ("http_429", "status 429"),
    ("http_429", "error 429"),
    ("http_429", "http 429"),
    ("http_429", "429 too many"),
    ("credit", "insufficient credit"),
    ("credit", "out of credits"),
    ("limit_reached", "limit reached"),
)

# Spawnability is a data property: profiles listed here have a local headless
# CLI template. Every other profile (hermes, omx/omo/omc runtimes, generic,
# unassigned) gets a prepared-prompt fallback and is never spawned.
DISPATCH_COMMAND_TEMPLATES: dict[str, tuple[str, ...]] = {
    "codex": ("codex", "exec", "{prompt}"),
    # acceptEdits alone lets Claude edit files but blocks the `git add/commit`
    # the unit prompt asks for (observed in the first live dispatch);
    # allowedTools grants exactly those two git verbs, nothing broader.
    "claude-code": (
        "claude",
        "-p",
        "{prompt}",
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        "Bash(git add:*),Bash(git commit:*)",
    ),
    # omo ships as an extension of a pi-family host CLI (usually `pi`;
    # `senpi` is a distribution of it with the same headless surface) or of
    # opencode. The host is DETECTED at dispatch time in a fixed order —
    # see OMO_RUNTIME_HOST_CANDIDATES — and the placeholder below is
    # replaced by the detected host's template; no personal stack is
    # hardcoded. The pi/senpi surface was validated in a live bridge
    # dispatch (2026-07, senpi): `--print --no-session` completes
    # non-interactively with clean exit codes on failure, and the
    # `workspace` permission preset allowed file creation plus exactly the
    # `git add`/`git commit` the unit prompt asks for. The opencode
    # template is prepared from `opencode run --help` (model/variant flags
    # verified locally); its permission behavior validates on first live
    # dispatch, claude-template precedent.
    "omo-runtime": (
        "senpi",
        "--print",
        "--no-session",
        "--permission-preset",
        "workspace",
        "{prompt}",
    ),
}

# Fixed detection order for the omo runtime's local host CLI: first on PATH
# wins ("usually pi" — user-stated common case; senpi is a pi distribution;
# opencode hosts omo as a plugin). Both layouts — pi-family host CLI and
# opencode plugin — are first-class dispatch hosts. Detection is
# presence-only and recorded implicitly by argv[0]/probe command. Model
# CONFIG, by contrast, is currently read only from the opencode config path
# (see MODEL_INVENTORY_CATALOG_PROFILE in model_inventory): a pi-only
# install still dispatches, but its routes degrade to `no_model_catalog`.
OMO_RUNTIME_HOST_CANDIDATES: tuple[str, ...] = ("pi", "senpi", "opencode")

_OMO_HOST_TEMPLATES: dict[str, dict[str, tuple[str, ...] | int | None]] = {
    "pi": {
        "argv": ("pi", "--print", "--no-session", "--permission-preset", "workspace", "{prompt}"),
        "model": ("--model", "{model}"),
        "effort": ("--thinking", "{effort}"),
        "insert": 5,
    },
    "senpi": {
        "argv": ("senpi", "--print", "--no-session", "--permission-preset", "workspace", "{prompt}"),
        "model": ("--model", "{model}"),
        "effort": ("--thinking", "{effort}"),
        "insert": 5,
    },
    "opencode": {
        "argv": ("opencode", "run", "{prompt}"),
        "model": ("--model", "{model}"),
        "effort": ("--variant", "{effort}"),
        "insert": 2,
    },
}


def omo_runtime_host(which: Callable[[str], str | None] | None = None) -> str | None:
    """Return the first omo host CLI present on PATH, or None.

    The default resolves `shutil.which` at CALL time (a def-time default
    would freeze the binding and make the probe untestable/unpatchable).
    """
    resolved_which = shutil.which if which is None else which
    for candidate in OMO_RUNTIME_HOST_CANDIDATES:
        if resolved_which(candidate):
            return candidate
    return None


# Model routing is prepared metadata on the unit handoff; these fragments turn
# it into argv only at dispatch time. Codex takes options before the prompt
# positional; claude accepts them anywhere, so they append after the pinned
# base argv to keep the no-route argv byte-identical to the template.
DISPATCH_MODEL_OPTION_TEMPLATES: dict[str, tuple[str, ...]] = {
    "codex": ("--model", "{model}"),
    "claude-code": ("--model", "{model}"),
    # senpi takes `provider/model` ids — exactly the form inventory-derived
    # routes carry.
    "omo-runtime": ("--model", "{model}"),
}
DISPATCH_REASONING_OPTION_TEMPLATES: dict[str, tuple[str, ...]] = {
    # `-c` values parse as TOML with a raw-string fallback, so a bare effort
    # level is accepted verbatim (verified against `codex exec --help`).
    "codex": ("--config", "model_reasoning_effort={effort}"),
    "claude-code": ("--effort", "{effort}"),
    # senpi's thinking levels (off|minimal|low|medium|high|xhigh|max) are a
    # superset of the effort ladder, so routed efforts map verbatim.
    "omo-runtime": ("--thinking", "{effort}"),
}
# senpi treats trailing tokens as message positionals, so options insert
# before the prompt like codex; claude accepts them anywhere and appends.
_DISPATCH_OPTION_INSERT_INDEX: dict[str, int | None] = {"codex": 2, "claude-code": None, "omo-runtime": 5}


def build_dispatch_argv(
    owner: str,
    prompt: str,
    model_route: Mapping[str, Any] | None = None,
) -> list[str] | None:
    """Return the spawn argv for one owner, or None when the owner has no template.

    Without a model route the argv is byte-identical to the base template; a
    routed model/effort inserts the per-owner option fragments only.
    """
    if owner == "omo-runtime":
        host = omo_runtime_host()
        if host is None:
            return None
        host_table = _OMO_HOST_TEMPLATES[host]
        template = host_table["argv"]
        model_template = host_table["model"]
        effort_template = host_table["effort"]
        insert_index = host_table["insert"]
    else:
        template = DISPATCH_COMMAND_TEMPLATES.get(owner)
        model_template = DISPATCH_MODEL_OPTION_TEMPLATES.get(owner, ())
        effort_template = DISPATCH_REASONING_OPTION_TEMPLATES.get(owner, ())
        insert_index = _DISPATCH_OPTION_INSERT_INDEX.get(owner)
    if template is None:
        return None
    argv = [part.replace("{prompt}", prompt) for part in template]
    route = model_route or {}
    options: list[str] = []
    model = str(route.get("selected_model", "") or "")
    effort = str(route.get("selected_reasoning_effort", "") or "")
    if model:
        options.extend(part.replace("{model}", model) for part in model_template)
    if effort:
        options.extend(part.replace("{effort}", effort) for part in effort_template)
    if not options:
        return argv
    insert_at = insert_index
    if insert_at is None:
        return argv + options
    return argv[:insert_at] + options + argv[insert_at:]


def build_unit_prompt(
    unit: Mapping[str, Any],
    goal_text: str,
    discovery: Mapping[str, Any] | None = None,
    *,
    unit_result_contract: Mapping[str, Any] | None = None,
) -> str:
    boundary = unit.get("boundary", {}) if isinstance(unit.get("boundary"), Mapping) else {}
    file_scope = ", ".join(str(path) for path in boundary.get("file_scope", []))
    do_not_touch = ", ".join(str(path) for path in boundary.get("do_not_touch", []))
    lines = [
        f"Work unit: {unit.get('title', unit.get('unit_id'))}",
        f"Overall goal: {goal_text.strip()}",
        f"Stay strictly inside these paths: {file_scope}.",
    ]
    if do_not_touch:
        lines.append(f"Do not touch: {do_not_touch} (owned by sibling units).")
    lines.append(f"Work on branch {unit.get('branch_suggestion', '')} in the current worktree.")
    # Goal echo-back, pre-declared completion criteria (absorbing the unit's
    # integration checks), bounded verification discipline, and — on
    # high-effort routes — the per-family over-verification calibration.
    lines.extend(unit_protocol_lines(unit))
    # Skills the operator actually has, named with the invocation form their
    # source directory implies. Absent discovery (the default, and every
    # zero-skill environment) leaves the prompt byte-identical.
    lines.extend(unit_skill_lines(unit, discovery))
    if unit_result_contract is not None:
        lines.extend(_unit_result_prompt_lines(unit_result_contract))
    # Unconditional shared-lane guidance: the same constant the capability
    # blocks carry, so the two prepared prompt lanes cannot drift, and the
    # no-discovery byte-identity contract stays intact (both sides gain it).
    lines.append(STRUCTURAL_SEARCH_GUIDANCE)
    lines.append("Commit your work; do not merge or push other branches.")
    return "\n".join(lines)


def _unit_result_prompt_lines(contract: Mapping[str, Any]) -> list[str]:
    """Executor-neutral, typed sidecar contract appended to a live unit prompt."""
    return [
        "Before exiting, write one fanout_unit_result/v1 JSON sidecar to exactly "
        f"{contract.get('path', '')}.",
        "Top-level fields: schema_version, unit_id, run_id, fanout_id, base_sha, head_sha, "
        "process_status, changed_paths, checks, findings, schema_error (optional).",
        "Use these dispatch-bound values: "
        f"schema_version=fanout_unit_result/v1, unit_id={contract.get('unit_id', '')}, "
        f"run_id={contract.get('run_id', '')}, fanout_id={contract.get('fanout_id', '')}, "
        f"base_sha={contract.get('base_sha', '')}; head_sha is the git HEAD you leave behind.",
        "Each checks row fields: command, status, evidence_ref, reported_by, observed_by, "
        "observation_source.",
        "For every executor-authored checks row, set reported_by=executor. observed_by and "
        "observation_source are dispatcher-owned; leave both null. Sidecar validation records "
        "only a report and never verification.",
    ]


# The one hedge every emitted sequence carries: declared-on-disk is not loaded,
# and a step the work does not need is droppable.
_SKILL_SEQUENCE_PREAMBLE = (
    "Suggested skill sequence for this unit, from what this environment declares. OMH read these "
    "definitions on disk; it did not load or verify them, so resolve each one in your own registry, "
    "skip any that does not resolve, and drop any step that does not fit the work:"
)
_DECLARED_SEQUENCE_PREAMBLE = (
    "Operator-declared skill sequence for this unit. Resolve each one in your own registry and skip "
    "any that does not resolve:"
)


def unit_skill_lines(unit: Mapping[str, Any], discovery: Mapping[str, Any] | None) -> list[str]:
    """Return the skill-sequence block for one unit, or an empty list.

    Precedence: an explicit `skill_sequence` on the unit always wins — a
    non-empty list renders verbatim (interview option 4), an empty list
    suppresses the block entirely (option 5, pure prompt). Otherwise the
    recommended sequence is arranged from discovery; and with no discovery or
    no matches the block is absent, so the modal operator — a fresh install
    with no executor skills — gets exactly the prompt they get today.
    """
    from .executor_skill_discovery import suggested_skill_sequence

    declared = unit.get("skill_sequence")
    if isinstance(declared, (list, tuple)):
        entries = [str(entry).strip() for entry in declared if str(entry).strip()]
        if not entries:
            return []
        steps = [f"{index}. `{entry}`" for index, entry in enumerate(entries, start=1)]
        return [_DECLARED_SEQUENCE_PREAMBLE, *steps]
    if not isinstance(discovery, Mapping):
        return []
    steps = [
        f"{index}. `{step['invocation']}` — {step['purpose']}"
        for index, step in enumerate(suggested_skill_sequence(discovery, _unit_role(unit)), start=1)
    ]
    if not steps:
        return []
    return [_SKILL_SEQUENCE_PREAMBLE, *steps]


def _unit_role(unit: Mapping[str, Any]) -> str:
    handoff = unit.get("handoff", {}) if isinstance(unit.get("handoff"), Mapping) else {}
    route = handoff.get("model_route") if isinstance(handoff.get("model_route"), Mapping) else {}
    return str(route.get("role", "") or "") if isinstance(route, Mapping) else ""


def _owner_skill_discoveries(
    units: Iterable[Mapping[str, Any]],
    project_root: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Observe declared skills once per distinct spawnable owner in this contract.

    Only owners that actually spawn are probed — a prepared-prompt fallback
    owner never reaches `build_unit_prompt`, so scanning for it would be IO
    nobody reads. `project_root` is the dispatch target repo, so repo-local
    `.claude/skills` definitions are discovered alongside the operator-level
    ones.
    """
    from .executor_skill_discovery import discovered_executor_skills

    owners = {
        str(unit.get("handoff", {}).get("executor_target", ""))
        for unit in units
        if isinstance(unit.get("handoff"), Mapping)
    }
    return {
        owner: discovered_executor_skills(owner, project_root=project_root)
        for owner in sorted(owners)
        if owner and DISPATCH_COMMAND_TEMPLATES.get(owner) is not None
    }


def verify_goal_matches_contract(contract: Mapping[str, Any], goal_text: str) -> None:
    """Refuse dispatch when the supplied goal diverges from the frozen contract.

    The contract stores the goal as a digest only (privacy); the operator
    re-supplies the text at dispatch time, so integrity must be re-proven.
    """
    from hashlib import sha256

    normalized = " ".join(goal_text.split())
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    expected = str(contract.get("goal", {}).get("sha256", ""))
    if digest != expected:
        raise ValueError(
            "goal text does not match the digest frozen in the fanout contract; "
            "dispatch refuses to run a diverged goal (re-run fanout prepare for a new goal)"
        )


def _live_safety_profile_revision() -> str | None:
    """The live safety-profile revision, or None when that lane is not installed."""
    try:
        from ..quality.safety_preflight import safety_profile_revision
    except ImportError:
        return None
    return safety_profile_revision()


def verify_safety_profile_matches_contract(contract: Mapping[str, Any], live_revision: str | None = None) -> None:
    """Refuse dispatch when the safety profile moved after the contract froze.

    The boundary re-check re-proves what the contract was prepared under; it does
    not re-decide it. It runs beside the goal-digest check and *before* any
    confirmation is requested, because a user who pays a prompt for work that
    then hard-fails on drift pays a second prompt on the retry.

    A contract that froze no revision is not gated at all. A contract that froze
    one in an environment that can no longer produce one refuses: an
    unprovable profile is drift, not a pass.
    """
    carried = str(contract.get("safety_profile_revision", "") or "")
    if not carried:
        return
    observed = live_revision if live_revision is not None else _live_safety_profile_revision()
    reason = recheck_safety_profile_revision(carried, observed)
    if reason:
        raise ValueError(
            f"{reason}; dispatch refuses to run under a drifted safety profile "
            "(re-run fanout prepare to refreeze the contract)"
        )


def _dispatch_status_ladder(
    *,
    process_succeeded: bool = False,
    result_schema_valid: bool = False,
    unit_verification_observed: bool = False,
    merge_order_position_satisfied: bool = False,
) -> dict[str, bool]:
    """Build the dispatch-only evidence ladder without inferring later rungs."""
    integration_ready = bool(
        process_succeeded
        and result_schema_valid
        and unit_verification_observed
        and merge_order_position_satisfied
    )
    return {
        "process_succeeded": bool(process_succeeded),
        "result_schema_valid": bool(result_schema_valid),
        "unit_verification_observed": bool(unit_verification_observed),
        "integration_ready": integration_ready,
    }


def _dispatch_capability_snapshot(
    paths: OmhPaths,
    handoff: Mapping[str, Any],
    owner: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    frozen_snapshot = handoff.get("executor_capability_snapshot")
    policy = handoff.get("executor_capability_snapshot_policy")
    if policy is not None and policy != "frozen_required":
        return None, ["executor_capability_snapshot_policy is unsupported"]
    if frozen_snapshot is None:
        return None, ["executor_capability_snapshot is required by this handoff"]
    if not isinstance(frozen_snapshot, Mapping):
        return None, ["executor_capability_snapshot must be a mapping"]
    if frozen_snapshot.get("executor") != owner:
        return None, ["executor_capability_snapshot executor does not match the handoff owner"]
    errors = validate_executor_capability_snapshot(frozen_snapshot)
    if errors:
        return None, errors
    return complete_executor_capability_snapshot(frozen_snapshot), []


def _unit_capability_precheck(
    paths: OmhPaths,
    unit: Mapping[str, Any],
    *,
    contract_schema_version: str,
) -> tuple[str, dict[str, Any] | None, list[str]]:
    declared_owner = str(unit.get("owner") or "choose")
    handoff = unit.get("handoff", {}) if isinstance(unit.get("handoff"), Mapping) else {}
    handoff_owner = str(handoff.get("executor_target", "choose"))
    if handoff_owner != declared_owner:
        return declared_owner, None, ["unit owner does not match the handoff owner"]
    if declared_owner == "choose":
        return declared_owner, {}, []
    if (
        contract_schema_version == FANOUT_CONTRACT_SCHEMA_VERSION
        and declared_owner != "choose"
    ):
        if handoff.get("executor_capability_snapshot_policy") != "frozen_required":
            return declared_owner, None, [
                "executor_capability_snapshot_policy must be frozen_required"
            ]
        if "executor_capability_snapshot" not in handoff:
            return declared_owner, None, [
                "executor_capability_snapshot is required by this contract"
            ]
    snapshot, errors = _dispatch_capability_snapshot(paths, handoff, declared_owner)
    return declared_owner, snapshot, errors


def fanout_dispatch_preflight(
    paths: OmhPaths,
    contract: Mapping[str, Any],
    *,
    only_units: Sequence[str] | None = None,
    goal_text: str | None = None,
    live_safety_profile_revision: str | None = None,
) -> dict[str, Any]:
    """Validate persisted dispatch identity before any local tool activity."""
    if goal_text is not None:
        verify_goal_matches_contract(contract, goal_text)
        verify_safety_profile_matches_contract(
            contract,
            live_safety_profile_revision,
        )
    schema_version = str(contract.get("schema_version", ""))
    if schema_version == LEGACY_FANOUT_CONTRACT_SCHEMA_VERSION:
        raise ValueError(
            "fanout_contract/v1 must be migrated with "
            "'omh coding fanout migrate-legacy' before dispatch"
        )
    if schema_version != FANOUT_CONTRACT_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported fanout contract schema_version: {schema_version or 'missing'}"
        )
    raw_units = contract.get("units")
    if not isinstance(raw_units, list) or not all(
        isinstance(unit, Mapping) for unit in raw_units
    ):
        raise ValueError("fanout contract units must be a list of objects")
    unit_ids = [str(unit.get("unit_id", "")) for unit in raw_units]
    if any(not unit_id for unit_id in unit_ids) or len(set(unit_ids)) != len(unit_ids):
        raise ValueError("fanout contract unit ids must be nonempty and unique")
    units = {unit_id: unit for unit_id, unit in zip(unit_ids, raw_units, strict=True)}
    merge_plan = contract.get("merge_plan")
    raw_order = merge_plan.get("merge_order") if isinstance(merge_plan, Mapping) else None
    if not isinstance(raw_order, list) or not all(
        isinstance(unit_id, str) for unit_id in raw_order
    ):
        raise ValueError("fanout contract merge_order must be a list of unit ids")
    order = list(raw_order)
    if len(set(order)) != len(order) or set(order) != set(units):
        raise ValueError("fanout contract merge_order must name every unit exactly once")
    selected = set(only_units) if only_units else set(order)
    unknown_selected = sorted(selected - set(units))
    if unknown_selected:
        raise ValueError(
            "selected fanout units are not in the contract: "
            + ", ".join(unknown_selected)
        )
    capability_prechecks = {
        unit_id: _unit_capability_precheck(
            paths,
            unit,
            contract_schema_version=schema_version,
        )
        for unit_id, unit in units.items()
    }
    invalid_selected = [
        unit_id
        for unit_id in order
        if unit_id in selected and capability_prechecks[unit_id][2]
    ]
    return {
        "schema_version": schema_version,
        "units": units,
        "order": order,
        "selected": selected,
        "capability_prechecks": capability_prechecks,
        "invalid_selected": invalid_selected,
    }


def _apply_integration_readiness(units: Sequence[dict[str, Any]]) -> None:
    """Fold integration eligibility in declared merge order."""
    merge_order_position_satisfied = True
    for entry in units:
        ladder = _dispatch_status_ladder(
            process_succeeded=bool(entry.get("process_succeeded")),
            result_schema_valid=bool(entry.get("result_schema_valid")),
            unit_verification_observed=bool(entry.get("unit_verification_observed")),
            merge_order_position_satisfied=merge_order_position_satisfied,
        )
        entry.update(ladder)
        # A later unit cannot become eligible ahead of an earlier unit whose
        # complete dispatcher-observed evidence chain is still missing.
        merge_order_position_satisfied = ladder["integration_ready"]


def _unit_verification_is_observed(paths: OmhPaths, run_ref: str) -> bool:
    """Project the complete journal so an old receipt cannot fall off a tail."""
    from ..workflows.observation_journal import project_run_lifecycle, read_observation_events

    try:
        events = read_observation_events(paths, run_id=run_ref, limit=None)
    except (OSError, ValueError, KeyError):
        return False
    projection = project_run_lifecycle(events, run_id=run_ref)
    return bool(projection.get("unit_verification_observed"))


def declared_verification_commands(unit: Mapping[str, Any]) -> list[str]:
    """The runnable commands one contract unit declares, or an empty list."""
    declared = unit.get("verification_commands")
    if not isinstance(declared, (list, tuple)):
        return []
    return [str(entry).strip() for entry in declared if str(entry).strip()]


def _run_verification_command(
    command: str,
    worktree: Path,
    runner: Callable[..., Any],
) -> tuple[str, str]:
    """Run one command in the unit worktree; return its status and a bounded tail.

    Never raises: a command that cannot start is a failed check, not a failed
    dispatch. `shell=False`, so the argv comes from the contract's own frozen
    split and nothing in the command string is reinterpreted here.
    """
    try:
        env_overrides, argv = verification_command_argv(command)
    except FanoutContractError as exc:
        return "failed", str(exc)
    try:
        completed = runner(
            argv,
            cwd=str(worktree),
            env={**os.environ, **env_overrides},
            text=True,
            capture_output=True,
            timeout=_VERIFICATION_COMMAND_TIMEOUT,
        )
        exit_code = int(getattr(completed, "returncode", 1))
        combined = (
            f"{getattr(completed, 'stdout', '') or ''}{getattr(completed, 'stderr', '') or ''}"
        )
    except FileNotFoundError:
        return "failed", f"{argv[0]} not found on PATH"
    except subprocess.TimeoutExpired:
        return "failed", f"timed out after {_VERIFICATION_COMMAND_TIMEOUT}s"
    except (OSError, subprocess.SubprocessError, TypeError, ValueError) as exc:
        return "failed", f"could not run: {exc}"
    if exit_code == 0:
        return "passed", ""
    tail = redact_metadata_text(
        combined[-_MAX_VERIFICATION_OUTPUT_TAIL:], limit=_MAX_VERIFICATION_OUTPUT_TAIL
    )
    return "failed", f"exit {exit_code}: {tail}"


def _run_unit_verification(
    paths: OmhPaths,
    unit: Mapping[str, Any],
    *,
    run_ref: str,
    unit_id: str,
    worktree: Path,
    owner: str,
    runner: Callable[..., Any],
) -> dict[str, Any]:
    """Run one unit's declared verification commands and record what was observed.

    Every row is dispatcher-reported AND dispatcher-observed: omh ran the
    command itself, which is the only way the result schema allows an
    observation to be claimed. All rows passing is what appends the per-unit
    `unit_verification_observed` journal event, so the ladder flips from the
    same evidence an operator would otherwise record by hand. Any failure
    appends nothing, leaving the unit short of `integration_ready`.
    """
    commands = declared_verification_commands(unit)
    if not commands:
        return {}
    rows: list[dict[str, object]] = []
    failures: list[str] = []
    for command in commands:
        status, detail = _run_verification_command(command, worktree, runner)
        rows.append(
            {
                "command": command,
                "status": status,
                "evidence_ref": f"journal:{UNIT_VERIFICATION_OBSERVATION_SOURCE}:{run_ref}",
                "reported_by": "dispatcher",
                "observed_by": "dispatcher",
                "observation_source": UNIT_VERIFICATION_OBSERVATION_SOURCE,
            }
        )
        if status != "passed":
            failures.append(f"{command}: {detail}")
    # Through the shared validator, not beside it: rows omh writes about itself
    # are held to the schema every executor-written row goes through.
    validated_rows = validate_check_rows(rows)
    if not failures:
        append_journal_observation(
            paths,
            {
                "target_type": "run",
                "target_id": run_ref,
                "run_id": run_ref,
                "event": "unit_verification_observed",
                "status": "observed",
                "summary": (
                    f"dispatcher ran {len(validated_rows)} declared verification command(s) "
                    f"for unit {unit_id}; all passed"
                ),
                "worker_ref": unit_id,
                "worktree_ref": str(worktree),
                "runtime_profile": owner,
            },
        )
    verification: dict[str, Any] = {
        "verification_status": "failed" if failures else "passed",
        "verification_checks": validated_rows,
        "verification_claim_boundary": UNIT_VERIFICATION_CLAIM_BOUNDARY,
    }
    if failures:
        verification["verification_failures"] = failures
    return verification


def dispatch_fanout(
    paths: OmhPaths,
    contract: Mapping[str, Any],
    *,
    goal_text: str,
    repo_root: Path,
    base_sha: str,
    source_ref: str = "",
    concurrency: int = 2,
    timeout: int = 1800,
    only_units: Sequence[str] | None = None,
    dry_run: bool = False,
    run_verification: bool = False,
    runner: Callable[..., Any] = subprocess.run,
    readiness: Callable[..., dict[str, object]] = probe_executor_readiness,
    live_safety_profile_revision: str | None = None,
) -> dict[str, Any]:
    # Both boundary re-checks run first, before discovery, readiness probing,
    # any unit spawn, and any summary write: nothing downstream should observe a
    # contract whose goal or safety profile no longer matches the live state.
    verify_goal_matches_contract(contract, goal_text)
    verify_safety_profile_matches_contract(contract, live_safety_profile_revision)
    preflight = fanout_dispatch_preflight(
        paths,
        contract,
        only_units=only_units,
        goal_text=goal_text,
        live_safety_profile_revision=live_safety_profile_revision,
    )
    units = preflight["units"]
    order = preflight["order"]
    selected = preflight["selected"]
    capability_prechecks = preflight["capability_prechecks"]
    invalid_units = preflight["invalid_selected"]
    selected_capability_invalid = bool(invalid_units)
    capability_valid_units = [
        unit
        for unit_id, unit in units.items()
        if capability_prechecks[unit_id][1] is not None
        and not capability_prechecks[unit_id][2]
    ]
    current_catalog_digest = (
        ""
        if selected_capability_invalid
        else _current_catalog_digest(capability_valid_units)
    )
    # Resolved up here rather than beside the summary write below: the dispatch
    # loop needs it to write per-unit in-flight markers while units are running.
    fanout_id = str(contract.get("fanout_id", "") or "")
    # Observed once per distinct owner, here at the dispatch boundary rather
    # than inside the prompt builder: `build_unit_prompt` stays a pure function
    # of its arguments, so a prompt built without discovery is byte-identical
    # across machines.
    discoveries = (
        {}
        if selected_capability_invalid
        else _owner_skill_discoveries(capability_valid_units, project_root=repo_root)
    )
    results: dict[str, dict[str, Any]] = {}

    if selected_capability_invalid:
        invalid_reason = (
            "selected batch refused because capability evidence is invalid for "
            + ", ".join(invalid_units)
        )
        for unit_id in order:
            unit = units[unit_id]
            if _already_completed(paths, unit):
                results[unit_id] = _skipped(
                    unit,
                    "already_completed",
                    process_succeeded=True,
                    unit_verification_observed=_unit_verification_is_observed(
                        paths, str(unit.get("run_ref", unit_id))
                    ),
                )
                continue
            if unit_id not in selected:
                results[unit_id] = _skipped(unit, "not_selected")
                continue
            owner, _snapshot, errors = capability_prechecks[unit_id]
            if errors:
                results[unit_id] = {
                    "unit_id": unit_id,
                    "run_ref": str(unit.get("run_ref", unit_id)),
                    "owner": owner,
                    "status": "capability_snapshot_invalid",
                    **_dispatch_status_ladder(),
                    "reason": "; ".join(errors),
                }
            elif any(
                _dependency_failed(results.get(str(dependency)))
                for dependency in unit.get("depends_on", []) or []
            ):
                results[unit_id] = _blocked(unit, results)
            else:
                results[unit_id] = {
                    "unit_id": unit_id,
                    "run_ref": str(unit.get("run_ref", unit_id)),
                    "owner": owner,
                    "status": "capability_snapshot_invalid",
                    **_dispatch_status_ladder(),
                    "reason": invalid_reason,
                }

    for unit_id in order if not selected_capability_invalid else ():
        unit = units[unit_id]
        if _already_completed(paths, unit):
            # Completed units satisfy dependencies whether or not they are in
            # the current selection, so partial re-dispatch of downstream
            # units works after an earlier run (or manual recovery) finished
            # their prerequisites.
            results[unit_id] = _skipped(
                unit,
                "already_completed",
                process_succeeded=True,
                unit_verification_observed=_unit_verification_is_observed(
                    paths, str(unit.get("run_ref", unit_id))
                ),
            )
        elif unit_id not in selected:
            results[unit_id] = _skipped(unit, "not_selected")

    pending = [unit_id for unit_id in order if unit_id not in results]
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        while pending:
            ready = [
                unit_id
                for unit_id in pending
                if all(_dependency_satisfied(results.get(dep)) for dep in units[unit_id].get("depends_on", []))
            ]
            blocked = [
                unit_id
                for unit_id in pending
                if any(_dependency_failed(results.get(dep)) for dep in units[unit_id].get("depends_on", []))
            ]
            for unit_id in blocked:
                results[unit_id] = _blocked(units[unit_id], results)
                pending.remove(unit_id)
            ready = [unit_id for unit_id in ready if unit_id in pending]
            if not ready:
                if pending and not blocked:
                    for unit_id in list(pending):
                        results[unit_id] = _blocked(units[unit_id], results)
                        pending.remove(unit_id)
                continue
            futures = {
                unit_id: pool.submit(
                    _dispatch_unit,
                    paths,
                    units[unit_id],
                    goal_text=goal_text,
                    repo_root=repo_root,
                    base_sha=base_sha,
                    source_ref=source_ref,
                    timeout=timeout,
                    dry_run=dry_run,
                    run_verification=run_verification,
                    runner=runner,
                    readiness=readiness,
                    current_catalog_digest=current_catalog_digest,
                    fanout_id=fanout_id,
                    discoveries=discoveries,
                    capability_precheck=capability_prechecks[unit_id],
                )
                for unit_id in ready
            }
            for unit_id, future in futures.items():
                results[unit_id] = future.result()
                pending.remove(unit_id)

    summary_units = [results[unit_id] for unit_id in order]
    _apply_integration_readiness(summary_units)
    summary = {
        "schema_version": FANOUT_DISPATCH_SCHEMA_VERSION,
        "fanout_id": contract.get("fanout_id", ""),
        "dry_run": dry_run,
        "observed_at": utc_now(),
        "merge_order": order,
        "units": summary_units,
        "integration_ready_units": [
            entry["unit_id"] for entry in summary_units if entry.get("integration_ready")
        ],
        # The counterpart to process success: units that failed but left work worth
        # looking at before anyone re-runs them from scratch.
        "recovery_available_units": _recovery_available(summary_units),
        "auto_merge": False,
        "dependency_bar": (
            "A satisfied dependency means only that the owner agent process exited 0. "
            "It is not verified, reviewed, or correct work."
        ),
        "base_sha": base_sha,
        "claim_boundary": f"{DISPATCH_CLAIM_BOUNDARY} {FANOUT_CLAIM_BOUNDARY}",
    }
    if not dry_run and fanout_id:
        from .fanout_artifacts import fanout_dispatch_summary_path

        # Metadata-only persistence so `omh coding fanout brief` can join
        # observed telemetry without replaying the journal. The validated
        # helper re-checks the id pattern and containment because this
        # fanout_id comes from the contract body, not the CLI argument.
        # Per-unit entries merge with the stored summary so a partial
        # re-dispatch (`--unit b`) does not erase unit a's observed telemetry
        # with a skipped placeholder.
        summary_path = fanout_dispatch_summary_path(paths, fanout_id)
        stored = _merged_dispatch_summary(summary_path, summary)
        atomic_write_json(summary_path, stored, private=True)
        # The CLI prints what this returns, so the rollups it carries have to
        # agree with the file just written — an operator who re-ran one unit
        # was being told nothing was salvageable while the stored summary said
        # otherwise. Only the rollups and the carried-forward `recovery` are
        # taken from the merged view: per-unit `status` stays THIS run's answer,
        # so `already_completed` still means "I did not re-run this".
        summary["units"] = _with_carried_recovery(summary["units"], stored.get("units", []))
        summary["recovery_available_units"] = _recovery_available(summary["units"])
    return summary


def _with_carried_recovery(
    units: list[dict[str, Any]],
    merged_units: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """This run's entries, plus the recovery a unit that did not re-run still has."""
    merged_by_id = {str(entry.get("unit_id", "")): entry for entry in merged_units if isinstance(entry, Mapping)}
    carried: list[dict[str, Any]] = []
    for entry in units:
        merged = merged_by_id.get(str(entry.get("unit_id", "")))
        if "recovery" not in entry and isinstance(merged, Mapping) and isinstance(merged.get("recovery"), Mapping):
            carried.append({**entry, "recovery": dict(merged["recovery"])})
        else:
            carried.append(entry)
    return carried


def _recovery_available(units: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        str(entry.get("unit_id"))
        for entry in units
        if isinstance(entry, Mapping)
        and isinstance(entry.get("recovery"), Mapping)
        and entry["recovery"].get("outcome") == "recovery_available"
    ]


_DISPATCH_SKIP_STATUSES = frozenset({"already_completed", "not_selected"})


def _merged_dispatch_summary(summary_path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    from ..system.local_store import read_json_object_result

    previous, _error = read_json_object_result(summary_path)
    previous_units = {
        str(entry.get("unit_id", "")): entry
        for entry in (previous or {}).get("units", [])
        if isinstance(entry, dict)
    }
    merged_units = []
    for entry in summary.get("units", []):
        if not isinstance(entry, dict):
            continue
        unit_id = str(entry.get("unit_id", ""))
        earlier = previous_units.get(unit_id)
        if entry.get("status") in _DISPATCH_SKIP_STATUSES and isinstance(earlier, dict):
            # A skipped unit carries no telemetry; the earlier observed entry
            # is the richer record and stays.
            merged_units.append(earlier)
        elif (
            isinstance(earlier, dict)
            and "recovery" in earlier
            and "recovery" not in entry
            and "exit_code" not in entry
        ):
            # The unit did not actually re-run: no exit code means no spawn, so
            # statuses like `worktree_failed` or `executor_not_ready` say
            # nothing about what the earlier attempt left behind. Carrying the
            # earlier recovery forward keeps a salvageable unit from vanishing
            # from the rollup while its record is still on disk. A unit that
            # DID run replaces the answer, which is how a later success clears
            # a stale one.
            merged_units.append({**entry, "recovery": earlier["recovery"]})
        else:
            merged_units.append(entry)
    _apply_integration_readiness(merged_units)
    merged = dict(summary)
    merged["units"] = merged_units
    merged["integration_ready_units"] = [
        str(entry.get("unit_id"))
        for entry in merged_units
        if isinstance(entry, dict) and entry.get("integration_ready")
    ]
    # Recomputed for the same reason integration_ready_units is: the current run's
    # rollup only names units it dispatched, so carrying it through unchanged
    # would erase an earlier run's salvageable unit from the one field an
    # operator reads first — while that unit's own `recovery` record, merged
    # just above, still says otherwise.
    merged["recovery_available_units"] = _recovery_available(merged_units)
    return merged


def _current_catalog_digest(units: Iterable[Mapping[str, Any]]) -> str:
    """Observe the current local-catalog digest once per dispatch, and only
    when some unit's frozen route actually carries a catalog fingerprint —
    contracts routed purely from built-in catalogs never trigger the read."""
    for unit in units:
        handoff = unit.get("handoff", {}) if isinstance(unit.get("handoff"), Mapping) else {}
        route = handoff.get("model_route")
        if isinstance(route, Mapping) and isinstance(route.get("catalog_fingerprint"), Mapping):
            break
    else:
        return ""
    from .model_inventory import inventory_model_catalog, local_model_inventory

    catalog = inventory_model_catalog(local_model_inventory())
    if not isinstance(catalog, Mapping):
        return ""
    fingerprint = catalog.get("fingerprint")
    return str(fingerprint.get("digest", "") or "") if isinstance(fingerprint, Mapping) else ""


# Telemetry keys copied onto a dispatch result. `parse_unit_telemetry` also
# returns schema/owner/parsed/source, which describe the READING rather than the
# unit, and would be noise on every row of the summary.
_TELEMETRY_RESULT_KEYS: tuple[str, ...] = (
    "tokens_total",
    "tokens_billable",
    "tokens_billable_source",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "session_ref",
)


def _write_inflight(paths: OmhPaths, fanout_id: str, unit_id: str, fields: dict[str, str]) -> None:
    """Best-effort marker write. Observability must never fail a dispatch."""
    if not fanout_id:
        return
    try:
        write_inflight_marker(paths, fanout_id, unit_id, fields)
    except (InflightMarkerError, OSError):
        return


def _clear_inflight(paths: OmhPaths, fanout_id: str, unit_id: str) -> None:
    """Runs inside `finally`, so it must never mask the dispatch exception."""
    if not fanout_id:
        return
    try:
        clear_inflight_marker(paths, fanout_id, unit_id)
    except (InflightMarkerError, OSError):
        return


def _dispatch_unit(
    paths: OmhPaths,
    unit: Mapping[str, Any],
    *,
    goal_text: str,
    repo_root: Path,
    base_sha: str,
    timeout: int,
    dry_run: bool,
    run_verification: bool = False,
    source_ref: str = "",
    runner: Callable[..., Any],
    readiness: Callable[..., dict[str, object]],
    current_catalog_digest: str = "",
    fanout_id: str = "",
    discoveries: Mapping[str, Mapping[str, Any]] | None = None,
    capability_precheck: tuple[str, dict[str, Any] | None, list[str]],
) -> dict[str, Any]:
    from .model_inventory import catalog_fingerprint_note

    unit_id = str(unit["unit_id"])
    run_ref = str(unit.get("run_ref", unit_id))
    handoff = unit.get("handoff", {}) if isinstance(unit.get("handoff"), Mapping) else {}
    owner, capability_snapshot, capability_errors = capability_precheck
    if capability_errors or capability_snapshot is None:
        return {
            "unit_id": unit_id,
            "run_ref": run_ref,
            "owner": owner,
            "status": "capability_snapshot_invalid",
            **_dispatch_status_ladder(),
            "reason": "; ".join(capability_errors),
        }
    model_route = handoff.get("model_route") if isinstance(handoff.get("model_route"), Mapping) else None
    routed_model = str(model_route.get("selected_model", "") or "") if model_route else ""
    routed_effort = str(model_route.get("selected_reasoning_effort", "") or "") if model_route else ""
    fingerprint_note = catalog_fingerprint_note(model_route, current_catalog_digest)
    if model_route is not None and str(model_route.get("status", "")) == "choice_required":
        # A frozen choice_required route means the contract explicitly says
        # "a human or wrapper must pick the model". Spawning anyway would
        # silently substitute the executor CLI default for a choice the
        # contract reserved — fail closed and name the unresolved choice
        # instead. Recovery: re-prepare the unit with an explicit `model`
        # (or a role that resolves), then re-run dispatch for this unit.
        return {
            "unit_id": unit_id,
            "run_ref": run_ref,
            "owner": owner,
            "status": "model_choice_required",
            **_dispatch_status_ladder(),
            "reason": (
                "the frozen route requires an explicit model choice; re-prepare the unit with a "
                "declared model or resolvable role, then re-dispatch"
            ),
        }
    if DISPATCH_COMMAND_TEMPLATES.get(owner) is None:
        return {
            "unit_id": unit_id,
            "run_ref": run_ref,
            "owner": owner,
            "status": "unsupported_for_local_dispatch",
            **_dispatch_status_ladder(),
            "fallback": "use the unit handoff as a prepared prompt for this owner",
        }
    probe = readiness(paths, owner)
    if str(probe.get("status", "")) != "ready":
        # The pre-handoff recheck (#837) can turn a once-ready owner into
        # `stale` right here. Carrying its repair card through means the unit
        # result names the prerequisite that moved and the command that
        # confirms it, instead of only reporting that the owner was not ready.
        not_ready: dict[str, Any] = {
            "unit_id": unit_id,
            "run_ref": run_ref,
            "owner": owner,
            "status": "executor_not_ready",
            "readiness_status": str(probe.get("status", "unknown")),
            **_dispatch_status_ladder(),
        }
        repair_card = probe.get("repair_card")
        if isinstance(repair_card, Mapping):
            not_ready["repair_card"] = dict(repair_card)
        return not_ready
    discovery = (discoveries or {}).get(owner)
    sidecar_path = None
    if fanout_id:
        from .fanout_artifacts import unit_result_path

        sidecar_path = unit_result_path(paths, fanout_id, unit_id)
    prompt = build_unit_prompt(
        unit,
        goal_text,
        discovery,
        unit_result_contract=(
            {
                "path": str(sidecar_path),
                "unit_id": unit_id,
                "run_id": run_ref,
                "fanout_id": fanout_id,
                "base_sha": base_sha,
            }
            if sidecar_path is not None
            else None
        ),
    )
    argv = build_dispatch_argv(owner, prompt, model_route)
    worktree = _worktree_path(repo_root, unit_id)
    if dry_run:
        from .executor_skill_discovery import skill_selection_card, suggested_skill_sequence

        planned: dict[str, Any] = {
            "unit_id": unit_id,
            "run_ref": run_ref,
            "owner": owner,
            "model": routed_model,
            "status": "dry_run_planned",
            "planned_argv": [part if part != prompt else "<unit prompt>" for part in argv],
            "worktree_path": str(worktree),
            **_dispatch_status_ladder(),
        }
        if fingerprint_note is not None:
            planned["inventory_fingerprint"] = fingerprint_note
        # Only when the operator asked for verification: a plan that named
        # commands nothing was going to run would read as a promise.
        if run_verification:
            declared_commands = declared_verification_commands(unit)
            if declared_commands:
                planned["planned_verification_commands"] = declared_commands
        # The deep-interview surface: when the unit has not answered (no
        # declared skill_sequence) and the environment offers a genuine
        # arrangement choice, the dry run carries the question card so a
        # wrapper can double-check with the user before live dispatch. Live
        # dispatch never blocks on it — unanswered means option 1.
        declared = unit.get("skill_sequence")
        if isinstance(declared, (list, tuple)):
            planned["skill_sequence_source"] = "declared" if any(str(v).strip() for v in declared) else "declared_none"
        else:
            card = skill_selection_card(discovery, _unit_role(unit))
            if card is not None:
                planned["skill_sequence_source"] = "auto_recommended"
                planned["skill_selection"] = card
            else:
                auto_steps = suggested_skill_sequence(discovery, _unit_role(unit))
                if auto_steps:
                    planned["skill_sequence_source"] = "auto"
                    # Name the sequence that will actually ride the prompt:
                    # "auto" alone told the operator a skill was chosen
                    # without saying which one.
                    planned["skill_sequence"] = [str(step["invocation"]) for step in auto_steps]
                else:
                    planned["skill_sequence_source"] = "none"
        return planned
    from .worktree_creator import ensure_fanout_unit_worktree

    worktree_record = ensure_fanout_unit_worktree(
        paths,
        repo_root=repo_root,
        unit_id=unit_id,
        branch=str(unit.get("branch_suggestion", f"agent/{unit_id}")),
        base_sha=base_sha,
        source_ref=source_ref,
        run_ref=run_ref,
        runner=runner,
    )
    if not worktree_record.get("created"):
        return {
            "unit_id": unit_id,
            "run_ref": run_ref,
            "owner": owner,
            "status": "worktree_failed",
            "refusal": str(worktree_record.get("refusal", "")),
            "reason": str(worktree_record.get("reason", "")),
            **_dispatch_status_ladder(),
        }
    worktree = Path(str(worktree_record["worktree_path"]))
    if fanout_id:
        # Before the spawn, like the in-flight marker below. A record from an
        # earlier attempt describes a worktree that has just been rebuilt from
        # base, so leaving it would advertise a stale digest and a recover_with
        # pointing at work that no longer exists. If this run also fails, the
        # probe writes a fresh one.
        from .fanout_artifacts import clear_fanout_unit_recovery

        clear_fanout_unit_recovery(paths, fanout_id, unit_id)
    if sidecar_path is not None:
        # A re-dispatch must never consume an earlier attempt's report. Create
        # only the managed parent; the executor owns the sidecar write itself.
        ensure_dir(sidecar_path.parent, private=True)
        sidecar_path.unlink(missing_ok=True)
    _ensure_unit_run(paths, unit, owner)
    append_journal_observation(
        paths,
        {
            "target_type": "run",
            "target_id": run_ref,
            "run_id": run_ref,
            "event": "worker_dispatch",
            "status": "observed",
            "summary": f"local dispatch of unit {unit_id} to {owner}",
            "worker_ref": unit_id,
            "worktree_ref": str(worktree),
            # The schema has carried this field all along and nothing set it,
            # so the runtime name survived only inside free-text `summary`.
            "runtime_profile": owner,
        },
    )
    started_at = utc_now()
    started_clock = time.monotonic()
    stderr_tail = ""
    stdout_text = ""
    owner_host = omo_runtime_host() or "" if owner == "omo-runtime" else ""
    # Written BEFORE the spawn and cleared in `finally`. This call blocks for
    # the whole unit, so the dispatching process cannot report on itself; the
    # marker is what lets ANOTHER session see that this unit is running and
    # compute its elapsed time. Marker failures never block a dispatch.
    _write_inflight(
        paths,
        fanout_id,
        unit_id,
        {
            "owner": owner,
            "owner_host": owner_host,
            "model": routed_model,
            "reasoning_effort": routed_effort,
            "run_ref": run_ref,
            "worktree": str(worktree),
            "started_at": started_at,
        },
    )
    try:
        completed = runner(argv, cwd=str(worktree), text=True, capture_output=True, timeout=timeout)
        exit_code = int(getattr(completed, "returncode", 1))
        stdout_text = str(getattr(completed, "stdout", "") or "")
        output_tail = stdout_text[-2000:]
        stderr_tail = str(getattr(completed, "stderr", "") or "")[-2000:]
    except FileNotFoundError:
        exit_code, output_tail = 127, f"{argv[0]} not found on PATH"
    except subprocess.TimeoutExpired:
        exit_code, output_tail = 124, f"unit timed out after {timeout}s"
    except OSError as exc:
        exit_code, output_tail = 1, f"spawn failed: {exc}"
    finally:
        _clear_inflight(paths, fanout_id, unit_id)
    finished_at = utc_now()
    duration_seconds = round(time.monotonic() - started_clock, 3)
    limit_label = _limit_shaped_label(output_tail, stderr_tail) if exit_code != 0 else ""
    if limit_label:
        _record_limit_signal(paths, owner, run_ref=run_ref, unit_id=unit_id, pattern_label=limit_label)
    elif exit_code == 0:
        # A successful dispatch to this executor is the freshest evidence the
        # provider is serving it again; a stale limit signal must not keep
        # down-ranking the executor forever.
        _clear_limit_signal(paths, owner)
    status = "observed" if exit_code == 0 else "failed"
    summary = (
        f"unit {unit_id} exit {exit_code} after {duration_seconds}s: "
        f"{redact_metadata_text(output_tail[-300:], limit=300)}"
    )
    if limit_label:
        summary = f"limit-shaped failure ({limit_label}); {summary}"
    append_journal_observation(
        paths,
        {
            "target_type": "run",
            "target_id": run_ref,
            "run_id": run_ref,
            "event": "worker_result",
            "status": status,
            "summary": summary,
            "worker_ref": unit_id,
            "worktree_ref": str(worktree),
            "runtime_profile": owner,
        },
    )
    unit_result = _intake_unit_result(
        paths,
        sidecar_path=sidecar_path,
        run_ref=run_ref,
        unit_id=unit_id,
        fanout_id=fanout_id,
        base_sha=base_sha,
        worktree=worktree,
        owner=owner,
    )
    # Both rungs below it must already hold: a unit whose process failed has
    # nothing to verify, and one whose sidecar did not validate has not yet
    # reported what it did. Runs before the ladder is built, so the journal
    # event it may append is visible to `_unit_verification_is_observed`.
    verification: dict[str, Any] = {}
    if run_verification and exit_code == 0 and unit_result.get("result_schema_valid"):
        verification = _run_unit_verification(
            paths,
            unit,
            run_ref=run_ref,
            unit_id=unit_id,
            worktree=worktree,
            owner=owner,
            runner=runner,
        )
    result = {
        "unit_id": unit_id,
        "run_ref": run_ref,
        "owner": owner,
        "model": routed_model,
        "reasoning_effort": routed_effort,
        "status": "completed" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "worktree_path": str(worktree),
        **_dispatch_status_ladder(
            process_succeeded=exit_code == 0,
            result_schema_valid=bool(unit_result.get("result_schema_valid")),
            unit_verification_observed=_unit_verification_is_observed(paths, run_ref),
        ),
        **unit_result,
        **verification,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
    }
    if owner_host:
        result["owner_host"] = owner_host
    result["executor_capability_snapshot"] = capability_snapshot
    result["executor_capability"] = legacy_executor_capability_projection(capability_snapshot)
    # `tokens_total` and `session_ref` were READ by `omh coding fanout brief`
    # and had no write site anywhere, so both columns always printed "unknown".
    # Only keys the executor actually reported are copied: an absent count stays
    # absent rather than becoming a zero that would read as an observation.
    for key, value in parse_unit_telemetry(owner, stdout_text).items():
        if key in _TELEMETRY_RESULT_KEYS:
            result[key] = value
    if fingerprint_note is not None:
        result["inventory_fingerprint"] = fingerprint_note
    if limit_label:
        result["limit_shaped"] = True
        result["limit_pattern"] = limit_label
    if exit_code != 0:
        # A failed unit still owns its worktree, and whatever it managed to
        # write is the only thing standing between the operator and redoing
        # the work. Capture what survived before the summary claims the unit
        # produced nothing.
        recovery = _capture_unit_recovery(
            paths,
            fanout_id=fanout_id,
            unit_id=unit_id,
            worktree=worktree,
            base_sha=base_sha,
            runner=runner,
        )
        if recovery is not None:
            result["recovery"] = recovery
    return result


_UNIT_RESULT_TOP_LEVEL_KEYS = (
    "schema_version",
    "unit_id",
    "run_id",
    "fanout_id",
    "base_sha",
    "head_sha",
    "process_status",
)
_UNIT_RESULT_CHECK_KEYS = (
    "command",
    "status",
    "evidence_ref",
    "reported_by",
    "observed_by",
    "observation_source",
)
_MAX_UNIT_RESULT_PATHS = 100
_MAX_UNIT_RESULT_CHECKS = 50
_MAX_UNIT_RESULT_FINDINGS = 20
_MAX_UNIT_RESULT_TEXT = 300


def _intake_unit_result(
    paths: OmhPaths,
    *,
    sidecar_path: Path | None,
    run_ref: str,
    unit_id: str,
    fanout_id: str,
    base_sha: str,
    worktree: Path,
    owner: str,
) -> dict[str, Any]:
    """Read one sidecar after process exit and classify shape, never truth."""
    if sidecar_path is None or not sidecar_path.is_file():
        return _unit_result_failure(
            paths,
            event="unit_result_missing",
            reason="sidecar is missing",
            sidecar_path=None,
            run_ref=run_ref,
            unit_id=unit_id,
            worktree=worktree,
            owner=owner,
        )
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        if isinstance(payload, Mapping):
            # Enforce executor provenance before the general shape validator,
            # so even an internally inconsistent laundering attempt receives
            # the intake contract's stable checks[i].reported_by error.
            _validate_executor_sidecar_checks(payload)
        validated = validate_unit_result(payload)
        _validate_unit_result_identity(
            validated,
            unit_id=unit_id,
            run_ref=run_ref,
            fanout_id=fanout_id,
            base_sha=base_sha,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        return _unit_result_failure(
            paths,
            event="unit_result_invalid",
            reason=str(exc),
            sidecar_path=sidecar_path,
            run_ref=run_ref,
            unit_id=unit_id,
            worktree=worktree,
            owner=owner,
        )

    append_journal_observation(
        paths,
        {
            "target_type": "run",
            "target_id": run_ref,
            "run_id": run_ref,
            "event": "unit_result_validated",
            "status": "observed",
            "summary": f"fanout unit result shape validated for {unit_id}",
            "worker_ref": unit_id,
            "worktree_ref": str(worktree),
            "runtime_profile": owner,
            "evidence_refs": [str(sidecar_path)],
        },
    )
    return {
        "unit_result_status": "unit_result_validated",
        "result_schema_valid": True,
        "unit_result": _bounded_unit_result(validated),
    }


def _validate_unit_result_identity(
    validated: Mapping[str, Any],
    *,
    unit_id: str,
    run_ref: str,
    fanout_id: str,
    base_sha: str,
) -> None:
    expected = {
        "unit_id": unit_id,
        "run_id": run_ref,
        "fanout_id": fanout_id,
        "base_sha": base_sha,
    }
    for field, expected_value in expected.items():
        reported_value = validated.get(field)
        if reported_value != expected_value:
            reported = redact_metadata_text(repr(reported_value), limit=100)
            expected_text = redact_metadata_text(repr(expected_value), limit=100)
            raise ValueError(
                f"{field} does not match dispatch identity: reported {reported}, "
                f"expected {expected_text}"
            )


def _validate_executor_sidecar_checks(validated: Mapping[str, Any]) -> None:
    for index, row in enumerate(validated.get("checks", [])):
        if not isinstance(row, Mapping):
            continue
        if (
            row.get("reported_by") != "executor"
            or row.get("observed_by") is not None
            or row.get("observation_source") is not None
        ):
            raise ValueError(
                f"checks[{index}].reported_by must be 'executor' and dispatcher-owned "
                "observed_by/observation_source must be null in an executor-written sidecar"
            )


def _unit_result_failure(
    paths: OmhPaths,
    *,
    event: str,
    reason: str,
    sidecar_path: Path | None,
    run_ref: str,
    unit_id: str,
    worktree: Path,
    owner: str,
) -> dict[str, Any]:
    bounded_reason = redact_metadata_text(reason, limit=_MAX_UNIT_RESULT_TEXT)
    append_journal_observation(
        paths,
        {
            "target_type": "run",
            "target_id": run_ref,
            "run_id": run_ref,
            "event": event,
            "status": "observed",
            "summary": f"fanout unit result {event.removeprefix('unit_result_')} for {unit_id}: "
            f"{bounded_reason}",
            "worker_ref": unit_id,
            "worktree_ref": str(worktree),
            "runtime_profile": owner,
            "evidence_refs": [str(sidecar_path)] if sidecar_path is not None else [],
        },
    )
    result: dict[str, Any] = {
        "unit_result_status": event,
        "result_schema_valid": False,
    }
    if event == "unit_result_invalid":
        result["unit_result_error"] = bounded_reason
    return result


def _bounded_unit_result(validated: Mapping[str, Any]) -> dict[str, Any]:
    """Allowlist and size-bound sidecar fields before summary persistence."""
    bounded = {
        key: redact_metadata_text(str(validated.get(key, "")), limit=_MAX_UNIT_RESULT_TEXT)
        for key in _UNIT_RESULT_TOP_LEVEL_KEYS
    }
    bounded["changed_paths"] = [
        redact_metadata_text(str(value), limit=_MAX_UNIT_RESULT_TEXT)
        for value in list(validated.get("changed_paths", []))[:_MAX_UNIT_RESULT_PATHS]
    ]
    bounded["checks"] = [
        {
            key: (
                None
                if row.get(key) is None
                else redact_metadata_text(str(row.get(key)), limit=_MAX_UNIT_RESULT_TEXT)
            )
            for key in _UNIT_RESULT_CHECK_KEYS
        }
        for row in list(validated.get("checks", []))[:_MAX_UNIT_RESULT_CHECKS]
        if isinstance(row, Mapping)
    ]
    bounded["findings"] = [
        redact_metadata_text(str(value), limit=_MAX_UNIT_RESULT_TEXT)
        for value in list(validated.get("findings", []))[:_MAX_UNIT_RESULT_FINDINGS]
    ]
    if "schema_error" in validated:
        bounded["schema_error"] = redact_metadata_text(
            str(validated["schema_error"]), limit=_MAX_UNIT_RESULT_TEXT
        )
    return bounded


# One unit's salvage report is a few dozen paths at most; past that the list
# stops being a recovery aid and starts being a second copy of the diff.
_MAX_RECOVERY_PATHS = 50
RECOVERY_SCHEMA_VERSION = "fanout_unit_recovery/v1"
RECOVERY_CLAIM_BOUNDARY = (
    "A recovery record measures what a failed unit left in its worktree. It is not verification, review, "
    "or evidence that the captured work is correct, complete, or safe to merge."
)


def _capture_unit_recovery(
    paths: OmhPaths,
    *,
    fanout_id: str,
    unit_id: str,
    worktree: Path,
    base_sha: str,
    runner: Callable[..., Any],
) -> dict[str, Any] | None:
    """Metadata for whatever a failed unit left behind, or None when unmeasurable.

    Metadata only, on purpose: the changed paths, how many lines moved, and the
    size and SHA-256 of the diff that carries them. The diff itself is hashed
    and dropped — it stays in the unit worktree, which is the one place it is
    already allowed to live.

    Capture never raises. A unit that failed must not fail differently because
    the salvage probe did.
    """
    # Each argv is spelled with a literal subcommand, never `["git", verb]`:
    # INVARIANT 3 in tests/test_handoff_safety_contract_enforcement.py resolves
    # git verbs statically and fails closed on a runtime one.
    #
    # Git discovery walks UP from cwd, and a unit worktree is a sibling of the
    # repo root. If the unit destroyed its own `.git` link, an unguarded write
    # here would land in whatever repository encloses the parent directory —
    # possibly the operator's. Confirm the worktree is its own toplevel before
    # writing anything, so the allowlist's "never the operator's repository"
    # claim is checked rather than asserted.
    toplevel = _git_text(runner, worktree, ["git", "rev-parse", "--show-toplevel"])
    if toplevel is None or not _same_directory(toplevel.strip(), worktree):
        return _capture_failed("the unit worktree no longer resolves as its own git toplevel")
    # `git diff` does not see untracked files, and a failed unit's brand-new
    # files are the most common thing worth salvaging. `add -N` records the
    # paths without staging content, which both completes the measurement and
    # makes the `recover_with` command below actually produce a full patch.
    # It respects .gitignore, so build output stays out of the report.
    untracked_measured = _git_text(runner, worktree, ["git", "add", "-N", "--", "."]) is not None
    # Bytes, not text. `-z` deliberately disables git's C-quoting so paths are
    # emitted raw, and decoding them through the host locale (cp1252 on the
    # enforcing Windows job) silently rewrites a non-ASCII filename into
    # mojibake the operator then cannot find. Decoded strictly as UTF-8 below,
    # which is what git records paths as.
    numstat_bytes = _git_bytes(runner, worktree, ["git", "diff", "--numstat", "-z", base_sha])
    # Captured as BYTES, never decoded. A partial file in a non-UTF-8 encoding
    # is ordinary debris in a failed unit, and `text=True` would raise
    # UnicodeDecodeError straight through this function and abort the whole
    # dispatch. Hashing raw bytes also makes the digest describe what git
    # actually emits, rather than a decode/re-encode round trip through
    # whatever the host locale happens to be.
    patch_bytes = _git_bytes(runner, worktree, ["git", "diff", base_sha])
    if numstat_bytes is None or patch_bytes is None:
        return _capture_failed("git refused to diff the unit worktree against the dispatch base")
    paths_changed, lines_changed = _parse_numstat(numstat_bytes.decode("utf-8", "surrogateescape"))
    if not untracked_measured:
        # `add -N` failed, so anything the unit CREATED is invisible to
        # `git diff`. Whatever the tracked diff shows, this record cannot make
        # the completeness promise its `recover_with` command advertises, and a
        # partial answer an operator acts on is worse than an honest refusal.
        # `tracked_paths_seen` says the worktree is not empty so nobody deletes
        # it on the strength of this record.
        failed = _capture_failed(
            "git add -N failed, so files the unit created could not be measured; "
            "the tracked diff alone is not a complete patch"
        )
        failed["tracked_paths_seen"] = len(paths_changed)
        return failed
    if not paths_changed and not patch_bytes:
        return {
            "schema_version": RECOVERY_SCHEMA_VERSION,
            "outcome": "no_changes",
            "claim_boundary": RECOVERY_CLAIM_BOUNDARY,
        }
    record: dict[str, Any] = {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "outcome": "recovery_available",
        "unit_id": unit_id,
        "base_sha": base_sha,
        "worktree_path": str(worktree),
        "paths_changed": len(paths_changed),
        "lines_changed": lines_changed,
        "paths": paths_changed[:_MAX_RECOVERY_PATHS],
        "paths_truncated": len(paths_changed) > _MAX_RECOVERY_PATHS,
        "diff_bytes": len(patch_bytes),
        "diff_sha256": sha256(patch_bytes).hexdigest(),
        "recover_with": f"git -C {shlex.quote(str(worktree))} diff {shlex.quote(base_sha)}",
        "claim_boundary": RECOVERY_CLAIM_BOUNDARY,
    }
    if fanout_id:
        from .fanout_artifacts import fanout_unit_recovery_path, write_fanout_unit_recovery

        try:
            # The ref goes INTO the record before it is serialized. Writing
            # first and assigning after left the on-disk file missing a key the
            # summary's copy carried, so two shapes advertised the same
            # schema_version and a consumer reading the documented path got a
            # KeyError.
            record["recovery_ref"] = str(fanout_unit_recovery_path(paths, fanout_id, unit_id))
            write_fanout_unit_recovery(paths, fanout_id, unit_id, record)
        except (OSError, ValueError):
            # Same posture as the in-flight marker: a persistence failure is
            # reported by omission, never by losing the unit result.
            record["recovery_ref"] = ""
    return record


def _capture_failed(reason: str) -> dict[str, Any]:
    """A recovery record that reports the probe could not answer.

    Distinct from `no_changes` on purpose: "the unit left nothing" and "I could
    not tell" lead an operator to opposite actions.
    """
    return {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "outcome": "capture_failed",
        "reason": reason,
        "claim_boundary": RECOVERY_CLAIM_BOUNDARY,
    }


def _same_directory(reported: str, worktree: Path) -> bool:
    if not reported:
        return False
    try:
        return Path(reported).resolve(strict=False) == worktree.resolve(strict=False)
    except OSError:
        return False


def _git_text(runner: Callable[..., Any], worktree: Path, argv: list[str]) -> str | None:
    """Decoded stdout of one git command in the unit worktree, or None on failure.

    Callers pass the complete argv, subcommand included, so the verb stays a
    literal at every construction site. Decoding is lenient: this is used for
    git's own structured output (paths, refs), where an undecodable byte
    should degrade one field rather than abort a dispatch.
    """
    try:
        completed = runner(
            argv, cwd=str(worktree), text=True, errors="replace", capture_output=True, timeout=60
        )
        # Inside the try: a runner that reports a non-numeric returncode makes
        # `int(...)` raise TypeError, which would escape this "never raises"
        # helper exactly the way UnicodeDecodeError used to.
        if int(getattr(completed, "returncode", 1)) != 0:
            return None
        stdout = getattr(completed, "stdout", "") or ""
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None
    return stdout if isinstance(stdout, str) else stdout.decode("utf-8", "replace")


def _git_bytes(runner: Callable[..., Any], worktree: Path, argv: list[str]) -> bytes | None:
    """Raw stdout of one git command, undecoded, or None on failure.

    Used for the patch: it may contain any byte sequence a failed unit wrote,
    and decoding it would both risk raising and make any digest describe the
    round trip rather than git's actual output.
    """
    try:
        completed = runner(argv, cwd=str(worktree), capture_output=True, timeout=60)
        if int(getattr(completed, "returncode", 1)) != 0:
            return None
        stdout = getattr(completed, "stdout", b"") or b""
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None
    return stdout if isinstance(stdout, bytes) else str(stdout).encode("utf-8", "surrogateescape")


def _parse_numstat(numstat: str) -> tuple[list[str], int]:
    """Sorted changed paths and total moved lines from `git diff --numstat -z`.

    `-z` is what makes this parseable: it NUL-terminates records and turns off
    the C-quoting that would otherwise mangle a path containing a tab or a
    quote. Binary files report `-` for both counts; they still count as a
    changed path and contribute no lines.

    A rename or copy emits an empty path field followed by two more records —
    the old path then the new one. Both are counted, because both are things
    the operator has to reconcile.
    """
    tokens = numstat.split("\0")
    paths_changed: list[str] = []
    lines_changed = 0
    index = 0
    while index < len(tokens):
        record = tokens[index]
        index += 1
        # Split on the first two tabs only. `-z` emits the path raw, so a
        # filename containing a tab would otherwise be truncated at it.
        fields = record.split("\t", 2)
        if len(fields) < 3:
            continue
        added, removed, path = fields[0], fields[1], fields[2]
        for count in (added, removed):
            if count.isdigit():
                lines_changed += int(count)
        if path:
            paths_changed.append(path)
            continue
        # Rename/copy: the next two tokens are the old and new paths.
        for offset in (0, 1):
            if index + offset < len(tokens) and tokens[index + offset]:
                paths_changed.append(tokens[index + offset])
        index += 2
    return sorted(set(paths_changed)), lines_changed


def _ensure_unit_run(paths: OmhPaths, unit: Mapping[str, Any], owner: str) -> None:
    run_ref = str(unit.get("run_ref", unit.get("unit_id", "")))
    run_path = paths.runtime_runs_dir / run_ref / "run.json"
    if run_path.exists():
        return
    create_run(
        paths,
        {
            "run_id": run_ref,
            "skill": "fanout-unit",
            "harness": "coding-handling",
            "trigger": f"fanout:dispatch:{unit.get('unit_id')}",
            "privacy": "metadata_only",
            "inputs_summary": f"fanout unit {unit.get('unit_id')} owned by {owner}",
            "outputs_summary": "local dispatch bridge run",
            "verification_summary": "observed via journal worker_dispatch/worker_result events",
        },
    )


def _already_completed(paths: OmhPaths, unit: Mapping[str, Any]) -> bool:
    run_ref = str(unit.get("run_ref", ""))
    try:
        shown = show_run(paths, run_ref)
    except (OSError, ValueError, KeyError):
        return False
    if not isinstance(shown, dict):
        return False
    for event in shown.get("journal_events", []) or []:
        if (
            isinstance(event, dict)
            and str(event.get("event", "")) in {"worker_result", "executor_result_observed"}
            and str(event.get("status", "")) == "observed"
        ):
            return True
    return False


def _dependency_satisfied(result: dict[str, Any] | None) -> bool:
    if result is None:
        return False
    # dry_run_planned satisfies dependencies so a --dry-run renders the full
    # plan; live dispatch only advances on an observed exit-0 result.
    return (
        result.get("status") in {"completed", "already_completed", "dry_run_planned"}
        or bool(result.get("process_succeeded"))
    )


def _dependency_failed(result: dict[str, Any] | None) -> bool:
    if result is None:
        return False
    return result.get("status") in {
        "capability_snapshot_invalid",
        "failed",
        "blocked_by_dependency",
        "executor_not_ready",
        "unsupported_for_local_dispatch",
        "worktree_failed",
        "not_selected",
    } and not result.get("process_succeeded")


def _blocked(unit: Mapping[str, Any], results: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    entry = _skipped(unit, "blocked_by_dependency")
    entry["blocked_on"] = [
        str(dep)
        for dep in unit.get("depends_on", []) or []
        if _dependency_failed(results.get(str(dep)))
    ]
    return entry


def _skipped(
    unit: Mapping[str, Any],
    status: str,
    *,
    process_succeeded: bool = False,
    unit_verification_observed: bool = False,
) -> dict[str, Any]:
    return {
        "unit_id": str(unit["unit_id"]),
        "run_ref": str(unit.get("run_ref", "")),
        "owner": str(unit.get("owner") or "choose"),
        "status": status,
        **_dispatch_status_ladder(
            process_succeeded=process_succeeded,
            unit_verification_observed=unit_verification_observed,
        ),
    }


def _worktree_path(repo_root: Path, unit_id: str) -> Path:
    return repo_root.parent / f"{repo_root.name}-fanout-{unit_id}"


def _limit_shaped_label(output_tail: str, stderr_tail: str) -> str:
    haystack = f"{output_tail}\n{stderr_tail}".casefold()
    for label, pattern in _LIMIT_SHAPED_PATTERNS:
        if pattern in haystack:
            return label
    return ""


def _record_limit_signal(paths: OmhPaths, owner: str, *, run_ref: str, unit_id: str, pattern_label: str) -> None:
    def _update(state: dict[str, Any]) -> dict[str, Any]:
        state["schema_version"] = EXECUTOR_LIMIT_SIGNALS_SCHEMA_VERSION
        profiles = state.setdefault("profiles", {})
        profiles[owner] = {
            "last_limit_shaped_at": utc_now(),
            "run_ref": run_ref,
            "unit_id": unit_id,
            "pattern_label": pattern_label,
        }
        state["claim_boundary"] = EXECUTOR_LIMIT_SIGNALS_CLAIM_BOUNDARY
        return state

    try:
        locked_json_update(paths.executor_limit_signals_path, _update, private=True)
    except (OSError, TimeoutError):
        # An advisory that cannot be written must never abort the dispatch —
        # losing the whole summary over a lock timeout would be worse than
        # missing one ranking hint.
        pass


def _clear_limit_signal(paths: OmhPaths, owner: str) -> None:
    if not paths.executor_limit_signals_path.exists():
        return

    def _update(state: dict[str, Any]) -> dict[str, Any]:
        profiles = state.get("profiles")
        if isinstance(profiles, dict):
            profiles.pop(owner, None)
        return state

    try:
        locked_json_update(paths.executor_limit_signals_path, _update, private=True)
    except (OSError, TimeoutError):
        pass
