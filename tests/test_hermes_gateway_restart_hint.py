"""`omh update` names the running Hermes gateways that predate the bundle it installed.

File evidence only: Hermes' `gateway.pid` record says a gateway is running
in that home, `gateway-starts.log` carries the wall-clock start, and the
bundle manifest's `installed_at` says when OMH last wrote the plugin. The
pid record's `start_time` is a per-host PID-reuse fingerprint (centiseconds
on macOS, clock ticks since boot on Linux) and is pinned here as NOT read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli

from omh.maintenance.hermes_gateway import gateway_restart_hint, gateway_restart_hints, recorded_gateway_starts
from omh.paths import OmhPaths

_INSTALLED_AT = "2026-09-24T02:05:26Z"
_INSTALLED_EPOCH = datetime(2026, 9, 24, 2, 5, 26, tzinfo=UTC).timestamp()


def _write_home(
    home: Path,
    *,
    starts: list[float] | None,
    pid_record: dict[str, object] | str | None,
    installed_at: str | None = _INSTALLED_AT,
) -> None:
    home.mkdir(parents=True, exist_ok=True)
    if starts is not None:
        (home / "gateway-starts.log").write_text("".join(f"{repr(value)}\n" for value in starts), encoding="utf-8")
    if pid_record is not None:
        text = pid_record if isinstance(pid_record, str) else json.dumps(pid_record)
        (home / "gateway.pid").write_text(text, encoding="utf-8")
    if installed_at is not None:
        plugin = home / "plugins" / "omh"
        plugin.mkdir(parents=True, exist_ok=True)
        (plugin / ".omh-plugin-manifest.json").write_text(
            json.dumps({"schema_version": 1, "installed_at": installed_at, "files": []}), encoding="utf-8"
        )


def _record(home: Path, **overrides: object) -> dict[str, object]:
    # The owner machine's record shape on 2026-09-24: `start_time` is
    # psutil create_time * 100 there, and not a wall clock anywhere.
    record: dict[str, object] = {
        "pid": 29076,
        "kind": "hermes-gateway",
        "argv": ["hermes_cli/main.py", "gateway", "run", "--replace", "--external-supervisor"],
        "start_time": 178981055327,
        "hermes_home": str(home),
    }
    record.update(overrides)
    return record


class GatewayRestartHintTests(unittest.TestCase):
    def test_a_gateway_started_before_the_bundle_was_installed_is_named(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "miku"
            _write_home(home, starts=[1789456697.382985, 1789551415.168149, 1789810555.531535], pid_record=_record(home))

            hint = gateway_restart_hint(home, label="profile miku", restart_command="hermes --profile miku gateway restart")

            self.assertEqual(
                hint,
                "Hermes gateway for profile miku: last recorded start 2026-09-19T09:35:55Z precedes this bundle's "
                "install (2026-09-24T02:05:26Z); run `hermes --profile miku gateway restart`",
            )

    def test_a_gateway_started_after_the_install_needs_no_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "miku"
            _write_home(home, starts=[1789810555.531535, _INSTALLED_EPOCH + 60], pid_record=_record(home))
            self.assertIsNone(gateway_restart_hint(home, label="x", restart_command="y"))

    def test_the_pid_record_start_time_is_not_read_as_a_clock(self) -> None:
        # Same files, opposite `start_time` values: the verdict does not move.
        with TemporaryDirectory() as tmp:
            stale = Path(tmp) / "stale"
            _write_home(stale, starts=[_INSTALLED_EPOCH - 3600], pid_record=_record(stale, start_time=10**13))
            self.assertIsNotNone(gateway_restart_hint(stale, label="x", restart_command="y"))
            fresh = Path(tmp) / "fresh"
            _write_home(fresh, starts=[_INSTALLED_EPOCH + 3600], pid_record=_record(fresh, start_time=1))
            self.assertIsNone(gateway_restart_hint(fresh, label="x", restart_command="y"))

    def test_no_pid_record_means_no_running_gateway_to_name(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "primary"
            _write_home(home, starts=[_INSTALLED_EPOCH - 3600], pid_record=None)
            self.assertIsNone(gateway_restart_hint(home, label="x", restart_command="y"))

    def test_a_record_naming_another_home_is_that_home_s_gateway(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "primary"
            other = Path(tmp) / "profiles" / "miku"
            _write_home(home, starts=[_INSTALLED_EPOCH - 3600], pid_record=_record(other))
            self.assertIsNone(gateway_restart_hint(home, label="x", restart_command="y"))

    def test_a_legacy_record_without_a_home_is_read_as_this_home_s(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "primary"
            record = _record(home)
            del record["hermes_home"]
            _write_home(home, starts=[_INSTALLED_EPOCH - 3600], pid_record=record)
            self.assertIsNotNone(gateway_restart_hint(home, label="x", restart_command="y"))

    def test_unreadable_evidence_produces_no_hint(self) -> None:
        with TemporaryDirectory() as tmp:
            malformed = Path(tmp) / "malformed"
            _write_home(malformed, starts=[_INSTALLED_EPOCH - 3600], pid_record="{not json")
            self.assertIsNone(gateway_restart_hint(malformed, label="x", restart_command="y"))
            no_ledger = Path(tmp) / "no-ledger"
            _write_home(no_ledger, starts=None, pid_record=_record(no_ledger))
            self.assertIsNone(gateway_restart_hint(no_ledger, label="x", restart_command="y"))
            junk_ledger = Path(tmp) / "junk-ledger"
            _write_home(junk_ledger, starts=None, pid_record=_record(junk_ledger))
            (junk_ledger / "gateway-starts.log").write_text("not a number\n\n", encoding="utf-8")
            self.assertIsNone(gateway_restart_hint(junk_ledger, label="x", restart_command="y"))
            no_bundle = Path(tmp) / "no-bundle"
            _write_home(no_bundle, starts=[_INSTALLED_EPOCH - 3600], pid_record=_record(no_bundle), installed_at=None)
            self.assertIsNone(gateway_restart_hint(no_bundle, label="x", restart_command="y"))
            bad_stamp = Path(tmp) / "bad-stamp"
            _write_home(bad_stamp, starts=[_INSTALLED_EPOCH - 3600], pid_record=_record(bad_stamp), installed_at="yesterday")
            self.assertIsNone(gateway_restart_hint(bad_stamp, label="x", restart_command="y"))

    def test_a_ledger_hermes_did_not_write_never_raises_out_of_update(self) -> None:
        # `omh update` prints the hint after a successful install and `main`
        # catches only OmhError, so a line that parses as a float but is not
        # a timestamp, or bytes that are not UTF-8, must yield no hint rather
        # than a traceback. A finite positive start on another line still
        # counts.
        cases: dict[str, bytes] = {
            "nan": b"nan\n",
            "negative": b"-1e12\n",
            "negative-inf": b"-1e400\n",
            "inf": b"1e400\n",
            "not-utf8": b"\xff\xfe1790000000.0\n",
            "empty": b"",
        }
        with TemporaryDirectory() as tmp:
            for label, payload in cases.items():
                with self.subTest(label):
                    home = Path(tmp) / label
                    _write_home(home, starts=None, pid_record=_record(home))
                    (home / "gateway-starts.log").write_bytes(payload)
                    self.assertIsNone(gateway_restart_hint(home, label="x", restart_command="y"))
            mixed = Path(tmp) / "mixed"
            _write_home(mixed, starts=None, pid_record=_record(mixed))
            (mixed / "gateway-starts.log").write_text(f"nan\n-5\n{_INSTALLED_EPOCH - 3600!r}\ninf\n", encoding="utf-8")
            self.assertIsNotNone(gateway_restart_hint(mixed, label="x", restart_command="y"))
            huge = Path(tmp) / "huge-stamp"
            _write_home(huge, starts=[_INSTALLED_EPOCH - 3600], pid_record=_record(huge), installed_at="9999-12-31T23:59:59Z")
            # Whether a year-9999 stamp converts back is the platform's
            # time_t range (POSIX yes, Windows no); either way nothing raises.
            far = datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC).timestamp()
            try:
                datetime.fromtimestamp(far, UTC)
                convertible = True
            except (ValueError, OverflowError, OSError):
                convertible = False
            hint = gateway_restart_hint(huge, label="x", restart_command="y")
            if convertible:
                self.assertEqual(
                    hint,
                    "Hermes gateway for x: last recorded start 2026-09-24T01:05:26Z precedes this bundle's "
                    "install (9999-12-31T23:59:59Z); run `y`",
                )
            else:
                self.assertIsNone(hint)

    def test_hints_cover_the_primary_home_and_every_profile_with_their_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            _write_home(hermes_home, starts=[_INSTALLED_EPOCH - 3600], pid_record=_record(hermes_home))
            miku = hermes_home / "profiles" / "miku"
            # A real named profile has host identity; an empty shell is ignored.
            miku.mkdir(parents=True, exist_ok=True)
            (miku / "SOUL.md").write_text("Profile identity\n", encoding="utf-8")
            _write_home(miku, starts=[_INSTALLED_EPOCH - 60], pid_record=_record(miku))
            fresh = hermes_home / "profiles" / "fresh"
            fresh.mkdir(parents=True, exist_ok=True)
            (fresh / "SOUL.md").write_text("Profile identity\n", encoding="utf-8")
            _write_home(fresh, starts=[_INSTALLED_EPOCH + 60], pid_record=_record(fresh))
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=hermes_home)

            hints = gateway_restart_hints(paths)

            self.assertEqual(
                hints,
                [
                    f"Hermes gateway for {hermes_home}: last recorded start 2026-09-24T01:05:26Z precedes this "
                    "bundle's install (2026-09-24T02:05:26Z); run `hermes gateway restart`",
                    "Hermes gateway for profile miku: last recorded start 2026-09-24T02:04:26Z precedes this "
                    "bundle's install (2026-09-24T02:05:26Z); run `hermes --profile miku gateway restart`",
                ],
            )

    def test_recorded_starts_cover_the_primary_home_and_profiles_on_the_hint_s_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            _write_home(hermes_home, starts=[_INSTALLED_EPOCH - 3600, _INSTALLED_EPOCH - 7200], pid_record=_record(hermes_home))
            for name, pid_record in (("miku", True), ("stopped", False)):
                profile = hermes_home / "profiles" / name
                profile.mkdir(parents=True, exist_ok=True)
                (profile / "SOUL.md").write_text("Profile identity\n", encoding="utf-8")
                _write_home(profile, starts=[_INSTALLED_EPOCH + 60], pid_record=_record(profile) if pid_record else None)

            self.assertEqual(recorded_gateway_starts(hermes_home), [_INSTALLED_EPOCH - 3600, _INSTALLED_EPOCH + 60])


class UpdatePrintsRestartHintsTests(unittest.TestCase):
    def _base(self, root: Path) -> list[str]:
        return ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

    def test_update_prints_the_hint_for_a_stale_gateway_and_stays_quiet_for_a_fresh_one(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            miku = hermes_home / "profiles" / "miku"
            miku.mkdir(parents=True)
            # Seed genuine profile identity before setup registers the profile.
            (miku / "SOUL.md").write_text("Profile identity\n", encoding="utf-8")
            status, _, stderr = run_cli(self._base(root) + ["setup"])
            self.assertEqual(status, 0, stderr)
            # Started well before any bundle this test installs; the update
            # below rewrites the bundle, so its `installed_at` is later still.
            stale_start = datetime.now(UTC).timestamp() - 86400
            _write_home(hermes_home, starts=[stale_start], pid_record=_record(hermes_home), installed_at=None)
            fresh_start = (datetime.now(UTC) + timedelta(days=1)).timestamp()
            _write_home(miku, starts=[fresh_start], pid_record=_record(miku), installed_at=None)

            status, stdout, stderr = run_cli(self._base(root) + ["update"], output_json=False)

            self.assertEqual(status, 0, stderr)
            self.assertIn(f"  Hermes gateway for {hermes_home.resolve()}: last recorded start ", stdout)
            self.assertIn("; run `hermes gateway restart`", stdout)
            self.assertNotIn("hermes --profile miku gateway restart", stdout)
            # The existing restart line is kept beside the named hint.
            self.assertIn("Restart Hermes Desktop for bot chats to reload skills.", stdout)
            self.assertLess(stdout.index("Bot profiles:"), stdout.index("Hermes gateway for"))

    def test_update_json_carries_the_same_hints(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            status, _, stderr = run_cli(self._base(root) + ["setup"])
            self.assertEqual(status, 0, stderr)
            _write_home(hermes_home, starts=[datetime.now(UTC).timestamp() - 86400], pid_record=_record(hermes_home),
                        installed_at=None)

            status, stdout, stderr = run_cli(self._base(root) + ["update"])

            self.assertEqual(status, 0, stderr)
            [hint] = json.loads(stdout)["gateway_restart_hints"]
            self.assertTrue(hint.startswith(f"Hermes gateway for {hermes_home.resolve()}: last recorded start "))
            self.assertTrue(hint.endswith("; run `hermes gateway restart`"))


if __name__ == "__main__":
    unittest.main()
