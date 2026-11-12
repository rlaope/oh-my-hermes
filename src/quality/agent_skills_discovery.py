"""Agent Skills host evidence: five stages per host and scope, fail-closed receipts.

Evidence layer for the host-adapter surface (#1525). For every host in
``HOST_ADAPTERS`` and both scopes it records five stages -- installed,
discovered, nominated, loaded, executed -- and never infers one stage from
another. A receipt binds what it saw to the host version, the operating
system, the scan path, the pack inventory's ``source_digest``, and the pack
``catalog_revision``. ``parse_receipt`` raises on a receipt that fails any check
it makes (field set, enumerations, host-version agreement, stage order and
reasons, credential-like text) instead of passing it; it cannot check free-text
details against the disk.

OMH observes ``installed`` itself, with no subprocess: it reads the host's
scan path under the project root (repo scope) or under the home it is given
(user scope) and compares every file with its host's pack inventory
(``agent-skills/.omh-agent-skills-manifest.json``, or Claude Code's own
``.claude/agent-skills/.omh-agent-skills-manifest.json``). OMH writes nothing. OMH
has verified no credential-free, non-interactive command in any supported host
that lists the skills the host discovered, and it makes no model call, so the
four later stages are ``not_observed`` and the receipt carries the host's
``probe_unsupported`` reason. That reason is not a claim that the host cannot
discover Agent Skills.

The host version comes from the readiness module's approved
``<cli> --version`` probe, and only for a CLI in that probe's set; that
``--version`` run is the only host process this module causes. The set is the
readiness probe's, but the trigger is wider: this runs the probe for every
such CLI on PATH, where readiness ran pi only for pi-family-runtime and opencode only
when neither pi nor its distribution host was on PATH. Any other host's version is recorded as
not observed, with the reason.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Final

from ..install.agent_skills_projection import _checked_path, agent_skill_files, agent_skills_manifest
from ..plugin_bundle.omh._governance_safety import contains_credential_like_material
from ..skills.host_adapters import (
    HOST_ADAPTERS, host_adapter_manifest, host_pack_files, source_digest as pack_source_digest,
)
from ..system.hashutil import sha256_file


RECEIPT_SCHEMA_VERSION: Final = "omh_agent_skills_discovery/v1"
EVIDENCE_SCHEMA_VERSION: Final = "omh_agent_skills_evidence/v1"
ADAPTER_SCHEMA_VERSION: Final = "omh_host_adapter/v1"
STAGES: Final = ("installed", "discovered", "nominated", "loaded", "executed")
HOSTS: Final = tuple(sorted(adapter.host for adapter in HOST_ADAPTERS))
SCOPES: Final = ("repo", "user")
OUTCOMES: Final = ("observed", "not_observed", "hold")
# Why `installed` has the outcome it has, as a closed vocabulary so a reader
# never parses `detail` to tell an unreadable path from an edited pack.
INSTALLED_REASONS: Final[Mapping[str, str]] = {
    "match": "observed",
    "absent": "not_observed",
    "partial": "hold",
    "modified": "hold",
    "symlink": "hold",
    "unreadable": "hold",
}
LATER_STAGE_REASON: Final = "probe_unsupported"
OPERATING_SYSTEMS: Final = ("darwin", "linux", "other", "windows")
TRANSFORMS: Final = ("copy-only",)
# What observed the stages after `installed`. `none` is the only value because
# no probe for them exists; a new value lands with the first probe that emits
# it, never ahead of it.
DISCOVERY_MECHANISMS: Final = ("none",)
# OMH creates no file, directory or session, so it has nothing to clean up.
# What a `--version` child writes for itself is neither prevented nor observed.
CLEANUP_RESULTS: Final = ("nothing_created",)
HOST_VERSION_STATUSES: Final = (
    "observed",
    "no_approved_probe",
    "executable_missing",
    "probe_failed",
    "output_unrecognized",
)
MAX_TEXT: Final = 240
OBSERVED_CLAIM_BOUNDARY: Final = (
    "OMH read each host scan path and compared its bytes with the pack inventory, writing nothing itself. "
    "It started no host session and made no model call; the only host process it ran is `<cli> --version`, "
    "for a CLI in the readiness probe's set. `installed` is the only stage this command observes. "
    "Discovered, nominated, loaded and executed stay not_observed (probe_unsupported) and are never inferred "
    "from installation. A receipt holds only for the host version, OS, scan path, source digest and catalog "
    "revision it recorded."
)
STORED_CLAIM_BOUNDARY: Final = (
    "OMH read no scan path: it validated stored receipts and compared them with the current pack and the host "
    "versions observed now, through `<cli> --version` only, for a CLI in the readiness probe's set. It "
    "started no host session and made no model call. A stored receipt is evidence from the run that recorded "
    "it, not from this one."
)

# Why no stage after `installed` is probed, per host. None of these is a claim
# that the host cannot discover Agent Skills.
PROBE_UNSUPPORTED: Final[Mapping[str, str]] = {
    "claude": (
        "OMH has verified no credential-free, non-interactive command that lists discovered skills; a "
        "model session (claude -p) could list them but needs provider credentials, and OMH does not start one"
    ),
    "codex": (
        "OMH has verified no credential-free, non-interactive command that lists discovered skills; a "
        "model session (codex exec) could list them but needs provider credentials, and OMH does not start one"
    ),
    "opencode": (
        "OMH has verified no credential-free, non-interactive command that lists discovered skills; a "
        "model session (opencode run) could list them but needs provider credentials, and OMH does not start one"
    ),
    "cursor": "OMH has verified no credential-free, non-interactive command that lists discovered skills",
    "openclaw": "OMH has verified no credential-free, non-interactive command that lists discovered skills",
    "pi": "OMH has verified no credential-free, non-interactive command that lists discovered skills",
}

RECEIPT_KEYS: Final = frozenset(
    {
        "schema_version",
        "host",
        "scope",
        "os",
        "target_path",
        "adapter_schema_version",
        "transform",
        "source_digest",
        "catalog_revision",
        "host_version",
        "host_version_status",
        "version_command",
        "discovery_mechanism",
        "credential_required",
        "probe_unsupported",
        "started_at",
        "ended_at",
        "cleanup",
        "stages",
    }
)
STAGE_KEYS: Final = frozenset({"stage", "outcome", "reason", "detail"})

_HEX_64: Final = re.compile(r"[0-9a-f]{64}")
_VERSION: Final = re.compile(r"[0-9]+(?:\.[0-9]+){1,3}(?:[-+][0-9A-Za-z.-]{1,32})?")
_STAMP_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"
_STAMP: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


class DiscoveryEvidenceError(ValueError):
    """Raised when a descriptor or receipt violates the evidence contract."""


def _member(value: object, allowed: Iterable[str], *, field: str) -> str:
    if not isinstance(value, str) or value not in tuple(allowed):
        raise DiscoveryEvidenceError(f"invalid {field}: {value!r}")
    return value


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryEvidenceError(f"missing {field}")
    if len(value) > MAX_TEXT:
        raise DiscoveryEvidenceError(f"{field} too long")
    if contains_credential_like_material(value):
        raise DiscoveryEvidenceError(f"{field} carries credential-like material")
    return value


def _digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _HEX_64.fullmatch(value):
        raise DiscoveryEvidenceError(f"invalid {field}")
    return value


def _relative_path(value: object, *, field: str) -> str:
    text = _text(value, field=field)
    path = PurePosixPath(text)
    if path.is_absolute() or "\\" in text or ":" in text or any(part in ("", ".", "..") for part in text.split("/")):
        raise DiscoveryEvidenceError(f"{field} must be a relative POSIX path")
    return text


def _stamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not _STAMP.fullmatch(value):
        raise DiscoveryEvidenceError(f"invalid {field}")
    try:
        return datetime.strptime(value, _STAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise DiscoveryEvidenceError(f"invalid {field}") from exc


def _version_probed() -> frozenset[str]:
    from ..coding.executor_readiness import version_probed_agent_clis

    return version_probed_agent_clis()


@dataclass(frozen=True, slots=True)
class ProbeDescriptor:
    """Checked-in description of what OMH may observe for one host and scope.

    Host, scan path and transform come from ``HOST_ADAPTERS``; nothing here
    re-types them. ``probe_descriptors`` sets ``version_command`` only for a
    CLI in the readiness probe's ``--version`` set, and ``parse_receipt``
    rejects a version probe for any other host. ``credential_required`` is
    OMH's conservative assumption, not an observation: OMH has verified no
    credential-free listing command for any host. ``probe_unsupported`` says
    why the stages after ``installed`` are not probed.
    """

    host: str
    scope: str
    target_path: str
    transform: str
    version_command: tuple[str, ...] | None
    discovery_mechanism: str
    credential_required: bool
    probe_unsupported: str

    def __post_init__(self) -> None:
        _member(self.host, HOSTS, field="host")
        _member(self.scope, SCOPES, field="scope")
        _relative_path(self.target_path, field="target_path")
        _member(self.transform, TRANSFORMS, field="transform")
        _member(self.discovery_mechanism, DISCOVERY_MECHANISMS, field="discovery_mechanism")
        if self.version_command is not None and self.version_command != (self.host, "--version"):
            raise DiscoveryEvidenceError(f"version command must be `{self.host} --version`")
        if type(self.credential_required) is not bool:
            raise DiscoveryEvidenceError("credential_required must be a bool")
        _text(self.probe_unsupported, field="probe_unsupported")


def probe_descriptors(version_probed: Iterable[str] | None = None) -> tuple[ProbeDescriptor, ...]:
    """One descriptor per host and scope, derived from ``HOST_ADAPTERS``, sorted."""
    probed = _version_probed() if version_probed is None else frozenset(version_probed)
    return tuple(
        ProbeDescriptor(
            host=adapter.host,
            scope=scope,
            target_path=adapter.repo_path if scope == "repo" else adapter.user_path,
            transform=adapter.transform,
            version_command=(adapter.host, "--version") if adapter.host in probed else None,
            discovery_mechanism="none",
            credential_required=True,
            probe_unsupported=PROBE_UNSUPPORTED[adapter.host],
        )
        for adapter in sorted(HOST_ADAPTERS, key=lambda item: item.host)
        for scope in SCOPES
    )


@dataclass(frozen=True, slots=True)
class StageRecord:
    stage: str
    outcome: str
    reason: str
    detail: str

    def to_json(self) -> dict[str, str]:
        return {"stage": self.stage, "outcome": self.outcome, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ProbeReceipt:
    """One host and scope, bound to host version and source digest.

    The dataclass validates nothing itself; ``parse_receipt`` is the only
    validation, so construct receipts through it.
    """

    host: str
    scope: str
    os: str
    target_path: str
    adapter_schema_version: str
    transform: str
    source_digest: str
    catalog_revision: str
    host_version: str | None
    host_version_status: str
    version_command: tuple[str, ...]
    discovery_mechanism: str
    credential_required: bool
    probe_unsupported: str
    started_at: str
    ended_at: str
    cleanup: str
    stages: tuple[StageRecord, ...]

    def stage(self, name: str) -> StageRecord:
        for record in self.stages:
            if record.stage == name:
                return record
        raise DiscoveryEvidenceError(f"receipt missing stage: {name}")

    def highest_observed_stage(self) -> str | None:
        for record in reversed(self.stages):
            if record.outcome == "observed":
                return record.stage
        return None

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "host": self.host,
            "scope": self.scope,
            "os": self.os,
            "target_path": self.target_path,
            "adapter_schema_version": self.adapter_schema_version,
            "transform": self.transform,
            "source_digest": self.source_digest,
            "catalog_revision": self.catalog_revision,
            "host_version": self.host_version,
            "host_version_status": self.host_version_status,
            "version_command": list(self.version_command),
            "discovery_mechanism": self.discovery_mechanism,
            "credential_required": self.credential_required,
            "probe_unsupported": self.probe_unsupported,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "cleanup": self.cleanup,
            "stages": [record.to_json() for record in self.stages],
        }


def _parse_stages(value: object, *, discovery_mechanism: str) -> tuple[StageRecord, ...]:
    if not isinstance(value, list) or len(value) != len(STAGES):
        raise DiscoveryEvidenceError("a receipt records exactly the five stages")
    stages: list[StageRecord] = []
    for expected, item in zip(STAGES, value):
        if not isinstance(item, Mapping) or set(item) != STAGE_KEYS:
            raise DiscoveryEvidenceError("invalid stage record")
        if item["stage"] != expected:
            raise DiscoveryEvidenceError(f"stages out of order: expected {expected}, got {item['stage']!r}")
        stages.append(
            StageRecord(
                stage=expected,
                outcome=_member(item["outcome"], OUTCOMES, field=f"{expected} outcome"),
                reason=_text(item["reason"], field=f"{expected} reason"),
                detail=_text(item["detail"], field=f"{expected} detail"),
            )
        )
    installed = stages[0]
    if INSTALLED_REASONS.get(installed.reason) != installed.outcome:
        raise DiscoveryEvidenceError(f"installed reason {installed.reason!r} does not fit outcome {installed.outcome!r}")
    if discovery_mechanism == "none":
        for record in stages[1:]:
            if record.outcome != "not_observed":
                raise DiscoveryEvidenceError(f"{record.stage} cannot be {record.outcome} without a probe that observes it")
            if record.reason != LATER_STAGE_REASON:
                raise DiscoveryEvidenceError(f"{record.stage} reason must be {LATER_STAGE_REASON}")
    return tuple(stages)


def parse_receipt(payload: object) -> ProbeReceipt:
    """Fail-closed receipt parser: a receipt that fails any check below raises, never passes.

    It does not compare free-text ``detail`` or ``probe_unsupported`` with the
    disk or the descriptor table, so a hand-written receipt can still say
    something no run observed; only receipts this module builds are vouched for.
    """
    if not isinstance(payload, Mapping):
        raise DiscoveryEvidenceError("receipt must be an object")
    if set(payload) != RECEIPT_KEYS:
        raise DiscoveryEvidenceError(f"receipt fields differ: {sorted(set(payload) ^ RECEIPT_KEYS)}")
    if payload["schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise DiscoveryEvidenceError("wrong receipt schema")
    if payload["adapter_schema_version"] != ADAPTER_SCHEMA_VERSION:
        raise DiscoveryEvidenceError("wrong adapter schema")
    host = _member(payload["host"], HOSTS, field="host")
    status = _member(payload["host_version_status"], HOST_VERSION_STATUSES, field="host_version_status")
    if (status == "no_approved_probe") == (host in _version_probed()):
        raise DiscoveryEvidenceError(
            f"host_version_status {status} contradicts the approved version probe set for {host}"
        )
    version = payload["host_version"]
    if status == "observed":
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            raise DiscoveryEvidenceError("an observed host version must be a version token")
    elif version is not None:
        raise DiscoveryEvidenceError(f"host_version must be null when its status is {status}")
    command = payload["version_command"]
    expected_command = [] if status == "no_approved_probe" else [host, "--version"]
    if command != expected_command:
        raise DiscoveryEvidenceError(f"version_command must be {expected_command} when its status is {status}")
    if type(payload["credential_required"]) is not bool:
        raise DiscoveryEvidenceError("credential_required must be a bool")
    started = _stamp(payload["started_at"], field="started_at")
    ended = _stamp(payload["ended_at"], field="ended_at")
    if ended < started:
        raise DiscoveryEvidenceError("ended_at precedes started_at")
    mechanism = _member(payload["discovery_mechanism"], DISCOVERY_MECHANISMS, field="discovery_mechanism")
    return ProbeReceipt(
        host=host,
        scope=_member(payload["scope"], SCOPES, field="scope"),
        os=_member(payload["os"], OPERATING_SYSTEMS, field="os"),
        target_path=_relative_path(payload["target_path"], field="target_path"),
        adapter_schema_version=ADAPTER_SCHEMA_VERSION,
        transform=_member(payload["transform"], TRANSFORMS, field="transform"),
        source_digest=_digest(payload["source_digest"], field="source_digest"),
        catalog_revision=_digest(payload["catalog_revision"], field="catalog_revision"),
        host_version=version,
        host_version_status=status,
        version_command=tuple(command),
        discovery_mechanism=mechanism,
        credential_required=payload["credential_required"],
        probe_unsupported=_text(payload["probe_unsupported"], field="probe_unsupported"),
        started_at=payload["started_at"],
        ended_at=payload["ended_at"],
        cleanup=_member(payload["cleanup"], CLEANUP_RESULTS, field="cleanup"),
        stages=_parse_stages(payload["stages"], discovery_mechanism=mechanism),
    )


def _kind(path: Path) -> str:
    """``absent``, ``dir``, ``file`` or ``other``; any other ``OSError`` propagates.

    ``Path.is_dir`` and ``Path.is_file`` return False on any ``OSError`` on
    Python 3.14, which would report an unreadable path as an absent one;
    3.11 to 3.13 raise. Stat explicitly so every version behaves the same.
    """
    try:
        mode = path.stat().st_mode
    except (FileNotFoundError, NotADirectoryError):
        return "absent"
    if stat.S_ISDIR(mode):
        return "dir"
    return "file" if stat.S_ISREG(mode) else "other"


def _installed_stage(root: Path, target_path: str, expected: Mapping[str, str]) -> StageRecord:
    """Compare the scan path's bytes with the pack inventory; read-only.

    Files beside the pack, including ones a newer pack retired, are not
    checked: ``match`` means every pack file is present and byte-identical.
    """
    target = root.absolute().joinpath(*PurePosixPath(target_path).parts)
    total = len(expected)
    unreadable = StageRecord("installed", "hold", "unreadable", f"scan path unreadable at {target_path}")
    try:
        # The installers' own rule: no symlink anywhere from the scan path's
        # parent down to a file, since a symlink could point the host
        # elsewhere. Manifest paths are OMH's own, so the unsafe-path refusal
        # that shares this ValueError cannot fire here.
        paths = [(_checked_path(target, relative), digest) for relative, digest in sorted(expected.items())]
    except ValueError:
        return StageRecord(
            "installed",
            "hold",
            "symlink",
            f"symlink in the scan path at {target_path}; the installers refuse to write through one",
        )
    except OSError:
        return unreadable
    try:
        if _kind(target) != "dir":
            return StageRecord("installed", "not_observed", "absent", f"no scan directory at {target_path}")
        missing = differ = 0
        for path, digest in paths:
            if _kind(path) != "file":
                missing += 1
            elif sha256_file(path) != digest:
                differ += 1
    except OSError:
        return unreadable
    if missing == total:
        return StageRecord(
            "installed", "not_observed", "absent", f"none of the {total} pack files are present at {target_path}"
        )
    if missing or differ:
        return StageRecord(
            "installed",
            "hold",
            "partial" if missing else "modified",
            f"{total - missing - differ} of {total} pack files match at {target_path}; {missing} missing, {differ} differ",
        )
    return StageRecord(
        "installed", "observed", "match", f"all {total} pack files match the pack inventory at {target_path}"
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _os_name() -> str:
    # `sys.platform`, not `platform.system()`: on Windows with Python 3.11 the
    # latter shells out to `ver`.
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux" if sys.platform.startswith("linux") else "other"


InstalledRead = tuple[StageRecord, datetime, datetime]


def read_installed(
    root: Path, target_path: str, files: Mapping[str, str], clock: Callable[[], datetime] = _utc_now
) -> InstalledRead:
    """The ``installed`` stage under ``root`` against the pack inventory's ``files``.

    Returned with the window that bracketed the read.
    """
    started = clock().astimezone(timezone.utc)
    installed = _installed_stage(root, target_path, files)
    # A wall-clock step backwards between the two reads must not void the run.
    ended = max(clock().astimezone(timezone.utc), started)
    return installed, started, ended


def observe_receipt(
    descriptor: ProbeDescriptor,
    *,
    root: Path,
    adapter_manifest: Mapping[str, object],
    inventory: Mapping[str, object],
    host_version: tuple[str, str | None],
    clock: Callable[[], datetime] = _utc_now,
    read: InstalledRead | None = None,
) -> ProbeReceipt:
    """A parsed receipt for ``read``, or for a fresh read under ``root`` when none is given.

    Hosts that share a scan path pass the one read, so every receipt's window
    is the window that bracketed the read it reports.
    """
    if read is None:
        files = inventory["files"]
        if not isinstance(files, Mapping):
            raise DiscoveryEvidenceError("pack inventory has no file digests")
        read = read_installed(root, descriptor.target_path, files, clock)
    installed, started, ended = read
    status, version = host_version
    later = [
        StageRecord(stage, "not_observed", LATER_STAGE_REASON, "no OMH probe observes this stage")
        for stage in STAGES[1:]
    ]
    payload = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "host": descriptor.host,
        "scope": descriptor.scope,
        "os": _os_name(),
        "target_path": descriptor.target_path,
        "adapter_schema_version": adapter_manifest["schema_version"],
        "transform": adapter_manifest["transform"],
        "source_digest": inventory["source_digest"],
        "catalog_revision": inventory["catalog_revision"],
        "host_version": version,
        "host_version_status": status,
        "version_command": list(descriptor.version_command or ()),
        "discovery_mechanism": descriptor.discovery_mechanism,
        "credential_required": descriptor.credential_required,
        "probe_unsupported": descriptor.probe_unsupported,
        "started_at": started.strftime(_STAMP_FORMAT),
        "ended_at": ended.strftime(_STAMP_FORMAT),
        "cleanup": "nothing_created",
        "stages": [record.to_json() for record in (installed, *later)],
    }
    # Built through the parser: a receipt this producer cannot make valid
    # raises here instead of being emitted.
    return parse_receipt(payload)


@dataclass(frozen=True, slots=True)
class CurrentPack:
    """What a receipt must still match to be current: pack, scan path, OS, host version."""

    catalog_revision: str
    source_digests: Mapping[str, str]
    target_paths: Mapping[tuple[str, str], str]
    os: str
    host_versions: Mapping[str, str | None]


@dataclass(frozen=True, slots=True)
class MatrixRow:
    host: str
    scope: str
    evidence_class: str
    highest_observed_stage: str | None
    installed: str
    installed_reason: str
    installed_detail: str | None
    host_version: str | None
    host_version_status: str
    source_digest: str | None
    catalog_revision: str | None
    observed_at: str | None
    freshness: str
    probe_unsupported: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "host": self.host,
            "scope": self.scope,
            "evidence_class": self.evidence_class,
            "highest_observed_stage": self.highest_observed_stage,
            "installed": self.installed,
            "installed_reason": self.installed_reason,
            "installed_detail": self.installed_detail,
            "host_version": self.host_version,
            "host_version_status": self.host_version_status,
            "source_digest": self.source_digest,
            "catalog_revision": self.catalog_revision,
            "observed_at": self.observed_at,
            "freshness": self.freshness,
            "probe_unsupported": self.probe_unsupported,
        }


def _freshness(receipt: ProbeReceipt, current: CurrentPack) -> str:
    # OS is compared, but freshness does not identify the machine.
    if (
        receipt.source_digest != current.source_digests[receipt.host]
        or receipt.catalog_revision != current.catalog_revision
        or receipt.target_path != current.target_paths[(receipt.host, receipt.scope)]
        or receipt.os != current.os
    ):
        return "stale"
    now = current.host_versions.get(receipt.host)
    if receipt.host_version is None or now is None:
        return "version_unverified"
    return "current" if receipt.host_version == now else "stale"


def _evidence_class(receipt: ProbeReceipt) -> str:
    if any(record.outcome == "hold" for record in receipt.stages):
        return "hold"
    highest = receipt.highest_observed_stage()
    return f"observed_through_{highest}" if highest else "not_observed"


def summarize_receipts(
    receipts: Iterable[ProbeReceipt], *, current: CurrentPack, scopes: Iterable[str] = SCOPES
) -> tuple[MatrixRow, ...]:
    """One row per host and scope, sorted; a host and scope without a receipt is an explicit row."""
    wanted = tuple(sorted({_member(scope, SCOPES, field="scope") for scope in scopes}))
    indexed: dict[tuple[str, str], ProbeReceipt] = {}
    for receipt in receipts:
        key = (receipt.host, receipt.scope)
        if key in indexed:
            raise DiscoveryEvidenceError(f"duplicate receipt for {receipt.host} {receipt.scope}")
        indexed[key] = receipt
    rows: list[MatrixRow] = []
    for host in HOSTS:
        for scope in wanted:
            receipt = indexed.get((host, scope))
            if receipt is None:
                rows.append(
                    MatrixRow(
                        host=host,
                        scope=scope,
                        evidence_class="no_receipt",
                        highest_observed_stage=None,
                        installed="no_receipt",
                        installed_reason="no_receipt",
                        installed_detail=None,
                        host_version=None,
                        host_version_status="no_receipt",
                        source_digest=None,
                        catalog_revision=None,
                        observed_at=None,
                        freshness="no_receipt",
                        probe_unsupported=None,
                    )
                )
                continue
            installed = receipt.stage("installed")
            rows.append(
                MatrixRow(
                    host=host,
                    scope=scope,
                    evidence_class=_evidence_class(receipt),
                    highest_observed_stage=receipt.highest_observed_stage(),
                    installed=installed.outcome,
                    installed_reason=installed.reason,
                    installed_detail=installed.detail,
                    host_version=receipt.host_version,
                    host_version_status=receipt.host_version_status,
                    source_digest=receipt.source_digest,
                    catalog_revision=receipt.catalog_revision,
                    observed_at=receipt.started_at,
                    freshness=_freshness(receipt, current),
                    probe_unsupported=receipt.probe_unsupported,
                )
            )
    return tuple(rows)


def load_evidence_receipts(path: Path) -> tuple[ProbeReceipt, ...]:
    """Receipts from an earlier ``--json`` payload; one malformed entry fails the load.

    Read as bytes, so ``json`` detects UTF-8 (with or without a BOM), UTF-16,
    or UTF-32, whichever encoding the shell redirect wrote.
    """
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, Mapping) or payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise DiscoveryEvidenceError(f"{path.name} is not an {EVIDENCE_SCHEMA_VERSION} payload")
    receipts = payload.get("receipts")
    if not isinstance(receipts, list):
        raise DiscoveryEvidenceError(f"{path.name} has no receipts list")
    return tuple(parse_receipt(item) for item in receipts)


def build_agent_skills_evidence(
    *,
    project_root: Path | None = None,
    user_home: Path | None = None,
    scopes: Iterable[str] = SCOPES,
    stored_receipts: Iterable[ProbeReceipt] | None = None,
    version_probe: Callable[[str], tuple[str, str | None]] | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> dict[str, object]:
    """The host evidence matrix, observed now or read from stored receipts.

    Without ``stored_receipts`` it observes ``installed`` for every host in
    each scope (repo under ``project_root``, user under ``user_home``; both
    required). With them it reads no scan path and reports how each stored
    receipt compares with the current pack and the host version observed now.
    """
    wanted = tuple(sorted({_member(scope, SCOPES, field="scope") for scope in scopes}))
    observing = stored_receipts is None
    if observing:
        if project_root is None or user_home is None:
            raise DiscoveryEvidenceError("observing scan paths needs both a project root and a user home")
        # A mistyped root would otherwise report every pack as absent.
        for label, root in (("project root", project_root), ("user home", user_home)):
            if _kind(root) != "dir":
                raise DiscoveryEvidenceError(f"{label} is not a directory: {root}")
    if version_probe is None:
        from ..coding.executor_readiness import agent_cli_version

        version_probe = agent_cli_version
    files = agent_skill_files()
    # One inventory per pack: the five `.agents` hosts copy the portable pack,
    # Claude Code its own copy (`host_pack_files`), so the digest a receipt
    # binds is its host's pack's. `catalog_revision` stays the portable
    # pack's, the one catalog both copies are generated from.
    receipt = agent_skills_manifest(files)
    catalog_revision = receipt["catalog_revision"]
    host_files = {host: agent_skills_manifest(host_pack_files(host, files))["files"] for host in HOSTS}
    inventories = {
        host: {**receipt, "files": host_files[host], "source_digest": pack_source_digest(host_files[host])}
        for host in HOSTS
    }
    manifests = {host: host_adapter_manifest(host, files) for host in HOSTS}
    all_descriptors = probe_descriptors()
    probed = {descriptor.host for descriptor in all_descriptors if descriptor.version_command}
    versions = {host: version_probe(host) if host in probed else ("no_approved_probe", None) for host in HOSTS}
    descriptors = tuple(descriptor for descriptor in all_descriptors if descriptor.scope in wanted)
    current = CurrentPack(
        catalog_revision=catalog_revision,
        source_digests={host: inventories[host]["source_digest"] for host in HOSTS},
        target_paths={(descriptor.host, descriptor.scope): descriptor.target_path for descriptor in descriptors},
        os=_os_name(),
        host_versions={host: version for host, (_status, version) in versions.items()},
    )
    if observing:
        # Hosts that share a scan path read the same pack bytes once, and
        # every receipt for that path carries that read's window.
        reads: dict[tuple[str, str], InstalledRead] = {}
        receipts_list = []
        for descriptor in descriptors:
            root = project_root if descriptor.scope == "repo" else user_home
            key = (descriptor.scope, descriptor.target_path, inventories[descriptor.host]["source_digest"])
            if key not in reads:
                reads[key] = read_installed(root, descriptor.target_path, host_files[descriptor.host], clock)
            receipts_list.append(
                observe_receipt(
                    descriptor,
                    root=root,
                    adapter_manifest=manifests[descriptor.host],
                    inventory=inventories[descriptor.host],
                    host_version=versions[descriptor.host],
                    read=reads[key],
                )
            )
        receipts = tuple(receipts_list)
    else:
        receipts = tuple(receipt for receipt in stored_receipts if receipt.scope in wanted)
    matrix = summarize_receipts(receipts, current=current, scopes=wanted)
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "receipt_source": "observed" if observing else "stored",
        "scopes": list(wanted),
        "current": {
            "catalog_revision": catalog_revision,
            "os": current.os,
            "hosts": {
                host: {
                    "source_digest": inventories[host]["source_digest"],
                    "host_version": versions[host][1],
                    "host_version_status": versions[host][0],
                }
                for host in HOSTS
            },
        },
        # Scan paths this run could not read; empty with stored receipts,
        # whose reads happened in the run that recorded them.
        "unread_scan_paths": [
            {"host": row.host, "scope": row.scope}
            for row in matrix
            if observing and row.installed_reason == "unreadable"
        ],
        "receipts": [receipt.to_json() for receipt in receipts],
        "matrix": [row.to_json() for row in matrix],
        "claim_boundary": OBSERVED_CLAIM_BOUNDARY if observing else STORED_CLAIM_BOUNDARY,
    }


def format_agent_skills_evidence(payload: Mapping[str, object]) -> str:
    """Plain-text matrix: one line per host and scope, then the boundary."""
    current = payload["current"]
    revision = current["catalog_revision"] if isinstance(current, Mapping) else ""
    lines = [
        f"Agent Skills host evidence ({payload['receipt_source']} receipts), pack catalog revision {str(revision)[:12]}",
    ]
    for row in payload["matrix"]:
        version = row["host_version"] or f"not observed ({row['host_version_status']})"
        lines.append(
            f"  {row['host']:<9} {row['scope']:<5} {row['evidence_class']:<26} "
            f"host version {version}; freshness {row['freshness']}"
        )
        lines.append(f"  {'':<15} installed: {row['installed_detail'] or 'no receipt for this host and scope'}")
    lines.append(
        "Discovered, nominated, loaded, executed: not observed for every host (probe_unsupported); "
        "--json carries each host's reason."
    )
    lines.append(f"Boundary: {payload['claim_boundary']}")
    return "\n".join(lines)
