"""Enforcement invariants for the handoff safety contract (issue #818).

The handoff safety contract says omh prepares work and never performs it: no
hidden dispatch, no network client, no remote mutation, no raw prompt on disk,
no merge authority. Prose says that. `docs/ARCHITECTURE.md` says that. Nothing
in the suite made it *false-able* -- a single import in a single module could
have quietly retired any of those claims and every existing test would still
have been green.

This module turns each claim into a gate. Two of them are new coverage, three
of them are regression prevention, and the difference is stated honestly per
invariant rather than blurred into "safety tests":

    INVARIANT 1  no hidden process spawn      GENUINE NEW COVERAGE
    INVARIANT 2  no network client in src/    GENUINE NEW COVERAGE
    INVARIANT 3  no remote mutation           REGRESSION PREVENTION
    INVARIANT 4  no raw prompt under .omh     GENUINE NEW COVERAGE
    INVARIANT 5  merge authority unreachable  REGRESSION PREVENTION

"Regression prevention" means exactly what it says: no such capability exists
in this repo today, so invariants 3 and 5 prove nothing new about the current
tree. They exist so one cannot appear unnoticed. Invariants 1, 2, and 4 have no
equivalent assertion anywhere in the suite: today the repo asserts a
`raw_prompt_stored: False` *flag* on several individual record families, but no
test has ever driven a real message through the delegation lane and then looked
at what actually landed on disk.

Method. The three static invariants read `src/` as an abstract syntax tree, not
as text. A comment mentioning `subprocess`, a docstring quoting `git push`, or
a detector regex naming `urllib.request` are all just string or comment tokens;
they can neither satisfy nor break a gate that only ever inspects import
statements, call sites, and argv literals. That property is what makes these
invariants worth having -- a `grep`-shaped gate would be defeated by rewording
a comment and would fire on documentation.

Determinism. Nothing here reads the network, the operator's home directory, the
wall clock, or any state outside the repository and a `TemporaryDirectory`. The
static invariants are pure functions of the checked-in tree. The one behavioural
invariant (4) drives the public CLI against a temporary OMH home.

Allowlists are the escape hatch and they are deliberate. Each entry names the
file and states why that file is permitted to hold the capability. Adding an
entry is a decision someone has to write down; that is the point.
"""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
import os
import re
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.coding.action_gate import (  # noqa: E402
    MUTATING_ACTIONS,
    build_task_authority_envelope,
    permission_profile_for,
    permission_profiles,
    required_actions_for,
)
from omh.coding.coding_delegation import DELEGATION_ACTIONS  # noqa: E402
from omh.coding.executors import WORK_OWNER_MODES  # noqa: E402
from omh.install.self_update_platform import (  # noqa: E402
    JUNCTION_LINK_ENV,
    JUNCTION_TARGET_ENV,
    JUNCTION_TIMEOUT_SECONDS,
    SelfUpdatePlatform,
    WINDOWS_JUNCTION_COMMAND,
)
from omh.plugin_bundle.omh.tools.evidence_tool import _DEFAULT_ALLOWLIST  # noqa: E402
from omh.skills.catalog_types import CODING_INTENTS  # noqa: E402
from omh.workflows.goal_loop import build_authority_envelope  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
THIS_TEST = "tests/test_handoff_safety_contract_enforcement.py"

# Parsing 476 modules five times over is wasted work; parse once per process.
_SOURCE_MODULES: list[tuple[str, ast.Module]] = []


def _source_modules() -> list[tuple[str, ast.Module]]:
    """Every module under `src/`, as (repo-relative posix path, parsed tree).

    Paths are `as_posix()` so allowlist keys compare equal on Windows CI, where
    `Path.relative_to` would otherwise yield backslash-separated strings.
    """
    if not _SOURCE_MODULES:
        for path in sorted(SOURCE_ROOT.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            _SOURCE_MODULES.append((path.relative_to(REPO_ROOT).as_posix(), tree))
    return _SOURCE_MODULES


def _imported_modules(tree: ast.Module) -> list[tuple[str, tuple[str, ...], int]]:
    """(module, imported names, lineno) for every import at every scope.

    `ast.walk` is used rather than iterating `tree.body` because a function-local
    import is still an import: `src/commands/coding.py` imports `subprocess`
    inside `cmd_coding_fanout_dispatch`, and a gate that only read module level
    would have missed it.
    """
    found: list[tuple[str, tuple[str, ...], int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, (), node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # A relative import (`from .foo import bar`) has level > 0 and is
            # always in-repo, never a stdlib or third-party capability.
            if node.level:
                continue
            module = node.module or ""
            found.append((module, tuple(alias.name for alias in node.names), node.lineno))
    return found


# --------------------------------------------------------------------------
# INVARIANT 1 -- no hidden process spawn
# --------------------------------------------------------------------------

# Verified against the tree, not copied from the issue: an AST sweep for
# `subprocess` imports at any scope returns exactly these modules. Each
# is reachable only from an explicit operator command; none sits on the chat or
# handoff-preparation path.
PROCESS_SPAWN_ALLOWLIST: dict[str, str] = {
    "src/coding/fanout_dispatch.py": (
        "`omh coding fanout dispatch` -- the one opt-in bridge that spawns local agent CLIs, "
        "documented as the scoped exception in CLAUDE.md."
    ),
    "src/coding/fanout_confinement.py": (
        "`omh coding fanout dispatch`; runs only the same-backend `/bin/sh` filesystem-refusal "
        "probe before the opt-in fanout owner or verification process is sandboxed."
    ),
    "src/coding/diagnostic_execution_engine.py": (
        "`omh coding fanout dispatch --diagnostics`; imports only subprocess exception classes "
        "to classify an injected or built-in runner's bounded failure and contains no "
        "process-spawn call of its own."
    ),
    "src/coding/local_diagnostic_engine.py": (
        "repository-owned adapter reached only after explicit `omh coding fanout dispatch "
        "--diagnostics`; runs bounded local read-only Git revision/status/diff probes before "
        "the allowlisted provider bridge and starts no executor or network client."
    ),
    "src/coding/local_diagnostic_process.py": (
        "provider bridge reached only after explicit `omh coding fanout dispatch --diagnostics`; "
        "materializes/removes detached fixed-revision worktrees and starts only the closed local "
        "pyright/basedpyright/ruff command map with bounded output, time, and environment."
    ),
    "src/coding/local_diagnostic_process_owner.py": (
        "private lifecycle boundary reached only by the explicit `omh coding fanout dispatch "
        "--diagnostics` provider bridge; starts the same closed provider argv suspended on "
        "Windows, binds it to a kill-on-close Job Object, then resumes it."
    ),
    "src/coding/final_review_worktree.py": (
        "explicit `omh coding fanout dispatch --final-review`; creates/removes disposable "
        "detached review worktrees and runs only bounded local Git identity/status probes."
    ),
    "src/coding/final_review_local_engine.py": (
        "explicit `omh coding fanout dispatch --final-review`; imports only SubprocessError to "
        "classify failures from the disposable worktree boundary and spawns no process itself."
    ),
    "src/coding/paired_run_local_worktrees.py": (
        "`omh coding paired-run dispatch --confirm-dispatch`; imports only SubprocessError to "
        "convert a timed-out local git worktree command into a per-cell failure with cleanup "
        "evidence, while all process spawning stays in the existing sanctioned bridge."
    ),
    "src/coding/worktree_creator.py": (
        "`git worktree add` for isolated executor workspaces; local, non-remote (see INVARIANT 3)."
    ),
    "src/coding/fanout_artifact_sharing.py": (
        "reached only from `_dispatch_unit` inside the `omh coding fanout dispatch` bridge above, "
        "right after `ensure_fanout_unit_worktree`; runs `git check-ignore` to decide whether a "
        "parent-checkout directory may be symlinked into the fresh unit worktree, and spawns no "
        "executor of its own."
    ),
    "src/coding/executor_readiness.py": (
        "probes `<executor> --version` on PATH to report which agent CLIs are installed; "
        "reads a version line, dispatches no work."
    ),
    "src/coding/hermes_model_config.py": (
        "operator-invoked `omh setup --model-setup` and `omh coding model-routing status`; "
        "runs bounded local `hermes config` / `hermes auth` inspection and approved alias "
        "mutation, never a model or coding executor."
    ),
    "src/coding/hermes_child_dispatch.py": (
        "operator-only, explicitly confirmed `ask_before_dispatch` seam for one bounded local "
        "`hermes --oneshot --model` child; suppresses recursion and cleans its process group."
    ),
    "src/coding/skill_load_process.py": (
        "private executable snapshot and process lifecycle adapter for the operator-only "
        "`omh coding hermes-child skill-load-probe --confirm-dispatch`; runs one bounded local "
        "machine-inventory command, never a model or skill body."
    ),
    "src/coding/_hermes_child_process.py": (
        "private lifecycle helper for the explicitly confirmed Hermes child seam; relays signals, "
        "escalates SIGTERM to SIGKILL, and verifies that the child process group is absent."
    ),
    "src/commands/coding.py": (
        "`git rev-parse <base-ref>` inside the operator-invoked `coding fanout dispatch` command, "
        "to resolve the base commit before the fanout bridge above runs."
    ),
    "src/commands/main.py": (
        "bare `omh` with a tty -- the operator's own launch of `hermes`, the same "
        "door as typing it themselves; never reached from any prepared-handoff path."
    ),
    "src/commands/setup.py": (
        "`omh setup` / `omh update` -- pip self-update, CLI re-entry after update, and the "
        "opt-in GitHub star (see GH_INVOCATION_EXCEPTIONS in INVARIANT 3)."
    ),
    "src/quality/cross_harness_adapter_sandbox.py": (
        "sandboxed child process for the cross-harness benchmark lane."
    ),
    "src/quality/cross_harness_adapters.py": (
        "adapter process factory for the cross-harness benchmark lane."
    ),
    "src/install/release_smoke_core.py": (
        "release smoke runner; executes the smoke commands an operator asked for."
    ),
    "src/install/self_update.py": (
        "the installer branch of an explicit `omh update` (reached only from "
        "`commands/setup.py:_run_command_package_self_update` when the operator runs it, never a "
        "hidden or default execution): runs local, staged commands only -- `python -m venv` to "
        "build the candidate generation's venv, that candidate's `python -m pip install "
        "--disable-pip-version-check --no-cache-dir --upgrade <package_url>` into it, the "
        "candidate smokes (`python -c 'import omh.cli'`, `python -m omh.cli --version`, and the "
        "workflow-pack smoke), and the bounded post-activation re-entry `python -m omh.cli ... "
        "--command-package-updated` through the generation pointer. Every command runs the staged "
        "candidate interpreter locally; rollback, never the operator's environment, absorbs any "
        "failure."
    ),
    "src/install/self_update_platform.py": (
        "the Windows platform seam of the staged `omh update` transaction above: it creates the "
        "bootstrap and `current` generation links as local directory junctions through one fixed "
        "argv, `powershell.exe -NoLogo -NoProfile -NonInteractive -Command "
        "WINDOWS_JUNCTION_COMMAND`, whose program text is a module-level constant running "
        "`New-Item -ItemType Junction ... | Out-Null`. The command's only data inputs are the "
        "two named environment keys `OMH_JUNCTION_LINK` and `OMH_JUNCTION_TARGET`, added to a "
        "copy of the parent environment: no path, user, or target bytes are ever embedded in the "
        "program text, so a valid Windows install path containing `&`, `|`, `^`, `<`, `>`, or "
        "`%...%` cannot be re-parsed or expanded by the child -- the data transport is the "
        "environment variables, not `shell=False`. The child runs with `shell=False`, the link's "
        "parent as `cwd` so the target stays relative and relocatable, and a 15-second bound; a "
        "failed junction is removed and the old pointer is left untouched. The command holds no "
        "other PowerShell authority -- no script file, no expression evaluation, no network or "
        "process cmdlet. On POSIX the same operation is `os.symlink` and spawns nothing, and the "
        "Windows launcher retarget is an `atomic_write_text` shim rewrite that spawns no process. "
        "Reached only from `install.self_update` inside an explicit `omh update`; no network, no "
        "remote."
    ),
    "src/maintenance/installer_update.py": (
        "deterministic `demo_atomic_update()` facade for the installer transaction above; imports "
        "`subprocess` only to build `CompletedProcess` stand-ins for the fake runner it injects "
        "into `install.self_update` -- it spawns no process of its own, makes no network call, "
        "and runs entirely inside a TemporaryDirectory."
    ),
    "src/install/plugin_loader_observation.py": (
        "`omh doctor` isolated real-Hermes registration probe; reads registered tool/hook names, "
        "dispatches no agent work, and writes only inside a temporary HERMES_HOME."
    ),
    "src/maintenance/release_source_identity.py": (
        "the single subprocess owner of the release-identity lane after the #1280 split: "
        "`probe_source_identity`, reached from explicit `omh release evidence-bundle "
        "--write/--verify` (commands/release.py) and the release evidence builder "
        "(maintenance/release.py) through the `release_identity.py` facade; runs only the local, "
        "read-only git identity reads enumerated in GIT_ARGV_ALLOWLIST below (`git -c "
        "core.fsmonitor=false rev-parse HEAD`, `git -c core.fsmonitor=false rev-parse "
        "HEAD^{tree}`, and `git -c core.fsmonitor=false --no-optional-locks status "
        "--porcelain=v1 --untracked-files=all`), every argv explicitly overriding repository-"
        "configured `core.fsmonitor` so an identity-only probe cannot execute repo-configured "
        "hook-shaped config, the status probe additionally refusing the optional index lock "
        "and pinning its own porcelain format and untracked-file visibility so repository config "
        "cannot change what it reports, each bounded by a 15-second timeout, to identify a "
        "source-checkout install. The facade and `release_evidence_verification.py` "
        "import no subprocess; this module spawns no agent, names no remote, and fails soft when "
        "git or a repository is absent."
    ),
    "src/maintenance/update_check_probe.py": (
        "transport owner for the opt-in `omh update-check` facade (mode defaults to off): bounded "
        "`curl` GETs of the public GitHub API for the watched branch head, repository metadata, "
        "commit compare, reachable tags, and reachable releases. The scheduled probe is one curl subprocess carrying at "
        "most two URLs (branch head first, repository metadata second), `--max-time 1.5` per "
        "transfer with a 2.0 s `subprocess.run` whole-process bound; compare, tags, and releases use the same "
        "bound only on the rare moved-head/recovery path. Reached from the launch door or explicit "
        "install/update only after the user opts in. The external curl process makes the connection; "
        "the facade, state, and recovery modules have no subprocess capability."
    ),
    "src/runtime/update_watch_recovery.py": (
        "deterministic `demo_rewrite_recovery()` facade for the issue #1282 update-watch recovery; "
        "imports `subprocess` only to build `CompletedProcess` stand-ins for the fake curl runner "
        "it injects into `maintenance.update_check` -- it spawns no process of its own, makes no "
        "network call, and runs entirely inside a TemporaryDirectory."
    ),
    "src/plugin_bundle/omh/tools/evidence_tool.py": (
        "allowlisted local verification-command runner; its allowlist is itself gated below."
    ),
    "src/surfaces/menubar_app.py": (
        "`swiftc` compile plus `launchctl` load for the opt-in macOS menubar helper install."
    ),
    "src/surfaces/hermes_processes.py": (
        "explicit `omh menubar status --observe-local-processes` (also invoked by the opted-in "
        "native helper); reads local process status, spawns no agent."
    ),
    "src/quality/evidence_records.py": (
        "`current_git_tree_hash()`, reached from `omh goal checkpoint`, runs one bounded local "
        "read-only `git rev-parse --short HEAD^{tree}` so a recorded observation carries the tree "
        "it was observed against. It reads a hash and nothing else: no ref moves, no work starts, "
        "and a machine with no git or no repository answers None instead of a stamp."
    ),
}

# Alternative spawn routes. No allowlist: `subprocess` is the only sanctioned
# door, so reaching for one of these is always the wrong move and there is no
# entry to add. `os.fork` and friends would let a module spawn work while
# importing nothing that INVARIANT 1 inspects.
OS_SPAWN_FUNCTIONS = frozenset(
    {
        "system",
        "popen",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "fork",
        "forkpty",
        "posix_spawn",
        "posix_spawnp",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "startfile",
    }
)


class NoHiddenProcessSpawn(unittest.TestCase):
    """INVARIANT 1 (GENUINE NEW COVERAGE): only named bridges may spawn.

    omh's safety story rests on the claim that preparing a handoff cannot start
    work. That claim is only true while the set of modules able to start a
    process stays small and deliberate. Nothing enforced the set before this.

    Decided by AST: an `ast.Import`/`ast.ImportFrom` node naming `subprocess`,
    at any scope. A comment or docstring mentioning `subprocess` is a token the
    parser discards, so it can neither add nor clear a module here.
    """

    def test_only_allowlisted_modules_import_subprocess(self) -> None:
        for relative_path, tree in _source_modules():
            for module, _names, lineno in _imported_modules(tree):
                if module != "subprocess" and not module.startswith("subprocess."):
                    continue
                self.assertIn(
                    relative_path,
                    PROCESS_SPAWN_ALLOWLIST,
                    f"INVARIANT 1 (no hidden process spawn): {relative_path} line {lineno} imports "
                    f"`{module}`, but it is not an allowlisted process bridge. Preparing a handoff "
                    f"must never be able to start work. Either remove the import, or -- if this "
                    f"module really is reached only from an explicit operator command -- add "
                    f'"{relative_path}" to PROCESS_SPAWN_ALLOWLIST in {THIS_TEST} with a one-line '
                    f"reason naming the command that reaches it.",
                )

    def test_every_allowlisted_module_still_needs_its_entry(self) -> None:
        """A stale allowlist is a silently widened allowlist."""
        importing = {
            relative_path
            for relative_path, tree in _source_modules()
            for module, _names, _lineno in _imported_modules(tree)
            if module == "subprocess" or module.startswith("subprocess.")
        }
        stale = sorted(set(PROCESS_SPAWN_ALLOWLIST) - importing)
        self.assertEqual(
            stale,
            [],
            f"INVARIANT 1 (no hidden process spawn): {stale} are listed in "
            f"PROCESS_SPAWN_ALLOWLIST in {THIS_TEST} but no longer import `subprocess`. "
            f"Delete those entries so the allowlist keeps describing the real spawn surface "
            f"instead of pre-authorising a future one.",
        )

    def test_no_module_spawns_through_the_os_module(self) -> None:
        for relative_path, tree in _source_modules():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr not in OS_SPAWN_FUNCTIONS:
                    continue
                if not isinstance(func.value, ast.Name) or func.value.id != "os":
                    continue
                self.fail(
                    f"INVARIANT 1 (no hidden process spawn): {relative_path} line {node.lineno} calls "
                    f"`os.{func.attr}`, which starts a process without importing `subprocess` and so "
                    f"walks around the allowlist entirely. There is no allowlist entry to add for this: "
                    f"route the call through an allowlisted bridge module using `subprocess`, or remove it.",
                )

    def test_no_module_reaches_a_spawn_capability_by_dynamic_import(self) -> None:
        """`__import__("subprocess")` would satisfy no static import check."""
        for relative_path, tree in _source_modules():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                is_builtin = isinstance(func, ast.Name) and func.id == "__import__"
                is_importlib = isinstance(func, ast.Attribute) and func.attr == "import_module"
                if not (is_builtin or is_importlib):
                    continue
                self.fail(
                    f"INVARIANT 1 (no hidden process spawn): {relative_path} line {node.lineno} imports "
                    f"a module dynamically. A dynamic import is invisible to every static gate in "
                    f"{THIS_TEST}, so it can reach `subprocess`, a network client, or anything else "
                    f"without tripping any of them. Use a normal `import` statement, which the "
                    f"allowlists can see.",
                )


# --------------------------------------------------------------------------
# INVARIANT 2 -- no network client in src/
# --------------------------------------------------------------------------

# Top-level module names that give a caller a live connection. `urllib` is
# absent on purpose and handled separately below, because its two submodules
# differ: `urllib.parse` is pure string work, `urllib.request` is the client.
NETWORK_CLIENT_MODULES = frozenset(
    {
        # stdlib
        "asyncio",  # its stream and subprocess APIs are exactly the two capabilities #818 blocks
        "ftplib",
        "http",  # http.client, http.server, http.cookiejar
        "imaplib",
        "nntplib",
        "poplib",
        "smtplib",
        "socket",
        "socketserver",
        "ssl",  # only reachable meaningfully by wrapping a socket
        "telnetlib",
        "webbrowser",
        "xmlrpc",
        # third party -- also barred by the repo's zero-runtime-dependency rule,
        # listed here so the reason a reviewer sees is the safety one
        "aiohttp",
        "boto3",
        "botocore",
        "grpc",
        "httpx",
        "paramiko",
        "pycurl",
        "requests",
        "tornado",
        "twisted",
        "urllib3",
        "websocket",
        "websockets",
    }
)

# `urllib.request` is a network client module that happens to also contain one
# pure path-parsing function. `url2pathname` maps a `file://` URL onto a local
# filesystem path -- it is string manipulation and opens nothing. Importing the
# *name* is therefore fine; importing the *module* (`import urllib.request`)
# hands the file `urlopen` and is not.
PARSING_ONLY_URLLIB_REQUEST_NAMES = frozenset({"url2pathname", "pathname2url"})
PARSING_ONLY_URLLIB_REQUEST_FILES: dict[str, str] = {
    "src/workflows/visual_summary.py": "resolves screenshot `file://` references to local paths",
    "src/workflows/web_visual_qa_contracts.py": "resolves visual-QA `file://` references to local paths",
    "src/commands/setup.py": "resolves PEP 610 direct_url.json `file://` origins to local paths for update guidance",
}


class NoNetworkClientInSource(unittest.TestCase):
    """INVARIANT 2 (GENUINE NEW COVERAGE): core omh cannot open a connection.

    "Core `omh` code makes no LLM, API, or network calls" is the first sentence
    of the repo's own description, and until now the only thing standing behind
    it was that nobody had added a client. The zero-dependency rule blocks
    `requests`; it does nothing about `socket` or `urllib.request`, both of
    which are stdlib and both of which would install a working client.

    Decided by AST import nodes, which is what separates a client from a
    detector. `src/workflows/plugin_risk_audit.py` contains the regex
    `\\b(?:axios|httpx|requests|urllib...)` -- that is one `ast.Constant`
    holding a pattern used to *audit third-party plugins for* network calls. It
    is the opposite of a violation, and a text search would have flagged it.
    """

    def test_no_module_imports_a_network_client(self) -> None:
        for relative_path, tree in _source_modules():
            for module, _names, lineno in _imported_modules(tree):
                if not module:
                    continue
                top = module.split(".")[0]
                if top not in NETWORK_CLIENT_MODULES:
                    continue
                self.fail(
                    f"INVARIANT 2 (no network client in src/): {relative_path} line {lineno} imports "
                    f"`{module}`. Core omh makes no network calls -- that is the product boundary, not "
                    f"a style preference, and it is what lets omh claim it never acts on the user's "
                    f"behalf. Remove the import. If a genuinely offline use of this module exists "
                    f"(as `url2pathname` is for `urllib.request`), add it to "
                    f"NETWORK_CLIENT_MODULES' documented exceptions in {THIS_TEST} and say why it "
                    f"cannot open a connection.",
                )

    def test_urllib_request_is_imported_only_for_path_parsing(self) -> None:
        for relative_path, tree in _source_modules():
            for module, names, lineno in _imported_modules(tree):
                if module != "urllib.request" and not module.startswith("urllib.request."):
                    continue
                self.assertTrue(
                    names,
                    f"INVARIANT 2 (no network client in src/): {relative_path} line {lineno} does "
                    f"`import {module}`, which binds the whole client module and with it `urlopen`. "
                    f"Import only the path-parsing name you need "
                    f"(`from urllib.request import url2pathname`), or drop the import.",
                )
                self.assertIn(
                    relative_path,
                    PARSING_ONLY_URLLIB_REQUEST_FILES,
                    f"INVARIANT 2 (no network client in src/): {relative_path} line {lineno} imports "
                    f"from `urllib.request`, which is a network client module. Only files listed in "
                    f"PARSING_ONLY_URLLIB_REQUEST_FILES in {THIS_TEST} may do so, and only for the "
                    f"pure path-parsing names. Add the file with a reason, or remove the import.",
                )
                forbidden = sorted(set(names) - PARSING_ONLY_URLLIB_REQUEST_NAMES)
                self.assertEqual(
                    forbidden,
                    [],
                    f"INVARIANT 2 (no network client in src/): {relative_path} line {lineno} imports "
                    f"{forbidden} from `urllib.request`. Only "
                    f"{sorted(PARSING_ONLY_URLLIB_REQUEST_NAMES)} are path parsing; everything else in "
                    f"that module opens a connection. Remove the name.",
                )

    def test_the_parsing_only_exception_list_is_not_stale(self) -> None:
        importing = {
            relative_path
            for relative_path, tree in _source_modules()
            for module, _names, _lineno in _imported_modules(tree)
            if module == "urllib.request" or module.startswith("urllib.request.")
        }
        stale = sorted(set(PARSING_ONLY_URLLIB_REQUEST_FILES) - importing)
        self.assertEqual(
            stale,
            [],
            f"INVARIANT 2 (no network client in src/): {stale} no longer import from `urllib.request`. "
            f"Delete the entries from PARSING_ONLY_URLLIB_REQUEST_FILES in {THIS_TEST} rather than "
            f"leaving standing permission behind.",
        )


# --------------------------------------------------------------------------
# INVARIANT 3 -- no remote mutation
# --------------------------------------------------------------------------

# Verbs that publish to, or rewrite history against, a remote. `fetch`/`pull`
# are here because omh must not move the operator's working state either: a
# prepared handoff that quietly updated the tree it describes is no longer a
# prepared handoff.
FORBIDDEN_GIT_VERBS = frozenset({"push", "merge", "rebase", "remote", "fetch", "pull"})

# Programs whose whole job is talking to a forge.
FORGE_PROGRAMS = frozenset({"gh", "hub", "glab", "tea"})

# The complete set of git argv literals in `src/`, keyed by file and by the run
# of literal words that follow `git`. Every one is local; none names a remote.
GIT_ARGV_ALLOWLIST: dict[tuple[str, tuple[str, ...]], str] = {
    ("src/coding/worktree_creator.py", ("worktree", "add")): (
        "creates a local isolated workspace for an executor; touches no remote"
    ),
    ("src/coding/worktree_creator.py", ("worktree", "list")): (
        "`git worktree list --porcelain`, run BEFORE the `worktree add` above, to refuse a branch "
        "another registered worktree already holds and a path git already knows; read-only, names "
        "no remote, and the reason the collision is a named refusal instead of a half-built worktree"
    ),
    ("src/coding/worktree_creator.py", ("check-ref-format",)): (
        "`git check-ref-format refs/heads/<branch>` validates the unit's proposed branch name before "
        "any worktree exists; pure syntax check, reads no object and writes nothing"
    ),
    ("src/coding/worktree_creator.py", ("rev-parse",)): (
        "`rev-parse --verify` twice before the add: once on the source ref, to prove the caller's "
        "base_sha still describes it, and once on refs/heads/<branch>, to prove the unit branch does "
        "not already exist; read-only local object lookups"
    ),
    ("src/coding/paired_run_local_runner.py", ("rev-parse",)): (
        "`git rev-parse --verify <execution_revision>^{commit}` proves the explicitly confirmed "
        "paired-run adapter will create every detached cell from the immutable commit in the "
        "decision; read-only, local-only, and names no remote"
    ),
    ("src/coding/paired_run_local_worktrees.py", ("worktree", "add")): (
        "creates one detached local worktree per explicitly confirmed paired-run cell at the "
        "already-validated decision revision; touches no remote"
    ),
    ("src/coding/paired_run_local_worktrees.py", ("worktree", "remove")): (
        "removes only the detached local worktree this paired-run invocation created after the "
        "cell reaches a terminal state; touches no remote"
    ),
    ("src/coding/local_diagnostic_engine.py", ("diff",)): (
        "`git diff --name-only -z` derives the bounded changed-file set between two already-fixed "
        "diagnostic revisions; read-only, local-only, and names no remote"
    ),
    ("src/coding/local_diagnostic_engine.py", ("rev-parse",)): (
        "`git rev-parse --verify <revision>^{commit}` resolves only the fixed baseline/end/HEAD "
        "identity used by the explicit diagnostic adapter; read-only and local-only"
    ),
    ("src/coding/local_diagnostic_engine.py", ("status",)): (
        "`git status --porcelain --untracked-files=normal` refuses a dirty diagnostic execution "
        "workspace instead of claiming fresh evidence; read-only and local-only"
    ),
    ("src/coding/local_diagnostic_process.py", ("worktree", "add")): (
        "creates one disposable detached checkout of a fixed diagnostic revision under the "
        "explicit `--diagnostics` boundary; local-only and names no remote"
    ),
    ("src/coding/local_diagnostic_process.py", ("worktree", "remove")): (
        "removes only the disposable diagnostic checkout created by the same provider call; "
        "local-only and names no remote"
    ),
    ("src/coding/final_review_worktree.py", ("rev-parse", "HEAD^{tree}")): (
        "reads the integrated and isolated checkout tree identities so final-review lanes cannot "
        "accept a moved revision; read-only and local-only"
    ),
    ("src/coding/final_review_worktree.py", ("rev-parse", "HEAD")): (
        "reads the integrated checkout commit used to create the disposable review worktree after "
        "its tree identity matches; read-only and local-only"
    ),
    ("src/coding/final_review_worktree.py", ("worktree", "add")): (
        "creates one disposable detached checkout for an explicitly requested review lens at the "
        "already-verified integrated commit; local-only and names no remote"
    ),
    ("src/coding/final_review_worktree.py", ("worktree", "remove")): (
        "removes only the disposable review checkout created by the same lens after permissions "
        "are restored; local-only and names no remote"
    ),
    ("src/coding/final_review_worktree.py", ("status",)): (
        "`git --no-optional-locks status --porcelain=v1 --untracked-files=all` verifies the "
        "disposable review checkout stayed unmodified before any verdict is accepted; read-only"
    ),
    ("src/commands/coding.py", ("rev-parse",)): (
        "resolves --base-ref to a commit sha inside `coding fanout dispatch`; read-only"
    ),
    ("src/commands/coding.py", ("status",)): (
        "`git status --porcelain=v1 -z` inside `coding commit-plan`, the metadata the "
        "commit-split planner groups; read-only, names no remote, and the prepared plan "
        "it feeds is never a commit"
    ),
    ("src/coding/fanout_dispatch.py", ("add", ".")): (
        "`git add -N -- .` inside a FAILED unit's own isolated worktree, so the recovery probe can "
        "measure files that unit created. Not read-only: it writes intent-to-add entries to that "
        "worktree's index. It stages no content, makes no commit, names no remote, and never runs "
        "against the operator's repository or a unit that succeeded"
    ),
    ("src/coding/fanout_dispatch.py", ("diff",)): (
        "measures what a failed unit left in its own worktree -- `--numstat -z` for paths, then the "
        "patch that is hashed for size/sha256 and dropped; read-only"
    ),
    ("src/coding/fanout_dispatch.py", ("rev-parse",)): (
        "`rev-parse --show-toplevel`, run BEFORE the `add -N` above, to prove the recovery probe is "
        "standing in the unit's own worktree and not in whatever repository encloses it; read-only, "
        "and the reason the `add` entry's containment claim is checked rather than asserted"
    ),
    ("src/coding/fanout_dispatch.py", ("status",)): (
        "`git status --porcelain=v1 --untracked-files=all` rejects dirty or untracked unit and "
        "integrated worktrees before verification receipts can be reused; read-only local metadata "
        "inspection, names no remote, writes nothing, and fixes both output format and untracked visibility"
    ),
    ("src/coding/fanout_dispatch.py", ("rev-parse", "HEAD^{tree}")): (
        "`rev-parse HEAD^{tree}` reads the tree hash of the unit worktree's HEAD, the revision "
        "component of every verification receipt key the planned-verification engine resolves; "
        "without it a receipt could be reused across a content change, so the read happens at plan "
        "time inside the unit's own worktree. Read-only local object lookup, names no remote, "
        "writes nothing, and resolves no caller-supplied ref"
    ),
    ("src/coding/fanout_dispatch.py", ("rev-parse", "HEAD")): (
        "`rev-parse HEAD` reads the canonical full commit SHA from the clean producer worktree "
        "after executor exit. The dispatcher compares it exactly to the sidecar report before "
        "allowing integration fan-in, so executor text cannot substitute a stale base SHA. "
        "Read-only local object lookup, names no remote, writes nothing, and resolves no "
        "caller-supplied ref"
    ),
    ("src/coding/fanout_dispatch.py", ("merge-base",)): (
        "`merge-base --is-ancestor <producer-head> HEAD` proves each sidecar-observed producer commit "
        "is contained by the caller-supplied integrated checkout before a broad integration gate can "
        "run. It is a read-only local ancestry query, names no remote, writes nothing, and refuses "
        "rather than treating fan-in alone as integration evidence"
    ),
    ("src/maintenance/release_source_identity.py", ("core.fsmonitor=false", "rev-parse", "HEAD")): (
        "`git -c core.fsmonitor=false rev-parse HEAD` reads the current commit sha to identify a "
        "source-checkout install for release-evidence identity; the `-c` override is the whole "
        "isolation story of this call -- it disables repository-configured `core.fsmonitor` so an "
        "identity-only read cannot execute repo-configured hook-shaped config -- and it is the "
        "only config the probe overrides. Read-only local object lookup, names no remote, fails "
        "soft when git or a repository is absent"
    ),
    ("src/maintenance/release_source_identity.py", ("core.fsmonitor=false", "rev-parse", "HEAD^{tree}")): (
        "`git -c core.fsmonitor=false rev-parse HEAD^{tree}` reads the tree hash the release-evidence "
        "identity is recorded against, so a later verification can tell the same tracked content apart "
        "from rewritten content; same single-purpose fsmonitor isolation as the HEAD call above; "
        "read-only local object lookup, names no remote"
    ),
    ("src/maintenance/release_source_identity.py", ("core.fsmonitor=false", "status")): (
        "`git -c core.fsmonitor=false --no-optional-locks status --porcelain=v1 "
        "--untracked-files=all` reads whether the checkout is dirty so the recorded identity can say "
        "so; beyond the fsmonitor override shared with the two rev-parse calls, `--no-optional-locks` "
        "keeps a read-only probe from touching the index lock, and `--porcelain=v1` plus "
        "`--untracked-files=all` fix the output format and the untracked-file visibility so repository "
        "config (status.showUntrackedFiles, status.porcelainFormat) cannot change what the probe "
        "reports. Read-only, names no remote, writes nothing"
    ),
    ("src/quality/evidence_records.py", ("rev-parse", "HEAD^{tree}")): (
        "`rev-parse --short HEAD^{tree}` reads the tree hash a quality-evidence observation is "
        "recorded against, so assessment can later tell evidence about the current tracked content "
        "from evidence about older content; read-only local object lookup, names no remote, and it "
        "resolves no ref the caller supplied"
    ),
    ("src/coding/fanout_artifact_sharing.py", ("check-ignore",)): (
        "`git check-ignore -q --` against the parent checkout, then again inside the fresh unit "
        "worktree after a symlink is created, to decide whether an allowlisted artifact directory "
        "may be shared; read-only, names no remote, and never runs against anything but the "
        "dispatching repo or the unit worktree it just created"
    ),
}

# The one executed forge invocation in `src/`. It is not repository authority:
# it stars the project on the operator's own account, from an interactive
# prompt in `omh setup`, and it can neither push code nor merge anything. It is
# pinned by exact argv so that widening it to any other `gh` call fails here.
GH_INVOCATION_EXCEPTIONS: dict[tuple[str, tuple[str, ...]], str] = {
    (
        "src/commands/setup.py",
        ("gh", "api", "-X", "PUT", "/user/starred/rlaope/oh-my-hermes"),
    ): (
        "opt-in 'star the repo?' prompt during interactive `omh setup`; mutates the operator's "
        "own stars, never repository contents, and never runs unattended"
    ),
}


def _argv_literals() -> list[tuple[str, int, list[str | None]]]:
    """Every list/tuple literal in `src/` that starts with a literal program name.

    Elements are returned as their string value, or `None` where the element is
    a dynamic expression. Only literals whose *first* element is a constant
    string are returned, because that is the shape of a hand-built argv.
    """
    found: list[tuple[str, int, list[str | None]]] = []
    for relative_path, tree in _source_modules():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
                continue
            first = node.elts[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue
            elements: list[str | None] = [
                element.value if isinstance(element, ast.Constant) and isinstance(element.value, str) else None
                for element in node.elts
            ]
            found.append((relative_path, node.lineno, elements))
    return found


def _leading_words(elements: list[str | None]) -> tuple[str, ...]:
    """The run of literal non-flag words after the program name."""
    words: list[str] = []
    for element in elements[1:]:
        if element is None:
            break
        if element.startswith("-"):
            continue
        words.append(element)
    return tuple(words)


class NoRemoteMutation(unittest.TestCase):
    """INVARIANT 3 (REGRESSION PREVENTION): omh cannot push, merge, or post.

    Nothing in `src/` performs a remote mutation today, so this proves nothing
    new about the current tree. It exists so that one cannot arrive unnoticed --
    a single `["git", "push", ...]` added to an already-allowlisted spawn module
    would otherwise pass every gate in this repo.

    The hard part is telling an *executed* argv apart from documentation and
    from a parser, and this is done structurally rather than by searching text.
    The scan visits exactly one AST shape: a list or tuple literal whose first
    element is a constant program name. That distinction does real work:

    * `src/maintenance/release.py` holds
      `f'git tag -a {tag} ... && git push origin {tag}'` -- a single
      `ast.JoinedStr` printed for a human to run. It is not a list, its parts
      are not argv elements, and the scan never reaches it. A text search would
      have reported a `git push` in `src/`.
    * `src/coding/work_reporting.py` evaluates `"gh pr checks" in command_lower`
      against an executor's transcript. The literal is an operand of a
      `Compare` used to *recognise* someone else's command in text omh was
      handed. Not a list, not visited. A text search would have reported a `gh`
      invocation in `src/`.
    * `src/coding/worktree_creator.py` builds `["git", "worktree", "add", ...]`
      and passes it to `subprocess.run`. That is an argv, it is visited, and
      its verb is checked.

    A git argv whose verb cannot be resolved to a literal fails closed. Today
    every one of them is literal, so proving safety costs nothing; the day
    someone writes `["git", verb, ...]` the reviewer is asked about it.
    """

    def test_no_git_argv_carries_a_remote_mutating_verb(self) -> None:
        for relative_path, lineno, elements in _argv_literals():
            program = elements[0]
            if program != "git" and not str(program).endswith("/git"):
                continue
            words = _leading_words(elements)
            self.assertTrue(
                words,
                f"INVARIANT 3 (no remote mutation): {relative_path} line {lineno} builds a `git` argv "
                f"whose subcommand is a runtime value, so this gate cannot prove it is not `push`, "
                f"`merge`, or `rebase`. Spell the subcommand as a literal "
                f'(`["git", "rev-parse", ref]`, not `["git", verb, ref]`) so the invariant stays '
                f"checkable.",
            )
            offending = sorted(set(words) & FORBIDDEN_GIT_VERBS)
            self.assertEqual(
                offending,
                [],
                f"INVARIANT 3 (no remote mutation): {relative_path} line {lineno} builds "
                f"`git {' '.join(words)}`, which uses the forbidden verb(s) {offending}. omh prepares "
                f"work and never performs it -- it must not publish to, or move, a remote. Remove the "
                f"command; there is no allowlist entry for a mutating git verb.",
            )
            self.assertIn(
                (relative_path, words),
                GIT_ARGV_ALLOWLIST,
                f"INVARIANT 3 (no remote mutation): {relative_path} line {lineno} builds a new git "
                f"argv `git {' '.join(words)}`. Every git command omh runs is enumerated. Add "
                f'("{relative_path}", {words!r}) to GIT_ARGV_ALLOWLIST in {THIS_TEST} with a reason '
                f"stating that it is local and read-only, or remove the command.",
            )

    def test_no_module_invokes_a_forge_cli_outside_the_named_exception(self) -> None:
        for relative_path, lineno, elements in _argv_literals():
            program = elements[0]
            if program not in FORGE_PROGRAMS:
                continue
            argv = tuple(element for element in elements if element is not None)
            self.assertIn(
                (relative_path, argv),
                GH_INVOCATION_EXCEPTIONS,
                f"INVARIANT 3 (no remote mutation): {relative_path} line {lineno} invokes the `{program}` "
                f"forge CLI as {list(argv)}. omh must not open, review, or merge anything on a forge on "
                f"the user's behalf -- it prepares the handoff and the operator acts. Remove the call. "
                f"If it genuinely cannot touch repository state, add the exact argv to "
                f"GH_INVOCATION_EXCEPTIONS in {THIS_TEST} and say what it can and cannot do.",
            )

    def test_the_git_and_forge_allowlists_are_not_stale(self) -> None:
        live_git = {
            (relative_path, _leading_words(elements))
            for relative_path, _lineno, elements in _argv_literals()
            if elements[0] == "git"
        }
        live_forge = {
            (relative_path, tuple(element for element in elements if element is not None))
            for relative_path, _lineno, elements in _argv_literals()
            if elements[0] in FORGE_PROGRAMS
        }
        stale = sorted(
            (set(GIT_ARGV_ALLOWLIST) - live_git) | (set(GH_INVOCATION_EXCEPTIONS) - live_forge)
        )
        self.assertEqual(
            stale,
            [],
            f"INVARIANT 3 (no remote mutation): {stale} are permitted in {THIS_TEST} but no longer "
            f"exist in `src/`. Delete the entries; an allowlist that outlives its call site is "
            f"standing permission for whoever adds the next one.",
        )

    def test_the_evidence_tool_allowlist_admits_no_remote_command(self) -> None:
        """The one place a command *string* really is an execution surface.

        `evidence_tool` runs operator-requested verification commands, matched
        against `_DEFAULT_ALLOWLIST` by token prefix. These strings are not
        prose: adding `"git push"` there would make it runnable. The check is on
        the imported value, not on the file text.
        """
        for entry in _DEFAULT_ALLOWLIST:
            tokens = entry.split()
            self.assertTrue(tokens, "evidence tool allowlist entries must not be empty")
            program = tokens[0]
            self.assertNotIn(
                program,
                FORGE_PROGRAMS,
                f"INVARIANT 3 (no remote mutation): the evidence tool allowlist admits {entry!r}, which "
                f"runs the `{program}` forge CLI. `_DEFAULT_ALLOWLIST` in "
                f"src/plugin_bundle/omh/tools/evidence_tool.py is an execution surface, not "
                f"documentation. Remove the entry.",
            )
            if program != "git":
                continue
            offending = sorted(set(tokens[1:]) & FORBIDDEN_GIT_VERBS)
            self.assertEqual(
                offending,
                [],
                f"INVARIANT 3 (no remote mutation): the evidence tool allowlist admits {entry!r}, which "
                f"would let a verification request run the mutating git verb(s) {offending}. Evidence "
                f"gathering is read-only. Remove the entry from `_DEFAULT_ALLOWLIST` in "
                f"src/plugin_bundle/omh/tools/evidence_tool.py.",
            )


# --------------------------------------------------------------------------
# INVARIANT 1 corollary -- the fixed Windows junction command boundary
# --------------------------------------------------------------------------

# The staged-update junction seam. `create_directory_link` used to pass the
# link and target bytes as cmd.exe program text after `/c`, where `&`, `|`,
# `^`, `<`, `>`, and `%...%` are operators and percent expansion happens even
# inside quotes -- `shell=False` protected nothing because cmd.exe IS the
# shell (correction-verification.md section 17.1, BLOCKER-S1). The correction
# moved every path byte out of the program text and into two named environment
# variables behind one fixed powershell.exe command. These gates hold that
# boundary in place: the command stays a constant, the path bytes stay out of
# the argv, and the written allowlist rationale stays describing the command
# the code actually runs, so neither can drift alone.
WINDOWS_JUNCTION_PLATFORM = "src/install/self_update_platform.py"
WINDOWS_JUNCTION_ARGV_HEAD = (
    "powershell.exe",
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
)

# `powershell -Command` is arbitrary-code authority on a Windows host; these
# are the tokens that would widen the junction command from "create one
# directory junction" into network or process authority.
POWERSHELL_PROGRAMS = frozenset({"powershell", "powershell.exe", "pwsh", "pwsh.exe"})
POWERSHELL_AUTHORITY_TOKENS = (
    "Invoke-",
    "Start-Process",
    "Net.WebClient",
    "DownloadFile",
    "DownloadString",
    "http",
)


class WindowsJunctionCommandBoundary(unittest.TestCase):
    """BLOCKER-S1 cannot regress silently: the junction argv is pinned.

    The producer suite (`tests/test_staged_self_update.py`) proves the seam
    works; these gates prove the safety contract holds. They are behavioural
    where behaviour decides (the spawn itself, observed through a captured
    runner) and structural where structure decides (the argv and command
    constant read as an AST, so a comment cannot satisfy them and an
    f-string cannot sneak past them).
    """

    def _platform_tree(self) -> ast.Module:
        for relative_path, tree in _source_modules():
            if relative_path == WINDOWS_JUNCTION_PLATFORM:
                return tree
        self.fail(
            f"{WINDOWS_JUNCTION_PLATFORM} is not in the src/ sweep, so the junction command "
            f"boundary cannot be checked. This gate only runs against the live tree."
        )

    def test_the_allowlist_rationale_names_the_live_command(self) -> None:
        """The written safety policy must describe the command the code runs.

        The entry below is the safety policy for this spawn; if it names a
        command the module no longer runs (or stops naming the one it does),
        the policy and the spawn surface have drifted apart. The asserted
        strings are the command vocabulary -- program, flags, cmdlet, and the
        two environment keys -- not prose wording.
        """
        self.assertIn(
            WINDOWS_JUNCTION_PLATFORM,
            PROCESS_SPAWN_ALLOWLIST,
            f"INVARIANT 1 (no hidden process spawn): {WINDOWS_JUNCTION_PLATFORM} lost its "
            f"PROCESS_SPAWN_ALLOWLIST entry in {THIS_TEST} but still runs the Windows junction "
            f"command. Restore the entry with the fixed-command rationale.",
        )
        rationale = PROCESS_SPAWN_ALLOWLIST[WINDOWS_JUNCTION_PLATFORM]
        for token in (
            *WINDOWS_JUNCTION_ARGV_HEAD,
            "New-Item",
            JUNCTION_LINK_ENV,
            JUNCTION_TARGET_ENV,
        ):
            self.assertIn(
                token,
                rationale,
                f"INVARIANT 1 (no hidden process spawn): the PROCESS_SPAWN_ALLOWLIST entry for "
                f"{WINDOWS_JUNCTION_PLATFORM} does not name {token!r}, but the module runs "
                f"{' '.join(WINDOWS_JUNCTION_ARGV_HEAD)} <constant>. The allowlist rationale is "
                f"the written safety policy for this spawn; update it to describe the live "
                f"command instead of a retired one.",
            )
        for retired in ("cmd.exe", "mklink"):
            self.assertNotIn(
                retired,
                rationale,
                f"INVARIANT 1 (no hidden process spawn): the PROCESS_SPAWN_ALLOWLIST entry for "
                f"{WINDOWS_JUNCTION_PLATFORM} still describes the retired `{retired}` argv. "
                f"That argv passed untrusted path bytes as cmd.exe program text (BLOCKER-S1, "
                f"correction-verification.md section 17.1); the rationale must describe the "
                f"fixed powershell.exe command with environment-variable data transport.",
            )

    def test_the_junction_command_references_only_the_two_named_environment_keys(self) -> None:
        """The command's only data inputs are the two named environment keys."""
        referenced = re.findall(r"\$env:([A-Za-z0-9_]+)", WINDOWS_JUNCTION_COMMAND)
        self.assertEqual(
            referenced,
            [JUNCTION_LINK_ENV, JUNCTION_TARGET_ENV],
            f"INVARIANT 1 (no hidden process spawn): the Windows junction command reads "
            f"{referenced} from the environment, but only {JUNCTION_LINK_ENV} and "
            f"{JUNCTION_TARGET_ENV} are the sanctioned data transport. Any other reference "
            f"puts unsanitised parent-environment bytes into the program text. Read only the "
            f"two named keys in src/install/self_update_platform.py.",
        )
        self.assertNotIn(
            "%",
            WINDOWS_JUNCTION_COMMAND,
            "INVARIANT 1 (no hidden process spawn): cmd.exe-style percent sequences have no "
            "place in the fixed junction command; they expand before the command runs.",
        )
        for token in ("New-Item", "-ItemType Junction", "Out-Null"):
            self.assertIn(
                token,
                WINDOWS_JUNCTION_COMMAND,
                f"INVARIANT 1 (no hidden process spawn): the junction command no longer creates "
                f"the junction with {token!r}. It must stay the one fixed `New-Item -ItemType "
                f"Junction ... | Out-Null` command -- widening it needs a new safety rationale.",
            )
        for token in POWERSHELL_AUTHORITY_TOKENS:
            self.assertNotIn(
                token,
                WINDOWS_JUNCTION_COMMAND,
                f"INVARIANT 1 (no hidden process spawn): the junction command contains {token!r}, "
                f"which is network or process authority, not junction creation. The staged-update "
                f"seam is admitted for one fixed local command and nothing broader.",
            )

    def test_the_junction_argv_is_built_only_from_constants(self) -> None:
        """The argv is five literals plus one module constant -- nothing dynamic.

        Decided by AST: if any element becomes an f-string, a concatenation,
        or a computed value, the path bytes are back in the program text and
        BLOCKER-S1 has regressed, whatever the captured-runner tests say.
        """
        tree = self._platform_tree()
        commands = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.List)
            and node.elts
            and isinstance(node.elts[0], ast.Constant)
            and node.elts[0].value == "powershell.exe"
        ]
        self.assertEqual(
            len(commands),
            1,
            f"INVARIANT 1 (no hidden process spawn): {WINDOWS_JUNCTION_PLATFORM} now builds "
            f"{len(commands)} powershell.exe argv literals. Exactly one fixed command is "
            f"admitted; a second one needs its own safety rationale.",
        )
        elements = commands[0].elts
        self.assertEqual(
            len(elements),
            len(WINDOWS_JUNCTION_ARGV_HEAD) + 1,
            f"INVARIANT 1 (no hidden process spawn): the junction argv changed shape from the "
            f"fixed {list(WINDOWS_JUNCTION_ARGV_HEAD)} head plus one command constant. Update "
            f"the allowlist rationale and these gates together, deliberately.",
        )
        for element in elements[: len(WINDOWS_JUNCTION_ARGV_HEAD)]:
            self.assertIsInstance(
                element,
                ast.Constant,
                "INVARIANT 1 (no hidden process spawn): a junction argv head element is now a "
                "computed value. The head must stay literal so the gate can prove which program "
                "and flags run.",
            )
        self.assertEqual(
            [element.value for element in elements[: len(WINDOWS_JUNCTION_ARGV_HEAD)]],
            list(WINDOWS_JUNCTION_ARGV_HEAD),
            "INVARIANT 1 (no hidden process spawn): the junction argv head is no longer the "
            "fixed powershell.exe -NoLogo -NoProfile -NonInteractive -Command spelling. The "
            "flags bound the child (no profile, no interactivity); widening them needs a new "
            "safety rationale.",
        )
        command_element = elements[len(WINDOWS_JUNCTION_ARGV_HEAD)]
        self.assertIsInstance(command_element, ast.Name)
        self.assertEqual(
            command_element.id,  # type: ignore[attr-defined]
            "WINDOWS_JUNCTION_COMMAND",
            "INVARIANT 1 (no hidden process spawn): the junction program text is no longer the "
            "WINDOWS_JUNCTION_COMMAND constant. An interpolated or built string would carry "
            "path bytes into the program text -- BLOCKER-S1 exactly. Pass the fixed constant.",
        )
        constants = [
            node.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "WINDOWS_JUNCTION_COMMAND"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
        ]
        self.assertEqual(
            constants,
            [WINDOWS_JUNCTION_COMMAND],
            "INVARIANT 1 (no hidden process spawn): WINDOWS_JUNCTION_COMMAND must stay a single "
            "module-level string constant. Building it from anything dynamic puts untrusted "
            "bytes back into the child's program text.",
        )

    def test_the_spawn_carries_path_bytes_only_in_the_two_named_keys(self) -> None:
        """BLOCKER-S1's case, driven through the real seam with a captured runner.

        A link and target whose every byte is a shell metacharacter
        (`A&B%TEMP%^!()`) must reach the child exactly twice -- as the values of
        the two named environment keys -- and must appear in neither the argv
        nor the `list2cmdline` program text the child parses. `shell=False`, a
        bounded timeout, and the link's parent as `cwd` are asserted on the
        same captured spawn, because they are part of the same boundary.
        """
        metacharacters = "A&B%TEMP%^!()"
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "", "")

        with TemporaryDirectory() as temporary:
            root = Path(temporary) / metacharacters
            link = root / f".current.{metacharacters}.tmp"
            target = root / "generations" / metacharacters
            with patch.dict(os.environ, {"PRESERVED": "yes"}, clear=True):
                SelfUpdatePlatform.windows(runner).create_directory_link(root, link, target)

        self.assertEqual(
            len(calls),
            1,
            "INVARIANT 1 (no hidden process spawn): the Windows junction creation spawned more "
            "than one child. The seam is admitted for one command.",
        )
        command, kwargs = calls[0]
        program_text = subprocess.list2cmdline(command)
        self.assertNotIn(
            metacharacters,
            "\n".join(command),
            "INVARIANT 1 (no hidden process spawn): the untrusted path bytes appear in the "
            "junction argv itself. Path data must travel in the two named environment keys, "
            "never in the program text (BLOCKER-S1).",
        )
        self.assertNotIn(
            metacharacters,
            program_text,
            "INVARIANT 1 (no hidden process spawn): the untrusted path bytes survive into the "
            "`list2cmdline` program text the child parses. They must travel in the two named "
            "environment keys only (BLOCKER-S1).",
        )
        self.assertEqual(command[0], "powershell.exe")
        self.assertEqual(command[1:5], ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command"])
        self.assertEqual(command[5], WINDOWS_JUNCTION_COMMAND)
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["timeout"], JUNCTION_TIMEOUT_SECONDS)
        self.assertGreater(
            JUNCTION_TIMEOUT_SECONDS,
            0,
            "INVARIANT 1 (no hidden process spawn): the junction child has no positive timeout "
            "bound; an unbounded PowerShell child is not an admitted spawn shape.",
        )
        self.assertLessEqual(
            JUNCTION_TIMEOUT_SECONDS,
            15.0,
            "INVARIANT 1 (no hidden process spawn): the junction timeout bound grew beyond the "
            "15 seconds the allowlist rationale states. Widen the policy deliberately, not by "
            "editing the constant.",
        )
        self.assertEqual(kwargs["cwd"], str(link.parent))
        expected_environment = {
            "PRESERVED": "yes",
            JUNCTION_LINK_ENV: str(link),
            JUNCTION_TARGET_ENV: os.path.relpath(target, link.parent),
        }
        self.assertEqual(
            kwargs["env"],
            expected_environment,
            "INVARIANT 1 (no hidden process spawn): the junction child environment is not the "
            "parent environment plus exactly the two named link/target keys. No third data "
            "channel and no dropped parent variable is admitted.",
        )
        self.assertIn(metacharacters, kwargs["env"][JUNCTION_LINK_ENV])
        self.assertIn(metacharacters, kwargs["env"][JUNCTION_TARGET_ENV])
        carrying = sorted(
            key for key, value in kwargs["env"].items() if metacharacters in value
        )
        self.assertEqual(
            carrying,
            sorted((JUNCTION_LINK_ENV, JUNCTION_TARGET_ENV)),
            "INVARIANT 1 (no hidden process spawn): environment keys other than the two named "
            "ones carry the untrusted path bytes. The transport must be exactly "
            f"{JUNCTION_LINK_ENV} and {JUNCTION_TARGET_ENV}.",
        )

    def test_no_module_gains_broader_powershell_authority(self) -> None:
        """PowerShell is admitted for one fixed junction command, nowhere else.

        The whole `src/` tree is swept for constant-headed argv literals that
        start a PowerShell program. Exactly one exists, in the staged-update
        platform seam, with exactly the bounded flag head -- so neither a new
        module nor a widened existing one gains a PowerShell door without this
        gate and the allowlist both noticing.
        """
        for relative_path, lineno, elements in _argv_literals():
            program = elements[0]
            if program not in POWERSHELL_PROGRAMS:
                continue
            argv = tuple(element for element in elements if element is not None)
            self.assertEqual(
                (relative_path, argv),
                (WINDOWS_JUNCTION_PLATFORM, WINDOWS_JUNCTION_ARGV_HEAD),
                f"INVARIANT 1 (no hidden process spawn): {relative_path} line {lineno} runs a "
                f"PowerShell argv {list(argv)}. PowerShell is arbitrary-code authority on a "
                f"Windows host; the only admitted argv is the fixed junction command in "
                f"{WINDOWS_JUNCTION_PLATFORM}. Remove the call, or widen the safety policy in "
                f"{THIS_TEST} explicitly and with a reason.",
            )


# --------------------------------------------------------------------------
# INVARIANT 1 corollary -- the isolated release-identity git argv
# --------------------------------------------------------------------------

# The release source-identity probe. The security review task st_01a06650
# found that `git status --porcelain` runs repository-configured
# `core.fsmonitor` -- hook-shaped config a repository can point at any
# executable -- which turned an identity-only release probe into an execution
# boundary. The fix isolated every probe argv with `-c core.fsmonitor=false`;
# the status probe additionally refuses the optional index lock and pins its
# own porcelain format and untracked-file visibility, so the dirtiness it
# reports is deterministic rather than repository-configured. The producer
# suite (tests/test_release_revision_binding.py) proves that behavior end to
# end against a real repository with a sentinel fsmonitor and a
# `status.showUntrackedFiles=no` config; these gates pin the structure, so the
# argv cannot drift back toward the unsafe shape without this policy file
# changing in the same commit.
RELEASE_IDENTITY_SOURCE = "src/maintenance/release_source_identity.py"

# The exact live argv of the three probe calls, read from the tree rather
# than copied from issue text.
RELEASE_IDENTITY_GIT_ARGV: tuple[tuple[str, ...], ...] = (
    ("git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD"),
    ("git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD^{tree}"),
    (
        "git",
        "-c",
        "core.fsmonitor=false",
        "--no-optional-locks",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    ),
)

# The command vocabulary the written safety policy must keep naming: the
# fsmonitor override, the non-locking flag, and the deterministic
# porcelain/untracked flags. Machine-consumed command tokens, not prose
# wording -- the same standard the junction rationale gate applies.
RELEASE_IDENTITY_ISOLATION_TOKENS = (
    "core.fsmonitor=false",
    "--no-optional-locks",
    "--porcelain=v1",
    "--untracked-files=all",
)


class ReleaseSourceIdentityGitBoundary(unittest.TestCase):
    """The st_01a06650 finding cannot regress silently: the argv is pinned.

    The behavioral proof lives in the release suite: a sentinel fsmonitor and a
    `status.showUntrackedFiles=no` config are both overridden and the probe
    still reports the untracked file as dirty. Behavior is proven once, per
    run, against a real repository; structure is what decides whether the
    NEXT change can quietly drop the isolation. Every gate here reads
    `src/` as an abstract syntax tree, so a comment claiming the flags are
    there cannot satisfy them and removing the flags cannot pass them.
    """

    def _git_argv(self) -> list[tuple[str | None, ...]]:
        """Every constant-headed `git` argv literal in the identity module."""
        return [
            tuple(elements)
            for relative_path, _lineno, elements in _argv_literals()
            if relative_path == RELEASE_IDENTITY_SOURCE and elements[0] == "git"
        ]

    def test_the_probe_runs_exactly_the_three_isolated_git_argv(self) -> None:
        argv = self._git_argv()
        self.assertNotIn(
            None,
            [element for line in argv for element in line],
            f"INVARIANT 1 (no hidden process spawn): {RELEASE_IDENTITY_SOURCE} builds a `git` "
            f"argv with a non-literal element, so this gate cannot prove which flags run. "
            f"Spell every probe element as a literal.",
        )
        self.assertEqual(
            argv,
            [tuple(expected) for expected in RELEASE_IDENTITY_GIT_ARGV],
            f"INVARIANT 1 (no hidden process spawn): {RELEASE_IDENTITY_SOURCE} no longer runs "
            f"exactly the three isolated git argv recorded in RELEASE_IDENTITY_GIT_ARGV in "
            f"{THIS_TEST}. The probe's whole safety story is that argv shape: fsmonitor disabled "
            f"on every call, no optional index lock, deterministic porcelain and untracked "
            f"visibility on the status call. Changing it is a safety-policy change -- update "
            f"RELEASE_IDENTITY_GIT_ARGV, GIT_ARGV_ALLOWLIST, and the PROCESS_SPAWN_ALLOWLIST "
            f"rationale together, deliberately, with a security reason.",
        )

    def test_every_probe_argv_disables_fsmonitor_and_overrides_no_other_config(self) -> None:
        """`-c core.fsmonitor=false` on every call, and nothing else via `-c`.

        The fsmonitor override must ride every probe argv -- the rev-parse
        calls read objects only, but git still consults repo config on the way
        in, and the review found the status call executing repo-configured
        code. And the override must stay the ONLY config the probe sets: a
        second `-c` key would be a broader config channel than the finding
        justified. Checked repo-wide, not just in this module, so a git argv
        anywhere in `src/` cannot grow a config override this gate never
        blessed.
        """
        for relative_path, lineno, elements in _argv_literals():
            if elements[0] != "git":
                continue
            overrides = [
                elements[index + 1]
                for index in range(len(elements) - 1)
                if elements[index] == "-c"
            ]
            offending = sorted(set(overrides) - {"core.fsmonitor=false"})
            self.assertEqual(
                offending,
                [],
                f"INVARIANT 1 (no hidden process spawn): {relative_path} line {lineno} builds a "
                f"`git` argv whose `-c` config overrides include {offending}. The only sanctioned git "
                f"config override in `src/` is `core.fsmonitor=false` on the release-identity "
                f"probe (st_01a06650): one flag, one purpose, disabling repo-configured "
                f"hook-shaped config on an identity-only read. A broader override needs a new "
                f"security reason and a wider gate in {THIS_TEST}.",
            )
        for argv in self._git_argv():
            overrides = [
                argv[index + 1]
                for index in range(len(argv) - 1)
                if argv[index] == "-c"
            ]
            self.assertEqual(
                overrides,
                ["core.fsmonitor=false"],
                f"INVARIANT 1 (no hidden process spawn): a release-identity probe argv in "
                f"{RELEASE_IDENTITY_SOURCE} carries `-c` config overrides {overrides}. Every "
                f"probe argv must carry exactly one -- `core.fsmonitor=false`, nothing else.",
            )

    def test_the_status_probe_is_non_locking_and_reports_deterministic_untracked_state(
        self,
    ) -> None:
        status_argv = [argv for argv in self._git_argv() if "status" in argv]
        self.assertEqual(
            len(status_argv),
            1,
            f"INVARIANT 1 (no hidden process spawn): {RELEASE_IDENTITY_SOURCE} builds "
            f"{len(status_argv)} `git status` argv. Exactly one status probe is admitted; "
            f"a second one needs its own safety rationale.",
        )
        argv = status_argv[0]
        for flag in ("--no-optional-locks", "--porcelain=v1", "--untracked-files=all"):
            self.assertIn(
                flag,
                argv,
                f"INVARIANT 1 (no hidden process spawn): the release-identity status probe no "
                f"longer carries {flag!r}. That flag is part of the st_01a06650 boundary: "
                f"`--no-optional-locks` keeps a read-only probe from touching the index lock, and "
                f"`--porcelain=v1` / `--untracked-files=all` make the reported dirtiness "
                f"deterministic against repository config like status.showUntrackedFiles. If the "
                f"locking mechanism legitimately moves (flag to environment or back), update "
                f"RELEASE_IDENTITY_GIT_ARGV and these gates together, deliberately.",
            )

    def test_the_probe_names_no_remote_or_mutating_verb(self) -> None:
        for argv in self._git_argv():
            offending = sorted(set(argv) & FORBIDDEN_GIT_VERBS)
            self.assertEqual(
                offending,
                [],
                f"INVARIANT 3 (no remote mutation): the release-identity probe in "
                f"{RELEASE_IDENTITY_SOURCE} runs `git {' '.join(str(element) for element in argv)}`"
                f", which carries the forbidden verb(s) {offending}. An identity probe reads; it "
                f"never publishes to or moves a remote.",
            )

    def test_the_allowlist_rationale_names_the_live_isolated_argv(self) -> None:
        """The written safety policy must describe the argv the code runs.

        The PROCESS_SPAWN_ALLOWLIST entry is the safety policy for this spawn;
        if it stops naming the isolation vocabulary, policy and spawn surface
        have drifted apart. The asserted strings are the command tokens -- the
        fsmonitor override, the non-locking flag, the porcelain format, and
        the untracked-files policy -- not prose wording.
        """
        self.assertIn(
            RELEASE_IDENTITY_SOURCE,
            PROCESS_SPAWN_ALLOWLIST,
            f"INVARIANT 1 (no hidden process spawn): {RELEASE_IDENTITY_SOURCE} lost its "
            f"PROCESS_SPAWN_ALLOWLIST entry in {THIS_TEST} but still spawns the release-identity "
            f"git probe. Restore the entry with the isolated-argv rationale.",
        )
        rationale = PROCESS_SPAWN_ALLOWLIST[RELEASE_IDENTITY_SOURCE]
        for token in RELEASE_IDENTITY_ISOLATION_TOKENS:
            self.assertIn(
                token,
                rationale,
                f"INVARIANT 1 (no hidden process spawn): the PROCESS_SPAWN_ALLOWLIST entry for "
                f"{RELEASE_IDENTITY_SOURCE} does not name {token!r}, but the module runs it on "
                f"every probe (or, for the status-only flags, on the status probe). The allowlist "
                f"rationale is the written safety policy for this spawn; update it to describe "
                f"the live isolated argv instead of a retired bare one.",
            )


# --------------------------------------------------------------------------
# INVARIANT 4 -- no raw prompt persisted under .omh
# --------------------------------------------------------------------------

# Deliberately not a word, a path, or anything a template, a fixture, or a
# routing table could produce. If this string is on disk, it came from the
# message and nowhere else.
RAW_MESSAGE_SENTINEL = "Zq7XvbwkPfmdGhntrlys9314"

# Concrete enough to clear the record-readiness gate (a named file plus real
# requirements), so a record is actually written and the test proves absence
# rather than proving nothing happened.
SENTINEL_MESSAGE = (
    f"refactor src/omh/parser.py to split the tokenizer function into two helpers {RAW_MESSAGE_SENTINEL}"
)

# `--include-message-full` selects message_context_mode "full",
# `--include-message` selects "bounded". Both are driven; "full" is the mode
# that interpolates the verbatim message into the returned prompt, and so is
# the mode where a careless write would leak it.
MESSAGE_CONTEXT_FLAGS = (("full", "--include-message-full"), ("bounded", "--include-message"))


class NoRawPromptPersistedUnderOmhHome(unittest.TestCase):
    """INVARIANT 4 (GENUINE NEW COVERAGE): the message never lands on disk.

    The repo asserts `raw_prompt_stored: False` on individual record families --
    the goal ledger, the fanout contract, the workflow trace, the context brief.
    Every one of those is a *flag inside one record*. No test has ever driven a
    real message through the delegation lane and then looked at what the run
    actually left behind, so a new artifact family could have started writing
    the prompt and every existing assertion would still have passed.

    This drives the public CLI end to end against a temporary OMH home, then
    walks every file under it. Two things are asserted together, because either
    alone is worthless:

    * the sentinel appears in no file -- the raw message was not persisted;
    * the message SHA-256 does appear -- a record really was written, so the
      absence above is evidence and not an empty directory.

    The in-memory / on-disk distinction is the point, and it is asserted rather
    than assumed. With `message_context_mode == "full"` the delegation payload
    legitimately contains the verbatim message: it is interpolated into the
    executor prompt template that is *returned to the caller* so a human can
    paste it. That is not a violation. The contract is "not persisted under
    .omh", so the test requires the sentinel to be present in the returned
    prompt and absent from every file.
    """

    def _drive(self, tmp: str, flag: str) -> tuple[dict, Path]:
        root = Path(tmp)
        omh_home = root / ".omh"
        status, stdout, stderr = run_cli(
            [
                "--omh-home",
                str(omh_home),
                "--hermes-home",
                str(root / ".hermes"),
                "coding",
                "delegate",
                "--record",
                "--force-record",
                "--executor",
                "codex",
                flag,
                SENTINEL_MESSAGE,
            ]
        )
        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        return json.loads(stdout), omh_home

    def test_no_file_under_the_omh_home_contains_the_raw_message(self) -> None:
        message_sha = hashlib.sha256(SENTINEL_MESSAGE.encode("utf-8")).hexdigest()
        variants = (RAW_MESSAGE_SENTINEL, RAW_MESSAGE_SENTINEL.lower(), RAW_MESSAGE_SENTINEL.upper())

        for mode, flag in MESSAGE_CONTEXT_FLAGS:
            with self.subTest(message_context_mode=mode), TemporaryDirectory() as tmp:
                payload, omh_home = self._drive(tmp, flag)

                self.assertEqual(
                    payload["message_context"]["raw_content_included"],
                    mode == "full",
                    f"INVARIANT 4: the run did not actually exercise message_context_mode {mode!r}, "
                    f"so its result proves nothing. Check that {flag} still selects that mode.",
                )
                self.assertIn(
                    "run",
                    payload.get("runtime", {}),
                    f"INVARIANT 4 (no raw prompt persisted under .omh): the delegation was not "
                    f"recorded (runtime says {payload.get('runtime')}), so walking the OMH home "
                    f"would prove nothing. Adjust SENTINEL_MESSAGE in {THIS_TEST} so it still "
                    f"clears the record-readiness gate.",
                )

                written = sorted(path for path in omh_home.rglob("*") if path.is_file())
                self.assertTrue(
                    written,
                    "INVARIANT 4 (no raw prompt persisted under .omh): nothing was written under the "
                    "OMH home, so 'the message is not on disk' is vacuously true. The test must "
                    "observe a real record before it can assert an absence.",
                )

                leaked: list[str] = []
                carrying_sha: list[str] = []
                for path in written:
                    blob = path.read_bytes()
                    if any(variant.encode("utf-8") in blob for variant in variants):
                        leaked.append(path.relative_to(omh_home).as_posix())
                    if message_sha.encode("ascii") in blob:
                        carrying_sha.append(path.relative_to(omh_home).as_posix())

                self.assertEqual(
                    leaked,
                    [],
                    f"INVARIANT 4 (no raw prompt persisted under .omh): with message_context_mode "
                    f"{mode!r} the raw user message was written verbatim into {leaked}. omh records "
                    f"the SHA-256 and the length of a message, never its text -- that is what lets a "
                    f"user paste a private prompt into a chat surface. Replace the raw text in those "
                    f"artifacts with `message_sha256` plus `message_length`, and keep the verbatim "
                    f"text in the returned in-memory payload only.",
                )
                self.assertTrue(
                    carrying_sha,
                    f"INVARIANT 4 (no raw prompt persisted under .omh): no file under the OMH home "
                    f"carries the message SHA-256, so the clean result above may just mean nothing "
                    f"was recorded. Files seen: "
                    f"{[path.relative_to(omh_home).as_posix() for path in written]}.",
                )

    def test_full_mode_still_returns_the_verbatim_prompt_in_memory(self) -> None:
        """The rule is 'not persisted', not 'never rendered' -- pin the difference.

        Without this, INVARIANT 4 could be satisfied tomorrow by dropping the
        verbatim message from the prompt template altogether, which would keep
        the gate green while breaking the feature it is guarding.
        """
        with TemporaryDirectory() as tmp:
            payload, omh_home = self._drive(tmp, "--include-message-full")
            self.assertIn(
                RAW_MESSAGE_SENTINEL,
                str(payload.get("executor_handoff_prompt", "")),
                "INVARIANT 4: message_context_mode 'full' must still interpolate the verbatim "
                "message into the prompt returned in memory. If it no longer does, the absence "
                "check above stopped testing anything.",
            )
            self.assertNotIn(
                RAW_MESSAGE_SENTINEL,
                "".join(
                    path.read_text(encoding="utf-8", errors="replace")
                    for path in sorted(omh_home.rglob("*"))
                    if path.is_file()
                ),
                "INVARIANT 4 (no raw prompt persisted under .omh): the prompt that carries the "
                "verbatim message was also written to disk. It may be returned; it may not be "
                "stored.",
            )


# --------------------------------------------------------------------------
# INVARIANT 5 -- merge authority is unreachable
# --------------------------------------------------------------------------

# `permission_profile_for` takes only these five inputs, and every one is
# finite, so the sweep below is exhaustive rather than a sample. The empty
# strings probe the unknown-value paths.
_DENIED_VALUES = (True, False)
_DELEGATION_ACTIONS = (*DELEGATION_ACTIONS, "")
_WORK_OWNER_MODES = (*WORK_OWNER_MODES, "")
_INTENTS = (*CODING_INTENTS, "")
_BOOLEANS = (True, False)


class MergeAuthorityIsUnreachable(unittest.TestCase):
    """INVARIANT 5 (REGRESSION PREVENTION): no input yields merge authority.

    `PERMISSION_PROFILES` includes `full_loop`, and `full_loop` does grant
    `merge`. So the profile vocabulary can express merge authority; what this
    proves is that omh's delegation lane cannot *select* it. Two independent
    barriers have to fail before a handoff could carry merge:

    1. `permission_profile_for` never returns a merge-granting profile. Its
       range over every input combination is {observe_only, handoff_only,
       execute_with_gates}; `full_loop` is unreachable from it.
    2. `required_actions_for` never asks for `merge`, and the envelope builder
       forbids everything outside the required set -- so merge would still be
       stripped even if barrier 1 fell.

    Existing tests spot-check `merge_authority == "disabled"` on a handful of
    constructed cases. This proves it from the code, over the full cartesian
    product of the inputs, so a new branch in the selection helper cannot open
    the door for one combination nobody thought to write a case for.
    """

    def test_no_selectable_permission_profile_grants_merge(self) -> None:
        selectable = {
            permission_profile_for(
                denied=denied,
                delegation_action=action,
                work_owner_mode=owner,
                dispatchable=dispatchable,
                choice_required=choice_required,
            )
            for denied, action, owner, dispatchable, choice_required in itertools.product(
                _DENIED_VALUES, _DELEGATION_ACTIONS, _WORK_OWNER_MODES, _BOOLEANS, _BOOLEANS
            )
        }
        self.assertTrue(selectable)
        for profile in sorted(selectable):
            envelope = build_authority_envelope(permission_profile=profile)
            self.assertEqual(
                envelope["merge_authority"],
                "disabled",
                f"INVARIANT 5 (merge authority is unreachable): `permission_profile_for` can select "
                f"the {profile!r} profile, and that profile grants merge authority. omh prepares a "
                f"handoff; the operator merges. Either stop selecting {profile!r} from the delegation "
                f"lane, or remove `merge` from its allowed actions in "
                f"src/workflows/goal_loop.py.",
            )
            self.assertNotIn(
                "merge",
                envelope["allowed_actions"],
                f"INVARIANT 5 (merge authority is unreachable): the selectable profile {profile!r} "
                f"lists `merge` in allowed_actions. Remove it, or stop selecting the profile.",
            )

    def test_every_derived_authority_envelope_disables_merge(self) -> None:
        checked = 0
        for denied, action, intent, review, owner, executor, dispatchable, choice in itertools.product(
            _DENIED_VALUES,
            _DELEGATION_ACTIONS,
            _INTENTS,
            _BOOLEANS,
            _WORK_OWNER_MODES,
            (None, "codex", "claude-code"),
            _BOOLEANS,
            _BOOLEANS,
        ):
            envelope = build_task_authority_envelope(
                denied=denied,
                delegation_action=action,
                intent=intent,
                review_required=review,
                work_owner_mode=owner,
                selected_executor_profile=executor,
                dispatchable=dispatchable,
                choice_required=choice,
            )
            checked += 1
            context = (
                f"denied={denied} action={action!r} intent={intent!r} review_required={review} "
                f"work_owner_mode={owner!r} executor={executor!r} dispatchable={dispatchable} "
                f"choice_required={choice}"
            )
            remedy = (
                "A prepared handoff must never carry merge authority. Find the branch that admitted "
                "it in src/coding/action_gate.py -- `permission_profile_for` or "
                "`required_actions_for` -- and close it. Do not relax this test."
            )
            self.assertEqual(
                envelope["merge_authority"],
                "disabled",
                f"INVARIANT 5 (merge authority is unreachable): merge_authority became "
                f"{envelope['merge_authority']!r} for {context}. {remedy}",
            )
            self.assertNotIn(
                "merge",
                envelope["allowed_actions"],
                f"INVARIANT 5 (merge authority is unreachable): `merge` entered allowed_actions for "
                f"{context}. {remedy}",
            )
            self.assertNotIn(
                "merge",
                envelope["mutation_rights"],
                f"INVARIANT 5 (merge authority is unreachable): `merge` entered mutation_rights for "
                f"{context}. {remedy}",
            )
        # Guards the sweep itself: a vocabulary shrinking to nothing would make
        # every assertion above vacuous and the test would still pass.
        self.assertGreater(checked, 1000, "the input sweep collapsed; INVARIANT 5 is no longer proving anything")

    def test_the_required_action_set_never_asks_for_merge(self) -> None:
        """Barrier 2, checked on its own so barrier 1 cannot mask its failure."""
        for denied, action, intent, review, dispatchable, choice in itertools.product(
            _DENIED_VALUES, _DELEGATION_ACTIONS, _INTENTS, _BOOLEANS, _BOOLEANS, _BOOLEANS
        ):
            required = required_actions_for(
                denied=denied,
                delegation_action=action,
                intent=intent,
                review_required=review,
                dispatchable=dispatchable,
                choice_required=choice,
            )
            self.assertNotIn(
                "merge",
                required,
                f"INVARIANT 5 (merge authority is unreachable): `required_actions_for` asked for "
                f"`merge` (denied={denied} action={action!r} intent={intent!r} "
                f"review_required={review} dispatchable={dispatchable} choice_required={choice}). "
                f"No task omh prepares requires merge authority. Remove the branch in "
                f"src/coding/action_gate.py.",
            )

    def test_merge_is_a_mutating_action_so_the_checks_above_have_teeth(self) -> None:
        """If `merge` left MUTATING_ACTIONS, the mutation_rights assertion would go quiet."""
        self.assertIn(
            "merge",
            MUTATING_ACTIONS,
            "INVARIANT 5 (merge authority is unreachable): `merge` was removed from MUTATING_ACTIONS "
            "in src/coding/action_gate.py, which silently disarms the mutation_rights half of this "
            "invariant. Put it back.",
        )

    def test_the_profile_vocabulary_still_contains_a_merge_granting_profile(self) -> None:
        """Names the risk this invariant guards, so it cannot become tautological.

        If no profile anywhere granted merge, the sweeps above would pass for a
        reason that has nothing to do with the delegation lane's own choices.
        """
        granting = [
            profile
            for profile in permission_profiles()
            if build_authority_envelope(permission_profile=profile)["merge_authority"] == "granted"
        ]
        self.assertTrue(
            granting,
            "INVARIANT 5 (merge authority is unreachable): no permission profile grants merge at all "
            "any more, so this invariant now passes for free. That may be a fine change -- if so, "
            f"simplify or delete MergeAuthorityIsUnreachable in {THIS_TEST} rather than leaving a "
            "gate that proves nothing.",
        )


if __name__ == "__main__":
    unittest.main()
