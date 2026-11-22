"""Process-attributed native session references, never continuation authority.

The shared bounded binary intake calls observe() with individual decoded frames.
The dispatcher supplies capability probes bound to the resolved binary, immutable
attempt lineage, and freshly observed workspace/recovery state. Decoding and
projection are pure; explicit local probe helpers observe bounded metadata only.
No helper scans native session stores or launches continuation.
An observed ID proves neither successful work nor durable native session storage.

A user-declared executor does not print a native event stream. When its entry
declares a `session.export` fragment, the CLI writes one bounded JSON file into
this attempt's dispatcher-owned scratch directory and the dispatcher records
`fanout_executor_session/v2` (`user_export_json`): the expected filename, the
SHA-256 of the bytes it read, and the root `session_id` only when that is a
canonical id. The transcript body is never read into a record and is never
stored under `.omh`. v2 is evidence for a budgeted same-session repair, not a
status-time continuation: no status read launches anything.
"""
from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from typing import Final
from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from hashlib import sha256
import stat
import signal
import subprocess
from uuid import NAMESPACE_URL, uuid5
import re
import shlex

from ._hermes_child_process import MAX_CAPTURE_BYTES
from typing import TYPE_CHECKING, Literal, TypeGuard, TypedDict

if TYPE_CHECKING:
    from .fanout_confinement import FanoutFilesystemConfinement

SCHEMA_VERSION = 'fanout_executor_session/v1'
# v2 is the file-export dialect. It is a separate closed schema, branched in
# the reader and the serializer, so a v1 receipt keeps its exact bytes.
FILE_EXPORT_SCHEMA_VERSION = 'fanout_executor_session/v2'
FILE_EXPORT_PROTOCOL = 'user_export_json'
# The one basename the dispatcher assigns inside the attempt's scratch dir.
# A receipt records the basename, never the absolute path or the body.
FILE_EXPORT_REF = 'session.json'
MAX_EXPORT_BYTES = 1024 * 1024
MAX_EXPORT_DEPTH = 32
MAX_EVENTS = 65536
_PROTOCOLS = {'codex': 'codex_exec_json', 'claude-code': 'claude_stream_json'}
_UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
_SHA = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})')
_DIGEST = re.compile(r'[0-9a-f]{64}')
_TOKEN = re.compile(r'[A-Za-z0-9_.:/-]{1,256}')
# A file export may name a root `session_id`. Only these two shapes are ids;
# anything else is a malformed export, not a reference to resume from.
_EXPORT_ID = re.compile(r'(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|devin-[0-9a-f]{32})')
_EXPORT_REF = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
# Closed reasons for a v2 receipt. `export_digest_observed` is the only
# observed reason; the rest name why no digest became evidence.
FILE_EXPORT_FAILURE_REASONS: Final[frozenset[str]] = frozenset({
    'export_missing', 'export_unsafe', 'export_unreadable', 'export_not_object',
    'export_duplicate_keys', 'export_oversized', 'export_invalid_utf8',
    'export_invalid_json', 'export_too_deep', 'export_changing', 'export_invalid_id',
})
FILE_EXPORT_OBSERVED_REASON: Final[str] = 'export_digest_observed'
# Why a v2 receipt does or does not carry a resumable id. Recorded on every
# v2 receipt: a repair that started fresh says which check it failed.
FILE_EXPORT_RESUME_REASONS: Final[frozenset[str]] = frozenset({
    'not_a_repair', 'no_resume_declared', 'no_prior_receipt', 'not_user_export',
    'binding_changed', 'no_id', 'duplicate_reference', 'end_revision_not_observed',
    'stale_workspace', 'recovery_snapshot_mismatch', 'binary_changed',
    'same_session', 'fresh_retry',
})
State = Literal['observed', 'not_observed', 'not_available']


@dataclass(frozen=True, slots=True)
class BinaryIdentity:
    resolved_path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SessionCapability:
    """Supplied supported-help/version observation, not a version-floor guess."""
    executor: str
    protocol: str | None
    binary_identity: BinaryIdentity
    version: str | None
    # Why there is no protocol, when there is none. An absent protocol turns
    # off the structured-session lane -- no token counts, no session id to
    # steer with -- and before this field the only trace of that was an empty
    # column on the HUD, which reads like a unit that spent no tokens rather
    # than like a capability that was never negotiated. Empty when a protocol
    # was negotiated, or when the owner has no protocol to negotiate.
    reason: str = ""


@dataclass(frozen=True, slots=True)
class WorktreeIncarnation:
    incarnation_id: str
    common_dir: str
    branch: str
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class SessionBinding:
    fanout_id: str
    unit_id: str
    run_ref: str
    attempt_id: str
    contract_digest: str
    worktree_path: str
    worktree_incarnation: WorktreeIncarnation
    base_sha: str
    launch_head: str
    predecessor_attempt_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    """Fresh dispatcher observation; recovery digest includes dirty/untracked state."""
    path: str
    incarnation: WorktreeIncarnation
    head: str
    dirty: bool
    recovery_snapshot: str | None


@dataclass(frozen=True, slots=True)
class SessionReceipt:
    state: State
    reason: str
    capability: SessionCapability
    binding: SessionBinding
    reference: str | None
    event_ref: str | None
    end_head: str | None
    # v2 file-export fields. All three keep their defaults on a native receipt,
    # and `to_dict` emits them only in the v2 branch, so v1 bytes are unchanged.
    export_ref: str | None = None
    export_sha256: str | None = None
    resume_reason: str = ''

    @property
    def reference_kind(self) -> str | None:
        """The kind of reference this receipt actually observed, or None."""
        if self.state != 'observed':
            return None
        if self.capability.protocol == FILE_EXPORT_PROTOCOL:
            # A file with no canonical id is still a file observation; it just
            # cannot be resumed from.
            return 'session_id' if self.reference is not None else 'export_file'
        return _reference_kind(self.capability)

    def to_dict(self) -> dict[str, object]:
        binding, capability = self.binding, self.capability
        incarnation = binding.worktree_incarnation
        record: dict[str, object] = {
            'schema_version': SCHEMA_VERSION, 'state': self.state, 'reason': self.reason,
            'executor': capability.executor, 'protocol': capability.protocol,
            'reference_kind': self.reference_kind,
            'reference': self.reference, 'event_ref': self.event_ref,
            'fanout_id': binding.fanout_id, 'unit_id': binding.unit_id, 'run_ref': binding.run_ref,
            'attempt_id': binding.attempt_id, 'contract_digest': binding.contract_digest,
            'worktree_path': binding.worktree_path,
            'worktree_incarnation': {
                'incarnation_id': incarnation.incarnation_id, 'common_dir': incarnation.common_dir,
                'branch': incarnation.branch, 'device': incarnation.device, 'inode': incarnation.inode},
            'base_sha': binding.base_sha, 'launch_head': binding.launch_head, 'end_head': self.end_head,
            'binary_identity': {'resolved_path': capability.binary_identity.resolved_path,
                                'sha256': capability.binary_identity.sha256},
            'version': capability.version, 'predecessor_attempt_id': binding.predecessor_attempt_id,
        }
        if capability.protocol == FILE_EXPORT_PROTOCOL:
            record['schema_version'] = FILE_EXPORT_SCHEMA_VERSION
            # No decoded frame identity in a file export; the digest and the id
            # are the whole observation.
            record.pop('event_ref')
            record['export_ref'] = self.export_ref
            record['export_sha256'] = self.export_sha256
            record['resume_reason'] = self.resume_reason
        return record


@dataclass(frozen=True, slots=True)
class SessionRead:
    receipt: SessionReceipt | None
    reason: str


class ResumeProjection(TypedDict):
    available: bool
    reason: str
    argv: list[str]
    cwd: str | None
    shell_command: str | None
    execution_policy: Literal['copy_only']
    required_input: Literal['follow_up_prompt_on_stdin'] | None
    native_resume_state: Literal['not_tested']


def _supported(capability: SessionCapability) -> bool:
    return (capability.executor in _PROTOCOLS and
            capability.protocol == _PROTOCOLS[capability.executor] and capability.version is not None)


def _reference_kind(capability: SessionCapability) -> str:
    return 'thread_id' if capability.executor == 'codex' else 'session_id'


class SessionDecoder:
    """One decoder per fresh attempt; retains only a UUID and first event reference.

    Malformed candidate IDs, conflicts or excess events poison the whole attempt.
    Unrelated/nested/subagent frames never contribute identity. Wire/frame/depth
    budgets belong to the shared ingestion pipeline, not another parser here.
    """
    __slots__: tuple[str, ...] = ('capability', 'event_count', '_reference', '_event_ref', '_reason')

    def __init__(self, capability: SessionCapability) -> None:
        self.capability: SessionCapability = capability
        self.event_count: int = 0
        self._reference: str | None = None
        self._event_ref: str | None = None
        self._reason: str = 'event_missing' if _supported(capability) else 'unsupported_protocol'

    def observe(self, event: Mapping[str, object], *, event_ref: str) -> None:
        if self.event_count == MAX_EVENTS:
            if _supported(self.capability):
                self._invalidate('event_limit')
            return
        self.event_count += 1
        if self._reason not in ('event_missing', 'native_event_observed'):
            return
        if event.get('parent_tool_use_id') is not None:
            return
        if self.capability.executor == 'codex':
            if event.get('type') != 'thread.started':
                return
            reference = event.get('thread_id')
        else:
            if not (event.get('type') == 'result' or
                    (event.get('type') == 'system' and event.get('subtype') == 'init')):
                return
            reference = event.get('session_id')
        if not isinstance(reference, str) or not _UUID.fullmatch(reference):
            self._invalidate('invalid_reference')
        elif not _TOKEN.fullmatch(event_ref):
            self._invalidate('invalid_event_ref')
        elif self._reference is not None and reference != self._reference:
            self._invalidate('conflicting_reference')
        elif self._reference is None:
            self._reference, self._event_ref = reference, event_ref
            self._reason = 'native_event_observed'

    def _invalidate(self, reason: str) -> None:
        self._reference, self._event_ref, self._reason = None, None, reason

    def invalidate_capture(self) -> None:
        """A missing/partial native frame cannot leave a reusable earlier ID."""
        if _supported(self.capability):
            self._invalidate('incomplete_capture')

    def receipt(self, binding: SessionBinding, *, end_head: str | None = None) -> SessionReceipt:
        state: State = ('not_available' if not _supported(self.capability) else
                        'observed' if self._reference is not None else 'not_observed')
        receipt = SessionReceipt(state, self._reason, self.capability, binding,
                                 self._reference, self._event_ref, end_head)
        if read_session_receipt(receipt.to_dict()).receipt is None:
            raise ValueError('invalid_dispatcher_session_binding')
        return receipt


@dataclass(frozen=True, slots=True)
class SessionExportObservation:
    """What one bounded read of an executor's export file established.

    `reference` is the root `session_id` only when it is a canonical id. A
    valid file with no id is still an observation: `export_sha256` says which
    bytes were seen, `reference` stays None, and nothing can be resumed from it.
    """

    state: State
    reason: str
    export_ref: str
    export_sha256: str | None
    reference: str | None


class _DuplicateExportKey(ValueError):
    """A JSON object repeated a key; the export is ambiguous, not just wrong."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateExportKey(key)
        result[key] = value
    return result


def _exceeds_depth(document: str) -> bool:
    """Bound nesting before the parser allocates: a deep file is not evidence."""
    depth = 0
    in_string = False
    escaped = False
    for character in document:
        if in_string:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in '{[':
            depth += 1
            if depth > MAX_EXPORT_DEPTH:
                return True
        elif character in '}]':
            depth -= 1
    return False


def observe_session_export(path: Path, *, export_ref: str = FILE_EXPORT_REF,
                           scratch_fd: int | None = None) -> SessionExportObservation:
    """Digest one attempt's export file; never decode its transcript body.

    Only a regular, single-link, size-stable file no larger than 1 MiB, opened
    without following a link and read through that same descriptor, is
    observed. Anything else returns `not_observed` with a closed reason and no
    hash: a substituted, oversized or still-changing path is not a session.
    """
    def failed(reason: str) -> SessionExportObservation:
        return SessionExportObservation('not_observed', reason, export_ref, None, None)

    no_follow = getattr(os, 'O_NOFOLLOW', 0)
    if not no_follow or not getattr(os, 'O_DIRECTORY', 0) or os.open not in os.supports_dir_fd:
        return failed('export_unsafe')
    try:
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | no_follow)
        try:
            if scratch_fd is not None and not os.path.samestat(os.fstat(scratch_fd), os.fstat(directory)):
                return failed('export_unsafe')
            descriptor = os.open(path.name, os.O_RDONLY | no_follow | getattr(os, 'O_NONBLOCK', 0),
                                 dir_fd=directory)
        finally:
            os.close(directory)
    except FileNotFoundError:
        return failed('export_missing')
    except OSError as exc:
        return failed('export_unsafe' if exc.errno in (errno.ELOOP, errno.ENOTDIR) else 'export_unreadable')
    try:
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                return failed('export_unsafe')
            if before.st_size > MAX_EXPORT_BYTES:
                return failed('export_oversized')
            data = stream.read(MAX_EXPORT_BYTES + 1)
            after = os.fstat(stream.fileno())
            if len(data) > MAX_EXPORT_BYTES:
                return failed('export_oversized')
            if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                    before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns):
                return failed('export_changing')
            if len(data) != before.st_size:
                return failed('export_changing')
    except OSError:
        return failed('export_unreadable')
    try:
        document = data.decode('utf-8')
    except UnicodeDecodeError:
        return failed('export_invalid_utf8')
    if _exceeds_depth(document):
        return failed('export_too_deep')
    try:
        parsed = json.loads(document, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateExportKey:
        return failed('export_duplicate_keys')
    except ValueError:
        return failed('export_invalid_json')
    if not isinstance(parsed, dict):
        return failed('export_not_object')
    digest = sha256(data).hexdigest()
    reference = parsed.get('session_id')
    if reference is None:
        return SessionExportObservation('observed', FILE_EXPORT_OBSERVED_REASON, export_ref, digest, None)
    if not isinstance(reference, str) or not _EXPORT_ID.fullmatch(reference):
        # An unparseable or non-canonical id invalidates the whole file: a
        # clipped id is not a session someone can resume, and guessing is worse.
        return failed('export_invalid_id')
    return SessionExportObservation('observed', FILE_EXPORT_OBSERVED_REASON, export_ref, digest, reference)


def build_file_export_receipt(
    *, capability: SessionCapability, binding: SessionBinding,
    observation: SessionExportObservation, end_head: str | None, resume_reason: str,
) -> SessionReceipt:
    """The v2 receipt for one attempt, bound to this attempt's lineage.

    Raises ValueError when the record would not read back; the caller only
    supplies dispatcher-owned values, so that is a programming error, not
    something an executor can trigger.
    """
    if capability.protocol != FILE_EXPORT_PROTOCOL:
        raise ValueError('not_a_file_export_capability')
    if resume_reason not in FILE_EXPORT_RESUME_REASONS:
        raise ValueError('invalid_resume_reason')
    if not _EXPORT_REF.fullmatch(observation.export_ref):
        raise ValueError('invalid_export_ref')
    receipt = SessionReceipt(
        observation.state, observation.reason, capability, binding, observation.reference,
        None, end_head, observation.export_ref, observation.export_sha256, resume_reason)
    if read_session_receipt(receipt.to_dict()).receipt is None:
        raise ValueError('invalid_dispatcher_session_binding')
    return receipt


def _text(value: object, *, limit: int = 256) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= limit or not value.isprintable():
        raise ValueError('invalid_text')
    return value


def _match(value: object, pattern: re.Pattern[str]) -> str:
    text = _text(value)
    if not pattern.fullmatch(text):
        raise ValueError('invalid_shape')
    return text


def _optional_match(value: object, pattern: re.Pattern[str]) -> str | None:
    return None if value is None else _match(value, pattern)


def _path(value: object) -> str:
    text = _text(value, limit=4096)
    if not (PurePosixPath(text).is_absolute() or PureWindowsPath(text).is_absolute()):
        raise ValueError('path_not_absolute')
    return text


def _integer(value: object) -> int:
    if type(value) is not int or value < 0 or value > 2**64 - 1:
        raise ValueError('invalid_filesystem_identity')
    return value


def _is_mapping(value: object) -> TypeGuard[Mapping[object, object]]:
    return isinstance(value, Mapping)


def _object(value: object, keys: Collection[str]) -> Mapping[str, object]:
    if not _is_mapping(value) or len(value) != len(keys) or not all(key in value for key in keys):
        raise ValueError('invalid_fields')
    return {key: value[key] for key in keys}


_FIELDS = (
    'schema_version', 'state', 'reason', 'executor', 'protocol', 'reference_kind', 'reference',
    'event_ref', 'fanout_id', 'unit_id', 'run_ref', 'attempt_id', 'contract_digest',
    'worktree_path', 'worktree_incarnation', 'base_sha', 'launch_head', 'end_head',
    'binary_identity', 'version', 'predecessor_attempt_id',
)


_FILE_EXPORT_FIELDS = (
    'schema_version', 'state', 'reason', 'executor', 'protocol', 'reference_kind', 'reference',
    'fanout_id', 'unit_id', 'run_ref', 'attempt_id', 'contract_digest',
    'worktree_path', 'worktree_incarnation', 'base_sha', 'launch_head', 'end_head',
    'binary_identity', 'version', 'predecessor_attempt_id',
    'export_ref', 'export_sha256', 'resume_reason',
)


def _read_file_export_receipt(value: Mapping[object, object]) -> SessionRead:
    """Validate one v2 file-export record; same lineage fields, plus the file."""
    try:
        record = _object(value, _FILE_EXPORT_FIELDS)
        binary = _object(record['binary_identity'], ('resolved_path', 'sha256'))
        capability = SessionCapability(
            _match(record['executor'], _TOKEN), _match(record['protocol'], _TOKEN),
            BinaryIdentity(_path(binary['resolved_path']), _match(binary['sha256'], _DIGEST)),
            None if record['version'] is None else _text(record['version']))
        if capability.protocol != FILE_EXPORT_PROTOCOL:
            raise ValueError('invalid_protocol')
        incarnation = _object(record['worktree_incarnation'],
                              ('incarnation_id', 'common_dir', 'branch', 'device', 'inode'))
        binding = SessionBinding(
            _match(record['fanout_id'], _TOKEN), _match(record['unit_id'], _TOKEN),
            _match(record['run_ref'], _TOKEN), _match(record['attempt_id'], _UUID),
            _match(record['contract_digest'], _DIGEST), _path(record['worktree_path']),
            WorktreeIncarnation(_match(incarnation['incarnation_id'], _UUID),
                                _path(incarnation['common_dir']), _text(incarnation['branch']),
                                _integer(incarnation['device']), _integer(incarnation['inode'])),
            _match(record['base_sha'], _SHA), _match(record['launch_head'], _SHA),
            _optional_match(record['predecessor_attempt_id'], _UUID))
        if binding.predecessor_attempt_id == binding.attempt_id:
            raise ValueError('self_predecessor')
        end_head = _optional_match(record['end_head'], _SHA)
        export_ref = _match(record['export_ref'], _EXPORT_REF)
        export_sha256 = _optional_match(record['export_sha256'], _DIGEST)
        resume_reason = _text(record['resume_reason'])
        if resume_reason not in FILE_EXPORT_RESUME_REASONS:
            raise ValueError('invalid_resume_reason')
        # Only the two canonical id shapes are references; the reader never
        # scans nested fields or transcript text for one.
        reference = _optional_match(record['reference'], _EXPORT_ID)
        reason = _text(record['reason'])
        state: State
        if record['state'] == 'observed':
            state = 'observed'
            expected_kind = 'session_id' if reference is not None else 'export_file'
            if (export_sha256 is None or record['reference_kind'] != expected_kind
                    or reason != FILE_EXPORT_OBSERVED_REASON):
                raise ValueError('invalid_observation')
        elif record['state'] == 'not_observed':
            state = 'not_observed'
            if (reference is not None or export_sha256 is not None
                    or record['reference_kind'] is not None or reason not in FILE_EXPORT_FAILURE_REASONS):
                raise ValueError('invalid_not_observed')
        else:
            raise ValueError('invalid_state')
        return SessionRead(SessionReceipt(state, reason, capability, binding, reference,
                                          None, end_head, export_ref, export_sha256, resume_reason),
                           reason)
    except ValueError:
        # Malformed optional metadata disables this capability, not the unit result.
        return SessionRead(None, 'invalid_receipt')


def read_session_receipt(value: object) -> SessionRead:
    """Validate one optional decoded record without altering old result evidence.

    Closed fixed-depth fields bound retained data; the caller bounds JSON reads.
    Missing legacy or unknown-version records never synthesize an observation.
    The v1 native decoder is untouched; a v2 record takes its own branch.
    """
    if value is None:
        return SessionRead(None, 'legacy_missing')
    if not _is_mapping(value):
        return SessionRead(None, 'invalid_receipt')
    version = value.get('schema_version')
    if version == FILE_EXPORT_SCHEMA_VERSION:
        return _read_file_export_receipt(value)
    if version != SCHEMA_VERSION:
        return SessionRead(None, 'unknown_schema')
    try:
        record = _object(value, _FIELDS)
        binary = _object(record['binary_identity'], ('resolved_path', 'sha256'))
        capability = SessionCapability(
            _match(record['executor'], _TOKEN),
            None if record['protocol'] is None else _match(record['protocol'], _TOKEN),
            BinaryIdentity(_path(binary['resolved_path']), _match(binary['sha256'], _DIGEST)),
            None if record['version'] is None else _text(record['version']))
        incarnation = _object(record['worktree_incarnation'],
                              ('incarnation_id', 'common_dir', 'branch', 'device', 'inode'))
        binding = SessionBinding(
            _match(record['fanout_id'], _TOKEN), _match(record['unit_id'], _TOKEN),
            _match(record['run_ref'], _TOKEN), _match(record['attempt_id'], _UUID),
            _match(record['contract_digest'], _DIGEST), _path(record['worktree_path']),
            WorktreeIncarnation(_match(incarnation['incarnation_id'], _UUID),
                                _path(incarnation['common_dir']), _text(incarnation['branch']),
                                _integer(incarnation['device']), _integer(incarnation['inode'])),
            _match(record['base_sha'], _SHA), _match(record['launch_head'], _SHA),
            _optional_match(record['predecessor_attempt_id'], _UUID))
        if binding.predecessor_attempt_id == binding.attempt_id:
            raise ValueError('self_predecessor')
        end_head = _optional_match(record['end_head'], _SHA)
        reference = _optional_match(record['reference'], _UUID)
        event_ref = _optional_match(record['event_ref'], _TOKEN)
        reason = _text(record['reason'])
        state: State
        if record['state'] == 'observed':
            state = 'observed'
            if (not _supported(capability) or reference is None or event_ref is None or
                    capability.version is None or reason != 'native_event_observed' or
                    record['reference_kind'] != _reference_kind(capability)):
                raise ValueError('invalid_observation')
        else:
            if reference is not None or event_ref is not None or record['reference_kind'] is not None:
                raise ValueError('unobserved_reference')
            if record['state'] == 'not_available':
                state = 'not_available'
                if _supported(capability) or reason != 'unsupported_protocol':
                    raise ValueError('invalid_unavailable')
            elif record['state'] == 'not_observed':
                state = 'not_observed'
                if not _supported(capability) or reason not in (
                    'event_missing', 'invalid_reference', 'conflicting_reference',
                    'event_limit', 'invalid_event_ref', 'incomplete_capture',
                ):
                    raise ValueError('invalid_not_observed')
            else:
                raise ValueError('invalid_state')
        return SessionRead(SessionReceipt(state, reason, capability, binding,
                                          reference, event_ref, end_head), reason)
    except ValueError:
        # Malformed optional metadata disables this capability, not the unit result.
        return SessionRead(None, 'invalid_receipt')


def bound_session_fields(record: Mapping[str, object], *, fanout_id: str,
                         unit_id: str, run_ref: str) -> dict[str, object]:
    """Admit an optional receipt against outer dispatcher identity, never itself."""
    receipt = read_session_receipt(record.get('executor_session')).receipt
    if receipt is None:
        return {}
    binding = receipt.binding
    if (binding.fanout_id != fanout_id or binding.unit_id != unit_id or binding.run_ref != run_ref
            or record.get('attempt_id') != binding.attempt_id
            or record.get('owner', record.get('runtime_profile')) != receipt.capability.executor):
        return {}
    for key, expected in (('unit_id', unit_id), ('worker_ref', unit_id), ('run_ref', run_ref),
                          ('run_id', run_ref), ('target_id', run_ref), ('fanout_id', fanout_id),
                          ('worktree_path', binding.worktree_path), ('worktree_ref', binding.worktree_path),
                          ('contract_digest', binding.contract_digest), ('base_sha', binding.base_sha)):
        if key in record and record[key] != expected:
            return {}
    result: dict[str, object] = {'executor_session': receipt.to_dict()}
    recovery = record.get('session_recovery_snapshot')
    if isinstance(recovery, str) and _DIGEST.fullmatch(recovery):
        result['session_recovery_snapshot'] = recovery
    return result


# A CLI's `--help` is a document, not a value, and it grows with the CLI. The
# shared 16 KiB cap is right for a probe whose answer is a version string and
# wrong for one whose answer is "does this word appear anywhere in the help":
# a help page that outgrows the cap reads as an unanswerable probe, and the
# whole structured-session lane switches off without anything saying so.
# Observed 2026-09-11: `claude --help` was 21,401 bytes with `--verbose` at
# byte 17,991, so the negotiation refused a protocol the CLI does support.
SESSION_HELP_PROBE_BYTES: Final[int] = 262_144


def bounded_session_probe(argv: list[str], *, cwd: str | None = None,
                          env: Mapping[str, str] | None = None,
                          limit_bytes: int = MAX_CAPTURE_BYTES,
                          keep_partial: bool = False) -> tuple[bytes | None, str]:
    """Read at most `limit_bytes` per pipe; a failed/partial probe authorizes nothing.

    `keep_partial` hands back the bytes that WERE read alongside the
    `probe_output_limited` reason, for the one caller whose question can be
    answered positively from a prefix: finding a flag in the part that was read
    is a complete observation, and only NOT finding one is ambiguous when the
    rest was cut off. Every other caller keeps the original contract, where a
    truncated read authorizes nothing.
    """
    from ._hermes_child_process import start_pipe_drainers, terminate_process_group

    try:
        process = subprocess.Popen(argv, cwd=cwd, env=dict(env) if env is not None else None,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=os.name != 'nt')
    except OSError:
        return None, 'probe_launch_failed'
    with process:
        drainers = start_pipe_drainers(process, limit_bytes=limit_bytes)
        reason = 'observed'
        try:
            if process.wait(timeout=3) != 0:
                reason = 'probe_nonzero'
        except subprocess.TimeoutExpired:
            reason = 'probe_timeout'
        finally:
            _ = terminate_process_group(process, 0.2, signal.SIGTERM)
            for drainer in drainers:
                drainer.thread.join(timeout=1)
                if drainer.thread.is_alive():
                    drainer.close()
                    drainer.thread.join(timeout=1)
                    if drainer.thread.is_alive():
                        raise RuntimeError('session_probe_reader_not_reaped')
        captures = [drainer.capture() for drainer in drainers]
        if any(capture.truncated for capture in captures):
            reason = 'probe_output_limited'
        if reason == 'observed':
            return captures[0].data, reason
        if keep_partial and reason == 'probe_output_limited':
            return captures[0].data, reason
        return None, reason


def observe_session_workspace(
    path: str, *, confinement: FanoutFilesystemConfinement | None = None,
) -> WorkspaceSnapshot | None:
    """Read-only current Git/filesystem identity and bounded dirty-state digest.

    No git add, checkout, native-history lookup, marker writes or inherited receipt
    identity. Large/unreadable recovery state disables copy rather than guessing.

    `confinement` is the unit's enforced write fence when the caller holds one.
    Git reads its configuration from the worktree, which the unit wrote, so each
    probe then runs inside that fence (#1990); a probe that cannot be placed in
    it observes nothing rather than running outside it. A fence that was not
    proven observes nothing either, unless the operator opted in to running
    unconfined (#1999).
    """
    root = Path(path)
    from .fanout_confinement import dispatcher_git_environment

    # Unfenced too: the worktree is still the unit's (#2035).
    environment = dispatcher_git_environment()
    fenced = confinement is not None and confinement.receipt.get('enforced') is True
    if confinement is not None and not fenced and not confinement.unconfined_allowed:
        return None

    def probe(argv: list[str]) -> tuple[bytes | None, str]:
        if not fenced:
            return bounded_session_probe(argv, cwd=str(root), env=environment)
        assert confinement is not None
        # No network and only the environment git needs (#2035).
        command = confinement.dispatcher_git_command(argv)
        if command is None:
            return None, 'probe_fence_unavailable'
        return bounded_session_probe(list(command[0]), cwd=str(root), env=command[1])

    try:
        root = root.resolve(strict=True)
        link = root / '.git'
        if not link.is_file() or link.is_symlink():
            return None
        link_stat = link.stat()
        values: list[str] = []
        for args in (['rev-parse', '--show-toplevel'], ['rev-parse', '--absolute-git-dir'],
                     ['rev-parse', '--path-format=absolute', '--git-common-dir'],
                     ['symbolic-ref', 'HEAD'], ['rev-parse', 'HEAD']):
            raw, _reason = probe(['git', '-c', 'core.fsmonitor=false', *args])
            if raw is None:
                return None
            values.append(raw.decode('utf-8').strip())
        top, git_dir, common, branch, head = values
        if Path(top).resolve() != root or not _SHA.fullmatch(head):
            return None
        directory_stat = Path(git_dir).stat()
        root_stat = root.stat()
        incarnation_id = str(uuid5(NAMESPACE_URL, repr((str(root), link_stat.st_dev,
            link_stat.st_ino, link_stat.st_ctime_ns, directory_stat.st_dev, directory_stat.st_ino))))
        incarnation = WorktreeIncarnation(incarnation_id, str(Path(common).resolve()), branch,
                                         root_stat.st_dev, root_stat.st_ino)
        status, _reason = probe(['git', '-c', 'core.fsmonitor=false', 'status', '--porcelain=v1', '-z', '--untracked-files=all'])
        if status is None:
            return None
        recovery: str | None = None
        if status:
            diff, _reason = probe(['git', '-c', 'core.fsmonitor=false', 'diff', '--no-ext-diff', '--no-textconv', '--binary', 'HEAD'])
            untracked, _reason = probe(['git', 'ls-files', '--others', '--exclude-standard', '-z'])
            if diff is None or untracked is None:
                return None
            digest = sha256(status + b'\x00' + diff)
            budget = 16 * 1024 * 1024
            for name in untracked.split(b'\x00'):
                if not name:
                    continue
                file = root / os.fsdecode(name)
                if file.is_symlink() or not file.resolve().is_relative_to(root):
                    return None
                with file.open('rb') as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > budget:
                        return None
                    digest.update(name + b'\x00')
                    while chunk := stream.read(65536):
                        budget -= len(chunk)
                        if budget < 0:
                            return None
                        digest.update(chunk)
                    after = os.fstat(stream.fileno())
                    if (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                            info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns):
                        return None
            recovery = digest.hexdigest()
        after_link = link.stat()
        if (after_link.st_ino, after_link.st_size, after_link.st_mtime_ns, after_link.st_ctime_ns) != (
                link_stat.st_ino, link_stat.st_size, link_stat.st_mtime_ns, link_stat.st_ctime_ns):
            return None
        return WorkspaceSnapshot(str(root), incarnation, head, bool(status), recovery)
    except (OSError, UnicodeError, ValueError):
        return None


def duplicate_session_references(values: Iterable[object]) -> frozenset[str]:
    """Find IDs shared by distinct attempt bindings; exact receipt replay is safe.

    The dispatcher/status reader must supply all fresh and held attempt receipts,
    then pass this set to each projection so BOTH ambiguous actions are disabled.
    """
    owners: dict[str, SessionBinding] = {}
    duplicates: set[str] = set()
    for value in values:
        receipt = read_session_receipt(value).receipt
        if receipt is None or receipt.reference is None:
            continue
        previous = owners.setdefault(receipt.reference, receipt.binding)
        if previous != receipt.binding:
            duplicates.add(receipt.reference)
    return frozenset(duplicates)


def project_session_resume(
    value: object, *, binding: SessionBinding, workspace: WorkspaceSnapshot | None,
    recovery_snapshot: str | None = None, duplicate_references: Collection[str] = (),
    platform: str = os.name,
) -> ResumeProjection:
    """Copy-only exact-ID action after selected lineage and fresh workspace checks.

    recovery_snapshot is the dispatcher's recorded recovery-state digest, NOT a
    value learned from the executor or copied from the current snapshot. Dirty
    failed work is actionable only when those independently observed digests match.
    No native-store existence or future resume success is implied by availability.
    """
    read = read_session_receipt(value)
    result: ResumeProjection = {
        'available': False, 'reason': read.reason, 'argv': [], 'cwd': None,
        'shell_command': None, 'execution_policy': 'copy_only', 'required_input': None,
        'native_resume_state': 'not_tested',
    }
    receipt = read.receipt
    if receipt is None or receipt.state != 'observed':
        return result
    if receipt.capability.protocol == FILE_EXPORT_PROTOCOL:
        # A file export is repair-only evidence. A budgeted repair inside the
        # dispatcher may re-enter the same session; a status read never renders
        # a vendor command and never launches one, so the answer is the same
        # whether or not this workspace is still the one that receipt ended on.
        result['reason'] = 'repair_only'
        return result
    if receipt.binding != binding:
        result['reason'] = 'binding_mismatch'
    elif receipt.reference in duplicate_references:
        result['reason'] = 'duplicate_reference'
    elif receipt.end_head is None:
        result['reason'] = 'end_revision_not_observed'
    elif (workspace is None or workspace.path != binding.worktree_path or
          workspace.incarnation != binding.worktree_incarnation or workspace.head != receipt.end_head):
        result['reason'] = 'stale_workspace'
    elif (workspace.dirty or recovery_snapshot is not None) and (
        recovery_snapshot is None or not _DIGEST.fullmatch(recovery_snapshot) or
        workspace.recovery_snapshot != recovery_snapshot
    ):
        result['reason'] = 'recovery_snapshot_mismatch'
    else:
        # read_session_receipt established the canonical UUID and supported pair.
        reference = _match(receipt.reference, _UUID)
        binary = receipt.capability.binary_identity.resolved_path
        argv = ([binary, 'exec', 'resume', reference, '-'] if receipt.capability.executor == 'codex'
                else [binary, '--resume=' + reference])
        result.update(available=True, reason='copy_only', argv=argv, cwd=binding.worktree_path)
        if receipt.capability.executor == 'codex':
            result['required_input'] = 'follow_up_prompt_on_stdin'
        if platform == 'posix':
            result['shell_command'] = 'cd -- ' + shlex.quote(binding.worktree_path) + ' && ' + shlex.join(argv)
    return result
