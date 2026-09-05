"""End-to-end platform simulation: real contract outputs survive posting.

OMH never posts; an adapter takes `messenger_rendering` and sends it. These
tests replay what a minimal Discord/Slack/Telegram adapter would do with REAL
contract outputs (status board body, a long multi-unit brief-shaped body, a
show-prompt-handoff body carrying an inner ``` fence, and a heading/bold/table
body) and assert pure string properties: platform caps respected, fences
balanced per chunk, and dialect rules honored. No network, no wall-clock.
"""

from __future__ import annotations

import unittest

from omh.coding.status_board import (
    CODING_STATUS_BOARD_CLAIM_BOUNDARY,
    status_board_messenger_body,
)
from omh.coding.coding_delegation import build_coding_delegation_payload
from omh.wrapper.contract import (
    build_chat_response_from_delegation,
    messenger_rendering_contract,
)

DISCORD_HARD_CAP = 2000
SLACK_SOFT_CAP = 3000
TELEGRAM_HARD_CAP = 4096


def _fences_balanced(chunk: str) -> bool:
    """CommonMark-shaped pairing: an opening fence is only closed by a run of
    the same character at least as long, with no info string."""
    open_marker = ""
    for line in chunk.splitlines():
        stripped = line.strip()
        if open_marker:
            character = open_marker[0]
            if len(stripped) >= len(open_marker) and stripped == character * len(stripped):
                open_marker = ""
            continue
        for character in ("`", "~"):
            if stripped.startswith(character * 3):
                length = len(stripped) - len(stripped.lstrip(character))
                info = stripped[length:].strip()
                if character == "`" and "`" in info:
                    break
                open_marker = character * length
                break
    return not open_marker


def _lines_outside_fences(chunk: str) -> list[str]:
    lines: list[str] = []
    open_marker = ""
    for line in chunk.splitlines():
        stripped = line.strip()
        if open_marker:
            character = open_marker[0]
            if len(stripped) >= len(open_marker) and stripped == character * len(stripped):
                open_marker = ""
            continue
        opened = False
        for character in ("`", "~"):
            if stripped.startswith(character * 3):
                length = len(stripped) - len(stripped.lstrip(character))
                info = stripped[length:].strip()
                if character == "`" and "`" in info:
                    break
                open_marker = character * length
                opened = True
                break
        if not opened:
            lines.append(line)
    return lines


def _fence_opening_lines(chunk: str) -> list[str]:
    openings: list[str] = []
    open_marker = ""
    for line in chunk.splitlines():
        stripped = line.strip()
        if open_marker:
            character = open_marker[0]
            if len(stripped) >= len(open_marker) and stripped == character * len(stripped):
                open_marker = ""
            continue
        for character in ("`", "~"):
            if stripped.startswith(character * 3):
                length = len(stripped) - len(stripped.lstrip(character))
                info = stripped[length:].strip()
                if character == "`" and "`" in info:
                    break
                open_marker = character * length
                openings.append(stripped)
                break
    return openings


def simulate_discord(test: unittest.TestCase, contract: dict) -> None:
    chunks = contract["chunked_body_texts"]
    test.assertGreaterEqual(len(chunks), 1)
    for chunk in chunks:
        test.assertLessEqual(len(chunk), DISCORD_HARD_CAP)
        test.assertTrue(_fences_balanced(chunk), chunk[:120])


def simulate_slack(test: unittest.TestCase, contract: dict) -> None:
    chunks = contract["chunked_body_texts"]
    test.assertGreaterEqual(len(chunks), 1)
    for chunk in chunks:
        test.assertLessEqual(len(chunk), SLACK_SOFT_CAP)
        test.assertTrue(_fences_balanced(chunk), chunk[:120])
        for line in _lines_outside_fences(chunk):
            test.assertFalse(line.lstrip().startswith("#"), line)
            test.assertNotIn("**", line)
        for opening in _fence_opening_lines(chunk):
            test.assertEqual(set(opening), {opening[0]}, opening)


def simulate_telegram(test: unittest.TestCase, contract: dict) -> None:
    chunks = contract["chunked_body_texts"]
    test.assertGreaterEqual(len(chunks), 1)
    for chunk in chunks:
        test.assertLessEqual(len(chunk), TELEGRAM_HARD_CAP)
        test.assertTrue(_fences_balanced(chunk), chunk[:120])
    hint = contract["platform_hints"]["telegram"]
    test.assertIn("WITHOUT parse_mode", hint)
    test.assertIn("plain text", hint)


def _status_board_body() -> str:
    payload = {
        "schema_version": "omh_coding_status_board/v1",
        "observed_at": "2026-08-03T04:35:00Z",
        "unit_count": 2,
        "running_count": 2,
        "claim_boundary": CODING_STATUS_BOARD_CLAIM_BOUNDARY,
        "units": [
            {
                "label": "api-ratelimit",
                "runtime": "codex",
                "model_label": "gpt-5.6-sol xhigh",
                "status": "running",
                "elapsed_text": "35m",
                "tokens_text": "128,400",
                "session_ref": "019a7b3e",
                "summary": "",
            },
            {
                "label": "research-sweep",
                "runtime": "claude-code",
                "model_label": "opus xhigh",
                "status": "running",
                "elapsed_text": "4m",
                "tokens_text": "unknown",
                "session_ref": "unknown",
                "summary": "",
            },
        ],
    }
    return status_board_messenger_body(payload, render_profile="limited_markdown")


def _long_brief_body() -> str:
    """A long multi-unit brief-shaped body: per-unit sections with headers,
    bold labels, and a fenced evidence excerpt each."""
    sections = []
    for index in range(14):
        sections.append(
            "\n".join(
                (
                    f"### Unit unit-{index:02d}",
                    f"**Owner**: codex (gpt-5.6-sol xhigh); **status**: running; see [session](https://example.test/s/{index}).",
                    "",
                    "```log",
                    f"unit-{index:02d}  targeted tests passed  ({index * 7}s elapsed)",
                    f"unit-{index:02d}  files touched: src/module_{index}.py",
                    "```",
                )
            )
        )
    return "\n\n".join(sections)


def _prompt_handoff_body() -> str:
    """A real show-prompt chat body whose composed prompt embeds a ``` fence,
    so the outer display fence must outgrow it and the inner one must survive
    as content."""
    payload = build_coding_delegation_payload(
        "risky refactor: harden the fence parser",
        source="discord",
        executor_target="claude-code",
        include_message=True,
    )
    payload["prompt_handoff_prompt"] = (
        "Fix the parser. Repro:\n```python\nparse('data')\n```\nKeep the targeted tests green."
    )
    return str(build_chat_response_from_delegation(payload, thread_key="discord:c1:m1")["body"])


def _heading_bold_table_body() -> str:
    return "\n".join(
        (
            "## Rollout report",
            "",
            "The migration is **complete** and verified, details in [the runbook](https://example.test/runbook).",
            "",
            "| Stage | Result |",
            "| --- | --- |",
            "| canary | **passed** |",
            "| fleet | passed |",
            "",
            "### Follow-ups",
            "- monitor error budget",
        )
    )


def _contract(body: str, source: str) -> dict:
    return messenger_rendering_contract(
        visible_prefix="[omh] board",
        first_line="Status update",
        body=body,
        claim_boundary="Metadata only; not execution evidence.",
        render_profile="limited_markdown",
        source=source,
    )


_FIXTURES = {
    "status_board": _status_board_body,
    "long_brief": _long_brief_body,
    "prompt_handoff": _prompt_handoff_body,
    "heading_bold_table": _heading_bold_table_body,
}


class DiscordSimulationTests(unittest.TestCase):
    def test_every_fixture_survives_discord(self) -> None:
        for name, fixture in _FIXTURES.items():
            with self.subTest(fixture=name):
                simulate_discord(self, _contract(fixture(), "discord"))

    def test_the_long_brief_actually_needs_chunking(self) -> None:
        contract = _contract(_long_brief_body(), "discord")
        self.assertGreater(len(contract["body_text"]), contract["chunking"]["max_recommended_chars"])
        self.assertGreater(len(contract["chunked_body_texts"]), 1)


class SlackSimulationTests(unittest.TestCase):
    def test_every_fixture_survives_slack(self) -> None:
        for name, fixture in _FIXTURES.items():
            with self.subTest(fixture=name):
                simulate_slack(self, _contract(fixture(), "slack"))

    def test_the_heading_bold_table_body_is_full_mrkdwn(self) -> None:
        contract = _contract(_heading_bold_table_body(), "slack")
        body_text = contract["body_text"]
        self.assertIn("*Rollout report*", body_text)
        self.assertIn("is *complete* and verified", body_text)
        self.assertIn("<https://example.test/runbook|the runbook>", body_text)
        # The limited profile already converted the table to bullets.
        self.assertNotIn("| --- |", body_text)


class TelegramSimulationTests(unittest.TestCase):
    def test_every_fixture_survives_telegram(self) -> None:
        for name, fixture in _FIXTURES.items():
            with self.subTest(fixture=name):
                simulate_telegram(self, _contract(fixture(), "telegram"))


class PromptHandoffFenceSurvivalTests(unittest.TestCase):
    def test_the_shown_prompt_body_keeps_its_fence_balanced_everywhere(self) -> None:
        body = _prompt_handoff_body()
        # The display fence outgrew the embedded ``` fence, which survives as
        # content inside it.
        self.assertIn("````", body)
        self.assertIn("```python", body)
        self.assertTrue(_fences_balanced(body))
        for source in ("discord", "slack", "telegram"):
            with self.subTest(source=source):
                contract = _contract(body, source)
                for chunk in contract["chunked_body_texts"]:
                    self.assertTrue(_fences_balanced(chunk))


if __name__ == "__main__":
    unittest.main()
