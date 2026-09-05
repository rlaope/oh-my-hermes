"""Safety classification for memory governance (internal module).

Deterministic patterns for protected values, raw logs/transcripts, temporary
progress, and imperative prompt-injection-shaped content.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping


_BLOCKED_PATTERNS = (
    re.compile(r"password\s*=", re.IGNORECASE),
    re.compile(r"secret\s*=", re.IGNORECASE),
    re.compile(r"token\s*=", re.IGNORECASE),
    # Secret-token hyphen compounds (e.g. token-secret, secret-token,
    # abc-secret-token). Keep this narrow so ordinary prose such as
    # "token-based parsing" remains usable.
    re.compile(
        r"(?:password|passwd|secret|token|key)s?-(?:password|passwd|secret|token|key)s?(?![A-Za-z0-9])",
        re.IGNORECASE,
    ),
    re.compile(r"api[_-]key", re.IGNORECASE),
    re.compile(r"auth[_-]header", re.IGNORECASE),
    re.compile(r"Bearer\s+", re.IGNORECASE),
    # High-confidence credential formats that carry no descriptive keyword.
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", re.IGNORECASE),
    re.compile(r"\b(?:gh[oprsu]|github_pat|glpat)[_-][A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"\bhf_[A-Za-z0-9]{16,}\b", re.IGNORECASE),
    re.compile(r"\bnpm_[A-Za-z0-9]{16,}\b", re.IGNORECASE),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b", re.IGNORECASE),
    re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),
    re.compile(r"\bxox[a-z]?-[A-Za-z0-9-]{16,}\b", re.IGNORECASE),
    re.compile(r"\b[a-z][a-z0-9+.-]{1,31}://[^/\s:@]+:[^@\s/]+@", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE),
)

_CREDENTIAL_REVIEW_PATTERN = re.compile(
    r"\b(?:credential|session|access|key|access[_ -]?token|private[_ -]?key|secret|token|api[_ -]?key)\s*[:=]\s*\S{12,}",
    re.IGNORECASE,
)
_NEEDS_REVIEW_PATTERNS = (
    re.compile(r"ignore\s+previous", re.IGNORECASE),
    re.compile(r"reveal\s+the\s+system\s+prompt", re.IGNORECASE),
    re.compile(r"disregard\s+instructions", re.IGNORECASE),
    re.compile(r"this\s+is\s+temporary", re.IGNORECASE),
    re.compile(r"workaround\s+while", re.IGNORECASE),
    re.compile(r"(temporary|temp|hack|quick\s+fix)\s+", re.IGNORECASE),
    # A credential-like value with an unknown prefix is not auto-safe. The
    # character-class and uniqueness checks below avoid treating normal prose
    # as an opaque value while keeping this gate deterministic.
    _CREDENTIAL_REVIEW_PATTERN,
)
_OPAQUE_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/=_-]{32,}(?![A-Za-z0-9])")
_HEX_DIGEST_PATTERN = re.compile(
    r"(?:[0-9A-Fa-f]{32}|[0-9A-Fa-f]{40}|[0-9A-Fa-f]{56}|[0-9A-Fa-f]{64}|[0-9A-Fa-f]{96}|[0-9A-Fa-f]{128})"
)
_UUID_PATTERN = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[1-8][0-9A-Fa-f]{3}-[89ABab][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}"
)
_DIGEST_ASSIGNMENT_PATTERN = re.compile(
    r"(?:md5|sha(?:1|224|256|384|512))=(?:[0-9A-Fa-f]{32}|[0-9A-Fa-f]{40}|[0-9A-Fa-f]{56}|[0-9A-Fa-f]{64}|[0-9A-Fa-f]{96}|[0-9A-Fa-f]{128})",
    re.IGNORECASE,
)
_VERSIONED_CAMEL_CASE_IDENTIFIER_PATTERN = re.compile(
    r"(?:(?:[A-Z]{2,}(?=[A-Z][a-z]{2,}))|(?:[A-Z][a-z]{2,}(?:\d+)?)|(?:[A-Z]\d+)){2,}"
)
_WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^(?:[A-Za-z]:\\|\\\\)[^\r\n]+$")
_SAFE_DIGEST_QUERY_KEYS = frozenset(
    {"artifact", "artifact_id", "checksum", "commit", "digest", "hash", "id", "rev", "revision", "sha", "sha1", "sha224", "sha256", "sha384", "sha512"}
)
_SAFE_REASON_SEGMENT = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _looks_like_structured_identifier(segment: str) -> bool:
    return bool(_VERSIONED_CAMEL_CASE_IDENTIFIER_PATTERN.fullmatch(segment)) or bool(
        re.fullmatch(r"[A-Za-z][A-Za-z0-9]+", segment)
        and any(char.isupper() for char in segment)
        and len(re.findall(r"[a-z]{2,}", segment)) >= 2
    )


def _looks_like_safe_path_segment(segment: str) -> bool:
    if " " in segment:
        words = segment.split()
        return bool(words) and all(_looks_like_safe_path_segment(word) for word in words)
    stem, dot, suffix = segment.rpartition(".")
    if dot and suffix and re.fullmatch(r"[a-z0-9]{1,16}", suffix) and (
        _looks_like_structured_identifier(stem)
        or bool(re.fullmatch(r"[A-Z][A-Z0-9_]{1,31}", stem))
    ):
        return True
    if (
        re.fullmatch(r"\.?[a-z0-9][a-z0-9._-]*", segment)
        or re.fullmatch(r"[A-Z][a-z]{2,}", segment)
        or re.fullmatch(r"[A-Z]", segment)
        or _HEX_DIGEST_PATTERN.fullmatch(segment)
        or _looks_like_structured_identifier(segment)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d+Z-[a-z0-9-]+(?:\.[a-z0-9]+)?", segment)
    ):
        return True
    parts = segment.split("-")
    return len(parts) > 1 and all(
        bool(re.fullmatch(r"[a-z0-9][a-z0-9._]*", part))
        or _looks_like_structured_identifier(part)
        for part in parts
    )


def _looks_like_safe_path_token(token: str) -> bool:
    if "/" not in token or any(char in "+=" for char in token):
        return False
    segments = [segment for segment in token.split("/") if segment]
    return len(segments) >= 2 and all(_looks_like_safe_path_segment(segment) for segment in segments)


def _looks_like_safe_windows_path(content: str) -> bool:
    if not _WINDOWS_ABSOLUTE_PATH_PATTERN.fullmatch(content) or any(char in "+=" for char in content):
        return False
    segments = [segment for segment in content.split("\\") if segment and not re.fullmatch(r"[A-Za-z]:", segment)]
    return bool(segments) and all(_looks_like_safe_path_segment(segment) for segment in segments)


def _looks_like_safe_digest_query_token(token: str, content: str) -> bool:
    if "://" not in content or token.count("=") != 1:
        return False
    key, value = token.split("=", 1)
    return key.lower() in _SAFE_DIGEST_QUERY_KEYS and bool(_HEX_DIGEST_PATTERN.fullmatch(value))


def _has_opaque_character_mix(token: str) -> bool:
    has_lower = any(char.islower() for char in token)
    has_upper = any(char.isupper() for char in token)
    has_digit = any(char.isdigit() for char in token)
    has_encoding_punctuation = any(char in "+=" for char in token)
    return (has_lower and has_upper and (has_digit or ("_" in token and "-" in token))) or (
        has_encoding_punctuation
        and sum((has_lower, has_upper, has_digit, has_encoding_punctuation)) >= 3
    )


def _windows_path_has_split_opaque_value(content: str) -> bool:
    unsafe_run: list[str] = []
    for segment in (
        segment for segment in content.split("\\") if segment and not re.fullmatch(r"[A-Za-z]:", segment)
    ):
        if _looks_like_safe_path_segment(segment):
            if _has_opaque_character_mix("".join(unsafe_run)):
                return True
            unsafe_run = []
        else:
            unsafe_run.append(segment)
    return _has_opaque_character_mix("".join(unsafe_run))


def _looks_like_opaque_token(content: str) -> bool:
    """Recognize encoded opaque values without consuming common identifiers."""
    windows_path = bool(_WINDOWS_ABSOLUTE_PATH_PATTERN.fullmatch(content))
    if windows_path and _windows_path_has_split_opaque_value(content):
        return True
    for match in _OPAQUE_TOKEN_PATTERN.finditer(content):
        token = match.group(0)
        # Common immutable identifiers and explicit digest assignments are
        # evidence metadata, not credential evidence. A trailing Base64
        # padding marker is not an assignment and must remain review-gated.
        if (
            windows_path
            or _HEX_DIGEST_PATTERN.fullmatch(token)
            or _UUID_PATTERN.fullmatch(token)
            or _DIGEST_ASSIGNMENT_PATTERN.fullmatch(token)
            or _VERSIONED_CAMEL_CASE_IDENTIFIER_PATTERN.fullmatch(token)
            or _looks_like_safe_path_token(token)
            or _looks_like_safe_digest_query_token(token, content)
        ):
            continue
        # Mixed-case alphanumeric material is a conservative opaque-value
        # signal. Base64 punctuation can substitute for one alphanumeric
        # class, while ordinary lowercase path/package separators do not.
        if _has_opaque_character_mix(token):
            return True
    return False


def contains_credential_like_material(content: str) -> bool:
    """Return whether a value must be masked before it can serialize."""
    if not isinstance(content, str):
        return True
    return (
        any(pattern.search(content) for pattern in _BLOCKED_PATTERNS)
        or bool(_CREDENTIAL_REVIEW_PATTERN.search(content))
        or _looks_like_opaque_token(content)
    )


def _iter_renderable_values(value: object, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        if value:
            yield path, value
        return
    if isinstance(value, Mapping):
        for key, nested in value.items():
            segment = str(key)
            nested_path = f"{path}.{segment}" if _SAFE_REASON_SEGMENT.fullmatch(segment) else path
            if segment:
                yield f"{path}.key", segment
            yield from _iter_renderable_values(nested, nested_path)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            yield from _iter_renderable_values(nested, path)


def classify_memory_admission(content: str) -> dict[str, object]:
    """Classify memory content for safety admission.
    
    Returns a dict with "status" field:
    - "blocked": protected material (passwords, secrets, raw logs, transcripts)
    - "needs_review": ambiguous content (temporary, prompt injection, credentials)
    - "safe": safe to auto-approve
    """
    if not isinstance(content, str):
        return {"status": "blocked"}
    
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(content):
            return {"status": "blocked"}

    for pattern in _NEEDS_REVIEW_PATTERNS:
        if pattern.search(content):
            return {"status": "needs_review"}

    if _looks_like_opaque_token(content):
        return {"status": "needs_review"}

    return {"status": "safe"}


def evaluate_renderable_strings(artifact: dict[str, object]) -> dict[str, object]:
    """Evaluate every artifact field that can reach a memory render surface.

    Returns worst-case result with status and reason_code.
    Fail-closed: any blocked field blocks, any needs_review field needs review.
    """
    prioritized_fields = (
        "summary",
        "value",
        "label",
        "key",
        "source",
        "source_ref",
        "record_type",
        "retention_class",
        "retention",
        "stale_after",
        "time_sensitivity",
        "duplicate_of",
        "safety",
        "created_at",
        "scope",
        "tags",
        "derived_from",
        "source_evidence",
        "perspective",
        "attention",
    )
    renderable_fields = tuple(dict.fromkeys((*prioritized_fields, *(str(key) for key in artifact))))

    worst_status = "safe"
    worst_field = None

    for field in renderable_fields:
        key_status = classify_memory_admission(field).get("status", "safe")
        if key_status == "blocked":
            return {
                "status": "blocked",
                "field": "metadata_key",
                "reason_code": "safety_blocked_in_metadata_key",
            }
        if key_status == "needs_review" and worst_status != "blocked":
            worst_status = "needs_review"
            worst_field = "metadata_key"
        content = artifact.get(field)
        for value_path, value in _iter_renderable_values(content, field):
            result = classify_memory_admission(value)
            status = result.get("status", "safe")

            # Fail closed: blocked > needs_review > safe
            if status == "blocked":
                return {
                    "status": "blocked",
                    "field": value_path,
                    "reason_code": f"safety_blocked_in_{value_path}",
                }
            if status == "needs_review" and worst_status != "blocked":
                worst_status = "needs_review"
                worst_field = value_path

    if worst_status == "needs_review":
        return {
            "status": "needs_review",
            "field": worst_field,
            "reason_code": f"safety_needs_review_in_{worst_field}",
        }

    return {"status": "safe", "reason_code": "eligible"}
