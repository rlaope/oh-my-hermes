"""The courtesy and address a request may open with: one list for every reader.

A request is often put politely or addressed first -- "please", "hey,", "can
you", "hermes,", "i need you to", "go ahead and" -- and a reader looking for
its first word of substance has to look past them. Four readers did, each with
its own list, and the lists drifted: data-share-review admitted "hey, redact
pii in the export before we send it to the vendor" and refused the same
sentence opened with "hi,", "pls" or "would you", which the others stripped.
Every reader takes the openers from here now:

- `spend_signals`, before the spend's lead; the openers it strips are where
  it looks for a request marker, which stays its own list;
- `data_share_cues`, before the protective verb;
- `hermes_session_commands`, before a loop on a timer;
- `command_verb.command_words`, before the command verb that narrows
  a guard.

Stripping an opener admits nothing by itself: each reader still requires its
own lead, and spend-gate its own request marker. An opener counts only as
whole words at the start, followed by the end of the text, a space, or
punctuation that ends a word (`,.!;:?`), so "hermes's config", "so-called"
and "ok/loop" keep their first word. A "." right before a "/" is not taken
with the opener: it starts a path or OMH's `./loop`, so "ok ./loop" and
"ok./loop" both keep the sigil. Stdlib only.
"""

from __future__ import annotations

from collections.abc import Sequence
import re

# Longest first, so "go ahead and" is taken whole before "go ahead".
COURTESY_OPENERS: tuple[tuple[str, ...], ...] = tuple(
    sorted(
        (
            ("please",),
            ("pls",),
            ("plz",),
            ("kindly",),
            ("hey",),
            ("hi",),
            ("hello",),
            ("ok",),
            ("okay",),
            ("alright",),
            ("so",),
            ("just",),
            ("now",),
            ("hermes",),
            ("omh",),
            ("let's",),
            ("lets",),
            ("can", "you"),
            ("could", "you"),
            ("would", "you"),
            ("will", "you"),
            ("can", "we"),
            ("could", "we"),
            ("we", "need", "to"),
            ("i", "need", "you", "to"),
            ("i", "want", "you", "to"),
            ("go", "ahead", "and"),
            ("go", "ahead"),
        ),
        key=len,
        reverse=True,
    )
)

_OPENERS_AT_START = re.compile(
    r"\s*(?:(?:"
    + "|".join(r"\s+".join(re.escape(word) for word in opener) for opener in COURTESY_OPENERS)
    + r")(?=[\s,.!;:?]|$)(?:[,!;:?]|\.(?!/))*\s*)+"
)


def courtesy_opener_length(words: Sequence[str]) -> int:
    """How many of `words`, from the first, are one courtesy opener; 0 when they open with none.

    For a reader that has its own tokens and repeats this past each opener
    and whatever punctuation tokens it skips.
    """
    for opener in COURTESY_OPENERS:
        if tuple(words[: len(opener)]) == opener:
            return len(opener)
    return 0


def after_courtesy(text: str) -> str:
    """`text` from its first word after every courtesy opener at its start.

    `text` is folded the way the caller folds its own words (lower case).
    """
    opening = _OPENERS_AT_START.match(text)
    return text[opening.end():] if opening else text
