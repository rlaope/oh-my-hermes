"""POST typed questions to Jev and classify the reply: one of the two network clients in `src/`.

The other is the OMH TUI's update notice (`tui/update_notice.py`).

`omh_jev_ask` is the only caller (`tests/test_handoff_safety_contract_enforcement.py`
pins that no other module imports this one). Everything here exists to keep a
single explicit, user-requested call narrow:

* Two route identities, fixed in `ROUTES`. The TypeSafe endpoint defaults to
  `https://api.typesafe.ai/v1/systemone`; `TYPESAFE_BASE_URL`, the API-root
  variable TypeSafe's own SDKs read, may name an operator-configured HTTPS
  root instead (`route_url`). The OpenRouter route remains fixed. The request
  never accepts a URL argument.
* HTTPS only, default certificate verification, and every 3xx refused.
  CPython's redirect handler copies `Authorization` onto the redirected
  request, including to another host, so a redirect is a non-answer here.
* Bounded both ways: a request body above `MAX_REQUEST_BYTES` is refused
  before a socket opens, and a response is read to `MAX_RESPONSE_BYTES` at
  most.
* A retry only follows a reply that says the request was NOT processed: 429
  (rate limited) and 503/529 (overloaded), within `TOTAL_DEADLINE_SECONDS`.
  Any other 5xx -- 500, 502, 520-523 -- may come after the origin received
  and billed the request, so it is reported as `server_error` and the caller
  decides, the same way a timeout or a connection failure is never retried.
  A gateway timeout (504, 524) is a timeout in that sense -- the gateway gave
  up after the origin may have received the request -- so it is reported as
  `timeout`.
* The deadline also bounds the read: the body is read in chunks, the
  deadline is checked between them, and before each read the socket's own
  timeout is set to the time left, because urllib's timeout applies per
  socket operation and a server that trickles bytes would otherwise hold the
  turn a full attempt timeout past it. Residual: name resolution
  (`getaddrinfo`) has no timeout in the standard library, and the status line
  and headers are read inside `urlopen` under the per-operation attempt
  timeout; neither is bounded by the deadline.
* The key lives in one local variable of `send_ask`. It is never returned,
  never put in an error string, and any server text echoed back -- an error
  excerpt, the served model id -- has JSON escapes decoded and then every run
  that matches a substring of the key at least `MIN_KEY_FRAGMENT_CHARS` long,
  compared case-insensitively, redacted before it leaves this module; an echo
  that spells such a substring with whitespace between its characters
  redacts the whole excerpt.

Wire facts are `documented_not_observed` (docs.typesafe.ai/api.md and
openrouter.ai/docs/guides/community/typesafe-sdk.md, read 2026-09-23). Proxy
variables such as `HTTPS_PROXY` are honored by urllib, so a configured proxy
sees the destination host; `omh doctor` says so.

Stdlib and intra-bundle imports only: Hermes loads this directory with its own
interpreter.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

ROUTE_TYPESAFE: Final = "typesafe"
ROUTE_OPENROUTER: Final = "openrouter"

# route id -> (URL, key variable name). A third route is a code change with a
# cited source, not configuration.
TYPESAFE_BASE_URL_ENV: Final = "TYPESAFE_BASE_URL"
TYPESAFE_DEFAULT_BASE_URL: Final = "https://api.typesafe.ai"
TYPESAFE_VERSION_PATH: Final = "/v1"
TYPESAFE_ENDPOINT_PATH: Final = "/systemone"

ROUTES: Final[dict[str, tuple[str, str]]] = {
    ROUTE_TYPESAFE: (
        f"{TYPESAFE_DEFAULT_BASE_URL}{TYPESAFE_VERSION_PATH}{TYPESAFE_ENDPOINT_PATH}",
        "TYPESAFE_API_KEY",
    ),
    ROUTE_OPENROUTER: ("https://openrouter.ai/api/v1/systemone", "OPENROUTER_API_KEY"),
}

# Mirror of `MODEL_CONTRACTS["jev-1.13.0"]["served_ids"]` plus every declared
# projection row whose contract is `jev-1.13.0` (`src/coding/model_contracts.py`).
# The bundle cannot import that module; `tests/test_jev_ask_tool.py` pins the
# mirror.
FIRST_PARTY_MODEL_IDS: Final = ("jev-1.13.0", "jev-latest", "jev-preview")
# OpenRouter's documented spelling of the pinned version
# (openrouter.ai/docs/guides/community/typesafe-sdk.md, read 2026-09-23:
# `jev-1.13` maps to `typesafe/jev-1.13`). Accepted on that route only.
OPENROUTER_ONLY_MODEL_IDS: Final = ("jev-1.13",)
DEFAULT_MODEL: Final = "jev-latest"
# The version a threshold was written against. The vendor advises pinning a
# version when thresholds are tuned (docs.typesafe.ai/models.md); presets do.
PINNED_MODEL_BY_ROUTE: Final[dict[str, str]] = {
    ROUTE_TYPESAFE: "jev-1.13.0",
    ROUTE_OPENROUTER: "jev-1.13",
}

# Mirror of `_JEV_1_13["pricing_usd_per_mtok"]["input"]`, read 2026-09-21.
INPUT_PRICE_USD_PER_MTOK: Final = 0.042
PRICE_READ_ON: Final = "2026-09-21"

MAX_REQUEST_BYTES: Final = 256 * 1024
MAX_RESPONSE_BYTES: Final = 1024 * 1024
MAX_API_ERROR_CHARS: Final = 300
MAX_SERVED_MODEL_CHARS: Final = 128
# Any substring of the key this long is redacted wherever it appears.
MIN_KEY_FRAGMENT_CHARS: Final = 8
READ_CHUNK_BYTES: Final = 64 * 1024
ATTEMPT_TIMEOUT_SECONDS: Final = 10.0
TOTAL_DEADLINE_SECONDS: Final = 30.0
MAX_RETRIES: Final = 2
BACKOFF_START_SECONDS: Final = 0.5
BACKOFF_CAP_SECONDS: Final = 5.0
BACKOFF_JITTER_SECONDS: Final = 0.25

MAX_CHOICE_OPTIONS: Final = 255
MIN_SCORE_LEVELS: Final = 2
MAX_SCORE_LEVELS: Final = 10
QUESTION_TYPES: Final = ("noul", "choice", "score")

STATUS_ANSWERED: Final = "answered"
STATUS_CONSENT_NOT_OBSERVED: Final = "consent_not_observed"
STATUS_KEY_MISSING: Final = "key_missing"
STATUS_KEY_UNRESOLVABLE: Final = "key_unresolvable"
STATUS_INVALID_REQUEST: Final = "invalid_request"
STATUS_REJECTED_BY_API: Final = "rejected_by_api"
STATUS_AUTH_FAILED: Final = "auth_failed"
STATUS_PERMISSION_DENIED: Final = "permission_denied"
STATUS_PAYMENT_REQUIRED: Final = "payment_required"
STATUS_RATE_LIMITED: Final = "rate_limited"
STATUS_OVERLOADED: Final = "overloaded"
STATUS_SERVER_ERROR: Final = "server_error"
STATUS_TIMEOUT: Final = "timeout"
STATUS_NETWORK_ERROR: Final = "network_error"
STATUS_REJECTED_REDIRECT: Final = "rejected_redirect"
STATUS_MALFORMED_RESPONSE: Final = "malformed_response"

# Every status the tool can return. Exactly one of them is an answer;
# `tests/test_jev_ask_tool.py` re-derives this tuple and fails if a second
# member ever maps to `ok: true`.
ASK_STATUSES: Final = (
    STATUS_ANSWERED,
    STATUS_CONSENT_NOT_OBSERVED,
    STATUS_KEY_MISSING,
    STATUS_KEY_UNRESOLVABLE,
    STATUS_INVALID_REQUEST,
    STATUS_REJECTED_BY_API,
    STATUS_AUTH_FAILED,
    STATUS_PERMISSION_DENIED,
    STATUS_PAYMENT_REQUIRED,
    STATUS_RATE_LIMITED,
    STATUS_OVERLOADED,
    STATUS_SERVER_ERROR,
    STATUS_TIMEOUT,
    STATUS_NETWORK_ERROR,
    STATUS_REJECTED_REDIRECT,
    STATUS_MALFORMED_RESPONSE,
)
SUCCESS_STATUS: Final = STATUS_ANSWERED
# The caller may try again later; the tool itself retries only the first two,
# the replies that say the request was not processed (429, 503, 529).
RETRYABLE_STATUSES: Final = frozenset(
    {STATUS_RATE_LIMITED, STATUS_OVERLOADED, STATUS_SERVER_ERROR, STATUS_TIMEOUT, STATUS_NETWORK_ERROR}
)
_AUTO_RETRY_STATUSES: Final = frozenset({STATUS_RATE_LIMITED, STATUS_OVERLOADED})


class AskRequestError(ValueError):
    """The request cannot be sent as given; no socket was opened."""


@dataclass(frozen=True)
class TransportReply:
    """What one POST produced: an HTTP status, the headers OMH reads, and the body."""

    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[Request, float], TransportReply]


class _RefuseRedirects(HTTPRedirectHandler):
    """Refuse every 3xx rather than follow it with the Authorization header attached."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - urllib signature
        return None


def _default_transport(request: Request, timeout: float) -> TransportReply:
    """Send through a stdlib opener that follows no redirect.

    `build_opener` still installs the default proxy handler, so `HTTPS_PROXY`
    is honored; the redirect refusal is what keeps the key on the first host.
    An `HTTPError` is a reply the server sent, so it is returned as one
    rather than raised.
    """
    deadline = time.monotonic() + timeout
    opener = build_opener(_RefuseRedirects(), HTTPSHandler())
    try:
        with opener.open(request, timeout=timeout) as response:
            body = _read_bounded(response, deadline)
            return TransportReply(int(response.status), _header_view(response.headers), body)
    except HTTPError as error:
        try:
            body = _read_bounded(error, deadline) if error.fp is not None else b""
        except OSError:
            body = b""
        return TransportReply(int(error.code), _header_view(error.headers), body)


def _read_bounded(response: Any, deadline: float, clock: Callable[[], float] = time.monotonic) -> bytes:
    """Read at most MAX_RESPONSE_BYTES + 1 bytes, raising TimeoutError past `deadline`.

    `read1` returns as soon as any bytes are available, so the deadline is
    checked between chunks rather than after one blocking read of the whole
    bound, and each read's socket timeout is the time left, so one slow read
    cannot run past the deadline either.
    """
    reader = getattr(response, "read1", None) or response.read
    chunks: list[bytes] = []
    total = 0
    while total <= MAX_RESPONSE_BYTES:
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("the response did not finish within the attempt deadline")
        _bound_socket_timeout(response, remaining)
        chunk = reader(min(READ_CHUNK_BYTES, MAX_RESPONSE_BYTES + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _bound_socket_timeout(response: Any, seconds: float) -> None:
    """Set the response socket's timeout to `seconds` when the stdlib objects expose it.

    `urlopen` returns an `http.client.HTTPResponse` whose `fp` is a buffered
    reader over `socket.SocketIO`; an `HTTPError` wraps that response once
    more. Anything else -- a test double, a changed stdlib -- keeps the
    per-operation timeout and the between-chunk check.
    """
    node: Any = response
    for _ in range(4):
        sock = getattr(node, "_sock", None)
        settimeout = getattr(sock, "settimeout", None)
        if callable(settimeout):
            settimeout(max(seconds, 0.001))
            return
        node = getattr(node, "raw", None) or getattr(node, "fp", None)
        if node is None:
            return


def _header_view(headers: object) -> dict[str, str]:
    view: dict[str, str] = {}
    for name in ("retry-after", "retry-after-ms", "x-typesafe-request-id"):
        value = headers.get(name) if hasattr(headers, "get") else None
        if value is not None:
            view[name] = str(value)[:64]
    return view


def route_url(route: str, environ: Mapping[str, str] | None = None) -> str:
    """Resolve a route endpoint; the TypeSafe one may come from `TYPESAFE_BASE_URL`.

    TypeSafe's Python and JavaScript SDKs read `TYPESAFE_BASE_URL` as the API
    root (default `https://api.typesafe.ai`) and append `/v1/systemone`, so a
    value set for them must reach the same endpoint here. A root that already
    ends in `/v1` gets `/systemone`, and one that already ends in `/systemone`
    is used as is. Anything but an HTTPS URL with a host and no userinfo,
    query or fragment is refused before a socket opens.
    """
    if route not in ROUTES:
        raise AskRequestError(f"route must be one of {', '.join(ROUTES)}")
    default_url, _ = ROUTES[route]
    if route != ROUTE_TYPESAFE:
        return default_url
    values = os.environ if environ is None else environ
    raw_base_url = str(values.get(TYPESAFE_BASE_URL_ENV, "") or "").strip()
    if not raw_base_url:
        return default_url
    if any(char.isspace() or ord(char) < 0x20 for char in raw_base_url):
        raise AskRequestError(f"{TYPESAFE_BASE_URL_ENV} must be an HTTPS base URL")
    try:
        parsed = urlsplit(raw_base_url)
        _ = parsed.port
    except ValueError as error:
        raise AskRequestError(f"{TYPESAFE_BASE_URL_ENV} must be an HTTPS base URL") from error
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise AskRequestError(
            f"{TYPESAFE_BASE_URL_ENV} must be an HTTPS base URL without credentials, query, or fragment"
        )
    base_path = parsed.path.rstrip("/")
    if base_path.endswith(TYPESAFE_ENDPOINT_PATH):
        endpoint_path = base_path
    elif base_path.endswith(TYPESAFE_VERSION_PATH):
        endpoint_path = f"{base_path}{TYPESAFE_ENDPOINT_PATH}"
    else:
        endpoint_path = f"{base_path}{TYPESAFE_VERSION_PATH}{TYPESAFE_ENDPOINT_PATH}"
    return urlunsplit(("https", parsed.netloc, endpoint_path, "", ""))


def build_request_body(model: str, state: object, questions: Mapping[str, Any]) -> bytes:
    """Serialize the documented body once, with exactly these three keys."""
    body = json.dumps({"model": model, "state": state, "questions": questions}, ensure_ascii=False)
    encoded = body.encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        raise AskRequestError(f"request body is {len(encoded)} bytes; the bound is {MAX_REQUEST_BYTES}")
    return encoded


def send_ask(
    *,
    route: str,
    key: str,
    body: bytes,
    user_agent: str,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    jitter: Callable[[], float] = random.random,
) -> dict[str, Any]:
    """POST one ask and classify the outcome. Never raises for a network outcome.

    Returns `{status, attempts, latency_ms, api_status, reply?, retry_after_s?,
    api_error?}` where `reply` is the parsed JSON object on a 200. The key is
    not in the result and not in any message: a server excerpt is scrubbed of
    it before it is returned.
    """
    if route not in ROUTES:
        raise AskRequestError(f"route must be one of {', '.join(ROUTES)}")
    url = route_url(route)
    if not url.startswith("https://"):
        raise AskRequestError("only HTTPS routes are sent")
    send = transport or _default_transport
    started = clock()
    deadline = started + TOTAL_DEADLINE_SECONDS
    attempts = 0
    backoff = BACKOFF_START_SECONDS
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            return _outcome(STATUS_TIMEOUT, attempts, started, clock)
        request = Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": user_agent,
            },
        )
        attempts += 1
        try:
            reply = send(request, min(ATTEMPT_TIMEOUT_SECONDS, remaining))
        except (TimeoutError, URLError, OSError, ValueError) as error:
            return _outcome(_transport_failure_status(error), attempts, started, clock)
        except Exception:  # noqa: BLE001 - classified: a transport failure OMH does not name is a network_error, never an answer
            return _outcome(STATUS_NETWORK_ERROR, attempts, started, clock)
        status = _status_for_http(reply.status)
        if status == STATUS_ANSWERED:
            if len(reply.body) > MAX_RESPONSE_BYTES:
                return _outcome(STATUS_MALFORMED_RESPONSE, attempts, started, clock, api_status=reply.status)
            parsed = _parse_object(reply.body)
            if parsed is None:
                return _outcome(STATUS_MALFORMED_RESPONSE, attempts, started, clock, api_status=reply.status)
            result = _outcome(STATUS_ANSWERED, attempts, started, clock, api_status=reply.status)
            result["reply"] = parsed
            return result
        retry_after = _retry_after_seconds(reply.headers)
        extra: dict[str, Any] = {"api_status": reply.status}
        if retry_after is not None:
            extra["retry_after_s"] = retry_after
        if status in {STATUS_REJECTED_BY_API, STATUS_AUTH_FAILED, STATUS_PERMISSION_DENIED, STATUS_PAYMENT_REQUIRED}:
            extra["api_error"] = _api_error_excerpt(reply.body, key)
        if status not in _AUTO_RETRY_STATUSES or attempts > MAX_RETRIES:
            return _outcome(status, attempts, started, clock, **extra)
        wait = min(backoff, BACKOFF_CAP_SECONDS) + jitter() * BACKOFF_JITTER_SECONDS
        if retry_after is not None:
            wait = retry_after
        if clock() + wait >= deadline:
            # The server's own wait does not fit the budget: report it and do
            # not sleep past the deadline.
            return _outcome(status, attempts, started, clock, **extra)
        sleep(wait)
        backoff *= 2


def _outcome(
    status: str,
    attempts: int,
    started: float,
    clock: Callable[[], float],
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "attempts": attempts,
        "latency_ms": max(0, int(round((clock() - started) * 1000))),
        "api_status": extra.pop("api_status", 0),
    }
    result.update(extra)
    return result


def _status_for_http(code: int) -> str:
    if code == 200:
        return STATUS_ANSWERED
    if 300 <= code < 400:
        return STATUS_REJECTED_REDIRECT
    if code in {400, 404, 413, 422}:
        return STATUS_REJECTED_BY_API
    if code == 401:
        return STATUS_AUTH_FAILED
    if code == 402:
        return STATUS_PAYMENT_REQUIRED
    if code == 403:
        return STATUS_PERMISSION_DENIED
    if code == 429:
        return STATUS_RATE_LIMITED
    if code in {503, 529}:
        return STATUS_OVERLOADED
    if code in {504, 524}:
        # The gateway timed out waiting for the origin, which may already
        # have received (and billed) the request: a timeout, never retried.
        return STATUS_TIMEOUT
    if code == 408 or code >= 500:
        return STATUS_SERVER_ERROR
    # Any other status is a reply OMH has no reading for: not an answer.
    return STATUS_MALFORMED_RESPONSE


def _transport_failure_status(error: BaseException) -> str:
    if isinstance(error, TimeoutError):
        return STATUS_TIMEOUT
    reason = getattr(error, "reason", None)
    if isinstance(reason, TimeoutError):
        return STATUS_TIMEOUT
    return STATUS_NETWORK_ERROR


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    raw_ms = headers.get("retry-after-ms")
    if raw_ms is not None:
        try:
            value = float(raw_ms) / 1000.0
        except ValueError:
            value = math.nan
        if math.isfinite(value) and value >= 0:
            return value
    raw = headers.get("retry-after")
    if raw is not None:
        try:
            value = float(raw)
        except ValueError:
            return None
        if math.isfinite(value) and value >= 0:
            return value
    return None


def _parse_object(body: bytes) -> dict[str, Any] | None:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


_JSON_ESCAPE = re.compile(r"\\(?:u([0-9A-Fa-f]{4})|(.))", re.DOTALL)


def _decode_escapes(text: str) -> str:
    """`text` with JSON-style escapes decoded: `\\uXXXX` to its character, `\\x` to `x`."""
    return _JSON_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)) if match.group(1) else match.group(2), text)


def _fold(text: str) -> str:
    """Lower-case per character, keeping positions aligned with `text`."""
    return "".join(lowered if len(lowered := char.lower()) == 1 else char for char in text)


def _key_windows(key: str) -> set[str]:
    """Every MIN_KEY_FRAGMENT_CHARS-long window of the folded, whitespace-free key."""
    folded_key = _fold("".join(key.split()))
    width = min(MIN_KEY_FRAGMENT_CHARS, len(folded_key))
    return {folded_key[index:index + width] for index in range(len(folded_key) - width + 1)} if width else set()


def carries_key_fragment(text: str, key: str) -> bool:
    """Whether `text`, folded and with all whitespace removed, holds a key window.

    Whitespace is dropped from both sides first, so a key spelled with its
    characters spaced apart, or broken across lines, still matches.
    """
    windows = _key_windows(key)
    if not windows:
        return False
    compact = _fold("".join(str(text).split()))
    width = len(next(iter(windows)))
    return any(compact[index:index + width] in windows for index in range(len(compact) - width + 1))


def scrub_key(text: str, key: str) -> str:
    """`text` with every run that matches a substring of the key replaced by `[redacted]`.

    A server may echo the key whole, cut short at either end, from its middle,
    upper-cased, or JSON-escaped (`tsk\\u005flive...`). JSON escapes are decoded
    first, then every window of MIN_KEY_FRAGMENT_CHARS characters that equals a
    window of the key, compared case-insensitively, is marked, and each run of
    marked characters becomes one `[redacted]`. A key shorter than the window
    is matched whole. An echo with whitespace between the key's characters
    has no contiguous run to mark, so when one survives the marking the whole
    text becomes `[redacted]`. Over-redaction is accepted; a key substring of
    MIN_KEY_FRAGMENT_CHARS or more never survives, spaced out or not.
    """
    if not key:
        return text
    text = _decode_escapes(text)
    scrubbed = _scrub_contiguous(text, key)
    return "[redacted]" if carries_key_fragment(scrubbed, key) else scrubbed


def _scrub_contiguous(text: str, key: str) -> str:
    """Replace each run of characters covered by a contiguous key window with `[redacted]`."""
    width = min(MIN_KEY_FRAGMENT_CHARS, len(key))
    folded_key = _fold(key)
    windows = {folded_key[index:index + width] for index in range(len(key) - width + 1)}
    folded = _fold(text)
    marked = bytearray(len(text))
    for index in range(len(text) - width + 1):
        if folded[index:index + width] in windows:
            marked[index:index + width] = b"\x01" * width
    if not any(marked):
        return text
    pieces: list[str] = []
    index = 0
    while index < len(text):
        if marked[index]:
            while index < len(text) and marked[index]:
                index += 1
            pieces.append("[redacted]")
        else:
            pieces.append(text[index])
            index += 1
    return "".join(pieces)


def _bounded_scrubbed(text: str, key: str, limit: int) -> str:
    """Control-strip and collapse, scrub, then cut to `limit`.

    Only the head a cut can keep is scrubbed: `limit` characters plus one key
    length, so a key substring that starts before the cut is found whole. The
    scrub runs before the cut, so the cut cannot leave a new key fragment.
    """
    decoded = _decode_escapes(text)
    cleaned = "".join(char if char.isprintable() else " " for char in decoded)
    head = " ".join(cleaned.split())[: limit + len(key) + 1]
    return scrub_key(head, key)[:limit]


def _api_error_excerpt(body: bytes, key: str) -> str:
    """A bounded, control-stripped excerpt of the server's error text, scrubbed of the key."""
    return _bounded_scrubbed(body.decode("utf-8", errors="replace"), key, MAX_API_ERROR_CHARS)


def safe_served_model(served: str, key: str) -> str:
    """The reply's `model` field as it may be shown and stored: scrubbed of the key, bounded."""
    return _bounded_scrubbed(str(served or ""), key, MAX_SERVED_MODEL_CHARS)


# ---------------------------------------------------------------------------
# Local validation of the request, and of the reply against what was sent.
# ---------------------------------------------------------------------------


def validate_questions(questions: object) -> dict[str, dict[str, Any]]:
    """Check the question map against the documented shapes; raise AskRequestError."""
    if not isinstance(questions, Mapping) or not questions:
        raise AskRequestError("questions must be a non-empty object of id -> question")
    checked: dict[str, dict[str, Any]] = {}
    for question_id, question in questions.items():
        if not isinstance(question_id, str) or not question_id.strip() or len(question_id) > 128:
            raise AskRequestError("each question id must be a non-empty string of at most 128 characters")
        if not isinstance(question, Mapping):
            raise AskRequestError(f"question {question_id!r} must be an object")
        kind = question.get("type")
        if kind not in QUESTION_TYPES:
            raise AskRequestError(f"question {question_id!r} type must be one of {', '.join(QUESTION_TYPES)}")
        if not _non_empty_text_value(question.get("instructions")):
            raise AskRequestError(f"question {question_id!r} needs instructions")
        criteria = question.get("criteria")
        if kind == "choice":
            if not isinstance(criteria, Mapping) or not criteria:
                raise AskRequestError(f"choice question {question_id!r} needs criteria: option -> description")
            if len(criteria) > MAX_CHOICE_OPTIONS:
                raise AskRequestError(f"choice question {question_id!r} has more than {MAX_CHOICE_OPTIONS} options")
        elif kind == "score":
            if not isinstance(criteria, list) or not MIN_SCORE_LEVELS <= len(criteria) <= MAX_SCORE_LEVELS:
                raise AskRequestError(
                    f"score question {question_id!r} needs {MIN_SCORE_LEVELS} to {MAX_SCORE_LEVELS} ordered levels"
                )
        elif criteria is not None:
            if not isinstance(criteria, Mapping) or set(criteria) - {"true", "false"}:
                raise AskRequestError(f"noul question {question_id!r} criteria may only carry true and false")
        checked[question_id] = dict(question)
    return checked


def _non_empty_text_value(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, list)):
        return bool(value)
    return False


def validate_state(state: object) -> None:
    if isinstance(state, str):
        if not state.strip():
            raise AskRequestError("state must not be empty")
        return
    if isinstance(state, (Mapping, list)):
        if not state:
            raise AskRequestError("state must not be empty")
        return
    raise AskRequestError("state must be a string, an object, or an array")


class MalformedReply(ValueError):
    """A 200 whose body does not answer exactly what was asked."""


def validate_reply(questions: Mapping[str, Mapping[str, Any]], reply: Mapping[str, Any]) -> dict[str, Any]:
    """Return `{answers, usage, served_model}` or raise MalformedReply.

    A partial answer set is never an answer: every sent id must come back,
    nothing else may, every type must match, and every number must be finite
    and in range.
    """
    answers = reply.get("answers")
    if not isinstance(answers, Mapping):
        raise MalformedReply("answers is missing")
    if set(answers) != set(questions):
        raise MalformedReply("answer ids do not equal the question ids that were sent")
    checked: dict[str, dict[str, Any]] = {}
    for question_id, question in questions.items():
        answer = answers[question_id]
        if not isinstance(answer, Mapping) or answer.get("type") != question.get("type"):
            raise MalformedReply(f"answer {question_id!r} has the wrong type")
        kind = question["type"]
        if kind == "noul":
            checked[question_id] = {"type": "noul", "noul": _unit(answer.get("noul"), question_id)}
        elif kind == "choice":
            options = [str(option) for option in question["criteria"]]
            choice = answer.get("choice")
            if choice not in options:
                raise MalformedReply(f"answer {question_id!r} chose an option that was not sent")
            probabilities = _probability_map(answer.get("probabilities"), options, question_id)
            checked[question_id] = {
                "type": "choice",
                "choice": choice,
                "probabilities": probabilities,
                "confidence": _unit(answer.get("confidence"), question_id),
            }
        else:
            levels = len(question["criteria"])
            score = answer.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                raise MalformedReply(f"answer {question_id!r} score is not a number")
            if not 0 <= score <= levels - 1:
                raise MalformedReply(f"answer {question_id!r} score is outside the sent levels")
            probabilities = _probability_map(
                answer.get("probabilities"), [str(level) for level in range(levels)], question_id
            )
            checked[question_id] = {
                "type": "score",
                "score": score,
                "probabilities": probabilities,
                "confidence": _unit(answer.get("confidence"), question_id),
            }
    usage = reply.get("usage")
    if not isinstance(usage, Mapping):
        raise MalformedReply("usage is missing")
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    for value in (input_tokens, output_tokens):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MalformedReply("usage tokens must be non-negative integers")
    gateway_cost = usage.get("cost")
    if isinstance(gateway_cost, bool) or not isinstance(gateway_cost, (int, float)) or not math.isfinite(gateway_cost):
        gateway_cost = None
    served = reply.get("model")
    return {
        "answers": checked,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "gateway_cost": gateway_cost},
        # Bounded here; `safe_served_model` scrubs the key before it is shown.
        "served_model": str(served)[: MAX_SERVED_MODEL_CHARS * 4] if isinstance(served, str) else "",
    }


def _unit(value: object, question_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MalformedReply(f"answer {question_id!r} carries a non-number")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise MalformedReply(f"answer {question_id!r} carries a number outside [0, 1]")
    return number


def _probability_map(value: object, keys: list[str], question_id: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise MalformedReply(f"answer {question_id!r} probabilities do not name exactly the sent options")
    return {key: _unit(value[key], question_id) for key in keys}


def cost_for(
    route: str,
    usage: Mapping[str, Any],
    *,
    endpoint_url: str | None = None,
) -> dict[str, Any]:
    """Cost of one answered ask, with where the number came from; never a silent 0."""
    gateway_cost = usage.get("gateway_cost")
    if gateway_cost is not None:
        return {"cost_usd": float(gateway_cost), "cost_source": "reported_by_gateway", "price_read_on": PRICE_READ_ON}
    if route == ROUTE_OPENROUTER or (
        route == ROUTE_TYPESAFE and endpoint_url and endpoint_url != ROUTES[ROUTE_TYPESAFE][0]
    ):
        return {"cost_usd": None, "cost_source": "unknown", "price_read_on": PRICE_READ_ON}
    tokens = usage.get("input_tokens")
    if not isinstance(tokens, int):
        return {"cost_usd": None, "cost_source": "unknown", "price_read_on": PRICE_READ_ON}
    return {
        "cost_usd": round(tokens * INPUT_PRICE_USD_PER_MTOK / 1_000_000, 9),
        "cost_source": "estimated_from_list_price",
        "price_read_on": PRICE_READ_ON,
    }


__all__ = [
    "ASK_STATUSES",
    "AskRequestError",
    "DEFAULT_MODEL",
    "FIRST_PARTY_MODEL_IDS",
    "INPUT_PRICE_USD_PER_MTOK",
    "MAX_REQUEST_BYTES",
    "MAX_RESPONSE_BYTES",
    "MalformedReply",
    "OPENROUTER_ONLY_MODEL_IDS",
    "PINNED_MODEL_BY_ROUTE",
    "RETRYABLE_STATUSES",
    "ROUTES",
    "ROUTE_OPENROUTER",
    "ROUTE_TYPESAFE",
    "SUCCESS_STATUS",
    "TransportReply",
    "build_request_body",
    "carries_key_fragment",
    "cost_for",
    "safe_served_model",
    "scrub_key",
    "send_ask",
    "validate_questions",
    "validate_reply",
    "validate_state",
]
