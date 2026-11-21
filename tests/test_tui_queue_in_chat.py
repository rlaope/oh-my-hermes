"""A prompt queued behind the running turn is drawn in the chat, as Claude Code draws one (owner, 2026-11-21).

It sits right above the working row on the prompt band, dim, its images' labels
under it, with `⎿ Queued · <key> to send now · ↑ to edit` under the oldest;
never a `⧗` row over the composer. A prompt with images that the send-now key
cuts in shows its images while it waits, and a steer sent before it that the
stopped turn had not read goes with it, ahead of its text, in one prompt.
"""

from __future__ import annotations

import unittest

from test_tui_image_tokens import SID, ImageTestCase
from omh.tui.gateway import Event
from omh.tui.keys import ENTER, Key


class QueueInChatTests(ImageTestCase):
    def running(self) -> None:
        self.app._on_event(Event("message.start", SID, {}))
        self.hermes.pump()

    def rows(self) -> list[str]:
        return [row.rstrip() for row in self.screen().split("\n")]

    def composer_top(self, rows: list[str]) -> int:
        return next(index for index, row in enumerate(rows) if row.startswith("───"))

    def working_row(self, rows: list[str]) -> int:
        return next(index for index, row in enumerate(rows) if "esc to interrupt" in row)

    def test_a_queued_prompt_is_a_prompt_row_above_the_working_row(self) -> None:
        self.running()
        self.type("/skill-a now")  # a slash command queues
        self.press(Key(ENTER))
        rows = self.rows()
        prompt = rows.index("┃ ❯ /skill-a now")
        self.assertLess(prompt, self.working_row(rows))
        self.assertIn("⎿  Queued · ↑ to edit", rows[prompt + 1])
        self.assertFalse(any(row.startswith("⧗") for row in rows), rows)

    def test_a_queued_prompt_with_an_image_shows_its_image_and_the_send_now_key(self) -> None:
        self.running()
        self.paste_image()
        self.type("look")
        self.press(Key(ENTER))
        rows = self.rows()
        prompt = rows.index("┃ ❯ [Image #1] look")
        self.assertIn("⎿  [Image #1] image_1.png", rows[prompt + 1])
        self.assertIn("Queued · ctrl+j to send now · ↑ to edit", rows[prompt + 2])
        self.assertLess(prompt, self.working_row(rows))
        between = rows[self.working_row(rows) + 1 : self.composer_top(rows)]
        self.assertFalse(any("Queued" in row or "look" in row for row in between), between)

    def test_queued_prompts_keep_their_order_and_count_past_three(self) -> None:
        self.running()
        for word in ("one", "two", "three", "four"):
            self.type(f"/skill-a {word}")
            self.press(Key(ENTER))
        rows = self.rows()
        drawn = [rows.index(f"┃ ❯ /skill-a {word}") for word in ("one", "two", "three")]
        self.assertEqual(drawn, sorted(drawn))
        self.assertNotIn("┃ ❯ /skill-a four", rows)
        self.assertTrue(any(row.strip() == "+1 more" for row in rows), rows)

    def test_the_prompt_band_is_dim(self) -> None:
        self.running()
        self.type("/skill-a now")
        self.press(Key(ENTER))
        self.app._render()
        lines = self.app._queued_rows(80)
        prompt = next(line for line in lines if "".join(span.text for span in line).startswith("┃ ❯ /skill-a"))
        words = next(span for span in prompt if "skill-a" in span.text)
        self.assertEqual(words.style.fg, self.app.theme.dim.fg)  # dim, as a prompt the turn has not taken yet
        self.assertNotEqual(words.style.fg, self.app.theme.muted.fg)  # a sent prompt's colour

    def test_cut_in_shows_its_image_while_it_waits(self) -> None:
        self.running()
        self.paste_image()
        self.type("this one")
        self.press(Key(ENTER, ctrl=True))
        rows = self.rows()
        prompt = rows.index("┃ ❯ [Image #1] this one")
        self.assertIn("⎿  [Image #1] image_1.png", rows[prompt + 1])

    def test_a_steer_the_stopped_turn_had_not_read_goes_ahead_of_the_cut_in(self) -> None:
        self.running()
        self.type("first text")
        self.press(Key(ENTER))  # steers: Hermes queues the redirect as its next prompt
        self.hermes.respond("session.redirect", {"status": "queued"})
        data = self.paste_image()
        self.type("image now")
        self.press(Key(ENTER, ctrl=True))
        self.app._on_event(Event("message.complete", SID, {"text": "", "status": "interrupted"}))
        self.hermes.pump()
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("first text\n[Image #1] image now", [data])])
        self.assertEqual(list(self.app.queued), [])
        self.assertNotIn("not read", self.screen())

    def test_a_stop_with_no_cut_in_still_says_the_steer_was_not_read(self) -> None:
        self.running()
        self.type("first text")
        self.press(Key(ENTER))
        self.hermes.respond("session.redirect", {"status": "queued"})
        self.app.interrupting = True
        self.app._on_event(Event("message.complete", SID, {"text": "", "status": "interrupted"}))
        self.hermes.pump()
        self.assertIn("not read", self.screen())


if __name__ == "__main__":
    unittest.main()
