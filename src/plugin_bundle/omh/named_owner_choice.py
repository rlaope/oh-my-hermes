"""External coding owners a person named in this turn's dag-ulw request.

Stdlib and bundle imports only: Hermes loads this package without core ``omh``.
A coding-owner choice counts only for the request it was made in: `pre_llm_call`
replaces the session's marker at the start of every turn, and `omh_dag`
`define` copies it into the run it starts. An earlier request's naming, a
`omh chat` or `omh coding` choice, or a recorded preference never starts an
external coding CLI from a dag-ulw run. Nothing here is written to disk, and
no request prose is kept.
"""

from __future__ import annotations

from collections import OrderedDict
import re
import sys
import threading
import types
import unicodedata

from .dag_ulw_cues import invokes_dag_ulw
from .executor_cues import SUBSTRING_NAMED_CODING_AGENT_PHRASES


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


# One process can hold two copies of this package (Hermes' memory-provider loader execs the bundle again), and the
# hook and the tool may each be a different copy: the markers live in one process-wide holder (as `jev_consent`).
_STATE_HOLDER = "_omh_named_owner_turn_state"
MAX_TRACKED_SESSIONS = 256


def _shared_state() -> types.SimpleNamespace:
    candidate = types.SimpleNamespace(lock=threading.Lock(), turn_owners=OrderedDict())
    holder = sys.modules.setdefault(_STATE_HOLDER, types.ModuleType(_STATE_HOLDER))
    return holder.__dict__.setdefault("state", candidate)


_state = _shared_state()


def note_turn_owners(session_id: object, request_text: str) -> tuple[str, ...]:
    """Record the owners this turn's dag-ulw request names for the session, replacing the previous turn's.

    Text that does not invoke dag-ulw, or names no unnegated owner, records none.
    """
    owners = named_owners(request_text) if request_text and invokes_dag_ulw(request_text) else ()
    key = str(session_id or "").strip()
    if key:
        with _state.lock:
            _state.turn_owners.pop(key, None)
            _state.turn_owners[key] = owners
            while len(_state.turn_owners) > MAX_TRACKED_SESSIONS:
                # Oldest first; an evicted session reads as having named no owner.
                _state.turn_owners.popitem(last=False)
    return owners


def clear_turn_owners(session_id: object) -> None:
    """Record that this turn named no owner yet; the hook calls this first on every turn."""
    note_turn_owners(session_id, "")


def turn_owners(session_id: object) -> tuple[str, ...]:
    """The owners the session's current turn named in its dag-ulw request, or ()."""
    key = str(session_id or "").strip()
    with _state.lock:
        return tuple(_state.turn_owners.get(key, ())) if key else ()


def reset_turn_owners() -> None:
    """Test seam: forget every session's marker."""
    with _state.lock:
        _state.turn_owners.clear()
