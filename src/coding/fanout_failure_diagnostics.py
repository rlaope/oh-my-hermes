"""Closed, sanitized failure metadata. No I/O and no raw-output spill pointers.

Dispatcher bindings are supplied explicitly; this module does not infer failure
from exit numbers, choose retries, or upgrade a process result into success.
"""
from __future__ import annotations

import codecs
from collections.abc import Sequence
import hashlib
import re
from typing import Literal, TypeGuard, TypedDict, final
import unicodedata

StreamName = Literal['stdout', 'stderr']
Phase = Literal['preflight', 'worktree', 'launch', 'worker', 'timeout',
                'unit_result', 'verification', 'dispatcher']
FailureReason = Literal['denial', 'missing_binary', 'spawn_error', 'nonzero',
                        'deadline', 'malformed_result', 'internal_error',
                        'executor_sandbox_read_only', 'executor_sandbox_start_failed']
ExitCodeSource = Literal['process', 'synthetic', 'not_observed']
StreamState = Literal['retained', 'redacted', 'withheld', 'empty', 'not_captured']
LIMIT_BYTES = 2000
LIMIT_LINES = 20
SECRET_OVERLAP_BYTES = 256
SCHEMA_VERSION = 'fanout_failure_diagnostic/v1'

# Deliberately closed: no interpolated paths, messages, commands or source text.
_SAFE_LINES = frozenset({
    'compiler failed', 'phase A failed', 'phase B failed',
    'Permission denied', 'permission denied', 'Operation not permitted',
    'No such file or directory', 'command not found', 'Connection refused',
    'Connection timed out', 'Authentication failed', 'fatal: not a git repository',
    'failed to load configuration: Failed to synchronize managed preferences',
})
# A known startup error whose raw line wraps a fixed message in a variable
# envelope. The full line must match; only the fixed template is retained, never
# the envelope, so retained text stays inside `_SAFE_LINES`. Codex on macOS,
# verbatim (#1996): `Error: thread/start: thread/start failed: failed to load
# configuration: Failed to synchronize managed preferences (code -32600)`.
_SAFE_LINE_TEMPLATES = (
    (re.compile(r'(?:Error: (?:[a-z/]+: )*thread/start failed: )?'
                r'failed to load configuration: Failed to synchronize managed preferences'
                r'(?: \(code -?[0-9]{1,6}\))?'),
     'failed to load configuration: Failed to synchronize managed preferences'),
)
_SECRET_MARKERS = re.compile(
    rb'(?i:authorization\s*:|bearer\s|api[_-]?key\s*[=:]|password\s*[=:]|'
    + rb'-----BEGIN [A-Z ]*PRIVATE KEY-----)|sk-|github_pat_|gh[pousr]_|AKIA|AIza'
)
_WITHHELD = 'Output withheld; no safe diagnostic text retained.'
_REDACTED = 'Sensitive output redacted.'
_STREAM_REASONS = frozenset({'safe_template', 'sensitive_output', 'invalid_utf8',
                             'unsafe_control', 'unknown_output', 'protocol_output',
                             'empty', 'not_captured', 'incomplete_capture'})
_PHASES = frozenset({'preflight', 'worktree', 'launch', 'worker', 'timeout',
                     'unit_result', 'verification', 'dispatcher'})
_REASONS = frozenset({'denial', 'missing_binary', 'spawn_error', 'nonzero',
                      'deadline', 'malformed_result', 'internal_error',
                      'executor_sandbox_read_only', 'executor_sandbox_start_failed'})
# Fixed phrases the executor's own sandbox prints when it refuses work, mapped
# to the failure reason they name (#2471). Matched anywhere in the stream, not
# only in the bounded error window: Codex prints the refusal mid-session and
# keeps going, so the tail rarely still holds it. Only the reason is kept; the
# phrase never enters retained diagnostic text. Sources, openai/codex:
# `core/src/safety.rs` (patch refused under a read-only policy) and
# `mxc-sandbox/src/transport.rs` (MXC refuses to start without a host variable).
SANDBOX_REFUSAL_MARKERS: tuple[tuple[bytes, str], ...] = (
    (b'writing is blocked by read-only sandbox', 'executor_sandbox_read_only'),
    (b'MXC requires nonempty Unicode host', 'executor_sandbox_start_failed'),
)
_SANDBOX_MARKER_OVERLAP = max(len(marker) for marker, _reason in SANDBOX_REFUSAL_MARKERS)


class StreamDiagnostic(TypedDict):
    stream: StreamName
    state: StreamState
    reason: str
    text: str
    limit_bytes: int
    limit_lines: int
    original_bytes: int | None
    original_lines: int | None
    kept_bytes: int
    kept_lines: int
    truncated: bool
    truncation_reason: str | None
    digest: str
    digest_basis: Literal['sanitized_utf8']


class FailureDiagnostic(TypedDict):
    schema_version: str
    fanout_id: str
    unit_id: str | None
    run_ref: str | None
    owner: str
    attempt_id: str | None
    worktree_ref: str | None
    base_sha: str | None
    observed_revision: str | None
    phase: Phase
    reason: FailureReason
    returncode: int | None
    exit_code_source: ExitCodeSource
    streams: list[StreamDiagnostic]


def _lines(raw: bytes) -> int:
    return raw.count(b'\n') + int(bool(raw) and not raw.endswith(b'\n'))


def _capped(text: str) -> str:
    # Sanitized input only. Never split UTF-8 code points in retained output.
    raw = ''.join(text.splitlines(keepends=True)[:LIMIT_LINES]).encode('utf-8')
    return raw[:LIMIT_BYTES].decode('utf-8', errors='ignore')


@final
class SanitizedStream:
    """Shared mutable capture seam; only snapshot() is suitable for persistence.

    Long known secrets use a conservative 256-byte prefix, not an unbounded
    match buffer. All bytes are screened even after the retention cap is hit.
    The error window is ephemeral classifier input, NOT diagnostic text.
    """
    def __init__(self, name: StreamName, secrets: tuple[bytes, ...], *, protocol: bool) -> None:
        self.name: StreamName = name
        self.secrets = secrets
        self.protocol = protocol
        self.decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self.original_bytes = 0
        self.newlines = 0
        self.terminal_lf = False
        self.captured = False
        self.closed = False
        self.complete = False
        self.invalid = False
        self.control = False
        self.sensitive = False
        self.unknown = False
        self.limited = False
        self.line = bytearray()
        self.line_overrun = False
        self.overlap = b''
        self.error_window = b''
        self.sandbox_overlap = b''
        self.sandbox_refusals: set[str] = set()
        self.text = ''

    @property
    def buffered_bytes(self) -> int:
        return (len(self.line) + len(self.overlap) + len(self.sandbox_overlap) + len(self.error_window)
                + len(self.text.encode('utf-8')) + 4)

    def feed(self, chunk: bytes) -> None:
        self.captured = True
        self.original_bytes += len(chunk)
        self.newlines += chunk.count(b'\n')
        if chunk:
            self.terminal_lf = chunk.endswith(b'\n')
        self.error_window = (self.error_window + chunk)[-LIMIT_BYTES:]
        sandbox_screen = self.sandbox_overlap + chunk
        for marker, reason in SANDBOX_REFUSAL_MARKERS:
            if marker in sandbox_screen:
                self.sandbox_refusals.add(reason)
        self.sandbox_overlap = sandbox_screen[-_SANDBOX_MARKER_OVERLAP:]
        screen = self.overlap + chunk
        if _SECRET_MARKERS.search(screen) or any(secret in screen for secret in self.secrets):
            self.sensitive = True
        self.overlap = screen[-SECRET_OVERLAP_BYTES:]
        if not self.invalid:
            try:
                text = self.decoder.decode(chunk)
            except UnicodeDecodeError:
                self.invalid = True
                self.decoder.reset()
            else:
                if any(ch != '\n' and unicodedata.category(ch).startswith('C') for ch in text):
                    self.control = True
        # Only one bounded candidate line is ever held, even without a newline.
        start = 0
        while start < len(chunk):
            end = chunk.find(b'\n', start)
            stop = len(chunk) if end < 0 else end + 1
            segment = chunk[start:stop]
            room = LIMIT_BYTES - len(self.line)
            self.line.extend(segment[:room])
            if len(segment) > room:
                self.line_overrun = True
            if end >= 0:
                self._finish_line()
            start = stop
        if self.invalid or self.control or self.sensitive or self.unknown or self.protocol:
            self.text = ''

    def _finish_line(self) -> None:
        try:
            text = self.line.decode('utf-8')
        except UnicodeDecodeError:
            text = ''
        line = text.removesuffix('\n')
        line = next((template for pattern, template in _SAFE_LINE_TEMPLATES if pattern.fullmatch(line)), line)
        if self.line_overrun or line not in _SAFE_LINES:
            self.unknown = True
        elif not (self.unknown or self.invalid or self.control or self.sensitive or self.protocol):
            self.text = _capped(self.text + line + ('\n' if text.endswith('\n') else ''))
        self.line.clear()
        self.line_overrun = False

    def finish(self, *, complete: bool) -> None:
        self.captured = True
        self.closed = True
        self.complete = complete
        if complete and not self.invalid:
            try:
                _ = self.decoder.decode(b'', final=True)
            except UnicodeDecodeError:
                self.invalid = True
        self.decoder.reset()
        if self.line or self.line_overrun:
            self._finish_line()
        self.overlap = b''

    def snapshot(self) -> StreamDiagnostic:
        count_lines = self.newlines + int(self.original_bytes > 0 and not self.terminal_lf)
        state: StreamState
        if not self.captured:
            state, reason, text = 'not_captured', 'not_captured', ''
        elif self.invalid:
            state, reason, text = 'withheld', 'invalid_utf8', _WITHHELD
        elif self.sensitive:
            state, reason, text = 'redacted', 'sensitive_output', _REDACTED
        elif self.control:
            state, reason, text = 'withheld', 'unsafe_control', _WITHHELD
        elif not self.closed or not self.complete:
            state, reason, text = 'withheld', 'incomplete_capture', _WITHHELD
        elif self.original_bytes == 0:
            state, reason, text = 'empty', 'empty', ''
        elif self.protocol:
            state, reason, text = 'withheld', 'protocol_output', _WITHHELD
        elif self.unknown:
            state, reason, text = 'withheld', 'unknown_output', _WITHHELD
        else:
            state, reason, text = 'retained', 'safe_template', self.text
        text = _capped(text)
        raw = text.encode('utf-8')
        truncation = ('byte_limit' if self.original_bytes > LIMIT_BYTES else
                      'line_limit' if count_lines > LIMIT_LINES else
                      'capture_limit' if self.limited else None)
        return {'stream': self.name, 'state': state, 'reason': reason, 'text': text,
                'limit_bytes': LIMIT_BYTES, 'limit_lines': LIMIT_LINES,
                'original_bytes': self.original_bytes if self.complete else None,
                'original_lines': count_lines if self.complete else None,
                'kept_bytes': len(raw), 'kept_lines': _lines(raw),
                'truncated': truncation is not None, 'truncation_reason': truncation,
                'digest': hashlib.sha256(raw).hexdigest(), 'digest_basis': 'sanitized_utf8'}


def _binding(value: object, *, nullable: bool = True) -> bool:
    if value is None:
        return nullable
    return (isinstance(value, str) and 0 < len(value) <= 2048
            and not any(unicodedata.category(ch).startswith('C') for ch in value))


def _object_map(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def is_string_map(value: object) -> TypeGuard[dict[str, object]]:
    return _object_map(value) and all(isinstance(key, str) for key in value)


def is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _valid_stream(value: object) -> TypeGuard[StreamDiagnostic]:
    if not is_string_map(value) or set(value) != set(StreamDiagnostic.__annotations__):
        return False
    if (value['stream'] not in ('stdout', 'stderr')
            or not isinstance(value['reason'], str) or value['reason'] not in _STREAM_REASONS):
        return False
    text = value['text']
    if not isinstance(text, str) or len(text) > LIMIT_BYTES:
        return False
    try:
        raw = text.encode('utf-8')
    except UnicodeEncodeError:
        return False
    if (len(raw) > LIMIT_BYTES or _lines(raw) > LIMIT_LINES
            or any(ch != '\n' and unicodedata.category(ch).startswith('C') for ch in text)):
        return False
    state, reason = value['state'], value['reason']
    if state == 'retained':
        if reason != 'safe_template' or not text or any(line not in _SAFE_LINES for line in text.splitlines()):
            return False
    elif state == 'redacted':
        if reason != 'sensitive_output' or text != _REDACTED:
            return False
    elif state == 'withheld':
        if reason not in ('invalid_utf8', 'unsafe_control', 'unknown_output', 'protocol_output', 'incomplete_capture') or text != _WITHHELD:
            return False
    elif state in ('empty', 'not_captured'):
        if reason != state or text:
            return False
    else:
        return False
    if (value['limit_bytes'] != LIMIT_BYTES or value['limit_lines'] != LIMIT_LINES
            or type(value['kept_bytes']) is not int or value['kept_bytes'] != len(raw)
            or type(value['kept_lines']) is not int or value['kept_lines'] != _lines(raw)
            or value['digest_basis'] != 'sanitized_utf8'
            or value['digest'] != hashlib.sha256(raw).hexdigest()):
        return False
    size, lines = value['original_bytes'], value['original_lines']
    if (size is None) != (lines is None) or type(value['truncated']) is not bool:
        return False
    if size is not None:
        if type(size) is not int or type(lines) is not int or not 0 <= lines <= size:
            return False
        if (size == 0) != (lines == 0):
            return False
        if state == 'retained' and (size < len(raw) or lines < _lines(raw)):
            return False
        expected_limit = 'byte_limit' if size > LIMIT_BYTES else 'line_limit' if lines > LIMIT_LINES else None
        if expected_limit and (not value['truncated'] or value['truncation_reason'] != expected_limit):
            return False
    if state == 'empty' and (size != 0 or lines != 0):
        return False
    if state == 'not_captured' and size is not None:
        return False
    if value['truncated']:
        return value['truncation_reason'] in ('byte_limit', 'line_limit', 'capture_limit')
    return value['truncation_reason'] is None


def _valid_diagnostic(value: object) -> TypeGuard[FailureDiagnostic]:
    if not is_string_map(value) or set(value) != set(FailureDiagnostic.__annotations__):
        return False
    if (value['schema_version'] != SCHEMA_VERSION
            or not isinstance(value['phase'], str) or value['phase'] not in _PHASES
            or not isinstance(value['reason'], str) or value['reason'] not in _REASONS):
        return False
    for key in ('fanout_id', 'owner', 'unit_id', 'run_ref', 'attempt_id',
                'worktree_ref', 'base_sha', 'observed_revision'):
        if not _binding(value[key], nullable=key not in ('fanout_id', 'owner')):
            return False
    code, source = value['returncode'], value['exit_code_source']
    if source == 'not_observed':
        if code is not None:
            return False
    elif source in ('process', 'synthetic'):
        if type(code) is not int:
            return False
    else:
        return False
    streams = value['streams']
    if not is_object_list(streams) or len(streams) > 2:
        return False
    names: list[StreamName] = []
    for stream in streams:
        if not _valid_stream(stream):
            return False
        names.append(stream['stream'])
    return names in ([], ['stdout'], ['stderr'], ['stdout', 'stderr'])


def build_failure_diagnostic(
    *, fanout_id: str, unit_id: str | None, run_ref: str | None, owner: str,
    attempt_id: str | None, worktree_ref: str | None, base_sha: str | None,
    observed_revision: str | None, phase: str, reason: str,
    returncode: int | None, exit_code_source: str,
    streams: Sequence[StreamDiagnostic] = (), failed: bool = True,
) -> FailureDiagnostic | None:
    """Project an actual phase failure; successful phases return no diagnostic."""
    if not failed:
        return None
    value: dict[str, object] = {
        'schema_version': SCHEMA_VERSION, 'fanout_id': fanout_id, 'unit_id': unit_id,
        'run_ref': run_ref, 'owner': owner, 'attempt_id': attempt_id,
        'worktree_ref': worktree_ref, 'base_sha': base_sha,
        'observed_revision': observed_revision, 'phase': phase, 'reason': reason,
        'returncode': returncode, 'exit_code_source': exit_code_source,
        'streams': sorted((s.copy() for s in streams), key=lambda s: s['stream'] == 'stderr'),
    }
    if not _valid_diagnostic(value):
        raise ValueError('invalid_failure_diagnostic')
    return value


def read_failure_diagnostic(
    value: object, *, fanout_id: str, unit_id: str | None, attempt_id: str | None,
) -> FailureDiagnostic | None:
    """Optional closed reader: no spill resolution, migration, or stale borrowing."""
    if not _valid_diagnostic(value):
        return None
    if (value['fanout_id'], value['unit_id'], value['attempt_id']) != (fanout_id, unit_id, attempt_id):
        return None
    result = value.copy()
    result['streams'] = [s.copy() for s in value['streams']]
    return result
