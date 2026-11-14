"""Slash command routing in the OMH TUI."""

from __future__ import annotations

import unittest

from omh.tui import slash


class ParseSlashTests(unittest.TestCase):
    def test_a_known_command_resolves_through_its_alias(self) -> None:
        invocation = slash.parse_slash("/exit")
        self.assertEqual((invocation.command.name, invocation.command.route), ("quit", slash.LOCAL))

    def test_an_unknown_command_passes_through_with_its_argument(self) -> None:
        invocation = slash.parse_slash("/personality  terse --global ")
        self.assertIsNone(invocation.command)
        self.assertEqual(invocation.text, "personality terse --global")

    def test_text_that_only_looks_like_a_command_is_not_one(self) -> None:
        for text in ("hello /new", "/", "//comment", "/usr/bin/env python", "  "):
            with self.subTest(text=text):
                self.assertIsNone(slash.parse_slash(text))

    def test_surrounding_whitespace_is_ignored(self) -> None:
        self.assertEqual(slash.parse_slash("  /history  ").command.name, "history")

    def test_the_tuis_own_commands_and_aliases_resolve_in_any_case_and_keep_the_typed_name(self) -> None:
        # Hermes matches a command whatever its case (slash.exec lowercases the name), so the TUI matches its own.
        for text, name in (("/Rewind", "rewind"), ("/HELP", "help"), ("/EXIT", "quit"), ("/Detail on", "details"),
                           ("/Cost", "cost")):
            with self.subTest(text=text):
                invocation = slash.parse_slash(text)
                self.assertEqual(invocation.command.name, name)
                self.assertEqual(invocation.name, text[1:].split()[0])  # the echo and Hermes get what was typed

    def test_an_unknown_name_in_capitals_is_still_no_command_of_the_tuis(self) -> None:
        self.assertIsNone(slash.parse_slash("/Foo bar").command)


class RouteTableTests(unittest.TestCase):
    def test_names_and_aliases_are_unique_across_the_table(self) -> None:
        names = [name for command in slash.COMMANDS for name in (command.name, *command.aliases)]
        self.assertEqual(len(names), len(set(names)))

    def test_every_route_is_one_of_the_five_owned_kinds(self) -> None:
        for command in slash.COMMANDS:
            with self.subTest(command=command.name):
                self.assertIn(command.route, (slash.LOCAL, slash.HERMES, slash.DROPPED, slash.RENAMED, slash.CLASSIC))
                # A renamed command names the Hermes command it runs, which goes to Hermes as typed.
                self.assertEqual(bool(command.target), command.route == slash.RENAMED)
                if command.target:
                    self.assertIsNone(slash.parse_slash(f"/{command.target}").command)

    def test_commands_that_would_persist_raw_prompts_go_to_hermes(self) -> None:
        for name in ("save", "prompt", "compose"):
            with self.subTest(name=name):
                self.assertEqual(slash.parse_slash(f"/{name}").command.route, slash.HERMES)

    def test_attachments_and_session_switching_run_in_the_tui(self) -> None:
        for name, command in (
            ("image", "image"),
            ("paste", "paste"),
            ("sessions", "sessions"),
            ("switch", "sessions"),
            ("session", "sessions"),
            ("resume", "sessions"),
        ):
            with self.subTest(name=name):
                invocation = slash.parse_slash(f"/{name} x")
                self.assertEqual((invocation.command.name, invocation.command.route), (command, slash.LOCAL))
        names = [c.name for c in slash.completions("", [])]
        self.assertTrue({"image", "paste", "sessions"} <= set(names))

    def test_reload_skills_runs_in_the_tui_under_both_of_hermes_names(self) -> None:
        # `slash.exec` would run it in Hermes' per-session worker, whose rescan the gateway never sees.
        for name in ("reload-skills", "reload_skills"):
            with self.subTest(name=name):
                invocation = slash.parse_slash(f"/{name}")
                self.assertEqual((invocation.command.name, invocation.command.route), ("reload-skills", slash.LOCAL))

    def test_the_network_widget_is_dropped(self) -> None:
        self.assertEqual(slash.parse_slash("/weather").command.route, slash.DROPPED)

    def test_compact_is_claude_codes_name_for_hermes_compress(self) -> None:
        invocation = slash.parse_slash("/compact here 2")
        self.assertEqual((invocation.command.route, invocation.command.target), (slash.RENAMED, "compress"))
        catalog = [("/compress", "Compress conversation context")]
        offered = {c.name: c.summary for c in slash.completions("comp", catalog)}
        self.assertEqual(list(offered), ["compact", "compress"])
        self.assertIn("--preview", offered["compact"])

    def test_what_hermes_shared_gateway_runs_in_a_tui_session_is_not_routed_away(self) -> None:
        # Measured against Hermes bf0203a794's shared gateway: /topup is a read there (`_READ_COMMANDS`), so it goes
        # to Hermes as typed; /config, /tools and the other verbs the gateway child answers are no commands of the
        # TUI's.
        for name in ("config", "tools", "plugins", "stop", "bg", "btw", "branch", "fork", "retry", "undo",
                     "rollback", "reload", "reload-mcp", "compress"):
            with self.subTest(name=name):
                self.assertIsNone(slash.parse_slash(f"/{name}").command)

    def test_topup_is_the_tuis_own_so_it_can_tell_a_shared_gateway_from_the_stdio_entry(self) -> None:
        self.assertEqual(slash.parse_slash("/topup").command.route, slash.LOCAL)

    def test_what_only_hermes_classic_cli_runs_goes_as_typed_but_is_not_offered(self) -> None:
        catalog = [(f"/{name}", name) for name in ("handoff", "worktree", "snapshot", "import", "hatch", "palette")]
        for name in ("handoff", "worktree", "snapshot", "snap", "import", "hatch", "generate-pet", "palette"):
            with self.subTest(name=name):
                self.assertEqual(slash.parse_slash(f"/{name}").command.route, slash.CLASSIC)
        self.assertEqual([c.name for c in slash.completions("", catalog) if c.name in dict(catalog)], [])
        self.assertEqual(slash.catalog_categories({"categories": [{"name": "Session", "pairs": catalog}]}), [])

    def test_ink_timestamps_are_a_dropped_display_setting(self) -> None:
        for name in ("timestamps", "ts"):
            with self.subTest(name=name):
                self.assertEqual(slash.parse_slash(f"/{name} on").command.route, slash.DROPPED)

    def test_hermes_notice_names_the_hermes_door(self) -> None:
        notice = slash.hermes_notice(slash.parse_slash("/voice").command)
        self.assertIn("hermes --tui", notice)


class CompletionTests(unittest.TestCase):
    CATALOG = {
        "pairs": [
            ["/model", "Switch model"],
            ["/moa", "Mixture of agents"],
            ["/new", "Start a new session"],
            ["/voice", "Voice mode"],
            ["bad"],
        ]
    }

    def test_local_commands_lead_and_catalog_follows(self) -> None:
        names = [c.name for c in slash.completions("", slash.catalog_pairs(self.CATALOG))]
        local = [command.name for command in slash.COMMANDS if command.route == slash.LOCAL]
        self.assertEqual(names[: len(local)], local)
        self.assertIn("model", names)
        self.assertIn("moa", names)

    def test_omh_model_is_exact_and_ranks_ahead_of_a_longer_catalog_name(self) -> None:
        # In Hermes' TUI, Enter on `/omh-model` picked the `/omh-model-optimization` completion.
        catalog = [("/omh-model-optimization", "Model optimization skill")]
        self.assertEqual(slash.parse_slash("/omh-model").command.route, slash.LOCAL)
        names = [c.name for c in slash.completions("omh-model", catalog)]
        self.assertEqual(names, ["omh-model", "omh-model-optimization"])

    def test_names_starting_with_the_prefix_lead_and_names_only_containing_it_follow(self) -> None:
        names = [c.name for c in slash.completions("mo", slash.catalog_pairs(self.CATALOG))]
        self.assertEqual(names[:3], ["model", "moa", "omh-model"])  # then names holding the letters in order only

    def test_a_prefix_in_any_case_offers_the_same_names(self) -> None:
        names = [c.name for c in slash.completions("MO", slash.catalog_pairs(self.CATALOG))]
        self.assertEqual(names, [c.name for c in slash.completions("mo", slash.catalog_pairs(self.CATALOG))])
        self.assertEqual(names[:3], ["model", "moa", "omh-model"])

    def test_part_of_a_skill_name_finds_the_skill(self) -> None:
        # Every OMH skill is `omh-*` or `ulw-*`, so a prefix alone never reaches one by its own word.
        catalog = [("/omh-codebase-uml", "Draw UML from the code"), ("/ulw-umbrella", "Umbrella"), ("/uml-sketch", "x")]
        names = [c.name for c in slash.completions("uml", catalog)]
        self.assertEqual(names, ["uml-sketch", "omh-codebase-uml", "ulw-umbrella"])  # `ulw-umbrella` only in order
        self.assertEqual([c.name for c in slash.completions("", catalog)][-3:], ["omh-codebase-uml", "ulw-umbrella", "uml-sketch"])

    def test_catalog_commands_routed_elsewhere_are_not_offered_twice_or_at_all(self) -> None:
        names = [c.name for c in slash.completions("", slash.catalog_pairs(self.CATALOG))]
        self.assertEqual(names.count("new"), 1)
        self.assertNotIn("voice", names)

    def test_malformed_catalog_rows_are_skipped(self) -> None:
        self.assertEqual(slash.catalog_pairs({"pairs": "nope"}), [])
        self.assertEqual(len(slash.catalog_pairs(self.CATALOG)), 4)


class CatalogReaderTests(unittest.TestCase):
    def test_categories_drop_what_the_tui_runs_routes_or_drops_and_then_empty_categories(self) -> None:
        catalog = {
            "categories": [
                {"name": "Session", "pairs": [["/new", "Start"], ["/retry", "Retry"], ["/save", "Export"]]},
                {"name": "TUI", "pairs": [["/mouse", "Mouse"], ["/logs", "Logs"]]},
                {"name": "Info", "pairs": [["/whoami", "Access"], ["bad"]]},
                {"pairs": [["/x", "nameless"]]},
                "not a category",
            ]
        }
        self.assertEqual(slash.catalog_categories(catalog), [("Session", ["/retry"]), ("Info", ["/whoami"])])
        self.assertEqual(slash.catalog_categories({"categories": "nope"}), [])

    def test_a_catalog_name_is_the_same_name_in_any_case(self) -> None:
        # A typed name resolves whatever its case, so a catalog row differing from a TUI command only in case is that
        # command, and a catalog name with capitals is matched lowercased.
        catalog = {"categories": [{"name": "Session", "pairs": [["/Model", "Hermes' model"], ["/retry", "Retry"]]}]}
        self.assertEqual(slash.catalog_categories(catalog), [("Session", ["/retry"])])
        names = [c.name for c in slash.completions("", [("/Rewind", "Hermes' rewind"), ("/My-Skill", "A skill")])]
        self.assertEqual([name for name in names if name.lower() == "rewind"], ["rewind"])
        known = slash.known_names([("/My-Skill", "A skill")])
        self.assertEqual(slash.slash_token_ranges("/my-skill go", known), [(0, 9)])

    def test_the_skill_count_is_a_positive_integer_or_zero(self) -> None:
        for value, expected in ((144, 144), (0, 0), (-1, 0), (True, 0), ("3", 0), (None, 0)):
            with self.subTest(value=value):
                self.assertEqual(slash.catalog_skill_count({"skill_count": value}), expected)


if __name__ == "__main__":
    unittest.main()
