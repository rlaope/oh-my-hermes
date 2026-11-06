"""Per-owner explicit choices named in a person's dag-ulw request.

Stdlib and bundle imports only: Hermes loads this package without core ``omh``.
The main route family remains the router's; this writer only records each
external owner's own choice and never stores request prose.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import unicodedata

from .dag_ulw_cues import invokes_dag_ulw
from .executor_cues import SUBSTRING_NAMED_CODING_AGENT_PHRASES
from .owner_preference_record import (
    OWNER_PREFERENCE_EXCLUDED_SIGNALS,
    OWNER_PREFERENCE_PATH_SEGMENTS,
    OWNER_PREFERENCE_RECORD_TYPE,
    OWNER_PREFERENCE_SCHEMA_VERSION,
    per_owner_route_family,
    validate_owner_preference,
)


# Map each existing unambiguous executor phrase to its external owner once.
NAMED_OWNER_PHRASES = (
    ("codex", "codex"),
    ("코덱스", "codex"),
    ("claude code", "claude-code"),
    ("claude-code", "claude-code"),
    ("claudecode", "claude-code"),
    ("클로드 코드", "claude-code"),
    ("클로드코드", "claude-code"),
)
_EXTERNAL_OWNERS = ("codex", "claude-code")
_EN_NEGATIONS = (
    r"\b(?:no|not|without|except|never)\s+(?:use\s+)?{name}",
    r"\b(?:don't|do not|dont)\s+use\s+{name}",
    r"\b(?:instead of|other than)\s+{name}",
)
_KO_NEGATIONS = (
    r"{name}\s*(?:은|는|을|를)?\s*(?:말고|빼고|없이|제외)",
)
_JA_NEGATIONS = (
    r"{name}\s*(?:以外|なし|を使わず)",
)


def named_owners(text: str) -> tuple[str, ...]:
    """Return explicitly named, unnegated external owners in fixed order.

    Bare advisor names are absent from the shared executor cues. Latin word
    boundaries prevent an ordinary larger word from naming an owner, while
    allowing Japanese and Korean particles directly after a product name.
    """
    folded = " ".join(unicodedata.normalize("NFKC", text).casefold().replace("’", "'").split())
    found: set[str] = set()
    for phrase, owner in NAMED_OWNER_PHRASES:
        if phrase not in SUBSTRING_NAMED_CODING_AGENT_PHRASES:
            continue
        name = rf"(?<![a-z0-9_-]){re.escape(phrase)}(?![a-z0-9_-])"
        negated = [
            match.span()
            for template in (*_EN_NEGATIONS, *_KO_NEGATIONS, *_JA_NEGATIONS)
            for match in re.finditer(template.format(name=name), folded)
        ]
        if any(
            not any(start <= match.start() and match.end() <= end for start, end in negated)
            for match in re.finditer(name, folded)
        ):
            found.add(owner)
    return tuple(owner for owner in _EXTERNAL_OWNERS if owner in found)


def record_named_owner_choices(
    omh_home: str | Path, text: str, *, now_iso: str
) -> tuple[str, ...]:
    """Atomically record each named dag-ulw owner, preserving all other routes.

    Invalid existing state is never repaired or replaced. Naming refreshes an
    existing owner's timestamp without advancing the router's learning streak.
    I/O and new-state validation errors belong to the calling hook's degraded
    list; neither raw message text nor exception text is stored here.
    """
    if not invokes_dag_ulw(text):
        return ()
    owners = named_owners(text)
    if not owners:
        return ()
    path = Path(omh_home).joinpath(*OWNER_PREFERENCE_PATH_SEGMENTS)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        state = {
            "schema_version": OWNER_PREFERENCE_SCHEMA_VERSION,
            "record_type": OWNER_PREFERENCE_RECORD_TYPE,
            "privacy": {
                "mode": "metadata_only",
                "learning_source": "accepted_explicit_owner_choice",
                "excluded_signals": list(OWNER_PREFERENCE_EXCLUDED_SIGNALS),
            },
            "routes": {},
            "updated_at": "",
        }
    except (ValueError, UnicodeError):
        return ()
    if not isinstance(state, dict) or validate_owner_preference(state):
        return ()
    for owner in owners:
        family = per_owner_route_family("ulw-coding-delivery", owner)
        previous = state["routes"].get(family)
        changed = previous is not None and previous["selected_owner"] != owner
        if previous is None or changed or not previous["selected_owner"]:
            route = {
                "route_family": family,
                "selected_owner": owner,
                "consecutive_accepted_explicit_choices": 1,
                "first_choice_at": now_iso,
                "last_choice_at": now_iso,
                "learned_at": "",
                "reset_at": now_iso if changed else "",
                "reset_reason": "explicit_owner_changed" if changed else "",
                "provenance": "in_message_naming",
                "naming_cue": "named_executor:" + owner,
            }
        else:
            route = dict(previous)
            route.update(last_choice_at=now_iso, provenance="in_message_naming", naming_cue="named_executor:" + owner)
        state["routes"][family] = route
    state["updated_at"] = now_iso
    errors = validate_owner_preference(state)
    if errors:
        raise ValueError("; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary: Path | None = None
    try:
        # NamedTemporaryFile creates mode 600 from the outset, before writing.
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix=".owner-preference-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return owners
