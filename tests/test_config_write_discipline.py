"""One discipline for every OMH write of Hermes' `config.yaml` (#1742).

OMH wrote this file from two families that did not know about each other. The
delegation route writer read, compared a file signature and replaced
atomically; `write_config` rewrote the whole file with no lock and no
compare, reached by `omh setup`, `omh theme`, `omh memory`, self-update and
`system/targets`. One of those could read the file, have a route land, and
write back its stale copy -- erasing the route, after which the restore
record saw a value it had not written and dropped the person's baseline as a
foreign edit.

These tests pin the discipline itself (compare, retry, refuse, atomic
replace, mode preserved), the shared lock, and the source-derived gate that
keeps a new call site from skipping it. Every test passes explicit temporary
homes; nothing here may read or write the developer's own `~/.hermes` or
`~/.omh`.
"""

from __future__ import annotations

import ast
import os
import threading
import time
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.system.local_store import atomic_replace_text  # noqa: E402
from omh.config_adapter import (  # noqa: E402
    ConfigChange,
    ConfigConcurrentUpdate,
    ConfigUnwritable,
    ConfigWriteRefused,
    ensure_external_dir,
    read_config,
    set_memory_provider,
    update_config,
)
from omh.plugin_bundle.omh import delegation_route_restore  # noqa: E402
from omh.plugin_bundle.omh.delegation_route_restore import (  # noqa: E402
    delegation_route_restore_path,
    route_write_lock,
    write_route_with_baseline,
)
from omh.plugin_bundle.omh.delegation_routing import (  # noqa: E402
    config_file_signature,
    read_config_snapshot,
    write_delegation_route,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"

BASE_CONFIG = "version: 1\nmemory:\n  limit: 5\n"


class _Home:
    """A temp Hermes home plus a temp OMH home, both named explicitly."""

    def __init__(self, root: Path) -> None:
        self.hermes = root / "hermes"
        self.omh = root / "omh"
        self.hermes.mkdir(parents=True, exist_ok=True)
        self.omh.mkdir(parents=True, exist_ok=True)
        self.config = self.hermes / "config.yaml"
        self.config.write_text(BASE_CONFIG, encoding="utf-8", newline="")


class UpdateConfigDisciplineTests(unittest.TestCase):
    def test_a_route_landing_between_the_read_and_the_write_is_not_erased(self) -> None:
        """The interleave the issue describes, driven from inside the mutation."""
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))
            landed: list[int] = []

            def _claim(text: str) -> ConfigChange:
                # First pass only: a route write lands after this writer has
                # read the file and before it replaces it.
                if not landed:
                    landed.append(1)
                    result = write_delegation_route(home.hermes, model="glm-5.3")
                    self.assertEqual(result["status"], "routed")
                return set_memory_provider(text, "omh")

            update = update_config(home.config, _claim, omh_home=home.omh)

            self.assertTrue(update.written)
            self.assertEqual(update.attempts, 2)
            final = read_config(home.config)
            # Neither update is lost: the retry re-derived the memory claim
            # from the file the route writer left behind.
            self.assertIn("  provider: omh", final)
            self.assertIn("delegation:", final)
            self.assertIn("model: 'glm-5.3'", final)

    def test_the_compare_is_load_bearing(self) -> None:
        """Mutation proof: with the compare stubbed out, the route is erased."""
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))

            def _claim(text: str) -> ConfigChange:
                if "delegation:" not in text:
                    write_delegation_route(home.hermes, model="glm-5.3")
                return set_memory_provider(text, "omh")

            # Neutralise exactly the compare and nothing else: the guard
            # is `config_file_signature(path) == signature`, so answering it
            # with the signature this attempt read makes it always true.
            seen: list[object] = []
            real_snapshot = read_config_snapshot

            def _recording_snapshot(path: Path):
                text, signature, error = real_snapshot(path)
                seen.append(signature)
                return text, signature, error

            with mock.patch(
                "omh.plugin_bundle.omh.delegation_routing.read_config_snapshot",
                _recording_snapshot,
            ), mock.patch(
                "omh.plugin_bundle.omh.delegation_routing.config_file_signature",
                lambda _path: seen[-1],
            ):
                update = update_config(home.config, _claim, omh_home=home.omh)

            self.assertEqual(update.attempts, 1)
            self.assertNotIn("delegation:", read_config(home.config))

    def test_the_compare_guards_this_writers_read_and_nothing_earlier(self) -> None:
        """The one thing it cannot do, pinned so nobody assumes otherwise.

        `update_config` protects the window between the text it hands the
        mutation and the replace. A mutation that IGNORES that text and
        returns bytes derived from some earlier read is writing a stale copy
        by construction, and no signature can tell: the file has not moved
        since this writer read it. That is why every call site was
        restructured so the decision happens inside the mutation, and why
        `MutationShapeGateTests` below refuses one that drops its argument.
        """
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))
            stale = read_config(home.config)
            write_delegation_route(home.hermes, model="glm-5.3")

            update = update_config(
                home.config,
                lambda _text: ConfigChange(True, "stale", stale),
                omh_home=home.omh,
            )

            self.assertTrue(update.written)
            self.assertNotIn("delegation:", read_config(home.config))

    def test_a_file_that_keeps_moving_refuses_rather_than_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))

            def _always_races(text: str) -> ConfigChange:
                home.config.write_text(text + f"# {os.urandom(4).hex()}\n", encoding="utf-8", newline="")
                return ensure_external_dir(text, "/tmp/omh/skills")

            with self.assertRaises(ConfigConcurrentUpdate) as caught:
                update_config(home.config, _always_races, omh_home=home.omh, attempts=3)

            self.assertIn("3 update attempts", str(caught.exception))
            self.assertNotIn("external_dirs", read_config(home.config))

    def test_a_mutation_that_changes_nothing_leaves_the_bytes_alone(self) -> None:
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))
            before = home.config.read_bytes()
            signature = config_file_signature(home.config)

            update = update_config(
                home.config,
                lambda text: ConfigChange(False, "nothing to do", text),
                omh_home=home.omh,
            )

            self.assertFalse(update.changed)
            self.assertFalse(update.written)
            self.assertEqual(home.config.read_bytes(), before)
            self.assertEqual(config_file_signature(home.config), signature)

    def test_dry_run_decides_without_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))
            before = home.config.read_bytes()

            update = update_config(
                home.config,
                lambda text: set_memory_provider(text, "omh"),
                omh_home=home.omh,
                dry_run=True,
            )

            self.assertTrue(update.changed)
            self.assertFalse(update.written)
            self.assertIn("  provider: omh", update.text)
            self.assertEqual(home.config.read_bytes(), before)

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_the_replacement_carries_the_destination_mode(self) -> None:
        """A rename installs the temp file's mode, which is this process's umask."""
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))
            home.config.chmod(0o600)

            update_config(home.config, lambda text: set_memory_provider(text, "omh"), omh_home=home.omh)

            self.assertEqual(home.config.stat().st_mode & 0o777, 0o600)

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_the_mode_is_read_before_the_guard_so_the_last_step_is_the_rename(self) -> None:
        """The guard-to-rename window has to be the rename and nothing else.

        The observable half of that ordering: the destination's mode is read
        before the temp file exists, so a destination that disappears later
        still hands its mode to the replacement. Doing the `stat` after the
        guard, as an earlier version did, would see `FileNotFoundError` and
        fall back to this process's umask — and would also put a `stat` and
        a `chmod` inside a window the docstring called one `os.replace`.
        """
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(BASE_CONFIG, encoding="utf-8", newline="")
            path.chmod(0o600)

            def _vanish() -> bool:
                path.unlink()
                return True

            self.assertTrue(atomic_replace_text(path, "replaced\n", guard=_vanish))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.read_text(encoding="utf-8"), "replaced\n")

    def test_a_timeout_from_the_mutation_is_not_relabelled_as_a_lock_timeout(self) -> None:
        """`FileLockTimeout` in this repo is a `TimeoutError`.

        Wrapping the whole loop in `except TimeoutError` therefore reported
        any future mutation that touches a locked store as a lock timeout on
        the config. The handler now covers the acquisition only.
        """
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))

            def _raises(_text: str) -> ConfigChange:
                raise TimeoutError("something else entirely")

            with self.assertRaises(TimeoutError) as caught:
                update_config(home.config, _raises, omh_home=home.omh)

            self.assertNotIsInstance(caught.exception, ConfigWriteRefused)
            self.assertEqual(str(caught.exception), "something else entirely")

    def test_a_symlinked_config_is_refused_rather_than_replaced_with_a_file(self) -> None:
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))
            real = home.hermes / "real-config.yaml"
            real.write_text(BASE_CONFIG, encoding="utf-8", newline="")
            home.config.unlink()
            home.config.symlink_to(real)

            # `ConfigUnwritable`, not `ConfigConcurrentUpdate`: nothing
            # raced here, and an exception that named a race would put a
            # cause in the log that did not happen.
            with self.assertRaises(ConfigUnwritable) as caught:
                update_config(home.config, lambda text: set_memory_provider(text, "omh"), omh_home=home.omh)

            self.assertIsInstance(caught.exception, ConfigWriteRefused)
            self.assertNotIsInstance(caught.exception, ConfigConcurrentUpdate)
            self.assertTrue(home.config.is_symlink())

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_an_unreadable_config_refuses_without_naming_a_race(self) -> None:
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))
            home.config.chmod(0o000)
            try:
                with self.assertRaises(ConfigUnwritable):
                    update_config(
                        home.config,
                        lambda text: set_memory_provider(text, "omh"),
                        omh_home=home.omh,
                    )
            finally:
                home.config.chmod(0o600)

    def test_a_cli_writer_waits_on_the_lock_a_route_write_holds(self) -> None:
        """The real route writer, not a stand-in holding the same path.

        An earlier version of this test took `route_write_lock` itself and
        then asserted `delegation_route_restore_path(...)` equalled the
        value it had assigned from that same call four lines earlier. That
        compares a value to itself and holds for any implementation, so the
        name was the only thing claiming the two families share a lock.
        Here the holder is `write_route_with_baseline`, stopped mid-write.
        """
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))
            entered = threading.Event()
            release = threading.Event()
            outcome: list[object] = []

            def _slow_route() -> None:
                # Wedge the real route writer inside its own lock by making
                # the write it performs block.
                original = delegation_route_restore.write_delegation_route

                def _blocking(*args: object, **kwargs: object) -> object:
                    entered.set()
                    release.wait(10)
                    return original(*args, **kwargs)

                # Patched where `write_route_with_baseline` looks it up: the
                # restore module binds the name at import time, so patching
                # the defining module would not reach it.
                with mock.patch.object(
                    delegation_route_restore, "write_delegation_route", _blocking
                ):
                    outcome.append(
                        write_route_with_baseline(home.hermes, omh_home=home.omh, model="glm-5.3")
                    )

            holder = threading.Thread(target=_slow_route)
            holder.start()
            try:
                self.assertTrue(entered.wait(10))
                with self.assertRaises(ConfigConcurrentUpdate) as caught:
                    update_config(
                        home.config,
                        lambda text: set_memory_provider(text, "omh"),
                        omh_home=home.omh,
                        attempts=1,
                    )
            finally:
                release.set()
                holder.join(10)

            self.assertIn("timed out waiting for the OMH config lock", str(caught.exception))
            # Named so a reader can see WHICH lock the CLI waited on.
            self.assertIn(
                delegation_route_restore_path(home.omh).name, str(caught.exception)
            )
            self.assertNotIn("provider: omh", read_config(home.config))
            self.assertEqual(outcome[0]["status"], "routed")  # type: ignore[index]

    def test_a_dry_run_takes_no_lock_and_leaves_the_omh_home_alone(self) -> None:
        """A preview writes nothing, so it must not create or wait on state.

        Taking the lock regardless made `--dry-run` create `routing/` and a
        lock file inside it, force that directory to 0700, and acquire a
        five-second wait plus a way to exit 2 — on a command whose contract
        is that it changes nothing.
        """
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))

            update = update_config(
                home.config,
                lambda text: set_memory_provider(text, "omh"),
                omh_home=home.omh,
                dry_run=True,
            )

            self.assertTrue(update.changed)
            self.assertFalse(update.written)
            # No `routing/`, no lock sidecar, no directory mode forced.
            self.assertEqual(sorted(entry.name for entry in home.omh.iterdir()), [])

        # And it does not wait on a lock somebody else is holding.
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))
            with route_write_lock(home.omh, timeout_seconds=0.05):
                started = time.monotonic()
                preview = update_config(
                    home.config,
                    lambda text: set_memory_provider(text, "omh"),
                    omh_home=home.omh,
                    dry_run=True,
                )
                waited = time.monotonic() - started

            self.assertTrue(preview.changed)
            self.assertFalse(preview.written)
            self.assertLess(waited, 1.0)

    def test_an_absent_omh_home_takes_no_lock_but_keeps_the_compare(self) -> None:
        with TemporaryDirectory() as tmp:
            home = _Home(Path(tmp))
            landed: list[int] = []

            def _claim(text: str) -> ConfigChange:
                if not landed:
                    landed.append(1)
                    write_delegation_route(home.hermes, model="glm-5.3")
                return set_memory_provider(text, "omh")

            update = update_config(
                home.config, _claim, omh_home=Path(tmp) / "never-created"
            )

            self.assertFalse(update.lock_enforced)
            self.assertEqual(update.attempts, 2)
            self.assertIn("delegation:", read_config(home.config))
            self.assertIn("  provider: omh", read_config(home.config))


class CallSiteGateTests(unittest.TestCase):
    """Re-derive every `config.yaml` writer in `src/` from source.

    A named list would go stale the moment somebody adds a command, which is
    how the two families got out of step in the first place. The subject is
    the source tree.
    """

    def _calls(self, name: str) -> list[str]:
        found: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                target = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if target == name:
                    found.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
        return found

    def test_no_module_writes_the_config_outside_update_config(self) -> None:
        writers = [site for site in self._calls("write_config") if "install/config_adapter.py" not in site]

        self.assertEqual(
            writers,
            [],
            "these call `write_config` directly and so skip the signature compare, "
            "the retry and the shared lock; route them through `update_config` "
            f"(#1742): {writers}",
        )

    def test_write_config_is_not_imported_under_another_name(self) -> None:
        """The gate above matches a call by name, so a rename would hide one."""
        aliased: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                for alias in node.names:
                    if alias.name == "write_config" and alias.asname:
                        aliased.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} as {alias.asname}")

        self.assertEqual(aliased, [], f"a renamed import hides the call from the gate above: {aliased}")

    def test_nothing_writes_the_hermes_config_path_a_level_lower(self) -> None:
        """`update_config` is only the discipline if it is the only way down.

        Routing every `write_config` call through it says nothing about a
        caller that skips that layer entirely and hands the config path to
        `atomic_write_text`, `Path.write_text` or `open`. Nothing in `src/`
        does today; this is the gate that keeps it that way, and it is the
        shape worth guarding, because the whole point is "no whole-file
        rewrite of this path without the compare".
        """
        lower = {"atomic_write_text", "write_text", "write_bytes", "open"}
        sites: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                func = node.func
                target = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if target not in lower:
                    continue
                destination = ast.unparse(func.value) if isinstance(func, ast.Attribute) else ast.unparse(node.args[0])
                if "hermes_config_path" in destination:
                    sites.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} -> {target}")

        self.assertEqual(
            sites,
            [],
            "these write the Hermes config below `update_config`, so they take "
            f"neither the compare nor the lock (#1742): {sites}",
        )

    def test_every_update_config_call_names_an_omh_home(self) -> None:
        """A call with no `omh_home` gets the compare but not the shared lock.

        `system/targets` is the one place that may pass None, and it does so
        on a branch: the config it writes can belong to a Hermes home this
        invocation is not bound to, whose OMH home it cannot name.
        """
        unnamed: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                target = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if target != "update_config":
                    continue
                if not any(keyword.arg == "omh_home" for keyword in node.keywords):
                    unnamed.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

        self.assertEqual(unnamed, [], f"these take the compare but not the shared lock: {unnamed}")


class MutationShapeGateTests(unittest.TestCase):
    """Every `update_config` mutation must at least NAME the text it is handed.

    Not a style rule. `update_config` can only detect a change between the
    text it read and the replace; a mutation that ignores that text and
    returns bytes derived from an earlier read writes a stale copy that no
    signature can catch, which is the exact defect #1742 describes. It was
    reintroduced while converting `cmd_uninstall`: the first attempt
    precomputed the new text outside and returned it from a
    `lambda _text: ...`, and it passed every other test in this file.

    What this gate proves and what it does not, stated because the
    difference matters. It proves the mutation's first parameter appears in
    its body, which is exactly the spelling that was reintroduced, and it
    proves the mutation is one this gate can read at all. It CANNOT prove
    the returned text derives from that parameter: a mutation that mentions
    its argument and still returns precomputed bytes is the same lost
    update and is syntactically indistinguishable from a correct one. That
    half is a review question, not a gate one.
    """

    def _mutations(self) -> list[tuple[str, ast.AST]]:
        found: list[tuple[str, ast.AST]] = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            functions = {
                node.name: node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                target = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if target != "update_config":
                    continue
                where = f"{path.relative_to(REPO_ROOT)}:{node.lineno}"
                # The mutation reaches `update_config` positionally or as
                # `mutate=`. Collecting only the positional form let a
                # keyword call skip both gates below without either of them
                # saying so.
                mutation = node.args[1] if len(node.args) >= 2 else next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "mutate"),
                    None,
                )
                if mutation is None:
                    found.append((where, ast.Pass()))
                    continue
                if isinstance(mutation, ast.Lambda):
                    found.append((where, mutation))
                elif isinstance(mutation, ast.Name) and mutation.id in functions:
                    found.append((where, functions[mutation.id]))
                else:
                    found.append((where, mutation))
        return found

    def test_every_call_site_passes_a_mutation_this_gate_can_read(self) -> None:
        unreadable = [
            where
            for where, node in self._mutations()
            if not isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        self.assertEqual(
            unreadable,
            [],
            "the mutation is missing, or is not an inline lambda or a function "
            "defined in the same module, so the gate below cannot check it: "
            f"{unreadable}",
        )

    def test_no_mutation_discards_the_text_it_was_handed(self) -> None:
        discarding: list[str] = []
        for where, node in self._mutations():
            if not isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            positional = node.args.posonlyargs + node.args.args
            if not positional:
                discarding.append(f"{where} (mutation takes no config text)")
                continue
            name = positional[0].arg
            body = node.body if isinstance(node.body, list) else [ast.Expr(node.body)]
            used = any(
                isinstance(inner, ast.Name) and inner.id == name
                for statement in body
                for inner in ast.walk(statement)
            )
            if not used:
                discarding.append(f"{where} (ignores `{name}`)")

        self.assertEqual(
            discarding,
            [],
            "a mutation that ignores the text `update_config` hands it writes a "
            "stale whole-file copy that the signature compare cannot detect, "
            f"because the file has not moved since this writer read it (#1742): {discarding}",
        )


if __name__ == "__main__":
    unittest.main()
