"""A resumed session's user rows that Hermes wrote itself (a background process or delegation finishing, a notice,
a resumed turn) are drawn as one dim `↳` row, never as a `❯` prompt the person sent; the person's own prompts are
unchanged (owner's decision of 2026-11-12)."""

from __future__ import annotations

import unittest

from test_tui_modes import drawn, make_app
from omh.tui.transcript import NoticeBlock, UserBlock

DELEGATION = (
    "[ASYNC DELEGATION BATCH COMPLETE — deleg_0967bdc4]\nA background fan-out unit you dispatched earlier — 2 "
    "subagent(s) — has finished; its consolidated results are below."
)
PROCESS = "[IMPORTANT: Background process proc_1 completed normally (exit code 0).\nCommand: make test"


def resumed(messages: list[dict]) -> tuple[list[str], list[object]]:
    app, _client = make_app(rows=40, cols=100)
    app._draw_history(messages)
    return drawn(app), list(app.transcript.blocks)


class MachineRowTests(unittest.TestCase):
    def test_a_delegation_result_is_one_dim_row_with_hermes_title_not_a_prompt(self) -> None:
        screen, blocks = resumed([
            {"role": "user", "text": "review the branches"},
            {"role": "assistant", "text": "dispatched"},
            {"role": "user", "text": DELEGATION, "display_kind": "async_delegation_complete",
             "display_metadata": {"display_text": "Subagent Tasks Completed: Review the harness branches (2 tasks)"}},
            {"role": "assistant", "text": "both reviews are in"},
        ])
        page = "\n".join(screen)
        self.assertIn("↳ Subagent Tasks Completed: Review the harness branches (2 tasks)", page)
        self.assertNotIn("ASYNC DELEGATION", page)
        self.assertEqual([b.text for b in blocks if isinstance(b, UserBlock)], ["review the branches"])
        self.assertTrue(any(isinstance(b, NoticeBlock) and b.one_line for b in blocks))
        self.assertFalse([line for line in screen if "❯" in line and "Subagent" in line])

    def test_a_process_notice_without_a_title_takes_the_label(self) -> None:
        screen, blocks = resumed([{"role": "user", "text": PROCESS, "display_kind": "process_complete"},
                                  {"role": "assistant", "text": "tests passed"}])
        self.assertIn("↳ background process finished", "\n".join(screen))
        self.assertFalse([b for b in blocks if isinstance(b, UserBlock)])

    def test_every_hermes_written_kind_is_a_row_not_a_prompt(self) -> None:
        for kind in ("internal_notification", "auto_continue", "model_switch", "personality_switch"):
            with self.subTest(kind=kind):
                _screen, blocks = resumed([{"role": "user", "text": "[System: x]", "display_kind": kind}])
                self.assertFalse([b for b in blocks if isinstance(b, UserBlock)])

    def test_an_untyped_row_with_hermes_exact_opening_is_a_row_too(self) -> None:
        for text, label in ((DELEGATION, "↳ background agent work finished"),
                            (PROCESS, "↳ background process finished")):
            with self.subTest(label=label):
                screen, blocks = resumed([{"role": "user", "text": text}])
                self.assertFalse([b for b in blocks if isinstance(b, UserBlock)])
                self.assertIn(label, "\n".join(screen))

    def test_the_persons_own_prompts_and_skill_lines_stay_prompts(self) -> None:
        for message in ({"role": "user", "text": "fix it"},
                        {"role": "user", "text": "/plan the work", "display_kind": "skill_invocation"},
                        {"role": "user", "text": "go on", "display_kind": "steer"},
                        {"role": "user", "text": "[IMPORTANT: typed by me]"}):
            with self.subTest(message=message):
                _screen, blocks = resumed([message])
                self.assertEqual([type(b) for b in blocks], [UserBlock])


if __name__ == "__main__":
    unittest.main()
