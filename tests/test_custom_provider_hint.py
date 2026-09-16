"""What a `providers.<id>` block serves: read it, say when it is unknown, record it.

A block whose id says nothing (`custom`, `work-relay`) used to land on the
`gateway` fallback unconditionally. `gateway` is multi-vendor, so
`alias_is_served` counts every alias as served and `entitlement_shaped_chain`
is a no-op -- the chain reordering was off, silently, for exactly the machines
free-tier users build.

Three surfaces, pinned in both directions here:

* detection reads the block's `base_url` host. An exact, known vendor endpoint
  carries that vendor's family; an unknown host -- including a private gateway
  whose URL merely contains a vendor name -- stays unresolved, and an id that
  already names a family is never overruled by its URL.
* `omh model-chains show` names the machine whose providers still resolve to
  nothing, and names both ways out.
* `omh model-chains provider set|clear` is the way out that does not need a
  terminal, since a `--yes`, `--json`, or non-TTY setup asks no provider
  question at all.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli

from omh.commands import provider_entitlements as writer_module
from omh.commands import setup as setup_module
from omh.plugin_bundle.omh import provider_detection as detection
from omh.plugin_bundle.omh.hermes_delegation import (
    PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
    PROVIDER_KIND_VOCABULARY,
    effective_provider_entitlements,
    provider_entitlements_path,
    provider_family_for,
)

HINT = "none of these names a model family, so no chain is reordered"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _config(root: Path, text: str) -> None:
    _write(root / "hermes" / "config.yaml", text)


def _homes(root: Path) -> list[str]:
    return ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes")]


def _show(root: Path) -> str:
    status, text, stderr = run_cli([*_homes(root), "model-chains", "show"], output_json=False)
    assert (status, stderr) == (0, ""), (status, stderr)
    return text


def _show_json(root: Path) -> dict:
    _status, text, _stderr = run_cli([*_homes(root), "model-chains", "show", "--json"])
    return json.loads(text)


class EndpointHostInferenceTests(unittest.TestCase):
    """The block's own `base_url` answers, or nothing does."""

    def _kinds(self, config_text: str) -> dict[str, str]:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _write(root / "config.yaml", config_text)
            return {row["id"]: row["kind"] for row in detection.detect_linked_providers(root)}

    def test_a_known_vendor_endpoint_carries_that_vendors_family(self) -> None:
        kinds = self._kinds(
            "providers:\n"
            "  custom:\n    base_url: https://openrouter.ai/api/v1\n"
            "  vendor:\n    base_url: https://api.deepseek.com/v1\n"
        )
        self.assertEqual(kinds, {"custom": "openrouter", "vendor": "deepseek"})

    def test_an_unknown_host_stays_unresolved(self) -> None:
        kinds = self._kinds("providers:\n  private:\n    base_url: https://relay.mycorp.example/v1\n")
        self.assertEqual(kinds, {"private": "gateway"})

    def test_a_private_gateway_named_after_a_vendor_does_not_resolve(self) -> None:
        # The rule that keeps this honest. Someone fronting OpenRouter with
        # their own relay has a host the table does not name, and inferring
        # `openrouter` from the spelling would promote models in front of a
        # chain their gateway may not serve.
        kinds = self._kinds(
            "providers:\n"
            "  a:\n    base_url: https://openrouter.mycorp.example/v1\n"
            "  b:\n    base_url: https://my-openrouter.ai.internal/v1\n"
            "  c:\n    base_url: https://proxy.example/openrouter.ai/v1\n"
        )
        self.assertEqual(kinds, {"a": "gateway", "b": "gateway", "c": "gateway"})

    def test_an_id_that_names_a_family_is_not_overruled_by_its_url(self) -> None:
        # The id is the operator naming the provider; the URL under it does
        # not get to rename it.
        kinds = self._kinds(
            "providers:\n"
            "  zai:\n    base_url: https://api.anthropic.com/v1\n"
            "  openrouter:\n    base_url: https://api.deepseek.com/v1\n"
        )
        self.assertEqual(kinds, {"zai": "zai", "openrouter": "openrouter"})

    def test_a_loopback_block_is_still_left_out_entirely(self) -> None:
        # The host serves two questions now; the local one must not regress.
        kinds = self._kinds(
            "providers:\n"
            "  lm:\n    base_url: http://localhost:1234/v1\n"
            "  custom:\n    base_url: https://openrouter.ai/api/v1\n"
        )
        self.assertEqual(kinds, {"custom": "openrouter"})

    def test_one_parser_answers_both_questions(self) -> None:
        text = (
            "providers:\n"
            "  lm:\n    base_url: http://127.0.0.1:8080/v1  # a comment\n"
            "  custom:\n    base_url: 'https://openrouter.ai/api/v1'\n"
            "  keyless:\n    api_key: x\n"
        )
        hosts = detection.config_provider_base_url_hosts(text)
        self.assertEqual(hosts, {"lm": "127.0.0.1", "custom": "openrouter.ai"})
        self.assertEqual(detection.local_config_provider_ids(text), ["lm"])
        self.assertEqual(detection.endpoint_family_for_host(hosts["custom"]), "openrouter")
        self.assertEqual(detection.endpoint_family_for_host(hosts["lm"]), "")

    def test_every_mapped_family_is_a_kind_the_document_accepts(self) -> None:
        for host, family in detection.ENDPOINT_HOST_FAMILIES.items():
            self.assertIn(family, PROVIDER_KIND_VOCABULARY, host)
            # A host is a host, not a URL or a pattern.
            self.assertNotIn("/", host)
            self.assertEqual(host, host.lower())


class ShowNamesTheInertCaseTests(unittest.TestCase):
    """The positive case and every negative control beside it."""

    def test_an_unresolved_endpoint_is_told_the_reordering_is_doing_nothing(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _config(root, "providers:\n  private:\n    base_url: https://relay.mycorp.example/v1\n")
            text = _show(root)
            payload = _show_json(root)
        self.assertIn("Linked Hermes providers: private (config)", text)
        self.assertIn(HINT, text)
        self.assertNotIn("(reordered by this machine's providers)", text)
        self.assertEqual(payload["unplaced_providers"], ["private"])

    def test_the_hint_names_both_ways_out(self) -> None:
        # A `--yes`, `--json`, or non-TTY setup asks no provider question, and
        # that install path overlaps heavily with the machines that land here,
        # so advice that said only `omh setup` would be advice they cannot take.
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _config(root, "providers:\n  private:\n    base_url: https://relay.mycorp.example/v1\n")
            text = _show(root)
        self.assertIn("`omh model-chains provider set <id> <kind>`", text)
        self.assertIn("`omh setup`", text)

    def test_a_block_pointed_at_a_known_vendor_is_not_told_anything(self) -> None:
        # Reading the host removes this machine from the hint's population:
        # the endpoint answered, so there is nothing left to record.
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _config(root, "providers:\n  custom:\n    base_url: https://api.deepseek.com/v1\n")
            text = _show(root)
            payload = _show_json(root)
        self.assertIn("Linked Hermes providers: custom (config)", text)
        self.assertNotIn(HINT, text)
        self.assertIn("(reordered by this machine's providers)", text)
        self.assertEqual(payload["unplaced_providers"], [])

    def test_a_multi_vendor_family_is_not_told_to_go_and_fix_anything(self) -> None:
        # openrouter leaves every chain unshaped too, and correctly: it does
        # serve every family, and no answer would change that.
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _config(root, "providers:\n  openrouter:\n    base_url: https://openrouter.ai/api/v1\n")
            text = _show(root)
            payload = _show_json(root)
        self.assertIn("Linked Hermes providers: openrouter (config)", text)
        self.assertNotIn(HINT, text)
        self.assertNotIn("(reordered by this machine's providers)", text)
        self.assertEqual(payload["unplaced_providers"], [])

    def test_a_vendor_family_reorders_and_is_not_told_anything(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _config(root, "providers:\n  zai:\n    base_url: https://api.z.ai/v1\n")
            text = _show(root)
        self.assertIn("(reordered by this machine's providers)", text)
        self.assertNotIn(HINT, text)

    def test_one_usable_provider_beside_an_unplaced_one_keeps_the_line_off(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _config(
                root,
                "providers:\n"
                "  private:\n    base_url: https://relay.mycorp.example/v1\n"
                "  zai:\n    base_url: https://api.z.ai/v1\n",
            )
            text = _show(root)
            payload = _show_json(root)
        self.assertIn("Linked Hermes providers: private (config), zai (config)", text)
        # The chains are unshaped here too -- the gateway kind wins the
        # multi-vendor branch -- but "none of these names a model family" is
        # false, and the operator has already named one.
        self.assertNotIn(HINT, text)
        self.assertEqual(payload["unplaced_providers"], ["private"])

    def test_a_route_that_shapes_a_chain_keeps_the_line_off(self) -> None:
        # A gateway kind alone cannot shape anything, but a route decides
        # `alias_is_served` before the kind does. "No chain is reordered"
        # would then be false, so the claim is made only when it holds.
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _config(root, "providers:\n  private:\n    base_url: https://relay.mycorp.example/v1\n")
            _write(
                root / "omh" / "routing" / "model-providers.json",
                json.dumps(
                    {
                        "schema_version": "model_provider_routes/v1",
                        "models": {"gpt-5.6-luna": {"provider": "elsewhere", "model": "gpt-5.6-luna"}},
                    }
                ),
            )
            text = _show(root)
            payload = _show_json(root)
        self.assertIn("(reordered by this machine's providers)", text)
        self.assertNotIn(HINT, text)
        self.assertEqual(payload["unplaced_providers"], ["private"])

    def test_no_linked_provider_keeps_the_line_it_always_had(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            text = _show(root)
        self.assertIn("Linked Hermes providers: none found", text)
        self.assertNotIn(HINT, text)


class ProviderRecordCommandTests(unittest.TestCase):
    """The scriptable way to record a kind, for the installs setup never asks."""

    def _run(self, root: Path, *argv: str):
        return run_cli([*_homes(root), "model-chains", "provider", *argv], output_json=False)

    def _document(self, root: Path) -> dict:
        return json.loads(provider_entitlements_path(root / "omh").read_text(encoding="utf-8"))

    def test_a_recorded_kind_resolves_end_to_end(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _config(root, "providers:\n  private:\n    base_url: https://relay.mycorp.example/v1\n")
            self.assertIn(HINT, _show(root))
            status, out, stderr = self._run(root, "set", "private", "deepseek")
            self.assertEqual((status, stderr), (0, ""), out)
            entitlements, doc_status, _rows = effective_provider_entitlements(root / "omh", root / "hermes")
            text = _show(root)
        self.assertEqual(doc_status, "applied")
        # Not "the file was written": the resolver the serving rule and every
        # surface share now answers for this id, and the chains move.
        self.assertEqual(provider_family_for("private", entitlements), "deepseek")
        self.assertIn("(reordered by this machine's providers)", text)
        self.assertNotIn(HINT, text)

    def test_a_rejected_kind_writes_nothing_and_names_the_accepted_values(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _config(root, "providers:\n  private:\n    base_url: https://relay.mycorp.example/v1\n")
            status, _out, stderr = self._run(root, "set", "private", "deepsek")
            self.assertEqual(status, 2)
            self.assertIn("unknown provider kind 'deepsek'", stderr)
            for kind in PROVIDER_KIND_VOCABULARY:
                self.assertIn(kind, stderr)
            self.assertFalse(provider_entitlements_path(root / "omh").exists())
            # A typo must not manufacture the unresolvable state this whole
            # surface exists to make visible.
            self.assertIn(HINT, _show(root))

    def test_a_rejected_provider_id_writes_nothing(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            status, _out, stderr = self._run(root, "set", "not an id", "deepseek")
            self.assertEqual(status, 2)
            self.assertIn("not a plain provider identifier", stderr)
            self.assertFalse(provider_entitlements_path(root / "omh").exists())

    def test_running_it_twice_leaves_the_same_document(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _config(root, "providers:\n  private:\n    base_url: https://relay.mycorp.example/v1\n")
            self.assertEqual(self._run(root, "set", "private", "deepseek")[0], 0)
            first = provider_entitlements_path(root / "omh").read_text(encoding="utf-8")
            status, out, _stderr = self._run(root, "set", "private", "deepseek")
            second = provider_entitlements_path(root / "omh").read_text(encoding="utf-8")
        self.assertEqual(status, 0)
        self.assertEqual(first, second)
        self.assertIn("nothing written", out)

    def test_a_second_provider_and_a_clear_leave_the_rest_alone(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _write(
                provider_entitlements_path(root / "omh"),
                json.dumps(
                    {
                        "schema_version": PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
                        "providers": {"kept": "zai"},
                        "subscription_clis": ["claude-code"],
                    }
                ),
            )
            self.assertEqual(self._run(root, "set", "private", "deepseek")[0], 0)
            after_set = self._document(root)
            self.assertEqual(self._run(root, "clear", "private")[0], 0)
            after_clear = self._document(root)
            status, out, _stderr = self._run(root, "clear", "private")
        self.assertEqual(after_set["providers"], {"kept": "zai", "private": "deepseek"})
        self.assertEqual(after_set["subscription_clis"], ["claude-code"])
        self.assertEqual(after_clear["providers"], {"kept": "zai"})
        self.assertEqual(after_clear["subscription_clis"], ["claude-code"])
        self.assertEqual(status, 0)
        self.assertIn("nothing written", out)

    def test_recording_a_kind_drops_a_contradictory_exclusion(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _write(
                provider_entitlements_path(root / "omh"),
                json.dumps(
                    {
                        "schema_version": PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
                        "providers": {},
                        "subscription_clis": [],
                        "excluded_providers": ["private", "other"],
                    }
                ),
            )
            self.assertEqual(self._run(root, "set", "private", "deepseek")[0], 0)
            document = self._document(root)
        self.assertEqual(document["providers"], {"private": "deepseek"})
        self.assertEqual(document["excluded_providers"], ["other"])

    def test_an_unreadable_record_is_refused_rather_than_replaced(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            path = provider_entitlements_path(root / "omh")
            _write(path, "{not json")
            status, _out, stderr = self._run(root, "set", "private", "deepseek")
            kept = path.read_text(encoding="utf-8")
        # A person watching the interview can be warned and answer again; a
        # script cannot, so the operator's document is left exactly as it was.
        self.assertEqual(status, 2)
        self.assertIn("is not readable as a provider record", stderr)
        self.assertEqual(kept, "{not json")

    def test_the_json_payload_reports_the_write(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _status, out, _stderr = run_cli(
                [*_homes(root), "model-chains", "provider", "set", "private", "deepseek", "--json"]
            )
            payload = json.loads(out)
        self.assertEqual(payload["schema_version"], "provider_entitlement_record/v1")
        self.assertEqual((payload["provider"], payload["kind"], payload["status"]), ("private", "deepseek", "recorded"))
        self.assertEqual(payload["providers"], {"private": "deepseek"})


class OneWriterTests(unittest.TestCase):
    """The interview and the command are not two writers."""

    def test_the_interview_writes_through_the_same_producer(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            args = argparse.Namespace(omh_home=str(root / ".omh"), hermes_home=str(root / ".hermes"), scope=None)
            paths = setup_module._paths(args)
            _write(paths.hermes_config_path, "providers:\n  og:\n    base_url: https://relay.mycorp.example/v1\n")
            with patch.object(
                setup_module,
                "_detect_external_cli_profiles",
                return_value={"claude-code": {"binary_present": False}, "codex": {"binary_present": False}},
            ), patch.object(setup_module, "_ask_multi_choice", return_value=["og"]), patch.object(
                setup_module, "_ask", return_value=""
            ), patch.object(setup_module, "_use_color", return_value=False), patch.object(
                writer_module, "write_provider_entitlements", wraps=writer_module.write_provider_entitlements
            ) as producer, redirect_stdout(io.StringIO()):
                setup_module._ask_provider_entitlements(argparse.Namespace(), paths, "en")
            producer.assert_called_once()
            document = json.loads(provider_entitlements_path(paths.omh_home).read_text(encoding="utf-8"))
        self.assertEqual(document["providers"], {"og": "gateway"})

    def test_the_producer_refuses_what_the_reader_would_drop(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError) as raised:
                writer_module.write_provider_entitlements(
                    root,
                    {
                        "schema_version": PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
                        "providers": {"private": "warp"},
                        "subscription_clis": [],
                    },
                )
            self.assertIn("kind must be one of", str(raised.exception))
            self.assertFalse(provider_entitlements_path(root).exists())


if __name__ == "__main__":
    unittest.main()
