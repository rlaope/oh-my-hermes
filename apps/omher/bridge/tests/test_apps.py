"""The Apps page (BOUNDARY rule 41): Hermes' MCP catalog read from its manifest files, each entry's state for one bot
from the bot's `mcp_servers` names and switches and a token file's stat, the bot's integration skills, and the three
fixed `hermes -p <bot> mcp install|login|remove <name>` argvs a press runs. Every test uses a temp Hermes home, a temp
catalog and a fake runner: no real profile, no real `hermes`."""
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
OAUTH = "manifest_version: 1\nname: {name}\ndescription: {name} issues and pages.\ntransport: {{type: http, url: https://mcp.example.org/mcp}}\nauth: {{type: oauth}}\n"
OPEN = "manifest_version: 1\nname: {name}\ndescription: {name} docs.\ntransport: {{type: http, url: https://mcp.example.org/mcp}}\n"
KEYED = ("manifest_version: 1\nname: {name}\ndescription: {name} with a key.\ntransport: {{type: http, url: https://mcp.example.org/mcp}}\n"
         "auth:\n  type: oauth\n  env:\n    - {{name: DEMO_CLIENT_ID, secret: false}}\n    - {{name: DEMO_SECRET}}\n"
         "    - {{name: DEMO_REGION, default: eu}}\n    - {{name: DEMO_OPTIONAL, required: false}}\n")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / "hermes"
        self.profile = self.home / "profiles" / BOT
        self.catalog = self.root / "checkout" / "optional-mcps"
        write(self.home / "config.yaml", "model: x\n")
        self.config("")
        for name, text in (("notion", OAUTH), ("deepwiki", OPEN), ("asana", KEYED)):
            write(self.catalog / name / "manifest.yaml", text.format(name=name))
        self._env = mock.patch.dict(os.environ, {"HERMES_OPTIONAL_MCPS": str(self.catalog),
                                                 "HERMES_BUNDLED_SKILLS": str(self.root / "checkout" / "skills"),
                                                 "HERMES_OPTIONAL_SKILLS": str(self.root / "checkout" / "optional-skills")})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self._tmp.cleanup()

    def config(self, servers: str, extra: str = "") -> None:
        write(self.profile / "config.yaml", "model: x\n" + (f"mcp_servers:\n{servers}" if servers else "") + extra)

    def token(self, name: str, body: str = "{}") -> None:
        write(self.profile / "mcp-tokens" / f"{name}.json", body)


class Catalog(Base):
    def test_reads_name_description_auth_and_what_install_asks(self):
        got = ob.read_mcp_catalog(self.catalog)
        self.assertEqual([e["name"] for e in got], ["asana", "deepwiki", "notion"])
        by = {e["name"]: e for e in got}
        self.assertEqual(by["notion"], {"name": "notion", "description": "notion issues and pages.", "auth": "oauth", "asks": [],
                                        "terminal": False})
        self.assertEqual(by["deepwiki"]["auth"], "none")
        # every required value Hermes prompts for: with no stdin its prompt answers "" (not the manifest's default),
        # so DEMO_REGION's default does not fill it; a non-secret one is never read from .env, so it needs a terminal
        self.assertEqual(by["asana"]["asks"], ["DEMO_CLIENT_ID", "DEMO_SECRET", "DEMO_REGION"])
        self.assertTrue(by["asana"]["terminal"])
        self.assertFalse(by["deepwiki"]["terminal"])
        # a secret alone may already be in the profile's .env: Connect can work, no terminal needed up front
        write(self.catalog / "keyonly" / "manifest.yaml", OPEN.format(name="keyonly") + "auth:\n  type: api_key\n  env:\n    - {name: MCP_KEYONLY_API_KEY}\n")
        key = next(e for e in ob.read_mcp_catalog(self.catalog) if e["name"] == "keyonly")
        self.assertEqual((key["asks"], key["terminal"]), (["MCP_KEYONLY_API_KEY"], False))
        # only those five keys leave the reader: no url, no transport, no oauth block
        for e in got:
            self.assertEqual(set(e), {"name", "description", "auth", "asks", "terminal"})

    def test_skips_what_hermes_would_not_list_or_omher_could_not_pass(self):
        bad = {
            "dash": OAUTH.format(name="-h"),                         # would read as an option
            "space": OAUTH.format(name="a b"),
            "semi": OAUTH.format(name="x;rm"),
            "future": OAUTH.format(name="future").replace("manifest_version: 1", "manifest_version: 2"),
            "nodesc": "manifest_version: 1\nname: nodesc\n",
            "authkind": OAUTH.format(name="authkind").replace("type: oauth", "type: magic"),
            "dup": OAUTH.format(name="notion"),                       # a repeated name: the first folder wins
            "list": "- a\n- b\n",
        }
        for folder, text in bad.items():
            write(self.catalog / folder / "manifest.yaml", text)
        write(self.catalog / "big" / "manifest.yaml", OAUTH.format(name="big") + "#" * ob.MCP_MANIFEST_MAX)
        real = write(self.root / "elsewhere.yaml", OAUTH.format(name="linked"))
        outside = write(self.root / "outside" / "manifest.yaml", OAUTH.format(name="linkdir")).parent
        (self.catalog / "linked").mkdir()
        try:
            (self.catalog / "linked" / "manifest.yaml").symlink_to(real)
            (self.catalog / "linkdir").symlink_to(outside, target_is_directory=True)
        except OSError:  # Windows without the privilege: the link cases are not built there
            pass
        names = [e["name"] for e in ob.read_mcp_catalog(self.catalog)]
        self.assertEqual(names, ["asana", "deepwiki", "notion"])

    def test_no_folder_is_none_and_a_crlf_manifest_reads(self):
        self.assertIsNone(ob.read_mcp_catalog(self.root / "missing"))
        (self.catalog / "crlf" / "manifest.yaml").parent.mkdir()
        (self.catalog / "crlf" / "manifest.yaml").write_bytes(b"\xef\xbb\xbf" + OPEN.format(name="crlf").replace("\n", "\r\n").encode())
        self.assertIn("crlf", [e["name"] for e in ob.read_mcp_catalog(self.catalog)])

    def test_the_folder_follows_hermes_own_override(self):
        self.assertEqual(ob._hermes_dir("HERMES_OPTIONAL_MCPS", "optional-mcps", Path("/r"), {}), Path("/r/optional-mcps"))
        self.assertEqual(ob._hermes_dir("HERMES_OPTIONAL_MCPS", "optional-mcps", Path("/r"), {"HERMES_OPTIONAL_MCPS": " /nix/mcps "}),
                         Path("/nix/mcps"))


class States(Base):
    def states(self) -> dict:
        return {a["name"]: a["state"] for a in ob.read_apps(self.profile)["apps"]}

    def test_available_installed_needs_signin_and_disabled(self):
        self.assertEqual(self.states(), {"asana": "available", "deepwiki": "available", "notion": "available"})
        self.config("  notion: {url: https://mcp.example.org/mcp, auth: oauth}\n  deepwiki: {url: https://x}\n"
                    "  asana: {url: https://x, enabled: false}\n")
        self.assertEqual(self.states(), {"asana": "disabled", "deepwiki": "installed", "notion": "needs_signin"})
        self.token("notion")
        self.assertEqual(self.states()["notion"], "installed")
        # the legacy `disabled: true` wins over `enabled`, as Hermes' mcp_server_enabled reads it
        self.config("  deepwiki: {url: https://x, enabled: true, disabled: true}\n")
        self.assertEqual(self.states()["deepwiki"], "disabled")
        self.config("  deepwiki: {url: https://x, disabled: maybe}\n")
        self.assertEqual(self.states()["deepwiki"], "unknown")

    def test_switches_read_as_hermes_reads_them_and_anything_else_is_unknown(self):
        # Hermes: its YAML 1.1 loader, then _parse_boolish (a bool or number as itself, true/1/yes/on and
        # false/0/no/off in any case); any other value Hermes takes as its default with a warning: omher says unknown
        cases = {"false": "disabled", "False": "disabled", "off": "disabled", "no": "disabled", "0": "disabled",
                 "0.0": "disabled", "'false'": "disabled", "'FALSE'": "disabled", "'0'": "disabled", "'Off'": "disabled",
                 "FaLsE": "disabled", "true": "installed", "1": "installed", "2": "installed", "'yes'": "installed",
                 "TrUe": "installed", "~": "installed", "": "installed", "maybe": "unknown", "'maybe'": "unknown",
                 "[a]": "unknown", "{a: 1}": "unknown"}
        for word, want in cases.items():
            self.config(f"  deepwiki:\n    url: https://x\n    enabled: {word}\n")
            self.assertEqual(self.states()["deepwiki"], want, f"enabled: {word}")
        for word, want in {"1": "disabled", "'true'": "disabled", "yes": "disabled", "TRUE": "disabled", "0": "installed",
                           "no": "installed", "'off'": "installed", "huh": "unknown"}.items():
            self.config(f"  deepwiki:\n    url: https://x\n    disabled: {word}\n")
            self.assertEqual(self.states()["deepwiki"], want, f"disabled: {word}")

    def test_the_switch_words_match_hermes_own_parse(self):
        self.assertEqual([ob.mcp_switch(v, True) for v in ("y", "N", "on", "0", "1_0", "-1", ".5", "", "null")],
                         [True, False, True, False, True, True, True, None, None])
        self.assertEqual(ob.mcp_switch("y", True, ruamel=False), "?")           # PyYAML: a plain y is the string "y"
        self.assertEqual([ob.mcp_switch(v, False) for v in ("1", " YES ", "off", "", "y")], [True, True, False, "?", "?"])

    def test_a_config_that_does_not_parse_is_unknown_never_installed(self):
        write(self.profile / "config.yaml", "mcp_servers: {notion: {enabled: false}\n")
        self.assertEqual(set(self.states().values()), {"unknown"})

    def test_no_catalog_says_so(self):
        os.environ["HERMES_OPTIONAL_MCPS"] = str(self.root / "missing")
        got = ob.read_apps(self.profile)
        self.assertEqual((got["catalog"], got["apps"]), (False, []))

    def test_a_device_code_sign_in_is_read_from_the_bots_own_config_and_nothing_else_of_oauth(self):
        fake = "client-" + "S" * 24
        self.config(f"  notion:\n    url: https://mcp.example.org/mcp\n    auth: oauth\n    oauth:\n      client_secret: {fake}\n"
                    f"      flow: device\n  linear:\n    url: https://x\n    oauth: {{flow: browser}}\n"
                    f"  figma:\n    url: https://x\n    oauth: {{flow: magic}}\n  sentry:\n    url: https://x\n    flow: device\n")
        servers = ob.mcp_server_names(self.profile / "config.yaml", ob.MCP_KEYS)
        self.assertEqual(servers, {"notion": {"oauth.flow": "device"}, "linear": {"oauth.flow": "browser"},
                                   "figma": {"oauth.flow": "?"}, "sentry": {}})
        self.assertNotIn(fake, repr(servers))
        got = {a["name"]: a["device"] for a in ob.read_apps(self.profile)["apps"]}
        self.assertEqual(got["notion"], True)
        self.assertEqual((got["asana"], got["deepwiki"]), (False, False))
        # the Linear source asks for `enabled` only: `oauth` is never followed for it
        self.assertEqual(ob.mcp_server_names(self.profile / "config.yaml"), {"notion": {}, "linear": {}, "figma": {}, "sentry": {}})

    def test_no_server_value_and_no_token_byte_is_returned(self):
        fake = "glpat-" + "Z" * 24
        self.config(f"  notion:\n    url: https://mcp.example.org/mcp?t={fake}\n    headers: {{Authorization: Bearer {fake}}}\n"
                    f"    env: {{K: {fake}}}\n    auth: oauth\n")
        self.token("notion", '{"access_token": "%s"}' % fake)
        # every op's bot lookup already parses the config whole (`discover_bots`); the Apps read adds nothing to that
        ob._YAML_CACHE.clear()
        ob.discover_bots(self.home)
        before = repr(ob._YAML_CACHE)
        got = ob.read_apps(self.profile)
        self.assertNotIn(fake, repr(got))
        self.assertEqual(got["apps"][-1], {"name": "notion", "description": "notion issues and pages.", "auth": "oauth",
                                           "asks": [], "terminal": False, "state": "installed", "device": False})
        self.assertEqual(repr(ob._YAML_CACHE), before)

    def test_the_token_file_name_is_hermes_safe_name(self):
        self.assertEqual(ob.mcp_token_file(self.profile, "hugging_face").name, "hugging_face.json")
        self.assertEqual(ob.mcp_token_file(self.profile, "_x-").name, "x-.json")


class Skills(Base):
    def test_installed_disabled_available_and_left_out(self):
        write(self.profile / "skills" / "productivity" / "google-workspace" / "SKILL.md",
              "---\nname: google-workspace\ndescription: Gmail and Calendar.\n---\n")
        write(self.profile / "skills" / "note-taking" / "obsidian" / "SKILL.md", "---\nname: obsidian\ndescription: Vault.\n---\n")
        write(self.root / "checkout" / "skills" / "email" / "himalaya" / "SKILL.md", "---\nname: himalaya\ndescription: IMAP.\n---\n")
        write(self.root / "checkout" / "optional-skills" / "productivity" / "box" / "SKILL.md", "---\nname: box\ndescription: Box files.\n---\n")
        for disabled in ("\nskills:\n  disabled: [obsidian]\n", "\nskills:\n  disabled: \"['obsidian']\"\n", "\nskills:\n  disabled: obsidian\n"):
            self.config("", disabled)
            got = {s["name"]: s["state"] for s in ob.read_apps(self.profile)["skills"]}
            self.assertEqual(got, {"google-workspace": "installed", "obsidian": "disabled", "himalaya": "available", "box": "available"},
                             disabled)


class Argv(unittest.TestCase):
    def test_three_fixed_argvs(self):
        for verb in ("install", "login", "remove"):
            self.assertEqual(ob.mcp_argv("/h/hermes", BOT, verb, "notion"), ["/h/hermes", "-p", BOT, "mcp", verb, "notion"])

    def test_refuses_any_other_verb_profile_or_name(self):
        for verb in ("add", "test", "configure", "reauth", "catalog", "list", "picker", "", "install --all"):
            with self.assertRaises(ValueError, msg=verb):
                ob.mcp_argv("hermes", BOT, verb, "notion")
        for bot in ("Kami", "a b", "x;y", "../x", "--all", "-p", "", "a" * 65, None):
            with self.assertRaises(ValueError, msg=bot):
                ob.mcp_argv("hermes", bot, "install", "notion")
        for name in ("-h", "--help", "x;rm -rf ~", "a b", "$(id)", "`id`", "x|y", "x&y", "x/y", "official/notion",
                     "../x", "x\ny", "", "a" * 65, None):
            with self.assertRaises(ValueError, msg=name):
                ob.mcp_argv("hermes", BOT, "install", name)

    def fake_popen(self, seen: dict, code=0, said=b"ok\n", hang=False):
        test = self

        class Proc:
            pid = 4242

            def __init__(self, argv, **kw):
                seen.update(argv=argv, **kw)
                kw["stdout"].write(said)
                self.waits = seen.setdefault("waits", [])

            def wait(self, timeout=None):
                self.waits.append(timeout)
                if hang and len(self.waits) == 1:
                    raise subprocess.TimeoutExpired("hermes", timeout)
                return None if hang else code

            def kill(self):
                seen["killed"] = True

        del test
        return Proc

    def test_one_run_no_shell_nothing_on_stdin_and_the_root_as_home(self):
        seen: dict = {}
        with mock.patch.object(ob.subprocess, "Popen", self.fake_popen(seen)), mock.patch.dict(os.environ, {"_HERMES_GATEWAY": "1"}):
            self.assertEqual(ob.run_hermes_mcp("/h/hermes", BOT, "login", "notion", Path("/home/h"), 330.0), (0, "ok\n"))
        self.assertEqual(seen["argv"], ["/h/hermes", "-p", BOT, "mcp", "login", "notion"])
        self.assertIs(seen["stdin"], subprocess.DEVNULL)
        self.assertNotIn("shell", seen)
        self.assertEqual(seen["waits"], [330.0])
        # the home as the system writes the path (`\\home\\h` on Windows)
        self.assertEqual((seen["env"]["HERMES_HOME"], seen["env"]["PYTHONIOENCODING"]), (str(Path("/home/h")), "utf-8"))
        self.assertNotIn("_HERMES_GATEWAY", seen["env"])
        # its own session (POSIX) or process group (Windows), so a stop reaches only this run
        if os.name == "nt":
            self.assertEqual(seen["creationflags"] & 0x00000200, 0x00000200)
        else:
            self.assertIs(seen["start_new_session"], True)
        # output to a file, never a pipe a leftover helper could hold open
        self.assertNotEqual(seen["stdout"], subprocess.PIPE)

    def test_a_run_past_its_time_is_stopped_with_its_group_and_the_wait_after_is_bounded(self):
        seen: dict = {}
        killed = []
        with mock.patch.object(ob.subprocess, "Popen", self.fake_popen(seen, said=b"  Open https://example.org/a\n", hang=True)), \
                mock.patch.object(ob.os, "killpg", lambda pid, sig: killed.append((pid, sig)), create=True):
            code, out = ob.run_hermes_mcp("/h/hermes", BOT, "login", "notion", Path("/h"), 2.0)
        self.assertEqual((code, out), (None, "  Open https://example.org/a\n"))  # what Hermes said so far is kept
        self.assertEqual(seen["waits"], [2.0, ob.MCP_STOP_WAIT])
        if os.name == "nt":
            self.assertTrue(seen.get("killed"))
        else:
            self.assertEqual(killed, [(4242, ob.signal.SIGKILL)])

    def test_the_end_of_a_long_output_is_kept(self):
        # Hermes' error line comes last: a run that printed more than the cap keeps its tail, not its head
        seen: dict = {}
        said = b"noise line\n" * (ob.MCP_OUTPUT_MAX // 8) + "  ✗ install failed: the end\n".encode()
        with mock.patch.object(ob.subprocess, "Popen", self.fake_popen(seen, said=said)):
            code, out = ob.run_hermes_mcp("/h/hermes", BOT, "install", "notion", Path("/h"), 1.0)
        self.assertEqual(code, 0)
        self.assertLessEqual(len(out.encode()), ob.MCP_OUTPUT_MAX)
        self.assertTrue(out.endswith("✗ install failed: the end\n"))
        self.assertEqual(ob.hermes_said(out), "✗ install failed: the end")

    def test_a_program_that_cannot_start(self):
        def missing(argv, **kw):
            raise FileNotFoundError(2, "No such file", argv[0])

        with mock.patch.object(ob.subprocess, "Popen", missing):
            code, out = ob.run_hermes_mcp("/h/hermes", BOT, "install", "notion", Path("/h"), 1.0)
        self.assertEqual(code, -1)
        self.assertIn("Hermes could not be started", out)

    def test_hermes_own_words_trimmed(self):
        out = "\x1b[36m  Installing MCP 'asana'\x1b[0m\n\n  Configure credentials:\n  DEMO_SECRET: \n" \
              "\x1b[31m  ✗ install failed: DEMO_SECRET is required but no value was provided\x1b[0m\n"
        self.assertEqual(ob.hermes_said(out), "✗ install failed: DEMO_SECRET is required but no value was provided")
        # no error line: the last line is always there (here a traceback's), and an update note from Hermes' start-up
        # is left out while a warning about this run stays
        crash = ("  ⚠ A newer Hermes is available: run `hermes update`\n  ⚠ Server responded slowly\nTraceback (most recent call last):\n"
                 '  File "x.py", line 1, in <module>\nRuntimeError: callback port 27890 is in use\n')
        self.assertEqual(ob.hermes_said(crash), "⚠ Server responded slowly\nRuntimeError: callback port 27890 is in use")
        self.assertEqual(ob.hermes_said("  ⚠ Could not check for an interrupted `hermes update`: x\n  ✗ Authentication failed: denied\n"),
                         "✗ Authentication failed: denied")
        self.assertEqual(ob.hermes_said("\r\n".join(f"line {i}" for i in range(20))), "line 19")
        self.assertLessEqual(len(ob.hermes_said("✗ " + "x" * 5000)), 800)
        self.assertEqual(ob.hermes_said(""), "")


class Ops(Base):
    def setUp(self) -> None:
        super().setUp()
        self.bridge = ob.Bridge(token="t", hermes_home=self.home)
        self.runs: list[tuple] = []
        self.effect = lambda verb, name: (0, "")
        self._run = mock.patch.object(ob, "run_hermes_mcp", self.fake)
        self._path = mock.patch.object(ob, "hermes_path", lambda *a, **k: "/stub/hermes")
        self._run.start()
        self._path.start()

    def tearDown(self) -> None:
        self._path.stop()
        self._run.stop()
        super().tearDown()

    def fake(self, hermes, bot, verb, name, home, timeout):
        self.runs.append((hermes, bot, verb, name, Path(home), timeout))
        return self.effect(verb, name)

    def op(self, verb: str, **p):
        return asyncio.run(getattr(self.bridge, f"op_apps_{verb}")({"bot": BOT, **p}))

    def refused(self, verb: str, code: str, **p) -> None:
        with self.assertRaises(ob.BridgeError) as cm:
            self.op(verb, **p)
        self.assertEqual(cm.exception.code, code, cm.exception.message)

    def test_list(self):
        got = self.op("list")
        self.assertTrue(got["catalog"])
        self.assertEqual([a["name"] for a in got["apps"]], ["asana", "deepwiki", "notion"])
        self.assertEqual(self.runs, [])

    def test_install_runs_the_fixed_argv_and_reads_the_result_back(self):
        def effect(verb, name):
            self.config(f"  {name}: {{url: https://mcp.example.org/mcp, auth: oauth, enabled: true}}\n")
            return 0, "  ✓ Installed 'notion' (enabled).\n"
        self.effect = effect
        self.assertEqual(self.op("install", name="notion"), {"outcome": "ok", "state": "needs_signin"})
        self.assertEqual(self.runs, [("/stub/hermes", BOT, "install", "notion", self.home, ob.MCP_TIMEOUT["install"])])

    def test_a_refused_install_shows_hermes_own_text(self):
        self.effect = lambda verb, name: (1, "  Configure credentials:\n  ✗ install failed: DEMO_SECRET is required but no value was provided\n")
        got = self.op("install", name="asana")
        self.assertEqual(got, {"outcome": "failed", "state": "available",
                               "line": "✗ install failed: DEMO_SECRET is required but no value was provided"})

    def test_connect_is_refused_for_a_server_already_there_or_an_unreadable_config(self):
        # Hermes' install replaces the whole block and turns it on: a turned-off or hand-made server is never touched
        for block in ("  notion: {url: https://custom.example.org/mcp, enabled: false}\n", "  notion: {url: https://x}\n"):
            self.config(block)
            self.refused("install", "exists", name="notion")
        write(self.profile / "config.yaml", "mcp_servers: {notion: {enabled: false}\n")
        self.refused("install", "bad_request", name="deepwiki")
        self.assertEqual(self.runs, [])

    def test_sign_in_is_refused_for_a_device_code_server(self):
        self.config("  notion:\n    url: https://mcp.example.org/mcp\n    auth: oauth\n    oauth: {flow: device}\n")
        with self.assertRaises(ob.BridgeError) as cm:
            self.op("login", name="notion")
        self.assertEqual(cm.exception.code, "bad_request")
        self.assertIn(f"hermes -p {BOT} mcp login notion", cm.exception.message)
        self.assertEqual(self.runs, [])
        # Remove still works for it
        self.effect = lambda verb, name: (self.config(""), (0, ""))[1]
        self.assertEqual(self.op("remove", name="notion")["outcome"], "ok")

    def test_refusals_run_nothing(self):
        self.refused("install", "not_found", name="linear")                # not in the catalog read just now
        for bad in ("x;rm -rf ~", "-h", "$(id)", "a b", "official/notion", "", None, 7, ["notion"]):
            self.refused("install", "bad_request", name=bad)
        self.refused("login", "not_found", name="notion")                  # not installed on this bot
        self.refused("remove", "not_found", name="notion")
        self.config("  deepwiki: {url: https://x}\n")
        self.refused("login", "bad_request", name="deepwiki")              # no OAuth sign-in for that entry
        with self.assertRaises(ob.BridgeError) as cm:
            asyncio.run(self.bridge.op_apps_install({"bot": "nobody", "name": "notion"}))
        self.assertEqual(cm.exception.code, "unknown_bot")
        write(self.home / "profiles" / "Bad.Name" / "config.yaml", "model: x\n")   # a folder Hermes' id grammar refuses
        with self.assertRaises(ob.BridgeError) as cm:
            asyncio.run(self.bridge.op_apps_install({"bot": "Bad.Name", "name": "notion"}))
        self.assertEqual(cm.exception.code, "bad_request")
        self.assertEqual(self.runs, [])

    def test_login_is_ok_only_when_a_new_token_file_lands(self):
        self.config("  notion: {url: https://mcp.example.org/mcp, auth: oauth}\n")
        self.effect = lambda verb, name: (0, "  ⚠ Server responded, but no OAuth token was obtained — authentication did not complete.\n")
        got = self.op("login", name="notion")
        self.assertEqual((got["outcome"], got["state"]), ("failed", "needs_signin"))
        self.assertIn("no OAuth token was obtained", got["line"])

        def signed(verb, name):
            self.token(name, '{"t": 1}')
            return 0, "  ✓ Authenticated — 12 tool(s) available\n"
        self.effect = signed
        self.assertEqual(self.op("login", name="notion"), {"outcome": "ok", "state": "installed"})
        self.assertEqual(self.runs[-1][2:4], ("login", "notion"))
        self.assertEqual(self.runs[-1][5], ob.MCP_TIMEOUT["login"])
        # Sign in again when the old token stays as it was: Hermes' text, not ok
        self.effect = lambda verb, name: (0, "  ✗ Authentication failed: access_denied\n")
        got = self.op("login", name="notion")
        self.assertEqual((got["outcome"], got["line"]), ("failed", "✗ Authentication failed: access_denied"))

    def test_remove_is_ok_only_when_the_server_is_gone(self):
        self.config("  notion: {url: https://mcp.example.org/mcp, auth: oauth}\n")
        self.effect = lambda verb, name: (0, "  Cancelled.\n")
        self.assertEqual(self.op("remove", name="notion")["outcome"], "failed")

        def gone(verb, name):
            self.config("")
            return 0, "  ✓ Removed 'notion' from config\n"
        self.effect = gone
        self.assertEqual(self.op("remove", name="notion"), {"outcome": "ok", "state": "available"})

    def test_a_run_that_does_not_finish_says_so(self):
        self.effect = lambda verb, name: (None, "")
        got = self.op("install", name="notion")
        self.assertEqual(got["line"], f"Hermes did not finish in {int(ob.MCP_TIMEOUT['install'])} seconds.")
        # a sign-in that ran out of time still shows what Hermes printed (the address it could not open, say)
        self.config("  notion: {url: https://mcp.example.org/mcp, auth: oauth}\n")
        self.effect = lambda verb, name: (None, "  Open this address to sign in: https://example.org/authorize?x=1\n")
        got = self.op("login", name="notion")
        self.assertEqual(got["line"], f"Hermes did not finish in {int(ob.MCP_TIMEOUT['login'])} seconds.\n"
                                      "Open this address to sign in: https://example.org/authorize?x=1")

    def test_without_hermes_nothing_runs(self):
        with mock.patch.object(ob, "hermes_path", lambda *a, **k: None):
            got = self.op("install", name="notion")
        self.assertEqual((got["outcome"], got["line"]), ("failed", "Hermes is not on this computer."))
        self.assertEqual(self.runs, [])

    def test_one_run_at_a_time_per_bot(self):
        self.bridge._apps_busy.add(BOT)
        self.refused("install", "busy", name="notion")
        self.assertEqual(self.runs, [])


if __name__ == "__main__":
    unittest.main()
