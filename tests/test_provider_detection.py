"""Providers Hermes is linked to, read from what Hermes records -- keys only.

The bundle's `provider_detection` turns a `hermes auth` login, a config
provider key, and an API-key variable NAME into the entitlement document's
own `provider id -> kind` shape, and `effective_provider_entitlements` lays
the recorded document over it. These tests pin what is read (ids and names),
what is never read (a token, a key, a label), which source wins, and that the
routing side counts a linked provider without an interview.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.config_adapter import configured_provider_ids as core_configured_provider_ids  # noqa: E402
from omh.plugin_bundle.omh import provider_detection as detection  # noqa: E402
from omh.plugin_bundle.omh import runtime_paths  # noqa: E402
from omh.plugin_bundle.omh.hermes_delegation import (  # noqa: E402
    HERMES_MIXTURE_CATEGORY_CHAINS,
    PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
    PROVIDER_KIND_UNKNOWN,
    PROVIDER_KIND_VOCABULARY,
    _CHAIN_TOKEN_RE,
    alias_is_served,
    effective_mixture_category_chains,
    effective_provider_entitlements,
    provider_entitlements_path,
    routes_to_unknown_providers,
)
from omh.plugin_bundle.omh.model_chain_picker import picker_rows  # noqa: E402

TOKEN = "sk-live-token-that-must-never-leave-the-store"
KEY_VALUE = "sk-secret-value-that-must-never-leave-the-env"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _auth_store(**sections: object) -> str:
    return json.dumps({"version": 1, **sections})


class TableTests(unittest.TestCase):
    def test_every_kind_is_one_the_document_accepts_and_never_unknown(self) -> None:
        # `unknown` is a multi-vendor kind: mapping a Hermes id to it would
        # count every model as served on the strength of a key OMH cannot
        # place. Ids OMH cannot place are left out of the table instead.
        for provider_id, kind in detection.HERMES_PROVIDER_KINDS.items():
            with self.subTest(provider=provider_id):
                self.assertIn(kind, PROVIDER_KIND_VOCABULARY)
                self.assertNotEqual(kind, PROVIDER_KIND_UNKNOWN)
        for name, provider_id in detection.HERMES_ENV_KEY_PROVIDERS.items():
            with self.subTest(name=name):
                self.assertIn(provider_id, detection.HERMES_PROVIDER_KINDS)
        # Detection deliberately keeps its own narrower token grammar; stored
        # routing ids may name Hermes' custom provider, but this reader does
        # not infer a linked account from an unrecognized config/auth key.
        self.assertTrue(_CHAIN_TOKEN_RE.fullmatch("custom:cli-proxy"))
        self.assertFalse(detection.PROVIDER_ID_RE.fullmatch("custom:cli-proxy"))
        for token in ("openai-codex", "vendor/model", "bad id", "a" * 129):
            self.assertEqual(
                bool(detection.PROVIDER_ID_RE.fullmatch(token)),
                bool(_CHAIN_TOKEN_RE.fullmatch(token)),
            )

    def test_a_route_only_provider_stays_out_of_both_detection_tables(self) -> None:
        self.assertTrue(detection.ROUTE_ONLY_ENV_KEY_PROVIDERS)
        for name, provider_id in detection.ROUTE_ONLY_ENV_KEY_PROVIDERS.items():
            with self.subTest(name=name):
                self.assertNotIn(provider_id, detection.HERMES_PROVIDER_KINDS)
                self.assertNotIn(name, detection.HERMES_ENV_KEY_PROVIDERS)
                self.assertNotIn(provider_id, detection.HERMES_ENV_KEY_PROVIDERS.values())

    # Relays Hermes reads one key for, each named here rather than read back
    # from the table, so dropping a row from it fails these tests.
    ROUTE_ONLY_RELAYS = (
        ("COMMANDCODE_API_KEY", "commandcode"),
        ("KILOCODE_API_KEY", "kilocode"),
        ("AI_GATEWAY_API_KEY", "ai-gateway"),
    )

    def test_a_route_only_key_leaves_detection_and_the_chains_alone(self) -> None:
        # In the detection table this key is an account of kind `gateway`,
        # which serves every alias: shaping would fall back to the shipped
        # order and a key-holder's working category routes would refuse.
        for name, provider_id in self.ROUTE_ONLY_RELAYS:
            with self.subTest(name), TemporaryDirectory() as tmp:
                root = Path(tmp)
                without, with_key = root / "without" / "hermes", root / "with" / "hermes"
                _write(without / ".env", f"DEEPSEEK_API_KEY={KEY_VALUE}\n")
                _write(with_key / ".env", f"DEEPSEEK_API_KEY={KEY_VALUE}\n{name}={KEY_VALUE}\n")
                self.assertEqual(
                    [row["id"] for row in detection.detect_linked_providers(with_key)],
                    ["deepseek"],
                )
                self.assertEqual(
                    effective_mixture_category_chains(root / "with" / "omh", with_key),
                    effective_mixture_category_chains(root / "without" / "omh", without),
                )
                self.assertEqual(detection.route_only_provider_ids(with_key), {provider_id})

    def test_a_route_only_login_leaves_detection_and_the_chains_alone(self) -> None:
        # With a kind row, any of these counts as a `gateway` account and flips
        # category routes the same way the key does.
        for _name, provider_id in self.ROUTE_ONLY_RELAYS:
            for label, store in (
                ("manual row", {"credential_pool": {provider_id: [{"source": "manual"}]}}),
                ("active provider", {"active_provider": provider_id}),
                ("provider state", {"providers": {provider_id: {"token_type": "key"}}}),
            ):
                with self.subTest(provider_id, store=label), TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    without, held = root / "without" / "hermes", root / "held" / "hermes"
                    _write(without / ".env", f"DEEPSEEK_API_KEY={KEY_VALUE}\n")
                    _write(held / ".env", f"DEEPSEEK_API_KEY={KEY_VALUE}\n")
                    _write(held / "auth.json", _auth_store(**store))
                    self.assertEqual([row["id"] for row in detection.detect_linked_providers(held)], ["deepseek"])
                    self.assertEqual(
                        effective_mixture_category_chains(root / "held" / "omh", held),
                        effective_mixture_category_chains(root / "without" / "omh", without),
                    )
                    self.assertEqual(detection.route_only_provider_ids(held), {provider_id})

    def test_a_route_only_relay_block_in_config_stays_a_declared_gateway(self) -> None:
        # Only the key and the login stop counting; a `providers.<id>` block is
        # the person declaring the relay, and keeps the `gateway` default.
        for _name, provider_id in self.ROUTE_ONLY_RELAYS:
            for config in (
                f"providers:\n  {provider_id}:\n    base_url: https://relay.example/v1\n",
                f"model:\n  provider: {provider_id}\n",
            ):
                with self.subTest(provider_id, config=config), TemporaryDirectory() as tmp:
                    home = Path(tmp) / "hermes"
                    _write(home / "config.yaml", config)
                    self.assertEqual(
                        detection.detect_linked_providers(home),
                        [{"id": provider_id, "kind": "gateway", "source": "config", "evidence": "config.yaml"}],
                    )

    def test_a_routes_document_naming_a_held_route_only_relay_serves_its_aliases(self) -> None:
        # A gateway row made every route to the relay count as held. Without
        # the row, a route to a relay this home holds must still count, and
        # one to a relay it does not hold, or excluded, still must not.
        anthropic_only = {"providers": {"anthropic": "anthropic"}, "subscription_clis": []}
        aliases = sorted(
            {alias for chain in HERMES_MIXTURE_CATEGORY_CHAINS.values() for alias, _effort in chain}
            - {alias for chain in HERMES_MIXTURE_CATEGORY_CHAINS.values() for alias, _effort in chain if alias_is_served(alias, anthropic_only)}
        )
        self.assertTrue(aliases)
        for name, provider_id in self.ROUTE_ONLY_RELAYS:
            routes = {alias: (provider_id, f"vendor/{alias}") for alias in aliases}
            for label, env, excluded, held in (
                ("key", f"{name}={KEY_VALUE}\n", False, True),
                ("no key", "", False, False),
                ("excluded", f"{name}={KEY_VALUE}\n", True, False),
            ):
                with self.subTest(provider_id, case=label), TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    hermes, omh = root / "hermes", root / "omh"
                    _write(hermes / ".env", f"ANTHROPIC_API_KEY={KEY_VALUE}\n{env}")
                    if excluded:
                        _write(
                            provider_entitlements_path(omh),
                            json.dumps(
                                {
                                    "schema_version": PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
                                    "providers": {"anthropic": "anthropic"},
                                    "excluded_providers": [provider_id],
                                }
                            ),
                        )
                    entitlements, _status, _rows = effective_provider_entitlements(omh, hermes)
                    self.assertEqual(entitlements["providers"], {"anthropic": "anthropic"})
                    self.assertEqual([alias for alias in aliases if alias_is_served(alias, entitlements, routes)], aliases if held else [])
                    unknown = routes_to_unknown_providers(routes, entitlements)
                    self.assertEqual(sorted({row["route"] for row in unknown}), [] if held else aliases)

    def test_generic_and_implicit_tokens_are_not_provider_evidence(self) -> None:
        # Hermes' registry lists CLAUDE_CODE_OAUTH_TOKEN under its implicit
        # variables: Claude Code sets it, the operator did not configure
        # Anthropic in Hermes, and the Hermes lane cannot spend a Claude
        # subscription. Counting it would lead every chain with Claude.
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "HF_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
            self.assertNotIn(name, detection.HERMES_ENV_KEY_PROVIDERS)
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "hermes"
            _write(home / ".env", f"CLAUDE_CODE_OAUTH_TOKEN={KEY_VALUE}\n")
            self.assertEqual(detection.detect_linked_providers(home), [])
            self.assertEqual(effective_mixture_category_chains(Path(tmp) / "omh", home), dict(HERMES_MIXTURE_CATEGORY_CHAINS))


class AuthStoreTests(unittest.TestCase):
    def test_ids_come_from_every_section_and_no_value_comes_with_them(self) -> None:
        text = _auth_store(
            providers={
                "openai-codex": {"access_token": TOKEN, "refresh_token": TOKEN, "auth_mode": "chatgpt"},
                "spotify": {"access_token": TOKEN},
                "empty": {},
                "not a token": {"access_token": TOKEN},
            },
            credential_pool={"zai": [{"id": "k1", "api_key": TOKEN, "label": "work", "source": "manual"}], "nous": []},
            active_provider="xai-oauth",
        )
        ids = detection.auth_store_provider_ids(text)
        self.assertEqual(ids, ["openai-codex", "spotify", "xai-oauth", "zai"])
        self.assertNotIn(TOKEN, json.dumps(ids))
        self.assertNotIn("work", json.dumps(ids))

    def test_pool_rows_count_only_when_hermes_itself_would_count_them(self) -> None:
        # Mirror of Hermes' `_pool_entry_is_explicit`: its own flows and a
        # manual add count; a credential borrowed from another CLI does not;
        # an env-seeded row counts only while its variable is still in .env.
        text = _auth_store(
            credential_pool={
                "anthropic": [{"api_key": TOKEN, "source": "claude_code"}],
                "copilot": [{"api_key": TOKEN, "source": "gh_cli"}],
                "qwen-oauth": [{"api_key": TOKEN, "source": "qwen-cli"}],
                "openai-codex": [{"api_key": TOKEN, "source": "device_code"}],
                "xai-oauth": [{"api_key": TOKEN, "source": "Loopback_PKCE"}],
                "nous": [{"api_key": TOKEN, "source": "manual:paste"}],
                "zai": [{"api_key": TOKEN, "source": "env:ZAI_API_KEY"}],
                "deepseek": [{"api_key": TOKEN, "source": "env:DEEPSEEK_API_KEY"}],
                "kimi-coding": [{"api_key": TOKEN}],
                "gemini": ["not a row"],
            },
        )
        self.assertEqual(
            detection.auth_store_provider_ids(text, env_names=["ZAI_API_KEY"]),
            ["nous", "openai-codex", "xai-oauth", "zai"],
        )
        self.assertEqual(detection.auth_store_provider_ids(text), ["nous", "openai-codex", "xai-oauth"])

    def test_an_unreadable_or_foreign_store_yields_nothing(self) -> None:
        self.assertEqual(detection.auth_store_provider_ids("not json"), [])
        self.assertEqual(detection.auth_store_provider_ids("[1, 2]"), [])
        self.assertEqual(detection.auth_store_provider_ids(json.dumps({"providers": "x"})), [])
        self.assertEqual(detection.auth_store_provider_ids(json.dumps({"active_provider": "no spaces here"})), [])


class ConfigReaderTests(unittest.TestCase):
    FIXTURES = (
        "",
        "model:\n  provider: og\nproviders:\n  og:\n    base_url: x\n  zai:\n    base_url: y\n",
        "model:\n  provider: 'openai-codex'\n  default: gpt\nproviders:\n  openai-codex:\n    enabled: true\n",
        "providers:\n  og:\n    base_url: x\n\nmodel:\n  provider: og\n",
        "model:\n  provider: auto\nstt:\n  openai:\n    model: whisper\nproviders: {}\n",
        "providers:\n  # comment\n  \"quoted\":\n    base_url: x\n  <<: *anchor\n",
        "model:\n  name: x\n",
    )

    def test_the_core_side_reads_through_the_bundle_reader(self) -> None:
        # One function, not two mirrored ones: a fuzz of the earlier mirror
        # found 269 configs the two read apart (an empty first `provider:`
        # line, a quoted or commented value).
        self.assertIs(core_configured_provider_ids, detection.configured_provider_ids)
        for text in self.FIXTURES:
            with self.subTest(text=text):
                self.assertEqual(detection.configured_provider_ids(text), core_configured_provider_ids(text))

    def test_values_are_unquoted_uncommented_and_the_first_non_empty_wins(self) -> None:
        self.assertEqual(detection.configured_provider_ids("model:\n  provider:\n  provider: 'og'  # c\n"), ["og"])
        self.assertEqual(detection.configured_provider_ids("model.provider: \"zai\"\nproviders:\n  og:\n"), ["zai", "og"])
        self.assertEqual(detection.configured_provider_ids("model:\n  provider: og # trailing\nproviders:\n  og:\n"), ["og"])


class DetectionTests(unittest.TestCase):
    def _home(self, root: Path) -> Path:
        home = root / "hermes"
        _write(
            home / "config.yaml",
            "model:\n  provider: og\nproviders:\n  og:\n    base_url: https://x\n  zai:\n    base_url: y\n"
            "  lmstudio-local:\n    base_url: http://127.0.0.1:1234/v1\n  ollama-box:\n    base_url: 'http://localhost:11434/v1'\n",
        )
        _write(
            home / "auth.json",
            _auth_store(
                providers={"openai-codex": {"access_token": TOKEN}, "spotify": {"access_token": TOKEN}},
                credential_pool={"og": [{"api_key": TOKEN, "source": "manual"}], "mystery": [{"api_key": TOKEN, "source": "manual"}]},
                active_provider="openai-codex",
            ),
        )
        _write(home / ".env", f"# keys\nexport ANTHROPIC_API_KEY={KEY_VALUE}\nMINIMAX_API_KEY={KEY_VALUE}\nUNRELATED=1\n")
        return home

    def test_login_then_config_then_env_names_one_row_per_id(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._home(Path(tmp))
            # A key exported only in the shell is not something Hermes
            # recorded: the process environment is not read.
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": KEY_VALUE}, clear=True):
                rows = detection.detect_linked_providers(home)
        self.assertEqual(
            [(row["id"], row["kind"], row["source"], row["evidence"]) for row in rows],
            [
                # A custom endpoint whose credential sits in the store: the
                # login is the stronger evidence, the config key gave the kind.
                ("og", "gateway", "login", "auth.json"),
                ("openai-codex", "openai-codex", "login", "auth.json"),
                ("zai", "zai", "config", "config.yaml"),
                ("anthropic", "anthropic", "env", "ANTHROPIC_API_KEY"),
            ],
        )
        serialized = json.dumps(rows)
        self.assertNotIn(TOKEN, serialized)
        self.assertNotIn(KEY_VALUE, serialized)
        # Spotify is a service login, `mystery` is a pool entry no config
        # names, MiniMax serves nothing the catalog describes, the two
        # loopback blocks serve a local model under a local name: none count.
        for absent in ("spotify", "mystery", "minimax", "deepseek", "lmstudio-local", "ollama-box"):
            self.assertNotIn(absent, serialized)

    def test_auto_is_a_mode_not_a_provider_and_a_caller_may_supply_the_names(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "hermes"
            _write(home / "config.yaml", "model:\n  provider: auto\n")
            _write(home / ".env", f"OPENAI_API_KEY={KEY_VALUE}\n")
            self.assertEqual(
                [(row["id"], row["kind"], row["source"]) for row in detection.detect_linked_providers(home)],
                [("openai-api", "openai", "env")],
            )
            # Supplied names replace the read, so an interview that already
            # read them (the shell's included) can hold them still.
            self.assertEqual(detection.detect_linked_providers(home, env_names=()), [])
            self.assertEqual(
                [row["evidence"] for row in detection.detect_linked_providers(home, env_names={"ZAI_API_KEY"})],
                ["ZAI_API_KEY"],
            )

    def test_names_come_from_the_file_and_only_from_the_environment_when_handed_in(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "hermes"
            _write(home / ".env", f"export GLM_API_KEY={KEY_VALUE}\nXAI_API_KEY = {KEY_VALUE}\n# GEMINI_API_KEY=commented\nNOT_A_KEY\n")
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": KEY_VALUE}, clear=True):
                self.assertEqual(detection.env_key_names(home), ["GLM_API_KEY", "XAI_API_KEY"])
                names = detection.env_key_names(home, environ={"KIMI_API_KEY": KEY_VALUE, "PATH": "/bin"})
        self.assertEqual(names, ["GLM_API_KEY", "KIMI_API_KEY", "XAI_API_KEY"])

    def test_an_empty_line_is_not_a_key_and_the_last_line_decides(self) -> None:
        empty = ("X=", "X=   ", 'X=""', "X=''", 'X="  "', 'X="" # none yet', "X='' # none yet", "export X=")
        filled = (f"X={KEY_VALUE}", f'X="{KEY_VALUE}"', "X=# note", 'X="', '""x', 'X="" tail')
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "hermes"
            for line in empty:
                with self.subTest(empty=line):
                    _write(home / ".env", line.replace("X", "DEEPSEEK_API_KEY") + "\n")
                    self.assertEqual(detection.env_key_names(home), [])
                    self.assertEqual(detection.detect_linked_providers(home), [])
            for line in filled:
                with self.subTest(filled=line):
                    text = line.replace("X", "DEEPSEEK_API_KEY") if "=" in line else f"DEEPSEEK_API_KEY={line}"
                    _write(home / ".env", text + "\n")
                    self.assertEqual(detection.env_key_names(home), ["DEEPSEEK_API_KEY"])
            _write(home / ".env", f"DEEPSEEK_API_KEY={KEY_VALUE}\nDEEPSEEK_API_KEY=\n")
            self.assertEqual(detection.env_key_names(home), [])
            _write(home / ".env", f"DEEPSEEK_API_KEY=\nDEEPSEEK_API_KEY={KEY_VALUE}\n")
            self.assertEqual(detection.env_key_names(home), ["DEEPSEEK_API_KEY"])

    def test_an_empty_line_stops_counting_for_every_reader_of_the_names(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "hermes"
            _write(home / ".env", f"ANTHROPIC_API_KEY=\nXAI_API_KEY={KEY_VALUE}\nTYPESAFE_API_KEY=\nOMH_HOME=\n")
            self.assertEqual([row["id"] for row in detection.detect_linked_providers(home)], ["xai"])
            self.assertEqual(detection.env_key_names(home, allowed=("TYPESAFE_API_KEY",)), [])
            self.assertEqual(detection.env_key_names(home, allowed=("OMH_HOME",)), [])
            # A pool row seeded from the variable lapses with it, as Hermes' does.
            store = _auth_store(credential_pool={"anthropic": [{"source": "env:ANTHROPIC_API_KEY"}]})
            self.assertEqual(detection.auth_store_provider_ids(store, detection.env_key_names(home)), [])

    def test_a_filled_line_returns_the_name_and_never_the_value(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "hermes"
            _write(home / ".env", f"DEEPSEEK_API_KEY={KEY_VALUE}\n")
            self.assertNotIn(KEY_VALUE, repr(detection.env_key_names(home)))
            self.assertNotIn(KEY_VALUE, repr(detection.detect_linked_providers(home)))

    def test_local_endpoints_are_read_from_their_base_url_line(self) -> None:
        text = (
            "providers:\n  og:\n    base_url: https://apis.example/v1\n  lm:\n    base_url: http://127.0.0.1:1234/v1\n"
            "  six:\n    base_url: http://[::1]:8080/v1  # comment\n  docker:\n    base_url: \"http://host.docker.internal:11434\"\n"
            "  nested:\n    extra:\n      base_url: http://localhost:1\n  bare:\n    base_url: localhost:9\n"
        )
        self.assertEqual(detection.local_config_provider_ids(text), ["lm", "six", "docker", "bare"])

    def test_a_missing_or_unbound_home_yields_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(detection.detect_linked_providers(Path(tmp) / "absent", env_names=()), [])
        with patch.object(runtime_paths, "default_hermes_home", side_effect=runtime_paths.RuntimeBindingError("unbound")):
            self.assertEqual(detection.detect_linked_providers(None, env_names=()), [])


class LinkedEntitlementTests(unittest.TestCase):
    """`effective_provider_entitlements`: detection is the baseline, the record wins."""

    def _login_only(self, root: Path) -> tuple[Path, Path]:
        omh_home = root / "omh"
        hermes_home = root / "hermes"
        _write(hermes_home / "auth.json", _auth_store(providers={"openai-codex": {"access_token": TOKEN}}))
        return omh_home, hermes_home

    def test_nothing_recorded_and_nothing_linked_is_none(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            entitlements, status, providers = effective_provider_entitlements(Path(tmp) / "omh", Path(tmp) / "hermes")
        self.assertEqual((entitlements, status, providers), (None, "absent", ()))

    def test_a_login_counts_without_an_interview_and_reorders_the_chains(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            omh_home, hermes_home = self._login_only(Path(tmp))
            entitlements, status, providers = effective_provider_entitlements(omh_home, hermes_home)
            self.assertEqual(entitlements, {"providers": {"openai-codex": "openai-codex"}, "subscription_clis": []})
            # The document's own status is still reported: nobody answered.
            self.assertEqual(status, "absent")
            self.assertEqual(
                providers, ({"id": "openai-codex", "kind": "openai-codex", "source": "login", "evidence": "auth.json"},)
            )
            chains = effective_mixture_category_chains(omh_home, hermes_home)
        quick = HERMES_MIXTURE_CATEGORY_CHAINS["quick"]
        self.assertNotEqual(quick[0][0], "gpt-6-luna")
        self.assertEqual(chains["quick"][0][0], "gpt-6-luna")
        self.assertEqual(sorted(chains["quick"]), sorted(quick))

    def test_the_recorded_kind_wins_and_neither_side_drops_the_other(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            omh_home, hermes_home = self._login_only(Path(tmp))
            _write(hermes_home / "config.yaml", "providers:\n  og:\n    base_url: x\n")
            _write(
                provider_entitlements_path(omh_home),
                json.dumps(
                    {
                        "schema_version": PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
                        "providers": {"og": "zai", "hand-added": "gateway"},
                        "subscription_clis": ["claude-code"],
                    }
                ),
            )
            entitlements, status, providers = effective_provider_entitlements(omh_home, hermes_home)
        self.assertEqual(status, "applied")
        self.assertEqual(
            entitlements,
            {
                "providers": {"hand-added": "gateway", "og": "zai", "openai-codex": "openai-codex"},
                "subscription_clis": ["claude-code"],
            },
        )
        self.assertEqual(
            [(row["id"], row["source"]) for row in providers],
            [("hand-added", "recorded"), ("og", "recorded"), ("openai-codex", "login")],
        )

    def test_an_excluded_linked_provider_stops_counting(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            omh_home, hermes_home = self._login_only(Path(tmp))
            _write(hermes_home / ".env", f"ZAI_API_KEY={KEY_VALUE}\n")
            _write(
                provider_entitlements_path(omh_home),
                json.dumps({"schema_version": PROVIDER_ENTITLEMENTS_SCHEMA_VERSION, "excluded_providers": ["openai-codex"]}),
            )
            entitlements, status, providers = effective_provider_entitlements(omh_home, hermes_home)
        self.assertEqual(status, "applied")
        self.assertEqual(entitlements["providers"], {"zai": "zai"})
        self.assertEqual([(row["id"], row["source"]) for row in providers], [("zai", "env")])

    def test_an_env_row_the_record_already_holds_is_one_account_not_two(self) -> None:
        # The interview once recorded OPENAI_API_KEY under the family id
        # `openai`; detection names Hermes' `openai-api`. One key, one row.
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            omh_home = Path(tmp) / "omh"
            hermes_home = Path(tmp) / "hermes"
            _write(hermes_home / ".env", f"OPENAI_API_KEY={KEY_VALUE}\nZAI_API_KEY={KEY_VALUE}\n")
            _write(hermes_home / "auth.json", _auth_store(providers={"openai-codex": {"access_token": TOKEN}}))
            _write(
                provider_entitlements_path(omh_home),
                json.dumps({"schema_version": PROVIDER_ENTITLEMENTS_SCHEMA_VERSION, "providers": {"openai": "openai", "my-zai": "zai"}}),
            )
            entitlements, _status, providers = effective_provider_entitlements(omh_home, hermes_home)
        # `openai-api` (kind openai) is covered by the recorded `openai`; `zai`
        # (kind zai) by the recorded `my-zai`; the Codex login is a distinct
        # Hermes provider and stands.
        self.assertEqual(
            [(row["id"], row["source"]) for row in providers],
            [("my-zai", "recorded"), ("openai", "recorded"), ("openai-codex", "login")],
        )
        self.assertEqual(set(entitlements["providers"]), {"my-zai", "openai", "openai-codex"})
        self.assertTrue(detection.env_row_is_covered({"source": "env", "kind": "openai"}, {"openai": "openai"}))
        self.assertTrue(detection.env_row_is_covered({"source": "env", "kind": "zai"}, {"my-zai": "zai"}))
        self.assertFalse(detection.env_row_is_covered({"source": "login", "kind": "openai"}, {"openai": "openai"}))
        self.assertFalse(detection.env_row_is_covered({"source": "env", "kind": "gemini"}, {"openai": "openai"}))

    def test_an_invalid_record_leaves_the_linked_providers_standing(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            omh_home, hermes_home = self._login_only(Path(tmp))
            _write(provider_entitlements_path(omh_home), "{not json")
            entitlements, status, _providers = effective_provider_entitlements(omh_home, hermes_home)
        self.assertTrue(status.startswith("invalid:"), status)
        self.assertEqual(entitlements["providers"], {"openai-codex": "openai-codex"})


class SurfaceTests(unittest.TestCase):
    def test_the_picker_marks_served_from_the_linked_providers_and_lists_them(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _write(root / "hermes" / "auth.json", _auth_store(providers={"openai-codex": {"access_token": TOKEN}}))
            payload = picker_rows(root / "omh", hermes_home=root / "hermes")
        self.assertEqual(payload["providers"], [{"id": "openai-codex", "kind": "openai-codex", "source": "login", "evidence": "auth.json"}])
        served = {row["alias"]: row["served"] for row in payload["models"]}
        self.assertTrue(served["gpt-6-astra"])
        self.assertFalse(served["kimi-k3.1-pro"])
        self.assertNotIn(TOKEN, json.dumps(payload))

    def test_show_names_the_linked_providers_and_the_reorder(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            _write(root / "hermes" / "auth.json", _auth_store(providers={"openai-codex": {"access_token": TOKEN}}))
            homes = ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes")]
            status, text, _stderr = run_cli([*homes, "model-chains", "show"], output_json=False)
            self.assertEqual(status, 0)
            self.assertIn("Linked Hermes providers: openai-codex (login)", text)
            self.assertIn("quick: gpt-6-luna:low", text)
            self.assertIn("(reordered by this machine's providers)", text)
            self.assertNotIn(TOKEN, text)
            _status, out, _stderr = run_cli([*homes, "model-chains", "show", "--json"])
            self.assertEqual(json.loads(out)["providers"], [{"id": "openai-codex", "kind": "openai-codex", "source": "login", "evidence": "auth.json"}])
            homes[-1] = str(root / "nowhere")
            _status, text, _stderr = run_cli([*homes, "model-chains", "show"], output_json=False)
            self.assertIn("Linked Hermes providers: none found", text)


if __name__ == "__main__":
    unittest.main()
