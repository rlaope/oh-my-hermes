"""Cold-start cost contracts for the chat router and the dag-ulw cue module.

A fresh Hermes process (one-shot ``chat -q``, cron, a delegated child) pays the plugin's imports before its first
reply. Two of them were measured as the largest avoidable costs: the router importing the whole loop engine for one
command check, and ``dag_ulw_cues`` compiling every one of its patterns at import while a turn reads a few dozen.
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
import unittest


def _run(code: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


class RouterImportCostTests(unittest.TestCase):
    def test_importing_the_router_does_not_load_the_loop_engine(self) -> None:
        loaded = _run(
            """
            import sys
            import omh.routing.chat
            print(sorted(m for m in sys.modules if m.endswith(("goal_loop", "goal_ledger"))))
            """
        )
        self.assertEqual(loaded, "[]")

    def test_the_loop_command_check_is_one_function_in_both_places(self) -> None:
        from omh.routing import chat
        from omh.workflows import goal_loop, loop_command

        self.assertIs(chat.explicit_loop_invocation_signal, loop_command.explicit_loop_invocation_signal)
        self.assertIs(goal_loop.explicit_loop_invocation_signal, loop_command.explicit_loop_invocation_signal)
        self.assertIs(goal_loop.LOOP_COMMAND_RE, loop_command.LOOP_COMMAND_RE)
        self.assertIs(goal_loop.OMH_LOOP_COMMAND_RE, loop_command.OMH_LOOP_COMMAND_RE)

    def test_the_loop_command_reading_is_unchanged(self) -> None:
        from omh.workflows.loop_command import explicit_loop_invocation_signal as signal

        for text in ("loop fix the flaky tests", "/loop", "$loop go", "./loop x", "omh loop ship it", "OMH 루프 시작"):
            with self.subTest(text=text):
                self.assertTrue(signal(text))
        for text in ("", "   ", "loophole in the parser", "a loop over the files", "omh looped", "slash /loop later"):
            with self.subTest(text=text):
                self.assertFalse(signal(text))


class DagUlwCuePatternTests(unittest.TestCase):
    def test_importing_the_module_compiles_none_of_its_patterns(self) -> None:
        compiled = _run(
            """
            import omh.plugin_bundle.omh.dag_ulw_cues as m
            lazy = [v for v in vars(m).values() if isinstance(v, m._LazyPattern)]
            print(len(lazy), sum(v._compiled is not None for v in lazy))
            """
        )
        count, already = (int(part) for part in compiled.split())
        self.assertGreater(count, 100)
        self.assertEqual(already, 0)

    def test_a_lazy_pattern_answers_like_the_compiled_one(self) -> None:
        from omh.plugin_bundle.omh import dag_ulw_cues

        lazy = dag_ulw_cues._lazy_compile(r"(?P<w>b+)|x", re.IGNORECASE)
        real = re.compile(r"(?P<w>b+)|x", re.IGNORECASE)
        text = "aBb x bbb"
        self.assertEqual(lazy.pattern, real.pattern)
        self.assertEqual(lazy.flags, re.IGNORECASE)
        self.assertEqual(lazy.search(text).span(), real.search(text).span())
        self.assertEqual(lazy.match("bb!").group("w"), real.match("bb!").group("w"))
        self.assertIsNone(lazy.fullmatch(text))
        self.assertEqual([m.span() for m in lazy.finditer(text)], [m.span() for m in real.finditer(text)])
        self.assertEqual(lazy.findall(text), real.findall(text))
        self.assertEqual(lazy.split(text), real.split(text))
        self.assertEqual(lazy.sub("-", text, count=1), real.sub("-", text, count=1))

    def test_every_module_pattern_compiles(self) -> None:
        from omh.plugin_bundle.omh import dag_ulw_cues

        lazy = {name: v for name, v in vars(dag_ulw_cues).items() if isinstance(v, dag_ulw_cues._LazyPattern)}
        for name, pattern in lazy.items():
            with self.subTest(pattern=name):
                self.assertIsInstance(re.compile(pattern.pattern, pattern.flags), re.Pattern)


if __name__ == "__main__":
    unittest.main()
