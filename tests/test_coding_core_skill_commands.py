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

    def test_briefing_reference_lists_the_payload_fields_the_validator_reads(self) -> None:
        text = _reference("research", "references/briefing-format.md")
        sentence = re.search(r"top-level fields are (.*?)\. ", text, re.S)
        self.assertIsNotNone(sentence)
        fields = re.findall(r"`([a-z_]+)`", sentence.group(1))
        self.assertGreaterEqual(len(fields), 10)
        source = _BRIEFING_SOURCE.read_text(encoding="utf-8")
        for field in fields:
            self.assertRegex(source, rf'["\']{field}["\']', field)

    def test_project_terms_reference_quotes_the_capture_commands(self) -> None:
        text = _reference("context", "references/project-terms.md")
        parser = build_parser()
        capture = _options(_subparser(parser, "memory", "domain-capture"))
        for flag in ("--from-file", "--stage"):
            self.assertIn(flag, capture)
            self.assertIn(flag, text)
        for command in ("domain-review", "domain-approve", "project-identity"):
            self.assertIn(f"omh memory {command}", text)
        _subparser(parser, "memory", "domain-review")
        _subparser(parser, "memory", "domain-approve")
        init = _subparser(parser, "memory", "project-identity")
        self.assertIn("init", next(a for a in init._actions if isinstance(a, argparse._SubParsersAction)).choices)


if __name__ == "__main__":
    unittest.main()
