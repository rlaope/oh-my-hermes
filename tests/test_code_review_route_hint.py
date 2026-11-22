"""A request to review a code change gets the code-review route hint first, in Hermes too.

The router dispatches these to code-review (`CODE_REVIEW_REQUEST_GUARD`), but
the per-turn `[OMH Route Hint]` the plugin injects never named code-review, so
the skill never loaded in a real session. Hint workflows measured on
1399085ef, before this hint:

benchmark review task (below): visual-qa (visual_qa_gate), feedback-triage (customer_signal)
review this diff for bugs: visual-qa, ulw-work (coding_delivery)
can you review my PR?: ulw-work
이 diff 리뷰해줘: visual-qa, ulw-work
코드 리뷰 해줘: ulw-work
does this change introduce a bug?: feedback-triage

One word each matched: "diff" is a visual-qa token (pixel or screenshot diff),
"bug"/"버그" a customer-signal cue, "review"/"PR"/"리뷰" coding delivery. The hint
now reads the router's guard itself (`code_review_cues`, which the router
imports), puts code-review first and stands those three rules down.

`tests/fixtures/code_review_route_hint.json` holds the base hint workflows of 44
look-alikes saved before the edit (must_not_change) and 25 negatives written
after it (fresh_negatives). Every one keeps its base hints.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package
from _standalone_bundle import run_in_no_package_host

load_local_package()

from omh.plugin_bundle.omh import awareness  # noqa: E402
from omh.plugin_bundle.omh.awareness import (  # noqa: E402
    awareness_route_hint,
    awareness_route_hint_context,
)
from omh.plugin_bundle.omh import code_review_cues  # noqa: E402
from omh.routing import policy  # noqa: E402
from omh.wrapper.contract import build_chat_interaction_payload  # noqa: E402

BENCHMARK_TASK = (
    "Review a code change. The unified diff is in diff.patch in the current directory, and the files as they "
    "are after the change are under context/ (you may read any of them).\n"
    "Decide whether the change introduces a bug.\n"
    "End your reply with exactly one line in one of these two forms, and nothing after it:\n"
    "VERDICT: clean\n"
    "VERDICT: bug <path>:<line>"
)
MEASURED_ROWS = (
    BENCHMARK_TASK,
    "review this diff for bugs",
    "can you review my PR?",
    "이 diff 리뷰해줘",
    "코드 리뷰 해줘",
    "does this change introduce a bug?",
)
# The router's own positives (`test_code_review_request_routing.POSITIVE` less the six above).
MORE_REVIEW_REQUESTS = (
    "이 PR 버그 있는지 봐줘",
    "check this patch for regressions",
    "review this PR",
    "review PR 1234 for bugs",
    "find bugs in this diff",
    "이 커밋 리뷰해 주세요",
    "이 diff에서 버그 찾아줘",
    "review this diff for bugs. The context is in the PR description.",
    "can you review my PR? It changes how Hermes stores memory.",
)
# A review sentence beside a code edit: the router keeps it a fix (direct-coding guard), and so does the hint.
REVIEW_AND_FIX = (
    "review this PR. then fix the bug in auth.py",
    "이 diff 리뷰해줘. 로그인 버그 고쳐줘",
)
STAND_DOWN_RULES = {"visual_qa_gate", "customer_signal", "coding_delivery"}
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "code_review_route_hint.json").read_text(encoding="utf-8"))

_HOST_CODE = """
import importlib
awareness = importlib.import_module("hermes_plugin_omh.awareness")
rows = [[h.get("workflow") for h in awareness.awareness_route_hint(m).get("hints", [])] for m in json.loads(MESSAGES_JSON)]
print(json.dumps({"omh_spec": omh_spec, "rows": rows}))
"""


def _hints(message: str) -> list[dict]:
    return awareness_route_hint(message)["hints"]


def _workflows(message: str) -> list[str]:
    return [hint["workflow"] for hint in _hints(message)]


class CodeReviewRouteHintTests(unittest.TestCase):
    def test_measured_rows_get_code_review_first(self) -> None:
        for message in MEASURED_ROWS + MORE_REVIEW_REQUESTS:
            with self.subTest(message=message[:60]):
                payload = awareness_route_hint(message)
                self.assertEqual(payload["selected_workflow"], "code-review")
                self.assertEqual(payload["hints"][0]["id"], "code_review_request")

    def test_the_rules_one_word_matched_stand_down(self) -> None:
        for message in MEASURED_ROWS + MORE_REVIEW_REQUESTS:
            with self.subTest(message=message[:60]):
                ids = {hint["id"] for hint in _hints(message)}
                self.assertFalse(ids & STAND_DOWN_RULES, ids)
                self.assertNotIn("visual-qa", _workflows(message))
                self.assertNotIn("feedback-triage", _workflows(message))

    def test_hint_and_router_agree(self) -> None:
        for message in MEASURED_ROWS + MORE_REVIEW_REQUESTS:
            with self.subTest(message=message[:60]):
                route = build_chat_interaction_payload(message, source="discord")["route"]
                self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "code-review"))

    def test_the_hint_and_router_read_one_guard(self) -> None:
        self.assertIs(policy.code_review_request_guard_applies, code_review_cues.code_review_request_guard_applies)
        self.assertIs(policy.code_review_request_sentence, code_review_cues.code_review_request_sentence)

    def test_the_rendered_hint_carries_the_review_rules(self) -> None:
        # Measured live, the model never called skill_view on this task, so the rules ride in the hint itself.
        text = awareness_route_hint_context(BENCHMARK_TASK)
        self.assertIn("selected=code-review", text)
        first = next(line for line in text.splitlines() if line.strip().startswith("first_response_shape="))
        for phrase in (
            "step-by-step trace",
            "concrete input or state",
            "path:line",
            "wrong output or state",
            "read the callers and tests the diff relies on",
            "drop a finding",
            "guarded, intended or documented",
            "theoretical only",
            "End the review body with a `Not checked:` line",
            "required last line, still comes last",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, first)
        # The skill stays one optional clause at the end, not a precondition the rules depend on.
        self.assertTrue(first.rstrip().endswith("skill_view(name='omh-code-review')."), first)
        self.assertNotIn("Load the code-review skill first", first)

    def test_the_hint_rules_come_from_the_review_method_sources(self) -> None:
        # One copy of the rules: each key phrase of the hint must still read in the drop gate and evidence
        # threshold (`review_methods`) or the shared Not checked bar, so an edit there shows up here.
        from omh.skills import catalog_definitions, review_methods

        method = " ".join(review_methods._FINDING_VALIDATION.split()).lower()
        hint = awareness._CODE_REVIEW_REQUEST_RESPONSE.lower()
        for phrase in (
            "step-by-step trace",
            "concrete input or state",
            "wrong output or state",
            "callers",
            "tests",
            "guard",
            "intended",
            "documented",
            "theoretical only",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, hint)
                self.assertIn(phrase, method)
        self.assertIn("Not checked", awareness._CODE_REVIEW_REQUEST_RESPONSE)
        self.assertIn("`Not checked`", catalog_definitions._NOT_CHECKED_BAR)

    def test_a_review_beside_a_code_edit_keeps_its_hints(self) -> None:
        for message in REVIEW_AND_FIX:
            with self.subTest(message=message):
                self.assertNotEqual(awareness_route_hint(message)["selected_workflow"], "code-review")
                self.assertNotEqual(
                    build_chat_interaction_payload(message, source="discord")["route"]["selected_skill"], "code-review"
                )

    def test_without_the_router_a_code_edit_sentence_stands_the_hint_down(self) -> None:
        # The standalone fallback of `_code_review_request_hint_applies`, forced in this process.
        original = awareness._router_guard
        awareness._router_guard = lambda name: None
        try:
            for message in REVIEW_AND_FIX:
                with self.subTest(message=message):
                    self.assertFalse(awareness._code_review_request_hint_applies(message))
            for message in MEASURED_ROWS:
                with self.subTest(message=message[:60]):
                    self.assertTrue(awareness._code_review_request_hint_applies(message))
        finally:
            awareness._router_guard = original

    def test_a_workflow_invoked_by_name_keeps_its_own_hint(self) -> None:
        self.assertEqual(_hints("use code-review on this diff")[0]["id"], "direct_workflow_invocation")

    def test_must_not_change_fixture_keeps_base_hints(self) -> None:
        for row in FIXTURE["must_not_change"]:
            with self.subTest(message=row["message"]):
                self.assertEqual(_workflows(row["message"]), row["hints"])

    def test_fresh_negatives_keep_base_hints(self) -> None:
        for row in FIXTURE["fresh_negatives"]:
            with self.subTest(message=row["message"]):
                self.assertEqual(_workflows(row["message"]), row["hints"])
                self.assertNotIn("code-review", _workflows(row["message"]))

    def test_a_host_without_the_package_gives_the_same_hint(self) -> None:
        messages = MEASURED_ROWS + MORE_REVIEW_REQUESTS + REVIEW_AND_FIX
        with TemporaryDirectory() as tmp:
            observed = run_in_no_package_host(
                _HOST_CODE.replace("MESSAGES_JSON", repr(json.dumps(messages))), cwd=Path(tmp)
            )
        self.assertFalse(observed["omh_spec"])
        for message, standalone in zip(messages, observed["rows"], strict=True):
            with self.subTest(message=message[:60]):
                self.assertEqual(standalone, _workflows(message))


if __name__ == "__main__":
    unittest.main()
