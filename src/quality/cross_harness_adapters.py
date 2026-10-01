from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from typing import Final

from .cross_harness_adapter_evidence import (
    AdapterEvidenceBundle,
    AdapterEvidenceCase,
    CommandEvidence,
    SourceEvidence,
    adapter_evidence_payload,
    adapter_request_payload,
    adapter_result_payload,
    artifact_content_digest,
)
from .cross_harness_adapter_model import (
    AdapterContractError,
    AdapterRequest,
    AdapterResult,
    canonical_digest,
    parse_adapter_result,
)
from . import cross_harness_adapter_io as _adapter_io
from .cross_harness_adapter_sandbox import (
    ChildContext as _ChildContext,
    PopenFactory as _PopenFactory,
    ProcessObservation as _ProcessObservation,
    allocate_child as _allocate_child,
    backend as _backend,
    backend_available as _backend_available,
    WRITE_ONLY_BACKENDS as _WRITE_ONLY_BACKENDS,
    environment_is_safe as _environment_is_safe,
    observe_process as _observe_process,
    preflight as _preflight,
    read_roots_are_safe as _read_roots_are_safe,
    runtime_roots as _runtime_roots,
    sandbox_command as _sandbox_command,
    unique_roots as _unique_roots,
)
from .cross_harness_benchmark_input import BenchmarkJsonInputError, decode_benchmark_bytes
from .cross_harness_benchmark_values import JsonValue, json_map


RECEIPT_SCHEMA: Final = "cross_harness_adapter_runner_receipt/v1"
_write_json = _adapter_io.write_json


@dataclass(frozen=True, slots=True)
class ExecutionSpec:
    argv: tuple[str, ...]
    read_roots: tuple[Path, ...]
    scratch_parent: Path
    backend: str = "auto"
    allow_network: bool = False
    environment: tuple[tuple[str, str], ...] = ()
    version_argv: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OutputContract:
    receipt_path: Path
    evidence_path: Path
    harness_id: str
    source_binding: SourceEvidence
    command_evidence: CommandEvidence


@dataclass(frozen=True, slots=True)
class RepetitionReceipt:
    repetition: int
    spawn_digest: str
    request_digest: str
    result_digest: str | None
    process_status: str
    process_group_terminated: bool
    exit_code: int | None
    reason_code: str
    stdout_hash: str
    stdout_bytes: int
    stderr_hash: str
    stderr_bytes: int
    artifact_hash: str | None
    inventory_digest: str
    inventory: tuple[_adapter_io.InventoryEntry, ...]
    result: AdapterResult | None


@dataclass(frozen=True, slots=True)
class AdapterRunReceipt:
    schema_version: str
    status: str
    reason_code: str
    backend: str
    backend_version: str
    preflight: str
    network_allowed: bool
    request_digest: str
    argv_digest: str
    version_spawn_digest: str
    cleanup_verified: bool
    repetitions: tuple[RepetitionReceipt, ...]


def run_adapter(
    request: AdapterRequest,
    spec: ExecutionSpec,
    output: OutputContract,
    popen_factory: _PopenFactory = subprocess.Popen,
) -> AdapterRunReceipt:
    _adapter_io.unlink_file(output.evidence_path)
    _adapter_io.unlink_file(output.receipt_path)
    request_digest = canonical_digest(adapter_request_payload(request))
    backend = _backend(spec.backend)
    allocated: list[Path] = []
    failure = _prelaunch_failure(request, spec, backend, output)
    if failure is not None:
        return _finish(_receipt("unavailable", failure, backend, "unavailable", "failed", request_digest, spec, "0" * 64, _roots_absent(allocated), ()), output)
    located = shutil.which(spec.argv[0])
    if located is None:
        return _finish(_receipt("unavailable", "executable_not_found", backend, "unavailable", "failed", request_digest, spec, "0" * 64, _roots_absent(allocated), ()), output)
    executable = str(Path(located).resolve())
    system_roots = _runtime_roots(backend)
    roots = _unique_roots((*spec.read_roots, Path(executable).parent, Path(sys.base_prefix), *system_roots))
    with TemporaryDirectory(prefix="omh-adapter-preflight-", dir=spec.scratch_parent) as root_text:
        child = _child_context(Path(root_text), request, request_digest, 0)
        allocated.append(child.root)
        ready, backend_version = _preflight(backend, roots, child, spec.allow_network, _environment(spec, child, request_digest, 0))
    if not ready:
        return _finish(_receipt("unavailable", "sandbox_preflight_failed", backend, backend_version, "failed", request_digest, spec, "0" * 64, _roots_absent(allocated), ()), output)
    with TemporaryDirectory(prefix="omh-adapter-version-", dir=spec.scratch_parent) as root_text:
        version_child = _child_context(Path(root_text), request, request_digest, 0)
        allocated.append(version_child.root)
        logical_version = spec.version_argv or (spec.argv[0], "--version")
        version_argv = (executable, *logical_version[1:])
        version_environment = _environment(spec, version_child, request_digest, 0)
        version = _observe_process(
            _sandbox_command(version_argv, backend, roots, version_child, spec.allow_network, version_environment, backend_version),
            version_child.work,
            version_environment,
            min(request.timeout_seconds, 10),
            popen_factory, backend_version,
        )
    version_text = (version.stdout_sample + version.stderr_sample).decode("utf-8", "replace")
    if not version.process_group_terminated:
        return _finish(_receipt("unavailable", "process_cleanup_failed", backend, backend_version, "passed", request_digest, spec, version_child.spawn_digest, False, ()), output)
    if version.status != "exit" or version.exit_code != 0 or request.executable_version not in version_text:
        return _finish(_receipt("unavailable", "executable_version_mismatch", backend, backend_version, "passed", request_digest, spec, version_child.spawn_digest, _roots_absent(allocated), ()), output)
    repetitions: list[RepetitionReceipt] = []
    for index in range(1, request.repetition + 1):
        with TemporaryDirectory(prefix="omh-adapter-run-", dir=spec.scratch_parent) as root_text:
            child = _child_context(Path(root_text), request, request_digest, index)
            allocated.append(child.root)
            repetitions.append(_run_once(request, spec, backend, backend_version, roots, executable, child, index, request_digest, popen_factory))
    failed = next((item.reason_code for item in repetitions if item.reason_code != "none"), None)
    receipt = _receipt("observed_failed" if failed else "observed_success", failed or "none", backend, backend_version, "passed", request_digest, spec, version_child.spawn_digest, _roots_absent(allocated) and version.process_group_terminated and all(item.process_group_terminated for item in repetitions), tuple(repetitions))
    evidence = _evidence_bundle(request, request_digest, receipt, output)
    return _finish(receipt, output, evidence)


def runner_receipt_payload(receipt: AdapterRunReceipt) -> dict[str, JsonValue]:
    return {"schema_version": receipt.schema_version, "status": receipt.status, "reason_code": receipt.reason_code, "backend": receipt.backend, "backend_version": receipt.backend_version, "preflight": receipt.preflight, "network_allowed": receipt.network_allowed, "request_digest": receipt.request_digest, "argv_digest": receipt.argv_digest, "version_spawn_digest": receipt.version_spawn_digest, "cleanup_verified": receipt.cleanup_verified, "repetitions": [_repetition_payload(item) for item in receipt.repetitions]}


def _child_context(root: Path, request: AdapterRequest, request_digest: str, repetition: int) -> _ChildContext:
    return _allocate_child(root, adapter_request_payload(request), request_digest, repetition)


def _run_once(request: AdapterRequest, spec: ExecutionSpec, backend: str, backend_version: str, roots: tuple[Path, ...], executable: str, child: _ChildContext, index: int, request_digest: str, popen_factory: _PopenFactory) -> RepetitionReceipt:
    started_ns = time.time_ns()
    argv = (executable, *spec.argv[1:])
    environment = _environment(spec, child, request_digest, index)
    observed = _observe_process(_sandbox_command(argv, backend, roots, child, spec.allow_network, environment, backend_version), child.work, environment, request.timeout_seconds, popen_factory, backend_version)
    result, reason = _artifact_result(child.artifact_path, request, request_digest, observed, started_ns)
    if observed.overflow:
        reason = "output_limit_exceeded"
    if observed.status == "timeout":
        reason = "process_timeout"
    if observed.status == "crash":
        reason = "process_crash"
    if observed.status == "exit" and observed.exit_code != 0:
        reason = "adapter_exit_nonzero"
    excluded = {child.request_path.relative_to(child.root).as_posix(), child.artifact_path.relative_to(child.root).as_posix()}
    try:
        inventory = _adapter_io.inventory(child.root, excluded)
    except _adapter_io.UnsafeRegularFileError:
        inventory, reason = (), "unsafe_inventory_entry"
    if not observed.process_group_terminated:
        reason = "process_cleanup_failed"
    result_digest = canonical_digest(adapter_result_payload(result)) if result else None
    inventory_payload: list[JsonValue] = [{"path": item.path, "sha256": item.sha256} for item in inventory]
    return RepetitionReceipt(index, child.spawn_digest, request_digest, result_digest, observed.status, observed.process_group_terminated, observed.exit_code, reason, observed.stdout_hash, observed.stdout_bytes, observed.stderr_hash, observed.stderr_bytes, result.artifact_hash if result else None, canonical_digest(inventory_payload), inventory, result)


def _artifact_result(path: Path, request: AdapterRequest, request_digest: str, observed: _ProcessObservation, started_ns: int) -> tuple[AdapterResult | None, str]:
    try:
        raw, metadata = _adapter_io.read_regular_file(path)
    except FileNotFoundError:
        return None, "artifact_missing"
    except _adapter_io.UnsafeRegularFileError:
        return None, "artifact_not_regular_file"
    except OSError:
        return None, "artifact_unreadable"
    if metadata.st_mtime_ns < started_ns:
        return None, "stale_artifact"
    try:
        result = parse_adapter_result(json_map(decode_benchmark_bytes(raw)))
    except (AdapterContractError, BenchmarkJsonInputError) as error:
        return None, str(error)
    if result.request_digest != request_digest or (result.fixture_id, result.adapter_id, result.capability_id) != (request.fixture_id, request.adapter_id, request.capability_id):
        return None, "request_digest_mismatch"
    if result.artifact_hash != artifact_content_digest(adapter_result_payload(result)):
        return None, "artifact_hash_mismatch"
    if observed.status != result.process_status.value or observed.exit_code != result.exit_code:
        return None, "process_evidence_mismatch"
    if any(event.result != "pass" for event in (*result.skill_events, *result.tool_events, *result.child_results)):
        return result, "failed_child_event"
    return result, "none"


def _prelaunch_failure(request: AdapterRequest, spec: ExecutionSpec, backend: str, output: OutputContract) -> str | None:
    if output.receipt_path == output.evidence_path or not output.harness_id:
        return "invalid_output_contract"
    if not spec.scratch_parent.is_dir():
        return "scratch_allocator_unavailable"
    if not spec.argv or canonical_digest(list(spec.argv)) != request.argv_digest or Path(spec.argv[0]).name != request.executable:
        return "argv_digest_mismatch"
    if spec.version_argv and Path(spec.version_argv[0]).name != request.executable:
        return "argv_digest_mismatch"
    if not _backend_available(backend) or backend in _WRITE_ONLY_BACKENDS:
        return "sandbox_backend_unavailable"
    if not _environment_is_safe(spec.environment):
        return "credential_environment_rejected"
    if not _read_roots_are_safe(spec.read_roots):
        return "unsafe_read_root"
    return None


def _environment(spec: ExecutionSpec, child: _ChildContext, request_digest: str, repetition: int) -> dict[str, str]:
    values = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONNOUSERSITE": "1", "HOME": str(child.home), "TMPDIR": str(child.temporary), "OMH_ADAPTER_REQUEST": str(child.request_path), "OMH_ADAPTER_OUTPUT": str(child.artifact_path), "OMH_OUTSIDE_PROBE": str(child.root.parent / "outside-write-sentinel"), "OMH_REQUEST_DIGEST": request_digest, "OMH_REPETITION_INDEX": str(repetition), "OMH_SPAWN_DIGEST": child.spawn_digest}
    values.update(spec.environment)
    return values


def _evidence_bundle(request: AdapterRequest, request_digest: str, receipt: AdapterRunReceipt, output: OutputContract) -> AdapterEvidenceBundle | None:
    selected = next((item for item in receipt.repetitions if item.reason_code != "none" and item.result is not None), None)
    if selected is None:
        selected = next((item for item in reversed(receipt.repetitions) if item.result is not None), None)
    if selected is None or selected.result is None or selected.result_digest is None:
        return None
    result = selected.result
    observed_exit = result.exit_code
    if observed_exit is None:
        observed_exit = 124 if result.process_status.value == "timeout" else 1
    semantic = "pass" if selected.reason_code == "none" else "fail"
    command = replace(output.command_evidence, observed_exit=observed_exit, observed_semantic_result=semantic)
    case = AdapterEvidenceCase(request.fixture_id, request, request_digest, result, selected.result_digest, output.source_binding, command)
    draft = AdapterEvidenceBundle("cross_harness_adapter_evidence/v1", request.corpus_digest, output.harness_id, (case,), "0" * 64)
    raw = adapter_evidence_payload(draft)
    digest = canonical_digest({key: value for key, value in raw.items() if key != "bundle_digest"})
    return replace(draft, bundle_digest=digest)


def _finish(receipt: AdapterRunReceipt, output: OutputContract, evidence: AdapterEvidenceBundle | None = None) -> AdapterRunReceipt:
    _write_json(output.receipt_path, runner_receipt_payload(receipt))
    if evidence is not None:
        _write_json(output.evidence_path, adapter_evidence_payload(evidence))
    return receipt


def _receipt(status: str, reason: str, backend: str, version: str, preflight: str, request_digest: str, spec: ExecutionSpec, version_spawn_digest: str, cleanup_verified: bool, repetitions: tuple[RepetitionReceipt, ...]) -> AdapterRunReceipt:
    return AdapterRunReceipt(RECEIPT_SCHEMA, status, reason, backend, version, preflight, spec.allow_network, request_digest, canonical_digest(list(spec.argv)), version_spawn_digest, cleanup_verified, repetitions)


def _roots_absent(roots: Sequence[Path]) -> bool:
    return all(not root.exists() and not root.is_symlink() for root in roots)


def _repetition_payload(item: RepetitionReceipt) -> JsonValue:
    return {"repetition": item.repetition, "spawn_digest": item.spawn_digest, "request_digest": item.request_digest, "result_digest": item.result_digest, "process_status": item.process_status, "process_group_terminated": item.process_group_terminated, "exit_code": item.exit_code, "reason_code": item.reason_code, "stdout_hash": item.stdout_hash, "stdout_bytes": item.stdout_bytes, "stderr_hash": item.stderr_hash, "stderr_bytes": item.stderr_bytes, "artifact_hash": item.artifact_hash, "inventory_digest": item.inventory_digest, "inventory": [{"path": entry.path, "sha256": entry.sha256} for entry in item.inventory]}
