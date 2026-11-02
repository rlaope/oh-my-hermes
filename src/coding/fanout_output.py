"""Bounded binary fanout intake; raw data is transient and never spilled.

Call feed with bytes from binary pipes, finish each stream after EOF (or with
complete=False after a failed drain), then consume final text exactly once.
The observer receives a single bounded top-level JSON object and stream name.
It must validate/project session, usage or closed admission metadata immediately;
it must not retain or persist the event. Observer failures propagate to the
runner, which owns child termination. Legacy runners require an explicit adapter;
constructing this accumulator does not prove a launch/capture capability.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import threading
from typing import Literal, final

from .fanout_failure_diagnostics import (
    LIMIT_BYTES, SECRET_OVERLAP_BYTES, StreamDiagnostic, StreamName, SanitizedStream,
    is_object_list, is_string_map,
)

Protocol = Literal['plain', 'codex', 'claude']
EventObserver = Callable[[StreamName, dict[str, object]], None]
FRAME_LIMIT_BYTES = 1024 * 1024
DEPTH_LIMIT = 16
EVENT_LIMIT = 65536
FINAL_TEXT_LIMIT_BYTES = 256 * 1024
_CHUNK_BYTES = 8192
_USAGE_FIELDS = ('input_tokens', 'output_tokens', 'cached_input_tokens',
                 'cache_creation_input_tokens', 'cache_read_input_tokens', 'total_tokens')


def _depth_ok(raw: bytes) -> bool:
    depth = 0
    quoted = escaped = False
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > DEPTH_LIMIT:
                return False
        elif byte in (93, 125):
            depth -= 1
    return True


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise ValueError('nonfinite_json')


@final
class FanoutOutput:
    """One attempt, two independent streams, and one serialized observer seam.

    Stored raw buffers: at most 1MiB/frame/stream, 256KiB last final text,
    256KiB in-progress plain fence, and 2000-byte error windows/stream plus
    fixed secret-match overlap. Oversized frames drain through LF and recover.
    Parsed JSON is transient and bounded by frame bytes, depth and event count.
    """
    def __init__(self, *, protocol: str = 'plain',
                 observer: EventObserver | None = None,
                 known_secrets: tuple[str, ...] = ()) -> None:
        if protocol not in ('plain', 'codex', 'claude'):
            raise ValueError('unsupported_output_protocol')
        if len(known_secrets) > 128:
            raise ValueError('too_many_known_secrets')
        # Slice characters first: even a giant prompt never causes a giant copy.
        secrets = tuple(secret[:SECRET_OVERLAP_BYTES].encode('utf-8')[:SECRET_OVERLAP_BYTES]
                        for secret in known_secrets if secret)
        self.protocol = protocol
        self.observer = observer
        self._lock = threading.RLock()
        self._streams = {
            name: SanitizedStream(name, secrets, protocol=protocol != 'plain' and name == 'stdout')
            for name in ('stdout', 'stderr')
        }
        self._frames: dict[StreamName, bytearray] = {'stdout': bytearray(), 'stderr': bytearray()}
        self._discard: dict[StreamName, bool] = {'stdout': False, 'stderr': False}
        self._events = 0
        self._issues: set[str] = set()
        self._final = b''
        self._fence: bytearray | None = None
        self._fence_overrun = False
        self._has_root_result = False
        self._usage: dict[str, int] = {}
        self._legacy_streams: set[str] = set()

    @property
    def issues(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._issues))

    @property
    def usage(self) -> dict[str, int]:
        with self._lock:
            return dict(self._usage)

    @property
    def buffered_bytes(self) -> int:
        """Retained byte payload size, excluding bounded Python object overhead."""
        with self._lock:
            return (sum(len(frame) for frame in self._frames.values())
                    + sum(stream.buffered_bytes for stream in self._streams.values())
                    + len(self._final) + len(self._fence or b''))

    def feed(self, stream: str, data: bytes | str) -> None:
        if not isinstance(data, bytes):
            raise TypeError('fanout_output_requires_bytes')
        if stream not in ('stdout', 'stderr'):
            raise ValueError('invalid_output_stream')
        with self._lock:
            if self._streams[stream].closed:
                raise ValueError('output_stream_already_finished')
            for start in range(0, len(data), _CHUNK_BYTES):
                chunk = data[start:start + _CHUNK_BYTES]
                self._streams[stream].feed(chunk)
                self._ingest(stream, chunk)

    def _ingest(self, stream: StreamName, chunk: bytes) -> None:
        start = 0
        while start < len(chunk):
            end = chunk.find(b'\n', start)
            stop = len(chunk) if end < 0 else end + 1
            frame = self._frames[stream]
            if not self._discard[stream]:
                if len(frame) + stop - start > FRAME_LIMIT_BYTES:
                    frame.clear()
                    self._discard[stream] = True
                    self._issues.add('frame_limit')
                    self._streams[stream].limited = True
                    if stream == 'stdout' and self._fence is not None:
                        self._fence.clear()
                        self._fence_overrun = True
                        self._issues.add('final_text_limit')
                else:
                    frame.extend(chunk[start:stop])
            if end >= 0:
                raw = bytes(frame)
                frame.clear()
                discard = self._discard[stream]
                self._discard[stream] = False
                self._frame(stream, raw, discard=discard)
            start = stop

    def _frame(self, stream: StreamName, raw: bytes, *, discard: bool = False) -> None:
        if self.protocol == 'plain':
            if stream == 'stdout' and not discard:
                self._plain_line(raw)
            return
        self._events += 1
        if self._events > EVENT_LIMIT:
            self._lost_frame(stream, 'event_limit')
            self._streams[stream].limited = True
            return
        if discard:
            self._lost_frame(stream, 'frame_limit')
            return
        if not _depth_ok(raw):
            self._lost_frame(stream, 'depth_limit')
            return
        try:
            text = raw.decode('utf-8')
            load_event: Callable[..., object] = json.loads
            event = load_event(text, object_pairs_hook=_unique_object,
                               parse_constant=_reject_constant)
        except (ValueError, UnicodeError, RecursionError):
            self._lost_frame(stream, 'invalid_frame')
            return
        if not is_string_map(event) or not isinstance(event.get('type'), str):
            self._lost_frame(stream, 'invalid_frame')
            return
        if stream == 'stdout':
            self._native_final(event)
        if self.observer is not None:
            self.observer(stream, event)

    def _lost_frame(self, stream: StreamName, issue: str) -> None:
        self._issues.add(issue)
        if stream == 'stdout':
            self._final = b''
            # A lost root result may have superseded assistant fallback.
            self._has_root_result = True

    def _set_final(self, text: str) -> None:
        self._final = b''
        # UTF-8 can only expand; reject huge Python strings before encoding.
        if len(text) > FINAL_TEXT_LIMIT_BYTES:
            self._issues.add('final_text_limit')
            return
        try:
            raw = text.encode('utf-8')
        except UnicodeEncodeError:
            self._issues.add('invalid_final_text')
            return
        if len(raw) > FINAL_TEXT_LIMIT_BYTES:
            self._issues.add('final_text_limit')
        else:
            self._final = raw

    def _native_final(self, event: Mapping[str, object]) -> None:
        if event.get('parent_tool_use_id') is not None:
            return
        kind = event.get('type')
        if self.protocol == 'codex' and kind == 'item.completed':
            item = event.get('item')
            if is_string_map(item) and item.get('type') == 'agent_message':
                text = item.get('text')
                if isinstance(text, str):
                    self._set_final(text)
                else:
                    self._lost_frame('stdout', 'invalid_final_text')
        elif self.protocol == 'claude':
            if kind == 'result' and isinstance(event.get('result'), str):
                text = event['result']
                if isinstance(text, str):
                    self._has_root_result = True
                    self._set_final(text)
            elif kind == 'assistant' and not self._has_root_result:
                message = event.get('message')
                if is_string_map(message):
                    content = message.get('content')
                    if is_object_list(content):
                        texts: list[str] = []
                        for block in content:
                            if is_string_map(block) and block.get('type') == 'text':
                                text = block.get('text')
                                if isinstance(text, str):
                                    texts.append(text)
                        self._set_final(''.join(texts))
        if ((self.protocol == 'codex' and kind == 'turn.completed')
                or (self.protocol == 'claude' and kind == 'result')):
            usage = event.get('usage')
            if is_string_map(usage):
                # Last reading replaces the group; never combine different events.
                self._usage = {key: value for key in _USAGE_FIELDS
                               if type(value := usage.get(key)) is int and 0 <= value <= 2**63 - 1}

    def _plain_line(self, raw: bytes) -> None:
        try:
            line = raw.decode('utf-8').strip()
        except UnicodeDecodeError:
            if self._fence is not None:
                self._fence_overrun = True
                self._issues.add('invalid_final_text')
            return
        if self._fence is None:
            if line == '```json':
                self._fence = bytearray(b'```json\n')
                self._fence_overrun = False
        elif line == '```':
            if not self._fence_overrun and len(self._fence) + 4 <= FINAL_TEXT_LIMIT_BYTES:
                self._final = bytes(self._fence) + b'```\n'
            else:
                # Last complete fence is invalid: never borrow an older result.
                self._final = b''
                self._issues.add('final_text_limit')
            self._fence = None
        elif not self._fence_overrun:
            if len(self._fence) + len(raw) + 4 > FINAL_TEXT_LIMIT_BYTES:
                self._fence.clear()
                self._fence_overrun = True
                self._issues.add('final_text_limit')
            else:
                self._fence.extend(raw)

    def finish(self, stream: str, *, complete: bool = True) -> None:
        if stream not in ('stdout', 'stderr'):
            raise ValueError('invalid_output_stream')
        with self._lock:
            captured = self._streams[stream]
            if captured.closed:
                raise ValueError('output_stream_already_finished')
            frame = self._frames[stream]
            if complete and (frame or self._discard[stream]):
                raw = bytes(frame)
                frame.clear()
                self._frame(stream, raw, discard=self._discard[stream])
            frame.clear()
            self._discard[stream] = False
            captured.finish(complete=complete)
            if stream == 'stdout':
                self._fence = None

    def feed_legacy(self, stream: str, data: object, *, complete: bool = True) -> None:
        """Adapt an injected runner without claiming re-encoded text is wire bytes."""
        if isinstance(data, bytes):
            self.feed(stream, data)
        elif isinstance(data, str):
            self._legacy_streams.add(stream)
            for start in range(0, len(data), _CHUNK_BYTES):
                self.feed(stream, data[start:start + _CHUNK_BYTES].encode('utf-8', errors='surrogatepass'))
        else:
            complete = False
        self.finish(stream, complete=complete)

    def finish_pending(self, *, complete: bool = False) -> None:
        """Finalize only unfinished pipes after launch, drain or observer failure."""
        with self._lock:
            for name in ('stdout', 'stderr'):
                if not self._streams[name].closed:
                    self.finish(name, complete=complete)

    def streams(self) -> list[StreamDiagnostic]:
        with self._lock:
            snapshots = [self._streams[name].snapshot() for name in ('stdout', 'stderr')]
            for stream in snapshots:
                if stream['stream'] in self._legacy_streams:
                    stream['original_bytes'] = stream['original_lines'] = None
                    if stream['state'] == 'empty':
                        stream['state'] = 'not_captured'
                        stream['reason'] = 'not_captured'
            return snapshots

    def sandbox_refusal(self) -> str:
        """The executor-sandbox failure reason either stream named, or "".

        Start failure outranks read-only: a sandbox that never started explains
        every refusal after it.
        """
        with self._lock:
            seen = set().union(*(stream.sandbox_refusals for stream in self._streams.values()))
        for reason in ('executor_sandbox_start_failed', 'executor_sandbox_read_only'):
            if reason in seen:
                return reason
        return ''

    def error_window(self, stream: str) -> str:
        """Ephemeral bounded legacy retry/auth classifier input; NEVER persist."""
        if stream not in ('stdout', 'stderr'):
            raise ValueError('invalid_output_stream')
        with self._lock:
            text = self._streams[stream].error_window.decode('utf-8', errors='replace')
            return text.encode('utf-8')[-LIMIT_BYTES:].decode('utf-8', errors='ignore')

    def take_final_text(self) -> str:
        """Consume bounded result intake text; not diagnostic or session authority."""
        with self._lock:
            text = self._final.decode('utf-8')
            self._final = b''
            return text
