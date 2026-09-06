from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED
from concurrent.futures import CancelledError as FuturesCancelledError
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from concurrent.futures import wait as futures_wait
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..runtime.artifacts import append_journal_observation, create_run, show_run
from ..system.approval_tier import TIER_AUTO_ALLOWED, resolve_approval_tier
from ..system.local_store import atomic_write_json, ensure_dir, locked_json_update, read_json_object_result, utc_now
from ..system.security_posture import resolve_security_posture
from ..system.metadata_safety import redact_metadata_text
from ..system.output_truncation import spill_evidence_ref, truncate_output, truncation_notice
from ..system.paths import OmhPaths
from ._hermes_child_process import terminate_process_group
from .action_gate import recheck_safety_profile_revision
from .coding_contracts import STRUCTURAL_SEARCH_GUIDANCE
from .dispatch_failure_recovery import (
    HERMES_LANE_CONSENT,
    dispatch_unit_via_hermes_child,
    hermes_routing_available,
    CHOICE_HERMES,
    CHOICE_REPORT,
    CHOICE_RETARGET,
    CHOICE_WAIT,
    COOLDOWN_STATUS_AUTH,
    COOLDOWN_STATUS_LIMIT,
    ON_FAILURE_HERMES,
    ON_FAILURE_REPORT,
    ON_FAILURE_WAIT,
    FAILURE_KIND_AUTH_SHAPED,
    FAILURE_KIND_LIMIT_SHAPED,
    FAILURE_RECOVERY_CLAIM_BOUNDARY,
    FAILURE_RECOVERY_SCHEMA_VERSION,
    auth_shaped_label,
    build_repair_card,
    classify_failure_kind,
    clear_auth_failure_signal,
    prompt_recovery_choice,
    record_auth_failure_signal,
    recovery_candidates,
    recovery_decision,
    recovery_options,
    retarget_candidates,
    spawn_cooldown,
)
from .executor_capability_snapshots import (
    complete_executor_capability_snapshot,
    validate_executor_capability_snapshot,
)
from .executor_capabilities import legacy_executor_capability_projection
from .media_handoff_capabilities import build_executor_modality_decision
from .executor_progress import (
    ExecutorProgressError,
    build_progress_binding,
    build_safe_progress_signal,
    normalize_executor_profile,
    observe_executor_progress,
    write_progress_binding,
)
from .executor_readiness import probe_executor_readiness
from .fanout_admission import AdaptiveFanoutAdmission
from .fanout_artifact_sharing import plan_and_link_shared_artifacts
from .fanout_diagnostics_hook import run_post_green_diagnostics
from .fanout_final_review_hook import FinalReviewWaveEngine, run_final_review_after_integration
from .fanout_health_events import (
    FanoutHealthEvents,
    monotonic_milliseconds,
    write_fanout_health_event,
)
from .fanout_confinement import (
    FanoutFilesystemConfinement,
    confinement_receipt,
    owner_state_directories,
    planned_fanout_filesystem_confinement,
    prepare_fanout_filesystem_confinement,
)
from .diagnostic_execution import DiagnosticExecutionEngine
from .fanout_contracts import (
    FANOUT_CLAIM_BOUNDARY,
    FANOUT_CONTRACT_SCHEMA_VERSION,
    LEGACY_FANOUT_CONTRACT_SCHEMA_VERSION,
    UNIT_VERIFICATION_OBSERVATION_SOURCE,
    FanoutContractError,
    verification_command_argv,
)
from .fanout_journal import (
    RESUME_HOLD_ACTIONS,
    RESUME_HOLD_SUCCEEDED,
    build_fanout_run_journal,
    plan_fanout_resume,
    resume_counts,
    write_fanout_run_journal,
)
from .fanout_review_budget import (
    ReviewDispatchBudget,
    normalized_review_role,
)
from .inflight import InflightMarkerError, clear_inflight_marker, write_inflight_marker
from .parallelism_policy import FANOUT_MAX_DEPTH_DEFAULT, FANOUT_RUN_SPAWN_CEILING_DEFAULT
from .fanout_retry import (
    FANOUT_MAX_RETRIES,
    RETRY_CLAIM_BOUNDARY,
    RETRY_POLICY_SCHEMA_VERSION,
    classify_unit_failure,
    evaluate_unit_retry,
)
from .unit_prompt_protocol import shared_unit_preamble_lines, unit_protocol_lines
from .verification_execution import VerificationExecutionGate
from .verification_integration import run_post_integration_verification
from .verification_plan import (
    VERIFICATION_PLAN_SCHEMA_VERSION,
    compile_verification_plan,
    verification_execution_environment,
)
from .verification_receipts import SingleFlight
from .verification_runner import PlanRunContext, run_verification_plan
from .fanout_unit_results import (
    FANOUT_UNIT_RESULT_CHECK_STATUSES,
    FANOUT_UNIT_RESULT_DECLINE_REASONS,
    FANOUT_UNIT_RESULT_PROCESS_STATUSES,
    validate_check_rows,
    validate_unit_result,
)
from .unit_telemetry import parse_unit_telemetry

FANOUT_DISPATCH_SCHEMA_VERSION = "fanout_dispatch_summary/v1"

# Grace between SIGTERM and SIGKILL when a unit group must die — OMO's
# launcher uses the same 10s window before re-raising on itself.
UNIT_TERMINATE_GRACE_SECONDS = 10.0

# Unit statuses for a batch that was stopped. Four words, because the four
# facts an operator has to act on differently used to arrive as one
# (`interrupted`) or as `failed`:
#
#   cancelled                       -- this unit's process was running and the
#                                      dispatcher terminated its group. It may
#                                      have left a dirty worktree, so a resume
#                                      still asks the replay-safety question.
#   cancelled_outcome_unknown       -- the unit was in flight and its worker did
#                                      not come back within the terminate grace.
#                                      Whether it wrote anything is not known,
#                                      and saying so is the honest answer.
#   not_started_cancelled           -- the unit never spawned. Nothing exists to
#                                      preserve, so a resume re-attempts it.
#   blocked_by_cancelled_dependency -- the unit was admissible only behind a
#                                      unit that was cancelled. It is not a
#                                      failure of this unit and not the same as
#                                      being blocked behind one that failed.
#
# OMH records these; it does not claim it can cancel every external executor.
# The dispatcher can only terminate the process groups it spawned itself, and
# these words describe what it OBSERVED of that termination.
UNIT_STATUS_CANCELLED = "cancelled"
UNIT_STATUS_CANCELLED_OUTCOME_UNKNOWN = "cancelled_outcome_unknown"
UNIT_STATUS_NOT_STARTED_CANCELLED = "not_started_cancelled"
UNIT_STATUS_BLOCKED_BY_CANCELLED_DEPENDENCY = "blocked_by_cancelled_dependency"
CANCELLED_UNIT_STATUSES = frozenset(
    {
        UNIT_STATUS_CANCELLED,
        UNIT_STATUS_CANCELLED_OUTCOME_UNKNOWN,
        UNIT_STATUS_NOT_STARTED_CANCELLED,
        UNIT_STATUS_BLOCKED_BY_CANCELLED_DEPENDENCY,
    }
)

# Live unit process groups, registered by the signal-safe default runner so
# an interrupt terminates them instead of orphaning them to pid 1. OMO
# shipped exactly this incident: a launcher blocked in spawnSync died on
# SIGTERM and its engine reparented to init, still writing into the tree.
# Injected test runners never register here. The lock is reentrant because
# the SIGTERM handler can fire while the main thread already holds it.
_LIVE_UNIT_LOCK = threading.RLock()
_LIVE_UNIT_GROUPS: dict[int, subprocess.Popen] = {}

# Set BEFORE any group is terminated, checked by workers before and after
# the owner gate and by the runner immediately after registering its child
# (register-then-check): either the terminator's snapshot contains the
# process, or the worker sees the flag — no spawn slips through the gap.
# One dispatch per process is the supported shape; the flag is cleared at
# dispatch entry.
_INTERRUPT_FLAG = threading.Event()


def _register_live_unit(process: subprocess.Popen) -> None:
    with _LIVE_UNIT_LOCK:
        _LIVE_UNIT_GROUPS[process.pid] = process


def _unregister_live_unit(process: subprocess.Popen) -> None:
    with _LIVE_UNIT_LOCK:
        _LIVE_UNIT_GROUPS.pop(process.pid, None)


def terminate_live_unit_groups(*, grace: float = UNIT_TERMINATE_GRACE_SECONDS) -> list[int]:
    """SIGTERM every live unit group, escalating to SIGKILL after `grace`.

    Sets the interrupt flag first so a worker that has not spawned yet
    refuses to, and a spawn racing this snapshot terminates itself on the
    runner's register-then-check.
    """
    _INTERRUPT_FLAG.set()
    with _LIVE_UNIT_LOCK:
        processes = list(_LIVE_UNIT_GROUPS.values())
    terminated: list[int] = []
    for process in processes:
        # The child may have been reaped between snapshot and signal; a
        # freed pid must not be signalled — the reaper refuses recycled
        # pids and the in-process path holds the same line.
        if process.poll() is None:
            terminate_process_group(process, grace, signal.SIGTERM)
        terminated.append(process.pid)
        _unregister_live_unit(process)
    return terminated


def signal_safe_unit_runner(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    text: bool | None = None,
    errors: str | None = None,
    capture_output: bool = False,
    timeout: float | None = None,
    on_spawn: Callable[[subprocess.Popen], None] | None = None,
    on_output: Callable[[str], None] | None = None,
    confinement_command: Sequence[str] | None = None,
) -> subprocess.CompletedProcess:
    """Drop-in for `subprocess.run` that owns each child as a process group.

    A blocking `subprocess.run` orphans the agent CLI when the dispatcher
    dies: the child reparents to pid 1 and keeps writing into the worktree.
    A session-leader child can be terminated as a group on interrupt or
    timeout, and its pid is real state the fanout reaper can verify against
    the inflight marker. `on_spawn` hands the live process to the caller
    (the dispatch path records the pid in the unit's inflight marker).

    `on_output` receives the stdout captured SO FAR, at a fixed poll cadence
    while the child runs — the seam the dispatch path uses to read a unit's
    cumulative token telemetry mid-run instead of only after exit. It only
    engages for text-mode captured output (the dispatch path's shape); any
    other shape keeps the plain blocking `communicate` exactly as before.
    """
    pipe = subprocess.PIPE if capture_output else None
    process = subprocess.Popen(
        list(confinement_command or argv),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        text=text,
        errors=errors,
        stdout=pipe,
        stderr=pipe,
        start_new_session=os.name != "nt",
    )
    with process:
        _register_live_unit(process)
        try:
            # Register-then-check: a spawn racing the interrupt either lands
            # in the terminator's snapshot or sees the flag here and dies at
            # once instead of outliving the dispatcher.
            if _INTERRUPT_FLAG.is_set():
                terminate_process_group(process, UNIT_TERMINATE_GRACE_SECONDS, signal.SIGTERM)
            try:
                if on_spawn is not None:
                    on_spawn(process)
            except Exception:
                # A raising hook must not leak the child it was handed.
                terminate_process_group(process, UNIT_TERMINATE_GRACE_SECONDS, signal.SIGTERM)
                raise
            if on_output is not None and capture_output and text:
                stdout, stderr = _communicate_with_output_polls(
                    process,
                    timeout=timeout,
                    on_output=on_output,
                    poll_seconds=UNIT_OUTPUT_POLL_SECONDS,
                )
            else:
                stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # The whole group dies with the leader — a timed-out unit must
            # not leave grandchildren running against the worktree.
            terminate_process_group(process, UNIT_TERMINATE_GRACE_SECONDS, signal.SIGTERM)
            raise
        finally:
            _unregister_live_unit(process)
    return subprocess.CompletedProcess(list(argv), int(process.returncode or 0), stdout, stderr)


# Capability marker, not an identity check: a wrapper (functools.partial, a
# retry decorator) can propagate it so the dispatch path keeps recording the
# reapable pid instead of silently dropping it.
signal_safe_unit_runner.accepts_on_spawn = True  # type: ignore[attr-defined]
# Same marker pattern for the mid-run stdout seam: injected test runners keep
# the plain protocol unless they opt in, exactly like `accepts_on_spawn`.
signal_safe_unit_runner.accepts_on_output = True  # type: ignore[attr-defined]

# Cadence of mid-run stdout snapshots handed to `on_output`. Also the upper
# bound the poll loop waits between liveness checks, so timeout precision is
# never worse than one poll step.
UNIT_OUTPUT_POLL_SECONDS = 5.0


def _drain_stream(stream: Any, chunks: list[str]) -> None:
    # Line-at-a-time on purpose: a text stream's `read(n)` blocks until n
    # characters accumulate, which starves the mid-run snapshots of
    # everything until EOF. `readline` returns as each line lands — the
    # exact granularity of the JSONL telemetry the snapshots exist to carry.
    try:
        while True:
            line = stream.readline()
            if not line:
                return
            chunks.append(line)
    except (OSError, ValueError):
        # A pipe closing mid-read (interrupt, group kill) ends the drain; the
        # chunks captured before that still return to the caller.
        return


def _snapshot_output(on_output: Callable[[str], None], chunks: list[str]) -> None:
    try:
        on_output("".join(chunks))
    except Exception:
        # A raising snapshot hook is telemetry-only narration; unlike a
        # raising on_spawn hook it must never kill the unit it observes.
        return


def _communicate_with_output_polls(
    process: subprocess.Popen,
    *,
    timeout: float | None,
    on_output: Callable[[str], None],
    poll_seconds: float,
) -> tuple[str, str]:
    """`communicate()` with periodic mid-run stdout snapshots.

    Reader threads drain both pipes continuously (the same deadlock guard
    `communicate` provides), while the waiting thread wakes every poll step
    to hand `on_output` the stdout collected so far. The overall timeout
    keeps `communicate`'s contract: `TimeoutExpired` raises to the caller,
    who terminates the group.
    """
    collected: dict[str, list[str]] = {"stdout": [], "stderr": []}
    threads: list[threading.Thread] = []
    for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        if stream is None:
            continue
        thread = threading.Thread(target=_drain_stream, args=(stream, collected[name]), daemon=True)
        thread.start()
        threads.append(thread)
    deadline = None if timeout is None else time.monotonic() + float(timeout)
    step = max(0.2, float(poll_seconds))
    while True:
        wait_for = step
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, float(timeout or 0))
            wait_for = min(step, remaining)
        try:
            process.wait(timeout=wait_for)
            break
        except subprocess.TimeoutExpired:
            _snapshot_output(on_output, collected["stdout"])
    for thread in threads:
        thread.join(timeout=UNIT_TERMINATE_GRACE_SECONDS)
    return "".join(collected["stdout"]), "".join(collected["stderr"])


# Spacing between real agent-CLI spawn starts of one fanout. Providers cache
# prompt prefixes by exact bytes, and a cache entry is readable only once the
# first response starts streaming — parallel identical-prefix requests each
# pay a full cache write. Two seconds gives the first dispatch a head start
# at writing the cache its siblings read without materially delaying a batch.
CACHE_WARM_SPAWN_STAGGER_SECONDS: float = 2.0


class _SpawnStagger:
    """Spaces real agent-CLI spawn starts so the first request writes the
    provider prompt cache the siblings read; parallel identical requests
    would each pay a full cache write."""

    def __init__(
        self,
        interval: float,
        *,
        # The clock and sleep are injected, same seam as the retry policy's
        # `sleep` parameter below, so the reservation schedule this class
        # computes is assertable without a real clock and without a single
        # wall-clock sleep in a test.
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = max(0.0, interval)
        self._lock = threading.Lock()
        self._next = 0.0
        self._monotonic = monotonic
        self._sleep = sleep

    def reserve(self) -> None:
        with self._lock:
            now = self._monotonic()
            slot = max(now, self._next)
            self._next = slot + self._interval
        # time.sleep can wake up to a timer tick early on Windows waitable
        # timers, which would collapse the spacing; loop until the slot is
        # actually reached on the monotonic clock.
        while True:
            now = self._monotonic()
            if now >= slot:
                return
            self._sleep(slot - now)


# Lineage stamp carried into every child environment this module spawns.
# `_DEPTH` is how many dispatch generations deep that child already is (the
# operator's own invocation is depth 0, its children run at depth 1);
# `_LINEAGE` is the human-readable chain of `<fanout_id>:<unit_id>` steps that
# got there, so a refusal names which run it came out of instead of only
# reporting a number. Both are namespaced under OMH_ and are the only thing
# the guard reads: a child cannot be trusted to report its own depth, but it
# cannot forge a smaller one either without the operator editing the env by
# hand, which is the same trust boundary every other env tunable has.
FANOUT_DEPTH_ENV_VAR = "OMH_FANOUT_DEPTH"
FANOUT_LINEAGE_ENV_VAR = "OMH_FANOUT_LINEAGE"
# A lineage chain is metadata on a refusal, not a queue: bound it so a
# pathological nesting cannot grow the child environment without limit.
_MAX_LINEAGE_CHARS = 512
FANOUT_DEPTH_REFUSAL_REASON = "fanout_depth_exceeded"
SPAWN_CEILING_STATUS = "spawn_ceiling_reached"
FANOUT_SPAWN_GUARD_CLAIM_BOUNDARY = (
    "The spawn guard bounds how many local agent-CLI processes one `omh coding fanout dispatch` run may "
    "start and how deep dispatch may nest. It is a refusal, not verification, review, or merge evidence, "
    "and a run inside its bounds is not thereby correct."
)


def read_fanout_depth(env: Mapping[str, str]) -> int:
    """The dispatch generation this process is already running at.

    Anything this module did not write reads as depth 0 — an absent marker is
    the ordinary operator invocation, and a corrupt one must not accidentally
    read as a LARGER depth that refuses a legitimate run. ASCII digits only:
    `str.isdigit()` alone accepts Arabic-Indic and other decimal forms that
    `int()` then parses into a depth nothing here ever stamped.
    """
    raw = str(env.get(FANOUT_DEPTH_ENV_VAR, "") or "").strip()
    if not raw.isascii() or not raw.isdigit():
        return 0
    return int(raw)


def fanout_child_env(
    base_env: Mapping[str, str],
    *,
    depth: int,
    fanout_id: str,
    unit_id: str,
    owner: str = "",
) -> dict[str, str]:
    """`base_env` plus this dispatcher's lineage and owner-state pins, for one child spawn.

    Every process this module starts gets the stamp, verification commands
    included: a guard a child sidesteps by shelling out one more level is not
    a guard.
    """
    lineage_step = f"{fanout_id or 'unrecorded'}:{unit_id}"
    parent_lineage = str(base_env.get(FANOUT_LINEAGE_ENV_VAR, "") or "").strip()
    lineage = f"{parent_lineage}/{lineage_step}" if parent_lineage else lineage_step
    child_env = {
        **dict(base_env),
        FANOUT_DEPTH_ENV_VAR: str(depth + 1),
        FANOUT_LINEAGE_ENV_VAR: lineage[-_MAX_LINEAGE_CHARS:],
    }
    if owner != "omo-runtime":
        return child_env
    host = omo_runtime_host()
    environment_variable = {"pi": "PI_CODING_AGENT_DIR", "senpi": "SENPI_CODING_AGENT_DIR"}.get(host)
    if environment_variable is None:
        return child_env
    state_directories = owner_state_directories(owner, child_env)
    if len(state_directories) != 1:
        return child_env
    # A direct pi/senpi spawn must not inherit an ambient Senpi brand: it
    # changes both the config directory and environment-prefix precedence.
    child_env.pop("SENPI_BRAND", None)
    child_env[environment_variable] = str(state_directories[0])
    return child_env


class _SpawnLedger:
    """The per-run total-spawn budget, claimed once per real agent-CLI start.

    Separate from the pool width on purpose: the pool bounds how many units
    run at once, this bounds how many are ever started by one run. A claim is
    taken BEFORE the unit worktree is created, so a refused unit costs nothing
    and leaves nothing behind to clean up.
    """

    def __init__(self, ceiling: int) -> None:
        self.ceiling = max(1, int(ceiling))
        self._lock = threading.Lock()
        self._claimed = 0

    def claim(self) -> bool:
        with self._lock:
            if self._claimed >= self.ceiling:
                return False
            self._claimed += 1
            return True

    def release(self) -> None:
        """Return a claim when a later admission reservation refuses the spawn."""
        with self._lock:
            self._claimed -= 1

    @property
    def claimed(self) -> int:
        with self._lock:
            return self._claimed


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
# What a dispatched unit's stdout/stderr keeps in memory for the summary and
# the journal. Everything above it spills, so the bound costs context rather
# than evidence.
_MAX_UNIT_OUTPUT_TAIL = 2000
# The journal's own `summary` field is capped at 500 characters upstream, so
# this second bound over an already-bounded tail leaves room for the rest of
# the line. The resolvable pointer rides in `evidence_refs`, which has no such
# ceiling, rather than in prose a bare slice could cut in half.
_MAX_UNIT_SUMMARY_TAIL = 300
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
    # Shared preamble first: sibling prompts must share a byte-identical head
    # so provider prefix caches serve every unit after the first (see
    # PROMPT_CACHE_COMPOSITION_PROTOCOL).
    lines = shared_unit_preamble_lines(goal_text)
    lines.append(f"Work unit: {unit.get('title', unit.get('unit_id'))}")
    lines.append(f"Stay strictly inside these paths: {file_scope}.")
    if do_not_touch:
        lines.append(f"Do not touch: {do_not_touch} (owned by sibling units).")
    lines.append(f"Work on branch {unit.get('branch_suggestion', '')} in the current worktree.")
    # Pre-declared completion criteria (absorbing the unit's integration
    # checks) and — on high-effort routes — the per-family over-verification
    # calibration; the unit-invariant discipline blocks already rode the
    # shared preamble above.
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
    """Executor-neutral, typed sidecar contract appended to a live unit prompt.

    The closed enums are spelled out with their exact literals — imported from
    the validator's own tuples so prompt and validation can never drift. The
    validator deliberately never infers or aliases (a "success" it normalized
    into "process_succeeded" would launder an executor claim), so this prompt
    is the ONLY channel that tells a foreign executor which values validate;
    omitting them produced real `unit_result_invalid` outcomes on work that
    had succeeded (#1190).
    """
    process_values = " or ".join(f'"{value}"' for value in FANOUT_UNIT_RESULT_PROCESS_STATUSES)
    decline_values = ", ".join(f'"{value}"' for value in FANOUT_UNIT_RESULT_DECLINE_REASONS)
    check_values = ", ".join(f'"{value}"' for value in FANOUT_UNIT_RESULT_CHECK_STATUSES)
    return [
        "Before exiting, write one fanout_unit_result/v1 JSON sidecar to exactly "
        f"{contract.get('path', '')}.",
        "Top-level fields: schema_version, unit_id, run_id, fanout_id, base_sha, head_sha, "
        "process_status, decline_reason (required only with process_status process_declined), "
        "changed_paths, checks, findings, schema_error (optional).",
        "Use these dispatch-bound values: "
        f"schema_version=fanout_unit_result/v1, unit_id={contract.get('unit_id', '')}, "
        f"run_id={contract.get('run_id', '')}, fanout_id={contract.get('fanout_id', '')}, "
        f"base_sha={contract.get('base_sha', '')}; head_sha is the git HEAD you leave behind.",
        f"process_status must be exactly {process_values} — no other value validates.",
        "process_declined is a conclusive negative answer (the target does not exist, the request "
        "is refused by policy, or the acceptance criteria are infeasible as specified), never a "
        "retry candidate — do not report process_failed for it. When you report process_declined, "
        f"decline_reason is required and must be exactly {decline_values} — omit decline_reason for "
        "every other process_status.",
        "Each checks row fields: command, status, evidence_ref, reported_by, observed_by, "
        "observation_source.",
        f"Each checks row status must be exactly one of {check_values} — no other value validates.",
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
    review_role = str(handoff.get("review_role", "") or "")
    if review_role:
        return review_role
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
    if errors or snapshot is None:
        return declared_owner, snapshot, errors
    decision = build_executor_modality_decision(
        input_representation=handoff.get("input_representation", "text_only"),
        snapshot=snapshot,
        route=handoff.get("model_route") if isinstance(handoff.get("model_route"), Mapping) else None,
        transformation=handoff.get("executor_modality_decision", {}).get("transformation")
        if isinstance(handoff.get("executor_modality_decision"), Mapping)
        else None,
    )
    verdict = str(decision["verdict"])
    if verdict != "dispatch":
        return declared_owner, snapshot, [f"{verdict}: {decision['fallback_reason'] or decision['remaining_user_action']}"]
    return declared_owner, snapshot, []


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


# One process-wide single-flight registry for verification receipts: two
# consumers resolving the same revision-bound key in this process share one
# check process and one receipt.
_VERIFICATION_SINGLE_FLIGHT = SingleFlight()


def _verification_worktree_revision(runner: Callable[..., Any], worktree: Path) -> str | None:
    """Return a reusable tree revision only when the worktree is clean.

    `HEAD^{tree}` cannot describe tracked edits or untracked files. Reuse is
    therefore disabled rather than guessed whenever git cannot prove the exact
    worktree is clean.
    """
    status = _git_text(
        runner, worktree, ["git", "status", "--porcelain=v1", "--untracked-files=all"]
    )
    if status is None or status.strip():
        return None
    revision = _git_text(runner, worktree, ["git", "rev-parse", "HEAD^{tree}"])
    return revision.strip() if revision else None


def _observed_clean_producer_head(runner: Callable[..., Any], worktree: Path) -> str | None:
    """Return the canonical full producer commit only after proving its worktree clean."""
    if _verification_worktree_revision(runner, worktree) is None:
        return None
    head_sha = _git_text(runner, worktree, ["git", "rev-parse", "HEAD"])
    if head_sha is None:
        return None
    normalized = head_sha.strip()
    return normalized if re.fullmatch(r"[0-9a-f]{40}", normalized) else None


def _run_verification_command(
    command: str,
    worktree: Path,
    runner: Callable[..., Any],
    child_env: Mapping[str, str] | None = None,
    spill_dir: Path | None = None,
    timeout: int | None = None,
    confinement: FanoutFilesystemConfinement | None = None,
) -> tuple[str, str, dict[str, Any] | None]:
    """Run one command in the unit worktree; return status, bounded tail, truncation record.

    Never raises: a command that cannot start is a failed check, not a failed
    dispatch. `shell=False`, so the argv comes from the contract's own frozen
    split and nothing in the command string is reinterpreted here.

    The third element is the `omh_output_truncation/v1` record for the captured
    output, present whenever output was actually captured -- including when it
    fit, so a reader can tell "this is the whole failure output" from "the tail
    of a longer one". It is `None` for the paths that never ran a command and
    so have a constructed message rather than captured output.

    `timeout` lets a planned check narrow the per-command ceiling; the module
    ceiling remains the default and nothing here can widen it.
    """
    effective_timeout = timeout if isinstance(timeout, int) and timeout > 0 else _VERIFICATION_COMMAND_TIMEOUT
    try:
        env_overrides, argv = verification_command_argv(command)
    except FanoutContractError as exc:
        return "failed", str(exc), None
    try:
        environment = {**(os.environ if child_env is None else child_env), **env_overrides}
        active_confinement = confinement
        if runner is signal_safe_unit_runner and active_confinement is None:
            active_confinement = prepare_fanout_filesystem_confinement(
                worktree, environment, (argv,)
            )
        confinement_command = (
            active_confinement.command(argv) if active_confinement is not None else None
        )
        if active_confinement is not None:
            environment = {**active_confinement.command_environment(), **env_overrides}
        completed = runner(
            argv,
            cwd=str(worktree),
            # The dispatcher's lineage stamp when the caller passed one: a
            # declared verification command is a child of this dispatch too,
            # and a depth guard a command can shell around is not a guard.
            env=environment,
            text=True,
            capture_output=True,
            timeout=effective_timeout,
            **({"confinement_command": confinement_command} if confinement_command is not None else {}),
        )
        exit_code = int(getattr(completed, "returncode", 1))
        combined = (
            f"{getattr(completed, 'stdout', '') or ''}{getattr(completed, 'stderr', '') or ''}"
        )
    except FileNotFoundError:
        return "failed", f"{argv[0]} not found on PATH", None
    except subprocess.TimeoutExpired:
        return "failed", f"timed out after {effective_timeout}s", None
    except (OSError, subprocess.SubprocessError, TypeError, ValueError) as exc:
        return "failed", f"could not run: {exc}", None
    if exit_code == 0:
        return "passed", "", None
    # The bound is the same 300 it always was; what changed is that the bytes it
    # drops are now written whole to a content-addressed spill and the row
    # carries a pointer to them, so a reader chasing a failure is not left with
    # the last 300 bytes of a build log and no way back to the rest.
    bounded = truncate_output(
        combined,
        limit_bytes=_MAX_VERIFICATION_OUTPUT_TAIL,
        source=f"fanout unit verification command: {command}",
        keep="tail",
        spill_dir=spill_dir,
    )
    tail = redact_metadata_text(bounded.kept_text, limit=_MAX_VERIFICATION_OUTPUT_TAIL)
    notice = truncation_notice(bounded.record)
    detail = f"exit {exit_code}: {tail}"
    return "failed", f"{detail} {notice}" if notice else detail, bounded.record


def _run_planned_verification(
    paths: OmhPaths,
    unit: Mapping[str, Any],
    *,
    fanout_id: str,
    run_ref: str,
    unit_id: str,
    worktree: Path,
    owner: str,
    runner: Callable[..., Any],
    child_env: Mapping[str, str] | None,
    wave_width: int,
    execution_gate: VerificationExecutionGate | None,
    integration_ready: Callable[[], bool],
    required_revision: str | None = None,
    post_integration: bool = False,
    producer_evidence: bool = False,
    confinement: FanoutFilesystemConfinement | None = None,
) -> dict[str, Any]:
    """Run a metadata-carrying unit's checks through the revision-bound plan engine.

    Rows keep the exact dispatcher-observed shape the legacy loop writes (plus
    additive `check_id`/`tier`/`reused` keys) and pass through the same
    `validate_check_rows` gate. The `unit_verification_observed` journal event
    is appended only when every check holds fresh or reused in-scope passing
    evidence: a failed, blocked, or fan-in-deferred check appends nothing,
    which is the HOLD semantics the aggregate has always had. Integration-tier
    checks defer while `integration_ready` is closed; the post-pool fan-in
    wave re-resolves the plan with the gate open and unit-tier receipts then
    share the one process the worker already ran.
    """
    plan = compile_verification_plan(unit, fanout_id=fanout_id, unit_id=unit_id)
    if plan is None:
        return {}
    revision = _verification_worktree_revision(runner, worktree)
    if required_revision is not None and revision != required_revision:
        revision = None
    execution_environment = verification_execution_environment(
        os.environ if child_env is None else child_env
    )
    context = PlanRunContext(
        paths=paths,
        worktree=worktree,
        revision=revision,
        max_workers=max(1, wave_width),
        integration_ready=integration_ready,
        single_flight=_VERIFICATION_SINGLE_FLIGHT,
        execution_environment=execution_environment,
        execution_gate=execution_gate,
    )

    def run_node(node: Any) -> tuple[str, str, dict[str, Any] | None]:
        return _run_verification_command(
            node.command,
            worktree,
            runner,
            execution_environment,
            spill_dir=paths.runtime_output_spills_dir,
            timeout=node.timeout,
            confinement=confinement,
        )

    result = (
        run_post_integration_verification(
            context, plan, producer_evidence=producer_evidence, run_node=run_node
        )
        if post_integration
        else run_verification_plan(context, plan, run_node=run_node)
    )
    rows: list[dict[str, object]] = []
    for outcome in result.outcomes:
        row: dict[str, object] = {
            "command": outcome.node.command,
            "status": outcome.status,
            "evidence_ref": f"journal:{UNIT_VERIFICATION_OBSERVATION_SOURCE}:{run_ref}",
            "reported_by": "dispatcher",
            "observed_by": "dispatcher",
            "observation_source": UNIT_VERIFICATION_OBSERVATION_SOURCE,
            "check_id": outcome.node.check_id,
            "tier": outcome.node.tier,
        }
        if outcome.reused and outcome.receipt_key:
            row["reused"] = True
            row["receipt_ref"] = f"verification_receipt:{outcome.receipt_key}"
        if outcome.status == "skipped" and outcome.detail:
            row["note"] = outcome.detail
        rows.append(row)
    validated_rows = validate_check_rows(rows)
    if result.all_passed:
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
        "verification_status": (
            "passed" if result.all_passed else ("held" if result.deferred and not result.failures else "failed")
        ),
        "verification_checks": validated_rows,
        "verification_claim_boundary": UNIT_VERIFICATION_CLAIM_BOUNDARY,
        "verification_plan_schema": VERIFICATION_PLAN_SCHEMA_VERSION,
    }
    receipt_keys = sorted(
        {outcome.receipt_key for outcome in result.outcomes if outcome.receipt_key}
    )
    if receipt_keys:
        verification["verification_receipts"] = receipt_keys
    if result.failures:
        verification["verification_failures"] = result.failures
    if result.truncations:
        verification["verification_output_truncation"] = result.truncations
    if result.deferred and not result.failures:
        verification["verification_integration_deferred"] = True
    return verification


def _producer_verification_is_sufficient(entry: Mapping[str, Any]) -> bool:
    """Whether one producer's unit-tier verification passed or was absent."""
    if not (entry.get("process_succeeded") and entry.get("result_schema_valid")):
        return False
    rows = entry.get("verification_checks")
    if not isinstance(rows, list):
        return True
    unit_rows = [row for row in rows if isinstance(row, Mapping) and row.get("tier", "unit") == "unit"]
    return all(row.get("status") == "passed" for row in unit_rows)


def _integration_tier_verification_passed(
    results: Mapping[str, Mapping[str, object]], selected_unit_ids: set[str]
) -> bool:
    """Whether every selected producer has dispatcher-observed integration GREEN."""
    if not selected_unit_ids:
        return False
    for unit_id in selected_unit_ids:
        entry = results.get(unit_id)
        rows = entry.get("verification_checks") if entry is not None else None
        if not isinstance(rows, list) or not any(
            isinstance(row, Mapping)
            and row.get("tier") == "integration"
            and row.get("status") == "passed"
            for row in rows
        ):
            return False
    return True


def _integrated_checkout_contains_producer_heads(
    runner: Callable[..., Any], integrated_worktree: Path, results: Mapping[str, dict[str, Any]]
) -> bool:
    """Prove the supplied checkout contains every dispatcher-observed producer commit."""
    for entry in results.values():
        head_sha = entry.get("producer_head_sha")
        if not isinstance(head_sha, str) or re.fullmatch(r"[0-9a-f]{40}", head_sha) is None:
            return False
        if _git_text(
            runner, integrated_worktree, ["git", "merge-base", "--is-ancestor", head_sha, "HEAD"]
        ) is None:
            return False
    return True


def _run_integration_verification_wave(
    paths: OmhPaths,
    *,
    results: Mapping[str, dict[str, Any]],
    units: Mapping[str, Mapping[str, Any]],
    order: Sequence[str],
    selected_unit_ids: set[str],
    runner: Callable[..., Any],
    wave_width: int,
    fanout_id: str,
    integrated_worktree: Path | None,
    integrated_revision: str | None,
    execution_gate: VerificationExecutionGate,
    diagnostic_engine: DiagnosticExecutionEngine | None,
) -> None:
    """Run integration-tier checks once the producer lanes have fanned in.

    Reached after the dispatch pool drained, so every selected unit is
    terminal by construction — that fan-in is the gate the worker deferred
    on. Only units whose unit-tier evidence all passed (`held`) re-resolve;
    the engine then runs just their integration-tier checks while unit-tier
    checks resolve as receipt reuses of the one process the worker ran. A
    pass appends the same `unit_verification_observed` event the worker
    withheld, and the ladder projection after this wave folds it in.
    """
    if integrated_worktree is None or not integrated_revision:
        return
    producer_results = {
        unit_id: results[unit_id] for unit_id in selected_unit_ids if unit_id in results
    }
    producer_evidence = bool(producer_results) and all(
        _producer_verification_is_sufficient(entry) for entry in producer_results.values()
    )
    producer_evidence = producer_evidence and _integrated_checkout_contains_producer_heads(
        runner, integrated_worktree, producer_results
    )
    for unit_id in order:
        if unit_id not in selected_unit_ids:
            continue
        entry = results.get(unit_id)
        unit = units.get(unit_id)
        if entry is None or unit is None or not entry.get("verification_integration_deferred"):
            continue
        integration_environment = verification_execution_environment(os.environ)
        integration_argv: list[list[str]] = []
        for command in declared_verification_commands(unit):
            try:
                _overrides, check_argv = verification_command_argv(command)
            except FanoutContractError:
                continue
            integration_argv.append(check_argv)
        integration_confinement = (
            prepare_fanout_filesystem_confinement(
                integrated_worktree, integration_environment, tuple(integration_argv)
            )
            if runner is signal_safe_unit_runner
            else None
        )
        if integration_confinement is not None:
            integration_environment = integration_confinement.command_environment()
        rerun = _run_planned_verification(
            paths,
            unit,
            fanout_id=fanout_id,
            run_ref=str(entry["run_ref"]),
            unit_id=unit_id,
            worktree=integrated_worktree,
            owner=str(entry.get("owner") or "choose"),
            runner=runner,
            child_env=integration_environment,
            wave_width=wave_width,
            execution_gate=execution_gate,
            integration_ready=lambda: True,
            required_revision=integrated_revision,
            post_integration=True,
            producer_evidence=producer_evidence,
            confinement=integration_confinement,
        )
        if not rerun:
            continue
        integration_rows = rerun.pop("verification_checks", [])
        unit_rows = [
            row for row in entry.get("verification_checks", []) if row.get("tier") != "integration"
        ]
        entry["verification_checks"] = [*unit_rows, *integration_rows]
        entry["integration_filesystem_confinement"] = confinement_receipt(
            integration_confinement, integrated_worktree
        )
        entry.pop("verification_integration_deferred", None)
        entry.pop("verification_failures", None)
        entry.update(rerun)
        entry["unit_verification_observed"] = _unit_verification_is_observed(paths, str(entry["run_ref"]))
        if diagnostic_engine is not None and diagnostic_engine.settings.enabled:
            diagnostics = run_post_green_diagnostics(
                diagnostic_engine,
                owner=str(entry.get("owner") or "choose"),
                workspace_id=f"{fanout_id}:{unit_id}:integrated",
                workspace_path=str(integrated_worktree),
                baseline_revision=str(entry.get("unit_result", {}).get("base_sha", "")),
                end_revision=integrated_revision,
                verification_passed=entry.get("verification_status") == "passed",
                producer_evidence=(
                    producer_evidence
                    and _verification_worktree_revision(runner, integrated_worktree) == integrated_revision
                ),
            )
            if diagnostics is not None:
                entry.update(diagnostics)


def _run_unit_verification(
    paths: OmhPaths,
    unit: Mapping[str, Any],
    *,
    run_ref: str,
    unit_id: str,
    worktree: Path,
    owner: str,
    runner: Callable[..., Any],
    child_env: Mapping[str, str] | None = None,
    fanout_id: str = "",
    wave_width: int = 1,
    execution_gate: VerificationExecutionGate | None = None,
    confinement: FanoutFilesystemConfinement | None = None,
) -> dict[str, Any]:
    """Run one unit's declared verification commands and record what was observed.

    Every row is dispatcher-reported AND dispatcher-observed: omh ran the
    command itself, which is the only way the result schema allows an
    observation to be claimed. All rows passing is what appends the per-unit
    `unit_verification_observed` journal event, so the ladder flips from the
    same evidence an operator would otherwise record by hand. Any failure
    appends nothing, leaving the unit short of `integration_ready`.

    A unit carrying `verification_checks` metadata runs through the
    revision-bound plan engine instead of the serial loop below; a
    metadata-free unit keeps the legacy loop byte-for-byte.
    """
    commands = declared_verification_commands(unit)
    if not commands:
        return {}
    if unit.get("verification_checks"):
        return _run_planned_verification(
            paths,
            unit,
            fanout_id=fanout_id,
            run_ref=run_ref,
            unit_id=unit_id,
            worktree=worktree,
            owner=owner,
            runner=runner,
            child_env=child_env,
            wave_width=wave_width,
            execution_gate=execution_gate,
            integration_ready=lambda: False,
            confinement=confinement,
        )
    rows: list[dict[str, object]] = []
    failures: list[str] = []
    truncations: list[dict[str, Any]] = []
    for command in commands:
        def run_command(command: str = command) -> tuple[str, str, dict[str, Any] | None]:
            return _run_verification_command(
                command,
                worktree,
                runner,
                child_env,
                spill_dir=paths.runtime_output_spills_dir,
                confinement=confinement,
            )

        outcome = (
            run_command()
            if execution_gate is None
            else execution_gate.submit_legacy(run_command).result()
        )
        status, detail, truncation = outcome
        if truncation is not None:
            truncations.append(truncation)
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
    # Carried whenever a command produced captured output, truncated or not.
    # The failure strings already read the notice inline; this is the same
    # thing in a form a consumer can branch on without parsing prose.
    if truncations:
        verification["verification_output_truncation"] = truncations
    return verification


def dispatch_fanout(
    paths: OmhPaths,
    contract: Mapping[str, Any],
    *,
    goal_text: str,
    repo_root: Path,
    base_sha: str,
    source_ref: str = "",
    # Conservative library fallback only: the CLI resolves the pool width
    # from the setup profile's `parallelism` block (default 5, ceiling 8).
    concurrency: int = 2,
    adaptive_concurrency: bool = False,
    timeout: int = 1800,
    only_units: Sequence[str] | None = None,
    dry_run: bool = False,
    run_verification: bool = False,
    integrated_worktree: Path | None = None,
    integrated_revision: str | None = None,
    runner: Callable[..., Any] = signal_safe_unit_runner,
    readiness: Callable[..., dict[str, object]] = probe_executor_readiness,
    live_safety_profile_revision: str | None = None,
    per_owner_lanes: Mapping[str, int] | None = None,
    concurrency_policy: Mapping[str, Any] | None = None,
    max_depth: int | None = None,
    spawn_ceiling: int | None = None,
    env: Mapping[str, str] | None = None,
    # A prior run's terminal-state journal. Present, it decides per unit
    # whether this dispatch attempts it again; absent, every selected unit is
    # attempted exactly as before.
    resume_journal: Mapping[str, Any] | None = None,
    # The retry policy's two impure inputs, injected so the whole ladder is
    # assertable without a clock and without a single sleep in a test.
    max_retries: int = FANOUT_MAX_RETRIES,
    rng: Callable[[], float] = random.random,
    sleep: Callable[[float], None] = time.sleep,
    # Failure-recovery inputs. `on_failure` is the closed degradation mode
    # (`report` changes nothing, which is the pre-recovery behavior); the
    # interview only ever runs when the caller states BOTH that this session is
    # interactive and how to read a line, so nothing here can block on a
    # terminal that is not there.
    ignore_limit_signal: bool = False,
    on_failure: str = ON_FAILURE_REPORT,
    retarget_owner: str = "",
    interactive: bool = False,
    read_line: Callable[[str], str] | None = None,
    write_line: Callable[[str], None] | None = None,
    hermes_routing: Mapping[str, Any] | None = None,
    hermes_child: Callable[..., Mapping[str, Any]] | None = None,
    goal_attempt_id: str = "attempt-1",
    goal_attempt_progressed: bool = False,
    review_dispatch_budget: int = 1,
    diagnostic_engine: DiagnosticExecutionEngine | None = None,
    final_review_engine: FinalReviewWaveEngine | None = None,
    emit_health_events: bool = False,
    health_clock: Callable[[], int] = monotonic_milliseconds,
) -> dict[str, Any]:
    # The spawn guard runs before every other check, including the two
    # boundary re-checks below: it is the only one whose whole job is that no
    # subprocess starts, and a refusal must not depend on a contract read, a
    # readiness probe, or a worktree first.
    guard_env: Mapping[str, str] = os.environ if env is None else env
    effective_max_depth = FANOUT_MAX_DEPTH_DEFAULT if max_depth is None else max(1, int(max_depth))
    current_depth = read_fanout_depth(guard_env)
    if current_depth >= effective_max_depth:
        depth_decision = resolve_approval_tier(
            "fanout_recursion_depth", posture=resolve_security_posture(guard_env)
        )
        if depth_decision.tier != TIER_AUTO_ALLOWED:
            summary = _depth_refusal_summary(
                contract,
                dry_run=dry_run,
                base_sha=base_sha,
                depth=current_depth,
                max_depth=effective_max_depth,
                lineage=str(guard_env.get(FANOUT_LINEAGE_ENV_VAR, "") or ""),
            )
            if adaptive_concurrency:
                summary["adaptive_admission"] = AdaptiveFanoutAdmission(
                    ceiling=concurrency,
                    dry_run=dry_run,
                ).receipt()
            return summary
    spawn_ledger = _SpawnLedger(
        FANOUT_RUN_SPAWN_CEILING_DEFAULT if spawn_ceiling is None else spawn_ceiling
    )
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
    health_events = (
        FanoutHealthEvents(
            fanout_id=fanout_id,
            revision=base_sha,
            emit=lambda event: write_fanout_health_event(paths, fanout_id, event),
            clock=health_clock,
        )
        if emit_health_events and fanout_id
        else None
    )
    review_budget = ReviewDispatchBudget(
        paths=paths,
        fanout_id=fanout_id,
        attempt_id=goal_attempt_id,
        limit=review_dispatch_budget,
        progressed=goal_attempt_progressed,
    )
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
    # Read once, before any unit is considered: the plan is a pure function of
    # the prior journal and the contract's own dependency edges, so it is the
    # same plan on every machine and can be printed before anything spawns.
    resume_plan = (
        None
        if resume_journal is None
        else plan_fanout_resume(
            resume_journal,
            order=order,
            depends_on={
                unit_id: [str(dep) for dep in (unit.get("depends_on") or [])]
                for unit_id, unit in units.items()
            },
        )
    )
    resume_decisions: dict[str, Mapping[str, Any]] = (
        {}
        if resume_plan is None
        else {str(decision["unit_id"]): decision for decision in resume_plan["decisions"]}
    )

    if selected_capability_invalid:
        invalid_reason = (
            "selected batch refused because capability evidence is invalid for "
            + ", ".join(invalid_units)
        )
        for unit_id in order:
            unit = units[unit_id]
            held = _resume_hold(paths, unit, resume_decisions.get(unit_id))
            if held is not None:
                results[unit_id] = held
                continue
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
                    "status": _capability_refusal_status(errors),
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
        # The resume verdict is read BEFORE the completion probe on purpose: a
        # unit the journal held as replay-unsafe must stay held even where the
        # run journal it would be probed against has since been pruned.
        held = _resume_hold(paths, unit, resume_decisions.get(unit_id))
        if held is not None:
            results[unit_id] = held
        elif _already_completed(paths, unit):
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
    admission = (
        AdaptiveFanoutAdmission(ceiling=concurrency, dry_run=dry_run)
        if adaptive_concurrency
        else None
    )
    # Per-owner lanes (OMO's per-provider limiter, reduced to what this
    # blocking pool can honor): only owners the policy names get a lane
    # semaphore — the global pool alone governs everyone else. The gate
    # wraps the unit's WHOLE lifecycle (readiness probe, worktree, spawn,
    # and local verification when requested), so an over-subscribed owner
    # holds a pool slot while it waits and can delay other owners' ready
    # units queued behind it; with the pool sized to the global
    # ceiling that is the same trade OMO's global permit makes.
    owner_gates = {
        owner: threading.BoundedSemaphore(int(width))
        for owner, width in (per_owner_lanes or {}).items()
        if isinstance(width, int) and not isinstance(width, bool) and int(width) >= 1
    }
    # One stagger per run: real spawns of this fanout space out so the first
    # request writes the provider prompt cache the siblings read. It engages
    # only for runners carrying the real-runner `accepts_on_spawn` seam, so
    # injected test runners and dry runs never wait.
    spawn_stagger = _SpawnStagger(CACHE_WARM_SPAWN_STAGGER_SECONDS)
    verification_execution_gate = (
        VerificationExecutionGate(max(1, concurrency)) if run_verification and not dry_run else None
    )
    # Every per-unit argument except the unit and its capability precheck.
    # Named once so the post-run recovery pass re-dispatches a retargeted unit
    # through exactly the arguments the pool used, rather than a second
    # hand-maintained copy of them that would drift on the next new parameter.
    unit_dispatch_kwargs: dict[str, Any] = {
        "goal_text": goal_text,
        "repo_root": repo_root,
        "base_sha": base_sha,
        "source_ref": source_ref,
        "timeout": timeout,
        "dry_run": dry_run,
        "run_verification": run_verification,
        "runner": runner,
        "readiness": readiness,
        "current_catalog_digest": current_catalog_digest,
        "fanout_id": fanout_id,
        "discoveries": discoveries,
        "spawn_stagger": spawn_stagger,
        "spawn_ledger": spawn_ledger,
        "dispatch_depth": current_depth,
        "base_env": guard_env,
        "max_retries": max_retries,
        "rng": rng,
        "sleep": sleep,
        "ignore_limit_signal": ignore_limit_signal,
        "review_budget": review_budget,
        # The check wave inside each unit rides the same policy-resolved width
        # as the unit pool itself — never a new unbounded pool.
        "verification_wave_width": max(1, concurrency),
        "verification_execution_gate": verification_execution_gate,
        # One caller-owned engine carries its cache and single-flight identity
        # across every eligible unit in this dispatch.
        "diagnostic_engine": diagnostic_engine,
        "health_events": health_events,
    }

    def _dispatch_with_owner_gate(unit: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        # A worker that reaches its turn after the interrupt — queued in the
        # pool, or parked on the owner gate while the batch died — must not
        # start a fresh agent CLI nobody will ever collect.
        if _INTERRUPT_FLAG.is_set():
            return _skipped(unit, UNIT_STATUS_NOT_STARTED_CANCELLED)
        gate = owner_gates.get(str(unit.get("owner") or "choose"))
        if gate is None:
            if health_events is not None:
                health_events.started(str(unit["unit_id"]))
            return _dispatch_unit(paths, unit, **kwargs)
        with gate:
            if _INTERRUPT_FLAG.is_set():
                return _skipped(unit, UNIT_STATUS_NOT_STARTED_CANCELLED)
            if health_events is not None:
                health_events.started(str(unit["unit_id"]))
            return _dispatch_unit(paths, unit, **kwargs)

    # SIGTERM must not orphan the spawned agent CLIs (OMO's launcher
    # incident): the handler terminates every live unit group and raises so
    # the interrupt path below records the batch honestly, then the original
    # signal is re-raised to the caller — a supervisor still observes the
    # death it asked for. Installed only in the main thread; anywhere else
    # Python forbids signal.signal and the default disposition stands.
    # One dispatch per process is the supported shape, so clearing the
    # interrupt flag here cannot strand another run's interrupt.
    _INTERRUPT_FLAG.clear()
    installed_term = False
    previous_term: Any = None
    interrupted_by: BaseException | None = None
    futures: dict[str, Any] = {}
    pool = ThreadPoolExecutor(max_workers=max(1, concurrency))
    try:
        if threading.current_thread() is threading.main_thread():
            def _on_sigterm(signum: int, frame: Any) -> None:
                terminate_live_unit_groups()
                raise SystemExit(128 + signum)

            previous_term = signal.signal(signal.SIGTERM, _on_sigterm)
            installed_term = True
        # Dependency-frontier admission, learned from OMO's DAG scheduler: a
        # unit is admitted the moment EVERY unit it depends on completed —
        # never because a wave boundary was reached — so an unrelated slow
        # sibling cannot starve ready dependents behind a barrier the
        # contract never promised. `merge_order`'s wave grouping is
        # informational from here on; admission is per-completion.
        def _submit(unit_id: str) -> None:
            if health_events is not None:
                health_events.queued(
                    unit_id,
                    dependencies=tuple(str(dep) for dep in units[unit_id].get("depends_on", []) or []),
                    resource_class=str(units[unit_id].get("owner") or "choose"),
                )
            futures[unit_id] = pool.submit(
                _dispatch_with_owner_gate,
                units[unit_id],
                **unit_dispatch_kwargs,
                capability_precheck=capability_prechecks[unit_id],
            )

        def _admit_frontier() -> None:
            # Blocking on a failed dependency is safe to do eagerly here:
            # unit failure is terminal in this engine (no revive), unlike the
            # OMO scheduler whose quiescence-gated cascade protects revivable
            # nodes. The no-progress fallback below still catches a pending
            # set that can neither run nor block (validated cycles aside).
            for unit_id in list(pending):
                if unit_id in futures:
                    continue
                if any(_dependency_failed(results.get(dep)) for dep in units[unit_id].get("depends_on", [])):
                    results[unit_id] = _blocked(units[unit_id], results)
                    pending.remove(unit_id)
            available_slots = (
                admission.available_slots(
                    sum(1 for unit_id in pending if unit_id in futures)
                )
                if admission is not None
                else None
            )
            for unit_id in list(pending):
                if available_slots is not None and available_slots <= 0:
                    break
                if unit_id in futures:
                    continue
                if all(_dependency_satisfied(results.get(dep)) for dep in units[unit_id].get("depends_on", [])):
                    _submit(unit_id)
                    if available_slots is not None:
                        available_slots -= 1

        _admit_frontier()
        while pending:
            inflight = {unit_id: futures[unit_id] for unit_id in pending if unit_id in futures}
            if not inflight:
                # Nothing running and nothing admissible: the remainder can
                # only be waiting on units that will never complete.
                for unit_id in list(pending):
                    results[unit_id] = _blocked(units[unit_id], results)
                    pending.remove(unit_id)
                break
            done, _ = futures_wait(inflight.values(), return_when=FIRST_COMPLETED)
            for unit_id, future in inflight.items():
                if future in done:
                    result = future.result()
                    results[unit_id] = result
                    if admission is not None:
                        admission.observe(unit_id, result)
                    pending.remove(unit_id)
            _admit_frontier()
        pool.shutdown(wait=True)
    except (KeyboardInterrupt, SystemExit) as exc:
        # Ctrl-C or a handled SIGTERM: stop admitting work, kill every live
        # unit group (children run in their own sessions now, so the tty no
        # longer delivers SIGINT to them), collect what the killed workers
        # still return, and mark everything never started as interrupted —
        # a unit silently missing from the rollup would read as never
        # planned rather than cut short.
        interrupted_by = exc
        _INTERRUPT_FLAG.set()
        pool.shutdown(wait=False, cancel_futures=True)
        terminate_live_unit_groups()
        for unit_id, future in list(futures.items()):
            if unit_id in results:
                continue
            try:
                result = future.result(timeout=UNIT_TERMINATE_GRACE_SECONDS + 5)
                results[unit_id] = result
                if admission is not None:
                    admission.observe(unit_id, result)
            except (FuturesCancelledError, KeyboardInterrupt, SystemExit):
                # `shutdown(cancel_futures=True)` cancels only futures the pool
                # never started, so a cancelled future is a unit that never
                # spawned: there is nothing on disk to preserve.
                results[unit_id] = _skipped(units[unit_id], UNIT_STATUS_NOT_STARTED_CANCELLED)
            except FuturesTimeoutError:
                # It was in flight and did not come back inside the terminate
                # grace. Whether it wrote anything is genuinely unknown, and a
                # resume has to ask rather than assume either way.
                results[unit_id] = _skipped(units[unit_id], UNIT_STATUS_CANCELLED_OUTCOME_UNKNOWN)
            if unit_id in pending:
                pending.remove(unit_id)
        for unit_id in list(pending):
            if unit_id not in results:
                results[unit_id] = _skipped(units[unit_id], UNIT_STATUS_NOT_STARTED_CANCELLED)
            pending.remove(unit_id)
        # A group-terminated unit exits with a negative signal code. Reported as
        # `failed` it reads as a genuine model failure in the merged summary and
        # sends the next reader hunting a defect that does not exist, so the
        # observed termination is recorded as the terminal state it was. The
        # failure classification goes with it: a stop is not a crash, and a
        # cancelled unit's `failure_kind` would otherwise steer the recovery
        # interview toward a fault nobody observed.
        for entry in results.values():
            exit_code = entry.get("exit_code")
            if isinstance(exit_code, int) and exit_code < 0:
                entry["interrupted"] = True
                entry["status"] = UNIT_STATUS_CANCELLED
                entry.pop("failure_kind", None)
                entry.pop("limit_shaped", None)
                entry.pop("limit_pattern", None)
    finally:
        # Idempotent after the success/interrupt shutdowns; without it, a
        # worker exception re-raised by future.result() leaks live pool
        # threads that the interpreter then joins at exit. A plain exception
        # unwinding here (not the handled interrupt) must also not orphan
        # live agent groups — the same hazard the signal path closes.
        if sys.exc_info()[0] is not None and interrupted_by is None:
            terminate_live_unit_groups()
            if verification_execution_gate is not None:
                verification_execution_gate.shutdown()
        pool.shutdown(wait=False, cancel_futures=True)
        if installed_term:
            signal.signal(signal.SIGTERM, previous_term)

    try:
        # Recovery runs on the collected results and before the summary is built, so
        # a retarget attempt's own outcome and a `wait` mark are both in hand when
        # the run journal is projected. An interrupted batch is skipped entirely:
        # the operator already asked for it to stop.
        failure_recovery = (
            None
            if (dry_run or interrupted_by is not None)
            else _run_failure_recovery(
                paths,
                results=results,
                order=order,
                units=units,
                repo_root=repo_root,
                timeout=timeout,
                mode=on_failure,
                retarget_owner=retarget_owner,
                interactive=interactive,
                read_line=read_line,
                write_line=write_line,
                hermes_routing=hermes_routing,
                hermes_child=hermes_child,
                unit_dispatch_kwargs=unit_dispatch_kwargs,
            )
        )
        # The fan-in gate the unit workers deferred integration-tier checks on:
        # the pool has drained, so every selected unit is terminal and those
        # checks may run now — once per integrated revision, with unit-tier
        # receipts sharing the process the worker already ran.
        if run_verification and not dry_run and interrupted_by is None and verification_execution_gate is not None:
            _run_integration_verification_wave(
                paths,
                results=results,
                units=units,
                order=order,
                selected_unit_ids=selected,
                runner=runner,
                wave_width=max(1, concurrency),
                fanout_id=fanout_id,
                integrated_worktree=integrated_worktree,
                integrated_revision=integrated_revision,
                execution_gate=verification_execution_gate,
                diagnostic_engine=diagnostic_engine,
            )
    finally:
        if verification_execution_gate is not None:
            verification_execution_gate.shutdown()
    final_review: dict[str, object] | None = None
    if final_review_engine is not None:
        current_integrated_revision = (
            _verification_worktree_revision(runner, integrated_worktree)
            if integrated_worktree is not None
            else None
        )
        producer_results = {unit_id: results[unit_id] for unit_id in selected if unit_id in results}
        producer_evidence = (
            len(producer_results) == len(selected)
            and bool(producer_results)
            and integrated_worktree is not None
            and all(_producer_verification_is_sufficient(entry) for entry in producer_results.values())
            and _integrated_checkout_contains_producer_heads(runner, integrated_worktree, producer_results)
        )
        integration_green = (
            _integration_tier_verification_passed(results, selected)
            and current_integrated_revision == integrated_revision
        )
        review_task = f"{fanout_id}:review"
        if health_events is not None and integration_green and producer_evidence:
            health_events.queued(
                review_task,
                dependencies=tuple(sorted(selected)),
                resource_class="final_review",
                phase="review",
                revision=current_integrated_revision,
            )
            health_events.started(review_task, phase="review")
        final_review = run_final_review_after_integration(
            final_review_engine,
            integrated_revision=integrated_revision or "",
            integration_green=integration_green,
            producer_evidence=producer_evidence,
            workspace_revision=(
                lambda: _verification_worktree_revision(
                    runner, integrated_worktree
                )
                if integrated_worktree is not None
                else None
            ),
        )
        if health_events is not None and integration_green and producer_evidence:
            health_events.finished(
                review_task,
                terminal_status=(
                    "succeeded" if final_review.get("final_review_status") == "PASS" else "failed"
                ),
                phase="review",
            )
    summary_units = [results[unit_id] for unit_id in order]
    for entry in summary_units:
        decision = resume_decisions.get(str(entry.get("unit_id", "")))
        if decision is not None and "resume" not in entry:
            # A re-dispatched unit says which resume rule admitted it, so the
            # summary answers "why did this run again" without the reader
            # having to join it back against the plan.
            entry["resume"] = _resume_note(decision)
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
    if final_review is not None:
        summary.update(final_review)
    summary["review_dispatch_budget"] = {
        "schema_version": "fanout_review_dispatch_budget/v1",
        "attempt_id": review_budget.attempt_id,
        "limit_per_role": review_budget.limit,
        "progressed": review_budget.progressed,
        "state_path": str(review_budget.path),
        "claim_boundary": "Budget accounting is not review, verification, CI, or merge evidence.",
    }
    if admission is not None:
        summary["adaptive_admission"] = admission.receipt()
    if concurrency_policy:
        # How the pool width was chosen (policy default vs flag, any clamp)
        # so a dispatch record answers "why did only N run at once".
        summary["concurrency"] = dict(concurrency_policy)
    # The bounds this run actually ran under, and how much of the budget it
    # used: a unit refused as `spawn_ceiling_reached` is otherwise the only
    # trace, and a summary that hit the ceiling exactly should say so.
    summary["spawn_guard"] = {
        "depth": current_depth,
        "max_depth": effective_max_depth,
        "run_spawn_ceiling": spawn_ledger.ceiling,
        "spawns_claimed": spawn_ledger.claimed,
        "claim_boundary": FANOUT_SPAWN_GUARD_CLAIM_BOUNDARY,
    }
    if failure_recovery is not None:
        summary["failure_recovery"] = failure_recovery
    if resume_plan is not None:
        summary["resume"] = {**resume_plan, "counts": resume_counts(resume_plan["decisions"])}
    if interrupted_by is not None:
        # A cut-short batch says so; units that never started carry the
        # `not_started_cancelled` status rather than silently vanishing from the
        # rollup as if they were never planned.
        summary["interrupted"] = True
        # Which units ended in which cancellation state, so the summary answers
        # "what happened to each of them" without a reader re-deriving it from
        # per-unit rows. Present only on a cancelled batch: an ordinary dispatch
        # has nothing to say here and should not carry an empty section.
        summary["cancellation"] = _cancellation_rollup(summary_units)
    if not dry_run and fanout_id:
        from .fanout_artifacts import fanout_dispatch_summary_path, fanout_run_journal_path

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
        # Written last, from the carried-forward view: the replay-safety
        # verdict a later resume reads is the recovery record's own answer,
        # and a unit whose recovery was carried rather than re-captured must
        # not be journalled as unmeasured. The write is temp-then-rename, so
        # an interrupted resume still leaves the previous journal intact.
        journal = build_fanout_run_journal(summary)
        summary["run_journal_path"] = str(
            write_fanout_run_journal(fanout_run_journal_path(paths, fanout_id), journal)
        )
    if isinstance(interrupted_by, SystemExit):
        # The summary is written; now honor the termination that was asked
        # for, so a supervisor still observes the death it requested (OMO's
        # launcher discipline). Ctrl-C returns the summary instead — the
        # operator is at the keyboard reading it.
        raise interrupted_by
    return summary


def _silent_write_line(_line: str) -> None:
    """Default narration sink: a library call prints nothing.

    The decisions and their options ride the summary, so a programmatic caller
    already has everything the narration would have said. The CLI passes a real
    writer (stderr, so a piped JSON stdout stays clean).
    """
    return None


def _run_failure_recovery(
    paths: OmhPaths,
    *,
    results: dict[str, dict[str, Any]],
    order: Sequence[str],
    units: Mapping[str, Mapping[str, Any]],
    repo_root: Path,
    timeout: int,
    mode: str,
    retarget_owner: str,
    interactive: bool,
    read_line: Callable[[str], str] | None,
    write_line: Callable[[str], None] | None,
    hermes_routing: Mapping[str, Any] | None,
    hermes_child: Callable[..., Mapping[str, Any]] | None,
    unit_dispatch_kwargs: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Offer, record, and carry out one recovery action per recoverable failure.

    Returns None when nothing failed recoverably, so a clean run's summary is
    byte-identical to what it was before this lane existed. Every decision is
    recorded whether or not it changed anything: `report` is a decision too, and
    an operator who was shown three options and picked none should be able to
    see that in the record.

    The one invariant this function exists to hold: no coding owner is ever
    switched without an explicit choice — an interview answer, or an explicit
    `--on-failure=retarget:<owner>` on the command line.
    """
    candidates = recovery_candidates([results[unit_id] for unit_id in order if unit_id in results])
    if not candidates:
        return None
    emit = write_line if write_line is not None else _silent_write_line
    hermes_available = hermes_routing_available(hermes_routing)
    context: dict[str, Any] | None = None

    def _choice_context() -> Mapping[str, Any]:
        nonlocal context
        if context is None:
            from .executor_readiness import executor_choice_context

            try:
                context = dict(executor_choice_context(paths))
            except (OSError, ValueError):
                # Ranking context is advisory. Losing it costs the operator the
                # readiness column on the retarget list, never the choice.
                context = {"candidates": []}
        return context

    decisions: list[dict[str, Any]] = []
    for candidate in candidates:
        unit_id = str(candidate["unit_id"])
        entry = results[unit_id]
        retargets = retarget_candidates(_choice_context(), exclude_owner=str(candidate["owner"]))
        options = recovery_options(
            candidate=candidate, retargets=retargets, hermes_available=hermes_available
        )
        chosen = _chosen_recovery(
            candidate=candidate,
            options=options,
            mode=mode,
            retarget_owner=retarget_owner,
            interactive=interactive,
            read_line=read_line,
            emit=emit,
        )
        decision = recovery_decision(
            candidate=candidate,
            choice=str(chosen["choice"]),
            target_owner=str(chosen.get("target_owner", "")),
            consent=HERMES_LANE_CONSENT if chosen["choice"] == CHOICE_HERMES else "",
            reason=str(chosen.get("reason", "")),
        )
        decision["options"] = options
        if entry.get("repair_card") is not None:
            decision["repair_card"] = entry["repair_card"]
        if decision["choice"] == CHOICE_RETARGET:
            decision["attempt"] = _retarget_dispatch(
                paths,
                unit=units[unit_id],
                new_owner=str(decision["target_owner"]),
                failed_owner=str(candidate["owner"]),
                unit_dispatch_kwargs=unit_dispatch_kwargs,
            )
        elif decision["choice"] == CHOICE_HERMES:
            decision["attempt"] = _hermes_recovery_dispatch(
                unit=units[unit_id],
                goal_text=str(unit_dispatch_kwargs["goal_text"]),
                repo_root=repo_root,
                timeout=timeout,
                routing=hermes_routing or {},
                hermes_child=hermes_child,
            )
        elif decision["choice"] == CHOICE_WAIT:
            # No re-dispatch: the mark on the unit is the whole action, and the
            # run journal turns it into the next resume's selection.
            entry["awaiting_retry"] = True
        entry["recovery_choice"] = {
            "choice": decision["choice"],
            "failure_kind": str(candidate["failure_kind"]),
            **({"target_owner": decision["target_owner"]} if decision.get("target_owner") else {}),
        }
        decisions.append(decision)
    return {
        "schema_version": FAILURE_RECOVERY_SCHEMA_VERSION,
        "mode": mode,
        "interactive": bool(interactive and read_line is not None),
        "decisions": decisions,
        "awaiting_retry_units": [
            str(decision["unit_id"]) for decision in decisions if decision["choice"] == CHOICE_WAIT
        ],
        "claim_boundary": FAILURE_RECOVERY_CLAIM_BOUNDARY,
    }


def _chosen_recovery(
    *,
    candidate: Mapping[str, Any],
    options: Sequence[Mapping[str, Any]],
    mode: str,
    retarget_owner: str,
    interactive: bool,
    read_line: Callable[[str], str] | None,
    emit: Callable[[str], None],
) -> dict[str, Any]:
    """Resolve one unit's recovery choice from the mode, or by asking.

    A named mode is obeyed without a prompt even on a terminal: the operator
    already answered on the command line. `report` prompts only when the caller
    stated the session is interactive AND supplied a reader — which is how a
    non-tty invocation can never block.
    """
    by_choice = {str(option.get("choice")): option for option in options}
    if mode == CHOICE_RETARGET:
        if retarget_owner == str(candidate.get("owner", "")):
            return {
                "choice": CHOICE_REPORT,
                "reason": f"--on-failure named {retarget_owner}, the owner that just failed",
            }
        return {"choice": CHOICE_RETARGET, "target_owner": retarget_owner}
    if mode == ON_FAILURE_HERMES:
        option = by_choice.get(CHOICE_HERMES, {})
        if not option.get("available"):
            return {"choice": CHOICE_REPORT, "reason": str(option.get("unavailable_reason", ""))}
        return {"choice": CHOICE_HERMES}
    if mode == ON_FAILURE_WAIT:
        return {"choice": CHOICE_WAIT}
    if interactive and read_line is not None:
        return prompt_recovery_choice(
            candidate=candidate, options=options, read_line=read_line, write_line=emit
        )
    _report_recovery_options(candidate=candidate, options=options, emit=emit)
    return {"choice": CHOICE_REPORT, "reason": "no recovery action was requested"}


def _report_recovery_options(
    *,
    candidate: Mapping[str, Any],
    options: Sequence[Mapping[str, Any]],
    emit: Callable[[str], None],
) -> None:
    emit(
        f"Unit {candidate.get('unit_id')} failed on {candidate.get('owner')} as "
        f"{candidate.get('failure_kind')}. Recovery options (none taken; pass --on-failure to choose):"
    )
    for option in options:
        suffix = "" if option.get("available") else f"  (unavailable: {option.get('unavailable_reason')})"
        emit(f"  [{option.get('key')}] {option.get('title')}{suffix}")


def _capability_refusal_status(errors: Sequence[str]) -> str:
    for status in ("modality_unknown", "modality_unsupported", "modality_transformation_unobserved"):
        if any(str(error).startswith(f"{status}:") for error in errors):
            return status
    return "capability_snapshot_invalid"


def _retarget_dispatch(
    paths: OmhPaths,
    *,
    unit: Mapping[str, Any],
    new_owner: str,
    failed_owner: str,
    unit_dispatch_kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-dispatch one failed unit under an explicitly chosen different owner.

    The attempt runs as a DERIVED unit id, which is what gives it its own
    worktree and branch. Reusing the failed unit's worktree would mean either
    building on state a refused spawn left behind or deleting an operator's
    directory, and this engine does neither — `worktree_creator` refuses a
    pre-existing path for exactly that reason.

    The frozen model route is dropped rather than carried across: a model id
    belongs to the CLI it was resolved for, and handing codex's route to claude
    substitutes a value the contract never froze for this owner. The retarget
    falls through to the new owner's own dispatch-model preference, or its CLI
    default, both of which are recorded.
    """
    from .executor_capability_snapshots import (
        ExecutorCapabilitySnapshotError,
        resolved_executor_capability_snapshot,
    )

    unit_id = str(unit.get("unit_id", ""))
    retarget_id = f"{unit_id}-retarget-{new_owner}"
    try:
        snapshot = resolved_executor_capability_snapshot(
            new_owner, paths.executor_capability_snapshots_dir
        )
    except (ExecutorCapabilitySnapshotError, ValueError) as exc:
        return {
            "unit_id": retarget_id,
            "owner": new_owner,
            "status": "capability_snapshot_invalid",
            "reason": str(exc),
        }
    handoff = dict(unit.get("handoff") or {})
    handoff["executor_target"] = new_owner
    handoff["executor_capability_snapshot"] = snapshot
    handoff["executor_capability_snapshot_policy"] = "frozen_required"
    handoff.pop("model_route", None)
    decision = build_executor_modality_decision(
        input_representation=handoff.get("input_representation", "text_only"),
        snapshot=snapshot,
        transformation=handoff.get("executor_modality_decision", {}).get("transformation")
        if isinstance(handoff.get("executor_modality_decision"), Mapping)
        else None,
    )
    handoff["executor_modality_decision"] = decision
    if decision["verdict"] != "dispatch":
        return {
            "unit_id": retarget_id,
            "owner": new_owner,
            "status": str(decision["verdict"]),
            "reason": str(decision["fallback_reason"] or decision["remaining_user_action"]),
            "retargeted_from": {"unit_id": unit_id, "owner": failed_owner},
        }
    retargeted = {
        **dict(unit),
        "unit_id": retarget_id,
        "run_ref": f"{unit.get('run_ref', unit_id)}-retarget-{new_owner}",
        "owner": new_owner,
        "branch_suggestion": f"agent/{retarget_id}",
        "handoff": handoff,
        "depends_on": [],
    }
    result = _dispatch_unit(
        paths,
        retargeted,
        **{**dict(unit_dispatch_kwargs), "ignore_limit_signal": False},
        capability_precheck=(new_owner, snapshot, []),
    )
    result["retargeted_from"] = {"unit_id": unit_id, "owner": failed_owner}
    return result


def _hermes_recovery_dispatch(
    *,
    unit: Mapping[str, Any],
    goal_text: str,
    repo_root: Path,
    timeout: int,
    routing: Mapping[str, Any],
    hermes_child: Callable[..., Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Re-run one failed unit through the Hermes subagent lane, in its worktree.

    The child runs in the unit's OWN worktree or not at all: pointing it at the
    dispatch repo root would let a recovery attempt edit the operator's main
    checkout, which no unit of a fanout is ever allowed to do.
    """
    unit_id = str(unit.get("unit_id", ""))
    worktree = _worktree_path(repo_root, unit_id)
    if not worktree.is_dir():
        return {
            "unit_id": unit_id,
            "owner": "hermes",
            "status": "hermes_child_refused",
            "reason": (
                f"unit worktree {worktree} does not exist; the Hermes lane never runs against the "
                "dispatch repo root"
            ),
        }
    dispatcher = hermes_child if hermes_child is not None else dispatch_unit_via_hermes_child
    run_ref = str(unit.get("run_ref", unit_id))
    attempt = dispatcher(
        prompt=build_unit_prompt(unit, goal_text),
        routing=routing,
        parent_run_id=run_ref,
        run_id=f"{run_ref}-hermes-recovery",
        cwd=worktree,
        timeout_seconds=float(timeout),
    )
    return {
        "unit_id": unit_id,
        "owner": "hermes",
        "worktree_path": str(worktree),
        "consent": HERMES_LANE_CONSENT,
        **dict(attempt),
    }


def _depth_refusal_summary(
    contract: Mapping[str, Any],
    *,
    dry_run: bool,
    base_sha: str,
    depth: int,
    max_depth: int,
    lineage: str,
) -> dict[str, Any]:
    """The refusal a too-deeply-nested dispatch returns instead of spawning.

    Shaped as a dispatch summary so a wrapper parses one schema either way,
    with an empty `units` list because nothing ran and a machine-readable
    `refusal_reason` so the refusal is a code, not prose to grep. Never
    persisted: no unit was dispatched, and overwriting the stored summary
    would erase the parent run's observed telemetry with a blank.
    """
    return {
        "schema_version": FANOUT_DISPATCH_SCHEMA_VERSION,
        "fanout_id": contract.get("fanout_id", ""),
        "dry_run": dry_run,
        "observed_at": utc_now(),
        "merge_order": [],
        "units": [],
        "integration_ready_units": [],
        "recovery_available_units": [],
        "auto_merge": False,
        "refused": True,
        "refusal_reason": FANOUT_DEPTH_REFUSAL_REASON,
        "spawn_guard": {
            "depth": depth,
            "max_depth": max_depth,
            "lineage": lineage,
            "claim_boundary": FANOUT_SPAWN_GUARD_CLAIM_BOUNDARY,
        },
        "reason": (
            f"dispatch refused at depth {depth} (max_depth {max_depth}): a dispatched agent CLI "
            "must not start another fanout dispatch; run this contract from the operator's own shell"
        ),
        "base_sha": base_sha,
        "claim_boundary": f"{DISPATCH_CLAIM_BOUNDARY} {FANOUT_CLAIM_BOUNDARY}",
    }


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


def _cancellation_rollup(units: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Which units this cancelled batch stopped, never started, or lost track of.

    Metadata only: unit ids and the closed status words above, never output,
    prompts, or signal detail. `operator_initiated_cancel` is deliberately
    false-by-construction wording rather than a field: OMH RECORDS an observed
    cancellation, and the only cancellation it performs is of the process groups
    its own dispatcher spawned.
    """
    by_status: dict[str, list[str]] = {status: [] for status in sorted(CANCELLED_UNIT_STATUSES)}
    for entry in units:
        if not isinstance(entry, Mapping):
            continue
        status = str(entry.get("status", ""))
        if status in by_status:
            by_status[status].append(str(entry.get("unit_id", "")))
    return {
        "cancelled": by_status[UNIT_STATUS_CANCELLED],
        "outcome_unknown": by_status[UNIT_STATUS_CANCELLED_OUTCOME_UNKNOWN],
        "never_started": by_status[UNIT_STATUS_NOT_STARTED_CANCELLED],
        "blocked_by_cancelled_dependency": by_status[UNIT_STATUS_BLOCKED_BY_CANCELLED_DEPENDENCY],
        "claim_boundary": (
            "A cancellation rollup records the terminal state each unit reached when this dispatch was "
            "stopped. OMH terminates only the process groups its own dispatcher spawned; it is not a "
            "claim that any external executor was cancelled, and it is not execution, verification, "
            "review, CI, merge-readiness, or merge evidence."
        ),
    }


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
    "cost_usd",
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


DISPATCH_MODEL_PREFERENCE_SCHEMA_VERSION = "omh_dispatch_model_preferences/v1"

# Owners that spawn a headless coding CLI directly accept a `--model` string
# (see DISPATCH_MODEL_OPTION_TEMPLATES); this is the operator preference read
# when a unit's prepared handoff carries no routed model at all -- it never
# overrides a frozen route, only fills the gap when there is none. No profile
# ships a default here: a model the account is not entitled to is an observed
# exit failure with no fallback walk, and a user who never opted into a
# specific model choice should not be defaulted into that failure. The unset
# entry -- meaning the spawned CLI's own default -- is therefore the honest
# out-of-the-box behavior for every profile, including claude-code.
# `docs/FANOUT.md` documents "opus" as the recommended claude-code value for
# an operator who wants the strongest tier and knows their account carries
# it (this codebase's own model-family alias set, `_CLAUDE_TIER_ALIASES` in
# `src/coding/model_routing.py`, recognizes "opus" as a claude-family model
# id; whether `claude --help` itself documents "opus" as a `--model` alias on
# a given install is unverified here). One operator's own preference for it
# (2026-08 directive: "use fable-5 opus wherever reasonably possible") is set
# the same way, in that operator's own `dispatch-models.json`, not as a
# package-wide default. Codex ships no default either: this repo has no
# local `codex` CLI to confirm its `--model` value space against. An
# operator sets either profile in `dispatch-models.json`; an explicit empty
# string clears an entry back to unset.
_SHIPPED_DISPATCH_MODEL_DEFAULTS: dict[str, str] = {}


def dispatch_model_preferences_path(omh_home: Path) -> Path:
    return Path(omh_home) / "routing" / "dispatch-models.json"


def _dispatch_model_preference(paths: OmhPaths, owner: str) -> str:
    """The operator's preferred `--model` value for `owner`, or "" for the CLI default.

    Never raises: a missing, unreadable, or malformed document reads the same
    as an absent one, and the shipped default still applies -- a broken
    preference file must not block a dispatch or silently downgrade the
    model choice below the shipped default.
    """
    document, _error = read_json_object_result(dispatch_model_preferences_path(paths.omh_home))
    if isinstance(document, dict) and document.get("schema_version") == DISPATCH_MODEL_PREFERENCE_SCHEMA_VERSION:
        profiles = document.get("profiles")
        if isinstance(profiles, dict) and owner in profiles:
            value = profiles.get(owner)
            return value.strip() if isinstance(value, str) else ""
    return _SHIPPED_DISPATCH_MODEL_DEFAULTS.get(owner, "")


# `source` on the progress binding this lane opens. The HUD reader keys off
# this exact string (`_hud_subagent_summary` in runtime_reader.py) to label a
# row `(<executor>/maestro)` instead of rendering it like a Hermes-native
# delegate_task child -- `omh coding fanout dispatch` spawning an external CLI
# directly IS the Maestro lane (CONTEXT.md "Maestro" / "Fanout dispatch").
_FANOUT_PROGRESS_SOURCE = "fanout_dispatch"


def _open_fanout_progress_binding(
    paths: OmhPaths,
    *,
    run_ref: str,
    owner: str,
    worktree: Path,
    started_at: str,
    routed_model: str,
    routed_effort: str,
    title: str,
) -> dict[str, Any] | None:
    """Best-effort: open and report the initial live row for one dispatched unit.

    Returns None when the owner has no progress lane (never raises) so the
    caller's later pid/close calls become no-ops rather than every dispatch
    growing a try/except of its own -- observability must never fail a
    dispatch, the same rule `_write_inflight` already holds for markers.
    """
    try:
        profile = normalize_executor_profile(owner)
    except ExecutorProgressError:
        return None
    try:
        binding = build_progress_binding(
            target_type="run",
            target_id=run_ref,
            executor_profile=profile,
            now=started_at,
            worktree=str(worktree),
            source=_FANOUT_PROGRESS_SOURCE,
            # The default 120s repeat interval would suppress the mid-run
            # token updates `_live_unit_telemetry_reporter` posts (same event
            # type each time) down to two-minute granularity on the HUD row.
            # A unit binding is short-lived and its reporter only writes when
            # the count moved, so the journal cadence matches the reporter's
            # own throttle instead.
            minimum_repeat_interval_seconds=int(LIVE_UNIT_TELEMETRY_MIN_INTERVAL_SECONDS),
        )
        binding = write_progress_binding(paths, binding)
        signal = build_safe_progress_signal(
            executor_profile=profile,
            process_status="dispatched",
            routed_model=routed_model,
            routed_reasoning_effort=routed_effort,
            explicit_summary=title,
        )
        observation = observe_executor_progress(paths, binding, signal, observed_at=started_at)
        return observation["binding"]
    except (ExecutorProgressError, OSError):
        return None


def _record_fanout_progress_pid(
    paths: OmhPaths,
    binding: dict[str, Any] | None,
    pid: int,
) -> dict[str, Any] | None:
    if binding is None:
        return None
    try:
        updated = dict(binding)
        updated["process"] = {**binding.get("process", {}), "pid": pid}
        return write_progress_binding(paths, updated)
    except (ExecutorProgressError, OSError):
        return binding


def _close_fanout_progress_binding(
    paths: OmhPaths,
    binding: dict[str, Any] | None,
    *,
    exit_code: int,
    routed_model: str,
    routed_effort: str,
    title: str,
    owner: str,
    stdout_text: str,
) -> None:
    """Best-effort: report the unit's terminal state and close its row.

    A closed binding drops out of the HUD's active-executor projection on the
    very next read, which is what stops the row the moment the process ends —
    the same lifecycle every other executor-progress binding already has, not
    a bespoke lingering rule invented for this lane.

    Telemetry parsing lives INSIDE this guard rather than being handed in
    already-parsed: a caller evaluating `parse_unit_telemetry(...)` as an
    argument to this function runs it outside any try/except of its own --
    from inside a `finally`, that would propagate straight out and mask
    whatever the dispatch itself was doing, which is exactly the failure mode
    this whole binding lifecycle is "best-effort" to avoid.
    """
    if binding is None:
        return
    try:
        telemetry = parse_unit_telemetry(owner, stdout_text)
        cost_usd = telemetry.get("cost_usd")
        # A dispatcher-terminated unit closes its binding as cancelled, not as
        # failed. `_INTERRUPT_FLAG` is the host's own observation that it sent
        # the signal, which is the corroboration the progress lane requires
        # before it will accept a cancellation at all.
        if exit_code == 0:
            observed_process_status = "completed"
        elif _INTERRUPT_FLAG.is_set():
            observed_process_status = "cancelled"
        else:
            observed_process_status = "failed"
        signal = build_safe_progress_signal(
            executor_profile=str(binding.get("executor_profile", "")),
            process_status=observed_process_status,
            routed_model=routed_model,
            routed_reasoning_effort=routed_effort,
            explicit_summary=title,
            tokens_total=_reported_unit_tokens(telemetry),
            cost_usd=cost_usd if isinstance(cost_usd, (int, float)) and not isinstance(cost_usd, bool) else None,
        )
        observe_executor_progress(paths, binding, signal)
    except (ExecutorProgressError, OSError):
        return


def _consider_unit_retry(
    paths: OmhPaths,
    *,
    attempt: int,
    exit_code: int,
    output_tail: str,
    stderr_tail: str,
    sidecar_path: Path | None,
    worktree: Path,
    base_sha: str,
    runner: Callable[..., Any],
    max_retries: int,
    rng: Callable[[], float],
) -> dict[str, Any]:
    """Decide whether this failed attempt earns another one, and say why.

    The replay-safety half is measured, not assumed: the SAME recovery probe
    that reports what a failed unit left behind answers "has this unit produced
    an observed side effect", and it is called with an empty `fanout_id` so a
    mid-flight probe never persists an intermediate record over the real one
    written at the end. The probe only runs for a failure already classified as
    transient -- a terminal failure is not retried whatever the worktree holds,
    so measuring it would be work spent on an answer nobody reads.
    """
    # Derived once and passed to both calls: the retry verdict and the
    # persisted provider-limit evidence must never disagree about whether this
    # failure was limit-shaped.
    limit_label = _limit_shaped_label(output_tail, stderr_tail)
    classification = classify_unit_failure(
        exit_code=exit_code,
        output_tail=output_tail,
        stderr_tail=stderr_tail,
        limit_shaped=limit_label,
    )
    recovery: dict[str, Any] | None = None
    artifact_observed = False
    if classification["retryable"] and attempt <= max_retries:
        artifact_observed = sidecar_path is not None and sidecar_path.is_file()
        if not artifact_observed:
            recovery = _capture_unit_recovery(
                paths,
                fanout_id="",
                unit_id="",
                worktree=worktree,
                base_sha=base_sha,
                runner=runner,
            )
    return evaluate_unit_retry(
        attempt=attempt,
        exit_code=exit_code,
        output_tail=output_tail,
        stderr_tail=stderr_tail,
        limit_shaped=limit_label,
        recovery=recovery,
        artifact_observed=artifact_observed,
        max_retries=max_retries,
        rng=rng,
    )


def _reported_unit_tokens(telemetry: Mapping[str, Any]) -> int | None:
    """The one display count a unit's reported telemetry supports.

    `tokens_total` when the CLI itself stated a total (codex's cumulative
    `total_token_usage` carries one); otherwise the sum of the reported input
    and output counts — the same input+output convention the Hermes-native
    HUD rows already use, and aggregation of stated values in the
    `tokens_billable` sense, never an estimate. Claude's result object states
    input and output but no total, so without this fallback its rows carried
    no count at all. Absent counts stay absent: None, never zero.
    """
    total = telemetry.get("tokens_total")
    if isinstance(total, int) and not isinstance(total, bool):
        return total
    parts = (telemetry.get("input_tokens"), telemetry.get("output_tokens"))
    counts = [part for part in parts if isinstance(part, int) and not isinstance(part, bool)]
    return sum(counts) if counts else None


# Minimum spacing between mid-run telemetry parses of one unit's stdout.
# The runner snapshots every UNIT_OUTPUT_POLL_SECONDS; parsing (bounded but
# not free) and journal writes throttle further, and a write only happens
# when the reported count actually moved.
LIVE_UNIT_TELEMETRY_MIN_INTERVAL_SECONDS = 10.0


def _live_unit_telemetry_reporter(
    paths: OmhPaths,
    *,
    owner: str,
    routed_model: str,
    routed_effort: str,
    title: str,
    binding_ref: Callable[[], dict[str, Any] | None],
    binding_set: Callable[[dict[str, Any]], None],
) -> Callable[[str], None]:
    """Best-effort mid-run token reporting for a unit's HUD row.

    Before this seam existed, a Maestro-lane row showed no token count until
    the process exited — and the closed binding dropped the row on the next
    poll, so the count was never visible live at all ('maestro세션은 어캐
    tokens 측정함?'). The runner hands this hook the stdout captured so far;
    it parses the same `omh_unit_telemetry/v1` surface the terminal close
    already uses (codex's cumulative token events mid-run; claude reports
    usage only in its terminal result, so its live rows stay honestly blank)
    and reports the count as a `running` progress signal on the unit's
    binding. Reporting only — never execution or result evidence, and a
    failure here never disturbs the dispatch.
    """
    throttle: dict[str, Any] = {"next_at": 0.0, "count": None}

    def report(stdout_snapshot: str) -> None:
        binding = binding_ref()
        if binding is None or not stdout_snapshot:
            return
        now = time.monotonic()
        if now < throttle["next_at"]:
            return
        throttle["next_at"] = now + LIVE_UNIT_TELEMETRY_MIN_INTERVAL_SECONDS
        tokens = _reported_unit_tokens(parse_unit_telemetry(owner, stdout_snapshot))
        if tokens is None or tokens == throttle["count"]:
            return
        try:
            signal = build_safe_progress_signal(
                executor_profile=str(binding.get("executor_profile", "")),
                process_status="running",
                routed_model=routed_model,
                routed_reasoning_effort=routed_effort,
                explicit_summary=title,
                tokens_total=tokens,
            )
            observation = observe_executor_progress(paths, binding, signal)
        except (ExecutorProgressError, OSError):
            return
        throttle["count"] = tokens
        # Hand the caller the updated binding so the later pid/close calls
        # carry this observation's reporter state instead of a stale copy.
        updated = observation.get("binding")
        if isinstance(updated, dict):
            binding_set(updated)

    return report


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
    spawn_stagger: _SpawnStagger | None = None,
    spawn_ledger: _SpawnLedger | None = None,
    dispatch_depth: int = 0,
    base_env: Mapping[str, str] | None = None,
    max_retries: int = FANOUT_MAX_RETRIES,
    rng: Callable[[], float] = random.random,
    sleep: Callable[[float], None] = time.sleep,
    ignore_limit_signal: bool = False,
    review_budget: ReviewDispatchBudget,
    verification_wave_width: int = 1,
    verification_execution_gate: VerificationExecutionGate | None = None,
    diagnostic_engine: DiagnosticExecutionEngine | None = None,
    health_events: FanoutHealthEvents | None = None,
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
            "status": _capability_refusal_status(capability_errors),
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
    # The one place an observed signal vetoes a spawn instead of ranking one.
    # It is checked before the readiness probe because the cheapest refusal is
    # the one that runs no subprocess at all, and it never fires on a dry run,
    # which spawns nothing to begin with. See COOLDOWN_CLAIM_BOUNDARY for why
    # this does not contradict the advisory-marker principle: the input is a
    # runtime failure omh observed from a real spawn of this owner, not the
    # absence of a local login file.
    if not dry_run and not ignore_limit_signal:
        cooldown = spawn_cooldown(paths, owner)
        if cooldown is not None:
            return {
                "unit_id": unit_id,
                "run_ref": run_ref,
                "owner": owner,
                "status": str(cooldown["status"]),
                "failure_kind": str(cooldown["failure_kind"]),
                **_dispatch_status_ladder(),
                "reason": str(cooldown["reason"]),
                "cooldown": {
                    key: value
                    for key, value in cooldown.items()
                    if key in {"pattern_label", "observed_at", "cooldown_remaining_seconds", "claim_boundary"}
                },
                "repair_card": cooldown["repair_card"],
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
        if dry_run:
            not_ready["filesystem_confinement"] = planned_fanout_filesystem_confinement(
                _worktree_path(repo_root, unit_id),
                owner=owner,
                environment=os.environ if base_env is None else base_env,
            )
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
    # The unit's prepared handoff routes a model whenever the contract
    # resolved one; when it did not (no route at all, or a route that
    # resolved with no model), the operator's dispatch-model preference fills
    # the gap so the spawn — and the row it opens — never silently falls back
    # to "whatever the CLI defaults to" without a recorded reason. A frozen
    # `choice_required` route already returned above and never reaches here.
    effective_model_route = model_route
    if not routed_model:
        preference = _dispatch_model_preference(paths, owner)
        if preference:
            routed_model = preference
            effective_model_route = {**(model_route or {}), "selected_model": preference}
    argv = build_dispatch_argv(owner, prompt, effective_model_route)
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
            "filesystem_confinement": planned_fanout_filesystem_confinement(
                worktree,
                owner=owner,
                environment=os.environ if base_env is None else base_env,
            ),
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
    # Claimed here, after the dry-run return and BEFORE either durable review
    # accounting or worktree creation. A ceiling refusal therefore leaves both
    # durable state and the filesystem untouched. If the review reservation
    # refuses afterward, its claim is returned before that refusal is exposed.
    spawn_claimed = spawn_ledger is not None and spawn_ledger.claim()
    if spawn_ledger is not None and not spawn_claimed:
        return {
            "unit_id": unit_id,
            "run_ref": run_ref,
            "owner": owner,
            "status": SPAWN_CEILING_STATUS,
            **_dispatch_status_ladder(),
            "reason": (
                f"run spawn ceiling of {spawn_ledger.ceiling} reached before this unit started; "
                "re-dispatch the remaining units, or raise `run_spawn_ceiling` in the setup "
                "profile's parallelism block"
            ),
        }
    review_role = normalized_review_role(_unit_role(unit))
    if review_role is not None:
        reservation = review_budget.reserve(review_role, unit_id)
        if not reservation.granted:
            if spawn_ledger is not None:
                spawn_ledger.release()
            reason_codes = {
                "attempt_not_progressed": "review_dispatch_attempt_not_progressed",
                "configuration_mismatch": "review_dispatch_budget_configuration_mismatch",
                "exhausted": "review_dispatch_no_progress",
            }
            reason_code = reason_codes.get(reservation.status, "review_dispatch_no_progress")
            reasons = {
                "attempt_not_progressed": (
                    "a new goal attempt was named without explicitly confirming concrete progress"
                ),
                "configuration_mismatch": (
                    "the requested review dispatch budget differs from the durable attempt budget"
                ),
                "exhausted": "the normalized reviewer role has no dispatch allowance left in this goal attempt",
            }
            return {
                "unit_id": unit_id,
                "run_ref": run_ref,
                "owner": owner,
                "status": "review_dispatch_budget_exhausted",
                "reason_code": reason_code,
                "reason": reasons.get(reservation.status, "review dispatch made no progress"),
                "review_dispatch_budget": reservation.as_dict(),
                **_dispatch_status_ladder(),
            }
    child_env = fanout_child_env(
        os.environ if base_env is None else base_env,
        depth=dispatch_depth,
        fanout_id=fanout_id,
        unit_id=unit_id,
        owner=owner,
    )
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
    verification_argv: list[list[str]] = []
    for command in declared_verification_commands(unit):
        try:
            _overrides, check_argv = verification_command_argv(command)
        except FanoutContractError:
            continue
        verification_argv.append(check_argv)
    confinement = (
        prepare_fanout_filesystem_confinement(
            worktree, child_env, (argv, *verification_argv), owner=owner
        )
        if runner is signal_safe_unit_runner
        else None
    )
    filesystem_confinement = confinement_receipt(confinement, worktree)
    if confinement is not None:
        child_env = confinement.command_environment()
    # After the worktree exists and before anything else touches it: a linked
    # artifact must be in place before the unit's process spawns to be worth
    # anything, and re-checking from inside the worktree (see
    # fanout_artifact_sharing) requires the worktree's own git metadata, which
    # `git worktree add` has just finished writing.
    shared_artifacts = plan_and_link_shared_artifacts(
        repo_root=repo_root,
        worktree_path=worktree,
        runner=runner,
    )
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
    dispatch_summary = f"local dispatch of unit {unit_id} to {owner}"
    if shared_artifacts.get("linked"):
        # Named in the journal, not just the eventual result dict, so a run
        # stays explainable from the journal alone: the observation schema
        # carries only fixed fields, so the note rides in free-text summary.
        dispatch_summary = f"{dispatch_summary} (shared_artifacts: {', '.join(shared_artifacts['linked'])})"
    append_journal_observation(
        paths,
        {
            "target_type": "run",
            "target_id": run_ref,
            "run_id": run_ref,
            "event": "worker_dispatch",
            "status": "observed",
            "summary": dispatch_summary,
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
    exit_code = 1
    owner_host = omo_runtime_host() or "" if owner == "omo-runtime" else ""
    unit_title = str(unit.get("title") or unit.get("unit_id", unit_id))
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
    # Best-effort HUD row for this unit: opened inside the same try whose
    # finally below closes it, so the row can never outlive the process it
    # describes -- opening it BEFORE the try left a window (a Ctrl-C during
    # the stagger sleep just below, in particular) where the binding was on
    # disk but the finally that closes it never ran, orphaning a live row for
    # up to its freshness window. See _open_fanout_progress_binding.
    progress_binding: dict[str, Any] | None = None
    spawn_kwargs: dict[str, Any] = {}
    # One entry per FAILED attempt, each carrying why it did or did not lead to
    # another one. An empty list means the unit succeeded first try.
    retry_decisions: list[dict[str, Any]] = []
    attempt = 0
    try:
        progress_binding = _open_fanout_progress_binding(
            paths,
            run_ref=run_ref,
            owner=owner,
            worktree=worktree,
            started_at=started_at,
            routed_model=routed_model,
            routed_effort=routed_effort,
            title=unit_title,
        )
        if getattr(runner, "accepts_on_spawn", False):
            # The signal-safe runner hands back the live process so the marker
            # carries the real group-leader pid the fanout reaper verifies
            # against; injected test runners keep the plain protocol.
            def _record_pid(process: subprocess.Popen) -> None:
                nonlocal progress_binding
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
                        "pid": str(process.pid),
                    },
                )
                progress_binding = _record_fanout_progress_pid(paths, progress_binding, process.pid)

            spawn_kwargs["on_spawn"] = _record_pid
        if getattr(runner, "accepts_on_output", False):
            # Mid-run token telemetry for the unit's HUD row, from the stdout
            # captured so far. Same opt-in marker pattern as accepts_on_spawn:
            # injected plain-protocol test runners never see the kwarg. Wired
            # once, outside the attempt loop: the reporter's own throttle is
            # per-unit, so a retry keeps reporting into the same row rather
            # than opening a second one.
            def _replace_binding(updated: dict[str, Any]) -> None:
                nonlocal progress_binding
                progress_binding = updated

            spawn_kwargs["on_output"] = _live_unit_telemetry_reporter(
                paths,
                owner=owner,
                routed_model=routed_model,
                routed_effort=routed_effort,
                title=unit_title,
                binding_ref=lambda: progress_binding,
                binding_set=_replace_binding,
            )
        confinement_command = confinement.command(argv) if confinement is not None else None
        if confinement_command is not None:
            spawn_kwargs["confinement_command"] = confinement_command
        while True:
            attempt += 1
            output_tail = ""
            stdout_text = ""
            stderr_tail = ""
            output_truncation: dict[str, Any] | None = None
            stderr_truncation: dict[str, Any] | None = None
            exit_code = 1
            if health_events is not None and attempt > 1:
                health_events.queued(
                    unit_id,
                    dependencies=tuple(str(dep) for dep in unit.get("depends_on", []) or []),
                    resource_class=owner,
                    retry=attempt - 1,
                )
            # Real spawns only (the same seam as the pid hook): stagger this
            # unit's start so the first dispatch of the fanout writes the
            # provider prompt cache the byte-identical sibling preambles read.
            # Inside the loop, so a retry is spaced from its siblings too.
            if spawn_stagger is not None and "on_spawn" in spawn_kwargs:
                spawn_stagger.reserve()
            if health_events is not None and attempt > 1:
                health_events.started(unit_id, retry=attempt - 1)
            try:
                completed = runner(
                    argv,
                    cwd=str(worktree),
                    # The lineage stamp goes in at the Popen boundary, not into
                    # the dispatcher's own environment: an agent CLI that reads
                    # its instructions and reaches for `omh coding fanout
                    # dispatch` refuses on the depth it inherits here.
                    env=child_env,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    **spawn_kwargs,
                )
                exit_code = int(getattr(completed, "returncode", 1))
                stdout_text = str(getattr(completed, "stdout", "") or "")
                # The tails are what rides into the summary and the journal; the
                # bytes above them used to be dropped on the floor. They now go
                # to a content-addressed spill, and the records below carry a
                # pointer a later step can resolve.
                bounded_stdout = truncate_output(
                    stdout_text,
                    limit_bytes=_MAX_UNIT_OUTPUT_TAIL,
                    source=f"fanout unit {unit_id} stdout",
                    keep="tail",
                    spill_dir=paths.runtime_output_spills_dir,
                )
                bounded_stderr = truncate_output(
                    str(getattr(completed, "stderr", "") or ""),
                    limit_bytes=_MAX_UNIT_OUTPUT_TAIL,
                    source=f"fanout unit {unit_id} stderr",
                    keep="tail",
                    spill_dir=paths.runtime_output_spills_dir,
                )
                output_tail = bounded_stdout.kept_text
                stderr_tail = bounded_stderr.kept_text
                output_truncation = bounded_stdout.record
                stderr_truncation = bounded_stderr.record
            except FileNotFoundError:
                exit_code, output_tail = 127, f"{argv[0]} not found on PATH"
            except subprocess.TimeoutExpired:
                exit_code, output_tail = 124, f"unit timed out after {timeout}s"
            except OSError as exc:
                exit_code, output_tail = 1, f"spawn failed: {exc}"
            if health_events is not None:
                health_events.finished(
                    unit_id,
                    terminal_status="succeeded" if exit_code == 0 else "failed",
                    retry=attempt - 1,
                )
            if exit_code == 0:
                break
            decision = _consider_unit_retry(
                paths,
                attempt=attempt,
                exit_code=exit_code,
                output_tail=output_tail,
                stderr_tail=stderr_tail,
                sidecar_path=sidecar_path,
                worktree=worktree,
                base_sha=base_sha,
                runner=runner,
                max_retries=max_retries,
                rng=rng,
            )
            retry_decisions.append(decision)
            if not decision.get("retry"):
                break
            # A retry is another real spawn and spends the run's budget like
            # any other; when the budget is gone the unit stops here with its
            # decision already recorded.
            if spawn_ledger is not None and not spawn_ledger.claim():
                decision["retry"] = False
                decision["decision"] = "spawn_ceiling_reached"
                break
            # An interrupted batch must not start a fresh attempt nobody will
            # collect -- the same rule the pool's own workers follow.
            if _INTERRUPT_FLAG.is_set():
                decision["retry"] = False
                decision["decision"] = "interrupted"
                break
            sleep(float(decision["delay_seconds"]))
    finally:
        _clear_inflight(paths, fanout_id, unit_id)
        _close_fanout_progress_binding(
            paths,
            progress_binding,
            exit_code=exit_code,
            routed_model=routed_model,
            routed_effort=routed_effort,
            title=unit_title,
            owner=owner,
            stdout_text=stdout_text,
        )
    finished_at = utc_now()
    duration_seconds = round(time.monotonic() - started_clock, 3)
    limit_label = _limit_shaped_label(output_tail, stderr_tail) if exit_code != 0 else ""
    auth_label = auth_shaped_label(output_tail, stderr_tail) if exit_code != 0 else ""
    # One closed-enum answer per failed unit, derived once so the envelope, the
    # persisted signal, and the recovery interview cannot disagree about what
    # kind of failure this was.
    failure_kind = classify_failure_kind(
        exit_code=exit_code, limit_label=limit_label, auth_label=auth_label
    )
    # Auth takes the persisted signal when both shapes match, for the same
    # reason it takes the enum: a credential rejection filed as a limit would be
    # waited out forever. `limit_shaped` stays on the envelope either way, so no
    # existing consumer of that flag loses its answer.
    if failure_kind == FAILURE_KIND_AUTH_SHAPED:
        record_auth_failure_signal(
            paths, owner, run_ref=run_ref, unit_id=unit_id, pattern_label=auth_label
        )
    elif limit_label:
        _record_limit_signal(paths, owner, run_ref=run_ref, unit_id=unit_id, pattern_label=limit_label)
    elif exit_code == 0:
        # A successful dispatch to this executor is the freshest evidence the
        # provider is serving it again; a stale limit or auth signal must not
        # keep down-ranking (or vetoing) the executor forever.
        _clear_limit_signal(paths, owner)
        clear_auth_failure_signal(paths, owner)
    status = "observed" if exit_code == 0 else "failed"
    # A second cap over an already-bounded tail. It goes through the shared
    # contract too, so the journal line says which of the two it is: the whole
    # tail, or a cut of it whose full text the evidence ref below resolves.
    unit_output_spilled = output_truncation is not None and bool(output_truncation.get("truncated"))
    summary_bound = truncate_output(
        output_tail,
        limit_bytes=_MAX_UNIT_SUMMARY_TAIL,
        source=f"fanout unit {unit_id} journal summary",
        keep="tail",
        # Spilled only when the unit-level cap did not already spill this text.
        # Otherwise the journal would point at a 2000-byte tail while a pointer
        # to the whole output already exists.
        spill_dir=None if unit_output_spilled else paths.runtime_output_spills_dir,
    )
    summary = (
        f"unit {unit_id} exit {exit_code} after {duration_seconds}s: "
        f"{redact_metadata_text(summary_bound.kept_text, limit=_MAX_UNIT_SUMMARY_TAIL)}"
    )
    # The unit-level record wins when it has one: it is the truncation that
    # actually holds a spill pointer. The summary's own cap is reported only
    # when the unit output fit and this second bound was what cut it.
    journal_truncation = output_truncation if unit_output_spilled else summary_bound.record
    journal_notice = truncation_notice(journal_truncation, compact=True)
    if journal_notice:
        summary = f"{summary} {journal_notice}"
    if failure_kind == FAILURE_KIND_AUTH_SHAPED:
        summary = f"auth-shaped failure ({auth_label}); {summary}"
    elif limit_label:
        summary = f"limit-shaped failure ({limit_label}); {summary}"
    # The compact notice above says "continuation=evidence_refs"; these are the
    # refs it means. Uncapped by the journal, so the pointer arrives whole.
    spill_refs = [
        ref
        for ref in (
            spill_evidence_ref(journal_truncation or {}),
            spill_evidence_ref(stderr_truncation or {}),
        )
        if ref
    ]
    append_journal_observation(
        paths,
        {
            "target_type": "run",
            "target_id": run_ref,
            "run_id": run_ref,
            "event": "worker_result",
            "status": status,
            "summary": summary,
            "evidence_refs": spill_refs,
            "worker_ref": unit_id,
            "worktree_ref": str(worktree),
            "runtime_profile": owner,
        },
    )
    unit_result = _intake_unit_result(
        paths,
        runner=runner,
        sidecar_path=sidecar_path,
        run_ref=run_ref,
        unit_id=unit_id,
        fanout_id=fanout_id,
        base_sha=base_sha,
        worktree=worktree,
        owner=owner,
        stdout_text=stdout_text,
    )
    # Both rungs below it must already hold: a unit whose process failed has
    # nothing to verify, and one whose sidecar did not validate has not yet
    # reported what it did. Runs before the ladder is built, so the journal
    # event it may append is visible to `_unit_verification_is_observed`.
    verification: dict[str, Any] = {}
    if run_verification and exit_code == 0 and unit_result.get("result_schema_valid"):
        verification_task = f"{unit_id}:verification"
        producer_revision = str(unit_result["producer_head_sha"])
        if health_events is not None:
            health_events.queued(
                verification_task,
                dependencies=(unit_id,),
                resource_class="verification",
                phase="verification",
                revision=producer_revision,
            )
            health_events.started(verification_task, phase="verification")
        verification = _run_unit_verification(
            paths,
            unit,
            run_ref=run_ref,
            unit_id=unit_id,
            worktree=worktree,
            owner=owner,
            runner=runner,
            child_env=child_env,
            fanout_id=fanout_id,
            wave_width=verification_wave_width,
            execution_gate=verification_execution_gate,
            confinement=confinement,
        )
        if health_events is not None:
            health_events.finished(
                verification_task,
                terminal_status="succeeded" if verification.get("verification_status") == "passed" else "failed",
                reused=any(
                    isinstance(row, Mapping) and bool(row.get("reused"))
                    for row in verification.get("verification_checks", [])
                ),
                phase="verification",
            )
    diagnostics: dict[str, object] = {}
    if diagnostic_engine is not None and diagnostic_engine.settings.enabled:
        producer_head = _observed_clean_producer_head(runner, worktree)
        diagnostics = run_post_green_diagnostics(
            diagnostic_engine,
            owner=owner,
            workspace_id=f"{fanout_id}:{unit_id}",
            workspace_path=str(worktree),
            baseline_revision=base_sha,
            end_revision=producer_head or "",
            verification_passed=verification.get("verification_status") == "passed",
            producer_evidence=(
                producer_head is not None
                and producer_head == unit_result.get("producer_head_sha")
            ),
        ) or {}
    result = {
        "unit_id": unit_id,
        "run_ref": run_ref,
        "owner": owner,
        "model": routed_model,
        "reasoning_effort": routed_effort,
        "status": "completed" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "worktree_path": str(worktree),
        "filesystem_confinement": filesystem_confinement,
        "shared_artifacts": shared_artifacts,
        **_dispatch_status_ladder(
            process_succeeded=exit_code == 0,
            result_schema_valid=bool(unit_result.get("result_schema_valid")),
            unit_verification_observed=_unit_verification_is_observed(paths, run_ref),
        ),
        **unit_result,
        **verification,
        **diagnostics,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
    }
    if owner_host:
        result["owner_host"] = owner_host
    # Present whenever a spawn actually produced captured output, truncated or
    # not, so the dispatch summary distinguishes "this is the whole tail" from
    # "the tail of a longer output, spilled to <path>" without parsing prose.
    if output_truncation is not None:
        result["output_truncation"] = output_truncation
    if stderr_truncation is not None:
        result["stderr_truncation"] = stderr_truncation
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
    if failure_kind:
        # Every failed envelope carries exactly one closed-enum kind, including
        # `crash` -- the fallback exists so a reader never has to infer "no kind
        # recorded" from an absent key.
        result["failure_kind"] = failure_kind
    if failure_kind == FAILURE_KIND_AUTH_SHAPED:
        result["auth_shaped"] = True
        result["auth_pattern"] = auth_label
    if failure_kind in {FAILURE_KIND_AUTH_SHAPED, FAILURE_KIND_LIMIT_SHAPED}:
        result["repair_card"] = build_repair_card(
            owner=owner,
            failure_kind=failure_kind,
            detail=f"unit {unit_id} exited {exit_code} on {owner} with a {failure_kind} output shape",
        )
    if retry_decisions:
        # Only when something actually failed once: a unit that succeeded on
        # its first attempt carries no retry key at all, so the presence of
        # this block is itself the signal.
        final = retry_decisions[-1]
        result["retry"] = {
            "schema_version": RETRY_POLICY_SCHEMA_VERSION,
            "attempts": attempt,
            "max_retries": max_retries,
            "final_decision": str(final.get("decision", "")),
            "decisions": retry_decisions,
            "claim_boundary": RETRY_CLAIM_BOUNDARY,
        }
        if final.get("decision") == "surfaced_for_continuation":
            # The headline of the replay-safety predicate: this unit COULD
            # have been retried and deliberately was not, because re-running
            # it from base would destroy the work its failure left behind.
            # The recovery record captured just below is how it is continued.
            result["retry_blocked_by_side_effects"] = True
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
    "decline_reason",
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
    runner: Callable[..., Any],
    sidecar_path: Path | None,
    run_ref: str,
    unit_id: str,
    fanout_id: str,
    base_sha: str,
    worktree: Path,
    owner: str,
    stdout_text: str = "",
) -> dict[str, Any]:
    """Read one unit return after process exit and classify shape, never truth.

    The sidecar file is the primary machine-read return. When a sidecar was
    contracted but the executor never wrote the file, the return protocol's
    redundant fenced ```json block is the fallback: the last fenced block in
    captured stdout goes through the same provenance, schema, and dispatch
    identity validation the sidecar gets. Only a missing sidecar with no
    fenced block at all stays `unit_result_missing`.
    """
    if sidecar_path is None or not sidecar_path.is_file():
        if sidecar_path is not None:
            fallback = _intake_stdout_unit_result(
                paths,
                stdout_text=stdout_text,
                run_ref=run_ref,
                unit_id=unit_id,
                fanout_id=fanout_id,
                base_sha=base_sha,
                worktree=worktree,
                owner=owner,
                runner=runner,
            )
            if fallback is not None:
                return fallback
        return _unit_result_failure(
            paths,
            event="unit_result_missing",
            reason=(
                "sidecar is missing"
                if sidecar_path is None
                else "sidecar is missing and stdout has no fenced json block"
            ),
            sidecar_path=None,
            run_ref=run_ref,
            unit_id=unit_id,
            worktree=worktree,
            owner=owner,
        )
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        validated = _validated_unit_result_payload(
            payload,
            unit_id=unit_id,
            run_ref=run_ref,
            fanout_id=fanout_id,
            base_sha=base_sha,
        )
        producer_head_sha = _observed_clean_producer_head(runner, worktree)
        if producer_head_sha is None:
            raise ValueError("dispatcher could not observe a clean committed producer HEAD")
        if validated["head_sha"] != producer_head_sha:
            raise ValueError("head_sha does not match dispatcher-observed producer HEAD")
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
        "unit_result_source": "sidecar",
        "producer_head_sha": producer_head_sha,
        "unit_result": _bounded_unit_result(validated),
    }


def _stdout_fenced_json_blocks(stdout_text: str) -> list[str]:
    """Bodies of fenced ```json blocks in stdout, in order of appearance.

    A deliberately plain line scan: a block opens on a line that is exactly
    ```json (after strip) and closes on the next line that is exactly ```.
    An unclosed trailing block is dropped rather than guessed at.
    """
    blocks: list[str] = []
    body: list[str] | None = None
    for line in stdout_text.splitlines():
        stripped = line.strip()
        if body is None:
            if stripped == "```json":
                body = []
        elif stripped == "```":
            blocks.append("\n".join(body))
            body = None
        else:
            body.append(line)
    return blocks


def _intake_stdout_unit_result(
    paths: OmhPaths,
    *,
    runner: Callable[..., Any],
    stdout_text: str,
    run_ref: str,
    unit_id: str,
    fanout_id: str,
    base_sha: str,
    worktree: Path,
    owner: str,
) -> dict[str, Any] | None:
    """Fallback intake from the fenced stdout block when the sidecar is absent.

    Returns None when stdout carries no fenced ```json block (the caller then
    reports `unit_result_missing`). The report protocol says the final report
    ENDS with the block, so the last one is the return; it faces exactly the
    validation the sidecar faces, and a block that fails it is reported as
    `unit_result_invalid` rather than silently ignored.
    """
    blocks = _stdout_fenced_json_blocks(stdout_text)
    if not blocks:
        return None
    try:
        payload = json.loads(blocks[-1])
        validated = _validated_unit_result_payload(
            payload,
            unit_id=unit_id,
            run_ref=run_ref,
            fanout_id=fanout_id,
            base_sha=base_sha,
        )
        producer_head_sha = _observed_clean_producer_head(runner, worktree)
        if producer_head_sha is None:
            raise ValueError("dispatcher could not observe a clean committed producer HEAD")
        if validated["head_sha"] != producer_head_sha:
            raise ValueError("head_sha does not match dispatcher-observed producer HEAD")
    except (ValueError, TypeError) as exc:
        return _unit_result_failure(
            paths,
            event="unit_result_invalid",
            reason=f"stdout fenced json block (sidecar missing): {exc}",
            sidecar_path=None,
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
            "summary": (
                f"fanout unit result shape validated for {unit_id} "
                "from stdout fenced json block (sidecar missing)"
            ),
            "worker_ref": unit_id,
            "worktree_ref": str(worktree),
            "runtime_profile": owner,
            "evidence_refs": [],
        },
    )
    return {
        "unit_result_status": "unit_result_validated",
        "result_schema_valid": True,
        "unit_result_source": "stdout_fenced_block",
        "producer_head_sha": producer_head_sha,
        "unit_result": _bounded_unit_result(validated),
    }


def _validated_unit_result_payload(
    payload: Any,
    *,
    unit_id: str,
    run_ref: str,
    fanout_id: str,
    base_sha: str,
) -> dict[str, Any]:
    """One validation ladder for both return lanes (sidecar and stdout block)."""
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
    return validated


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
        # A cancelled dependency produced nothing a dependent can build on. It
        # is admitted as a prerequisite by neither this predicate's opposite
        # (`_dependency_satisfied`, which requires an observed exit-0) nor by
        # any other path, and naming it here is what lets the dependent say
        # WHICH unit it is waiting on rather than blocking on nothing.
        *CANCELLED_UNIT_STATUSES,
        "executor_not_ready",
        "unsupported_for_local_dispatch",
        "worktree_failed",
        "not_selected",
        "review_dispatch_budget_exhausted",
        # A vetoed spawn never ran, so a dependent must block on it exactly as
        # it would on an unready executor -- admitting the dependent would run
        # it against work that does not exist.
        COOLDOWN_STATUS_AUTH,
        COOLDOWN_STATUS_LIMIT,
    } and not result.get("process_succeeded")


def _blocked(unit: Mapping[str, Any], results: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    deps = [str(dep) for dep in unit.get("depends_on", []) or []]
    cancelled_deps = [
        dep
        for dep in deps
        if str((results.get(dep) or {}).get("status", "")) in CANCELLED_UNIT_STATUSES
    ]
    # A dependent held behind a cancelled unit is not held behind a defect. The
    # two read the same in a rollup that has only `blocked_by_dependency`, and
    # they call for different next steps: one waits on a fix, the other waits on
    # a decision to re-dispatch.
    entry = _skipped(
        unit,
        UNIT_STATUS_BLOCKED_BY_CANCELLED_DEPENDENCY if cancelled_deps else "blocked_by_dependency",
    )
    failed = [dep for dep in deps if _dependency_failed(results.get(dep))]
    # A dependency stuck in a non-terminal verdict (for example
    # model_choice_required) is neither satisfied nor failed; the entry must
    # still name what it was waiting on rather than blocking on nothing.
    entry["blocked_on"] = failed or [
        dep for dep in deps if not _dependency_satisfied(results.get(dep))
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


def _resume_note(decision: Mapping[str, Any]) -> dict[str, Any]:
    note: dict[str, Any] = {
        "action": str(decision.get("action", "")),
        "prior_state": str(decision.get("prior_state", "")),
        "reason": str(decision.get("reason", "")),
    }
    carried = decision.get("carry_forward")
    if isinstance(carried, Mapping):
        # A held unit is recorded in THIS run's summary as a skip, which on its
        # own would journal as "never attempted" and make the next resume
        # re-dispatch exactly what this one refused to. The prior journal row
        # rides along so the verdict survives every further resume.
        note["carry_forward"] = dict(carried)
    return note


def _resume_hold(
    paths: OmhPaths,
    unit: Mapping[str, Any],
    decision: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """The skip entry for a unit a resume plan holds back, or None to dispatch.

    Held units reuse the existing skip vocabulary rather than inventing a
    status: a succeeded unit reads `already_completed` so it keeps satisfying
    its dependents, and a refused replay reads `not_selected` so its dependents
    stay blocked. The `resume` block is what says which of the two it was and
    why. Nothing else runs for a held unit -- no readiness probe, no worktree,
    no spawn, and above all no progress binding, so the live telemetry reporter
    never reports a unit this run did not actually run.
    """
    if decision is None or str(decision.get("action", "")) not in RESUME_HOLD_ACTIONS:
        return None
    if str(decision.get("action", "")) == RESUME_HOLD_SUCCEEDED:
        entry = _skipped(
            unit,
            "already_completed",
            process_succeeded=True,
            unit_verification_observed=_unit_verification_is_observed(
                paths, str(unit.get("run_ref", unit.get("unit_id", "")))
            ),
        )
    else:
        entry = _skipped(unit, "not_selected")
    entry["resume"] = _resume_note(decision)
    return entry


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
