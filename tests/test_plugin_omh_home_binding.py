"""`omh setup --omh-home X` binds the plugin loaded in the Hermes home to X (#1960).

The plugin resolves its store from its home's
`plugins.entries.omh.settings.omh_home`, then the Hermes process's `OMH_HOME`,
then `~/.omh`. Setup wrote none of the first, so an install at any other store
had a plugin reading `~/.omh` unless Hermes was started with `OMH_HOME`
exported. Every test here runs with `HOME` and `USERPROFILE` pointed at the
temporary root and `OMH_HOME` unset, so `~/.omh` is a directory the test owns.
Windows resolves `~` from `USERPROFILE` and ignores `HOME`, so patching
`HOME` alone left `~/.omh` on the runner's real profile there.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import patch

from _cli_harness import run_cli
from _module_patch import patch_modules
from omh.config_adapter import ensure_plugin_omh_home, plugin_omh_home_setting, remove_plugin_omh_home
from omh.plugin_bundle.omh import runtime_paths


class _IsolatedHome(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        environ = patch.dict(os.environ, {"HOME": str(self.root), "USERPROFILE": str(self.root)})
        environ.start()
        self.addCleanup(environ.stop)
        os.environ.pop("OMH_HOME", None)
        os.environ.pop("HERMES_HOME", None)
        self.hermes_home = self.root / "hermes"
        self.config_path = self.hermes_home / "config.yaml"

    def setup_at(self, omh_home: Path, *extra: str) -> dict:
        status, stdout, stderr = run_cli(
            ["--omh-home", str(omh_home), "--hermes-home", str(self.hermes_home), "setup", "--json", *extra],
            output_json=False,
        )
        self.assertEqual(status, 0, stderr)
        return json.loads(stdout)

    def plugin_binds(self) -> Path:
        """The store the plugin's own resolver picks for this Hermes home."""
        return runtime_paths.resolve_homes(hermes_home=self.hermes_home)[0]

    def config(self) -> str:
        return self.config_path.read_text(encoding="utf-8")


class SetupBindsPluginHomeTests(_IsolatedHome):
    def test_a_non_default_store_is_recorded_and_the_plugin_binds_it(self) -> None:
        store = self.root / "isolated-omh"

        self.setup_at(store)

        self.assertEqual(plugin_omh_home_setting(self.config()), store.as_posix())
        self.assertEqual(self.plugin_binds(), store)

    def test_the_default_store_is_recorded_too(self) -> None:
        # A single-profile process reaches `~/.omh` with nothing named, but a
        # multiplexed one (a gateway serving several profiles, Desktop
        # `serve`) refuses a profile that names no store, so the default
        # store is named like any other (#2037).
        default = self.root / ".omh"
        self.assertEqual(runtime_paths.unset_launch_omh_home(self.hermes_home), default)

        self.setup_at(default)

        self.assertEqual(plugin_omh_home_setting(self.config()), default.as_posix())
        self.assertEqual(self.plugin_binds(), default)

    def test_update_records_the_default_store_on_an_install_made_before_it(self) -> None:
        default = self.root / ".omh"
        self.setup_at(default)
        # A default install from before #2037: registered, and no setting.
        before = remove_plugin_omh_home(self.config(), default.as_posix())
        self.assertTrue(before.changed, before.message)
        self.config_path.write_text(before.text, encoding="utf-8")

        status, _stdout, stderr = run_cli(
            ["--omh-home", str(default), "--hermes-home", str(self.hermes_home), "update", "--json"],
            output_json=False,
        )

        self.assertEqual(status, 0, stderr)
        self.assertEqual(plugin_omh_home_setting(self.config()), default.as_posix())

    def test_a_setting_already_in_the_config_is_never_replaced(self) -> None:
        self.hermes_home.mkdir(parents=True)
        chosen = self.root / "chosen-store"
        self.config_path.write_text(
            f"plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: {chosen.as_posix()}\n",
            encoding="utf-8",
        )

        self.setup_at(self.root / "isolated-omh")

        self.assertEqual(plugin_omh_home_setting(self.config()), chosen.as_posix())

    def test_update_records_the_setting_on_an_install_made_before_it(self) -> None:
        store = self.root / "isolated-omh"
        self.setup_at(store)
        # An install from before #1960: registered, and no setting.
        before = remove_plugin_omh_home(self.config(), store.as_posix())
        self.assertTrue(before.changed, before.message)
        self.config_path.write_text(before.text, encoding="utf-8")
        self.assertEqual(self.plugin_binds(), self.root / ".omh")

        status, _stdout, stderr = run_cli(
            ["--omh-home", str(store), "--hermes-home", str(self.hermes_home), "update", "--json"],
            output_json=False,
        )

        self.assertEqual(status, 0, stderr)
        self.assertEqual(self.plugin_binds(), store)

    def test_uninstall_takes_back_the_setting_it_recorded(self) -> None:
        store = self.root / "isolated-omh"
        self.hermes_home.mkdir(parents=True)
        self.config_path.write_text("version: 1\n", encoding="utf-8")
        self.setup_at(store, "--with-plugin", "--yes")
        self.assertEqual(plugin_omh_home_setting(self.config()), store.as_posix())

        status, stdout, stderr = run_cli(
            ["--omh-home", str(store), "--hermes-home", str(self.hermes_home), "uninstall"],
        )

        self.assertEqual(status, 0, stderr)
        rows = {row["key"]: row["status"] for row in json.loads(stdout)["config_keys"]}
        self.assertEqual(rows["plugins.entries.omh.settings.omh_home"], "reversed")
        self.assertEqual(self.config(), "version: 1\n")

    def test_uninstall_keeps_a_setting_it_did_not_write(self) -> None:
        store = self.root / "isolated-omh"
        self.hermes_home.mkdir(parents=True)
        self.config_path.write_text(
            f"plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: {store.as_posix()}\n",
            encoding="utf-8",
        )
        self.setup_at(store, "--with-plugin", "--yes")

        status, stdout, stderr = run_cli(
            ["--omh-home", str(store), "--hermes-home", str(self.hermes_home), "uninstall"],
        )

        self.assertEqual(status, 0, stderr)
        rows = {row["key"]: row["status"] for row in json.loads(stdout)["config_keys"]}
        self.assertEqual(rows["plugins.entries.omh.settings.omh_home"], "unrecorded")
        self.assertEqual(plugin_omh_home_setting(self.config()), store.as_posix())


class ProfileStoreChoiceTests(_IsolatedHome):
    """A bot profile's store is its own choice (#1679); one with none binds the primary's (#1967).

    A profile's managed skills, widget and skin come from the primary's
    store, so a profile that names no store through its `settings.omh_home`
    or its `.env` `OMH_HOME` is given the primary's -- otherwise its plugin
    binds `~/.omh` whenever the primary's store is anywhere else.
    """

    def profile(self, name: str, config: str = "", env: str = "") -> Path:
        home = self.hermes_home / "profiles" / name
        home.mkdir(parents=True)
        # A real named profile has host identity; an empty shell is ignored.
        (home / "SOUL.md").write_text("Profile identity\n", encoding="utf-8")
        if config:
            (home / "config.yaml").write_text(config, encoding="utf-8")
        if env:
            (home / ".env").write_text(env, encoding="utf-8")
        return home

    @staticmethod
    def profile_config(home: Path) -> str:
        return (home / "config.yaml").read_text(encoding="utf-8")

    def test_a_profile_with_no_store_binds_the_non_default_primary(self) -> None:
        bare = self.profile("bare")
        store = self.root / "isolated-omh"

        self.setup_at(store)

        self.assertEqual(plugin_omh_home_setting(self.profile_config(bare)), store.as_posix())
        self.assertEqual(runtime_paths.resolve_homes(hermes_home=bare)[0], store)

    def test_a_profile_setting_is_kept(self) -> None:
        profile_store = self.root / "bot-store"
        own = self.profile(
            "own", f"plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: {profile_store.as_posix()}\n"
        )

        self.setup_at(self.root / "isolated-omh")

        own_after = self.profile_config(own)
        self.assertEqual(plugin_omh_home_setting(own_after), profile_store.as_posix())
        self.assertEqual(own_after.count("omh_home"), 1)
        self.assertIn("omh", own_after.split("enabled:", 1)[-1])

    def test_a_profile_with_an_env_omh_home_is_given_no_setting(self) -> None:
        # The written setting would outrank the profile's `.env` choice.
        plain = self.profile("plain", env="OMH_HOME=/stores/bot\n")
        exported = self.profile("exported", env="# bot store\nexport OMH_HOME=/stores/bot\n")

        self.setup_at(self.root / "isolated-omh")

        self.assertNotIn("omh_home", self.profile_config(plain))
        self.assertNotIn("omh_home", self.profile_config(exported))

    def test_a_profile_with_an_empty_env_omh_home_is_given_the_setting(self) -> None:
        # `OMH_HOME=` names no store, and the plugin refuses a blank path.
        empty = self.profile("empty", env="OMH_HOME=\n")
        store = self.root / "isolated-omh"

        self.setup_at(store)

        self.assertEqual(plugin_omh_home_setting(self.profile_config(empty)), store.as_posix())

    def test_a_default_primary_names_its_store_in_a_profile_with_none(self) -> None:
        # Before #2037 nothing was written here, and every multiplexed
        # process refused to load the plugin for this profile.
        bare = self.profile("bare", "version: 1\n")
        default = self.root / ".omh"

        self.setup_at(default)

        self.assertEqual(plugin_omh_home_setting(self.profile_config(bare)), default.as_posix())

    def test_update_records_the_default_store_on_a_profile_synced_before_it(self) -> None:
        bare = self.profile("bare")
        default = self.root / ".omh"
        self.setup_at(default)
        before = remove_plugin_omh_home(self.profile_config(bare), default.as_posix())
        self.assertTrue(before.changed, before.message)
        (bare / "config.yaml").write_text(before.text, encoding="utf-8")

        self.update_at(default)

        self.assertEqual(plugin_omh_home_setting(self.profile_config(bare)), default.as_posix())

    def test_update_records_the_setting_on_a_profile_synced_before_it(self) -> None:
        bare = self.profile("bare")
        store = self.root / "isolated-omh"
        self.setup_at(store)
        # A profile synced before #1967: registered, and no setting.
        before = remove_plugin_omh_home(self.profile_config(bare), store.as_posix())
        self.assertTrue(before.changed, before.message)
        (bare / "config.yaml").write_text(before.text, encoding="utf-8")
        self.assertEqual(runtime_paths.resolve_homes(hermes_home=bare)[0], self.root / ".omh")

        status, _stdout, stderr = run_cli(
            ["--omh-home", str(store), "--hermes-home", str(self.hermes_home), "update", "--json"],
            output_json=False,
        )

        self.assertEqual(status, 0, stderr)
        self.assertEqual(runtime_paths.resolve_homes(hermes_home=bare)[0], store)

    def test_uninstall_takes_back_only_the_profile_setting_it_wrote(self) -> None:
        bare = self.profile("bare", "version: 1\n")
        profile_store = self.root / "bot-store"
        own_setting = f"plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: {profile_store.as_posix()}\n"
        own = self.profile("own", own_setting)
        store = self.root / "isolated-omh"
        self.hermes_home.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text("version: 1\n", encoding="utf-8")
        self.setup_at(store, "--with-plugin", "--yes")
        self.assertEqual(plugin_omh_home_setting(self.profile_config(bare)), store.as_posix())

        status, stdout, stderr = run_cli(
            ["--omh-home", str(store), "--hermes-home", str(self.hermes_home), "uninstall"],
        )

        self.assertEqual(status, 0, stderr)
        rows = {
            entry["profile"]: {row["key"]: row["status"] for row in entry.get("config_keys", [])}
            for entry in json.loads(stdout)["hermes_profiles"]
        }
        self.assertEqual(rows["bare"]["plugins.entries.omh.settings.omh_home"], "reversed")
        self.assertEqual(rows["own"]["plugins.entries.omh.settings.omh_home"], "unrecorded")
        self.assertEqual(self.profile_config(bare), "version: 1\n")
        self.assertEqual(plugin_omh_home_setting(self.profile_config(own)), profile_store.as_posix())


    def update_at(self, store: Path) -> None:
        status, _stdout, stderr = run_cli(
            ["--omh-home", str(store), "--hermes-home", str(self.hermes_home), "update", "--json"],
            output_json=False,
        )
        self.assertEqual(status, 0, stderr)

    def test_update_takes_back_its_setting_once_the_profile_env_names_a_store(self) -> None:
        # #1973: the `.env` choice came after OMH's write, and the setting
        # outranks it in the plugin's resolver until it goes.
        bare = self.profile("bare", "version: 1\n")
        store = self.root / "isolated-omh"
        self.setup_at(store)
        self.assertEqual(plugin_omh_home_setting(self.profile_config(bare)), store.as_posix())
        (bare / ".env").write_text("OMH_HOME=/stores/bot\n", encoding="utf-8")

        self.update_at(store)

        self.assertNotIn("omh_home", self.profile_config(bare))
        self.assertNotIn("entries:", self.profile_config(bare))

    def test_a_setting_written_back_after_the_reclaim_is_the_persons(self) -> None:
        # The reclaim clears OMH's record, so the same value written again
        # by hand is no longer OMH's to take.
        bare = self.profile("bare")
        store = self.root / "isolated-omh"
        self.setup_at(store)
        (bare / ".env").write_text("OMH_HOME=/stores/bot\n", encoding="utf-8")
        self.update_at(store)
        restored = ensure_plugin_omh_home(self.profile_config(bare), store)
        self.assertTrue(restored.changed, restored.message)
        (bare / "config.yaml").write_text(restored.text, encoding="utf-8")

        self.update_at(store)

        self.assertEqual(plugin_omh_home_setting(self.profile_config(bare)), store.as_posix())

    def test_setup_reports_the_reclaim_in_the_profile_row(self) -> None:
        bare = self.profile("bare")
        store = self.root / "isolated-omh"
        first = self.setup_at(store)
        self.assertNotIn("omh_home_reclaimed", first["hermes_profiles"][0])
        (bare / ".env").write_text("OMH_HOME=/stores/bot\n", encoding="utf-8")

        payload = self.setup_at(store)

        rows = {row["profile"]: row for row in payload["hermes_profiles"]}
        self.assertEqual(rows["bare"]["omh_home_reclaimed"], store.as_posix())

    def test_update_keeps_a_setting_it_did_not_write_beside_an_env_store(self) -> None:
        own_setting = "plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: /stores/own\n"
        own = self.profile("own", own_setting, env="OMH_HOME=/stores/bot\n")
        store = self.root / "isolated-omh"
        self.setup_at(store)

        self.update_at(store)

        self.assertEqual(plugin_omh_home_setting(self.profile_config(own)), "/stores/own")

    def test_update_keeps_a_value_changed_by_hand_after_it_wrote_one(self) -> None:
        bare = self.profile("bare")
        store = self.root / "isolated-omh"
        self.setup_at(store)
        elsewhere = self.root / "elsewhere"
        (bare / "config.yaml").write_text(
            self.profile_config(bare).replace(f"'{store.as_posix()}'", f"'{elsewhere.as_posix()}'"), encoding="utf-8"
        )
        (bare / ".env").write_text("OMH_HOME=/stores/bot\n", encoding="utf-8")

        self.update_at(store)

        self.assertEqual(plugin_omh_home_setting(self.profile_config(bare)), elsewhere.as_posix())

    def test_update_keeps_its_setting_on_a_profile_without_an_env_store(self) -> None:
        bare = self.profile("bare")
        other = self.profile("other", env="OPENAI_API_KEY=x\n")
        store = self.root / "isolated-omh"
        self.setup_at(store)

        self.update_at(store)

        self.assertEqual(plugin_omh_home_setting(self.profile_config(bare)), store.as_posix())
        self.assertEqual(plugin_omh_home_setting(self.profile_config(other)), store.as_posix())

    def test_update_under_a_default_primary_leaves_an_env_profile_alone(self) -> None:
        envbot = self.profile("envbot", "version: 1\n", env="OMH_HOME=/stores/bot\n")
        store = self.root / ".omh"
        self.setup_at(store)
        before = self.profile_config(envbot)

        self.update_at(store)

        self.assertEqual(self.profile_config(envbot), before)
        self.assertNotIn("omh_home", before)


class DoctorBindingTests(_IsolatedHome):
    def doctor_row(self, store: Path) -> dict:
        _status, stdout, _stderr = run_cli(
            ["--omh-home", str(store), "--hermes-home", str(self.hermes_home), "doctor", "--json"],
        )
        rows = [row for row in json.loads(stdout)["checks"] if row["name"] == "plugin_omh_home_binding"]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_a_bound_pair_passes(self) -> None:
        store = self.root / "isolated-omh"
        self.setup_at(store, "--with-plugin")

        row = self.doctor_row(store)

        self.assertEqual(row["severity"], "ok", row)

    def test_an_unbound_pair_warns_without_blocking(self) -> None:
        store = self.root / "isolated-omh"
        self.setup_at(store, "--with-plugin")
        unbound = remove_plugin_omh_home(self.config(), store.as_posix())
        self.config_path.write_text(unbound.text, encoding="utf-8")

        row = self.doctor_row(store)

        self.assertTrue(row["ok"], row)
        self.assertEqual(row["severity"], "warning", row)
        self.assertIn(str(self.root / ".omh"), row["message"])
        self.assertIn(str(store), row["next_action"])

    def test_a_setting_naming_another_store_warns(self) -> None:
        store = self.root / "isolated-omh"
        self.setup_at(store, "--with-plugin")
        elsewhere = self.root / "elsewhere"
        self.config_path.write_text(
            self.config().replace(f"'{store.as_posix()}'", f"'{elsewhere.as_posix()}'"), encoding="utf-8"
        )

        row = self.doctor_row(store)

        self.assertEqual(row["severity"], "warning", row)
        self.assertIn(str(elsewhere), row["message"])


class DoctorProfileBindingTests(_IsolatedHome):
    def doctor_rows(self, store: Path) -> dict[str, dict]:
        status, stdout, _stderr = run_cli(
            ["--omh-home", str(store), "--hermes-home", str(self.hermes_home), "doctor", "--json"],
        )
        payload = json.loads(stdout)
        self.doctor_status = status
        return {
            row["name"]: row for row in payload["checks"] if row["name"].startswith("plugin_omh_home_binding:")
        }

    def test_an_unbound_profile_warns_without_blocking(self) -> None:
        bare = self.hermes_home / "profiles" / "bare"
        bare.mkdir(parents=True)
        (bare / "SOUL.md").write_text("Profile identity\n", encoding="utf-8")
        store = self.root / "isolated-omh"
        self.setup_at(store, "--with-plugin")
        self.assertEqual(self.doctor_rows(store), {})
        unbound = remove_plugin_omh_home((bare / "config.yaml").read_text(encoding="utf-8"), store.as_posix())
        (bare / "config.yaml").write_text(unbound.text, encoding="utf-8")
        baseline = self.doctor_status

        rows = self.doctor_rows(store)

        row = rows["plugin_omh_home_binding:bare"]
        self.assertTrue(row["ok"], row)
        self.assertEqual(row["severity"], "warning", row)
        self.assertIn(str(self.root / ".omh"), row["message"])
        self.assertIn(str(bare), row["next_action"])
        self.assertEqual(self.doctor_status, baseline)

    def test_a_profile_that_chose_a_store_is_not_reported(self) -> None:
        for name, env in (("env", "OMH_HOME=/stores/bot\n"), ("own", "")):
            home = self.hermes_home / "profiles" / name
            home.mkdir(parents=True)
            (home / "SOUL.md").write_text("Profile identity\n", encoding="utf-8")
            if env:
                (home / ".env").write_text(env, encoding="utf-8")
            else:
                (home / "config.yaml").write_text(
                    "plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: /stores/own\n", encoding="utf-8"
                )
        store = self.root / "isolated-omh"
        self.setup_at(store, "--with-plugin")

        self.assertEqual(self.doctor_rows(store), {})

    def assert_foreign_setting_shadowing_the_env_store_warns(self, store: Path) -> None:
        # #1973: update takes back only its own write, so a setting somebody
        # else put there keeps outranking the `.env` choice, and doctor says so.
        home = self.hermes_home / "profiles" / "own"
        home.mkdir(parents=True)
        (home / "SOUL.md").write_text("Profile identity\n", encoding="utf-8")
        (home / "config.yaml").write_text(
            "plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: /stores/own\n", encoding="utf-8"
        )
        self.setup_at(store, "--with-plugin")
        self.assertEqual(self.doctor_rows(store), {})
        baseline = self.doctor_status
        (home / ".env").write_text("OMH_HOME=/stores/bot\n", encoding="utf-8")

        rows = self.doctor_rows(store)

        row = rows["plugin_omh_home_binding:own"]
        self.assertTrue(row["ok"], row)
        self.assertEqual(row["severity"], "warning", row)
        self.assertIn("/stores/own", row["message"])
        self.assertIn(str(home / ".env"), row["message"])
        self.assertIn(str(home / "config.yaml"), row["next_action"])
        self.assertEqual(self.doctor_status, baseline)

    def test_a_foreign_setting_shadowing_the_env_store_warns(self) -> None:
        self.assert_foreign_setting_shadowing_the_env_store_warns(self.root / "isolated-omh")

    def test_a_foreign_setting_shadowing_the_env_store_warns_under_a_default_primary(self) -> None:
        # The shadow does not depend on where the primary's store is.
        self.assert_foreign_setting_shadowing_the_env_store_warns(self.root / ".omh")

    def test_the_setting_omh_wrote_beside_an_env_store_is_not_reported(self) -> None:
        # Update takes it back; doctor reports only what update will not fix.
        home = self.hermes_home / "profiles" / "bare"
        home.mkdir(parents=True)
        (home / "SOUL.md").write_text("Profile identity\n", encoding="utf-8")
        store = self.root / "isolated-omh"
        self.setup_at(store, "--with-plugin")
        (home / ".env").write_text("OMH_HOME=/stores/bot\n", encoding="utf-8")

        self.assertEqual(self.doctor_rows(store), {})

    def test_profiles_setup_bound_under_a_default_primary_are_not_reported(self) -> None:
        (self.hermes_home / "profiles" / "bare").mkdir(parents=True)
        (self.hermes_home / "profiles" / "bare" / "SOUL.md").write_text(
            "Profile identity\n", encoding="utf-8"
        )
        store = self.root / ".omh"
        self.setup_at(store, "--with-plugin")

        self.assertEqual(self.doctor_rows(store), {})

    def test_an_unbound_default_store_install_reports_the_multiplex_refusal(self) -> None:
        # #2037: a default-store install made before setup named `~/.omh`.
        # A single-profile process binds it, so every check passed, while a
        # multiplexed one refused to load the plugin for every profile.
        bare = self.hermes_home / "profiles" / "bare"
        bare.mkdir(parents=True)
        (bare / "SOUL.md").write_text("Profile identity\n", encoding="utf-8")
        store = self.root / ".omh"
        self.setup_at(store, "--with-plugin")
        for config_path in (self.config_path, bare / "config.yaml"):
            unbound = remove_plugin_omh_home(config_path.read_text(encoding="utf-8"), store.as_posix())
            self.assertTrue(unbound.changed, unbound.message)
            config_path.write_text(unbound.text, encoding="utf-8")

        rows = self.doctor_rows(store)
        _status, stdout, _stderr = run_cli(
            ["--omh-home", str(store), "--hermes-home", str(self.hermes_home), "doctor", "--json"],
        )
        primary = next(row for row in json.loads(stdout)["checks"] if row["name"] == "plugin_omh_home_binding")

        for row in (primary, rows["plugin_omh_home_binding:bare"]):
            self.assertTrue(row["ok"], row)
            self.assertEqual(row["severity"], "warning", row)
            self.assertIn("multiplexed", row["message"])
            self.assertIn("update", row["next_action"])


class MultiplexedDefaultStoreTests(_IsolatedHome):
    """The plugin's own resolver, inside a process that serves several profiles (#2037).

    A stand-in for the host modules a multiplexed Hermes process (the
    gateway, Desktop `serve`) gives the plugin: the multiplex flag on, a
    home override naming the profile being served, and that profile's own
    secret scope. The resolver is unchanged by #2037; what changed is that
    setup names the default store in every home it registers, so the
    profiles the install serves bind it here too.
    """

    profile = ProfileStoreChoiceTests.profile

    @staticmethod
    def _config(text: str) -> dict:
        found, value = runtime_paths.omh_home_setting(text)
        return {"plugins": {"entries": {"omh": {"settings": {"omh_home": value}}}}} if found else {}

    @staticmethod
    def _env(home: Path) -> dict[str, str]:
        path = home / ".env"
        if not path.is_file():
            return {}
        pairs = (line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)
        return {key.strip(): value.strip() for key, value in pairs}

    def multiplexed_bind(self, home: Path) -> Path:
        """What the plugin binds while a multiplexed process serves `home`."""
        def read(path: object) -> dict:
            config = Path(str(path))
            return self._config(config.read_text(encoding="utf-8")) if config.is_file() else {}

        def refuse(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("a multiplexed process never reads the process environment")

        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home = lambda: home
        constants.get_hermes_home_override = lambda: home
        secrets = types.ModuleType("agent.secret_scope")
        secrets.is_multiplex_active = lambda: True
        secrets.current_secret_scope = lambda: self._env(home)
        secrets.get_secret = refuse
        secrets.build_profile_secret_scope = self._env
        config = types.ModuleType("hermes_cli.config")
        config.require_readable_config_before_write = read
        config.load_config_readonly = lambda: read(home / "config.yaml")
        managed = types.ModuleType("hermes_cli.managed_scope")
        managed.load_managed_config = lambda: {}
        cwd = types.SimpleNamespace(resolve_context_cwd=lambda: None, resolve_agent_cwd=Path.cwd)
        modules = {"hermes_constants": constants, "agent.secret_scope": secrets, "hermes_cli.config": config,
                   "hermes_cli.managed_scope": managed, "agent.runtime_cwd": cwd}
        with patch_modules(modules), patch.dict(os.environ, {"HERMES_HOME": str(self.hermes_home)}):
            return runtime_paths.resolve_homes()[0]

    def test_every_profile_of_a_default_store_install_binds_it(self) -> None:
        bare = self.profile("bare", "version: 1\n")
        default = self.root / ".omh"

        self.setup_at(default)

        self.assertEqual(self.multiplexed_bind(self.hermes_home), default)
        self.assertEqual(self.multiplexed_bind(bare), default)

    def test_a_profile_that_chose_a_store_keeps_it_beside_the_default(self) -> None:
        own_store = self.root / "bot-store"
        own = self.profile(
            "own", f"plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: {own_store.as_posix()}\n"
        )
        env_store = self.root / "env-store"
        envbot = self.profile("envbot", "version: 1\n", env=f"OMH_HOME={env_store.as_posix()}\n")
        default = self.root / ".omh"

        self.setup_at(default)

        self.assertEqual(self.multiplexed_bind(own), own_store)
        self.assertEqual(self.multiplexed_bind(envbot), env_store)
        self.assertEqual(self.multiplexed_bind(self.hermes_home), default)

    def test_a_profile_naming_no_store_is_still_refused(self) -> None:
        # The safety property the refusal protects: a profile that names no
        # store is never handed one by a multiplexed process, not even the
        # default store the launch profile and its siblings bind -- here a
        # bot created after the last setup or update.
        default = self.root / ".omh"
        self.setup_at(default)
        self.assertEqual(self.multiplexed_bind(self.hermes_home), default)
        late = self.profile("late", "version: 1\n")

        with self.assertRaisesRegex(runtime_paths.RuntimeBindingError, "not configured for this profile"):
            self.multiplexed_bind(late)


class EnsurePluginOmhHomeTests(unittest.TestCase):
    def test_existing_entries_keep_their_indent_and_siblings(self) -> None:
        text = "plugins:\n  enabled:\n    - omh\n  entries:\n    other:\n      enabled: true\nmemory:\n  provider: omh\n"

        change = ensure_plugin_omh_home(text, "/stores/x")

        self.assertTrue(change.changed, change.message)
        self.assertEqual(
            change.text,
            "plugins:\n  enabled:\n    - omh\n  entries:\n    other:\n      enabled: true\n"
            "    omh:\n      settings:\n        omh_home: '/stores/x'\nmemory:\n  provider: omh\n",
        )
        self.assertEqual(remove_plugin_omh_home(change.text, "/stores/x").text, text)

    def test_shapes_the_plugin_scan_would_not_follow_are_left_alone(self) -> None:
        for text in (
            "plugins:\n  entries: {}\n",
            "plugins:\n  entries:\n    omh: ~\n",
            "plugins: &p\n  enabled:\n    - omh\n",
            "plugins:\n  enabled:\n    - omh\n  entries:\n    omh:\n      settings:\n        omh_home: /y\n",
        ):
            with self.subTest(text=text):
                change = ensure_plugin_omh_home(text, "/stores/x")
                self.assertFalse(change.changed, change.message)
                self.assertEqual(change.text, text)

    def test_a_path_with_a_single_quote_is_not_written(self) -> None:
        change = ensure_plugin_omh_home("plugins:\n  enabled:\n    - omh\n", "/stores/it's")

        self.assertFalse(change.changed)

    def test_removal_leaves_a_value_somebody_changed(self) -> None:
        text = ensure_plugin_omh_home("plugins:\n  enabled:\n    - omh\n", "/stores/x").text.replace("/stores/x", "/mine")

        self.assertFalse(remove_plugin_omh_home(text, "/stores/x").changed)


if __name__ == "__main__":
    unittest.main()
