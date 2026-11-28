"""A bot's backup model (BOUNDARY rule 55): Hermes' own fallback chain, `fallback_providers` in the profile's
config.yaml, read with only each entry's provider and model leaving the bridge, and set through one fixed
`hermes -p <bot> config set fallback_providers <list>`. The op tests use a temp Hermes home and a fake runner; the one
real run (`RealHermes`) runs the exact argv against a scratch profile in a temp Hermes home, never a real profile."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402

BOT = "demo-bot"
PRIMARY = "model:\n  default: gpt-6.1-sol\n  provider: openai\n"


class Argv(unittest.TestCase):
    def test_one_fixed_argv_with_a_flow_literal_and_no_quote(self):
        chain = [{"provider": "openrouter", "model": "anthropic/claude-sonnet-4.5"}, {"provider": "ollama", "model": "qwen3:8b"}]
        self.assertEqual(ob.fallback_argv("/h", BOT, chain), [
            "/h", "-p", BOT, "config", "set", "fallback_providers",
            "[{provider: openrouter, model: anthropic/claude-sonnet-4.5}, {provider: ollama, model: qwen3:8b}]"])
        self.assertEqual(ob.fallback_argv("/h", BOT, [])[-1], "[]")
        # Windows: the line subprocess writes for a `hermes.cmd` shim holds no `"` or `\` inside the value and none of
        # cmd.exe's own characters, so cmd.exe hands the value to Hermes as it is
        value = ob.fallback_argv("/h", BOT, chain)[-1]
        line = subprocess.list2cmdline(["hermes.cmd", value])
        self.assertEqual(line, f'hermes.cmd "{value}"')
        for ch in '"\\%!^&|<>()':
            self.assertNotIn(ch, value, ch)

    def test_the_chain_is_checked_before_anything_runs(self):
        ok = {"provider": "openai", "model": "gpt-6.1-terra"}
        bad = [
            None, "x", {"provider": "a", "model": "b"}, [ok] * 2, [{"provider": "a", "model": f"m{i}"} for i in range(5)],
            [{"provider": "a"}], [{"provider": "a", "model": "b", "base_url": "http://x"}], [{"provider": "a", "model": 7}],
            ["openai"],
        ]
        for chain in bad:
            with self.assertRaises(ValueError, msg=repr(chain)):
                ob.fallback_check(chain)
        # shell, cmd.exe and YAML metacharacters, an option, a space, and values YAML reads as something else than text
        for value in ("-p", "--force", "a b", "x;y", "$(id)", "`id`", "a|b", "a&b", "a%b", "a^b", "a!b", "a\"b", "a'b",
                      "a,b", "a}b", "a]b", "a#b", "a: b", "@x", ":x", "x:", "x/", "*x", "&x", "!x", "a\nb", "",
                      "1.0", "true", "null", "yes", "on", "off", "12:30", "0x10", "1_000", "1e3", "2024-01-01", "n", "~",
                      "é", "x" * 129):
            for key in ("provider", "model"):
                with self.assertRaises(ValueError, msg=f"{key}={value!r}"):
                    ob.fallback_check([{**ok, key: value}])
        for value in ("gpt-6.1-sol", "qwen3:8b", "claude-opus-4-5@20251101", "a.b:c/d-e_f@g", "8b", "inf"):
            self.assertEqual(ob.fallback_check([{**ok, "model": value}]), [{**ok, "model": value}])
        for bad in ("-h", "a b", "x;y", "Bad.Name", "", None):
            with self.assertRaises(ValueError):
                ob.fallback_argv("/h", bad, [ok])

    def test_it_runs_through_the_shared_runner(self):
        seen = []
        with mock.patch.object(ob, "_run_hermes_argv", lambda argv, home, timeout: seen.append((argv, home, timeout)) or (0, "")):
            ob.run_hermes_fallback("/h", BOT, [], Path("/root"), 60.0)
        self.assertEqual(seen, [(["/h", "-p", BOT, "config", "set", "fallback_providers", "[]"], Path("/root"), 60.0)])


class Read(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def read(self, text: str) -> dict:
        (self.dir / "config.yaml").write_text(PRIMARY + text, encoding="utf-8")
        return ob.fallback_chain(self.dir)

    def test_provider_and_model_in_order(self):
        got = self.read("fallback_providers:\n  - provider: openrouter\n    model: x-ai/grok-4.7\n"
                        "  - {provider: ollama, model: 'qwen3:8b'}\n")
        self.assertEqual(got, {"chain": [{"provider": "openrouter", "model": "x-ai/grok-4.7"},
                                         {"provider": "ollama", "model": "qwen3:8b"}], "editable": True})
        self.assertEqual(self.read(""), {"chain": [], "editable": True})
        self.assertEqual(self.read("fallback_providers: []\nfallback_model: {}\n"), {"chain": [], "editable": True})
        self.assertEqual(ob.fallback_chain(self.dir / "none"), {"chain": [], "editable": True})

    def test_no_secret_bearing_field_leaves_the_bridge(self):
        got = self.read("fallback_providers:\n"
                        "  - provider: custom\n    model: my-model\n    base_url: https://gw.example/v1\n"
                        "    api_key: sk-secret-123\n    api_mode: chat_completions\n"
                        "  - provider: openrouter\n    model: x\n    key_env: OPENROUTER_KEY_2\n")
        self.assertEqual(got, {"chain": [{"provider": "custom", "model": "my-model", "custom": True},
                                         {"provider": "openrouter", "model": "x", "custom": True}], "editable": False})
        text = repr(got)
        for secret in ("sk-secret-123", "gw.example", "OPENROUTER_KEY_2", "chat_completions", "api_key", "base_url", "key_env"):
            self.assertNotIn(secret, text)

    def test_a_chain_omher_would_damage_is_not_editable(self):
        legacy = self.read("fallback_model:\n  provider: openrouter\n  model: x\n")
        self.assertEqual(legacy, {"chain": [{"provider": "openrouter", "model": "x"}], "editable": False})
        for text in ("fallback_providers:\n  - provider: a\n",                      # Hermes skips it: a rewrite drops it
                     "fallback_providers:\n  - just-a-string\n",
                     "fallback_providers: openrouter\n",
                     "fallback_providers:\n  - {provider: a, model: 1.5}\n",        # a number Hermes reads as text
                     "fallback_providers:\n  - {provider: a, model: 'true'}\n",     # text omher could not send back
                     "fallback_providers:\n" + "".join(f"  - {{provider: a, model: m{i}}}\n" for i in range(5))):
            self.assertFalse(self.read(text)["editable"], text)

    def test_a_config_that_does_not_parse_raises(self):
        (self.dir / "config.yaml").write_text("model: [unclosed\n", encoding="utf-8")
        with self.assertRaises(Exception):
            ob.fallback_chain(self.dir)


class Ops(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "hermes"
        self.config = self.home / "profiles" / BOT / "config.yaml"
        for path in (self.home / "config.yaml", self.config):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(PRIMARY, encoding="utf-8")
        self.bridge = ob.Bridge(token="t", hermes_home=self.home)
        self.runs: list[tuple] = []
        self.effect = self.store
        self._run = mock.patch.object(ob, "run_hermes_fallback", self.fake)
        self._path = mock.patch.object(ob, "hermes_path", lambda *a, **k: "/stub/hermes")
        for m in (self._run, self._path):
            m.start()

    def tearDown(self) -> None:
        for m in (self._path, self._run):
            m.stop()
        self._tmp.cleanup()

    def store(self, chain):
        """What Hermes' `config set` does: the list under `fallback_providers`, the rest of the file kept."""
        body = "".join(f"  - provider: {e['provider']}\n    model: {e['model']}\n" for e in chain)
        self.config.write_text(PRIMARY + ("fallback_providers:\n" + body if chain else "fallback_providers: []\n"), encoding="utf-8")
        return 0, "✓ Set fallback_providers"

    def fake(self, hermes, bot, chain, home, timeout):
        self.runs.append((hermes, bot, chain, Path(home), timeout))
        return self.effect(chain)

    def op(self, name: str, **p):
        if name == "set" and "base" not in p:  # the page sends the list it read: here, the file's
            p["base"] = [{"provider": e["provider"], "model": e["model"]} for e in self._read()]
        return asyncio.run(getattr(self.bridge, f"op_fallback_{name}")({"bot": BOT, **p}))

    def _read(self) -> list:
        try:
            return ob.fallback_chain(self.config.parent)["chain"]
        except Exception:  # noqa: BLE001 - a config that does not parse: the op says so itself
            return []

    def refused(self, code: str, **p) -> ob.BridgeError:
        with self.assertRaises(ob.BridgeError) as cm:
            self.op("set", **p)
        self.assertEqual(cm.exception.code, code, cm.exception.message)
        return cm.exception

    def test_set_runs_once_and_returns_what_hermes_stored(self):
        chain = [{"provider": "openrouter", "model": "x-ai/grok-4.7"}]
        got = self.op("set", chain=chain)
        self.assertEqual(got, {"outcome": "ok", "chain": chain, "editable": True})
        self.assertEqual(self.runs, [("/stub/hermes", BOT, chain, self.home, ob.FALLBACK_TIMEOUT)])
        self.assertEqual(self.op("get"), {"chain": chain, "editable": True})
        self.assertEqual(self.op("set", chain=[])["chain"], [])

    def test_the_page_sends_a_bot_and_a_chain_and_nothing_else(self):
        chain = [{"provider": "openai", "model": "gpt-6.1-terra"}]
        asyncio.run(self.bridge.op_fallback_set({"bot": BOT, "chain": chain, "base": [], "key": "model.default", "value": "x",
                                                 "argv": ["rm"], "force": True, "base_url": "http://evil"}))
        self.assertEqual(self.runs, [("/stub/hermes", BOT, chain, self.home, ob.FALLBACK_TIMEOUT)])
        self.assertNotIn("evil", self.config.read_text(encoding="utf-8"))

    def test_a_refused_literal_shows_hermes_words_and_the_chain_as_it_is(self):
        self.effect = lambda chain: (1, "✗ Value for 'fallback_providers' looks like a list/mapping but is not valid "
                                        "YAML/JSON (x) — nothing was written.")
        got = self.op("set", chain=[{"provider": "openai", "model": "gpt-6.1-terra"}])
        self.assertEqual(got["outcome"], "failed")
        self.assertIn("nothing was written", got["line"])
        self.assertEqual(got["chain"], [])
        self.effect = lambda chain: (None, "")
        self.assertIn("did not finish in 60 seconds", self.op("set", chain=[])["line"])
        self.effect = lambda chain: (0, "✓ Set fallback_providers")  # exit 0, nothing written: the file decides
        got = self.op("set", chain=[{"provider": "openai", "model": "gpt-6.1-terra"}])
        self.assertEqual((got["outcome"], got["chain"]), ("failed", []))

    def test_refusals_run_nothing(self):
        self.refused("bad_request", chain=[{"provider": "openai", "model": "1.0"}])
        self.refused("bad_request", chain=[{"provider": "a", "model": "b"}] * 2)
        e = self.refused("bad_request", chain=[{"provider": "OpenAI", "model": "GPT-6.1-sol"}])  # the bot's own model
        self.assertIn("own model", e.message)
        self.bridge._fallback_busy.add(BOT)
        self.refused("busy", chain=[])
        self.bridge._fallback_busy.clear()
        with mock.patch.object(ob, "hermes_path", lambda *a, **k: None):
            self.refused("no_hermes", chain=[])
        with self.assertRaises(ob.BridgeError) as cm:
            asyncio.run(self.bridge.op_fallback_set({"bot": "nobody", "chain": [], "base": []}))
        self.assertEqual(cm.exception.code, "unknown_bot")
        for base in (None, "x", ["openai"]):
            self.refused("bad_request", chain=[], base=base)
        self.assertEqual(self.runs, [])

    def test_two_sets_at_once_make_one_run(self):
        """Frames are handled concurrently: the second set must find the bot taken even while the first one still
        reads the config, before Hermes runs."""
        async def both():
            frames = [self.bridge.op_fallback_set({"bot": BOT, "chain": [{"provider": "openai", "model": f"gpt-6.1-{m}"}],
                                                   "base": []}) for m in ("terra", "luna")]
            return await asyncio.gather(*frames, return_exceptions=True)
        got = asyncio.run(both())
        self.assertEqual(len(self.runs), 1, got)
        self.assertEqual(sorted(type(r).__name__ for r in got), ["BridgeError", "dict"])
        self.assertEqual(next(r for r in got if isinstance(r, ob.BridgeError)).code, "busy")
        self.assertEqual(self.bridge._fallback_busy, set())

    def test_a_list_changed_elsewhere_is_refused_and_never_written_over(self):
        self.store([{"provider": "openrouter", "model": "x-ai/grok-4.7"}])  # set elsewhere after the page read none
        e = self.refused("changed", chain=[{"provider": "openai", "model": "gpt-6.1-terra"}], base=[])
        self.assertIn("changed elsewhere", e.message)
        self.assertEqual(self.runs, [])
        self.assertEqual(self.op("get")["chain"], [{"provider": "openrouter", "model": "x-ai/grok-4.7"}])
        # built on the list as it is now, it goes through
        chain = [{"provider": "openrouter", "model": "x-ai/grok-4.7"}, {"provider": "openai", "model": "gpt-6.1-terra"}]
        self.assertEqual(self.op("set", chain=chain, base=[{"provider": "openrouter", "model": "x-ai/grok-4.7"}])["chain"], chain)

    def test_providers_compare_as_hermes_compares_them(self):
        """Hermes' `_entry_identity` folds a provider's aliases through its own `normalize_provider`; so do the
        duplicate, own-model and skipped-entry checks."""
        try:
            from hermes_cli.fallback_config import _entry_identity
        except ImportError:
            self.assertEqual(ob.fallback_provider_id(" OpenAI "), "openai")  # no Hermes: lowercased, as Hermes falls back
            return
        same = ({"provider": "opencode-zen", "model": "m"}, {"provider": "opencode", "model": "M"})
        self.assertEqual(_entry_identity(same[0]), _entry_identity(same[1]))
        with self.assertRaises(ValueError):
            ob.fallback_check(list(same))
        self.config.write_text(PRIMARY + "fallback_providers:\n  - {provider: opencode-zen, model: m}\n"
                                         "  - {provider: opencode, model: m}\n", encoding="utf-8")
        self.assertFalse(self.op("get")["editable"])  # Hermes skips the second: a rewrite would drop it
        with mock.patch.object(self.bridge, "_profile_bot", lambda p: {"name": BOT, "provider": "opencode", "model": "gpt-6.1-sol",
                                                                       "display_name": "Demo", "path": self.config.parent}):
            e = self.refused("bad_request", chain=[{"provider": "opencode-zen", "model": "gpt-6.1-sol"}], base=[])
        self.assertIn("own model", e.message)
        self.assertEqual(self.runs, [])

    def test_a_chain_written_in_hermes_config_is_never_rewritten(self):
        text = PRIMARY + "fallback_providers:\n  - provider: custom\n    model: m\n    base_url: http://127.0.0.1:9/v1\n"
        self.config.write_text(text, encoding="utf-8")
        self.assertEqual(self.op("get"), {"chain": [{"provider": "custom", "model": "m", "custom": True}], "editable": False})
        self.refused("not_editable", chain=[])
        self.config.write_text(PRIMARY + "fallback_model: {provider: a, model: b}\n", encoding="utf-8")
        self.refused("not_editable", chain=[{"provider": "c", "model": "d"}])
        self.assertEqual(self.runs, [])
        self.assertEqual(self.config.read_text(encoding="utf-8"), PRIMARY + "fallback_model: {provider: a, model: b}\n")

    def test_an_unreadable_config_is_said_not_read_as_no_chain(self):
        self.config.write_text("model: [unclosed\n", encoding="utf-8")
        with self.assertRaises(ob.BridgeError) as cm:
            self.op("get")
        self.assertEqual(cm.exception.code, "unreadable")
        self.refused("unreadable", chain=[])
        self.assertEqual(self.runs, [])


class Peer(unittest.TestCase):
    def test_a_bot_on_another_computer_is_refused_with_the_reason(self):
        bridge = ob.Bridge(token="t", hermes_home=Path(tempfile.gettempdir()) / "omher-no-home")
        link = ob.PeerLink("mac", "Mac mini", "demo@host.example", "ws://127.0.0.1:1/?token=" + "0" * 32)
        link.rows = [{"name": "mini"}]
        bridge.peers["mac"] = link
        for op in ("fallback.get", "fallback.set"):
            with self.assertRaises(ob.BridgeError) as cm:
                asyncio.run(bridge._peer_op({"op": op, "bot": "mac:mini", "chain": []}))
            self.assertEqual(cm.exception.code, "remote_bot", op)
            self.assertIn("set on the computer it runs on", cm.exception.message)
            self.assertNotIn(op, ob.PEER_FORWARD)


class SwitchNotice(unittest.TestCase):
    def test_hermes_fallback_status_is_marked_and_other_status_is_not(self):
        bridge = ob.Bridge(token="t", hermes_home=Path(tempfile.gettempdir()) / "omher-no-home")
        conn = ob.Conn({"name": BOT, "path": Path("/nowhere"), "display_name": "Demo"})
        sent = []

        async def emit(c, chat, event, **fields):
            sent.append((event, fields))
        bridge._chat_emit = emit
        line = "⚠️ Model fallback: gpt-6.1-sol via openai could not respond (rate limited); using x via openrouter."
        asyncio.run(bridge._main_event(conn, "status.update", {}, {"kind": "fallback", "text": line}))
        asyncio.run(bridge._main_event(conn, "status.update", {}, {"kind": "lifecycle", "text": "Retrying (2/3)"}))
        self.assertEqual(sent, [("status", {"text": line, "fallback": True}), ("status", {"text": "Retrying (2/3)"})])


@unittest.skipUnless(ob.hermes_path(), "no hermes on this computer")
class RealHermes(unittest.TestCase):
    """The exact argv against the installed Hermes, in a temp Hermes home with a scratch profile: never a real one."""

    def test_hermes_stores_the_list_omher_sends(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            home = Path(tmp)
            profile = home / "profiles" / "scratch"
            profile.mkdir(parents=True)
            (home / "config.yaml").write_text("model:\n  default: claude-opus\n  provider: anthropic\n", encoding="utf-8")
            (profile / "config.yaml").write_text(PRIMARY + "# kept\nagent:\n  reasoning_effort: high\n", encoding="utf-8")
            chain = [{"provider": "openrouter", "model": "anthropic/claude-sonnet-4.5"}, {"provider": "ollama", "model": "qwen3:8b"}]
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(home)}):
                code, out = ob.run_hermes_fallback(ob.hermes_path(), "scratch", chain, home, 300.0)
                self.assertEqual(code, 0, out)
                self.assertEqual(ob.fallback_chain(profile), {"chain": chain, "editable": True})
                stored = ob._yaml_safe_load((profile / "config.yaml").read_text(encoding="utf-8"))
                self.assertEqual(stored["fallback_providers"], chain)
                self.assertEqual(stored["model"], {"default": "gpt-6.1-sol", "provider": "openai"})
                self.assertEqual(stored["agent"], {"reasoning_effort": "high"})
                code, out = ob.run_hermes_fallback(ob.hermes_path(), "scratch", [], home, 300.0)
                self.assertEqual(code, 0, out)
                self.assertEqual(ob.fallback_chain(profile), {"chain": [], "editable": True})
            # the root profile was not touched
            self.assertNotIn("fallback", (home / "config.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
