"""Safety classification for memory governance (internal module).

Deterministic patterns only, and only for protected values: credential
keywords, the documented bare token shapes, a PEM private-key header, and a
URL carrying inline basic-auth credentials block; temporary progress,
imperative prompt-injection-shaped content, credential-shaped assignments,
and unknown opaque values route to review.

Raw logs and transcripts are deliberately NOT screened here, though the
capture lane refuses them. This function is a shared primitive -- action
gates, handoff manifests, batch identifiers, and reviewer labels all call it,
and several of them turn any non-safe verdict into a raise -- so a line-shape
heuristic placed here would fail a plain note whose lines happen to open with
"Error", "Warning" or "User:", and would fail it by exception. The shape gate
for that material lives beside the path that can afford to refuse:
`_ensure_vocabulary_safe` in `src/workflows/domain_intelligence_admission.py`
matches raw-log markers, three or more full `YYYY-MM-DD HH:MM:SS` line
openings, and an anchored role marker.
"""

from __future__ import annotations

import hashlib
import marshal
import re
import unicodedata
from collections.abc import Iterator, Mapping
from itertools import accumulate


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
    re.compile(r"\brk_(?:live|test)_[A-Za-z0-9]{16,}\b", re.IGNORECASE),
    re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),
    re.compile(r"\bxox[a-z]?-[A-Za-z0-9-]{16,}\b", re.IGNORECASE),
    re.compile(r"\b[a-z][a-z0-9+.-]{1,31}://[^/\s:@]+:[^@\s/]+@", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE),
)

_CREDENTIAL_REVIEW_PATTERN = re.compile(
    r"\b(?:(?:api|access|private|secret)[_ -]?key|(?:session|access)[_ -]?token)\s*[:=]\s*\S{12,}",
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
# French cues for the same two review categories (prompt injection, temporary
# progress), matched on `_folded_text`: accents and case are gone, so
# "précédentes", "PRECEDENTES" and "precedentes" read alike. Every cue names
# the act with at least two words -- a bare "temporaire" or "ignore les
# instructions" is ordinary narration ("le fichier temporaire est supprimé",
# "le linter ignore les instructions de formatage") and stays safe.
_FRENCH_NEEDS_REVIEW_PATTERNS = (
    re.compile(r"\b(?:ignor|oubli)\w*\s+(?:toutes\s+)?(?:les|tes|vos)\s+(?:instructions|consignes)\s+(?:precedentes|anterieures)"),
    re.compile(r"\brevel\w*\s+(?:(?:ton|votre)\s+prompt|le\s+prompt\s+systeme)"),
    re.compile(r"\b(?:c'est|ceci\s+est)\s+temporaire"),
    re.compile(r"\b(?:workaround|contournement|correctif|solution|fix|hack|bricolage|rustine|patch)\s+(?:provisoire|temporaire)"),
    re.compile(r"\bcontournement\s+en\s+attendant"),
)


def _folded_text(content: str) -> str:
    """Lowercase, accent-free, straight-apostrophe form for locale cues."""
    decomposed = unicodedata.normalize("NFKD", content.replace("\u2019", "'"))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower()


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
_IDENTIFIER_COMPONENT_PATTERN = re.compile(
    r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+"
)
_IDENTIFIER_MORPHOLOGY_SUFFIX = re.compile(
    r"(?:ation|ition|sion|tion|ions|ment|ness|ity|ence|ance|able|ible|ship|form|ount|point|ish|ary|ives|ents|out|er|or|al|ic|ive|ous|ful|less|ed|ing)$",
    re.IGNORECASE,
)
_SEMANTIC_IDENTIFIER_CONNECTORS = frozenset(
    {"a", "an", "and", "as", "at", "by", "for", "from", "in", "is", "not", "of", "on", "or", "the", "to", "v", "with"}
)
_SEMANTIC_IDENTIFIER_ACRONYMS = frozenset(
    {
        "API",
        "CI",
        "CLI",
        "CPU",
        "CSS",
        "DCO",
        "DNS",
        "DOM",
        "FAQ",
        "FQDN",
        "GPU",
        "HTML",
        "HTTP",
        "HTTPS",
        "ID",
        "IO",
        "JSON",
        "JSONRPC",
        "JWT",
        "LLM",
        "MCP",
        "OMH",
        "OS",
        "PR",
        "RPC",
        "SDK",
        "SHA",
        "SQL",
        "SSH",
        "TLS",
        "TOML",
        "TTL",
        "UI",
        "ULW",
        "URL",
        "UUID",
        "UX",
        "W3C",
        "XML",
        "YAML",
    }
)
_COMMON_IDENTIFIER_BIGRAMS = frozenset(
    "AC AD AG AI AL AN AP AR AS AT BE BI BO BR CA CE CH CK CO CT DA DE DI DO ED EE EL EM EN ER ES ET EV EX FI FO GE GL GR HA HE HI HO IC ID IE IL IM IN IO IS IT KE LA LD LE LI LL LO LY MA ME MI MO NA NC ND NE NG NI NO NS NT OD OF OL OM ON OP OR OT OU OW PA PE PI PL PO PR QU RA RC RE RI RO RS RT SE SH SI SO SS ST SU TA TE TH TI TO TR TS TT TW UL UN UP UR US UT VE WA WE WH WI YO".split()
)
_SEMANTIC_IDENTIFIER_WORDS = frozenset(
    {
        "account",
        "action",
        "adapter",
        "after",
        "agent",
        "alice",
        "application",
        "artifact",
        "authenticated",
        "batch",
        "block",
        "builder",
        "cache",
        "candidate",
        "canonical",
        "capability",
        "client",
        "command",
        "component",
        "configuration",
        "connection",
        "context",
        "contract",
        "controller",
        "data",
        "decision",
        "declared",
        "deterministic",
        "directory",
        "dispatcher",
        "document",
        "effect",
        "engine",
        "end",
        "english",
        "error",
        "evaluator",
        "event",
        "evidence",
        "execution",
        "executor",
        "factory",
        "failure",
        "file",
        "finder",
        "gateway",
        "handle",
        "handler",
        "hermes",
        "identifier",
        "index",
        "input",
        "interview",
        "job",
        "lifecycle",
        "loader",
        "maintainer",
        "manager",
        "memory",
        "metadata",
        "migration",
        "model",
        "observation",
        "object",
        "operation",
        "output",
        "package",
        "parser",
        "path",
        "platform",
        "policy",
        "project",
        "projections",
        "protocol",
        "provenance",
        "provider",
        "read",
        "reader",
        "reading",
        "record",
        "recommendations",
        "recoverable",
        "recovery",
        "reference",
        "registry",
        "request",
        "response",
        "reviewer",
        "router",
        "rhythm",
        "runtime",
        "safety",
        "schema",
        "seconds",
        "server",
        "service",
        "session",
        "shipped",
        "source",
        "stale",
        "state",
        "status",
        "store",
        "stream",
        "system",
        "target",
        "task",
        "terminal",
        "test",
        "tests",
        "thread",
        "token",
        "tool",
        "update",
        "user",
        "validator",
        "value",
        "version",
        "worker",
        "workflow",
        "writer",
    }
)
_UPPER_SNAKE_IDENTIFIER_PATTERN = re.compile(r"[A-Z][A-Z0-9]{1,15}(?:_[A-Z][A-Z0-9]{1,15}){2,}")
_SEPARATOR_SPLIT_OPAQUE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z0-9]{4,20}[./\\ _-]){1,}[A-Za-z0-9]{4,20}(?![A-Za-z0-9])"
)
# Machine-generated names whose separators are not split points. A window
# that overlaps one is not read as a split value; windows beside it still are.
_GENERATED_NAME_PATTERNS = (
    # An RFC 4122 UUID, which the opaque-token check already exempts whole.
    _UUID_PATTERN,
    # A Python `tempfile` default name: "tmp" plus eight characters, as a
    # whole path segment or word.
    re.compile(r"(?<![^\s/\\])tmp[a-z0-9_]{8}(?![^\s/\\])"),
    # A Hermes session id: YYYYMMDD_HHMMSS_ plus six hex characters.
    re.compile(r"\d{8}_\d{6}_[0-9a-f]{6}"),
)
_COMPACT_SPLIT_CREDENTIAL_PATTERN = re.compile(
    "(?:" + "|".join(
        (
            r"(?:AKIA|ASIA)[A-Z0-9]{16}",
            r"(?:gh[oprsu]|githubpat|glpat)[A-Za-z0-9]{16,}",
            r"hf[A-Za-z0-9]{16,}",
            r"npm[A-Za-z0-9]{16,}",
            r"sk(?:proj)?[A-Za-z0-9]{16,}",
            r"rk(?:live|test)[A-Za-z0-9]{16,}",
            r"sk(?:live|test)[A-Za-z0-9]{16,}",
            r"ya29[A-Za-z0-9]{20,}",
            r"AIza[A-Za-z0-9]{20,}",
            r"xox[a-z]?[A-Za-z0-9]{16,}",
        )
    ) + ")",
    re.IGNORECASE,
)
_CREDENTIAL_SPLIT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z0-9_-]{2,20}[./\\-]){1,}[A-Za-z0-9_-]{2,20}(?![A-Za-z0-9])"
)
_GOOGLE_SPLIT_CREDENTIAL_PATTERN = re.compile(
    r"\b(?:ya29\.|AIza)(?:[./\\][A-Za-z0-9_-]{2,20})+",
    re.IGNORECASE,
)
_CREDENTIAL_SPLIT_PREFIX_PATTERN = re.compile(
    r"(?:AKIA|ASIA|gh[oprsu][_-]|github_|glpat-|hf_|npm_|sk[-_]|rk_|ya29\.|AIza|xox[a-z]?-)",
    re.IGNORECASE,
)
_WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^(?:[A-Za-z]:\\|\\\\)[^\r\n]+$")
_SAFE_SOURCE_REVISION_URL_PATTERN = re.compile(
    r"https?://[^/\s]+(?:/[^/\s]+)*/(?:blob|tree)/[0-9A-Fa-f]{7,40}/",
    re.IGNORECASE,
)
_SAFE_TIMESTAMP_IDENTIFIER_PATTERN = re.compile(r"(?:\d{8}|\d{4}-\d{2}-\d{2})T\d+Z-[a-z0-9-]+(?:\.[a-z0-9]{1,16})?")
_SAFE_DIGEST_QUERY_KEYS = frozenset(
    {"artifact", "artifact_id", "checksum", "commit", "digest", "hash", "id", "rev", "revision", "sha", "sha1", "sha224", "sha256", "sha384", "sha512"}
)
_SAFE_REASON_SEGMENT = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _looks_like_structured_identifier(segment: str) -> bool:
    if not segment.isalnum() or not any(char.islower() for char in segment) or not any(
        char.isupper() for char in segment
    ):
        return False
    components = _IDENTIFIER_COMPONENT_PATTERN.findall(segment)
    alpha_components = [component for component in components if component.isalpha()]
    title_components = [
        component
        for component in alpha_components
        if re.fullmatch(r"[A-Z][a-z]{2,}", component)
    ]
    return (
        "".join(components) == segment
        and len(alpha_components) >= 3
        and len(title_components) >= 2
        and all(
            component.isdigit()
            or component.isupper()
            or bool(re.fullmatch(r"[A-Z][a-z]+|[a-z]{2,}", component))
            for component in components
        )
        and (
            sum(bool(_IDENTIFIER_MORPHOLOGY_SUFFIX.search(component)) for component in title_components) >= 2
            or title_components[-1] in {"Test", "Tests", "Setup", "Maestro"}
            or sum(len(component) >= 4 for component in title_components) >= 5
            or (
                sum(len(component) >= 4 for component in title_components) >= 4
                and any(len(component) == 3 for component in title_components)
            )
        )
    )

def _looks_like_semantic_upper_identifier_word(part: str) -> bool:
    if part.isdigit() or part in _SEMANTIC_IDENTIFIER_ACRONYMS:
        return True
    if not part.isalpha() or not part.isupper():
        return False
    if part.lower() in _SEMANTIC_IDENTIFIER_CONNECTORS or part.lower() in _SEMANTIC_IDENTIFIER_WORDS:
        return True
    if not any(char in "AEIOUY" for char in part):
        return False
    bigram_count = sum(
        part[index : index + 2] in _COMMON_IDENTIFIER_BIGRAMS
        for index in range(len(part) - 1)
    )
    return bigram_count * 4 >= len(part) - 1


def _looks_like_semantic_upper_snake_identifier(segment: str) -> bool:
    if not _UPPER_SNAKE_IDENTIFIER_PATTERN.fullmatch(segment):
        return False
    return all(_looks_like_semantic_upper_identifier_word(part) for part in segment.split("_"))


def _looks_like_path_identifier(segment: str) -> bool:
    return _looks_like_structured_identifier(segment) or bool(
        re.fullmatch(r"[A-Za-z][A-Za-z0-9]+", segment)
        and any(char.islower() for char in segment)
        and any(char.isupper() for char in segment)
    )


def _looks_like_safe_path_segment(segment: str) -> bool:
    if " " in segment:
        words = segment.split()
        return bool(words) and all(_looks_like_safe_path_segment(word) for word in words)
    # A leading run of "_" or "-" (`_temp`, `__pycache__`, an encoded
    # `-Users-name-project` directory) carries nothing; the rest is judged
    # by the same rules as a segment written without it. No part of the rest
    # may carry an opaque character mix (upper and lower case with digits)
    # either: a base64url secret split at "/" can
    # leave a fragment that opens with "_" or "-" (`.../_Ij6Kl7Mn8Op9/...`),
    # and "/_" is two separators, so the split-value check never joins it.
    if segment.startswith(("_", "-")):
        rest = segment.lstrip("_-")
        return (
            bool(rest)
            and _looks_like_safe_path_segment(rest)
            and not any(_has_opaque_character_mix(part) for part in re.split(r"[-_.]", rest))
        )
    if _UUID_PATTERN.fullmatch(segment):
        return True
    stem, dot, suffix = segment.rpartition(".")
    if dot and suffix and re.fullmatch(r"[a-z0-9]{1,16}", suffix) and (
        _looks_like_path_identifier(stem)
        or bool(re.fullmatch(r"[A-Z][A-Z0-9_]{1,31}", stem))
    ):
        return True
    if (
        re.fullmatch(r"\.?[a-z0-9][a-z0-9._-]*", segment)
        or re.fullmatch(r"[A-Z][a-z]{2,}", segment)
        or re.fullmatch(r"[A-Z]", segment)
        or re.fullmatch(r"[A-Z][A-Z0-9_]{1,31}", segment)
        or _HEX_DIGEST_PATTERN.fullmatch(segment)
        or _looks_like_path_identifier(segment)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d+Z-[a-z0-9-]+(?:\.[a-z0-9]+)?", segment)
    ):
        return True
    parts = segment.split("-")
    return len(parts) > 1 and all(
        bool(re.fullmatch(r"[a-z0-9][a-z0-9._]*", part))
        or _looks_like_path_identifier(part)
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
    return bool(segments) and all(
        _looks_like_safe_path_segment(segment)
        and (
            bool(re.fullmatch(r"[A-Z][a-z]+\d*", segment))
            or not _has_opaque_character_mix(segment)
        )
        # Judged without a leading "_"/"-" run, which the safe-segment rule
        # above drops from the segment and from each of its words: the mix
        # check reads only all-alphanumeric values.
        and not _has_single_case_alphanumeric_opaque_mix(segment.lstrip("_-"))
        and not any(
            _has_single_case_alphanumeric_opaque_mix(word.lstrip("_-"))
            for word in segment.split()
            if word.startswith(("_", "-"))
        )
        and not _has_separator_split_opaque_value(segment)
        for segment in segments
    )


def _looks_like_safe_digest_query_token(token: str, content: str) -> bool:
    if "://" not in content or token.count("=") != 1:
        return False
    key, value = token.split("=", 1)
    return key.lower() in _SAFE_DIGEST_QUERY_KEYS and bool(_HEX_DIGEST_PATTERN.fullmatch(value))


def _has_opaque_character_mix(token: str) -> bool:
    if "=" in token:
        key, value = token.split("=", 1)
        if "/" in value or (
            re.fullmatch(r"[a-z][a-z0-9_]*", key)
            and re.fullmatch(r"[A-Z][A-Z0-9_]*", value)
        ) or (
            re.fullmatch(r"[A-Z][A-Z0-9_]*", key)
            and re.fullmatch(r"[a-z][a-z0-9-]*", value)
        ):
            return False
    has_lower = any(char.islower() for char in token)
    has_upper = any(char.isupper() for char in token)
    has_digit = any(char.isdigit() for char in token)
    has_encoding_punctuation = "+" in token or token.endswith("=")
    if has_lower and has_upper and token.isalpha():
        return len(token) >= 32
    return (has_lower and has_upper and (has_digit or ("_" in token and "-" in token))) or (
        has_encoding_punctuation
        and sum((has_lower, has_upper, has_digit, has_encoding_punctuation)) >= 3
    )


def _has_single_case_alphanumeric_opaque_mix(token: str) -> bool:
    """Catch base-encoded values that do not mix letter case.

    Long semantic identifiers commonly contain one version run (for example
    ``project2026memoryhardeningidentifier``). Opaque encodings instead tend
    to alternate letter and digit runs throughout the value, so require both
    repeated transitions and several digits before review-gating a single-case
    token.
    """
    if not token.isalnum():
        return False
    letters = [char for char in token if char.isalpha()]
    digits = [char for char in token if char.isdigit()]
    if not letters:
        return False
    if any(char.islower() for char in letters) and any(char.isupper() for char in letters):
        return False
    if not digits:
        if all(char.isupper() for char in letters):
            return len(token) >= 32
        return len(token) >= 32 and len(set(token)) >= 8
    if len(token) >= 32 and all(char.isupper() for char in letters):
        return True
    if len(digits) < 3:
        return False
    transitions = sum(
        left.isdigit() != right.isdigit()
        for left, right in zip(token, token[1:])
    )
    return transitions >= 8


def _has_embedded_opaque_value(content: str) -> bool:
    """Detect opaque runs before a path or URL container can exempt them."""
    for match in re.finditer(r"[A-Za-z0-9]{32,}", content):
        segment = match.group(0)
        if (
            _HEX_DIGEST_PATTERN.fullmatch(segment)
            or _SAFE_SOURCE_REVISION_URL_PATTERN.search(content)
            or _looks_like_structured_identifier(segment)
        ):
            continue
        if _has_opaque_character_mix(segment) or _has_single_case_alphanumeric_opaque_mix(segment):
            return True
    return False


def _has_separator_split_blocked_credential(content: str) -> bool:
    """Recognize known credential prefixes after separator-split fragments."""
    if _GOOGLE_SPLIT_CREDENTIAL_PATTERN.search(content):
        return True
    for match in _CREDENTIAL_SPLIT_PATTERN.finditer(content):
        matched = match.group(0)
        if not _CREDENTIAL_SPLIT_PREFIX_PATTERN.match(matched):
            continue
        fragments = re.findall(r"[A-Za-z0-9]+", matched)
        for start in range(len(fragments)):
            for end in range(start + 2, min(len(fragments), start + 8) + 1):
                compact = "".join(fragments[start:end])
                if _COMPACT_SPLIT_CREDENTIAL_PATTERN.fullmatch(compact):
                    return True
    return False


def _generated_name_coverage(content: str) -> list[int] | None:
    """Prefix counts of characters inside a generated name, or None when there is none.

    ``coverage[end] - coverage[start]`` is how many characters of
    ``content[start:end]`` lie inside one, so a window's overlap costs one
    subtraction however many names the value holds.
    """
    inside = bytearray(len(content))
    for pattern in _GENERATED_NAME_PATTERNS:
        for found in pattern.finditer(content):
            start, end = found.span()
            if (start and content[start - 1].isalnum()) or (end < len(content) and content[end].isalnum()):
                continue
            inside[start:end] = b"\x01" * (end - start)
    if not any(inside):
        return None
    return list(accumulate(inside, initial=0))


def _has_separator_split_opaque_value(content: str) -> bool:
    """Catch one opaque value split into path or package fragments."""
    generated = _generated_name_coverage(content)
    for match in _SEPARATOR_SPLIT_OPAQUE_PATTERN.finditer(content):
        matched = match.group(0)
        fragment_matches = list(re.finditer(r"[A-Za-z0-9]+", matched))
        fragments = [fragment.group(0) for fragment in fragment_matches]
        if _looks_like_structured_identifier("".join(fragments)) or (
            " " in matched and all(_looks_like_semantic_upper_identifier_word(fragment) for fragment in fragments)
        ):
            continue
        semantic_snake_spans = [
            snake.span()
            for snake in _UPPER_SNAKE_IDENTIFIER_PATTERN.finditer(matched)
            if _looks_like_semantic_upper_snake_identifier(snake.group(0))
        ]
        for start in range(len(fragments)):
            for end in range(start + 2, min(len(fragments), start + 8) + 1):
                window = fragments[start:end]
                lengths = [len(fragment) for fragment in window]
                combined = "".join(window)
                chunked = (len(window) >= 3 and min(lengths) >= 8) or (
                    len(window) >= 4 and min(lengths) >= 4
                ) or (
                    len(window) >= 2 and min(lengths) >= 12
                )
                if len(combined) < 32 or not chunked:
                    continue
                if _HEX_DIGEST_PATTERN.fullmatch(combined) or _looks_like_structured_identifier(combined):
                    continue
                window_start = fragment_matches[start].start()
                window_end = fragment_matches[end - 1].end()
                semantic_snake_overlap = any(
                    window_start < snake_end and snake_start < window_end
                    for snake_start, snake_end in semantic_snake_spans
                )
                if any(_looks_like_structured_identifier(fragment) for fragment in window) or semantic_snake_overlap:
                    continue
                if generated and generated[match.start() + window_end] > generated[match.start() + window_start]:
                    continue
                mixed = _has_opaque_character_mix(combined)
                uppercase_fragments = sum(any(char.isupper() for char in fragment) for fragment in window)
                every_fragment_has_uppercase = uppercase_fragments == len(window)
                # Digit/letter alternation is a split value's signal only when
                # it spans fragments: one numbered segment among words (a
                # `prefix-xxxxxxxx` temp directory) alternates on its own.
                digit_fragments = sum(any(char.isdigit() for char in fragment) for fragment in window)
                single_case_with_signal = _has_single_case_alphanumeric_opaque_mix(combined) and (
                    combined.isupper() or digit_fragments >= 2
                )
                lowercase_encoded_split = (
                    combined.islower()
                    and combined.isalpha()
                    and len(set(combined)) * 100 >= len(combined) * 70
                )
                if (mixed and every_fragment_has_uppercase) or single_case_with_signal or lowercase_encoded_split:
                    return True
    return False


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
    if _looks_like_safe_windows_path(content):
        return False
    if _has_embedded_opaque_value(content) or _has_separator_split_opaque_value(content):
        return True
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
            or _SAFE_TIMESTAMP_IDENTIFIER_PATTERN.fullmatch(token)
            or _HEX_DIGEST_PATTERN.fullmatch(token)
            or _UUID_PATTERN.fullmatch(token)
            or _DIGEST_ASSIGNMENT_PATTERN.fullmatch(token)
            or _looks_like_structured_identifier(token)
            or _looks_like_safe_path_token(token)
            or _looks_like_safe_digest_query_token(token, content)
        ):
            continue
        # Mixed-case alphanumeric material is a conservative opaque-value
        # signal. Base64 punctuation can substitute for one alphanumeric
        # class, while ordinary lowercase path/package separators do not.
        if _has_opaque_character_mix(token) or _has_single_case_alphanumeric_opaque_mix(token):
            return True
    return False


# `contains_credential_like_material` verdicts for short strings. A live recall
# render redacts every string of every candidate record's evaluation metadata
# (ids, digests, timestamps, tags: about 400 strings for 39 records), the same
# strings every turn, and once the record verdicts below were cached this scan
# was a third of a render. The verdict is a function of the string alone, so
# the string itself is the key: exact, and an exact `str` only. Longer text is
# scanned every time, so what this keeps stays small; cleared whole when full.
_CREDENTIAL_MEMO_MAX_CHARS = 256
_CREDENTIAL_MEMO_LIMIT = 8192
_credential_verdicts: dict[str, bool] = {}


def contains_credential_like_material(content: str) -> bool:
    """Return whether a value must be masked before it can serialize."""
    if not isinstance(content, str):
        return True
    if type(content) is not str or len(content) > _CREDENTIAL_MEMO_MAX_CHARS:
        return _credential_like(content)
    verdict = _credential_verdicts.get(content)
    if verdict is None:
        verdict = _credential_like(content)
        if len(_credential_verdicts) >= _CREDENTIAL_MEMO_LIMIT:
            _credential_verdicts.clear()
        _credential_verdicts[content] = verdict
    return verdict


def _credential_like(content: str) -> bool:
    return (
        any(pattern.search(content) for pattern in _BLOCKED_PATTERNS)
        or _has_separator_split_blocked_credential(content)
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
    - "blocked": protected values (credential keywords, the documented bare
      token shapes, a PEM private-key header, inline basic-auth in a URL)
    - "needs_review": ambiguous content (temporary progress, prompt injection,
      credential-shaped assignments, unknown opaque values)
    - "safe": everything else, including pasted logs and transcripts -- see the
      module docstring for where that shape is screened instead
    """
    if not isinstance(content, str):
        return {"status": "blocked"}
    
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(content):
            return {"status": "blocked"}
    if _has_separator_split_blocked_credential(content):
        return {"status": "blocked"}

    for pattern in _NEEDS_REVIEW_PATTERNS:
        if pattern.search(content):
            return {"status": "needs_review"}
    folded = _folded_text(content)
    for pattern in _FRENCH_NEEDS_REVIEW_PATTERNS:
        if pattern.search(folded):
            return {"status": "needs_review"}

    if _looks_like_opaque_token(content):
        return {"status": "needs_review"}

    return {"status": "safe"}


# Verdicts of `evaluate_renderable_strings`, keyed by the digest of the
# artifact's `marshal` bytes. Live recall evaluates every record at every render
# (twice on an attended turn: the selector, then the consolidation check's
# expiry count), and this scan was most of that time; an unchanged record now
# costs one digest of about 2 KB. The key is exact: marshal takes only exact
# builtin types (a str or dict subclass, any other Mapping, raises and is
# scanned uncached) and decodes its bytes one way, so equal bytes are equal
# content -- every key, string, type and order the scan reads. Any change is a
# new key, so a record edited to unsafe text is scanned, and refused, on its
# next render. Version 2 writes no back-references, whose placement follows
# reference counts rather than content and would only cost hits. Cleared
# whole when full: a store past the bound rescans, as before.
_VERDICT_KEY_MARSHAL_VERSION = 2
_RENDERABLE_VERDICT_LIMIT = 8192
_renderable_verdicts: dict[bytes, dict[str, object]] = {}


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
    try:
        key: bytes | None = hashlib.sha256(marshal.dumps(artifact, _VERDICT_KEY_MARSHAL_VERSION)).digest()
    except ValueError:
        key = None
    verdict = _renderable_verdicts.get(key) if key is not None else None
    if verdict is None:
        verdict = _renderable_verdict(artifact, renderable_fields)
        if key is not None:
            if len(_renderable_verdicts) >= _RENDERABLE_VERDICT_LIMIT:
                _renderable_verdicts.clear()
            _renderable_verdicts[key] = verdict
    return dict(verdict)


def _renderable_verdict(artifact: Mapping[str, object], renderable_fields: tuple[str, ...]) -> dict[str, object]:
    """The worst classification over the field names and their renderable strings, in scan order."""
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
