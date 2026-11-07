"""Closing a story has an owner, and the page it opens may only cite records.

Two claims, each pinned against the producer rather than a second copy of it.

The page claim: `references/closing-a-story.md` may only tell a closer to read
records that exist. Its source table is rendered from the same
`HANDOVER_RECORD_SOURCES` the `wiki` handover page uses, so the two cannot
disagree about which of the four outlives the session, and its caps and phase
label are interpolated from the store and the template rather than typed.

The routing claim is narrower than it first looks, and deliberately so. There
is NO chat trigger for closing a story: every wording tried was built from
`close`, `story` and a finishing word, which as an unordered token set
dispatched nine sentences about bedtime stories, closing ceremonies and Jira
tickets at high confidence, and as a phrase list still matched inside "close
the story book". A run reaches the page through the `code-story` phase
template instead. What IS pinned here is the half that stands on its own:
`finance-analysis` carried the bare word `close` out of its "month-end close"
phrase, and no longer does. Measured on `build_chat_interaction_payload` --
the surface that decides a dispatch -- because `omh recommend` only ranks, and
this repository has already reported a routing defect that did not exist by
measuring the other one.
"""

from __future__ import annotations

import re
import time
import unittest

from omh.plugin_bundle.omh.completion_store import (
    CompletionValidationError,
    KINDS,
    RESULT_FIELDS,
    _projection,
    _result,
)
from omh.plugin_bundle.omh.todo_store import (
    MAX_TODO_ITEMS,
    MAX_TODO_TEXT_CHARS,
    TODO_STALE_SECONDS,
)
from omh.plugin_bundle.omh.todo_templates import (
    CODE_STORY_TEMPLATE,
    template_coverage_error,
    template_phase_labels,
)
from omh.routing.recommend import _WHOLE_PHRASE_ONLY_TRIGGER_TOKENS
from omh.skills.render import (
    HANDOVER_DURABLE_RECORD,
    HANDOVER_QUIZ_BASIS,
    HANDOVER_RECORD_SOURCES,
    TODO_CHECKLIST_CLOSING_REFERENCE_PATH,
    todo_checklist_reference_templates,
)
from omh.wrapper.contract import build_chat_interaction_payload


def _route(message: str) -> dict:
    return build_chat_interaction_payload(message, source="discord", mode="auto")["route"]


def _matched_for(message: str, skill: str) -> set[str]:
    for recommendation in _route(message).get("recommendations", ()):
        if recommendation.get("skill") == skill:
            return set(recommendation.get("matched", ()))
    return set()


def _closing_reference_content() -> str:
    for template in todo_checklist_reference_templates():
        if template.relative_path == TODO_CHECKLIST_CLOSING_REFERENCE_PATH:
            return template.content
    raise AssertionError(f"{TODO_CHECKLIST_CLOSING_REFERENCE_PATH} is not rendered for todo-checklist")


# Measured on the deciding surface while a `close` + `story` + finishing-word
# token set was in the tree. Every one of them dispatched to `todo-checklist`
# at high confidence, scoring 30-36 against fields of 3-7. They are kept here
# because the evidence is the expensive part (#1789): the first two are this
# file's own negative controls with one finishing word added, which showed
# that the finishing word filters a corpus rather than detecting that `story`
# is the object of `close`.
STORY_CLOSE_COUNTEREXAMPLES = (
    "close the modal when the story carousel has finished",
    "a user story that is closed in jira shows as done",
    "the news story about the merger is done being edited, close the tab",
    "closing the story arc in chapter twelve, the hero is finally done",
    "the closing ceremony is done and the story of the games is over",
    "the story of this outage is not done until we close the incident",
    "the newspaper story is finished, close the layout file",
    "close the story book after the child is done reading",
    "the closing paragraph of the story is done",
    "the story branch was merged, close the stale PR",
    "we shipped the story to the newsroom and closed the comment thread",
    "the release story is shipped, close the docs tab",
)


class StoryCloseHasNoChatTriggerTest(unittest.TestCase):
    """The plain-words path is an open gap, and this is the bar it has to clear.

    These pass trivially today, because nothing routes a closing request at
    all -- the skill is reached through the `code-story` phase template. They
    are not a pin on the empty state: a correct trigger leaves every one of
    them alone, so the battery states the property any future trigger must
    have rather than freezing the absence of one. Whoever writes that trigger
    should run this file first.
    """

    def test_no_counterexample_reaches_a_dispatch(self) -> None:
        for message in STORY_CLOSE_COUNTEREXAMPLES:
            with self.subTest(message=message):
                route = _route(message)
                self.assertNotEqual(
                    (route.get("action"), route.get("candidate_skill")),
                    ("dispatch", "todo-checklist"),
                    "a closing trigger must not dispatch on a sentence that merely contains "
                    "a closing verb, `story`, and a finishing word",
                )


class FinanceCloseTokenTest(unittest.TestCase):
    def test_the_bare_close_token_no_longer_names_the_finance_workflow(self) -> None:
        """The measured defect: `month-end close` split, and `close` came loose.

        `finance-analysis` was the top candidate on "close this story, it is
        done" at a score of 4, over every workflow that has anything to do
        with finishing work.
        """

        self.assertIn("close", _WHOLE_PHRASE_ONLY_TRIGGER_TOKENS["finance-analysis"])
        for message in (
            "close this story, it is done",
            "the modal should close when the user presses escape",
            "close the file handle before unlinking it",
        ):
            with self.subTest(message=message):
                self.assertNotIn("trigger:close", _matched_for(message, "finance-analysis"))
                self.assertNotEqual(_route(message).get("candidate_skill"), "finance-analysis")

    def test_the_accounting_request_still_reaches_the_finance_workflow(self) -> None:
        """The hold-back may not cost the phrase it was derived from.

        "month-end close" reaches the workflow as a domain cue, which the
        trigger-token hold-back does not touch.
        """

        route = _route("month-end close variance for October")
        self.assertEqual(route["action"], "dispatch")
        self.assertEqual(route["candidate_skill"], "finance-analysis")


class ClosingReferenceContentTest(unittest.TestCase):
    def test_the_page_names_the_close_phase_from_the_template(self) -> None:
        close_phase = template_phase_labels(CODE_STORY_TEMPLATE)[-1]
        self.assertIn(f"`{close_phase}` in the `{CODE_STORY_TEMPLATE}` plan", _closing_reference_content())

    def test_the_page_does_not_call_its_own_template_unordered(self) -> None:
        """"No canonical sequence" is true of `omh_todo/v1`, not of this page's subject.

        The page tells a closer to read the list as it stands, which is right
        for both cases and for different reasons. An ordinary plan has no
        order to derive; a `code-story` plan has one, numbered and enforced,
        and stored order already is it. Both halves are checked against the
        template rather than asserted in prose.
        """

        labels = template_phase_labels(CODE_STORY_TEMPLATE)
        self.assertEqual(labels[0].split(".", 1)[0], "I")
        self.assertEqual(labels[-1].split(".", 1)[0], "X")
        reversed_plan = [
            {"text": f"item {index}", "state": "done", "phase": label}
            for index, label in enumerate(reversed(labels))
        ]
        self.assertIn(
            "out of order",
            template_coverage_error(CODE_STORY_TEMPLATE, reversed_plan),
            "the page says a stamped plan naming its phases out of sequence is refused",
        )
        content = _closing_reference_content()
        self.assertIn("**Phase by phase, in the list's own order.**", content)
        self.assertIn("free-text label the store never ranks", content)
        self.assertIn(f"A\n   `{CODE_STORY_TEMPLATE}` plan does have a delivery order", content)

    def test_the_page_takes_the_record_bounds_from_the_store(self) -> None:
        """Interpolated, never typed, so the prose cannot drift from the code."""

        content = _closing_reference_content()
        self.assertIn(f"at most {MAX_TODO_ITEMS} items", content)
        self.assertIn(f"{MAX_TODO_TEXT_CHARS} characters of text each", content)
        self.assertIn(f"unlinked after {TODO_STALE_SECONDS // 3600} hours", content)

    def test_the_source_table_is_the_handover_page_s_table(self) -> None:
        """One vocabulary for which records exist, not two.

        Both pages render from `HANDOVER_RECORD_SOURCES`, so a source that is
        renamed or reclassified moves on both at once. Two hand-written tables
        would drift, and the one that drifted would be sending a reader to a
        store that is not there.
        """

        content = _closing_reference_content()
        for source in HANDOVER_RECORD_SOURCES:
            with self.subTest(source=source.label):
                self.assertIn(f"| {source.label} (", content)
                for citation in source.citations:
                    self.assertIn(f"`{citation.token}`", content)

    def test_the_page_rests_the_close_on_the_one_durable_record(self) -> None:
        """The hard constraint: a verification verdict is not a close criterion.

        Native result declarations now persist, but storage never promotes a
        declared verdict into a close criterion or evidence of observed work.
        The live plan and the optional dossier remain distinct sources.
        """

        durable = [s for s in HANDOVER_RECORD_SOURCES if s.held_in == HANDOVER_DURABLE_RECORD]
        self.assertEqual([s.label for s in durable], ["Plan record"])
        content = _closing_reference_content()
        self.assertIn(f"read with `{durable[0].read_with}`", content)
        self.assertIn(
            "bounded declarations written with `omh_todo action=record`",
            content,
        )
        self.assertIn("belong to `omh-verification-gate`, which runs\n  before this phase", content)

    def test_the_page_refuses_to_read_a_declaration_as_work(self) -> None:
        content = _closing_reference_content()
        self.assertIn("**Every item `done` does not mean every item was worked.**", content)
        self.assertIn("**A phase `done` carrying a `blocked_reason` was skipped on purpose.**", content)
        self.assertIn("**No `blocked_reason` anywhere means nothing was RECORDED as blocked.**", content)
        self.assertIn("**Do not tick the remaining items to finish the list.**", content)

    def test_the_basis_vocabulary_is_the_one_already_shipped(self) -> None:
        """Reused from the handover page rather than coined again.

        Both answer the same question -- what could be read -- and two words
        for one idea is a defect this repository has paid for before.
        """

        content = _closing_reference_content()
        for state in HANDOVER_QUIZ_BASIS:
            with self.subTest(state=state):
                self.assertIn(f"`{state}`", content)

    def test_the_page_says_omh_never_observes_the_landing(self) -> None:
        content = _closing_reference_content()
        self.assertIn("**Landing the change happens outside OMH.**", content)
        self.assertIn("`prepared_not_observed` and is not a landing", content)


def _verdict_map_rows() -> list[dict[str, object]]:
    """The closing page's outcome table, as the store would receive each row."""
    lines = _closing_reference_content().split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("| Closing outcome |"))
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        outcome, kind, verdict, findings, blocker = (cell.strip() for cell in line.strip("|").split("|"))
        rows.append(
            {
                "outcome": outcome,
                "kind": kind.strip("`"),
                "verdicts": re.findall(r"`([^`]+)`", verdict),
                "findings": [] if findings == "empty" else [findings],
                "blocks": blocker == "yes",
            }
        )
    return rows


def _row(kind: str, verdict: str, findings: list[str]) -> dict[str, object]:
    return {
        "kind": kind,
        "item": 1,
        "verdict": verdict,
        "summary": "closing outcome",
        "findings": findings,
        "claimed_source": "model",
        "claimed_evidence_state": "prepared_not_observed",
        "references": [],
        "revision": "rev",
        "environment": "env",
        "author": "0" * 64,
        "created_at": time.time(),
        "standing": "model_declaration",
        "observed": False,
    }


def _completion(rows: list[dict[str, object]]) -> dict[str, object]:
    checkpoint = {"items": [{"text": "only item"}], "results": rows}
    return _projection(checkpoint, "rev", "env")["completion"]


class ClosingVerdictMapTest(unittest.TestCase):
    """The page's outcome table against the store that takes the declaration."""

    def test_every_mapped_verdict_and_kind_is_one_the_store_accepts(self) -> None:
        rows = _verdict_map_rows()
        self.assertEqual({row["kind"] for row in rows}, set(KINDS))
        self.assertTrue(all(row["verdicts"] for row in rows))
        self.assertEqual({verdict for row in rows for verdict in row["verdicts"]}, {"PASS", "HOLD", "BLOCK"})
        for row in rows:
            for verdict in row["verdicts"]:
                with self.subTest(outcome=row["outcome"], verdict=verdict):
                    declared = {k: v for k, v in _row(row["kind"], verdict, row["findings"]).items()
                                if k in RESULT_FIELDS}
                    _result(declared, 1)

    def test_the_outcome_words_the_page_names_are_refused_as_verdicts(self) -> None:
        self.assertIn("`ship`, `no_ship`, `pass` and `fail` are not verdicts", _closing_reference_content())
        for word in ("ship", "no_ship", "pass", "fail"):
            with self.subTest(word=word):
                declared = {k: v for k, v in _row("review", word, []).items() if k in RESULT_FIELDS}
                with self.assertRaises(CompletionValidationError):
                    _result(declared, 1)

    def test_the_blocker_column_is_what_the_projection_computes(self) -> None:
        for row in _verdict_map_rows():
            for verdict in row["verdicts"]:
                with self.subTest(outcome=row["outcome"], verdict=verdict):
                    rows = [_row(row["kind"], verdict, row["findings"])]
                    if row["kind"] != "verification":
                        rows.insert(0, _row("verification", "PASS", []))
                    completion = _completion(rows)
                    self.assertEqual(completion["blockers"], [1] if row["blocks"] else [])
                    self.assertEqual(completion["missing"], [])
                    self.assertEqual(completion["declarations_complete"], not row["blocks"])

    def test_the_prose_around_the_table_holds(self) -> None:
        # No verification row: the item is missing, whatever review says.
        completion = _completion([_row("review", "PASS", [])])
        self.assertEqual(completion["missing"], [1])
        self.assertFalse(completion["declarations_complete"])
        # A later row for the same item and kind replaces the earlier one.
        completion = _completion(
            [_row("verification", "PASS", []), _row("review", "BLOCK", ["finding"]), _row("review", "PASS", [])]
        )
        self.assertEqual(completion["blockers"], [])
        self.assertTrue(completion["declarations_complete"])
        self.assertEqual(completion["status"], "not_verified")


class ClosingReferenceReachabilityTest(unittest.TestCase):
    def test_the_skill_body_points_at_the_reference(self) -> None:
        from omh.skills.packaging import builtin_skill_templates

        bodies = {template.name: template.content for template in builtin_skill_templates()}
        self.assertIn(TODO_CHECKLIST_CLOSING_REFERENCE_PATH, bodies["todo-checklist"])

    def test_the_reference_is_rendered_for_the_checklist_skill(self) -> None:
        paths = {
            template.relative_path
            for template in todo_checklist_reference_templates()
            if template.skill_name == "todo-checklist"
        }
        self.assertIn(TODO_CHECKLIST_CLOSING_REFERENCE_PATH, paths)


if __name__ == "__main__":
    unittest.main()
