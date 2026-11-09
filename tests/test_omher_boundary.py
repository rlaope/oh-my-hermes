"""omher's boundary (docs/OMHER-BOUNDARY.md) pinned against the code: the doc's sentences, nothing in
``src/`` reaching ``apps/omher``, and the bridge submitting a prompt from exactly one place, with the
main chat's id."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "OMHER-BOUNDARY.md"
BRIDGE = ROOT / "apps" / "omher" / "bridge" / "omher_bridge.py"
CONTEXT = ROOT / "CONTEXT.md"
DOCS_INDEX = ROOT / "docs" / "README.md"

RULES = (
    "omher never patches Hermes.",
    "omher never writes to Slack, Discord or any other elsewhere session.",
    "omher sends, answers and interrupts only in the bot's main chat, the session titled `Bot Chat`;",
    "the bridge has exactly one `prompt.submit` call site and it takes the main chat's id.",
    "Files the person attaches go to that same chat only, as bytes through Hermes' own `image.attach_bytes`,",
    "the bridge never opens the person's files.",
    "omher talks only to the person's own Hermes gateway on this machine, over loopback,",
    "omher makes no LLM or API call itself. Every model call is Hermes'.",
    "The bridge listens on 127.0.0.1 only and refuses any connection that lacks the random token",
    "The app starts the bridge as a child process and stops it when the app exits.",
    "The Python `omh` package never imports omher, and nothing under `src/` refers to `apps/omher`.",
    "omher writes to a Hermes profile only its display name (`profile.yaml` `display_name`) and its picture",
    "omher shows a file from disk only when the bot named it in a `MEDIA:` line of its own answer,",
    "the desktop app opens only a file the bridge just served this way.",
)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class DocPins(unittest.TestCase):
    def test_boundary_doc_states_each_rule(self) -> None:
        text = _flat(DOC.read_text(encoding="utf-8"))
        for sentence in RULES:
            self.assertIn(_flat(sentence), text)

    def test_boundary_is_between_six_and_eleven_numbered_rules(self) -> None:
        rules = re.findall(r"^\d+\. ", DOC.read_text(encoding="utf-8"), re.M)
        self.assertTrue(6 <= len(rules) <= 11, len(rules))

    def test_glossary_and_docs_index_name_omher(self) -> None:
        context = CONTEXT.read_text(encoding="utf-8")
        self.assertIn("**omher**:", context)
        self.assertIn("**Elsewhere**:", context)
        self.assertIn("docs/OMHER-BOUNDARY.md", context)
        self.assertIn("(OMHER-BOUNDARY.md)", DOCS_INDEX.read_text(encoding="utf-8"))


class OmhNeverReachesOmher(unittest.TestCase):
    def test_no_file_under_src_imports_or_names_apps_omher(self) -> None:
        offenders = []
        for path in sorted((ROOT / "src").rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".md", ".json", ".toml", ".yaml", ".yml", ".js", ".ts"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "apps/omher" in text or "apps\\omher" in text:
                offenders.append(str(path.relative_to(ROOT)))
            if path.suffix == ".py":
                try:
                    tree = ast.parse(text)
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        names = [node.module or ""]
                    if any(n.split(".")[0] in {"omher", "omher_bridge"} for n in names):
                        offenders.append(f"{path.relative_to(ROOT)} imports {names}")
        self.assertEqual(offenders, [])


class BridgeSubmitsOnlyToTheMainChat(unittest.TestCase):
    def setUp(self) -> None:
        self.source = BRIDGE.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_exactly_one_prompt_submit_call_site(self) -> None:
        self.assertEqual(self.source.count("prompt.submit"), 1, "prompt.submit named more than once")
        sites = [
            n for n in ast.walk(self.tree)
            if isinstance(n, ast.Constant) and n.value == "prompt.submit"
        ]
        self.assertEqual(len(sites), 1)

    def test_that_call_takes_the_main_chat_id_variable(self) -> None:
        calls = []
        for fn in ast.walk(self.tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(fn):
                if isinstance(call, ast.Call) and any(
                    isinstance(a, ast.Constant) and a.value == "prompt.submit" for a in call.args
                ):
                    calls.append((fn, call))
        self.assertEqual(len(calls), 1)
        fn, call = calls[0]
        session = [k.value for k in call.keywords if k.arg == "session_id"]
        self.assertEqual(len(session), 1, "prompt.submit must pass session_id")
        self.assertIn(ast.unparse(session[0]), {"chat.runtime_id", "chat.session_id", "main_id", "runtime_id", "sid"})
        params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        self.assertNotIn("session_id", params, "the submitting function must not take a session id from its caller")

    def test_profile_writes_are_only_name_and_picture(self) -> None:
        """Every Hermes profile method the bridge names is a read, except set_asset (the avatar)."""
        names = {n.value for n in ast.walk(self.tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("profiles.")}
        self.assertTrue(names <= {"profiles.list", "profiles.set_asset"}, sorted(names))
        writes = {n.value for n in ast.walk(self.tree)
                  if isinstance(n, ast.Constant) and n.value in {"profiles.configure", "profiles.create", "profile.yaml"}}
        self.assertEqual(writes, {"profile.yaml"})  # named only by the display-name writer

    def test_media_read_checks_the_bots_own_messages_read_only(self) -> None:
        """`media.read` serves a path only after looking it up in state.db (opened with ``ro_uri``)."""
        fns = {n.name: n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef)}
        named = ast.unparse(fns["media_named"])
        self.assertIn("ro_uri(db)", named)
        self.assertIn("role = 'assistant'", named)
        self.assertIn("media_named(profile_dir, path)", ast.unparse(fns["read_media"]))
        lib = (ROOT / "apps" / "omher" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        self.assertIn("media_target(&path, |p| shell.bridge.served_media(p))", lib)

    def test_chat_attach_takes_the_main_chat_id_and_bytes_only(self) -> None:
        """Every Hermes attach call is made by `op_chat_attach`, with the main chat's id, and no path."""
        fns = {n.name: n for n in ast.walk(self.tree) if isinstance(n, ast.AsyncFunctionDef)}
        attach = fns["op_chat_attach"]
        body = ast.unparse(attach)
        self.assertIn("main = await self._main(conn)", body)
        self.assertIn("session_id=main", body)
        self.assertNotIn("path", body)
        self.assertNotIn("open(", body)
        for name in ("image.attach_bytes", "pdf.attach", "file.attach", "image.attach"):
            users = [f.name for f in fns.values() if any(isinstance(c, ast.Constant) and c.value == name for c in ast.walk(f))]
            self.assertEqual(users, [] if name == "image.attach" else ["op_chat_attach"], name)

    def test_bridge_has_no_http_or_llm_client(self) -> None:
        banned = {"requests", "httpx", "aiohttp", "urllib3", "openai", "anthropic", "urllib.request", "http.client"}
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        self.assertEqual(sorted(i for i in imported if i in banned or i.split(".")[0] in banned), [])


if __name__ == "__main__":
    unittest.main()
