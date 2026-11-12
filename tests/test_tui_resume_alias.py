"""`/resume` is `/sessions`: the menu offers it under its own name, and every form of it runs as /sessions' does.

Measured on a real TUI over Hermes' shared gateway (2026-10-28): `/res` highlighted Hermes' `/compress` (a name
that only contains it), `/resu` offered nothing and its Enter sent it to Hermes, which resolved it to its own
classic-only /resume; and `/sessions <title>` and `/resume <title>` were both refused `4001 not_found`, as the shared
gateway resumes ids only.
"""

from __future__ import annotations

import unittest

from test_tui_catalog import CATALOG, catalog_app
from test_tui_modes import SID, answer, make_app, notices, type_text
from omh.tui import slash
from omh.tui.app import RESUME_REFUSED, SESSION_LIST_LIMIT
from omh.tui.keys import ENTER, Key

# Every command name in the `commands.catalog` of Hermes bf0203a794's shared gateway (skills left out), as a
# throwaway home's gateway answered it on 2026-10-28.
HERMES_NAMES = (
    "agents approvals autoprune battery bg blueprint branch browser btw bundles busy clear codex-runtime compress "
    "config context copy cron curator debug density diff egress export fast focus footer goal handoff hatch heartbeat "
    "help history image import indicator init insights journey kanban learn login logs loop memory moa model mouse new "
    "palette paste personality pet plan platforms plugins profile prompt queue quit reasoning redraw refine reload "
    "reload-mcp reload-skills resume retry review rollback save sessions skills skin snapshot status statusbar steer "
    "stop subgoal subscription suggestions timestamps title tools toolsets topup undo update usage verbose version "
    "voice wake whoami worktree yolo"
).split()
HERMES_CATALOG = {**CATALOG, "pairs": [*CATALOG["pairs"], *([f"/{name}", f"Hermes' /{name}"] for name in HERMES_NAMES)]}
# The only 1-3 character prefixes whose top `/` menu row this change moves, each with its new top row.
INTENDED_TOP_ROWS = {"res": "resume"}


def main_top(prefix: str, pairs: list[tuple[str, str]]) -> str:
    """The top row origin/main a64987c58's `completions` gave `prefix`: the TUI's own names (never an alias), then
    the catalog's, those that start with it before those that only contain it. Kept verbatim as the baseline."""
    local = [command.name for command in slash.COMMANDS if command.route in (slash.LOCAL, slash.RENAMED)]
    seen = set(local)
    gateway = []
    for raw_name, _summary in pairs:
        name = raw_name.lstrip("/")
        if name.lower() in seen or name.lower() in slash._BY_NAME:
            continue
        seen.add(name.lower())
        gateway.append(name)
    offered = local + gateway
    key = prefix.lower()
    ranked = [name for name in offered if name.lower().startswith(key)]
    ranked += [name for name in offered if key in name.lower() and not name.lower().startswith(key)]
    return ranked[0] if ranked else ""


def picker_row(sid: str, title: str, count: int) -> dict:
    """A row as Hermes' shared gateway lists a stored session (`gateway/session_listing.py` `_picker_row`): no
    preview, no last_active."""
    return {"id": sid, "session_id": sid, "resolved_id": sid, "title": title, "source": "tui",
            "started_at": 1_791_900_000.0, "message_count": count, "model": "m", "running": False}


# The attach's `session.list`: the owner's live sessions first, then its stored ones, most recently active first.
LISTED = {"sessions": [
    {"id": "local-1f2e", "title": "", "preview": "", "started_at": 1_791_900_000.0, "message_count": 0, "source": "tui"},
    picker_row("20261027_084038_000003", "Release notes for 4.0.3", 31),
    picker_row("20261026_074038_000006", "Terminal capture driver", 46),
    picker_row("20261011_104038_00000c", "Weekly ops review", 3),
    picker_row("20261004_104038_00000f", "weekly OPS review", 5),  # Hermes keeps a title unique only in its case
    picker_row("20261002_104038_00000d", "terminal CAPTURE driver", 2),
]}
NOT_FOUND = {"code": RESUME_REFUSED, "message": "not_found"}


class MenuTests(unittest.TestCase):
    def names(self, typed: str) -> list[str]:
        return [completion.name for completion in slash.completions(typed, slash.catalog_pairs(HERMES_CATALOG))]

    def test_every_short_prefix_keeps_mains_top_row_but_the_intended_ones(self) -> None:
        # Every 1-3 character prefix of every name a `/` resolves to: the TUI's commands, their aliases, the catalog.
        pairs = slash.catalog_pairs(HERMES_CATALOG)
        names = {name for command in slash.COMMANDS for name in (command.name, *command.aliases)} | set(HERMES_NAMES)
        prefixes = sorted({name[:size] for name in names for size in (1, 2, 3)})
        moved = {}
        for prefix in prefixes:
            offered = slash.completions(prefix, pairs)
            top = offered[0].name if offered else ""
            # A prefix main offered nothing for may now offer names holding its letters in order; main's own
            # top row (the baseline) is what must not move.
            if main_top(prefix, pairs) and top != main_top(prefix, pairs):
                moved[prefix] = top
        self.assertEqual(moved, INTENDED_TOP_ROWS)
        self.assertGreater(len(prefixes), 200)
        for prefix, top in (("c", "copy"), ("e", "export"), ("ex", "export"), ("r", "redraw"), ("re", "redraw"),
                            ("a", "approvals"), ("s", "sessions"), ("se", "sessions"), ("co", "copy")):
            with self.subTest(prefix=prefix):
                self.assertEqual(slash.completions(prefix, pairs)[0].name, top)

    def test_an_alias_is_offered_when_what_is_typed_starts_it_and_is_not_in_the_commands_name(self) -> None:
        sessions = slash.parse_slash("/sessions").command
        self.assertEqual(slash.completions("resu", slash.catalog_pairs(HERMES_CATALOG)),
                         [slash.Completion("resume", sessions.summary)])
        # A start before an inside, then (new) the names holding the letters in order only.
        self.assertEqual(self.names("res")[:3], ["resume", "compress", "egress"])
        self.assertEqual(self.names("res")[3:], ["reload-skills", "reasoning"])
        # The TUI's own names first, then the alias, then the catalog's names that start with what is typed.
        self.assertEqual(self.names("re")[:5], ["redraw", "rewind", "reasoning", "reload-skills", "resume"])
        for alias in ("reset", "clear", "exit", "switch", "q", "s"):
            with self.subTest(alias=alias):
                self.assertNotIn(alias, self.names(alias[:2]))  # no other alias gets a row
        self.assertEqual(self.names("ses")[0], "sessions")  # its own name matches: no alias row
        self.assertNotIn("session", self.names("session"))
        self.assertNotIn("resume", self.names("sum"))  # an alias is offered on a start only
        self.assertNotIn("resume", self.names(""))
        self.assertTrue({"resume", "switch", "exit"} <= slash.known_names(slash.catalog_pairs(HERMES_CATALOG)))

    def test_res_and_resu_complete_to_resume_and_run_as_sessions_does(self) -> None:
        for typed, completed in (("/res", "/resume "), ("/resu", "/resume "), ("/sess", "/sessions ")):
            with self.subTest(typed=typed):
                app, client = catalog_app(HERMES_CATALOG)
                type_text(app, typed)
                self.assertEqual(app._menu_rows()[0][0], completed.strip())
                app._on_input(Key(ENTER))
                self.assertEqual(app.composer.text, completed)
                self.assertEqual(client.calls, [])
                app._on_input(Key(ENTER))
                self.assertEqual(client.calls, [("session.list", {"limit": SESSION_LIST_LIMIT})])


def looked_up(*rows: dict) -> dict:
    """The shared gateway's `session.list {"title": ...}` answer (`gateway/session_controls.py` `list_sessions`): the
    one session with that exact title over the whole store, or none."""
    return {"sessions": [{**row, "root_title": row["title"]} for row in rows], "scope": "stored"}


OLD = picker_row("20260901_090000_000042", "Migrate kanban to dag core", 120)  # past the 50 listed sessions


class TitleTests(unittest.TestCase):
    """`/sessions <arg>` and `/resume <arg>` against a shared gateway, which resumes ids only and looks titles up
    exactly (case and all) through `session.list`'s `title`."""

    def typed(self, line: str, *answers: dict):
        """Type `line`; the refusal answers its resume, then each of `answers` the next call (`{"error": ...}` an
        error)."""
        app, client = make_app()
        type_text(app, line)
        app._on_input(Key(ENTER))
        answer(app, client, error=NOT_FOUND)
        for given in answers:
            answer(app, client, error=given["error"]) if "error" in given else answer(app, client, given)
        return app, client

    def lookup(self, title: str) -> tuple[str, dict]:
        return ("session.list", {"title": title})

    def test_the_gateways_title_lookup_resumes_the_one_session_however_old(self) -> None:
        for line in ("/sessions Migrate kanban to dag core", "/resume Migrate kanban to dag core"):
            with self.subTest(line=line):
                app, client = self.typed(line, looked_up(OLD))
                self.assertEqual(client.calls, [
                    ("session.resume", {"session_id": "Migrate kanban to dag core", "cols": 80}),
                    self.lookup("Migrate kanban to dag core"),
                    ("session.resume", {"session_id": "20260901_090000_000042", "cols": 80}),
                ])
                self.assertIsNone(app.picker)

    def test_a_compressed_lineage_resumes_its_tip_found_by_the_roots_title(self) -> None:
        # `list_sessions` answers the lineage root as `id` and its compression tip as `resolved_id`; the tip's own
        # title may be the root's with a `#N` continuation, and `root_title` keeps the root's.
        tip = {"session_id": "20261027_101010_00f00d", "id": "20261001_090000_000001",
               "resolved_id": "20261027_101010_00f00d", "title": "Long refactor #3", "root_title": "Long refactor",
               "source": "tui", "started_at": 1_791_900_000.0, "message_count": 9, "running": False}
        app, client = self.typed("/resume Long refactor", {"sessions": [tip], "scope": "stored"})
        self.assertEqual(client.calls[-1], ("session.resume", {"session_id": "20261027_101010_00f00d", "cols": 80}))
        self.assertEqual(len(client.calls), 3)

    def test_with_no_exact_title_the_listing_is_scanned_ignoring_case(self) -> None:
        for line, sid in (("/resume RELEASE NOTES for 4.0.3", "20261027_084038_000003"),
                          ("/resume terminal capture DRIVER", None)):  # two differ only in case: none is picked
            with self.subTest(line=line):
                app, client = self.typed(line, looked_up(), LISTED)
                typed = line.split(" ", 1)[1]
                expected = [("session.resume", {"session_id": typed, "cols": 80}), self.lookup(typed),
                            ("session.list", {"limit": SESSION_LIST_LIMIT})]
                if sid:
                    expected.append(("session.resume", {"session_id": sid, "cols": 80}))
                self.assertEqual(client.calls, expected)
                self.assertEqual(app.picker is None, sid is not None)

    def test_a_gateway_that_refuses_or_ignores_title_gets_the_scan(self) -> None:
        for lookup in ({"error": {"code": 4000, "message": "invalid_params"}}, LISTED):  # refused; or listed as usual
            with self.subTest(lookup=str(lookup)[:30]):
                app, client = self.typed("/resume release notes for 4.0.3", lookup, LISTED)
                self.assertEqual(client.calls[-1], ("session.resume", {"session_id": "20261027_084038_000003",
                                                                       "cols": 80}))
        app, client = self.typed("/resume Release notes for 4.0.3", LISTED)  # ignored, with an exact match in it
        self.assertEqual([method for method, _params in client.calls], ["session.resume", "session.list",
                                                                         "session.resume"])
        self.assertEqual(client.calls[-1][1]["session_id"], "20261027_084038_000003")

    def test_a_title_several_sessions_share_ignoring_case_opens_the_picker_filtered_by_it(self) -> None:
        app, client = self.typed("/resume Weekly Ops Review", looked_up(), LISTED)
        self.assertEqual([method for method, _params in client.calls],
                         ["session.resume", "session.list", "session.list"])
        self.assertEqual(app.picker.query, "Weekly Ops Review")
        self.assertEqual([row.id for row in app.picker.visible()],
                         ["20261011_104038_00000c", "20261004_104038_00000f"])
        self.assertEqual(notices(app)[-1], '2 sessions are titled "Weekly Ops Review": pick one.')

    def test_a_title_none_has_opens_the_picker_filtered_by_it_and_sends_nothing_more(self) -> None:
        app, client = self.typed("/resume No such title", looked_up(), LISTED)
        self.assertEqual([method for method, _params in client.calls],
                         ["session.resume", "session.list", "session.list"])
        self.assertEqual(app.picker.query, "No such title")
        self.assertEqual(notices(app)[-1], 'No session is titled "No such title": pick one, or change the filter.')
        self.assertFalse(any(text.startswith("Could not switch") for text in notices(app)))

    def test_an_id_the_owner_refused_or_a_failed_listing_says_the_refusal(self) -> None:
        refused_id = "20261011_104038_00000c"
        cases = (
            (f"/resume {refused_id}", (looked_up(picker_row(refused_id, "Weekly ops review", 3)),), 2),  # the lookup
            (f"/resume {refused_id}", (looked_up(), LISTED), 3),  # the listing has it
            ("/resume Weekly ops review", (looked_up(), {"error": {"code": 5006, "message": "store locked"}}), 3),
        )
        cases += (
            ("/resume Weekly ops review", (looked_up(), {"sessions": []}), 3),  # an empty listing: nothing to pick from
            # Shaped as Hermes' ids, refused, and found by neither lookup: the owner's reason, not a title notice.
            ("/resume 20250101_101010_abcdef", (looked_up(), LISTED), 3),
            ("/resume local-0123456789abcdef", (looked_up(), LISTED), 3),
        )
        for line, answers, sent in cases:
            with self.subTest(line=line, sent=sent):
                app, client = self.typed(line, *answers)
                self.assertEqual(len(client.calls), sent)
                self.assertIsNone(app.picker)
                self.assertTrue(notices(app)[-1].startswith(f"Could not switch to {line.split(' ', 1)[1]} (4001)"))

    def test_an_id_switches_with_no_listing_and_a_pick_or_another_refusal_lists_nothing(self) -> None:
        app, client = make_app()
        type_text(app, "/resume 20261027_084038_000003")
        app._on_input(Key(ENTER))
        answer(app, client, {"session_id": "live-2", "stored_session_id": "20261027_084038_000003", "info": {},
                             "messages": []})
        self.assertNotIn("session.list", [method for method, _params in client.calls])
        app, client = make_app()
        app._switch_session("stored-9")  # what a pick runs: an id the person did not type
        answer(app, client, error=NOT_FOUND)
        type_text(app, "/resume stored-3")
        app._on_input(Key(ENTER))
        answer(app, client, error={"code": 4090, "message": "the session is open in another process"})
        self.assertEqual([method for method, _params in client.calls], ["session.resume", "session.resume"])
        self.assertEqual(len([text for text in notices(app) if text.startswith("Could not switch")]), 2)
        self.assertEqual(app.sid, SID)


if __name__ == "__main__":
    unittest.main()
