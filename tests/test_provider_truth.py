"""The surfaces that describe providers say which ones routing counts.

Detection made linked providers reorder chains on their own; these tests
hold `omh doctor`, `omh model-chains show`, and non-interactive `omh setup`
to telling that truth: which providers counted and where each was found,
whether the record applied, and the two silent faults -- an invalid
`providers.json` (its kinds and exclusions dropped) and a route to a
provider neither recorded nor linked (its alias demoted in every chain).
Every reader here gets a temporary Hermes home too, so a developer's own
`~/.hermes` never decides a verdict.
"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.commands import setup as setup_module  # noqa: E402
from omh.commands.language import LANGUAGE_CODES, tr  # noqa: E402
from omh.commands.model_chains import _print_state, _state  # noqa: E402
from omh.maintenance.doctor import doctor_ok, run_doctor  # noqa: E402
from omh.paths import OmhPaths  # noqa: E402
from omh.plugin_bundle.omh.hermes_delegation import (  # noqa: E402
    HERMES_MIXTURE_CATEGORY_CHAINS,
    MODEL_PROVIDER_ROUTES_SCHEMA_VERSION,
    PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
    UNKNOWN_ROUTE_NAMED_LIMIT,
    alias_is_served,
    chains_with_overrides,
    effective_mixture_category_chains,
    load_mixture_chain_overrides,
    model_provider_routes_path,
    provider_entitlements_path,
    routes_to_unknown_providers,
    split_unknown_routes,
    unknown_route_label,
    unknown_route_labels,
)


def _chain_row(alias: str, provider: str, route: str | None = None) -> dict[str, str]:
    return {"alias": alias, "route": route or alias, "provider": provider, "effect": "chain"}


def _dispatch_row(key: str, provider: str) -> dict[str, str]:
    return {"alias": key, "route": key, "provider": provider, "effect": "dispatch"}


def _paths(root: Path) -> OmhPaths:
    paths = OmhPaths(root / ".omh", root / ".hermes")
    paths.hermes_home.mkdir(parents=True, exist_ok=True)
    return paths


def _write_config(paths: OmhPaths, body: str) -> None:
    paths.hermes_config_path.write_text(body, encoding="utf-8")


def _write_record(paths: OmhPaths, providers: dict[str, str], *, excluded: list[str] | None = None) -> None:
    document: dict[str, object] = {
        "schema_version": PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
        "providers": providers,
        "subscription_clis": [],
    }
    if excluded:
        document["excluded_providers"] = excluded
    path = provider_entitlements_path(paths.omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def _write_invalid_record(paths: OmhPaths) -> None:
    path = provider_entitlements_path(paths.omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")


def _write_routes(paths: OmhPaths, models: dict[str, tuple[str, str]]) -> None:
    path = model_provider_routes_path(paths.omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": MODEL_PROVIDER_ROUTES_SCHEMA_VERSION,
                "models": {alias: {"provider": provider, "model": model} for alias, (provider, model) in models.items()},
            }
        ),
        encoding="utf-8",
    )


def _doctor_check(paths: OmhPaths):
    checks = run_doctor(paths)
    return checks, next(check for check in checks if check.name == "provider_entitlements")


class UnknownRouteRuleTests(unittest.TestCase):
    def test_names_only_routes_to_a_provider_the_machine_does_not_hold(self) -> None:
        routes = {
            "glm-5.3": ("work-relay", "zai/glm-5.3"),
            "kimi-k3": ("og", "kimi"),
            "gpt-6-astra": ("openai-codex", "gpt"),
            "my-private-model": ("work-relay", "private/model"),
        }
        entitlements = {"providers": {"og": "gateway", "openai-codex": "openai-codex"}, "subscription_clis": []}
        # A shipped chain names glm-5.3, so its route demotes it; nothing
        # names my-private-model, so its route only ever resolves a pin.
        self.assertEqual(
            routes_to_unknown_providers(routes, entitlements),
            (_chain_row("glm-5.3", "work-relay"), _dispatch_row("my-private-model", "work-relay")),
        )

    def test_a_key_the_serving_rule_never_reaches_is_dispatch_only(self) -> None:
        """A capitalized or vendor-prefixed key is not a route for the plain alias.

        `alias_is_served` looks a route up casefolded, then unqualified,
        then verbatim -- so `GLM-5.3` and `zai/glm-5.3` are never found for
        the chain entry `glm-5.3`, and reporting them as a demotion would
        describe a reordering that never happens. The rule and the report
        share one lookup, and this pins that they agree.
        """
        entitlements = {"providers": {"zai": "zai"}, "subscription_clis": []}
        unreached = {"GLM-5.3": ("work-relay", "zai/glm-5.3"), "zai/glm-5.3": ("work-relay", "zai/glm-5.3")}
        self.assertEqual(
            routes_to_unknown_providers(unreached, entitlements),
            (_dispatch_row("GLM-5.3", "work-relay"), _dispatch_row("zai/glm-5.3", "work-relay")),
        )
        self.assertTrue(alias_is_served("glm-5.3", entitlements, unreached))
        reached = {"glm-5.3": ("work-relay", "zai/glm-5.3")}
        self.assertEqual(routes_to_unknown_providers(reached, entitlements), (_chain_row("glm-5.3", "work-relay"),))
        self.assertFalse(alias_is_served("glm-5.3", entitlements, reached))
        # The unqualified lookup runs the other way too: an override chain
        # naming `zai/glm-5.3` is reached by the plain key, and the row
        # carries the chain's spelling beside the key as written.
        override_chains = {"quick": (("zai/glm-5.3", "low"),)}
        self.assertEqual(
            routes_to_unknown_providers(reached, entitlements, override_chains),
            (_chain_row("zai/glm-5.3", "work-relay", route="glm-5.3"),),
        )
        self.assertFalse(alias_is_served("zai/glm-5.3", entitlements, reached))

    def test_nothing_is_named_when_nothing_is_held(self) -> None:
        # No providers to judge against: `alias_is_served` fails open, so no
        # route demotes anything and the rule must not claim one does.
        routes = {"glm-5.3": ("work-relay", "zai/glm-5.3")}
        self.assertEqual(routes_to_unknown_providers(routes, None), ())
        self.assertEqual(routes_to_unknown_providers(routes, {"providers": {}, "subscription_clis": []}), ())
        self.assertEqual(routes_to_unknown_providers({}, {"providers": {"og": "gateway"}, "subscription_clis": []}), ())


class UnknownRouteReportTests(unittest.TestCase):
    def test_the_label_names_the_key_and_the_chain_spelling_only_when_it_differs(self) -> None:
        self.assertEqual(unknown_route_label(_chain_row("glm-5.3", "work-relay")), "glm-5.3 -> work-relay")
        self.assertEqual(unknown_route_label(_dispatch_row("GLM-5.3", "work-relay")), "GLM-5.3 -> work-relay")
        # The key is what the document holds and a repair edits; the
        # chain's own spelling rides along so the moved entry is named too.
        self.assertEqual(
            unknown_route_label(_chain_row("zai/glm-5.3", "work-relay", route="glm-5.3")),
            "glm-5.3 (chain alias zai/glm-5.3) -> work-relay",
        )

    def test_labels_are_capped_with_a_remainder(self) -> None:
        rows = [_dispatch_row(f"model-{index}", "work-relay") for index in range(UNKNOWN_ROUTE_NAMED_LIMIT + 2)]
        text = unknown_route_labels(rows)
        self.assertEqual(text.count("-> work-relay"), UNKNOWN_ROUTE_NAMED_LIMIT)
        self.assertTrue(text.endswith(" … and 2 more"), text)
        self.assertNotIn("more", unknown_route_labels(rows[:UNKNOWN_ROUTE_NAMED_LIMIT]))

    def test_split_matches_both_effects_by_equality_and_refuses_a_third(self) -> None:
        chain = _chain_row("glm-5.3", "work-relay")
        dispatch = _dispatch_row("GLM-5.3", "work-relay")
        self.assertEqual(split_unknown_routes([dispatch, chain]), ([chain], [dispatch]))
        with self.assertRaises(ValueError):
            split_unknown_routes([{**dispatch, "effect": "someday"}])
        with self.assertRaises(ValueError):
            split_unknown_routes([{"alias": "x", "route": "x", "provider": "p"}])

    def test_the_stored_chains_have_one_producer(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            base = ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)]
            status, _stdout, stderr = run_cli(base + ["model-chains", "set", "quick", "zai/glm-5.3:low"], output_json=False)
            self.assertEqual(status, 0, stderr)
            overrides, _status = load_mixture_chain_overrides(paths.omh_home)
            chains = chains_with_overrides(overrides)
            self.assertEqual(chains["quick"], (("zai/glm-5.3", "low"),))
            self.assertEqual(set(chains), set(HERMES_MIXTURE_CATEGORY_CHAINS))
            # With nothing linked or recorded the shaped reader is the stored
            # chains verbatim: the two derivations are one function.
            self.assertEqual(effective_mixture_category_chains(paths.omh_home, paths.hermes_home), chains)


class DoctorProviderCheckTests(unittest.TestCase):
    def test_counted_providers_and_exclusions_are_named_with_their_sources(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_config(paths, "providers:\n  og:\n    base_url: x\n  zai:\n    base_url: y\n")
            (paths.hermes_home / ".env").write_text("ANTHROPIC_API_KEY=sk-secret-value\n", encoding="utf-8")
            _write_record(paths, {"og": "gateway"}, excluded=["zai"])

            _checks, check = _doctor_check(paths)

            self.assertTrue(check.ok)
            self.assertEqual(check.severity, "ok")
            self.assertTrue(check.observed)
            self.assertIn("providers.json applied", check.message)
            self.assertIn("counted: og (recorded, providers.json), anthropic (env, ANTHROPIC_API_KEY)", check.message)
            self.assertIn("excluded by the record: zai", check.message)
            self.assertIn("model-providers.json absent", check.message)
            self.assertNotIn("sk-secret-value", check.message)
            self.assertNotIn("neither recorded nor linked", check.message)

    def test_nothing_linked_or_recorded_is_said_plainly(self) -> None:
        with TemporaryDirectory() as tmp:
            _checks, check = _doctor_check(_paths(Path(tmp)))
            self.assertTrue(check.ok)
            self.assertEqual(check.severity, "ok")
            self.assertIn("providers.json absent", check.message)
            self.assertIn("counted: none linked to Hermes or recorded; every model counts as served", check.message)
            self.assertNotIn("excluded by the record", check.message)

    def test_an_invalid_record_warns_about_what_it_silently_drops(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_config(paths, "providers:\n  zai:\n    base_url: y\n")
            _write_invalid_record(paths)

            checks, check = _doctor_check(paths)

            # A routing document the operator owns is not an install failure.
            self.assertTrue(check.ok)
            self.assertEqual(check.severity, "warning")
            self.assertEqual(doctor_ok(checks), doctor_ok([item for item in checks if item.name != "provider_entitlements"]))
            self.assertIn(f"{provider_entitlements_path(paths.omh_home)} is ignored (invalid: unreadable JSON)", check.message)
            self.assertIn("its recorded kinds are dropped and any providers it excluded count again", check.message)
            # The linked row the record might have excluded is counted again,
            # and the check shows exactly that.
            self.assertIn("counted: zai (config, config.yaml)", check.message)
            self.assertIn("omh setup", check.next_action)
            self.assertIn("omh doctor", check.next_action)

    def test_a_route_to_an_unknown_provider_is_named_as_a_demotion(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_config(paths, "providers:\n  og:\n    base_url: x\n")
            _write_routes(
                paths,
                {
                    "glm-5.3": ("work-relay", "zai/glm-5.3"),
                    "kimi-k3": ("og", "kimi"),
                    "my-private-model": ("work-relay", "private/model"),
                },
            )

            checks, check = _doctor_check(paths)

            self.assertTrue(check.ok)
            self.assertEqual(check.severity, "warning")
            self.assertEqual(doctor_ok(checks), doctor_ok([item for item in checks if item.name != "provider_entitlements"]))
            self.assertIn("chain entries routed to a provider neither recorded nor linked: glm-5.3 -> work-relay", check.message)
            self.assertIn("each sorts behind the served entries of every chain naming it", check.message)
            # A route no chain reaches reorders nothing; its effect is the
            # unchecked dispatch, and the check says that instead.
            self.assertIn("dispatch-only routes to a provider neither recorded nor linked: my-private-model -> work-relay", check.message)
            self.assertIn("a dispatch pinning one asks Hermes for a provider it is not linked to", check.message)
            self.assertNotIn("my-private-model -> work-relay; each sorts", check.message)
            # The route to the linked gateway is not a finding.
            self.assertNotIn("kimi-k3 -> og", check.message)
            self.assertIn("model-providers.json applied", check.message)

    def test_a_chain_entry_spelled_differently_is_reported_by_its_route_key(self) -> None:
        """The named key must exist in the operator's document.

        `omh model-chains set quick "zai/glm-5.3:low"` with a route under
        `glm-5.3` demotes the override entry through the unqualified
        lookup; a warning that said `zai/glm-5.3 -> work-relay` would send
        the repair after a key the routes document does not contain.
        """
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_config(paths, "providers:\n  og:\n    base_url: x\n")
            _write_routes(paths, {"glm-5.3": ("work-relay", "zai/glm-5.3")})
            base = ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)]
            status, _stdout, stderr = run_cli(base + ["model-chains", "set", "quick", "zai/glm-5.3:low"], output_json=False)
            self.assertEqual(status, 0, stderr)

            _checks, check = _doctor_check(paths)

            self.assertEqual(check.severity, "warning")
            self.assertIn("glm-5.3 (chain alias zai/glm-5.3) -> work-relay", check.message)
            self.assertNotIn("zai/glm-5.3 -> work-relay", check.message)
            # The shipped chains still name the plain alias, so the same
            # key is reported once more under its own spelling.
            self.assertIn(": glm-5.3 -> work-relay", check.message)
            state = _state(paths.omh_home, paths.hermes_home)
            out = io.StringIO()
            with redirect_stdout(out):
                _print_state(state)
            self.assertIn("glm-5.3 (chain alias zai/glm-5.3) -> work-relay", out.getvalue())
            self.assertNotIn("zai/glm-5.3 -> work-relay", out.getvalue())

    def test_many_unknown_routes_are_capped_and_the_segments_stay_readable(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_config(paths, "providers:\n  og:\n    base_url: x\n")
            _write_invalid_record(paths)
            _write_routes(
                paths,
                {f"private-model-{index}": ("work-relay", f"private/model-{index}") for index in range(UNKNOWN_ROUTE_NAMED_LIMIT + 3)},
            )

            _checks, check = _doctor_check(paths)

            self.assertEqual(check.severity, "warning")
            self.assertEqual(check.message.count("-> work-relay"), UNKNOWN_ROUTE_NAMED_LIMIT)
            self.assertIn(" … and 3 more; no chain names these", check.message)
            # Two warnings plus the status fragments: three segments, each
            # readable on its own, joined by a separator no warning uses.
            segments = check.message.split(" | ")
            self.assertEqual(len(segments), 3)
            self.assertTrue(segments[0].startswith(f"{provider_entitlements_path(paths.omh_home)} is ignored"))
            self.assertTrue(segments[1].startswith("dispatch-only routes to a provider neither recorded nor linked: "))
            self.assertIn("counted: og (config, config.yaml)", segments[2])
            self.assertIn("model-providers.json applied", segments[2])
            state = _state(paths.omh_home, paths.hermes_home)
            out = io.StringIO()
            with redirect_stdout(out):
                _print_state(state)
            show_line = next(line for line in out.getvalue().splitlines() if line.startswith("Dispatch-only routes"))
            self.assertEqual(show_line.count("-> work-relay"), UNKNOWN_ROUTE_NAMED_LIMIT)
            self.assertIn(" … and 3 more (no chain names these", show_line)

    def test_a_route_to_an_unknown_provider_is_no_finding_when_nothing_is_held(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_routes(paths, {"glm-5.3": ("work-relay", "zai/glm-5.3")})
            _checks, check = _doctor_check(paths)
            self.assertEqual(check.severity, "ok")
            self.assertNotIn("neither recorded nor linked", check.message)

    def test_an_invalid_routes_document_warns_that_every_alias_dispatches_unchanged(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            path = model_provider_routes_path(paths.omh_home)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{", encoding="utf-8")
            _checks, check = _doctor_check(paths)
            self.assertTrue(check.ok)
            self.assertEqual(check.severity, "warning")
            self.assertIn(f"{path} is ignored (invalid: unreadable JSON): every alias dispatches unchanged", check.message)

    def test_the_two_model_checks_form_the_model_routing_group_and_no_other(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_config(paths, "model:\n  default: anthropic/claude-opus-4.6\n  provider: auto\n")
            _write_invalid_record(paths)
            checks = run_doctor(paths)
            summary = setup_module._doctor_operator_summary(checks)
            groups = {group["name"]: group for group in summary["groups"]}
            # hermes_model_routing, provider_entitlements and prompt_cache_route.
            self.assertEqual(groups["model_routing"]["total"], 3)
            self.assertEqual(groups["model_routing"]["passing"], 3)
            self.assertEqual(groups["model_routing"]["status"], "warning")
            self.assertEqual(groups["model_routing"]["failed"], [])
            # The two checks belong to this group and to no other: a summary
            # built from them alone leaves every other group empty.
            members = [check for check in checks if check.name in {"hermes_model_routing", "provider_entitlements"}]
            self.assertEqual(len(members), 2)
            for group in setup_module._doctor_operator_summary(members)["groups"]:
                self.assertEqual(group["total"], 2 if group["name"] == "model_routing" else 0, group["name"])
        for code in LANGUAGE_CODES:
            self.assertTrue(tr(code, "doctor_group_model_routing").strip())

    def test_the_cli_prints_the_group_and_the_warning_with_its_fix(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            _write_config(paths, "providers:\n  og:\n    base_url: x\n")
            _write_routes(paths, {"glm-5.3": ("work-relay", "zai/glm-5.3")})
            base = ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)]
            with patch("omh.command_path.shutil.which", return_value="/usr/local/bin/omh"):
                status, _stdout, stderr = run_cli(base + ["setup", "--yes"], output_json=False)
            self.assertEqual(status, 0, stderr)

            with patch("omh.command_path.shutil.which", return_value="/usr/local/bin/omh"):
                status, stdout, stderr = run_cli(base + ["doctor"], output_json=False)

            self.assertEqual(status, 0, stderr)
            self.assertIn("Model routing: warning (3/3)", stdout)
            self.assertIn("- provider_entitlements: chain entries routed to a provider neither recorded nor linked: glm-5.3 -> work-relay", stdout)
            self.assertIn("Fix: Repair the named routing document", stdout)

            with patch("omh.command_path.shutil.which", return_value="/usr/local/bin/omh"):
                status, stdout, stderr = run_cli(base + ["doctor", "--json"], output_json=False)

            payload = json.loads(stdout)
            self.assertTrue(payload["ok"])
            check = {item["name"]: item for item in payload["checks"]}["provider_entitlements"]
            self.assertEqual(check["severity"], "warning")
            self.assertEqual(payload["summary"]["status"], "ok")


class ModelChainsShowTests(unittest.TestCase):
    def test_state_carries_the_routes_status_and_the_unknown_provider_routes(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_config(paths, "providers:\n  og:\n    base_url: x\n")
            _write_routes(
                paths,
                {
                    "glm-5.3": ("work-relay", "zai/glm-5.3"),
                    "kimi-k3": ("og", "kimi"),
                    "my-private-model": ("work-relay", "private/model"),
                },
            )

            state = _state(paths.omh_home, paths.hermes_home)

            self.assertEqual(state["schema_version"], "model_chain_state/v1")
            self.assertEqual(state["routes_status"], "applied")
            self.assertEqual(state["routes_path"], str(model_provider_routes_path(paths.omh_home)))
            self.assertEqual(
                state["unserved_routes"],
                [_chain_row("glm-5.3", "work-relay"), _dispatch_row("my-private-model", "work-relay")],
            )
            out = io.StringIO()
            with redirect_stdout(out):
                _print_state(state)
            text = out.getvalue()
            self.assertIn(
                "Chain entries routed to a provider neither recorded nor linked: glm-5.3 -> work-relay "
                "(each sorts behind the served entries of every chain naming it)",
                text,
            )
            self.assertIn(
                "Dispatch-only routes to a provider neither recorded nor linked: my-private-model -> work-relay "
                "(no chain names these; a dispatch pinning one asks Hermes for a provider it is not linked to)",
                text,
            )
            # An applied routes document is not restated; the findings are.
            self.assertNotIn("Provider routes:", text)
            self.assertNotIn("providers.json is ignored", text)

    def test_an_override_chain_alias_counts_as_chain_named(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_config(paths, "providers:\n  og:\n    base_url: x\n")
            _write_routes(paths, {"my-private-model": ("work-relay", "private/model")})
            base = ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)]
            status, _stdout, stderr = run_cli(base + ["model-chains", "set", "quick", "my-private-model:low"], output_json=False)
            self.assertEqual(status, 0, stderr)
            state = _state(paths.omh_home, paths.hermes_home)
            self.assertEqual(state["unserved_routes"], [_chain_row("my-private-model", "work-relay")])

    def test_an_absent_routes_document_prints_nothing_and_an_invalid_one_is_named(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            state = _state(paths.omh_home, paths.hermes_home)
            self.assertEqual(state["routes_status"], "absent")
            self.assertEqual(state["unserved_routes"], [])
            out = io.StringIO()
            with redirect_stdout(out):
                _print_state(state)
            # Absent is the common case and says nothing on every machine.
            self.assertNotIn("Provider routes:", out.getvalue())
            self.assertNotIn("routed to a provider", out.getvalue())
            path = model_provider_routes_path(paths.omh_home)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{", encoding="utf-8")
            state = _state(paths.omh_home, paths.hermes_home)
            self.assertEqual(state["routes_status"], "invalid: unreadable JSON")
            out = io.StringIO()
            with redirect_stdout(out):
                _print_state(state)
            self.assertIn(
                f"Provider routes: {path} [invalid: unreadable JSON] (ignored: every alias dispatches unchanged)",
                out.getvalue(),
            )

    def test_an_invalid_record_says_what_it_drops(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_config(paths, "providers:\n  zai:\n    base_url: y\n")
            _write_invalid_record(paths)
            state = _state(paths.omh_home, paths.hermes_home)
            self.assertEqual(state["entitlements_status"], "invalid: unreadable JSON")
            out = io.StringIO()
            with redirect_stdout(out):
                _print_state(state)
            self.assertIn("[invalid: unreadable JSON]", out.getvalue())
            self.assertIn("providers.json is ignored: its recorded kinds are dropped and any providers it excluded count again", out.getvalue())
            self.assertIn("Linked Hermes providers: zai (config)", out.getvalue())

    def test_show_json_stays_additive(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_routes(paths, {"glm-5.3": ("work-relay", "zai/glm-5.3")})
            base = ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)]
            status, stdout, stderr = run_cli(base + ["model-chains", "show", "--json"], output_json=False)
            self.assertEqual((status, stderr), (0, ""))
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "model_chain_state/v1")
            for key in ("path", "document_status", "entitlements_path", "entitlements_status", "providers", "categories"):
                self.assertIn(key, payload)
            self.assertEqual(payload["routes_status"], "applied")
            # Nothing held: the route demotes nothing and the list says so.
            self.assertEqual(payload["unserved_routes"], [])


class SetupSummaryProviderTests(unittest.TestCase):
    def _base(self, paths: OmhPaths) -> list[str]:
        return ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)]

    def test_a_yes_run_prints_the_counted_providers_and_json_carries_them(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_config(paths, "providers:\n  og:\n    base_url: x\n")
            (paths.hermes_home / ".env").write_text("ZAI_API_KEY=sk-secret-value\n", encoding="utf-8")

            status, stdout, stderr = run_cli(self._base(paths) + ["setup", "--yes"], output_json=False)

            self.assertEqual(status, 0, stderr)
            self.assertIn("Model providers: og (config), zai (env).", stdout)
            self.assertNotIn("sk-secret-value", stdout)

            status, stdout, stderr = run_cli(self._base(paths) + ["setup", "--json"], output_json=False)

            self.assertEqual(status, 0, stderr)
            payload = json.loads(stdout)
            summary = payload["operator_summary"]
            self.assertEqual(summary["schema_version"], "setup_operator_summary/v1")
            self.assertEqual(summary["providers"]["document_status"], "absent")
            # The command resolves its homes; compare resolved to resolved.
            self.assertEqual(
                Path(summary["providers"]["document_path"]).resolve(),
                provider_entitlements_path(paths.omh_home).resolve(),
            )
            self.assertEqual(
                [(row["id"], row["source"], row["evidence"]) for row in summary["providers"]["counted"]],
                [("og", "config", "config.yaml"), ("zai", "env", "ZAI_API_KEY")],
            )
            self.assertNotIn("sk-secret-value", stdout)

    def test_one_provider_reads_in_the_singular(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_config(paths, "providers:\n  og:\n    base_url: x\n")
            status, stdout, stderr = run_cli(self._base(paths) + ["setup", "--yes"], output_json=False)
            self.assertEqual(status, 0, stderr)
            self.assertIn("Model provider: og (config).", stdout)
            self.assertNotIn("og (config) count;", stdout)

    def test_nothing_linked_is_said_plainly(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            status, stdout, stderr = run_cli(self._base(paths) + ["setup", "--no-interactive"], output_json=False)
            self.assertEqual(status, 0, stderr)
            self.assertIn("Model providers: none linked yet. Use `hermes auth` to connect an account.", stdout)

    def test_an_invalid_record_is_named_with_what_still_counts(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_config(paths, "providers:\n  og:\n    base_url: x\n")
            _write_invalid_record(paths)
            status, stdout, stderr = run_cli(self._base(paths) + ["setup", "--yes"], output_json=False)
            self.assertEqual(status, 0, stderr)
            self.assertIn("is ignored (invalid: unreadable JSON); its recorded kinds are dropped and any providers it excluded count again", stdout)
            self.assertIn("Counting: og (config).", stdout)
            status, stdout, stderr = run_cli(self._base(paths) + ["setup", "--json"], output_json=False)
            self.assertEqual(json.loads(stdout)["operator_summary"]["providers"]["document_status"], "invalid: unreadable JSON")

    def test_a_dry_run_reads_the_same_providers_without_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_config(paths, "providers:\n  og:\n    base_url: x\n")
            status, stdout, stderr = run_cli(self._base(paths) + ["setup", "--dry-run", "--json"], output_json=False)
            self.assertEqual(status, 0, stderr)
            payload = json.loads(stdout)
            self.assertEqual([row["id"] for row in payload["operator_summary"]["providers"]["counted"]], ["og"])
            self.assertFalse(paths.omh_home.exists())

    def test_every_language_renders_the_three_provider_lines(self) -> None:
        for code in LANGUAGE_CODES:
            with self.subTest(language=code):
                self.assertTrue(tr(code, "setup_providers_line", providers="og (config)").strip())
                self.assertTrue(tr(code, "setup_providers_line_one", providers="og (config)").strip())
                self.assertTrue(tr(code, "setup_providers_none").strip())
                self.assertTrue(tr(code, "setup_providers_invalid", path="p", status="s", providers="-").strip())


if __name__ == "__main__":
    unittest.main()
