"""Explicit, bounded local Hermes single-query (``chat --query-file -``) child dispatch.

This is an operator-command integration seam. Importing or constructing a
request never starts work: callers must supply the fixed ask-before-dispatch
policy and an explicit confirmation for every invocation. OMH itself makes no
provider call; the spawned local Hermes CLI owns that call.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from threading import Event, Lock, Thread
import time
from typing import Final

from ..system.approval_tier import TIER_AUTO_ALLOWED, resolve_approval_tier
from .hermes_child_arm_setup import ArmSetup, PairedRunArmHome, observe_arm_setup
from ..system.security_posture import resolve_security_posture
from .hermes_child_evaluation import (
    HermesChildEvaluationContext,
    seal_evaluation_binding,
)
from ._hermes_child_usage import read_hermes_child_usage, state_session_ids
from .hermes_child_trace import CellTrace, read_hermes_child_trace
from ._hermes_child_process import (
    BoundedStreamCapture,
    PipeDrainer,
    await_pipe_threads as _await_pipe_threads,
    block_relay_signals as _block_relay_signals,
    bounded_redacted_output as _bounded_redacted_output,
    capture_truncation_record as _capture_truncation_record,
    install_signal_relays as _install_signal_relays,
    merge_signals as _merge_signals,
    restore_signal_handlers as _restore_signal_handlers,
    restore_signal_mask as _restore_signal_mask,
    start_pipe_drainers as _start_pipe_drainers,
    terminate_process_group as _terminate_process_group,
    write_stdin_and_close as _write_stdin_and_close,
)
from .spawn_preflight import (
    check_executable_present,
    check_working_directory,
    run_spawn_preflight,
)

MAX_CHILD_DEPTH: Final = 1
_PARENT_MARKER_ENV: Final = "OMH_ISOLATED_HERMES_PARENT"
_DEPTH_ENV: Final = "OMH_ISOLATED_HERMES_DEPTH"
_MARKER_KEY: Final = secrets.token_bytes(32)
_DISPATCH_GUARD = Lock()
# A dispatch's scratch home: the directory name's prefix and, inside it, OMH's own marker file, the only proof a
# later sweep accepts that OMH made a directory.
SCRATCH_PREFIX: Final = "omh-hermes-child-"
SCRATCH_MARKER: Final = ".omh-hermes-child-scratch"
SCRATCH_MARKER_TEXT: Final = "omh-hermes-child-scratch/v1\n"
# The marker's second and last line: the dispatch's own deadline (start + timeout + this margin) as decimal epoch
# seconds. A sweep never takes a home before it; a missing or malformed line means "never swept". A
# marker written by this PR's first head (the header line alone) has none, so it is never swept (nothing shipped it).
SCRATCH_DEADLINE_MARGIN_SECONDS: Final = 3600
_DEADLINE_DIGITS: Final = 20
# The largest deadline the marker can hold. An infinite or oversized timeout records it, so that home is never swept.
_UNBOUNDED_DEADLINE: Final = 10 ** _DEADLINE_DIGITS - 1
# Hermes' `chat` starts a detached `gateway run --idle-exit` for the scratch HERMES_HOME. That gateway is Hermes',
# not this process's child, so it is never signalled. It may still write into the home, or hold its log open (which
# refuses the unlink on Windows), right after the child exits. The removal is retried this often, this far apart,
# then the home is left and said.
SCRATCH_REMOVE_ATTEMPTS: Final = 3
SCRATCH_REMOVE_RETRY_SECONDS: Final = 0.2
# A later dispatch removes a scratch home left behind once its marker is older than this. That is far past Hermes'
# 600 s default idle window for the gateway that held it. The sweep checks at most this many candidates per dispatch.
SCRATCH_SWEEP_AGE_SECONDS: Final = 86400
SCRATCH_SWEEP_LIMIT: Final = 32  # removal attempts per dispatch, oldest marker first
SCRATCH_SWEEP_SCAN_LIMIT: Final = 1024  # candidates examined per dispatch
# The clock and the wait of the scratch step, module-level so tests hold them still.
_clock: Callable[[], float] = time.time
_sleep: Callable[[float], None] = time.sleep
_DISPATCH_ACTIVE = False
_DISPATCH_OBSERVATION_AUTHORITY: Final = object()
_SAFE_ENV_NAMES: Final = frozenset(
    {
        "PATH", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TERM",
        "TMPDIR", "TMP", "TEMP", "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    }
)
_PROVIDER_ENV: Final = {
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "ANTHROPIC_BASE_URL"),
    "azure": ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_VERSION"),
    "bedrock": ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_REGION"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "google": ("GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"),
    "nous": ("NOUS_API_KEY",),
    "openai": ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL"),
    "vertex": ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"),
    "openai-codex": ("OPENAI_API_KEY", "OPENAI_BASE_URL"),
    "claude-sdk-oauth": ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"),
    "opengateway": ("OPENGATEWAY_API_KEY", "OPENGATEWAY_BASE_URL"),
    "qwen": ("QWEN_API_KEY", "QWEN_BASE_URL"),
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"),
    "upstage": ("UPSTAGE_API_KEY", "UPSTAGE_BASE_URL"),
    "zai": ("ZAI_API_KEY", "ZAI_BASE_URL"),
    "xai": ("XAI_API_KEY", "XAI_BASE_URL"),
    "moonshot": ("MOONSHOT_API_KEY", "MOONSHOT_BASE_URL"),
    "commandcode": ("COMMANDCODE_API_KEY", "COMMANDCODE_BASE_URL"),
}
_CREDENTIAL_NAME = re.compile(r"(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTHORIZATION)", re.IGNORECASE)


class HermesChildDispatchError(RuntimeError):
    """Base error for a refused Hermes child dispatch."""


class DispatchConfirmationError(HermesChildDispatchError):
    """Raised unless the invocation is explicitly confirmed."""


class DispatchRecursionError(HermesChildDispatchError):
    """Raised when an isolated Hermes child attempts another dispatch."""


class SpawnPreflightError(HermesChildDispatchError):
    """Raised when a preflight check blocks the child spawn before anything starts.

    Nothing is spawned to produce this: no scratch directory, no dispatch
    guard, no subprocess. `verdict` is the full structured payload from
    `spawn_preflight.run_spawn_preflight`, so a caller that wants more than
    the rendered message can inspect the failed checks and their remedies
    directly instead of re-parsing the exception text.
    """

    def __init__(self, verdict: Mapping[str, object]) -> None:
        self.verdict = dict(verdict)
        failed = verdict.get("failed_checks", ())
        remedies = "; ".join(
            f"{item.get('check')}: {item.get('detail')} -- {item.get('remedy')}"
            for item in failed
            if isinstance(item, Mapping)
        )
        super().__init__(f"Hermes child spawn preflight failed: {remedies}")


@dataclass(frozen=True, slots=True)
class HermesChildRequest:
    prompt: str
    model: str
    provider: str
    reasoning: str
    parent_run_id: str
    run_id: str
    timeout_seconds: float = 900.0
    termination_grace_seconds: float = 2.0
    hermes: str = "hermes"
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    depth: int = 0
    evaluation_context: HermesChildEvaluationContext | None = None
    allow_parallel: bool = False
    # Set only by confirmed paired-run evaluation (`paired_run_arm_home`): the
    # child then runs in that declared arm home, attached to the gateway the
    # harness started for it, instead of a fresh safe-mode scratch home.
    arm_home: PairedRunArmHome | None = None


@dataclass(frozen=True, slots=True)
class HermesChildObservation:
    status: str
    parent_run_id: str
    run_id: str
    depth: int
    model: str
    pid: int | None
    observed_at: str
    evaluation_context: HermesChildEvaluationContext | None
    request_model: str
    timeout_seconds: float
    # Wall-clock seconds from the moment the child process was spawned to the
    # terminal event, on the dispatcher's monotonic clock. None for prepared
    # and running events, and for a terminal event no process ever started.
    elapsed_seconds: float | None
    _authority: object
    # What the arm home held when the child spawned, read from disk by the
    # dispatcher. None outside paired-run evaluation.
    arm_setup: ArmSetup | None = None
    # Paired-run evaluation only, terminal events only: the metadata-only
    # trace of the child's own rows in the arm home's `state.db`, read after
    # it exits and before the home goes (`hermes_child_trace`). None when the
    # store held no readable row of this child.
    cell_trace: CellTrace | None = None

    def has_dispatch_authority(self) -> bool:
        """Return whether this event was sealed by the real dispatcher."""
        return self._authority is _DISPATCH_OBSERVATION_AUTHORITY


def is_dispatch_observation(value: HermesChildObservation) -> bool:
    """Return whether the event came from this process's real dispatcher."""
    return value.has_dispatch_authority()


@dataclass(frozen=True, slots=True)
class HermesChildResult:
    status: str
    parent_run_id: str
    run_id: str
    depth: int
    model: str
    exit_code: int | None
    stdout: str
    stderr: str
    # The child's spend in the `-z --usage-file` vocabulary (token counts,
    # `api_calls`, `model`, `provider`, `estimated_cost_usd` with the
    # `cost_status`/`cost_source` that explain it), summed from the `sessions`
    # rows of its disposable `HERMES_HOME/state.db` after it exits
    # (`_hermes_child_usage`). Hermes writes the usage-file report for
    # `-z/--oneshot` alone and that mode cannot read a prompt from stdin
    # (#1824), so on this transport the ledger is the only source (#1831).
    # Empty, never zero, when the child recorded no API call or the file is
    # missing or unreadable. On `timed_out` or `cancelled` the child was
    # killed, and deltas still in Hermes' daemon token-writer queue at that
    # moment are lost, so the mapping is a lower bound of the spend and
    # carries no marker saying so; the status is the marker. The observation
    # copies this mapping into its session record
    # (`omh coding hermes-child dispatch`).
    usage: Mapping[str, object]
    # The child's process group ended, its pipes drained, and its scratch home
    # is gone. Only the first two can turn a `completed` child into `failed`:
    # a scratch home that could not be removed is said in `cleanup_note`.
    cleanup_verified: bool
    termination_signals: tuple[int, ...]
    stdout_truncated: bool
    stderr_truncated: bool
    # The machine-readable form of the two booleans above: reason code, byte
    # counts, kept ranges, and why no spill pointer exists for a cap the
    # drainer applied while reading. Empty only for a result built before any
    # capture happened.
    stdout_truncation: Mapping[str, object] = field(default_factory=dict)
    stderr_truncation: Mapping[str, object] = field(default_factory=dict)
    # The scratch home this dispatch had to leave ("" when it was removed),
    # and the note that says so; a later dispatch sweeps it
    # (`SCRATCH_SWEEP_AGE_SECONDS`). Never a reason for `status`.
    scratch_left: str = ""
    cleanup_note: str = ""


class CancellationToken:
    """Thread-safe explicit cancellation source without polling delays."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._cancelled = False
        self._callbacks: set[Callable[[], None]] = set()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            callbacks = tuple(self._callbacks)
        for callback in callbacks:
            callback()

    def _register(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if not self._cancelled:
                self._callbacks.add(callback)
                return
        callback()

    def _remove(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._callbacks.discard(callback)


def require_hermes_child_dispatch_boundary(
    *, dispatch_policy: str, confirmed: bool, depth: int = 0
) -> None:
    """Enforce the shared confirmation and depth-one child boundary.

    Both checks ask `resolve_approval_tier` for the DECISION and keep the
    enforcement (which error, which message) here: the confirmation check
    folds `dispatch_policy`/`confirmed` into the single `hermes_child_dispatch`
    operation class the resolver's table already documents as
    non-tightenable-by-posture; the depth check consults the structurally
    `refused` `hermes_child_recursion_depth` class only once the site's own
    trigger (`depth >= MAX_CHILD_DEPTH or` a child environment) fires.
    """
    posture = resolve_security_posture()
    is_confirmed = dispatch_policy == "ask_before_dispatch" and confirmed
    decision = resolve_approval_tier("hermes_child_dispatch", confirmed=is_confirmed, posture=posture)
    if decision.tier != TIER_AUTO_ALLOWED:
        raise DispatchConfirmationError(
            "isolated Hermes dispatch requires ask_before_dispatch and explicit confirmation"
        )
    if depth >= MAX_CHILD_DEPTH or _environment_is_child():
        depth_decision = resolve_approval_tier("hermes_child_recursion_depth", posture=posture)
        if depth_decision.tier != TIER_AUTO_ALLOWED:
            raise DispatchRecursionError("isolated Hermes child dispatch depth is limited to one")


def dispatch_hermes_child(
    request: HermesChildRequest,
    *,
    dispatch_policy: str,
    confirmed: bool,
    cancellation: CancellationToken | None = None,
    observe: Callable[[HermesChildObservation], None] | None = None,
    launch: Callable[[Callable[[], subprocess.Popen[bytes]]], subprocess.Popen[bytes]] | None = None,
) -> HermesChildResult:
    """Run one explicitly confirmed local Hermes child and observe its state."""
    require_hermes_child_dispatch_boundary(
        dispatch_policy=dispatch_policy, confirmed=confirmed, depth=request.depth
    )
    if not request.prompt or not request.model or request.timeout_seconds <= 0:
        raise ValueError("prompt, model, and a positive timeout are required")
    if math.isnan(request.timeout_seconds):
        raise ValueError("prompt, model, and a positive timeout are required")
    verdict = _spawn_preflight(request)
    if not verdict["ready"]:
        raise SpawnPreflightError(verdict)
    if request.evaluation_context is not None:
        seal_evaluation_binding(
            request.evaluation_context,
            request.model,
            request.timeout_seconds,
        )
    if not request.allow_parallel:
        _enter_dispatch_guard()
    try:
        return _dispatch_guarded(request, cancellation=cancellation, observe=observe, launch=launch)
    finally:
        if not request.allow_parallel:
            _leave_dispatch_guard()


def _dispatch_guarded(
    request: HermesChildRequest,
    *,
    cancellation: CancellationToken | None,
    observe: Callable[[HermesChildObservation], None] | None,
    launch: Callable[[Callable[[], subprocess.Popen[bytes]]], subprocess.Popen[bytes]] | None,
) -> HermesChildResult:
    depth = request.depth + 1
    notify = observe or (lambda _item: None)
    observer_error: BaseException | None = None

    spawned_at: float | None = None
    arm_setup: ArmSetup | None = None
    cell_trace: CellTrace | None = None

    def emit(status: str, pid: int | None = None) -> None:
        nonlocal observer_error
        terminal = status in {"completed", "failed", "timed_out", "cancelled"}
        elapsed = (
            max(0.0, time.monotonic() - spawned_at)
            if terminal and spawned_at is not None
            else None
        )
        try:
            notify(HermesChildObservation(
                status,
                request.parent_run_id,
                request.run_id,
                depth,
                request.model,
                pid,
                datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"
                ),
                request.evaluation_context,
                request.model,
                request.timeout_seconds,
                elapsed,
                _DISPATCH_OBSERVATION_AUTHORITY,
                arm_setup,
                cell_trace if terminal else None,
            ))
        except RuntimeError as exc:
            if status == "prepared":
                raise
            observer_error = exc

    emit("prepared")
    if cancellation is not None and cancellation.cancelled:
        emit("cancelled")
        return _result(request, depth, "cancelled", None, "", "", {}, True, ())

    _sweep_scratch_homes()
    scratch_created = _clock()
    marker_text = _marker_text(scratch_created + request.timeout_seconds + SCRATCH_DEADLINE_MARGIN_SECONDS)
    try:
        scratch_path = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX))
        scratch_identity = os.lstat(scratch_path)
    except OSError as exc:
        emit("failed")
        diagnostic = f"Hermes child scratch home could not be created ({type(exc).__name__})"
        return _result(request, depth, "failed", None, "", diagnostic, {}, True, ())
    try:
        # Bytes, never text mode: Windows would write `\r\n`, which the strict reader refuses, so nothing is swept.
        (scratch_path / SCRATCH_MARKER).write_bytes(marker_text.encode("ascii"))
    except OSError as exc:
        # Without its marker a left home could never be swept: no child starts on an unmarked home.
        shutil.rmtree(scratch_path, ignore_errors=True)
        emit("failed")
        diagnostic = f"Hermes child scratch home could not be marked ({type(exc).__name__})"
        return _result(request, depth, "failed", None, "", diagnostic, {}, not scratch_path.exists(), ())
    hermes_home = scratch_path / "hermes"
    home = scratch_path / "home"
    hermes_home.mkdir(mode=0o700)
    home.mkdir(mode=0o700)
    prior_sessions: frozenset[str] = frozenset()
    if request.arm_home is not None:
        # The arm home outlives this child; only its gateway reads it. The
        # scratch directory stays empty and is still removed below.
        hermes_home = request.arm_home.hermes_home
        home = request.arm_home.home
        prior_sessions = state_session_ids(hermes_home)
        arm_setup = observe_arm_setup(request.arm_home)
    marker = _parent_marker(request)
    child_env = _child_env(request, depth, hermes_home, home, marker)
    redaction_values = _redaction_values(request, child_env)
    process: subprocess.Popen[bytes] | None = None
    signals: tuple[int, ...] = ()
    cleanup = True
    status, stdout, stderr = "failed", "", ""
    stdout_capture = BoundedStreamCapture(b"", False)
    stderr_capture = BoundedStreamCapture(b"", False)
    drainers: tuple[PipeDrainer, PipeDrainer] | None = None
    stdin_thread: tuple[Thread, Event] | None = None
    usage: Mapping[str, object] = {}
    interrupted: BaseException | None = None
    handlers: dict[int, object] = {}
    old_mask: object | None = None
    spawn_lock = Lock()
    termination_lock = Lock()
    cancelled = Event()

    def terminate(first_signal: int) -> None:
        nonlocal signals, cleanup
        with termination_lock:
            if process is None:
                return
            sent, complete = _terminate_process_group(
                process, request.termination_grace_seconds, first_signal
            )
            signals = _merge_signals(signals, sent)
            cleanup = complete

    def cancel_child() -> None:
        cancelled.set()
        with spawn_lock:
            spawned = process is not None
        if spawned:
            terminate(signal.SIGTERM)

    if cancellation is not None:
        cancellation._register(cancel_child)
    try:
        try:
            old_mask = _block_relay_signals()
            with spawn_lock:
                if cancelled.is_set():
                    status = "cancelled"
                else:
                    def spawn() -> subprocess.Popen[bytes]:
                        return subprocess.Popen(
                            _argv(request), cwd=request.cwd, env=child_env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=False, close_fds=True, **_process_group_options(),
                        )
                    process = spawn() if launch is None else launch(spawn)
                    spawned_at = time.monotonic()
                    drainers = _start_pipe_drainers(process)
                    stdin_thread = _write_stdin_and_close(process, request.prompt)
            if process is None:
                emit("cancelled")
            else:
                handlers = _install_signal_relays(process)
        except OSError as exc:
            diagnostic = f"Hermes child process could not be started ({type(exc).__name__})"
            stderr_capture = BoundedStreamCapture(diagnostic.encode("utf-8"), False)
            emit("failed")
        finally:
            _restore_signal_mask(old_mask)
            old_mask = None

        if process is not None:
            emit("running", process.pid)
            if observer_error is not None:
                status = "cancelled"
                terminate(signal.SIGTERM)
            deadline = time.monotonic() + request.timeout_seconds
            try:
                _wait_until(process, deadline)
                status = "cancelled" if cancelled.is_set() else (
                    "completed" if process.returncode == 0 else "failed"
                )
            except subprocess.TimeoutExpired:
                status = "cancelled" if cancelled.is_set() else "timed_out"
                terminate(signal.SIGTERM)
            except (KeyboardInterrupt, SystemExit) as exc:
                status, interrupted = "cancelled", exc
                first = signal.SIGINT if isinstance(exc, KeyboardInterrupt) else signal.SIGTERM
                terminate(first)
            finally:
                terminate(signal.SIGTERM)
                if drainers is not None and stdin_thread is not None:
                    pipes_complete = _await_pipe_threads(
                        drainers,
                        stdin_thread,
                        timeout=max(0.25, request.termination_grace_seconds),
                    )
                    cleanup = cleanup and pipes_complete
                    stdout_capture = drainers[0].capture()
                    stderr_capture = drainers[1].capture()
    finally:
        if cancellation is not None:
            cancellation._remove(cancel_child)
        _restore_signal_mask(old_mask)
        _restore_signal_handlers(handlers)
        stdout = _bounded_redacted_output(
            stdout_capture, secrets=redaction_values, source="hermes child stdout capture"
        )
        stderr = _bounded_redacted_output(
            stderr_capture, secrets=redaction_values, source="hermes child stderr capture"
        )
        stdout_truncation = _capture_truncation_record(
            stdout_capture, source="hermes child stdout capture"
        )
        stderr_truncation = _capture_truncation_record(
            stderr_capture, source="hermes child stderr capture"
        )
        if process is not None:
            # After the child has exited and its pipes are drained, before
            # the disposable home goes: the read is bounded, read-only, and
            # never raises; a home the child never wrote leaves `usage` empty.
            usage = read_hermes_child_usage(hermes_home, exclude=prior_sessions)
            if request.arm_home is not None:
                # The arm home outlives this child, so its rows are still
                # there; only names and counts leave the read.
                cell_trace = read_hermes_child_trace(hermes_home, exclude=prior_sessions)
        cleanup_note = _remove_scratch(scratch_path, scratch_created, marker_text, scratch_identity)
    if interrupted is not None:
        emit(status)
        raise interrupted
    if observer_error is not None:
        raise observer_error
    if not cleanup and status == "completed":
        # The child's own process group or pipes did not finish: that is this
        # dispatch's own cleanup, unlike the scratch home Hermes' gateway may hold.
        status = "failed"
    emit(status)
    return _result(
        request, depth, status, process.returncode if process is not None else None,
        stdout, stderr, usage, cleanup and not cleanup_note, signals,
        stdout_capture.truncated, stderr_capture.truncated,
        stdout_truncation, stderr_truncation,
        scratch_left=str(scratch_path) if cleanup_note else "", cleanup_note=cleanup_note,
    )


# The longest single wait handed to `Popen.wait`. Windows converts it to whole milliseconds for
# `WaitForSingleObject`: `inf` raises OverflowError there and a huge finite value does not fit, so a long
# timeout is waited out in slices of this length.
_WAIT_SLICE_SECONDS = 3600.0


def _wait_until(process: subprocess.Popen[bytes], deadline: float) -> None:
    """Wait for the child until the monotonic `deadline` (which may be `inf`); raises `TimeoutExpired` at it."""
    while True:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= _WAIT_SLICE_SECONDS:
            process.wait(timeout=remaining)
            return
        try:
            process.wait(timeout=_WAIT_SLICE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            continue


def _marker_text(deadline: float) -> str:
    """The marker with its deadline line; an infinite or oversized deadline records `_UNBOUNDED_DEADLINE`."""
    value = int(deadline) + 1 if math.isfinite(deadline) and deadline < _UNBOUNDED_DEADLINE else _UNBOUNDED_DEADLINE
    return f"{SCRATCH_MARKER_TEXT}{value}\n"


def _marker_deadline(raw: bytes) -> int | None:
    """The deadline of an exact marker, or None: the header line, then 1-20 ASCII digits and a newline, nothing else."""
    header = SCRATCH_MARKER_TEXT.encode("ascii")
    if not raw.startswith(header):
        return None
    line = raw[len(header):]
    digits = line[:-1]
    if not line.endswith(b"\n") or not 0 < len(digits) <= _DEADLINE_DIGITS or not digits.isdigit():
        return None
    return int(digits)


def _remove_scratch(path: Path, created: float, marker_text: str, identity: os.stat_result | None = None) -> str:
    """Remove a dispatch's scratch home with a few brief retries; "" once it is gone, else the note that says it was left.

    Everything but OMH's marker goes first, then the marker, then the root, so a home
    that is left still carries its marker; one that lost it gets it back, dated
    `created`, for a later sweep. The note never decides the result's status: what
    still writes into the home, or holds a file in it open, is Hermes' gateway for
    that home, which outlives the child by design and is not OMH's to stop.
    """
    reason = ""
    marker = path / SCRATCH_MARKER
    for attempt in range(SCRATCH_REMOVE_ATTEMPTS):
        if attempt:
            _sleep(SCRATCH_REMOVE_RETRY_SECONDS)
        try:
            _remove_marker_last(path, identity)
        except FileNotFoundError:
            if not path.exists():
                return ""
            reason = "FileNotFoundError"
            continue
        except OSError as exc:
            reason = str(exc) if isinstance(exc, _ScratchRefused) else type(exc).__name__
            continue
        if not path.exists():
            return ""
        reason = "a file was written into it again after removal"
    sweep = (f"A later dispatch removes it once it is older than {SCRATCH_SWEEP_AGE_SECONDS} s and past this "
             "dispatch's deadline.")
    if marker_text == _marker_text(math.inf):
        sweep = "Its timeout has no bound, so its deadline never passes and no sweep removes it."
    if path.is_dir() and not marker.exists():
        try:
            marker.write_bytes(marker_text.encode("ascii"))
            os.utime(marker, (created, created))
        except OSError:
            sweep = "Its marker could not be restored, so no sweep removes it."
    return (
        f"scratch home left at {path}: something still used it after the child exited ({reason}); Hermes' idle-exit "
        f"gateway for that home does until it exits. {sweep}"
    )


class _ScratchRefused(OSError):
    """A scratch home this process will not remove: not a plain directory, or not the one its caller checked."""


def _link_like(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _same(info: os.stat_result, other: os.stat_result) -> bool:
    return (info.st_dev, info.st_ino) == (other.st_dev, other.st_ino)


def _descriptor_removal() -> bool:
    return (
        getattr(os, "O_NOFOLLOW", 0) != 0 and getattr(os, "O_DIRECTORY", 0) != 0
        and shutil.rmtree.avoids_symlink_attacks
        and {os.unlink, os.rmdir, os.stat} <= os.supports_dir_fd and os.scandir in os.supports_fd
    )


def _remove_marker_last(path: Path, expected: os.stat_result | None = None) -> None:
    """One removal attempt of a scratch home: every entry but OMH's marker, then the marker, then the root.

    It never follows a link at any level. The root must be a plain directory, not a link or reparse point, and
    the same one (`st_dev`/`st_ino`) as `expected`, the caller's own check. Where the platform allows it, the root is
    opened with `O_NOFOLLOW` and emptied only through that descriptor, and the root's own `rmdir` goes through its
    parent after the name is checked once more. Without that (Windows), the root and each entry are `lstat`ed
    just before use, and a link or reparse point is refused; a check-then-use window remains there, under the
    per-user temp root. A failure part way leaves the marker in place. Raises `OSError` (`_ScratchRefused` for a
    refusal).
    """
    before = os.lstat(path)
    if _link_like(before) or not stat.S_ISDIR(before.st_mode):
        raise _ScratchRefused(f"{path.name} is not a plain directory")
    if expected is not None and not _same(before, expected):
        raise _ScratchRefused(f"{path.name} changed after it was checked")
    if _descriptor_removal():
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY") | getattr(os, "O_NOFOLLOW")
        fd = os.open(path, flags)
        try:
            if not _same(os.fstat(fd), before):
                raise _ScratchRefused(f"{path.name} changed after it was checked")
            with os.scandir(fd) as listing:
                entries = [(entry.name, entry.is_dir(follow_symlinks=False))
                           for entry in listing if entry.name != SCRATCH_MARKER]
            for name, is_directory in entries:
                if is_directory:
                    shutil.rmtree(name, dir_fd=fd)
                else:
                    os.unlink(name, dir_fd=fd)
            try:
                os.unlink(SCRATCH_MARKER, dir_fd=fd)
            except FileNotFoundError:
                pass
        finally:
            os.close(fd)
        parent = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY"))
        try:
            if not _same(os.stat(path.name, dir_fd=parent, follow_symlinks=False), before):
                raise _ScratchRefused(f"{path.name} changed after it was checked")
            os.rmdir(path.name, dir_fd=parent)
        finally:
            os.close(parent)
        return
    with os.scandir(path) as listing:
        entries = [Path(entry.path) for entry in listing if entry.name != SCRATCH_MARKER]
    for entry in entries:
        info = os.lstat(entry)
        if _link_like(info):
            raise _ScratchRefused(f"{entry.name} in {path.name} is a link or reparse point")
        if stat.S_ISDIR(info.st_mode):
            shutil.rmtree(entry)
        else:
            os.unlink(entry)
    (path / SCRATCH_MARKER).unlink(missing_ok=True)
    after = os.lstat(path)
    if _link_like(after) or not _same(after, before):
        raise _ScratchRefused(f"{path.name} changed after it was checked")
    path.rmdir()


def _sweep_scratch_homes() -> None:
    """Remove scratch homes that earlier dispatches had to leave; best effort, bounded, never raises.

    A candidate must be a directory (not a link) directly under the temp root, named with `SCRATCH_PREFIX`, owned
    by this user where the platform has user ids. It must hold `SCRATCH_MARKER` as a regular file with exactly
    `SCRATCH_MARKER_TEXT` and a deadline line (`_marker_deadline`); that marker must be older than
    `SCRATCH_SWEEP_AGE_SECONDS` and the clock past its deadline. At most
    `SCRATCH_SWEEP_SCAN_LIMIT` candidates are examined; at most `SCRATCH_SWEEP_LIMIT` of the eligible ones, oldest
    marker first, get one removal attempt each, and one that fails waits for the next dispatch.
    """
    now = _clock()
    cutoff = now - SCRATCH_SWEEP_AGE_SECONDS
    candidates: list[Path] = []
    try:
        with os.scandir(tempfile.gettempdir()) as listing:
            for entry in listing:
                if entry.name.startswith(SCRATCH_PREFIX) and entry.is_dir(follow_symlinks=False):
                    candidates.append(Path(entry.path))
                    if len(candidates) >= SCRATCH_SWEEP_SCAN_LIMIT:
                        break
    except OSError:
        return
    eligible: list[tuple[float, Path]] = []
    for path in candidates:
        marker = path / SCRATCH_MARKER
        try:
            info = marker.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_mtime > cutoff:
                continue
            root = path.lstat()
            if hasattr(os, "getuid") and root.st_uid != os.getuid():
                continue
            with marker.open("rb") as handle:
                raw = handle.read(len(SCRATCH_MARKER_TEXT) + _DEADLINE_DIGITS + 2)
            deadline = _marker_deadline(raw)
            if deadline is None or now <= deadline:
                continue
        except OSError:
            continue
        eligible.append((info.st_mtime, path, raw, root))
    for mtime, path, raw, root in sorted(eligible, key=lambda item: (item[0], item[1]))[:SCRATCH_SWEEP_LIMIT]:
        try:
            _remove_marker_last(path, root)
        except OSError:
            # Failed after the marker went (the root could not be removed): put the same marker back, with its old
            # time, so the next dispatch can still take the home.
            marker = path / SCRATCH_MARKER
            try:
                if path.is_dir() and not marker.exists():
                    marker.write_bytes(raw)
                    os.utime(marker, (mtime, mtime))
            except OSError:
                pass


def _spawn_preflight(request: HermesChildRequest) -> dict[str, object]:
    """Everything about this request that can be checked before any spawn.

    Executable presence covers `request.hermes` exactly as the eventual spawn
    would resolve it; working directory covers an explicit `request.cwd`
    override. Both are unconditional prerequisites of a successful spawn on
    every provider, so blocking on them changes no passing case.

    Provider auth is deliberately NOT preflighted here even though
    `_PROVIDER_ENV` documents which variables a real provider needs: this
    dispatch's actual auth contract is "whatever the spawned Hermes CLI
    itself accepts", which prepare-time cannot fully know (a test double, a
    provider Hermes resolves outside these variables, a future auth channel).
    Refusing early on a documented-but-not-actually-required variable would
    be a behavior change for a spawn that would otherwise have succeeded, so
    that gap is left for the Hermes CLI itself to report.
    """
    return run_spawn_preflight(
        [
            check_executable_present(request.hermes),
            check_working_directory(request.cwd),
        ]
    )


def _argv(request: HermesChildRequest) -> tuple[str, ...]:
    # Prompt text must never enter argv, and `chat --query-file -` is the one
    # Hermes transport that reads it from stdin (`_read_query_file` in
    # hermes_cli/main.py). The top-level `-z/--oneshot PROMPT` takes the
    # prompt as its positional value and reads no stdin, so the former
    # `--oneshot -` handed the child the literal prompt "-" (#1824).
    # `--quiet` drops the banner, spinner and tool previews, so a completed
    # turn prints only the final response (Hermes' `_run_quiet_single_query`,
    # read, not observed against a live provider here) with the session-id
    # line on stderr. A start Hermes refuses before the turn -- no provider
    # visible to the child -- prints its first-run guidance on stdout and
    # exits 1, which `-z` did not; the verdict parsers need a literal tag, so
    # that text reads as no verdict. `--usage-file` is a `-z`-only report and
    # is not passed: this path writes none, so the child's spend is read from
    # the `sessions` rows of its disposable `HERMES_HOME/state.db` instead
    # (`_hermes_child_usage`, #1831). Safe mode
    # is the strongest customization boundary in the installed Hermes CLI;
    # explicit ignore flags keep the contract visible and compatible.
    # Confirmed paired-run evaluation alone drops safe mode and the user-config
    # bypass: its declared arm home (`paired_run_arm_home`) is the config to
    # read, and the variant's plugin and skills are the point of the arm. Both
    # arms take the same flags, so the arms differ only by what the home holds:
    # the home's toolsets are `file,skills`, plus `terminal` and/or
    # `delegation` with the run's explicit opt-in, identical for both arms. A
    # `delegation` arm's `delegate_task` children are threads of the arm
    # gateway, one level deep, pinned to the arm's model by the home's config;
    # this process still spawns nothing but the one CLI child. `--yolo` is never passed,
    # so Hermes' dangerous-command approval stays on.
    isolation = (
        ("--ignore-rules", "--toolsets", request.arm_home.toolsets)
        if request.arm_home is not None
        else ("--safe-mode", "--ignore-user-config", "--ignore-rules", "--toolsets", "file")
    )
    command = (
        request.hermes, "chat", "--query-file", "-", "--quiet",
        "--provider", request.provider, "--model", request.model,
        "--reasoning", request.reasoning,
        *isolation,
    )
    if os.name == "nt" and Path(request.hermes).suffix.casefold() == ".py":
        return (sys.executable, *command)
    return command


def _process_group_options() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _child_env(
    request: HermesChildRequest,
    depth: int,
    hermes_home: Path,
    home: Path,
    marker: str,
) -> dict[str, str]:
    source = os.environ if request.env is None else request.env
    child = {name: source[name] for name in _SAFE_ENV_NAMES if source.get(name)}
    child.setdefault("PATH", os.defpath)
    # Authentication is copied only from the caller-selected provider's
    # documented variables. Hermes' auth.json and .env remain unreachable in
    # the disposable homes, and credentials for every other provider stay out.
    provider_names = set(_PROVIDER_ENV.get(request.provider.lower(), ()))
    if request.arm_home is not None:
        provider_names = set(request.arm_home.key_env_names)
    for name in provider_names:
        value = source.get(name)
        if value:
            child[name] = value
    child.update(
        {
            "HOME": str(home),
            "HERMES_HOME": str(hermes_home),
            "HERMES_IGNORE_RULES": "1",
            "OMH_ISOLATED_HERMES_ROUTING": "disabled",
            "OMH_ISOLATED_HERMES_MAX_DEPTH": str(MAX_CHILD_DEPTH),
            _DEPTH_ENV: str(depth),
            _PARENT_MARKER_ENV: marker,
        }
    )
    if request.arm_home is None:
        child["HERMES_SAFE_MODE"] = "1"
        child["HERMES_IGNORE_USER_CONFIG"] = "1"
    return child


def provider_env_names(provider: str) -> tuple[str, ...]:
    """The documented credential variables of a built-in provider."""
    return tuple(_PROVIDER_ENV.get(provider.lower(), ()))


def arm_gateway_env(
    source: Mapping[str, str],
    hermes_home: Path,
    home: Path,
    tmp: Path,
    key_env_names: tuple[str, ...],
) -> dict[str, str]:
    """The minimal environment of a paired-run arm's harness-owned gateway.

    The gateway runs every turn's tools, so it carries the same depth-one
    markers a child does: an agent inside it cannot start another dispatch.
    The provider key arrives only by the variable names the arm declared.
    """
    env = {name: source[name] for name in _SAFE_ENV_NAMES if source.get(name)}
    env.setdefault("PATH", os.defpath)
    for name in key_env_names:
        value = source.get(name)
        if value:
            env[name] = value
    env.update(
        {
            "HOME": str(home),
            "HERMES_HOME": str(hermes_home),
            "TMPDIR": str(tmp),
            "OMH_ISOLATED_HERMES_ROUTING": "disabled",
            "OMH_ISOLATED_HERMES_MAX_DEPTH": str(MAX_CHILD_DEPTH),
            _DEPTH_ENV: str(MAX_CHILD_DEPTH),
            _PARENT_MARKER_ENV: f"v1.gateway.{secrets.token_urlsafe(18)}",
        }
    )
    return env


def _environment_is_child() -> bool:
    # Request.env is deliberately irrelevant: a child cannot bypass recursion
    # by passing env={} or deleting keys from a proposed subprocess mapping.
    if os.environ.get(_PARENT_MARKER_ENV):
        return True
    try:
        return int(os.environ.get(_DEPTH_ENV, "0")) >= MAX_CHILD_DEPTH
    except ValueError:
        return True


def _parent_marker(request: HermesChildRequest) -> str:
    nonce = secrets.token_urlsafe(18)
    identity = f"{nonce}\0{request.parent_run_id}\0{request.run_id}".encode()
    signature = hmac.new(_MARKER_KEY, identity, hashlib.sha256).hexdigest()
    return f"v1.{nonce}.{signature}"


def _redaction_values(request: HermesChildRequest, child_env: Mapping[str, str]) -> set[str]:
    source = os.environ if request.env is None else request.env
    values = {request.prompt}
    if request.arm_home is not None:
        values.update(
            source[name] for name in request.arm_home.key_env_names if source.get(name)
        )
    values.update(
        value for name, value in source.items()
        if value and _CREDENTIAL_NAME.search(name)
    )
    values.update(
        value for name, value in child_env.items()
        if value and _CREDENTIAL_NAME.search(name)
    )
    return values


def _enter_dispatch_guard() -> None:
    global _DISPATCH_ACTIVE
    with _DISPATCH_GUARD:
        if _DISPATCH_ACTIVE:
            raise DispatchRecursionError("an isolated Hermes child dispatch is already active")
        _DISPATCH_ACTIVE = True


def _leave_dispatch_guard() -> None:
    global _DISPATCH_ACTIVE
    with _DISPATCH_GUARD:
        _DISPATCH_ACTIVE = False


def _result(
    request: HermesChildRequest, depth: int, status: str, exit_code: int | None,
    stdout: str, stderr: str, usage: Mapping[str, object], cleanup: bool,
    signals: tuple[int, ...], stdout_truncated: bool = False,
    stderr_truncated: bool = False,
    stdout_truncation: Mapping[str, object] | None = None,
    stderr_truncation: Mapping[str, object] | None = None,
    *,
    scratch_left: str = "",
    cleanup_note: str = "",
) -> HermesChildResult:
    return HermesChildResult(
        status, request.parent_run_id, request.run_id, depth, request.model, exit_code,
        stdout, stderr, usage, cleanup, signals,
        stdout_truncated, stderr_truncated,
        dict(stdout_truncation or {}),
        dict(stderr_truncation or {}),
        scratch_left, cleanup_note,
    )
