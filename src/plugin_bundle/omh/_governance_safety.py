"""Safety classification for memory governance (internal module).

Deterministic patterns for protected values, raw logs/transcripts, temporary
progress, and imperative prompt-injection-shaped content.
"""

from __future__ import annotations

import re


_BLOCKED_PATTERNS = (
    re.compile(r"password\s*=", re.IGNORECASE),
    re.compile(r"secret\s*=", re.IGNORECASE),
    re.compile(r"token\s*=", re.IGNORECASE),
    # Secret-token hyphen compounds (e.g. token-secret, secret-token,
    # abc-secret-token). Keep this narrow so ordinary prose such as
    # "token-based parsing" remains usable.
    re.compile(
        r"(?:password|passwd|secret|token|key)s?-(?:password|passwd|secret|token|key)s?",
        re.IGNORECASE,
    ),
    re.compile(r"api[_-]key", re.IGNORECASE),
    re.compile(r"auth[_-]header", re.IGNORECASE),
    re.compile(r"Bearer\s+", re.IGNORECASE),
    # High-confidence credential formats that carry no descriptive keyword.
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", re.IGNORECASE),
    re.compile(r"\b(?:gh[oprsu]|github_pat|glpat|hf)[_-][A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    # npm granular/access tokens use the npm_ prefix followed by an opaque
    # payload. Keep ordinary package names such as npm-package-name out of
    # the high-confidence credential rule.
    re.compile(r"\bnpm_[A-Za-z0-9]{32,}\b", re.IGNORECASE),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),
    re.compile(r"\bxox[a-z]?-[A-Za-z0-9-]{16,}\b", re.IGNORECASE),
    re.compile(r"\b[a-z][a-z0-9+.-]{1,31}://[^/\s:@]+:[^@\s/]+@", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE),
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
    re.compile(
        r"\b(?:credential|access[_ -]?token|private[_ -]?key|secret|token|api[_ -]?key)\s*[:=]\s*\S{12,}",
        re.IGNORECASE,
    ),
)
_OPAQUE_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/=_-]{32,}(?![A-Za-z0-9])")
_DIGEST_ASSIGNMENT_PATTERN = re.compile(
    r"(?:md5|sha1|sha224|sha256|sha384|sha512)=[0-9a-f]{32,128}",
    re.IGNORECASE,
)
_HEX_DIGEST_PATTERN = re.compile(r"[0-9a-f]{40,64}", re.IGNORECASE)
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_WORDLIKE_IDENTIFIER_PATTERN = re.compile(r"[a-z]{2,}[A-Z][a-z]{2,}")
_STRUCTURED_IDENTIFIER_PATTERN = re.compile(
    r"^[a-z][a-z0-9]*(?:[-_](?:[a-z][a-z0-9]*|[0-9]+))+$"
)
_CREDENTIALISH_IDENTIFIER_PREFIXES = frozenset(
    {"access", "api", "auth", "credential", "key", "private", "secret", "token"}
)


def _looks_like_structured_identifier(token: str) -> bool:
    """Keep ordinary word/date/build identifiers out of opaque review."""
    if not _STRUCTURED_IDENTIFIER_PATTERN.fullmatch(token):
        return False
    prefix = re.split(r"[-_]", token, maxsplit=1)[0]
    return prefix not in _CREDENTIALISH_IDENTIFIER_PREFIXES


def _looks_like_opaque_token(content: str) -> bool:
    """Recognize unknown long opaque values conservatively for review."""
    for match in _OPAQUE_TOKEN_PATTERN.finditer(content):
        token = match.group(0)
        # Complete digest assignments and common non-secret identifiers are
        # already safe metadata. Do not exempt every value containing "=";
        # padded opaque values such as Base64-like credentials still need
        # review.
        if _DIGEST_ASSIGNMENT_PATTERN.fullmatch(token):
            continue
        if _HEX_DIGEST_PATTERN.fullmatch(token) or _UUID_PATTERN.fullmatch(token):
            continue
        if _looks_like_structured_identifier(token):
            continue
        # Long prose identifiers and CamelCase names are common in project,
        # domain, and handoff metadata. They have no credential-like
        # character mix, so do not let this shared classifier reject them.
        if token.isalpha() and (token.islower() or token.isupper() or _WORDLIKE_IDENTIFIER_PATTERN.search(token)):
            continue
        character_classes = sum(
            (
                any(char.islower() for char in token),
                any(char.isupper() for char in token),
                any(char.isdigit() for char in token),
                any(char in "+/=_-" for char in token),
            )
        )
        if character_classes >= 3 or (not any(char in "_-" for char in token) and len(set(token)) >= 12):
            return True
    return False


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
    """Evaluate every string that can reach a memory-facing surface.
    
    Returns worst-case result with status and reason_code.
    Fail-closed: any blocked field blocks, any needs_review fields need review.
    """
    renderable_fields = [
        "summary",
        "value",
        "label",
        "key",
        "source",
        "source_ref",
        "scope",
        "derived_from",
        "perspective",
    ]
    
    worst_status = "safe"
    worst_field = None
    
    for field in renderable_fields:
        values = artifact.get(field)
        if isinstance(values, str):
            values_to_check = ((field, values),)
        elif field == "scope" and isinstance(values, dict):
            values_to_check = ((field, str(values.get("ref", ""))),)
        elif field == "perspective" and isinstance(values, dict):
            values_to_check = tuple(
                (field, str(values.get(key, ""))) for key in ("observer", "observed") if str(values.get(key, ""))
            )
        elif field == "derived_from" and isinstance(values, (list, tuple)):
            values_to_check = tuple((field, str(value)) for value in values if str(value))
        else:
            values_to_check = ()

        for checked_field, content in values_to_check:
            if not content:
                continue
            result = classify_memory_admission(content)
            status = result.get("status", "safe")

            # Fail closed: blocked > needs_review > safe
            if status == "blocked":
                return {
                    "status": "blocked",
                    "field": checked_field,
                    "reason_code": f"safety_blocked_in_{checked_field}",
                }
            elif status == "needs_review" and worst_status != "blocked":
                worst_status = "needs_review"
                worst_field = checked_field

    tags = artifact.get("tags")
    if isinstance(tags, (list, tuple)):
        for content in (str(value) for value in tags if str(value)):
            result = classify_memory_admission(content)
            status = result.get("status", "safe")
            if status == "blocked":
                return {
                    "status": "blocked",
                    "field": "tags",
                    "reason_code": "safety_blocked_in_tags",
                }
            if status == "needs_review" and worst_status != "blocked":
                worst_status = "needs_review"
                worst_field = "tags"
    
    if worst_status == "needs_review":
        return {
            "status": "needs_review",
            "field": worst_field,
            "reason_code": f"safety_needs_review_in_{worst_field}",
        }
    
    return {"status": "safe", "reason_code": "eligible"}
