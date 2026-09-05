"""The message gate: the provenance header OMH renders into a messenger body.

``messenger_rendering`` (``src/wrapper/contract.py``) is the SHAPE gate. It
decides chunk ceilings, Slack mrkdwn dialect, tables-to-bullets, and fence
handling, and it says nothing about WHAT a delegated response must disclose.
This module is the CONTENT gate for the same body: which skill ran, which model
and reasoning effort it ran on, what evidence class the answer belongs to, and
which prompt produced it.

Why render it here instead of asking for it. ``DELEGATE_MODEL_LABEL_RULE`` and
``DELEGATE_PROMPT_DISPLAY_RULE`` in ``src/skills/catalog_types.py`` already
state the ``(model effort)`` and fenced-prompt disciplines, but ``render.py``
gates that block to handoff-shaped skills, so it reaches 7 of 103 skill bodies,
and nothing anywhere checks that an agent actually emitted either shape. A
prose rule that no surface validates is a hope.
``goal_ledger.build_goal_status_card`` already reached the same conclusion
once, for one payload, after a live Slack session rendered a markdown table
that the surface silently dropped: it now hands back exact ``checkpoint_lines``
plus a ``render_guidance`` sentence. This module generalizes that one-off.

The gate fixes the header and the prompt block, and nothing else. The response
body stays free prose, and every field degrades to the literal ``unknown``
rather than being dropped or invented -- an absent model is a fact worth
printing, and an empty ``()`` is the one shape the rule names as forbidden.

Deliberately NOT here: a parallel-lane roster. ``status_board_messenger_body``
in ``src/coding/status_board.py`` already renders observed lanes for both
profiles with seven columns, including the tokens and resumable session ref
this module never sees, and it builds its labels with the same
``model_label_for``. A four-column copy here would be a worse duplicate of a
surface that already exists; ask ``omh coding status-board`` for the roster.
"""

from __future__ import annotations

from typing import Any, Final

from ..coding.context_safety import bounded_prompt_preview
from ..coding.status_board import model_label_for

MESSAGE_GATE_SCHEMA_VERSION: Final[str] = "omh_message_gate/v1"

UNKNOWN: Final[str] = "unknown"

# Profiles are the two the shape gate already resolves; the gate switches on
# them rather than on the platform so a new source needs no change here.
RENDER_PROFILE_LIMITED_MARKDOWN: Final[str] = "limited_markdown"
RENDER_PROFILE_RICH_MARKDOWN: Final[str] = "rich_markdown"

# Field order and the MODEL/STATUS labels match `_COLUMNS` in
# `src/coding/status_board.py`: identity, then model, then status. A reader who
# has seen the status board should not have to learn a second vocabulary for
# the same four facts.
_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("SKILL", "skill"),
    ("MODEL", "model"),
    ("STATUS", "status"),
    ("TASK", "task"),
    ("PROMPT", "prompt"),
    # The same digest row under the name the surface can actually back: a goal
    # ledger holds an objective, and labelling it PROMPT asserts a provenance
    # category the card does not have.
    ("OBJECTIVE", "objective"),
)

REFERENCE_KINDS: Final[tuple[str, ...]] = ("prompt", "objective")

# Bounded so a long skill name or a pasted model id cannot push the header past
# the tightest messenger ceiling on its own.
_VALUE_LIMIT: Final[int] = 96
# The PROMPT row carries a digest prefix, never the prompt. Twelve hex
# characters is what `omh coding fanout` already prints for a unit ref.
_DIGEST_PREFIX: Final[int] = 12
# How much of the composed prompt the follow-on message shows. Long enough to
# recognize the order Hermes actually issued, short enough that the block stays
# well inside Discord's 1700-character soft ceiling next to a header.
PROMPT_PREVIEW_CHARS: Final[int] = 200

PROMPT_BLOCK_TITLE: Final[str] = "HERMES PROMPTING"

WARNING_MISSING_MODEL_LABEL: Final[str] = "message_gate_missing_model_label"
WARNING_EMPTY_PARENTHESES: Final[str] = "message_gate_empty_parentheses"
WARNING_MISSING_STATUS: Final[str] = "message_gate_missing_status"
WARNING_MISSING_PROMPT_REFERENCE: Final[str] = "message_gate_missing_prompt_reference"
# `codex (executor default)` is honest -- OMH did resolve an executor and did
# apply no model override -- but it is indistinguishable from a route that was
# never attempted, and it silenced the missing-model warning on the main
# delegate path. This names the difference instead of overloading `unknown`.
WARNING_UNRESOLVED_MODEL_ROUTE: Final[str] = "message_gate_unresolved_model_route"

# Rendered once under the header, mirroring `goal_status_card.render_guidance`:
# the gate hands back exact lines, so an agent relaying them has no formatting
# decision left to get wrong.
RENDER_GUIDANCE: Final[str] = (
    "Render the provided gate lines verbatim, in order, above the response body, and post "
    "prompt_block as its own follow-on message. Never restate either as a markdown table: "
    "messenger surfaces drop tables."
)


def fence_marker_for(text: str) -> str:
    """Backtick fence for embedding ``text``: one longer than the longest
    backtick run inside it, minimum three, so embedded ``` fences nest safely."""
    longest = 0
    run = 0
    for character in text:
        if character == "`":
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return "`" * max(3, longest + 1)


def build_message_gate(
    *,
    skill: str = "",
    executor: str = "",
    model: str = "",
    reasoning_effort: str = "",
    model_label: str = "",
    status: str = "",
    task: str = "",
    prompt_sha256: str = "",
    prompt_chars: Any = None,
    composed_prompt: str = "",
    discloses_model: bool = True,
    reference_kind: str = "prompt",
) -> dict[str, Any]:
    """Project one response's execution provenance into a gate payload.

    ``model_label`` wins when a caller already resolved the label through the
    status-board convention (``_status_model_label``); otherwise the label is
    composed here from ``model`` plus ``reasoning_effort`` so both entry points
    produce the identical string.

    ``task`` and ``composed_prompt`` are the caller's decision, not this
    module's: the chat envelope declares ``redaction_policy: metadata_only``
    unless the wrapper opted into ``include_message``, so a caller that has not
    opted in passes ``""`` and those surfaces are omitted. An omitted row is not
    an unknown one -- the fact was never admitted to this surface, so printing
    ``unknown`` would misdescribe a redaction as a gap.

    ``discloses_model=False`` says the same thing about MODEL, and only a
    surface with no executor at all may say it -- a goal ledger card tracks
    acceptance criteria, not a running lane, so "which model" is not a fact it
    withholds but one it does not have.

    Three model states, not two, because the middle one is the common one:
    no executor reads ``unknown`` and raises ``message_gate_missing_model_label``;
    a resolved executor with no route reads ``codex (executor default)`` and
    raises ``message_gate_unresolved_model_route``; a resolved route reads
    ``codex (gpt-5.6-sol xhigh)`` and raises nothing. Collapsing the middle
    state into the last one is what let the main delegate path ship a header
    that could not distinguish "OMH applied no override" from "OMH never
    resolved a route", with no warning either way.
    """
    resolved_label = str(model_label or "").strip()
    if not resolved_label and (str(model or "").strip() or str(reasoning_effort or "").strip()):
        resolved_label = model_label_for(model, reasoning_effort)
    reference = reference_kind if reference_kind in REFERENCE_KINDS else REFERENCE_KINDS[0]
    fields: dict[str, str] = {
        "skill": _bounded(skill) or UNKNOWN,
        "status": _bounded(status) or UNKNOWN,
        reference: _prompt_reference(prompt_sha256, prompt_chars),
    }
    if discloses_model:
        fields["model"] = _model_field(executor, resolved_label)
    bounded_task = _bounded(task)
    if bounded_task:
        fields["task"] = bounded_task
    payload: dict[str, Any] = {
        "schema_version": MESSAGE_GATE_SCHEMA_VERSION,
        # Whether a model route was resolved at all, which the rendered MODEL
        # row cannot express: `codex (executor default)` is what both a
        # deliberate no-override and an unattempted route look like.
        "model_route_resolved": bool(resolved_label) if discloses_model else None,
        "fields": fields,
        "field_order": [key for _, key in _FIELDS if key in fields],
        "render_guidance": RENDER_GUIDANCE,
    }
    prompt_block = _prompt_block(composed_prompt, fields.get("model", ""))
    if prompt_block:
        payload["prompt_block"] = prompt_block
    payload["warnings"] = message_gate_warnings(payload)
    return payload


def render_message_gate_lines(
    payload: dict[str, Any], *, render_profile: str = RENDER_PROFILE_LIMITED_MARKDOWN
) -> list[str]:
    """The exact lines to print above a response body, one per element.

    ``rich_markdown`` gets an aligned block inside a single fence, because
    alignment is the whole reason a fence is worth its vertical cost, and two
    adjacent fences read as a rendering fault rather than as two sections.
    ``limited_markdown`` gets flat bullets -- the same branch
    ``status_board_messenger_body`` already makes, and for the same reason: a
    monospace block shrinks the font on a narrow phone client, where the header
    is read most.
    """
    fields = _fields(payload)
    if not fields:
        return []
    if render_profile == RENDER_PROFILE_RICH_MARKDOWN:
        rows = _aligned_pairs(fields, payload)
        # An empty fence pair is a rendering fault on every messenger, so a
        # payload this version can read no rows out of renders nothing at all.
        return ["```", *rows, "```"] if rows else []
    labels = {key: label for label, key in _FIELDS}
    return [
        f"- {labels.get(key, key.upper()).lower()} — {fields[key]}"
        for key in _field_order(payload)
        if key in fields
    ]


def message_gate_body(
    payload: dict[str, Any],
    *,
    render_profile: str = RENDER_PROFILE_LIMITED_MARKDOWN,
    body: str = "",
) -> str:
    """The gate lines joined above ``body``, or ``body`` unchanged when empty."""
    lines = render_message_gate_lines(payload, render_profile=render_profile)
    if not lines:
        return body
    header = "\n".join(lines)
    return f"{header}\n\n{body}" if body else header



def message_gate_warnings(payload: dict[str, Any]) -> list[str]:
    """Name the shapes that broke the disclosure rule, without refusing them.

    Warnings, not errors, for the reason ``native_commands._unsafe_rendering_warnings``
    gives: a response that discloses less than it should is still a response the
    user is waiting on. What must not happen is that it degrades silently.
    """
    fields = _fields(payload)
    warnings: list[str] = []
    model = fields.get("model", "")
    # An absent MODEL row is a declared non-disclosure (`discloses_model=False`),
    # not a gap; a present-but-unknown one is the gap this warning names.
    if "model" in fields and (not model or model == UNKNOWN):
        warnings.append(WARNING_MISSING_MODEL_LABEL)
    if "()" in model:
        warnings.append(WARNING_EMPTY_PARENTHESES)
    if "model" in fields and payload.get("model_route_resolved") is False:
        warnings.append(WARNING_UNRESOLVED_MODEL_ROUTE)
    if fields.get("status", UNKNOWN) == UNKNOWN:
        warnings.append(WARNING_MISSING_STATUS)
    if any(fields.get(key, UNKNOWN) == UNKNOWN for key in REFERENCE_KINDS if key in fields):
        warnings.append(WARNING_MISSING_PROMPT_REFERENCE)
    return sorted(set(warnings))


def _prompt_block(composed_prompt: str, model_field: str) -> str:
    """The composed order Hermes issued, bounded and fenced, or "" when absent.

    Bounded through ``bounded_prompt_preview`` so the truncation marker is the
    exact ``... [truncated, N chars total]`` shape ``DELEGATE_PROMPT_DISPLAY_RULE``
    promises, and fenced through a content-derived marker so a prompt that
    itself contains a fence still nests.
    """
    text = str(composed_prompt or "").strip()
    if not text:
        return ""
    preview = bounded_prompt_preview(text, max_chars=PROMPT_PREVIEW_CHARS)
    fence = fence_marker_for(preview)
    title = PROMPT_BLOCK_TITLE
    if model_field and model_field != UNKNOWN:
        title = f"{title} — {model_field}"
    return "\n".join([title, fence, preview, fence])


def _model_field(executor: str, model_label: str) -> str:
    """``codex (gpt-5.6-sol xhigh)`` -- executor and model as ONE visual field.

    The parenthetical is never emitted empty: ``DELEGATE_MODEL_LABEL_RULE``
    names that exact shape as forbidden. A known executor with no resolved route
    is ``codex (executor default)`` — the status board's own convention, outside
    the rule's two `(model effort)` / `(model)` shapes; knowing neither is
    ``unknown``, not a default label OMH cannot back (a bare field, not a
    placeholder beside a known model, so the rule's ban does not apply).
    """
    owner = _bounded(executor)
    label = _bounded(model_label)
    if not owner:
        return label or UNKNOWN
    return f"{owner} ({label or model_label_for('', '')})"


def _prompt_reference(prompt_sha256: str, prompt_chars: Any) -> str:
    """``sha256:533d406a4863 · 412 chars`` -- a reference, never the prompt.

    OMH deliberately does not persist the raw task (``_composed_prompt_handoff_text``),
    and the chat envelope's ``metadata_only`` redaction policy says the same
    about echoing it. A digest plus a length still answers "is this the prompt I
    typed?" without carrying the content.
    """
    digest = "".join(
        character for character in str(prompt_sha256 or "").strip() if character.isalnum()
    )
    if not digest:
        return UNKNOWN
    reference = f"sha256:{digest[:_DIGEST_PREFIX]}"
    if isinstance(prompt_chars, int) and not isinstance(prompt_chars, bool) and prompt_chars >= 0:
        return f"{reference} · {prompt_chars} chars"
    return reference





def _aligned_pairs(fields: dict[str, str], payload: dict[str, Any]) -> list[str]:
    """Aligned ``LABEL  value`` rows, tolerant of a key this version does not know.

    The payload is a public, round-trippable schema. A field key added in a
    later version must degrade to its own uppercased name here rather than
    crash a `max()` over an empty generator or a `labels[key]` lookup.
    """
    labels = {key: label for label, key in _FIELDS}
    order = [key for key in _field_order(payload) if key in fields]
    if not order:
        return []
    width = max(len(labels.get(key, key.upper())) for key in order)
    return [f"{labels.get(key, key.upper()).ljust(width)}  {fields[key]}" for key in order]



def _fields(payload: dict[str, Any]) -> dict[str, str]:
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return {}
    return {str(key): str(value) for key, value in fields.items() if str(value)}


def _field_order(payload: dict[str, Any]) -> list[str]:
    order = payload.get("field_order")
    if isinstance(order, (list, tuple)):
        return [str(key) for key in order]
    return [key for _, key in _FIELDS]


def _bounded(value: object) -> str:
    """Single-line and length-capped: a newline in a header breaks every row below it."""
    text = " ".join(str(value or "").split())
    if len(text) <= _VALUE_LIMIT:
        return text
    return f"{text[: _VALUE_LIMIT - 1].rstrip()}…"
