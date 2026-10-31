"""A Hermes host without the `omh` package gives the route hint the router's answer.

Hermes loads the plugin bundle with its own interpreter. A released install
reaches the `omh` package through the `package_site` the installer records;
a bundle copied or linked from a source tree records none, and that host has
no package (the shared gateway the benchmarks run on was one). Until the
workflow-intent classifier moved into the bundle, such a host answered with a
simpler copy in `awareness` that matched raw substrings, so #2440's fix never
reached it: every benchmark wrapper prompt still drew the
`intent=meta_discussion; selected=workflow-learning` hint, about 740 extra
chars on every model call.

These cases run each piece #2440 changed -- whole-word everyday cues, the
code-edit lead, a later command, the OMH-behaviour report, the Korean
whole-word cues, the clause split -- through a real interpreter that cannot
import `omh`, and compare its classifier and route-hint answer with the
package path's in this process. Any difference fails, whichever side moved.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package
from _standalone_bundle import run_in_no_package_host

load_local_package()

from omh.plugin_bundle.omh.awareness import awareness_route_hint  # noqa: E402
from omh.routing.intent import classify_omh_quality_intent, classify_workflow_intent  # noqa: E402

BENCH_WRAPPER = (
    "OMH benchmark task:\n"
    "compute_fee in src/benchapp/pricing.py must now enforce a minimum fee: add a third parameter "
    "minimum_cents: int with no default value. Return JSON with changed_paths.\n\n"
    "Run tests with `/tmp/testenv/bin/python -m pytest -q`; pytest and this package are already installed."
)

PARITY_MESSAGES = (
    BENCH_WRAPPER,
    # Whole-word everyday cues: "test" in "pytest", "term" in "terminal", "log" in "changelog".
    "Use OMH to fix the failing test in billing.py",
    "Through OMH, debug why the terminal output is garbled in my CLI",
    "Ask OMH to bump the version in the changelog and tag a release",
    "I'm an OMH developer testing whether the term handoff confuses users",
    "Explain the OMH route hint vocabulary, what does selected mean?",
    # The code-edit lead, and an edit verb that is not the lead.
    "Have Hermes add a log line when the developer mode flag is set",
    "I asked OMH to fix a test and it opened workflow learning instead",
    "Ask OMH to fix a test and watch it open workflow learning, that's the bug",
    # The OMH-behaviour report, and a later command that makes it a setting.
    "the OMH router misread my last message; let's look at why",
    "OMH picked deep-interview when I only wanted a quick fix; why?",
    "OMH keeps routing my requests to the planner",
    "OMH picked these files; copy them to the backup folder",
    "OMH chose the release-cut workflow; go ahead and tag v1.2",
    "Copy the skills OMH selected into the new profile",
    "our router picked the cheapest shipping option",
    # Korean whole-word cues and code-edit endings.
    "OMH, 로그인 API에 대한 통합 테스트 작성해줘",
    "OMH로 billing.py에서 실패하는 테스트 고쳐줘",
    "OMH 라우팅 테스트해보자",
    "OMH 라우터가 내 로그 질문을 잘못 보냈어",
    "블로그 글에 OMH 워크플로 설명을 넣어줘",
    # Throwaway test messages (owner decision on #2440: no workflow-learning hint).
    "This is a test message for OMH",
)

_HOST_CODE = """
import importlib
awareness = importlib.import_module("hermes_plugin_omh.awareness")
messages = json.loads(MESSAGES_JSON)
rows = []
for message in messages:
    intent = awareness.classify_workflow_intent(message)
    quality = awareness.classify_omh_quality_intent(message)
    hint = awareness.awareness_route_hint(message)
    rows.append({
        "intent": intent.to_dict(),
        "quality_applies": quality.applies,
        "quality_cues": list(quality.matched_cues),
        "hint": [hint.get("intent_class"), hint.get("selected_workflow"),
                 [row.get("workflow") for row in hint.get("hints", [])]],
        "classifier_module": type(intent).__module__,
    })
print(json.dumps({"omh_spec": omh_spec, "omh_loaded": any(n == "omh" or n.startswith("omh.") for n in sys.modules), "rows": rows}))
"""


def _package_row(message: str) -> dict[str, object]:
    intent = classify_workflow_intent(message)
    quality = classify_omh_quality_intent(message)
    hint = awareness_route_hint(message)
    return {
        "intent": intent.to_dict(),
        "quality_applies": quality.applies,
        "quality_cues": list(quality.matched_cues),
        "hint": [hint.get("intent_class"), hint.get("selected_workflow"),
                 [row.get("workflow") for row in hint.get("hints", [])]],
    }


class StandaloneRouteHintParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with TemporaryDirectory() as tmp:
            observed = run_in_no_package_host(
                _HOST_CODE.replace("MESSAGES_JSON", repr(json.dumps(PARITY_MESSAGES))),
                cwd=Path(tmp),
            )
        cls.observed = observed

    def test_the_host_really_has_no_package(self) -> None:
        self.assertFalse(self.observed["omh_spec"])
        self.assertFalse(self.observed["omh_loaded"])
        for row in self.observed["rows"]:
            self.assertEqual(row["classifier_module"], "hermes_plugin_omh.workflow_intent")

    def test_classifier_and_route_hint_match_the_package_path(self) -> None:
        for message, standalone in zip(PARITY_MESSAGES, self.observed["rows"], strict=True):
            with self.subTest(message=message):
                standalone = {key: value for key, value in standalone.items() if key != "classifier_module"}
                self.assertEqual(standalone, _package_row(message))

    def test_the_bench_wrapper_draws_no_meta_hint_without_the_package(self) -> None:
        # The measured symptom (H2H2 load-path finding), pinned on the host
        # where it happened rather than only through parity.
        bench = self.observed["rows"][0]
        self.assertNotEqual(bench["intent"]["intent_class"], "meta_discussion")
        self.assertNotIn("workflow-learning", bench["hint"][2])


if __name__ == "__main__":
    unittest.main()
