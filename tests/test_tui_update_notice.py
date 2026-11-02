"""The OMH TUI's update notice (owner, 2026-11-02): npm's latest oh-my-hermes, asked at most once a day on a thread,
named beside the badge's version while it is newer than the running one.

No test here opens a socket: the fetch is injected, and `fetch_latest` itself
runs against a stand-in opener.
"""

from __future__ import annotations

import http.client
import io
import json
from pathlib import Path
import threading
import unittest
from unittest import mock
from urllib.request import Request

import _local_package  # noqa: F401 - the process-wide temp homes, as every harness that imports it gets
from _test_temp_root import make_test_tempdir
from _tui_lines import line_text
from omh.skin_pack import default_theme, read_update_check_choice, write_update_check_choice
from omh.tui import update_notice
from omh.tui.frame import badge_forms, branch_forms
from omh.tui.git_status import GitState
from omh.tui.modes import info_line
from omh.tui.style import Span, Style
from omh.tui.theme import build_theme
from omh.tui.update_notice import (
    CACHE_SCHEMA,
    INTERVAL_SECONDS,
    LATEST_URL,
    NOT_A_RELEASE,
    UpdateCheck,
    cache_path,
    fetch_latest,
    is_newer,
    read_cache,
    release_version,
    write_cache,
)
from omh.tui.update_notice_switch import HELD_BY_ENV, HELD_BY_LAUNCH_CHECK, HELD_BY_THEME, held_off_by, update_check_off
from _tui_gateway_replay import Scenario, spans
from test_tui_app import NO_TERMIOS, AppTestCase, Step, startup_answers
from test_tui_badge_row import native
from test_tui_modes import make_app

NOW = 1_800_000_000.0
VERSION = "9.9.9"  # the running version every test pins, so nothing here moves with a release
ON = {"OMH_TUI_UPDATE_CHECK": "1"}  # the harnesses hold the check off (`make_app`); these tests turn it on


class Fetch:
    """An injected fetch: answers `answer` (or raises it), counting the asks."""

    def __init__(self, answer: str | BaseException = "10.0.0") -> None:
        self.answer = answer
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


class Home(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(self.enterContext(make_test_tempdir("omh-update-check-"))) / ".omh"

    def checked(self, fetch: Fetch, current: str = VERSION, now: float = NOW) -> UpdateCheck:
        """An UpdateCheck started and, when it asked, with its thread done and its answer taken."""
        check = UpdateCheck(self.home, current, fetch=fetch, now=lambda: now)
        if check.start():
            assert check.thread is not None
            check.thread.join(5)
            self.assertTrue(check.take())
        return check

    def record(self) -> dict:
        return json.loads(cache_path(self.home).read_text(encoding="utf-8"))


class VersionTests(unittest.TestCase):
    def test_a_later_release_is_newer_and_an_equal_or_earlier_one_is_not(self) -> None:
        cases = {
            ("4.0.5", "4.0.4"): True,
            ("4.1.0", "4.0.9"): True,
            ("4.0.10", "4.0.9"): True,  # numbers, not text
            ("5.0.0", "4.99.99"): True,
            ("4.1", "4.0.9"): True,  # a missing part reads as 0
            ("4.0.4", "4.0.4"): False,
            ("4.0.4.0", "4.0.4"): False,
            ("4.0.3", "4.0.4"): False,
            ("3.9.9", "4.0.0"): False,
        }
        for (latest, current), newer in cases.items():
            with self.subTest(latest=latest, current=current):
                self.assertIs(is_newer(latest, current), newer)

    def test_a_pre_release_or_a_tag_on_either_side_is_ignored_rather_than_ordered(self) -> None:
        for latest, current in (("4.1.0-rc.1", "4.0.4"), ("4.0.5-beta", "4.0.4"), ("4.0.5+build.7", "4.0.4"),
                                ("v4.0.5", "4.0.4"), ("4.0.5", "4.0.5.dev1"), ("4.0.5", "4.0.5rc1"),
                                ("", "4.0.4"), ("latest", "4.0.4"), (None, "4.0.4"), (405, "4.0.4")):
            with self.subTest(latest=latest, current=current):
                self.assertFalse(is_newer(latest, current))
        self.assertIsNone(release_version("4.1.0-rc.1"))
        self.assertEqual(release_version("4.0.5"), (4, 0, 5))


class CheckTests(Home):
    def test_a_first_start_asks_once_keeps_the_answer_and_names_a_newer_release(self) -> None:
        fetch = Fetch("10.0.0")
        check = self.checked(fetch)
        self.assertEqual((fetch.calls, check.latest), (1, "10.0.0"))
        self.assertEqual(self.record(), {"schema_version": CACHE_SCHEMA, "checked_at": NOW, "latest": "10.0.0"})

    def test_inside_a_day_the_kept_answer_is_used_and_nothing_is_asked(self) -> None:
        write_cache(self.home, NOW - INTERVAL_SECONDS + 60, "10.0.0")
        fetch = Fetch("11.0.0")
        check = UpdateCheck(self.home, VERSION, fetch=fetch, now=lambda: NOW)
        self.assertFalse(check.start())
        self.assertIsNone(check.thread)
        self.assertEqual((fetch.calls, check.latest, check.take()), (0, "10.0.0", False))

    def test_a_day_on_it_asks_again_showing_the_kept_answer_meanwhile(self) -> None:
        write_cache(self.home, NOW - INTERVAL_SECONDS, "10.0.0")
        gate = threading.Event()
        fetch = Fetch("11.0.0")
        check = UpdateCheck(self.home, VERSION, fetch=lambda: (gate.wait(5), fetch())[1], now=lambda: NOW)
        self.assertTrue(check.start())  # returns while the ask is still waiting: the start is never held for it
        self.assertEqual(check.latest, "10.0.0")
        self.assertFalse(check.take())
        gate.set()
        assert check.thread is not None
        check.thread.join(5)
        self.assertTrue(check.take())
        self.assertEqual((fetch.calls, check.latest, self.record()["latest"]), (1, "11.0.0", "11.0.0"))

    def test_a_kept_answer_dated_in_the_future_is_asked_again(self) -> None:
        write_cache(self.home, NOW + 3600, "10.0.0")
        fetch = Fetch("10.0.1")
        self.assertEqual(self.checked(fetch).latest, "10.0.1")
        self.assertEqual(fetch.calls, 1)

    def test_an_equal_or_older_release_names_nothing(self) -> None:
        for answer in (VERSION, "9.9.8", "1.0.0"):
            with self.subTest(answer=answer):
                cache_path(self.home).unlink(missing_ok=True)
                self.assertEqual(self.checked(Fetch(answer)).latest, "")

    def test_a_failed_ask_says_nothing_keeps_what_was_known_and_counts_as_the_day_s_ask(self) -> None:
        failures = (OSError("offline"), TimeoutError("timed out"), ValueError("bad JSON"),
                    http.client.IncompleteRead(b""), RuntimeError("anything"))
        for error in failures:
            for known in ("", "10.0.0"):
                with self.subTest(error=type(error).__name__, known=known):
                    write_cache(self.home, NOW - 2 * INTERVAL_SECONDS, known)
                    stderr = io.StringIO()
                    with mock.patch("sys.stderr", stderr):
                        check = self.checked(Fetch(error))
                    self.assertEqual(check.latest, known)
                    self.assertEqual(self.record(), {"schema_version": CACHE_SCHEMA, "checked_at": NOW,
                                                     "latest": known, "problem": type(error).__name__})
                    self.assertEqual(stderr.getvalue(), "")
                    self.assertFalse(UpdateCheck(self.home, VERSION, fetch=Fetch(), now=lambda: NOW + 60).start())

    def test_an_answer_that_is_not_a_release_version_is_kept_out(self) -> None:
        write_cache(self.home, NOW - 2 * INTERVAL_SECONDS, "10.0.0")
        check = self.checked(Fetch("11.0.0-rc.1"))
        self.assertEqual(check.latest, "10.0.0")
        self.assertEqual(self.record()["problem"], NOT_A_RELEASE)

    def test_a_cache_this_module_did_not_write_is_no_answer(self) -> None:
        path = cache_path(self.home)
        path.parent.mkdir(parents=True)
        for text in ("{", "[]", json.dumps({"checked_at": NOW, "latest": "10.0.0"}),
                     json.dumps({"schema_version": CACHE_SCHEMA, "checked_at": "today", "latest": "10.0.0"}),
                     json.dumps({"schema_version": CACHE_SCHEMA, "checked_at": True, "latest": "10.0.0"})):
            with self.subTest(text=text):
                path.write_text(text, encoding="utf-8")
                self.assertIsNone(read_cache(self.home))

    def test_a_cache_that_cannot_be_written_still_ends_the_ask_quietly(self) -> None:
        self.home.parent.mkdir(parents=True, exist_ok=True)
        self.home.write_text("a file where the home's directory would be", encoding="utf-8")
        check = self.checked(Fetch("10.0.0"))
        self.assertEqual(check.latest, "10.0.0")


class OffTests(Home):
    def test_on_unless_the_terminal_or_the_saved_choice_turns_it_off(self) -> None:
        self.assertFalse(update_check_off({}, self.home))
        self.assertTrue(update_check_off({"OMH_TUI_UPDATE_CHECK": "0"}, self.home))
        self.assertFalse(update_check_off({"OMH_TUI_UPDATE_CHECK": "1"}, self.home))
        self.assertIsNone(read_update_check_choice(self.home))
        write_update_check_choice(self.home, False)
        self.assertTrue(update_check_off({}, self.home))
        write_update_check_choice(self.home, True)
        self.assertFalse(update_check_off({}, self.home))

    def test_the_tui_asks_nothing_while_it_is_off_or_without_an_omh_home(self) -> None:
        write_update_check_choice(self.home, False)
        cases = {
            "env off": {"OMH_HOME": str(self.home.parent / "other"), "OMH_TUI_UPDATE_CHECK": "0"},
            "saved off": {"OMH_HOME": str(self.home), **ON},
            "no OMH home": ON,
        }
        for label, environ in cases.items():
            with self.subTest(label):
                fetch = Fetch()
                app, _client = make_app(environ=environ, fetch_latest=fetch)
                app._start_update_check()
                self.assertIsNone(app.update_check)
                self.assertEqual(fetch.calls, 0)
        self.assertFalse(cache_path(self.home.parent / "other").exists())

    def asks(self, home: Path) -> int:
        """How many times a TUI on `home` asks npm as it starts."""
        fetch = Fetch()
        app, _client = make_app(environ={"OMH_HOME": str(home), **ON}, fetch_latest=fetch)
        app._start_update_check()
        if app.update_check is not None and app.update_check.thread is not None:
            app.update_check.thread.join(5)
        return fetch.calls

    def test_what_holds_it_off_is_named_in_the_order_it_is_read(self) -> None:
        from omh.maintenance.update_check import write_update_check_policy
        from omh.system.paths import OmhPaths

        self.assertEqual(held_off_by({}, self.home), "")
        write_update_check_policy(OmhPaths(omh_home=self.home, hermes_home=self.home.parent / "hermes"), mode="off")
        self.assertEqual(held_off_by({}, self.home), HELD_BY_LAUNCH_CHECK)
        write_update_check_choice(self.home, False)
        self.assertEqual(held_off_by({}, self.home), HELD_BY_THEME)
        self.assertEqual(held_off_by({"OMH_TUI_UPDATE_CHECK": "0"}, self.home), HELD_BY_ENV)

    def test_the_launch_update_check_chosen_off_turns_it_off_and_never_chosen_leaves_it_on(self) -> None:
        # Owner, 2026-11-02: an explicit `omh update-check` off is respected; read from what is stored, not the default.
        from omh.maintenance.update_check import write_update_check_policy
        from omh.system.paths import OmhPaths

        paths = OmhPaths(omh_home=self.home, hermes_home=self.home.parent / "hermes")
        self.assertFalse(paths.setup_profile_path.exists())
        self.assertEqual(self.asks(self.home), 1, "never chosen: the check is on")
        for mode, asked in (("off", 0), ("notify", 1), ("auto", 1), ("off", 0)):
            with self.subTest(mode=mode):
                write_update_check_policy(paths, mode=mode)
                cache_path(self.home).unlink(missing_ok=True)
                self.assertEqual(self.asks(self.home), asked)
                self.assertEqual(update_check_off({}, self.home), not asked)

    def test_off_chosen_through_the_command_is_respected(self) -> None:
        from _cli_harness import run_cli

        homes = ["--omh-home", str(self.home), "--hermes-home", str(self.home.parent / "hermes")]
        (self.home.parent / "hermes").mkdir(parents=True)
        self.assertEqual(run_cli([*homes, "update-check", "set", "--mode", "off"])[0], 0)
        self.assertTrue(update_check_off({}, self.home))
        self.assertEqual(self.asks(self.home), 0)

    def test_a_setup_profile_without_a_recorded_mode_is_never_chosen(self) -> None:
        profile = self.home / "setup-profile.json"
        profile.parent.mkdir(parents=True, exist_ok=True)
        for record in ({}, {"update_check": {}}, {"update_check": {"mode": "sometimes"}}, {"update_check": "off"}):
            with self.subTest(record=record):
                profile.write_text(json.dumps(record), encoding="utf-8")
                self.assertFalse(update_check_off({}, self.home))

    def test_the_tui_s_own_switch_off_wins_over_a_launch_check_that_is_on(self) -> None:
        from omh.maintenance.update_check import write_update_check_policy
        from omh.system.paths import OmhPaths

        write_update_check_policy(OmhPaths(omh_home=self.home, hermes_home=self.home.parent / "hermes"), mode="notify")
        self.assertTrue(update_check_off({"OMH_TUI_UPDATE_CHECK": "0"}, self.home))
        write_update_check_choice(self.home, False)
        self.assertEqual(self.asks(self.home), 0)

    def test_the_loop_starts_it(self) -> None:
        fetch = Fetch()
        app, _client = make_app(environ={"OMH_HOME": str(self.home), **ON}, fetch_latest=fetch)
        with mock.patch.object(app, "_step", side_effect=RuntimeError("stop")), self.assertRaises(RuntimeError):
            app.run()
        self.assertIsNotNone(app.update_check)
        assert app.update_check is not None and app.update_check.thread is not None
        app.update_check.thread.join(5)
        self.assertEqual(fetch.calls, 1)


class FetchTests(unittest.TestCase):
    """`fetch_latest` against a stand-in opener: what it asks for, and what it keeps of the reply."""

    def opened(self, body: bytes) -> tuple[str, list]:
        handlers: list = []
        requests: list[tuple[Request, float]] = []

        class Opener:
            def open(self, request, timeout):
                requests.append((request, timeout))
                return io.BytesIO(body)

        def build_opener(*given):
            handlers.extend(given)
            return Opener()

        with mock.patch("urllib.request.build_opener", build_opener):
            version = fetch_latest()
        self.assertEqual(len(requests), 1)
        request, timeout = requests[0]
        self.assertEqual((request.full_url, request.get_method(), timeout), (LATEST_URL, "GET", 3.0))
        self.assertTrue(LATEST_URL.startswith("https://registry.npmjs.org/"))
        self.assertIsNone(request.data)  # nothing is sent but the GET
        return version, handlers

    def test_only_the_version_is_read(self) -> None:
        version, _handlers = self.opened(json.dumps({"name": "oh-my-hermes", "version": "4.0.5",
                                                     "readme": "x" * 1000}).encode())
        self.assertEqual(version, "4.0.5")

    def test_a_reply_without_a_version_or_over_the_bound_raises(self) -> None:
        for body in (b"{}", b"[]", json.dumps({"version": 5}).encode(), b"not json",
                     b"{" + b" " * update_notice.MAX_RESPONSE_BYTES + b"}"):
            with self.subTest(body=body[:20]):
                with self.assertRaises(ValueError):
                    self.opened(body)

    def test_a_redirect_is_followed_only_to_https_on_the_registry_s_host(self) -> None:
        _version, handlers = self.opened(json.dumps({"version": "4.0.5"}).encode())
        redirects = [handler for handler in handlers if hasattr(handler, "redirect_request")]
        self.assertEqual(len(redirects), 1)
        request = Request(LATEST_URL)
        for target, followed in (("https://registry.npmjs.org/oh-my-hermes/4.0.5", True),
                                 ("https://registry.npmjs.org.example.com/x", False),
                                 ("https://example.com/oh-my-hermes/latest", False),
                                 ("http://registry.npmjs.org/oh-my-hermes/latest", False)):
            with self.subTest(target=target):
                answer = redirects[0].redirect_request(request, None, 302, "Found", {}, target)
                self.assertEqual(answer is not None, followed)


class InfoLineTests(Home):
    """The notice goes beside the badge's version and narrows away with it, before the branch name is cut."""

    THEME = build_theme(default_theme(), "#0D1117")
    RIGHT = ((Span("deepseek-v4.1-flash · ctx 12% · effort high", THEME.muted),),
             (Span("ctx 12% · effort high", THEME.muted),))
    STATE = GitState("omh/terminology-unification", 3, 128)
    NOTICE = ((Span("v10.0.0 available", THEME.warn), Span(" · omh update", THEME.hint)),
              (Span("↑ v10.0.0", THEME.warn),))

    ROW = ((Span("✳ background  terminal(make test)  8s", THEME.label),), (Span("✳ background  8s", THEME.label),))

    def line(self, width: int, background: tuple = ()) -> str:
        word, accent = native("spectrum", "#0D1117")
        return line_text(info_line(mode="normal", width=width, theme=self.THEME, right=self.RIGHT,
                                   badge=badge_forms(self.THEME, accent, word, Style(fg="#C3D2E3"), VERSION),
                                   branch=branch_forms(self.STATE, self.THEME), background=background,
                                   notice=self.NOTICE))

    def check(self, widths: dict, background: tuple = ()) -> None:
        for width, (left, right) in widths.items():
            with self.subTest(width=width):
                text = self.line(width, background)
                self.assertLessEqual(len(text), width)
                self.assertEqual(text.rstrip() if not right else text[: len(left)], left)
                self.assertTrue(text.endswith("   " + right) if right else text == left, text)

    def test_the_long_notice_goes_first_and_the_short_one_goes_with_the_version(self) -> None:
        # Owner, 2026-11-02: the notice is less live than anything else on the line, so its long form is the first
        # to go; `↑ v10.0.0` stays beside the version through the right side's shortening and goes with it.
        branch = "branch:omh/terminology-unification | !3 ?128"  # 44 cells
        noticed = "[⚚ OMH Native v9.9.9]  v10.0.0 available · omh update  "  # 21, 2, 30 and 2 cells
        held = "[⚚ OMH Native v9.9.9]  ↑ v10.0.0  "  # 21, 2, 9 and 2 cells
        badge = "[⚚ OMH Native]  "
        cut24 = "branch:omh/terminology-unifica… | !3 ?128"
        full, short = "deepseek-v4.1-flash · ctx 12% · effort high", "ctx 12% · effort high"
        self.check({
            145: (noticed + branch, full),
            144: (held + branch, full),  # the long form goes first, before the right side shrinks
            124: (held + branch, full),
            123: (held + branch, short),  # then the right side's fields, the short form kept
            102: (held + branch, short),
            101: (held + branch, ""),
            78: (held + branch, ""),
            77: (badge + branch, ""),  # then the version and the short form, together
            60: (badge + branch, ""),
            59: (badge + cut24, ""),  # then the branch's name is cut
        })

    def test_the_short_notice_stays_through_the_background_row_s_forms(self) -> None:
        branch = "branch:omh/terminology-unification | !3 ?128"
        row, row_short = "✳ background  terminal(make test)  8s", "✳ background  8s"  # 38 and 17 cells: ✳ is wide
        noticed = "[⚚ OMH Native v9.9.9]  v10.0.0 available · omh update  "
        held = "[⚚ OMH Native v9.9.9]  ↑ v10.0.0  "
        full = "deepseek-v4.1-flash · ctx 12% · effort high"
        self.check({
            184: (noticed + branch + "  " + row, full),  # 55, 44, 2, 38, 3 and 43 cells
            183: (held + branch + "  " + row, full),  # the long form goes, the row stays whole
            163: (held + branch + "  " + row, full),
            162: (held + branch + "  " + row_short, full),  # then the row shortens, the short form kept
            142: (held + branch + "  " + row_short, full),
            141: (held + branch, full),  # then the row goes
        }, background=self.ROW)

    def test_on_a_common_terminal_with_a_model_on_the_line_the_short_form_shows(self) -> None:
        self.enterContext(mock.patch("omh.tui.app.__version__", VERSION))
        write_cache(self.home, NOW, "10.0.0")
        for cols in (120, 100):
            with self.subTest(cols=cols):
                app, _client = make_app(cols=cols, environ={"OMH_HOME": str(self.home), **ON}, fetch_latest=Fetch(),
                                        wall_clock=lambda: NOW)
                app.model, app.context_percent, app.effort = "deepseek/deepseek-v4.1-flash", 37.0, "high"
                app._start_update_check()
                spans = app._info_line(cols)
                row = line_text(spans)
                self.assertTrue(row.startswith("  [⚚ OMH Native v9.9.9]  ↑ v10.0.0  "), row)
                self.assertIn("ctx", row)  # beside the model and the context, not instead of them
                self.assertEqual({span.text: span.style for span in spans}["↑ v10.0.0"], app.theme.warn)

    def test_the_tui_says_it_beside_the_badge_in_the_warning_colour(self) -> None:
        self.enterContext(mock.patch("omh.tui.app.__version__", VERSION))
        write_cache(self.home, NOW, "10.0.0")
        app, _client = make_app(cols=120, environ={"OMH_HOME": str(self.home), **ON}, fetch_latest=Fetch(),
                                wall_clock=lambda: NOW)
        app._start_update_check()
        row = app._info_line(120)
        self.assertTrue(line_text(row).startswith("  [⚚ OMH Native v9.9.9]  v10.0.0 available · omh update"),
                        line_text(row))
        styles = {span.text: span.style for span in row}
        self.assertEqual((styles["v10.0.0 available"], styles[" · omh update"]), (app.theme.warn, app.theme.hint))

    def test_a_thread_s_answer_is_drawn_once_the_loop_takes_it(self) -> None:
        self.enterContext(mock.patch("omh.tui.app.__version__", VERSION))
        app, _client = make_app(cols=120, environ={"OMH_HOME": str(self.home), **ON}, fetch_latest=Fetch("10.0.0"),
                                wall_clock=lambda: NOW)
        app._start_update_check()
        self.assertNotIn("available", line_text(app._info_line(120)))
        assert app.update_check is not None and app.update_check.thread is not None
        app.update_check.thread.join(5)
        app.dirty = False
        app._take_update_check()
        self.assertTrue(app.dirty)
        self.assertIn("v10.0.0 available · omh update", line_text(app._info_line(120)))

    def test_nothing_is_said_when_the_running_version_is_the_latest(self) -> None:
        self.enterContext(mock.patch("omh.tui.app.__version__", VERSION))
        write_cache(self.home, NOW, VERSION)
        app, _client = make_app(cols=120, environ={"OMH_HOME": str(self.home), **ON}, fetch_latest=Fetch(),
                                wall_clock=lambda: NOW)
        app._start_update_check()
        self.assertTrue(line_text(app._info_line(120)).startswith("  [⚚ OMH Native v9.9.9]  "))
        self.assertNotIn("available", line_text(app._info_line(120)))


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class NoRealFetchInTestsTests(AppTestCase):
    """No App the test harnesses build can reach the real `fetch_latest` with the check on: the whole process holds
    it off (`_local_package`), and so do `make_app` and the replay loop's `prepare`."""

    def test_every_harness_holds_the_check_off(self) -> None:
        import os

        home = Path(self.enterContext(make_test_tempdir("omh-update-guard-"))) / ".omh"
        self.assertEqual(os.environ.get("OMH_TUI_UPDATE_CHECK"), "0", "the test process holds it off")
        app, _client = make_app(environ={"OMH_HOME": str(home)})
        self.assertTrue(update_check_off(app.environ, home), "make_app holds it off")
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        self.assertTrue(update_check_off(run.environ, home), "the replay loop's environment holds it off")

    def test_the_real_loop_opens_no_connection_for_it(self) -> None:
        opened: list[tuple] = []
        run = self.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()))
        self.assertTrue(run.environ.get("OMH_HOME"), "an OMH home is set, so only the switch keeps the check off")
        run.terminal.script(Step(b"\x04", when=run.terminal.idle, label="the first frame"))
        started: list[bool] = []
        real_start = UpdateCheck.start

        def start(check: UpdateCheck, wake=None) -> bool:
            started.append(check.fetch is fetch_latest)
            return False if check.fetch is fetch_latest else real_start(check, wake)  # even failing, it asks nothing

        with mock.patch("urllib.request.build_opener", lambda *handlers: opened.append(handlers)), \
                mock.patch.object(UpdateCheck, "start", start):
            self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual((started, opened), ([], []))  # no check was started at all, so none with the real fetch


if __name__ == "__main__":
    unittest.main()
