"""Lint the sentence a person reads for the three reply rules OMH ships.

The rules are prompt text: every generated skill's Runtime Evidence tail, the
common rail's "Reply Language And Host Voice" and "Turn Ending" sections, and
the awareness primers all say the same thing -- OMH's record vocabulary stays
in records and tool calls, awareness lines are never quoted, and a stop or a
decision the user owns ends the turn with the next action offered as a
question. Nothing observed whether a reply followed them; the only evidence
was a person reading "this is an evidence-bounded surface" or "I will not
merge here" and reporting it.

This module reads reply text and reports where it departs from those rules:

- ``record_term_leak``: an OMH record term in the reply (the rail's list, the
  OMH schema ids and record ids, plus the Korean renderings that reached the
  owner's replies).
- ``awareness_line_quoted``: an ``[OMH ...]`` head OMH writes (``[OMH
  Awareness]``, ``[OMH plan todo]``, ...) or a ``Boundary:`` line quoted into
  the reply.
- ``refusal_closer``: the closing paragraph declares what will not be done
  and offers no question.
- ``decision_without_question``: the closing paragraph names an approval or a
  decision the user owns and offers no question.

It is pure: no model, no network, no file write. A term the user's own
message names is explained on request, not leaked, so it is carved out. A
clean result shows only that the text carries none of these shapes; it says
nothing about whether the reply was correct, complete, or in the host's
voice, and the payload's claim boundary says so.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence


REPLY_LINT_SCHEMA_VERSION = "reply_lint/v1"

REPLY_LINT_CLAIM_BOUNDARY = (
    "This lint reads reply text only. A clean result shows that the text carries no "
    "OMH record term, no quoted awareness line, and no closing that declares what will "
    "not be done or leaves a decision without a question. It does not show that the reply "
    "was correct, complete, or in the host's own voice, and it is not execution, review, "
    "CI, or merge evidence."
)

FINDING_KINDS: tuple[str, ...] = (
    "record_term_leak",
    "awareness_line_quoted",
    "refusal_closer",
    "decision_without_question",
)

# The rail's record vocabulary, spelled as it reaches a reply. Underscore
# tokens are exact; English phrases are whole-word and case-insensitive.
# ``surface`` and ``lane`` are everyday English, so they are matched only in
# the qualified forms the bodies use; ``wrapper`` is a programming word and is
# matched only as OMH's own compound. ``handoff`` is OMH's term in a coding
# reply and is matched whole. Longest match wins, so ``prepared_not_observed``
# is one finding, not two.
_ENGLISH_RECORD_TERMS: tuple[str, ...] = (
    "prepared_not_observed",
    "not_observed",
    "not_available",
    "routing_observation",
    "evidence_boundary",
    "claim_boundary",
    "evidence boundary",
    "claim boundary",
    "evidence-bounded",
    "operating surface",
    "OMH surface",
    "evidence surface",
    "coding lane",
    "workflow lane",
    "OMH lane",
    "run record",
    "wrapper action",
    "wrapper card",
    "OMH wrapper",
    "handoff",
    # Qualified forms only, from the 2026-09-28 leak audit: bare `fanout` is
    # an everyday word, so it is matched only in the command OMH spells it in
    # (`omh coding fanout dispatch`), never alone and never as "the fanout
    # dispatch queue" of someone's broker. `goal ledger` is held back: "update
    # the goal ledger in the finance sheet" is ordinary bookkeeping, and so is
    # `closure receipt` ("keep the account closure receipt"), which no surface
    # a Hermes model reads spells.
    "route_question",
    "coding fanout dispatch",
)

# OMH record ids a tool result carries as values, as exact literals: the
# routable categories (`hermes_delegation.HERMES_MIXTURE_CATEGORY_CHAINS`),
# the todo evidence codes and derived state (`todo_reconciliation`), the
# route exhaustion origin, and the fanout repair loop's blocked reasons and
# in-flight status (`omh.coding.fanout_repair`). Scope rule: an id that is an
# ordinary English word or phrase is held back in `_ORDINARY_CATEGORY_IDS`,
# because "a quick fix" or "a deep-work block" is not a leak; every other id
# is OMH's coinage. Matched case-sensitively and whole: a letter or digit
# after it (`unspecified-higher`) or a hyphen continuing it
# (`unspecified-high-tier`, `no_evidence-free`) makes it a different word.
# `tests/test_reply_lint.py` re-derives both sets from those producers and
# fails with the id to add or remove.
_RECORD_ID_TERMS: tuple[str, ...] = (
    "ultrabrain",
    "visual-engineering",
    "simple-work",
    "unspecified-high",
    "unspecified-low",
    "done_unverified",
    "no_evidence",
    "evidence_failed",
    "evidence_unresolved",
    "evidence_unreadable",
    "exhausted_to_inherit",
    "repair_budget_exhausted",
    "repair_worktree_missing",
    "repair_in_flight",
)
_ORDINARY_CATEGORY_IDS: frozenset[str] = frozenset(
    {"architect", "artistry", "capable", "deep", "deep-work", "quick", "writing"}
)

# OMH schema ids, as exact literals. Scope rule: every `omh_`-prefixed id the
# plugin bundle or a shipped plugin tool schema spells -- OMH's own namespace,
# which no ordinary sentence uses. Everything else stays out, including the
# unprefixed ids a tool schema names (`done_check/v1`, `route_question/v1`):
# none reached a reply in the 2026-09-28 audit, whose measured ids were all
# `omh_`-prefixed, and `done_check/v1` reads as a person's own versioned
# check as easily as OMH's. A one-word id like `governance/v2` reads as an
# ordinary version reference, and a shape pattern would flag `apps/v1` and
# `/api/v2/users`. `tests/test_reply_lint.py` re-derives this set from the
# bundle and the schemas and fails with the id to add or remove.
_SCHEMA_ID_TERMS: tuple[str, ...] = (
    "omh_approval_bypass/v1",
    "omh_awareness/v1",
    "omh_awareness_delivery/v1",
    "omh_buzz_probe/v1",
    "omh_capability_gap_roadmap/v1",
    "omh_capability_impact_report/v1",
    "omh_capability_inspect/v1",
    "omh_capability_list/v1",
    "omh_capability_manifest/v1",
    "omh_capability_summary/v1",
    "omh_catalog_question_hint/v1",
    "omh_code_mode_guidance/v1",
    "omh_context_brief/v1",
    "omh_context_brief_error/v1",
    "omh_context_response_contract/v1",
    "omh_cost_receipt/v1",
    "omh_degradation/v1",
    "omh_desktop_hud/v1",
    "omh_dispatch_outcome/v1",
    "omh_document_plan_result/v1",
    "omh_engagement_nudge/v1",
    "omh_engagement_nudges/v1",
    "omh_evidence_probe/v1",
    "omh_executor_progress_binding/v1",
    "omh_generic_tool_checkpoint/v1",
    "omh_group_activity_checkpoint/v1",
    "omh_group_activity_event/v1",
    "omh_group_activity_observer_status/v1",
    "omh_hook_manifest/v1",
    "omh_hud/v1",
    "omh_hud_fanout_cache/v1",
    "omh_inflight_marker/v1",
    "omh_interact_result/v1",
    "omh_jev_ask_record/v1",
    "omh_jev_ask_result/v1",
    "omh_kanban_readback/v1",
    "omh_lifecycle_projection/v1",
    "omh_loop_result/v1",
    "omh_memory_attention/v1",
    "omh_memory_audience/v1",
    "omh_memory_block/v1",
    "omh_memory_block/v2",
    "omh_memory_block_listing/v2",
    "omh_memory_block_read/v1",
    "omh_memory_block_read/v2",
    "omh_memory_bridge_unavailable/v1",
    "omh_memory_capture/v1",
    "omh_memory_consolidation_handoff/v1",
    "omh_memory_dreaming_state/v1",
    "omh_memory_eviction_plan/v1",
    "omh_memory_identity/v1",
    "omh_memory_index/v1",
    "omh_memory_open_reminders/v1",
    "omh_memory_pins/v1",
    "omh_memory_prefetch_receipt/v1",
    "omh_memory_prefetch_receipt/v2",
    "omh_memory_prefetch_receipt/v3",
    "omh_memory_recall_selector/v1",
    "omh_memory_recall_usage/v1",
    "omh_memory_replay_evaluation/v1",
    "omh_memory_scope/v1",
    "omh_memory_scope/v2",
    "omh_memory_scope/v3",
    "omh_memory_unknown_action/v1",
    "omh_memory_write_journal_entry/v1",
    "omh_observation_event/v1",
    "omh_parity_matrix/v1",
    "omh_platform_envelope/v1",
    "omh_plugin_host_observation/v1",
    "omh_plugin_host_observation_error/v1",
    "omh_plugin_session_end/v1",
    "omh_progress_event/v1",
    "omh_progress_report/v1",
    "omh_recommend_result/v1",
    "omh_remote_wait/v1",
    "omh_role_catalog/v1",
    "omh_role_context/v1",
    "omh_route_answer_result/v1",
    "omh_route_hint/v1",
    "omh_run_context_budget/v1",
    "omh_run_summary/v1",
    "omh_running_work_board/v1",
    "omh_skill_picker/v1",
    "omh_skill_shortlist_index/v1",
    "omh_status/v1",
    "omh_team_result/v1",
    "omh_todo/v1",
    "omh_todo_result/v1",
    "omh_tool_activity/v1",
    "omh_tool_bursts/v1",
    "omh_toolcall_rule_faults/v1",
    "omh_toolcall_rules/v1",
    "omh_truncated_read/v1",
    "omh_work_resume/v1",
    "omh_wrapper_session_ref/v1",
)

# Korean renderings observed in live replies ("두 표면을 서빙합니다", "레인을
# 열었습니다"). A term matches with or without a trailing particle and never
# inside another word, so 표면적 (superficially) and 브레인 (brain) do not
# match while 표면을 and 레인을 do.
_KOREAN_RECORD_TERMS: tuple[str, ...] = (
    "표면",
    "레인",
    "핸드오프",
    "증거 경계",
    "래퍼",
)

_KOREAN_PARTICLES = "(?:이|가|을|를|은|는|의|에|과|와|로|도|만|들|으로|입니다|이다)?"
_HANGUL = "가-힣"

# Every `[OMH ...]` head OMH writes into context or appends to a reply, as an
# exact literal. `tests/test_reply_lint.py` re-derives the set from `src/` and
# fails with the tag to add, so a new head cannot ship unseen. Exact, never a
# generic `[OMH ...]` shape: "[OMH README](...)" is a link and "[OMH 2.0.2]" a
# version, and neither is a tag OMH writes. A literal followed by `(`, `[`
# or `:` is markdown link text (`[OMH](url)`, `[OMH][1]`) or a reference
# definition (`[OMH]: https://...`), never a quoted line.
#
# The user carve-out does not apply to these heads: Hermes stores OMH's
# injected context inside the user turn's content, so a carve-out keyed on
# the user text would excuse every tag the model saw there.
_AWARENESS_TAGS: tuple[str, ...] = (
    "[OMH]",
    "[OMH Active Workflow]",
    "[OMH approval gate]",
    "[OMH Awareness]",
    "[OMH board readback]",
    "[OMH board]",
    "[OMH Code-Mode Discipline]",
    "[OMH Context Budget]",
    "[OMH continuation claim]",
    "[OMH Degraded]",
    "[OMH delegation]",
    "[OMH plan todo]",
    "[OMH Repeat Guard]",
    "[OMH Role Warning]",
    "[OMH Route Hint]",
    "[OMH Rule]",
    "[OMH truncated read]",
    "[OMH unarmed wait]",
)

# Heads built at runtime around a value (`[OMH Role: reviewer]`): the fixed
# prefix is the literal, and the value runs to the closing bracket.
_AWARENESS_TAG_PREFIXES: tuple[str, ...] = ("[OMH Role:",)

_AWARENESS_LINE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    tuple((tag, re.compile(re.escape(tag) + r"(?![\(\[:])")) for tag in _AWARENESS_TAGS)
    + tuple(
        (prefix + "]", re.compile(re.escape(prefix) + r"[^\]\n]*\](?![\(\[:])"))
        for prefix in _AWARENESS_TAG_PREFIXES
    )
    + (
        ("Boundary:", re.compile(r"(?m)^\s*(?:>\s*)?Boundary:")),
        ("Route hint:", re.compile(r"(?m)^\s*(?:>\s*)?Route hint:")),
    )
)

# A closing that says what will not be done. English forms are first person;
# Korean forms are the verb endings the owner's replies closed on
# ("하지 않을게", "처리하지 않겠습니다", "시작하지 않음").
_REFUSAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bI will not\b", re.IGNORECASE),
    re.compile(r"\bI won'?t\b", re.IGNORECASE),
    re.compile(r"\bI(?:'m| am) not going to\b", re.IGNORECASE),
    re.compile(r"\bI(?:'ll| will) stop here\b", re.IGNORECASE),
    re.compile(r"\bstopping here\b", re.IGNORECASE),
    re.compile(r"\bno further (?:action|changes|edits|work)\b", re.IGNORECASE),
    re.compile(r"하지 않을게"),
    re.compile(r"하지 않겠"),
    re.compile(r"하지 않음"),
    re.compile(r"않을게요"),
    re.compile(r"안 할게"),
    re.compile(r"진행하지 않"),
    re.compile(r"여기서 멈"),
    re.compile(r"중단하겠"),
    re.compile(r"보류하겠"),
)

# A closing that hands the user a decision without asking it.
_DECISION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:your|the user's) (?:call|decision|approval)\b", re.IGNORECASE),
    re.compile(r"\b(?:needs|requires|awaiting|waiting for) (?:your )?(?:approval|confirmation|decision)\b", re.IGNORECASE),
    re.compile(r"승인이 필요"),
    re.compile(r"승인 대기"),
    re.compile(r"결정이 필요"),
    re.compile(r"결정해 주"),
    re.compile(r"선택이 필요"),
)

_QUESTION_MARKS = ("?", "？")
_KOREAN_QUESTION_ENDINGS = ("까요", "습니까", "할까", "볼까", "드릴까", "될까", "나요", "가요")

_EXCERPT_CHARS = 160
_CLOSING_EXCERPT_CHARS = 240


def _english_term_pattern(term: str) -> re.Pattern[str]:
    if "_" in term:
        # An identifier followed by `(` is a call in the person's own code
        # (`route_question(q)`), not OMH's record word.
        return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_(])")
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.IGNORECASE)


def _korean_term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(
        f"(?<![{_HANGUL}])" + re.escape(term) + _KOREAN_PARTICLES + f"(?![{_HANGUL}])"
    )


def _schema_id_pattern(schema_id: str) -> re.Pattern[str]:
    # Exact: `omh_todo/v1` never matches inside `omh_todo_result/v1` or
    # `omh_todo/v12`, and a path segment (`x/omh_todo/v1`) is still the id.
    return re.compile(r"(?<![A-Za-z0-9_.-])" + re.escape(schema_id) + r"(?![A-Za-z0-9_])")


def _record_id_pattern(record_id: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(record_id) + r"(?![A-Za-z0-9_(-])")


_RECORD_TERM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    [(term, _english_term_pattern(term)) for term in _ENGLISH_RECORD_TERMS]
    + [(term, _record_id_pattern(term)) for term in _RECORD_ID_TERMS]
    + [(term, _schema_id_pattern(term)) for term in _SCHEMA_ID_TERMS]
    + [(term, _korean_term_pattern(term)) for term in _KOREAN_RECORD_TERMS]
)


def record_term_vocabulary() -> tuple[str, ...]:
    """The terms this lint reports, in match order, for docs and tests."""
    return tuple(term for term, _ in _RECORD_TERM_PATTERNS)


def build_reply_lint(reply: str, *, user_text: str = "") -> dict[str, Any]:
    """Lint one reply. ``user_text`` is the message it answers, for the carve-out."""
    text = str(reply or "")
    asked = str(user_text or "")
    lines = text.split("\n")
    findings: list[dict[str, Any]] = []
    carved_out: list[str] = []

    for term, match in _record_term_matches(text):
        if _user_named(term, match, asked):
            if term not in carved_out:
                carved_out.append(term)
            continue
        findings.append(_finding("record_term_leak", term, text, lines, match.start()))

    for label, pattern in _AWARENESS_LINE_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(_finding("awareness_line_quoted", label, text, lines, match.start()))

    closing = closing_paragraph(text)
    has_question = closing_has_question(closing)
    closing_kind = ""
    if not has_question:
        refusal = _first_match(_REFUSAL_PATTERNS, closing)
        if refusal is not None:
            closing_kind = "refusal_closer"
            findings.append(_closing_finding(closing_kind, refusal, text, lines, closing))
        else:
            decision = _first_match(_DECISION_PATTERNS, closing)
            if decision is not None:
                closing_kind = "decision_without_question"
                findings.append(_closing_finding(closing_kind, decision, text, lines, closing))

    findings.sort(key=lambda item: (int(item["line"]), int(item["column"]), str(item["kind"])))
    counts = {kind: sum(1 for item in findings if item["kind"] == kind) for kind in FINDING_KINDS}
    return {
        "schema_version": REPLY_LINT_SCHEMA_VERSION,
        "reply_chars": len(text),
        "closing": {
            "excerpt": _clip(closing, _CLOSING_EXCERPT_CHARS),
            "has_question": has_question,
            "kind": closing_kind,
        },
        "findings": findings,
        "counts": counts,
        "finding_count": len(findings),
        "carved_out_terms": carved_out,
        "ok": not findings,
        "claim_boundary": REPLY_LINT_CLAIM_BOUNDARY,
    }


def summarize_reply_lints(
    records: Sequence[Mapping[str, Any]], *, source: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Fold per-reply records into one payload with the same claim boundary."""
    rows = [dict(record) for record in records]
    counts = {kind: sum(int(row.get("counts", {}).get(kind, 0)) for row in rows) for kind in FINDING_KINDS}
    finding_count = sum(counts.values())
    return {
        "schema_version": REPLY_LINT_SCHEMA_VERSION,
        "source": dict(source or {}),
        "reply_count": len(rows),
        "replies": rows,
        "counts": counts,
        "finding_count": finding_count,
        "ok": finding_count == 0,
        "claim_boundary": REPLY_LINT_CLAIM_BOUNDARY,
    }


def format_reply_lint_summary(payload: Mapping[str, Any]) -> str:
    """Plain-text rendering: verdict, per-reply findings, then the boundary."""
    out: list[str] = []
    finding_count = int(payload.get("finding_count", 0))
    reply_count = int(payload.get("reply_count", 0))
    verdict = "clean" if payload.get("ok") else f"{finding_count} finding{'s' if finding_count != 1 else ''}"
    out.append(f"OMH reply lint: {verdict} across {reply_count} repl{'y' if reply_count == 1 else 'ies'}")
    counts = payload.get("counts") or {}
    out.append("  " + "    ".join(f"{kind}: {int(counts.get(kind, 0))}" for kind in FINDING_KINDS))
    for index, record in enumerate(payload.get("replies") or (), start=1):
        closing = record.get("closing") or {}
        state = "clean" if record.get("ok") else f"{int(record.get('finding_count', 0))} finding(s)"
        out.append(f"Reply {index}: {state}    closing question: {'yes' if closing.get('has_question') else 'no'}")
        for finding in record.get("findings") or ():
            out.append(
                f"  line {finding.get('line')}: {finding.get('kind')} `{finding.get('match')}`"
                f" -- {finding.get('excerpt')}"
            )
        carved = record.get("carved_out_terms") or ()
        if carved:
            out.append("  named by the user, not counted: " + ", ".join(str(term) for term in carved))
    out.append("Boundary")
    out.append(f"  {payload.get('claim_boundary', REPLY_LINT_CLAIM_BOUNDARY)}")
    return "\n".join(out)


def closing_paragraph(text: str) -> str:
    """The last blank-line-separated block; a list stays one block."""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
    return blocks[-1] if blocks else ""


def closing_has_question(closing: str) -> bool:
    if any(mark in closing for mark in _QUESTION_MARKS):
        return True
    stripped = closing.rstrip(" \t.)]」』\"'`*_")
    return any(stripped.endswith(ending) for ending in _KOREAN_QUESTION_ENDINGS)


def _record_term_matches(text: str) -> list[tuple[str, re.Match[str]]]:
    candidates: list[tuple[str, re.Match[str]]] = []
    for term, pattern in _RECORD_TERM_PATTERNS:
        candidates.extend((term, match) for match in pattern.finditer(text))
    # Longest span first, then earliest; a span inside an accepted one is dropped.
    candidates.sort(key=lambda item: (-(item[1].end() - item[1].start()), item[1].start()))
    accepted: list[tuple[str, re.Match[str]]] = []
    taken: list[tuple[int, int]] = []
    for term, match in candidates:
        span = (match.start(), match.end())
        if any(start < span[1] and span[0] < end for start, end in taken):
            continue
        taken.append(span)
        accepted.append((term, match))
    accepted.sort(key=lambda item: item[1].start())
    return accepted


def _user_named(term: str, match: re.Match[str], user_text: str) -> bool:
    if not user_text:
        return False
    lowered = user_text.lower()
    return term.lower() in lowered or match.group(0).lower() in lowered


def _first_match(patterns: Iterable[re.Pattern[str]], text: str) -> re.Match[str] | None:
    found: re.Match[str] | None = None
    for pattern in patterns:
        match = pattern.search(text)
        if match is not None and (found is None or match.start() < found.start()):
            found = match
    return found


def _finding(kind: str, label: str, text: str, lines: Sequence[str], offset: int) -> dict[str, Any]:
    line_index = text.count("\n", 0, offset)
    line_start = text.rfind("\n", 0, offset) + 1
    return {
        "kind": kind,
        "match": label,
        "line": line_index + 1,
        "column": offset - line_start + 1,
        "excerpt": _clip(lines[line_index].strip(), _EXCERPT_CHARS),
    }


def _closing_finding(
    kind: str, match: re.Match[str], text: str, lines: Sequence[str], closing: str
) -> dict[str, Any]:
    closing_offset = text.rfind(closing)
    offset = (closing_offset if closing_offset >= 0 else 0) + match.start()
    finding = _finding(kind, match.group(0), text, lines, offset)
    return finding


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"
