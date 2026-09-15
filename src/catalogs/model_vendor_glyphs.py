"""One glyph per model vendor, for telling parallel lanes apart at a glance.

A board of three running lanes is three rows of near-identical text; the model
is the field that actually differs, and it is the field a reader scans for. A
glyph in front of it is read before the word is.

Two rules shape the table.

Vendors, not models. `claude-opus-5` and `claude-fable-5-1` share a glyph
because a reader cannot hold eleven of them, let alone one per model
generation. The glyph answers "whose model is this", and the label beside it
answers which one.

The traffic lights are reserved. `briefing._SIGNAL_GLYPHS` spends 🟢 🟡 🔴 on
whether a run needs the reader, and those are the highest-salience colours
available. A vendor wearing red would read as a stopped lane, so this table
draws from what is left and reaches for a non-colour symbol rather than
reusing one. `tests/test_model_vendor_glyphs.py` fails if the two sets ever
intersect.

Every glyph is two display cells wide, which is what lets a glyph column sit in
an aligned board without shifting the columns after it. That is also pinned,
because a one-cell or three-cell glyph would look fine in a bullet list and
ragged in the fenced block the same data renders as on a narrow surface.
"""

from __future__ import annotations

from typing import Final, Mapping

# Keyed by vendor, the value a model alias resolves to through `_VENDOR_BY_TOKEN`.
VENDOR_GLYPHS: Final[Mapping[str, str]] = {
    "claude": "🟠",
    "gpt": "⚪",
    "deepseek": "🔵",
    "glm": "🟣",
    "gemini": "💠",
    "grok": "⚫",
    "qwen": "🟤",
    # Colours are spent by this point. A vendor whose name is already a picture
    # gets the picture: Moonshot's Kimi, Meta's llama, Mistral's wind.
    "kimi": "🌙",
    "llama": "🦙",
    "mistral": "🌬️",
}

# A model this table has never seen. Deliberately a neutral square rather than
# no glyph at all: an unlabelled row in a column of labelled ones reads as a
# rendering fault, and "a model we do not recognize" is a fact worth showing.
UNKNOWN_VENDOR_GLYPH: Final[str] = "⬜"
UNKNOWN_VENDOR: Final[str] = "unknown"

# First dash-separated token of an alias to its vendor. Written out rather than
# matched by prefix because the token is not always the vendor name:
# `qwen3-coder` starts with a generation-numbered token, and a prefix rule that
# handled it would also match anything else beginning with those letters.
_VENDOR_BY_TOKEN: Final[Mapping[str, str]] = {
    "claude": "claude",
    # Anthropic product names reach this table without their family prefix,
    # because the board carries the model string an executor reported rather
    # than an alias OMH chose: `fable-5 high` and `opus-5` are both real.
    "fable": "claude",
    "opus": "claude",
    "sonnet": "claude",
    "haiku": "claude",
    "mythos": "claude",
    "gpt": "gpt",
    "deepseek": "deepseek",
    "glm": "glm",
    "gemini": "gemini",
    "grok": "grok",
    "kimi": "kimi",
    "qwen": "qwen",
    "qwen3": "qwen",
    "llama": "llama",
    "llama4": "llama",
    "mistral": "mistral",
}


def vendor_for_model(model: str) -> str:
    """The vendor a model alias belongs to, or ``unknown``.

    Reads the first dash-separated token, so `codex (gpt-6-astra high)` must be
    reduced to its alias by the caller: this takes a model, not a rendered
    label, because guessing which part of a label is the model is how a runtime
    name ends up wearing a vendor's glyph.
    """
    # Strip, in order: a reasoning-effort suffix, then a provider prefix, then
    # the generation tail. `openrouter/qwen-3.5-coder high` is a shape the board
    # actually carries -- a gateway serving someone else's model -- and the
    # vendor is the model's, not the gateway's.
    identifier = str(model or "").strip().lower().split(" ", 1)[0]
    token = identifier.rsplit("/", 1)[-1].split("-", 1)[0]
    return _VENDOR_BY_TOKEN.get(token, UNKNOWN_VENDOR)


def vendor_glyph(model: str) -> str:
    """The glyph for a model alias, or the neutral square."""
    return VENDOR_GLYPHS.get(vendor_for_model(model), UNKNOWN_VENDOR_GLYPH)


def vendor_text(model: str) -> str:
    """``[vendor]`` for a surface that cannot render emoji at all.

    Email, a plain-text log, a terminal without a colour-emoji font: the glyph
    degrades to a mojibake box there, which carries less than the word does.
    """
    return f"[{vendor_for_model(model)}]"
