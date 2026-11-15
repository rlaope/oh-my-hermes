from __future__ import annotations

import json
import os
from pathlib import Path
import textwrap
import unittest

from _local_package import load_local_package
from _test_temp_root import make_test_tempdir

load_local_package()

from omh.coding.hermes_model_config import (  # noqa: E402
    AliasCollisionError,
    ConfirmationRequiredError,
    ConfigDigestMismatchError,
    HermesCommandError,
    HermesModelConfigError,
    _auth_provider_ids,
    apply_hermes_model_config,
    inspect_hermes_model_config,
    preview_hermes_model_config,
)


_FAKE_HERMES = r"""
#!/usr/bin/env python3
import json
import os
from pathlib import Path
import signal
import sys
from threading import Event

# Like Hermes itself (hermes_cli/__init__.py), write UTF-8 whatever the
# locale codec is, so Windows exercises the bytes a real Hermes emits.
sys.stdout.reconfigure(encoding="utf-8")
home = Path(os.environ["HERMES_HOME"])
state_path = home / "config.yaml"
log_path = home / "commands.jsonl"
home.mkdir(parents=True, exist_ok=True)
with log_path.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")
state = json.loads(state_path.read_text(encoding="utf-8"))

def get(key):
    current = state
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(key)
        current = current[part]
    return current

args = sys.argv[1:]
if os.environ.get("HERMES_HANG") == " ".join(args):
    Event().wait()
if args == ["config", "path"]:
    print(state_path)
elif args[:2] == ["config", "get"]:
    try:
        value = get(args[2])
    except KeyError:
        raise SystemExit(1)
    print(json.dumps(value))
elif args == ["config", "check"]:
    if os.environ.get("HERMES_CONFIG_CHECK_FAIL"):
        raise SystemExit(1)
    print("Configuration OK")
elif args[:2] == ["auth", "list"]:
    if not os.environ.get("HERMES_AUTH_MISSING"):
        print("alpha (1 credentials):")
        print("SECRET_VALUE_MUST_NOT_ESCAPE")
        for line in json.loads(os.environ.get("HERMES_AUTH_LIST_EXTRA", "[]")):
            print(line)
elif args[:2] == ["auth", "status"]:
    present = (
        args[2] in {"alpha", *os.environ.get("HERMES_AUTH_STATUS_OK", "").split(",")}
        and not os.environ.get("HERMES_AUTH_MISSING")
    )
    raise SystemExit(0 if present else 1)
elif args[:2] == ["config", "set"]:
    failure_marker = home / "mutation-failed"
    if os.environ.get("HERMES_FAIL_MUTATION") == args[2] and not failure_marker.exists():
        failure_marker.touch()
        raise SystemExit(9)
    current = state
    parts = args[2].split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = args[3]
    if os.environ.get("HERMES_CONCURRENT_ALIAS"):
        state["model"]["aliases"]["foreign"] = "foreign/concurrent"
    if os.environ.get("HERMES_CONCURRENT_TARGET_ALIAS"):
        state["model"]["aliases"][args[2].removeprefix("model.aliases.")] = "foreign/concurrent"
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    failure_after_marker = home / "mutation-failed-after"
    if (
        os.environ.get("HERMES_FAIL_AFTER_MUTATION") == args[2]
        and not failure_after_marker.exists()
    ):
        failure_after_marker.touch()
        raise SystemExit(9)
elif args[:2] == ["config", "unset"]:
    failure_marker = home / "mutation-failed"
    if os.environ.get("HERMES_FAIL_MUTATION") == args[2] and not failure_marker.exists():
        failure_marker.touch()
        raise SystemExit(9)
    current = state
    parts = args[2].split(".")
    for part in parts[:-1]:
        current = current[part]
    current.pop(parts[-1], None)
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    failure_after_marker = home / "mutation-failed-after"
    if (
        os.environ.get("HERMES_FAIL_AFTER_MUTATION") == args[2]
        and not failure_after_marker.exists()
    ):
        failure_after_marker.touch()
        raise SystemExit(9)
else:
    raise SystemExit(f"unexpected command: {args}")
"""


class HermesModelConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        # Nested under the shared, swept parent (issue #1731): this is the
        # dir that held the "hermes.py config path" fake host a killed run
        # left alive for 8 days on the owner's machine (measured 2026-09-19).
        self.temp = make_test_tempdir(prefix="omh-hermes-model-config-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "hermes-home"
        self.home.mkdir()
        self.hermes = Path(self.temp.name) / "hermes.py"
        self.hermes.write_text(textwrap.dedent(_FAKE_HERMES).lstrip(), encoding="utf-8")
        self.hermes.chmod(0o755)
        self.config = self.home / "config.yaml"
        self.config.write_text(
            json.dumps(
                {
                    "model_aliases": {"legacy": "alpha/legacy"},
                    "model": {
                        "provider": "alpha",
                        "aliases": {"fast": "alpha/fast", "retire": "beta/old"},
                    },
                    "plugins": {
                        "enabled": ["alpha"],
                        "entries": {"alpha": {"token": "SECRET_VALUE_MUST_NOT_ESCAPE"}},
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self.env = {"HERMES_HOME": str(self.home), "PATH": os.environ["PATH"]}

    def state(self) -> dict[str, object]:
        return json.loads(self.config.read_text(encoding="utf-8"))

    def test_inspect_uses_only_local_secret_free_commands(self) -> None:
        # Given: a config with legacy and nested aliases, auth, and one provider plugin.
        # When: the adapter inspects the Hermes-native surfaces.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)

        # Then: it returns structured presence only and never exposes command output secrets.
        self.assertEqual(dict(inspection.model_aliases), {"legacy": "alpha/legacy"})
        self.assertEqual(
            dict(inspection.model_dot_aliases),
            {"fast": "alpha/fast", "retire": "beta/old"},
        )
        providers = {item.provider_id: item for item in inspection.providers}
        self.assertTrue(providers["alpha"].auth_present)
        self.assertTrue(providers["alpha"].auth_status_ok)
        self.assertTrue(providers["alpha"].plugin_present)
        self.assertFalse(providers["beta"].auth_present)
        self.assertFalse(providers["beta"].auth_status_ok)
        self.assertFalse(providers["beta"].plugin_present)
        self.assertNotIn("SECRET_VALUE_MUST_NOT_ESCAPE", repr(inspection))
        flattened = [part for command in inspection.commands for part in command]
        self.assertNotIn("model", flattened)
        self.assertNotIn("--refresh", flattened)
        self.assertNotIn("env-path", flattened)

    def test_preview_emits_exact_set_and_unset_commands(self) -> None:
        # Given: a current digest and non-colliding alias changes.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)

        # When: a nested-alias update is previewed.
        preview = preview_hermes_model_config(
            inspection,
            {"new": "alpha/new", "retire": None},
            allow_collisions=True,
        )

        # Then: the preview contains the exact Hermes-native argv and no mutation occurred.
        self.assertEqual(
            preview.commands,
            (
                (str(self.hermes), "config", "set", "model.aliases.new", "alpha/new"),
                (str(self.hermes), "config", "unset", "model.aliases.retire"),
            ),
        )
        self.assertIn('"retire"', self.config.read_text(encoding="utf-8"))

    def test_preview_refuses_existing_alias_collision_by_default(self) -> None:
        # Given: an existing nested alias.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)

        # When/Then: changing its target without an override is refused.
        with self.assertRaises(AliasCollisionError):
            preview_hermes_model_config(inspection, {"fast": "beta/replacement"})

    def test_inspect_sanitizes_secret_shaped_alias_and_plugin_metadata(self) -> None:
        # Given: Hermes metadata keys and values shaped like issued credentials.
        secret = "sk-" + ("a" * 24)
        state = self.state()
        state["model"]["aliases"][secret] = f"{secret}/model"
        state["plugins"]["enabled"].append(secret)
        state["plugins"]["entries"][secret] = {}
        self.config.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

        # When: the adapter inspects provider metadata.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)

        # Then: the secret shape reaches neither the payload nor auth subprocess argv.
        self.assertNotIn(secret, repr(inspection))
        commands = [
            json.loads(line)
            for line in (self.home / "commands.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertFalse(any(secret in part for command in commands for part in command))

    def test_preview_rejects_secret_shaped_alias_before_building_payload(self) -> None:
        # Given: an inspected config and an alias shaped like an issued credential.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)
        secret_alias = "sk-" + ("b" * 24)

        # When/Then: preview construction rejects it before producing command payloads.
        with self.assertRaises(HermesModelConfigError):
            preview_hermes_model_config(inspection, {secret_alias: "alpha/model"})

    def test_subprocess_timeout_is_bounded_and_reported(self) -> None:
        # Given: the isolated Hermes CLI hangs before returning its config path.
        env = {**self.env, "HERMES_HANG": "config path"}

        # When/Then: the real child process is killed at the bound and reported as unobserved.
        with self.assertRaisesRegex(HermesCommandError, "timed out after 10s"):
            inspect_hermes_model_config(hermes=str(self.hermes), env=env)

    def test_preview_refuses_failed_config_check(self) -> None:
        # Given: Hermes reports the local config is invalid.
        inspection = inspect_hermes_model_config(
            hermes=str(self.hermes),
            env={**self.env, "HERMES_CONFIG_CHECK_FAIL": "1"},
        )

        # When/Then: no mutation preview is produced.
        with self.assertRaises(HermesModelConfigError):
            preview_hermes_model_config(inspection, {"new": "alpha/new"})

    def test_preview_refuses_target_provider_without_required_auth(self) -> None:
        # Given: the target provider has no observed Hermes auth.
        inspection = inspect_hermes_model_config(
            hermes=str(self.hermes),
            env={**self.env, "HERMES_AUTH_MISSING": "1"},
        )

        # When/Then: an alias targeting that provider is refused before apply.
        with self.assertRaises(HermesModelConfigError):
            preview_hermes_model_config(inspection, {"new": "alpha/new"})

    def test_apply_requires_confirmation_and_matching_digest(self) -> None:
        # Given: a valid preview.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)
        preview = preview_hermes_model_config(inspection, {"new": "alpha/new"})

        # When/Then: both explicit confirmation and the previewed digest are CAS gates.
        with self.assertRaises(ConfirmationRequiredError):
            apply_hermes_model_config(
                preview,
                confirmed=False,
                expected_config_digest=inspection.config_digest,
                env=self.env,
            )
        self.config.write_text(self.config.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(ConfigDigestMismatchError):
            apply_hermes_model_config(
                preview,
                confirmed=True,
                expected_config_digest=inspection.config_digest,
                env=self.env,
            )

    def test_apply_writes_and_verifies_nested_aliases(self) -> None:
        # Given: a confirmed preview whose config digest still matches.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)
        preview = preview_hermes_model_config(
            inspection,
            {"new": "alpha/new", "retire": None},
            allow_collisions=True,
        )

        # When: the adapter applies the exact preview.
        receipt = apply_hermes_model_config(
            preview,
            confirmed=True,
            expected_config_digest=inspection.config_digest,
            env=self.env,
        )

        # Then: post-write inspection verifies both the set and unset.
        self.assertTrue(receipt.verified)
        self.assertNotEqual(receipt.before_digest, receipt.after_digest)
        self.assertEqual(dict(receipt.inspection.model_dot_aliases), {"fast": "alpha/fast", "new": "alpha/new"})
        commands = [
            json.loads(line)
            for line in (self.home / "commands.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertFalse(any(command and command[0] == "model" for command in commands))
        self.assertFalse(any("env-path" in command or "--refresh" in command for command in commands))

    def test_apply_rolls_back_attempted_aliases_after_concurrent_drift(self) -> None:
        # Given: a two-alias preview and an external alias mutation during the first write.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)
        preview = preview_hermes_model_config(
            inspection,
            {"new": "alpha/new", "retire": None},
            allow_collisions=True,
        )

        # When: apply observes that concurrent mutation before completing the preview.
        with self.assertRaises(ConfigDigestMismatchError):
            apply_hermes_model_config(
                preview,
                confirmed=True,
                expected_config_digest=inspection.config_digest,
                env={**self.env, "HERMES_CONCURRENT_ALIAS": "1"},
            )

        # Then: this attempt is rolled back while the foreign mutation is preserved.
        aliases = self.state()["model"]["aliases"]
        self.assertNotIn("new", aliases)
        self.assertEqual(aliases["retire"], "beta/old")
        self.assertEqual(aliases["foreign"], "foreign/concurrent")

    def test_apply_rolls_back_all_attempted_aliases_after_partial_failure(self) -> None:
        # Given: a two-alias preview whose second Hermes mutation will fail.
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)
        preview = preview_hermes_model_config(
            inspection,
            {"new": "alpha/new", "retire": None},
            allow_collisions=True,
        )

        # When: the second mutation exits unsuccessfully.
        with self.assertRaises(HermesCommandError):
            apply_hermes_model_config(
                preview,
                confirmed=True,
                expected_config_digest=inspection.config_digest,
                env={**self.env, "HERMES_FAIL_MUTATION": "model.aliases.retire"},
            )

        # Then: both attempted aliases are restored to their inspected pre-apply values.
        aliases = self.state()["model"]["aliases"]
        self.assertNotIn("new", aliases)
        self.assertEqual(aliases["retire"], "beta/old")

    def test_apply_refuses_rollback_when_attempted_alias_ownership_is_lost(self) -> None:
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)
        preview = preview_hermes_model_config(inspection, {"new": "alpha/new"})

        with self.assertRaisesRegex(ConfigDigestMismatchError, "rollback refused"):
            apply_hermes_model_config(
                preview,
                confirmed=True,
                expected_config_digest=inspection.config_digest,
                env={**self.env, "HERMES_CONCURRENT_TARGET_ALIAS": "1"},
            )

        self.assertEqual(self.state()["model"]["aliases"]["new"], "foreign/concurrent")

    def test_apply_rolls_back_owned_mutation_when_command_exits_nonzero_after_write(self) -> None:
        inspection = inspect_hermes_model_config(hermes=str(self.hermes), env=self.env)
        preview = preview_hermes_model_config(inspection, {"new": "alpha/new"})

        with self.assertRaises(HermesCommandError):
            apply_hermes_model_config(
                preview,
                confirmed=True,
                expected_config_digest=inspection.config_digest,
                env={**self.env, "HERMES_FAIL_AFTER_MUTATION": "model.aliases.new"},
            )

        self.assertNotIn("new", self.state()["model"]["aliases"])

    def custom_pool_inspection(self, *, configured: bool = True):
        # Issue #1998's machine: model.provider is custom, the gateway is a
        # legacy custom_providers entry, and `hermes auth list` prints its pool
        # under the composed `custom:<name>` id (verbatim from the report).
        state = self.state()
        state["model"]["provider"] = "custom"
        if configured:
            state["custom_providers"] = [
                {"name": "9router", "base_url": "http://localhost:20128/v1", "key_env": "ROUTER_KEY"}
            ]
        self.config.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        env = {
            **self.env,
            "HERMES_AUTH_LIST_EXTRA": json.dumps(
                [
                    "custom:9router (2 credentials):",
                    "  #1  model_config         api_key id=9e6622 priority=0 model_config ←",
                    "  #2  api-key-2            api_key id=7992e4 priority=1 manual",
                ]
            ),
            # Hermes' `auth status` resolves both spellings to the same pool.
            "HERMES_AUTH_STATUS_OK": "9router,custom:9router",
        }
        return inspect_hermes_model_config(hermes=str(self.hermes), env=env)

    def test_auth_list_parses_the_composed_custom_pool_header(self) -> None:
        # Given: header lines as `hermes auth list` prints them (issue #1998).
        output = "\n".join(
            [
                "nous (1 credentials):",
                "openai-codex (1 credentials):",
                "custom:9router (2 credentials):",
                "  #1  model_config         api_key id=9e6622 priority=0 model_config ←",
                "custom:together.ai (1 credentials):",
            ]
        )

        # When/Then: built-in ids and composed custom pool ids are both observed.
        self.assertEqual(
            _auth_provider_ids(output),
            {"nous", "openai-codex", "custom:9router", "custom:together.ai"},
        )

    def test_auth_list_refuses_colon_headers_outside_the_custom_pool_shape(self) -> None:
        # Given: headers that carry a colon but are not `custom:<name>`.
        secret = "sk-" + ("c" * 24)
        output = "\n".join(
            [
                "foo:bar (1 credentials):",
                "custom:9router:extra (1 credentials):",
                "custom: (1 credentials):",
                "custom:9router/evil (1 credentials):",
                "https://evil.example (1 credentials):",
                "nous: free tier",
                f"custom:{secret} (1 credentials):",
            ]
        )

        # When/Then: none of them is observed as a provider id.
        self.assertEqual(_auth_provider_ids(output), set())

    def test_custom_pool_auth_binds_alias_under_the_configured_provider_name(self) -> None:
        # Given: the custom-pool machine from issue #1998.
        inspection = self.custom_pool_inspection()
        providers = {item.provider_id: item for item in inspection.providers}

        # Then: both the pool id and the configured name carry the observed auth.
        self.assertTrue(providers["custom:9router"].auth_present)
        self.assertTrue(providers["9router"].auth_present)
        self.assertTrue(providers["9router"].auth_status_ok)
        self.assertFalse(providers["custom"].auth_present)

        # When: aliases target the gateway by its configured name or pool id.
        preview = preview_hermes_model_config(
            inspection,
            {"main": "9router/clv/kimi-k3", "pool": "custom:9router/clv/kimi-k3"},
        )

        # Then: both bind, written exactly as Hermes resolves them.
        self.assertEqual(
            preview.commands,
            (
                (str(self.hermes), "config", "set", "model.aliases.main", "9router/clv/kimi-k3"),
                (str(self.hermes), "config", "set", "model.aliases.pool", "custom:9router/clv/kimi-k3"),
            ),
        )

    def test_bare_custom_target_is_refused_with_the_named_provider_reason(self) -> None:
        # Given: the custom-pool machine from issue #1998.
        inspection = self.custom_pool_inspection()

        # When/Then: bare `custom` names no endpoint, and the refusal says so.
        for target in ("custom/clv/kimi-k3", "custom/9router/clv/kimi-k3"):
            with self.subTest(target=target):
                with self.assertRaisesRegex(
                    HermesModelConfigError, "bare 'custom'.*'<name>/<model>'"
                ):
                    preview_hermes_model_config(inspection, {"main": target})

        # And: an unknown prefix still refuses as missing provider auth.
        with self.assertRaisesRegex(HermesModelConfigError, "lacks safe observed provider auth"):
            preview_hermes_model_config(inspection, {"main": "clv/kimi-k3"})

    def test_custom_pool_without_configured_provider_does_not_authorize(self) -> None:
        # Given: a `custom:9router` pool left behind with no custom_providers entry.
        inspection = self.custom_pool_inspection(configured=False)

        # When/Then: neither spelling binds, since Hermes would route it nowhere.
        for target in ("9router/clv/kimi-k3", "custom:9router/clv/kimi-k3"):
            with self.subTest(target=target):
                with self.assertRaisesRegex(
                    HermesModelConfigError, "lacks safe observed provider auth"
                ):
                    preview_hermes_model_config(inspection, {"main": target})


    def providers_entry_inspection(self, entry, *, env_extra=None, pools=(), status_ok=True):
        # Issue #2882's machine: the provider is a Hermes `providers:` entry,
        # not a pool and not a legacy `custom_providers` item, and
        # `hermes auth status mistral` exits 0 ("logged out").
        state = self.state()
        state["providers"] = {"mistral": entry}
        self.config.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        env = {
            **self.env,
            "HERMES_AUTH_LIST_EXTRA": json.dumps([f"{pool} (1 credentials):" for pool in pools]),
            "HERMES_AUTH_STATUS_OK": "mistral" if status_ok else "",
            **(env_extra or {}),
        }
        return inspect_hermes_model_config(hermes=str(self.hermes), env=env)

    def test_reported_providers_entry_with_env_key_binds_alias(self) -> None:
        # Given: the reporter's exact shape -- base_url only, MISTRAL_API_KEY
        # exported, no pool, auth status exits 0.
        key = "mistral-key-value-must-not-escape"
        inspection = self.providers_entry_inspection(
            {"name": "Mistral", "base_url": "https://api.mistral.ai/v1"},
            env_extra={"MISTRAL_API_KEY": key},
        )

        # When: the guided preview names the provider.
        preview = preview_hermes_model_config(
            inspection, {"main": "mistral/deepseek-v4-1-flash-1017"}
        )

        # Then: the alias binds, and the key value is nowhere in the result.
        self.assertEqual(
            preview.commands,
            (
                (
                    str(self.hermes),
                    "config",
                    "set",
                    "model.aliases.main",
                    "mistral/deepseek-v4-1-flash-1017",
                ),
            ),
        )
        mistral = {item.provider_id: item for item in inspection.providers}["mistral"]
        self.assertTrue(mistral.auth_present)
        self.assertTrue(mistral.provider_entry)
        self.assertEqual(mistral.credential_env, "MISTRAL_API_KEY")
        self.assertNotIn(key, repr(inspection) + repr(preview))
        logged = (self.home / "commands.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(key, logged)

    def test_providers_entry_declared_key_env_counts_when_present(self) -> None:
        # Given: entries naming their key variable either way Hermes accepts.
        for field in ("key_env", "api_key_env"):
            with self.subTest(field=field):
                inspection = self.providers_entry_inspection(
                    {"base_url": "https://api.mistral.ai/v1", field: "MY_MISTRAL_KEY"},
                    env_extra={"MY_MISTRAL_KEY": "x" * 12},
                )

                # When/Then: the declared variable being set is observed auth.
                preview = preview_hermes_model_config(inspection, {"main": "mistral/large"})
                self.assertEqual(preview.changes, {"main": "mistral/large"})

    def test_providers_entry_pool_counts_without_env(self) -> None:
        # Given: no key variable set, but a pool under the entry's key or its
        # legacy `custom:<name>` id.
        for pool in ("mistral", "custom:mistral"):
            with self.subTest(pool=pool):
                inspection = self.providers_entry_inspection(
                    {"base_url": "https://api.mistral.ai/v1", "key_env": "MY_MISTRAL_KEY"},
                    pools=(pool,),
                )

                # When/Then: the pool is the observed credential.
                preview = preview_hermes_model_config(inspection, {"main": "mistral/large"})
                self.assertEqual(preview.changes, {"main": "mistral/large"})

    def test_providers_entry_binds_under_every_spelling_hermes_resolves(self) -> None:
        # Given: an entry whose display name differs from its key.
        inspection = self.providers_entry_inspection(
            {"name": "Mistral AI", "base_url": "https://api.mistral.ai/v1"},
            env_extra={"MISTRAL_API_KEY": "x" * 12},
        )

        # When: aliases spell it by key, by `custom:` key, and by name.
        preview = preview_hermes_model_config(
            inspection,
            {
                "main": "mistral/large",
                "pool": "custom:mistral/large",
                "named": "mistral-ai/large",
            },
        )

        # Then: all bind, and auth status was asked once, for the entry key.
        self.assertEqual(len(preview.commands), 3)
        statuses = [
            command
            for command in inspection.commands
            if command[1:3] == ("auth", "status")
            and command[3] in {"mistral", "custom:mistral", "mistral-ai", "custom:mistral-ai"}
        ]
        self.assertEqual(statuses, [(str(self.hermes), "auth", "status", "mistral")])

    def test_providers_entry_without_observable_credential_names_the_remedy(self) -> None:
        # Given: the entry's key variable unset, or set but empty, and no pool.
        for env_extra in ({}, {"MY_MISTRAL_KEY": ""}, {"MY_MISTRAL_KEY": "   "}):
            with self.subTest(env=env_extra):
                inspection = self.providers_entry_inspection(
                    {"base_url": "https://api.mistral.ai/v1", "key_env": "MY_MISTRAL_KEY"},
                    env_extra={"MISTRAL_API_KEY": "x" * 12, **env_extra},
                )

                # When/Then: refused, naming the configured route and its remedy.
                with self.assertRaisesRegex(
                    HermesModelConfigError,
                    r"configured under providers: but no credential is observable: "
                    r"set MY_MISTRAL_KEY .*`hermes auth add mistral`",
                ):
                    preview_hermes_model_config(inspection, {"main": "mistral/large"})

    def test_providers_entry_with_unobservable_key_source_stays_refused(self) -> None:
        # Given: an entry whose key comes from a command OMH cannot observe,
        # and one Hermes keeps hidden with `enabled: false`.
        cases = (
            (
                {"base_url": "https://api.mistral.ai/v1", "key_cmd": "pass show mistral"},
                "name the variable holding its key with key_env",
            ),
            (
                {"base_url": "https://api.mistral.ai/v1", "enabled": False},
                "lacks safe observed provider auth",
            ),
            (
                {"base_url": "http://127.0.0.1:8080/v1"},
                "name the variable holding its key with key_env",
            ),
        )
        for entry, reason in cases:
            with self.subTest(entry=entry):
                inspection = self.providers_entry_inspection(
                    entry, env_extra={"MISTRAL_API_KEY": "x" * 12}
                )

                # When/Then: refused.
                with self.assertRaisesRegex(HermesModelConfigError, reason):
                    preview_hermes_model_config(inspection, {"main": "mistral/large"})

    def test_malformed_base_url_is_refused_without_a_traceback(self) -> None:
        # Given: a providers: entry whose base_url urlsplit cannot parse.
        inspection = self.providers_entry_inspection(
            {"base_url": "http://[bad"}, env_extra={"MISTRAL_API_KEY": "x" * 12}
        )

        # When/Then: a clean refusal, not a ValueError out of the inspection.
        with self.assertRaisesRegex(
            HermesModelConfigError, "name the variable holding its key with key_env"
        ):
            preview_hermes_model_config(inspection, {"main": "mistral/large"})

    def test_a_secret_pasted_into_key_env_is_never_echoed(self) -> None:
        # Given: key_env holds an identifier-shaped value that is not an UPPER_SNAKE name.
        pasted = "q7Rk2Lm9Xw4Tz8Vb1Nc6Hd3Fs5Gj0Ya"
        inspection = self.providers_entry_inspection(
            {"base_url": "https://api.mistral.ai/v1", "key_env": pasted},
            env_extra={"MISTRAL_API_KEY": "x" * 12},
        )

        # When: refused.
        with self.assertRaises(HermesModelConfigError) as caught:
            preview_hermes_model_config(inspection, {"main": "mistral/large"})

        # Then: the remedy is generic and the pasted text never appears.
        self.assertNotIn(pasted, str(caught.exception))
        self.assertIn("set the variable its key_env names", str(caught.exception))

    def test_unconfigured_provider_keeps_the_missing_auth_refusal(self) -> None:
        # Given: a providers: entry for mistral, and a target naming another id
        # with no pool, entry, legacy entry, or plugin.
        inspection = self.providers_entry_inspection(
            {"base_url": "https://api.mistral.ai/v1"},
            env_extra={"MISTRAL_API_KEY": "x" * 12, "GAMMA_API_KEY": "x" * 12},
        )

        # When/Then: the old refusal stands.
        with self.assertRaisesRegex(
            HermesModelConfigError, r"^Hermes model target 'gamma/large' lacks safe observed provider auth$"
        ):
            preview_hermes_model_config(inspection, {"main": "gamma/large"})

    def test_providers_entry_with_failed_auth_status_stays_refused(self) -> None:
        # Given: an observable key, but `hermes auth status mistral` exits non-zero.
        inspection = self.providers_entry_inspection(
            {"base_url": "https://api.mistral.ai/v1"},
            env_extra={"MISTRAL_API_KEY": "x" * 12},
            status_ok=False,
        )

        # When/Then: refused as before.
        with self.assertRaisesRegex(HermesModelConfigError, "lacks safe observed provider auth"):
            preview_hermes_model_config(inspection, {"main": "mistral/large"})

    def test_legacy_custom_provider_without_pool_is_unchanged(self) -> None:
        # Given: a legacy custom_providers entry whose key variable is set, but
        # no `custom:<name>` pool.
        state = self.state()
        state["custom_providers"] = [
            {"name": "9router", "base_url": "http://localhost:20128/v1", "key_env": "ROUTER_KEY"}
        ]
        self.config.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        inspection = inspect_hermes_model_config(
            hermes=str(self.hermes),
            env={**self.env, "ROUTER_KEY": "x" * 12, "HERMES_AUTH_STATUS_OK": "9router"},
        )

        # When/Then: still refused with the missing-auth text.
        with self.assertRaisesRegex(HermesModelConfigError, "lacks safe observed provider auth"):
            preview_hermes_model_config(inspection, {"main": "9router/clv/kimi-k3"})

    def test_plugin_provider_without_pool_is_refused_with_its_reason(self) -> None:
        # Given: an enabled plugin provider whose auth status exits 0 but which
        # holds no credential pool.
        state = self.state()
        state["plugins"]["enabled"].append("delta")
        self.config.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        inspection = inspect_hermes_model_config(
            hermes=str(self.hermes), env={**self.env, "HERMES_AUTH_STATUS_OK": "delta"}
        )
        delta = {item.provider_id: item for item in inspection.providers}["delta"]
        self.assertTrue(delta.plugin_present and delta.auth_status_ok)

        # When/Then: refused, saying its sign-in is not observable.
        with self.assertRaisesRegex(
            HermesModelConfigError, r"plugin whose own sign-in OMH cannot observe.*`hermes auth add delta`"
        ):
            preview_hermes_model_config(inspection, {"main": "delta/large"})

    def test_agent_install_guide_names_both_refusals_and_their_remedies(self) -> None:
        # Given: the agent install guide an agent follows on a refused preview.
        guide = " ".join(
            (Path(__file__).resolve().parents[1] / "INSTALL_FOR_AGENTS.md")
            .read_text(encoding="utf-8")
            .split()
        )
        inspection = self.providers_entry_inspection(
            {"base_url": "https://api.mistral.ai/v1", "key_env": "MY_MISTRAL_KEY"}
        )
        with self.assertRaises(HermesModelConfigError) as raised:
            preview_hermes_model_config(inspection, {"main": "mistral/large"})

        # Then: it quotes the text each refusal really carries, with its remedy.
        self.assertIn("is configured under providers: but no credential is observable", str(raised.exception))
        for phrase in (
            "`lacks safe observed provider auth`",
            "`is configured under providers: but no credential is observable`",
            "`key_env`",
            "`hermes auth add <id>`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, guide)

if __name__ == "__main__":
    unittest.main()
