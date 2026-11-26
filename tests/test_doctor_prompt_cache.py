from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.maintenance.doctor import doctor_ok, run_doctor  # noqa: E402
from omh.maintenance.prompt_cache_route import (  # noqa: E402
    PROMPT_CACHE_ROUTE_SCHEMA_VERSION,
    prompt_cache_hint_lines,
    prompt_cache_route_report,
)
from omh.paths import OmhPaths  # noqa: E402

NOW = datetime(2026, 11, 24, 20, 0, 0)

_PROXY_ROUTE = """model:
  provider: claude-proxy
  default: claude-opus-5-5
providers:
  claude-proxy:
    base_url: http://127.0.0.1:8317/v1
    api_mode: chat_completions
    key_cmd: security find-generic-password -ws claude-proxy-api-key
"""

_LOG = """2026-11-22 10:00:00,001 INFO [s0] agent.prompt_cache_lifecycle.warmer: prompt cache warming stopped: warm budget spent this turn (refreshes=3, spent=$0.0100)
2026-11-24 09:00:00,001 INFO [s1] agent.prompt_cache_lifecycle.warmer: prompt cache warming stopped: cache economics unavailable (refreshes=0, spent=$0.0000)
2026-11-24 09:00:01,002 INFO [s1] run_agent: unrelated line
2026-11-24 12:00:00,003 INFO [s2] agent.prompt_cache_lifecycle.warmer: prompt cache warming stopped: the parent agent keeps this prefix warm (refreshes=0, spent=$0.0000)
2026-11-24 19:30:00,004 INFO [s3] agent.prompt_cache_lifecycle.warmer: prompt cache warming stopped: cache economics unavailable (refreshes=0, spent=$0.0000)
"""


def _home(root: Path, config: str | None, log: str | None = None) -> Path:
    home = root / ".hermes"
    home.mkdir(parents=True, exist_ok=True)
    if config is not None:
        (home / "config.yaml").write_text(config, encoding="utf-8")
    if log is not None:
        (home / "logs").mkdir(exist_ok=True)
        (home / "logs" / "agent.log").write_text(log, encoding="utf-8")
    return home


class PromptCacheRouteReportTests(unittest.TestCase):
    def test_5m_on_a_1h_proxy_without_ceiling_warns_with_exact_fixes(self) -> None:
        with TemporaryDirectory() as tmp:
            home = _home(Path(tmp), _PROXY_ROUTE + "prompt_caching:\n  cache_ttl: 5m\n")
            report = prompt_cache_route_report(home, now=NOW)
            self.assertEqual(report["schema_version"], PROMPT_CACHE_ROUTE_SCHEMA_VERSION)
            self.assertEqual(len(report["findings"]), 1)
            self.assertIn("pinned to 5m", report["findings"][0])
            self.assertEqual(
                report["fixes"],
                [
                    "hermes config set prompt_caching.cache_ttl auto",
                    "hermes config set prompt_caching.route_ttl_ceilings.claude-proxy 1h",
                ],
            )
            self.assertNotIn("claude-proxy-api-key", json.dumps(report))

    def test_auto_with_1h_ceiling_is_ok(self) -> None:
        with TemporaryDirectory() as tmp:
            config = _PROXY_ROUTE + "prompt_caching:\n  cache_ttl: auto\n  route_ttl_ceilings:\n    claude-proxy: 1h\n"
            report = prompt_cache_route_report(_home(Path(tmp), config), now=NOW)
            self.assertEqual(report["findings"], [])
            self.assertEqual(report["route_ttl_ceiling"], "1h")
            self.assertIn("cache TTL matches what the route keeps", report["lines"])

    def test_5m_with_1h_ceiling_still_warns_with_only_the_ttl_fix(self) -> None:
        # Hermes returns a 5m request before consulting the ceiling, so the ceiling never lifts the pin.
        with TemporaryDirectory() as tmp:
            config = _PROXY_ROUTE + "prompt_caching:\n  cache_ttl: '5m'\n  route_ttl_ceilings: {claude-proxy: 1h}\n"
            report = prompt_cache_route_report(_home(Path(tmp), config), now=NOW)
            self.assertEqual(len(report["findings"]), 1)
            self.assertIn("pinned to 5m", report["findings"][0])
            self.assertEqual(report["fixes"], ["hermes config set prompt_caching.cache_ttl auto"])
            self.assertNotIn("cache TTL matches what the route keeps", report["lines"])

    def test_auto_or_1h_without_ceiling_warns_with_only_the_ceiling_fix(self) -> None:
        for ttl_block in ("prompt_caching:\n  cache_ttl: auto\n", "prompt_caching:\n  cache_ttl: 1h\n", ""):
            with self.subTest(ttl_block=ttl_block), TemporaryDirectory() as tmp:
                report = prompt_cache_route_report(_home(Path(tmp), _PROXY_ROUTE + ttl_block), now=NOW)
                self.assertEqual(len(report["findings"]), 1)
                self.assertNotIn("pinned to 5m", report["findings"][0])
                self.assertEqual(
                    report["fixes"], ["hermes config set prompt_caching.route_ttl_ceilings.claude-proxy 1h"]
                )

    def test_1h_with_1h_ceiling_is_ok(self) -> None:
        with TemporaryDirectory() as tmp:
            config = _PROXY_ROUTE + "prompt_caching:\n  cache_ttl: 1h\n  route_ttl_ceilings:\n    claude-proxy: 1h\n"
            self.assertEqual(prompt_cache_route_report(_home(Path(tmp), config), now=NOW)["findings"], [])

    def test_proxy_alias_on_a_direct_first_party_endpoint_is_not_a_proxy(self) -> None:
        # The base_url decides: a reused `claude-proxy` name pointing at api.anthropic.com is a direct route.
        for where in ("providers", "model"):
            with self.subTest(where=where), TemporaryDirectory() as tmp:
                if where == "providers":
                    route = (
                        "model:\n  provider: claude-proxy\n  default: claude-sonnet-4-6\nproviders:\n"
                        "  claude-proxy:\n    base_url: https://api.anthropic.com\n"
                    )
                else:
                    route = (
                        "model:\n  provider: claude-proxy\n  default: claude-sonnet-4-6\n"
                        "  base_url: https://api.anthropic.com\n"
                    )
                report = prompt_cache_route_report(_home(Path(tmp), route + "prompt_caching:\n  cache_ttl: 5m\n"), now=NOW)
                self.assertEqual(report["findings"], [])
                self.assertEqual(report["fixes"], [])
                self.assertEqual(report["one_hour_proxy"], "")

    def test_local_host_without_claude_or_remote_host_is_not_a_proxy(self) -> None:
        cases = (
            ("http://127.0.0.1:8317/v1", "gpt-5"),
            ("https://proxy.example.com/v1", "claude-sonnet-4-6"),
        )
        for base_url, model in cases:
            with self.subTest(base_url=base_url, model=model), TemporaryDirectory() as tmp:
                config = (
                    f"model:\n  provider: claude-proxy\n  default: {model}\n  base_url: {base_url}\n"
                    "prompt_caching:\n  cache_ttl: 5m\n"
                )
                self.assertEqual(prompt_cache_route_report(_home(Path(tmp), config), now=NOW)["findings"], [])

    def test_private_address_serving_claude_is_a_1h_proxy(self) -> None:
        with TemporaryDirectory() as tmp:
            config = (
                "model:\n  provider: lan-cpa\n  default: claude-opus-5-5\n  base_url: http://192.168.0.12:8317/v1\n"
                "prompt_caching:\n  cache_ttl: 5m\n"
            )
            report = prompt_cache_route_report(_home(Path(tmp), config), now=NOW)
            self.assertEqual(len(report["findings"]), 1)

    def test_known_proxy_name_without_base_url_falls_back_to_the_table(self) -> None:
        with TemporaryDirectory() as tmp:
            config = "model:\n  provider: claude-proxy\n  default: claude-opus-5-5\nprompt_caching:\n  cache_ttl: 5m\n"
            report = prompt_cache_route_report(_home(Path(tmp), config), now=NOW)
            self.assertIn("CLIProxyAPI", report["one_hour_proxy"])
            self.assertEqual(len(report["fixes"]), 2)

    def test_unlisted_loopback_provider_serving_claude_is_a_1h_proxy(self) -> None:
        with TemporaryDirectory() as tmp:
            config = (
                "model:\n  provider: my-cpa\n  default: claude-sonnet-5-5\nproviders:\n  my-cpa:\n"
                "    base_url: http://localhost:8317/v1\nprompt_caching:\n  cache_ttl: 5m  # pinned\n"
            )
            report = prompt_cache_route_report(_home(Path(tmp), config), now=NOW)
            self.assertIn("hermes config set prompt_caching.route_ttl_ceilings.my-cpa 1h", report["fixes"])

    def test_5m_on_a_direct_route_is_not_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            config = (
                "model:\n  provider: anthropic\n  default: claude-opus-5-5\nprompt_caching:\n  cache_ttl: 5m\n"
            )
            self.assertEqual(prompt_cache_route_report(_home(Path(tmp), config), now=NOW)["findings"], [])

    def test_disabled_caching_is_flagged(self) -> None:
        for value in ("off", "false", "null", "''"):
            with self.subTest(value=value), TemporaryDirectory() as tmp:
                config = _PROXY_ROUTE + f"prompt_caching:\n  cache_ttl: {value}\n"
                report = prompt_cache_route_report(_home(Path(tmp), config), now=NOW)
                self.assertTrue(report["caching_disabled"])
                self.assertIn("prompt caching is disabled", report["findings"][0])
                self.assertEqual(report["fixes"], ["hermes config set prompt_caching.cache_ttl auto"])

    def test_missing_prompt_caching_section_means_auto(self) -> None:
        with TemporaryDirectory() as tmp:
            config = _PROXY_ROUTE + "prompt_caching:\n  route_ttl_ceilings:\n    claude-proxy: 1h\n"
            report = prompt_cache_route_report(_home(Path(tmp), config), now=NOW)
            self.assertEqual(report["findings"], [])
            self.assertEqual(report["cache_ttl"], "auto (default)")

    def test_warmer_stop_reasons_are_counted_over_the_last_24h_with_explanations(self) -> None:
        with TemporaryDirectory() as tmp:
            home = _home(Path(tmp), _PROXY_ROUTE, _LOG)
            report = prompt_cache_route_report(home, now=NOW)
            warmer = report["warmer"]
            self.assertTrue(warmer["read"])
            self.assertEqual(
                warmer["counts"],
                {"cache economics unavailable": 2, "the parent agent keeps this prefix warm": 1},
            )
            self.assertEqual(warmer["latest"], "cache economics unavailable")
            text = "\n".join(report["lines"])
            self.assertIn("2x cache economics unavailable -- the route has no cache prices", text)
            self.assertIn("no quota is spent", text)
            self.assertNotIn("warm budget spent", text)

    def test_missing_config_and_log_are_said_not_hidden(self) -> None:
        with TemporaryDirectory() as tmp:
            report = prompt_cache_route_report(_home(Path(tmp), None), now=NOW)
            self.assertFalse(report["config_read"])
            self.assertFalse(report["warmer"]["read"])
            self.assertTrue(any("not readable" in line for line in report["lines"]))
            self.assertTrue(any("no agent log" in line for line in report["lines"]))

    def test_model_hint_carries_only_the_warning_and_fixes(self) -> None:
        with TemporaryDirectory() as tmp:
            bad = _home(Path(tmp) / "a", _PROXY_ROUTE + "prompt_caching:\n  cache_ttl: 5m\n", _LOG)
            good = _home(Path(tmp) / "b", _PROXY_ROUTE + "prompt_caching:\n  route_ttl_ceilings: {claude-proxy: 1h}\n", _LOG)
            hint = prompt_cache_hint_lines(bad)
            self.assertEqual(len(hint), 3)
            self.assertTrue(hint[0].startswith("warning:"))
            self.assertEqual(prompt_cache_hint_lines(good), [])


class PromptCacheDoctorTests(unittest.TestCase):
    def _paths(self, root: Path) -> OmhPaths:
        return OmhPaths(root.resolve() / ".omh", root.resolve() / ".hermes")

    def test_doctor_row_warns_without_failing(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            _home(Path(tmp).resolve(), _PROXY_ROUTE + "prompt_caching:\n  cache_ttl: 5m\n", _LOG)
            checks = run_doctor(paths)
            check = next(item for item in checks if item.name == "prompt_cache_route")
            self.assertTrue(check.ok)
            self.assertEqual(check.severity, "warning")
            self.assertIn("`hermes config set prompt_caching.cache_ttl auto`", check.next_action)
            self.assertIn("route_ttl_ceilings.claude-proxy 1h", check.next_action)
            self.assertEqual(check.detail["schema_version"], PROMPT_CACHE_ROUTE_SCHEMA_VERSION)
            self.assertEqual(doctor_ok([check]), True)

    def test_doctor_cli_prints_the_prompt_cache_section(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            # The CLI reads the warmer window against the wall clock (no `now` seam), so the log line is dated
            # relative to it; the fixed-date `_LOG` aged out of the 24h window a day after it was written.
            recent = (datetime.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
            log = (f"{recent},001 INFO [s1] agent.prompt_cache_lifecycle.warmer: prompt cache warming stopped: "
                   "cache economics unavailable (refreshes=0, spent=$0.0000)\n")
            _home(Path(tmp).resolve(), _PROXY_ROUTE + "prompt_caching:\n  cache_ttl: 5m\n", log)
            base = ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)]
            _status, stdout, _stderr = run_cli(base + ["doctor", "--no-state-write"], output_json=False)
            self.assertIn("Prompt cache (read-only)", stdout)
            self.assertIn("fix: hermes config set prompt_caching.route_ttl_ceilings.claude-proxy 1h", stdout)
            self.assertIn("cache economics unavailable", stdout)

    def test_model_show_prints_the_hint(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            _home(Path(tmp).resolve(), _PROXY_ROUTE + "prompt_caching:\n  cache_ttl: 5m\n")
            base = ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)]
            status, stdout, stderr = run_cli(base + ["model-chains", "show"], output_json=False)
            self.assertEqual(status, 0, stderr)
            self.assertIn("fix: hermes config set prompt_caching.cache_ttl auto", stdout)


if __name__ == "__main__":
    unittest.main()
