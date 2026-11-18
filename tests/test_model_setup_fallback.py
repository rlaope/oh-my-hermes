"""`omh setup --model-setup --fallback-model PROVIDER/MODEL`: one reviewed fallback chain entry."""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import textwrap
import unittest

from _local_package import load_local_package
from _test_temp_root import make_test_tempdir

load_local_package()

from omh.coding.hermes_model_config import (  # noqa: E402
    ConfigDigestMismatchError,
    ConfirmationRequiredError,
    HermesCommandError,
    HermesModelConfigError,
    HermesVerificationError,
    apply_hermes_model_config,
    effective_fallback_entries,
    inspect_hermes_model_config,
    preview_hermes_model_config,
)
from omh.coding.model_recommendations import resolve_model_recommendation  # noqa: E402
from omh.commands.main import build_parser  # noqa: E402
from omh.commands.model_setup_flow import (  # noqa: E402
    ModelSetupFlowDependencies,
    model_activation_result,
)
from omh.commands.model_setup_inputs import validate_model_setup_args  # noqa: E402
from omh.commands.model_setup_rendering import print_model_preview_review  # noqa: E402
from omh.installer import OmhError  # noqa: E402


# A stand-in `hermes` over a JSON config file: `config get/set/unset`, `config check`,
# `auth list/status`. Like Hermes, `config set` coerces a JSON object or list value, an
# unset `fallback_providers` reads back as Hermes' default `[]`, and any other missing key
# exits 1 with "Config key not set" on stderr. Faults: `HERMES_FAIL_MUTATION=<key>` makes
# the first write to that key exit 9 without writing, `HERMES_FAIL_AFTER_WRITE=<key>`
# writes and then exits 9, `HERMES_FAIL_READ=<key>[:<code>]` makes `config get <key>` exit
# with that code (9 by default), `HERMES_FAIL_READ_AFTER_WRITE=<key>` does so once any
# write ran, and `HERMES_BAD_JSON=<key>` answers that read with exit 0 and no JSON.
_FAKE_HERMES = r"""
#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

home = Path(os.environ["HERMES_HOME"])
state_path = home / "config.yaml"
with (home / "commands.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")
state = json.loads(state_path.read_text(encoding="utf-8"))
args = sys.argv[1:]

def save():
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

def fail_once(key):
    marker = home / "mutation-failed"
    if os.environ.get("HERMES_FAIL_MUTATION") == key and not marker.exists():
        marker.touch()
        raise SystemExit(9)

def read_fault(key):
    spec = os.environ.get("HERMES_FAIL_READ", "")
    name, _, code = spec.partition(":")
    if spec and name == key:
        print("synthetic read failure", file=sys.stderr)
        raise SystemExit(int(code or 9))
    if os.environ.get("HERMES_FAIL_READ_AFTER_WRITE") == key and (home / "written").exists():
        raise SystemExit(9)
    if os.environ.get("HERMES_BAD_JSON") == key:
        print("not json")
        raise SystemExit(0)
    name, _, nth = os.environ.get("HERMES_FAIL_READ_FROM", "").partition(":")
    if name == key:
        counter = home / f"reads-{key}"
        count = int(counter.read_text()) + 1 if counter.exists() else 1
        counter.write_text(str(count))
        if count >= int(nth):
            raise SystemExit(9)

if args == ["config", "path"]:
    print(state_path)
elif args[:2] == ["config", "get"]:
    read_fault(args[2])
    current = state
    for part in args[2].split("."):
        if not isinstance(current, dict) or part not in current:
            if args[2] == "fallback_providers":
                print("[]")
                raise SystemExit(0)
            print(f"Config key not set: {args[2]}", file=sys.stderr)
            raise SystemExit(1)
        current = current[part]
    print(json.dumps(current))
elif args == ["config", "check"]:
    print("Configuration OK")
elif args[:2] == ["auth", "list"]:
    print("alpha (1 credentials):")
elif args[:2] == ["auth", "status"]:
    raise SystemExit(0 if args[2] == "alpha" else 1)
elif args[:2] == ["config", "set"]:
    fail_once(args[2])
    value = args[3]
    if value[:1] in "[{":
        value = json.loads(value)
    current = state
    parts = args[2].split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value
    save()
    (home / "written").touch()
    if os.environ.get("HERMES_FAIL_AFTER_WRITE") == args[2]:
        raise SystemExit(9)
elif args[:2] == ["config", "unset"]:
    fail_once(args[2])
    current = state
    parts = args[2].split(".")
    for part in parts[:-1]:
        current = current[part]
    current.pop(parts[-1], None)
    save()
else:
    raise SystemExit(f"unexpected command: {args}")
"""

_BASE_CONFIG = {
    "model": {"provider": "alpha", "default": "main-1", "aliases": {"fast": "alpha/fast"}},
}
_CHAIN = [
    {"provider": "alpha", "model": "old-1"},
    {"provider": "alpha", "model": "old-2"},
]
_BACKUP = [{"provider": "alpha", "model": "backup"}]
_BACKUP_LITERAL = json.dumps(_BACKUP)
_SET_BACKUP = ["config", "set", "fallback_providers", _BACKUP_LITERAL]


class FallbackModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = make_test_tempdir(prefix="omh-model-setup-fallback-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "hermes-home"
        self.home.mkdir()
        self.hermes = Path(self.temp.name) / "hermes.py"
        self.hermes.write_text(textwrap.dedent(_FAKE_HERMES).lstrip(), encoding="utf-8")
        self.hermes.chmod(0o755)
        self.config = self.home / "config.yaml"
        self.env = {"HERMES_HOME": str(self.home), "PATH": os.environ["PATH"]}
        self.write_config(_BASE_CONFIG)

    def write_config(self, config: dict[str, object]) -> None:
        self.config.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")

    def state(self) -> dict[str, object]:
        return json.loads(self.config.read_text(encoding="utf-8"))

    def writes(self) -> list[list[str]]:
        log = self.home / "commands.jsonl"
        if not log.exists():
            return []
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        return [call for call in calls if call[:2] in (["config", "set"], ["config", "unset"])]

    def inspect(self, env: dict[str, str] | None = None):
        return inspect_hermes_model_config(hermes=str(self.hermes), env=env or self.env)

    def args(self, *extra: str):
        return build_parser().parse_args(["setup", "--model-setup", *extra])

    def approval(self, *preview_args: str) -> str:
        """The `approval_digest` a preview with these arguments shows (what an apply must name)."""
        return model_activation_result(
            self.args(*preview_args), language="en", dependencies=self.dependencies()
        )["preview"]["approval_digest"]

    def dependencies(self, env: dict[str, str] | None = None) -> ModelSetupFlowDependencies:
        run_env = env or self.env

        def unexpected(*_args, **_kwargs):
            raise AssertionError("not used by this flow")

        return ModelSetupFlowDependencies(
            discover_local_models=lambda _home: {
                "schema_version": "model_discovery/v1",
                "sources": {},
                "observations": [],
                "observation_count": 0,
                "claim_boundary": "metadata only",
            },
            inspect_hermes_model_config=lambda: self.inspect(run_env),
            preview_hermes_model_config=preview_hermes_model_config,
            apply_hermes_model_config=lambda preview, **kwargs: apply_hermes_model_config(
                preview, env=run_env, **kwargs
            ),
            resolve_model_recommendation=resolve_model_recommendation,
            ask_yes_no=unexpected,
            ask=unexpected,
            use_color=lambda: False,
            print_model_preview_review=unexpected,
        )

    # -- argument surface -------------------------------------------------

    def test_without_model_setup_the_flag_is_refused(self) -> None:
        args = build_parser().parse_args(["setup", "--fallback-model", "alpha/backup"])
        with self.assertRaisesRegex(OmhError, "require --model-setup"):
            validate_model_setup_args(args)

    def test_a_second_value_is_refused(self) -> None:
        args = self.args("--fallback-model", "alpha/one", "--fallback-model", "alpha/two")
        with self.assertRaisesRegex(OmhError, "Onboarding keeps one fallback model."):
            validate_model_setup_args(args)

    def test_a_value_without_provider_and_model_is_refused(self) -> None:
        for bad in ("backup", "alpha/", "/backup", "alpha/two words"):
            with self.subTest(value=bad), self.assertRaises(OmhError):
                validate_model_setup_args(self.args("--fallback-model", bad))

    def test_apply_with_only_a_fallback_passes_validation(self) -> None:
        validate_model_setup_args(
            self.args("--fallback-model", "alpha/backup", "--apply-model-config")
        )

    # -- preview -----------------------------------------------------------

    def test_preview_shows_the_fallback_before_and_after_in_the_same_payload(self) -> None:
        self.write_config({**_BASE_CONFIG, "fallback_providers": [{"provider": "alpha", "model": "old-1"}]})
        args = self.args("--confirm-model", "alpha/main-1", "--model-alias", "main=alpha/main-1", "--fallback-model", "alpha/backup")

        result = model_activation_result(args, language="en", dependencies=self.dependencies())

        preview = result["preview"]
        self.assertEqual(preview["changes"], {"main": "alpha/main-1"})
        self.assertEqual(
            preview["fallback_model"],
            {"before": ["alpha/old-1"], "before_chain": ["alpha/old-1"], "after": "alpha/backup",
             "replaces_chain": False, "unchanged": False, "legacy": False, "refusal": None},
        )
        self.assertEqual(preview["config_digest"], self.inspect().config_digest)
        self.assertEqual(result["inspection"]["main_model"], "alpha/main-1")
        self.assertEqual(self.writes(), [])
        shown = io.StringIO()
        with redirect_stdout(shown):
            print_model_preview_review(
                preview, language="en", use_color=lambda: False, color=lambda text, _c, _u: text
            )
        self.assertIn("fallback chain: alpha/old-1 -> alpha/backup", shown.getvalue())

    def test_a_fallback_only_run_previews_without_a_main_alias(self) -> None:
        result = model_activation_result(
            self.args("--fallback-model", "alpha/backup"),
            language="en",
            dependencies=self.dependencies(),
        )

        self.assertEqual(result["status"], "preview_ready")
        self.assertEqual(result["preview"]["changes"], {})
        self.assertEqual(result["preview"]["fallback_model"]["before"], [])
        self.assertEqual(
            [command[1:] for command in result["preview"]["commands"]],
            [["config", "set", "fallback_providers", _BACKUP_LITERAL]],
        )
        self.assertEqual(self.writes(), [])

    def test_a_run_without_the_flag_keeps_the_payload_key_empty(self) -> None:
        result = model_activation_result(
            self.args("--confirm-model", "alpha/main-1", "--model-alias", "main=alpha/main-1"),
            language="en",
            dependencies=self.dependencies(),
        )

        self.assertIsNone(result["preview"]["fallback_model"])
        self.assertEqual(result["preview"]["changes"], {"main": "alpha/main-1"})

    def test_provider_without_auth_is_refused_with_the_alias_remedy_text(self) -> None:
        inspection = self.inspect()
        with self.assertRaises(HermesModelConfigError) as fallback_error:
            preview_hermes_model_config(inspection, {}, fallback="beta/backup")
        with self.assertRaises(HermesModelConfigError) as alias_error:
            preview_hermes_model_config(inspection, {"x": "beta/backup"})

        self.assertEqual(str(fallback_error.exception), str(alias_error.exception))
        self.assertIn("lacks safe observed provider auth", str(fallback_error.exception))

    def test_fallback_equal_to_the_main_model_is_refused(self) -> None:
        with self.assertRaisesRegex(HermesModelConfigError, "fallback is the same as the main model"):
            preview_hermes_model_config(self.inspect(), {}, fallback="alpha/main-1")

    def test_fallback_equal_to_the_main_alias_in_the_same_run_is_refused(self) -> None:
        with self.assertRaisesRegex(HermesModelConfigError, "fallback is the same as the main model"):
            preview_hermes_model_config(
                self.inspect(), {"main": "alpha/new-main"}, fallback="alpha/new-main"
            )

    def test_a_chain_is_previewed_as_replaced_by_one_entry(self) -> None:
        self.write_config({**_BASE_CONFIG, "fallback_providers": _CHAIN})

        result = model_activation_result(
            self.args("--fallback-model", "alpha/backup"),
            language="en",
            dependencies=self.dependencies(),
        )

        fallback = result["preview"]["fallback_model"]
        self.assertTrue(fallback["replaces_chain"])
        self.assertEqual(fallback["before"], ["alpha/old-1", "alpha/old-2"])
        shown = io.StringIO()
        with redirect_stdout(shown):
            print_model_preview_review(
                result["preview"],
                language="en",
                use_color=lambda: False,
                color=lambda text, _c, _u: text,
            )
        self.assertIn("chain is replaced by this one entry", shown.getvalue())
        self.assertEqual(self.state()["fallback_providers"], _CHAIN)
        self.assertEqual(self.writes(), [])

    # -- apply -------------------------------------------------------------

    def test_apply_writes_one_fallback_providers_list(self) -> None:
        args = self.args(
            "--fallback-model", "alpha/backup", "--apply-model-config", "--model-config-digest",
            self.approval("--fallback-model", "alpha/backup"),
        )

        result = model_activation_result(args, language="en", dependencies=self.dependencies())

        self.assertEqual(result["status"], "verified")
        self.assertEqual(self.state()["fallback_providers"], _BACKUP)
        self.assertNotIn("fallback_model", self.state())
        self.assertEqual(self.writes(), [["config", "set", "fallback_providers", _BACKUP_LITERAL]])
        self.assertEqual(self.state()["model"], _BASE_CONFIG["model"])

    def test_apply_writes_the_alias_and_the_fallback_under_one_digest(self) -> None:
        digest = self.approval(
            "--confirm-model", "alpha/main-1", "--model-alias", "main=alpha/main-1", "--fallback-model", "alpha/backup",
        )
        args = self.args(
            "--confirm-model", "alpha/main-1", "--model-alias", "main=alpha/main-1", "--fallback-model", "alpha/backup",
            "--apply-model-config", "--model-config-digest", digest,
        )

        result = model_activation_result(args, language="en", dependencies=self.dependencies())

        self.assertEqual(result["status"], "verified")
        state = self.state()
        self.assertEqual(state["model"]["aliases"]["main"], "alpha/main-1")
        self.assertEqual(state["fallback_providers"], _BACKUP)

    def test_apply_with_a_stale_digest_writes_nothing(self) -> None:
        args = self.args(
            "--fallback-model", "alpha/backup", "--apply-model-config", "--model-config-digest", "stale",
        )

        with self.assertRaisesRegex(OmhError, "digest"):
            model_activation_result(args, language="en", dependencies=self.dependencies())

        self.assertEqual(self.writes(), [])
        self.assertNotIn("fallback_providers", self.state())

    def test_a_preview_of_one_fallback_never_applies_another(self) -> None:
        # The reviewer's repro: preview fb-1, then apply fb-2 with fb-1's digest on an unchanged file.
        digest = self.approval("--fallback-model", "alpha/fb-1")
        args = self.args("--fallback-model", "alpha/fb-2", "--apply-model-config", "--model-config-digest", digest)

        with self.assertRaisesRegex(OmhError, "does not match the preview digest"):
            model_activation_result(args, language="en", dependencies=self.dependencies())

        self.assertEqual(self.writes(), [])
        self.assertNotIn("fallback_providers", self.state())

    def test_a_preview_of_one_alias_never_applies_another(self) -> None:
        digest = self.approval("--confirm-model", "alpha/main-1", "--model-alias", "main=alpha/main-1")
        args = self.args(
            "--confirm-model", "alpha/main-2", "--model-alias", "main=alpha/main-2",
            "--apply-model-config", "--model-config-digest", digest,
        )

        with self.assertRaisesRegex(OmhError, "does not match the preview digest"):
            model_activation_result(args, language="en", dependencies=self.dependencies())

        self.assertEqual(self.writes(), [])

    def test_the_bare_config_digest_no_longer_approves_a_change(self) -> None:
        args = self.args(
            "--fallback-model", "alpha/backup", "--apply-model-config", "--model-config-digest",
            self.inspect().config_digest,
        )

        with self.assertRaisesRegex(OmhError, "does not match the preview digest"):
            model_activation_result(args, language="en", dependencies=self.dependencies())

        self.assertEqual(self.writes(), [])

    def test_the_approval_digest_names_the_file_and_the_change(self) -> None:
        inspection = self.inspect()
        one = preview_hermes_model_config(inspection, {}, fallback="alpha/fb-1")
        other = preview_hermes_model_config(inspection, {}, fallback="alpha/fb-2")
        again = preview_hermes_model_config(self.inspect(), {}, fallback="alpha/fb-1")

        self.assertEqual(one.config_digest, other.config_digest)
        self.assertNotEqual(one.approval_digest, other.approval_digest)
        self.assertEqual(one.approval_digest, again.approval_digest)
        self.write_config({**_BASE_CONFIG, "plugins": {"enabled": []}})
        moved = preview_hermes_model_config(self.inspect(), {}, fallback="alpha/fb-1")
        self.assertNotEqual(one.approval_digest, moved.approval_digest)

    def test_apply_refuses_when_the_config_drifted_after_the_preview(self) -> None:
        inspection = self.inspect()
        preview = preview_hermes_model_config(inspection, {}, fallback="alpha/backup")
        self.write_config({**_BASE_CONFIG, "plugins": {"enabled": []}})

        with self.assertRaises(ConfigDigestMismatchError):
            apply_hermes_model_config(
                preview, confirmed=True, expected_config_digest=inspection.config_digest, env=self.env
            )

        self.assertEqual(self.writes(), [])

    def test_a_chain_is_replaced_only_after_explicit_approval(self) -> None:
        self.write_config({**_BASE_CONFIG, "fallback_providers": _CHAIN})
        inspection = self.inspect()
        preview = preview_hermes_model_config(inspection, {}, fallback="alpha/backup")

        with self.assertRaises(ConfirmationRequiredError):
            apply_hermes_model_config(
                preview, confirmed=False, expected_config_digest=inspection.config_digest, env=self.env
            )
        self.assertEqual(self.state()["fallback_providers"], _CHAIN)
        self.assertEqual(self.writes(), [])

        apply_hermes_model_config(
            preview, confirmed=True, expected_config_digest=inspection.config_digest, env=self.env
        )
        self.assertEqual(self.state()["fallback_providers"], _BACKUP)
        self.assertEqual(self.writes(), [_SET_BACKUP])

    def test_the_same_fallback_already_set_writes_nothing(self) -> None:
        self.write_config({**_BASE_CONFIG, "fallback_providers": _BACKUP})
        preview = preview_hermes_model_config(self.inspect(), {}, fallback="alpha/backup")

        self.assertEqual(preview.commands, ())
        self.assertFalse(preview.fallback_replaces_chain)
        self.assertIsNone(preview.fallback_refusal)

    # -- Hermes' current chain: fallback_providers --------------------------

    def test_existing_fallback_providers_are_previewed_and_replaced_by_one_entry(self) -> None:
        self.write_config({**_BASE_CONFIG, "fallback_providers": _CHAIN})
        digest = self.approval("--fallback-model", "alpha/backup")

        preview = model_activation_result(
            self.args("--fallback-model", "alpha/backup"), language="en", dependencies=self.dependencies()
        )["preview"]["fallback_model"]
        result = model_activation_result(
            self.args("--fallback-model", "alpha/backup", "--apply-model-config", "--model-config-digest", digest),
            language="en",
            dependencies=self.dependencies(),
        )

        self.assertEqual(preview["before"], ["alpha/old-1", "alpha/old-2"])
        self.assertTrue(preview["replaces_chain"])
        self.assertEqual(result["status"], "verified")
        state = self.state()
        self.assertEqual(state["fallback_providers"], _BACKUP)
        self.assertNotIn("fallback_model", state)
        self.assertEqual(self.writes(), [_SET_BACKUP])
        inspection = self.inspect()
        self.assertEqual(
            effective_fallback_entries(inspection.fallback_providers, inspection.fallback_model),
            ("alpha/backup",),
        )

    def test_before_is_the_effective_chain_in_hermes_order(self) -> None:
        self.write_config({
            **_BASE_CONFIG,
            "fallback_providers": [_CHAIN[1]],
            "fallback_model": [_CHAIN[1], _CHAIN[0]],
        })

        preview = preview_hermes_model_config(self.inspect(), {}, fallback="alpha/backup")

        self.assertEqual(preview.before_fallback_chain, ("alpha/old-2", "alpha/old-1"))
        self.assertTrue(preview.fallback_is_legacy)

    # -- legacy fallback_model: shown, never written -------------------------

    def test_a_legacy_fallback_model_is_previewed_and_its_apply_refused_with_no_write(self) -> None:
        for extra in (
            {"fallback_model": {"provider": "alpha", "model": "old-1"}},
            {"fallback_model": _CHAIN},
            {"fallback_providers": _CHAIN, "fallback_model": {"provider": "alpha", "model": "old-3"}},
            {"fallback_model": {"provider": "alpha", "model": "old-1", "api_key": "synthetic-canary"}},
        ):
            with self.subTest(keys=sorted(extra)):
                self.write_config({**_BASE_CONFIG, **extra})
                before = self.state()
                digest = self.inspect().config_digest
                preview = model_activation_result(
                    self.args("--fallback-model", "alpha/backup"), language="en", dependencies=self.dependencies()
                )["preview"]
                for mode in ((), ("--dry-run",)):
                    args = self.args(
                        "--fallback-model", "alpha/backup", "--apply-model-config", "--model-config-digest", digest,
                        *mode,
                    )
                    with self.assertRaises(OmhError) as raised:
                        model_activation_result(args, language="en", dependencies=self.dependencies())
                    self.assertIn("hermes fallback clear", str(raised.exception))
                    self.assertNotIn("synthetic-canary", str(raised.exception))

                self.assertTrue(preview["fallback_model"]["legacy"])
                self.assertIn("older `fallback_model` setting", preview["fallback_model"]["refusal"])
                self.assertEqual(preview["commands"], [])
                shown = io.StringIO()
                with redirect_stdout(shown):
                    print_model_preview_review(
                        preview, language="en", use_color=lambda: False, color=lambda text, _c, _u: text
                    )
                self.assertIn("Apply is refused", shown.getvalue())
                self.assertEqual(self.writes(), [])
                self.assertEqual(self.state(), before)

    def test_the_library_apply_refuses_a_legacy_preview_before_any_write(self) -> None:
        self.write_config({**_BASE_CONFIG, "fallback_model": {"provider": "alpha", "model": "old-1"}})
        inspection = self.inspect()
        preview = preview_hermes_model_config(inspection, {"main": "alpha/main-1"}, fallback="alpha/backup")

        with self.assertRaisesRegex(HermesModelConfigError, "hermes fallback clear"):
            apply_hermes_model_config(
                preview, confirmed=True, expected_config_digest=inspection.config_digest, env=self.env
            )

        self.assertEqual(self.writes(), [])

    # -- strict reads ------------------------------------------------------

    def test_a_failed_fallback_read_refuses_before_any_write(self) -> None:
        self.write_config({
            **_BASE_CONFIG,
            "fallback_providers": [_CHAIN[0]],
            "fallback_model": {"provider": "alpha", "model": "old-3"},
        })
        before = self.state()
        digest = self.inspect().config_digest
        for fault in (
            {"HERMES_FAIL_READ": "fallback_model"},
            {"HERMES_FAIL_READ": "fallback_providers"},
            {"HERMES_FAIL_READ": "fallback_model:1"},
            {"HERMES_BAD_JSON": "fallback_providers"},
        ):
            with self.subTest(fault=fault):
                env = {**self.env, **fault}
                args = self.args(
                    "--fallback-model", "alpha/backup", "--apply-model-config", "--model-config-digest", digest,
                )

                with self.assertRaises(OmhError) as raised:
                    model_activation_result(args, language="en", dependencies=self.dependencies(env))

                message = str(raised.exception)
                self.assertIn("could not read your current fallback settings", message)
                self.assertIn("nothing was changed", message)
                self.assertNotIn("synthetic read failure", message)
                self.assertEqual(self.writes(), [])
                self.assertEqual(self.state(), before)

    def test_config_key_not_set_reads_as_absent(self) -> None:
        inspection = self.inspect()

        self.assertIsNone(inspection.fallback_model)
        self.assertIsNone(inspection.fallback_read_error)
        preview = preview_hermes_model_config(inspection, {}, fallback="alpha/backup")
        self.assertEqual(preview.fallback_commands[0][1:], tuple(_SET_BACKUP))

    def test_an_entry_with_a_credential_field_is_refused_before_any_write(self) -> None:
        for key, value in (
            ("fallback_providers", [{"provider": "alpha", "model": "old-1", "api_key": "synthetic-canary"}]),
            ("fallback_providers", [{"provider": "alpha", "model": "old-1", "extra_headers": {"x": "y"}}]),
        ):
            with self.subTest(key=key, fields=sorted(value if isinstance(value, dict) else value[0])):
                self.write_config({**_BASE_CONFIG, key: value})
                digest = self.inspect().config_digest
                args = self.args(
                    "--fallback-model", "alpha/backup", "--apply-model-config", "--model-config-digest", digest,
                )

                with self.assertRaises(OmhError) as raised:
                    model_activation_result(args, language="en", dependencies=self.dependencies())

                self.assertIn("fields OMH cannot restore safely", str(raised.exception))
                self.assertIn("hermes fallback", str(raised.exception))
                self.assertNotIn("synthetic-canary", str(raised.exception))
                self.assertEqual(self.writes(), [])
                self.assertEqual(self.state()[key], value)

    def test_restorable_fields_do_not_block_the_replacement(self) -> None:
        entry = {"provider": "alpha", "model": "old-1", "base_url": "https://example.test/v1",
                 "api_mode": "chat_completions"}
        self.write_config({**_BASE_CONFIG, "fallback_providers": [entry]})

        preview = preview_hermes_model_config(self.inspect(), {}, fallback="alpha/backup")

        self.assertEqual(preview.fallback_commands[0][1:], ("config", "set", "fallback_providers", _BACKUP_LITERAL))

    # -- one write, no replay ------------------------------------------------

    def _apply_with(self, fault: dict[str, str], config: dict[str, object] | None = None):
        self.write_config(config or {**_BASE_CONFIG, "fallback_providers": _CHAIN})
        inspection = self.inspect()
        preview = preview_hermes_model_config(inspection, {}, fallback="alpha/backup")
        apply_hermes_model_config(
            preview,
            confirmed=True,
            expected_config_digest=inspection.config_digest,
            env={**self.env, **fault},
        )

    def test_a_refused_write_that_left_the_file_alone_says_nothing_changed(self) -> None:
        for config in (None, _BASE_CONFIG):
            with self.subTest(existing=config is None):
                self.write_config(config or {**_BASE_CONFIG, "fallback_providers": _CHAIN})
                before = self.state()
                (self.home / "mutation-failed").unlink(missing_ok=True)
                log = self.home / "commands.jsonl"
                log.unlink(missing_ok=True)

                with self.assertRaisesRegex(HermesCommandError, "nothing was changed") as raised:
                    self._apply_with({"HERMES_FAIL_MUTATION": "fallback_providers"}, config)

                self.assertIn("exit 9", str(raised.exception))
                self.assertEqual(self.writes(), [_SET_BACKUP])
                self.assertEqual(self.state(), before)

    def test_a_failed_write_that_changed_the_file_points_to_hermes_fallback_list(self) -> None:
        with self.assertRaises(HermesVerificationError) as raised:
            self._apply_with({"HERMES_FAIL_AFTER_WRITE": "fallback_providers"})

        self.assertIn("config file changed", str(raised.exception))
        self.assertIn("hermes fallback list", str(raised.exception))
        self.assertEqual(self.writes(), [_SET_BACKUP])

    def test_a_failed_read_after_the_write_is_a_verification_error_with_no_more_writes(self) -> None:
        for key in ("fallback_providers", "fallback_model"):
            with self.subTest(key=key):
                for marker in ("written", "commands.jsonl"):
                    (self.home / marker).unlink(missing_ok=True)

                with self.assertRaises(HermesVerificationError) as raised:
                    self._apply_with({"HERMES_FAIL_READ_AFTER_WRITE": key})

                self.assertIn("OMH made one write", str(raised.exception))
                self.assertIn("hermes fallback list", str(raised.exception))
                self.assertEqual(self.writes(), [_SET_BACKUP])

    def test_a_failed_read_on_a_no_op_apply_never_claims_a_write(self) -> None:
        # The chain already is the approved entry, so the apply writes nothing; its read-back then fails.
        self.write_config({**_BASE_CONFIG, "fallback_providers": [{"provider": "alpha", "model": "backup"}]})
        inspection = self.inspect()
        preview = preview_hermes_model_config(inspection, {}, fallback="alpha/backup")
        self.assertEqual(preview.fallback_commands, ())

        with self.assertRaises(HermesVerificationError) as raised:
            apply_hermes_model_config(
                preview,
                confirmed=True,
                expected_config_digest=inspection.config_digest,
                env={**self.env, "HERMES_FAIL_READ": "fallback_providers"},
            )

        self.assertIn("OMH wrote no fallback", str(raised.exception))
        self.assertNotIn("OMH made one write", str(raised.exception))
        self.assertEqual(self.writes(), [])

    def test_a_late_read_failure_still_rolls_back_the_alias(self) -> None:
        # Reads of fallback_model: 1 preview, 2 the write's own check, 3 the receipt inspection.
        inspection = self.inspect()
        preview = preview_hermes_model_config(
            inspection, {"main": "alpha/main-1"}, fallback="alpha/backup"
        )
        (self.home / "reads-fallback_model").write_text("1")

        with self.assertRaises(HermesVerificationError) as raised:
            apply_hermes_model_config(
                preview,
                confirmed=True,
                expected_config_digest=inspection.config_digest,
                env={**self.env, "HERMES_FAIL_READ_FROM": "fallback_model:3"},
            )

        self.assertIn("OMH made one write", str(raised.exception))
        self.assertNotIn("main", self.state()["model"]["aliases"])
        self.assertEqual(self.state()["fallback_providers"], _BACKUP)

    def test_a_failed_fallback_write_also_restores_the_alias_written_before_it(self) -> None:
        inspection = self.inspect()
        preview = preview_hermes_model_config(
            inspection, {"main": "alpha/main-1"}, fallback="alpha/backup"
        )

        with self.assertRaisesRegex(HermesCommandError, "nothing was changed"):
            apply_hermes_model_config(
                preview,
                confirmed=True,
                expected_config_digest=inspection.config_digest,
                env={**self.env, "HERMES_FAIL_MUTATION": "fallback_providers"},
            )

        state = self.state()
        self.assertNotIn("main", state["model"]["aliases"])
        self.assertNotIn("fallback_providers", state)

    def test_a_fallback_changed_by_someone_else_mid_apply_is_not_overwritten(self) -> None:
        self.write_config({**_BASE_CONFIG, "fallback_providers": [{"provider": "alpha", "model": "old-1"}]})
        inspection = self.inspect()
        preview = preview_hermes_model_config(inspection, {}, fallback="alpha/backup")
        # Another writer lands a different entry after our preview, before the apply writes.
        racing = {**self.state(), "fallback_providers": [{"provider": "alpha", "model": "theirs"}]}
        self.write_config(racing)

        with self.assertRaises(ConfigDigestMismatchError):
            apply_hermes_model_config(
                preview, confirmed=True, expected_config_digest=inspection.config_digest, env=self.env
            )

        self.assertEqual(self.state()["fallback_providers"], [{"provider": "alpha", "model": "theirs"}])
        self.assertEqual(self.writes(), [])


if __name__ == "__main__":
    unittest.main()
