"""The commands the coding-core skill references name must exist with the options they quote.

A reviewer runs what the shipped text says, so each command line a reference
gives is compared with the parser that serves it, and each payload field the
briefing reference lists is compared with the validator that reads it.
"""

from __future__ import annotations

import argparse
import re
import unittest
from pathlib import Path

from omh.commands.main import build_parser
from omh.skills.packaging import builtin_skill_reference_templates

_BRIEFING_SOURCE = Path(__file__).resolve().parents[1] / "src" / "workflows" / "research_briefing.py"


def _subparser(parser: argparse.ArgumentParser, *path: str) -> argparse.ArgumentParser:
    for name in path:
        action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        parser = action.choices[name]
    return parser


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {option for action in parser._actions for option in action.option_strings}


def _reference(skill: str, relative: str) -> str:
    return next(
        t.content for t in builtin_skill_reference_templates() if t.skill_name == skill and t.relative_path == relative
    )


class CodingCoreSkillCommandTests(unittest.TestCase):
    def test_briefing_reference_quotes_the_renderer_it_runs(self) -> None:
        text = _reference("research", "references/briefing-format.md")
        options = _options(_subparser(build_parser(), "hermes", "briefing"))
        for flag in ("--input", "--markdown", "--page"):
            self.assertIn(flag, options)
            self.assertIn(flag, text)
        self.assertIn("omh hermes briefing", text)

    def test_briefing_reference_example_is_a_payload_the_validator_accepts(self) -> None:
        import json

        from omh.workflows.research_briefing import (
            BRIEFING_CLAIM_BOUNDARY,
            render_research_briefing_markdown,
            render_research_briefing_page,
            research_briefing_errors,
        )

        text = _reference("research", "references/briefing-format.md")
        block = re.search(r"```json\n(.*?)\n```", text, re.S)
        self.assertIsNotNone(block)
        payload = json.loads(block.group(1))
        self.assertEqual(research_briefing_errors(payload), [])
        self.assertEqual(payload["claim_boundary"], BRIEFING_CLAIM_BOUNDARY)
        self.assertIn("# " + payload["title"], render_research_briefing_markdown(payload))
        self.assertIn(payload["title"], render_research_briefing_page(payload))
        self.assertIn("first five errors", text)

    def test_a_briefing_without_a_title_is_reported_not_a_traceback(self) -> None:
        import json
        import tempfile

        from _cli_harness import run_cli
        from omh.workflows.research_briefing import research_briefing_errors

        text = _reference("research", "references/briefing-format.md")
        payload = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))
        del payload["title"]
        self.assertTrue(any("title" in issue for issue in research_briefing_errors(payload)))
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "b.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            status, _, stderr = run_cli(["hermes", "briefing", "--input", str(source), "--markdown", str(Path(tmp) / "o.md")])
        self.assertNotEqual(status, 0)
        self.assertIn("title", stderr)

    def test_project_terms_reference_quotes_the_capture_commands(self) -> None:
        text = _reference("context", "references/project-terms.md")
        parser = build_parser()
        capture = _options(_subparser(parser, "memory", "domain-capture"))
        for flag in ("--from-file", "--stage"):
            self.assertIn(flag, capture)
            self.assertIn(flag, text)
        self.assertIn("omh --scope project memory domain-review", text)
        self.assertIn("omh memory project-identity init", text)
        self.assertIn("--scope", _options(parser))
        _subparser(parser, "memory", "domain-review")
        _subparser(parser, "memory", "domain-approve")
        init = _subparser(parser, "memory", "project-identity")
        self.assertIn("init", next(a for a in init._actions if isinstance(a, argparse._SubParsersAction)).choices)

    def test_search_budget_text_matches_what_omh_search_does(self) -> None:
        guidance = _reference("research", "references/search-method.md")
        self.assertNotIn("each wave is a new plan", guidance)
        evidence = _reference("research", "references/evidence-records.md")
        self.assertIn("accepts one `plan` per host request", evidence)
        self.assertIn("`invalid_budget`", evidence)
        self.assertIn("research_progress/v1", evidence)

    def test_advisor_reference_uses_flags_the_vendors_document(self) -> None:
        text = _reference("ask", "references/cli-advisors.md")
        for token in ('claude -p "<question>" --tools Read,Grep,Glob', "codex exec --sandbox read-only --skip-git-repo-check"):
            self.assertIn(token, text)
        self.assertNotIn("--allowedTools Read", text)


if __name__ == "__main__":
    unittest.main()
