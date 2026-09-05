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
    re.compile(r"\b(?:gh[oprs]|github_pat|glpat|npm|hf)[_-][A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
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


def _looks_like_opaque_token(content: str) -> bool:
    """Recognize unknown long opaque values conservatively for review."""
    for match in _OPAQUE_TOKEN_PATTERN.finditer(content):
        token = match.group(0)
        # Keep ordinary assignment labels and low-entropy hyphenated prose
        # out of the opaque-value heuristic (for example sha256=aaaa... or
        # human-definition-source-only-sentinel).
        if "=" in token:
            continue
        character_classes = sum(
            (
                any(char.islower() for char in token),
                any(char.isupper() for char in token),
                any(char.isdigit() for char in token),
                any(char in "+/=_-" for char in token),
            )
        )
        if character_classes >= 3 or ("_-" not in token and len(set(token)) >= 12):
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
    """Evaluate all renderable string fields (summary, value, label).
    
    Returns worst-case result with status and reason_code.
    Fail-closed: any blocked field blocks, any needs_review fields need review.
    """
    renderable_fields = ["summary", "value", "label"]
    
    worst_status = "safe"
    worst_field = None
    
    for field in renderable_fields:
        content = artifact.get(field)
        if not isinstance(content, str) or not content:
            continue
        
        result = classify_memory_admission(content)
        status = result.get("status", "safe")
        
        # Fail closed: blocked > needs_review > safe
        if status == "blocked":
            return {
                "status": "blocked",
                "field": field,
                "reason_code": f"safety_blocked_in_{field}",
            }
        elif status == "needs_review" and worst_status != "blocked":
            worst_status = "needs_review"
            worst_field = field
    
    if worst_status == "needs_review":
        return {
            "status": "needs_review",
            "field": worst_field,
            "reason_code": f"safety_needs_review_in_{worst_field}",
        }
    
    return {"status": "safe", "reason_code": "eligible"}
