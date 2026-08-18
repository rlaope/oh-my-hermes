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
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
    "src/coding/git_checkpoint.py": (
        "operator-invoked `omh git` checkpoint, maintenance, and range-diff commands; runs bounded local "
        "Git observations only and never dispatches work or mutates repository state."
    ),
    "src/coding/fanout_dispatch.py": (
        "`omh coding fanout dispatch` -- the one opt-in bridge that spawns local agent CLIs, "
        "documented as the scoped exception in CLAUDE.md."
    ),
    "src/coding/worktree_creator.py": (
        "`git worktree add` for isolated executor workspaces; local, non-remote (see INVARIANT 3)."
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
    "src/coding/_hermes_child_process.py": (
        "private lifecycle helper for the explicitly confirmed Hermes child seam; relays signals, "
        "escalates SIGTERM to SIGKILL, and verifies that the child process group is absent."
    ),
    "src/commands/coding.py": (
        "`git rev-parse <base-ref>` inside the operator-invoked `coding fanout dispatch` command, "
        "to resolve the base commit before the fanout bridge above runs."
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
    "src/install/plugin_loader_observation.py": (
        "`omh doctor` isolated real-Hermes registration probe; reads registered tool/hook names, "
        "dispatches no agent work, and writes only inside a temporary HERMES_HOME."
    ),
    "src/plugin_bundle/omh/tools/evidence_tool.py": (
        "allowlisted local verification-command runner; its allowlist is itself gated below."
    ),
    "src/surfaces/menubar_app.py": (
        "`swiftc` compile plus `launchctl` load for the opt-in macOS menubar helper install."
    ),
    "src/surfaces/menubar_status.py": (
        "`ps -axo` local process scan to render menubar status; reads, spawns no agent."
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
    ("src/coding/git_checkpoint.py", ("status",)): (
        "captures local dirty-state entries for a checkpoint; read-only"
    ),
    ("src/coding/git_checkpoint.py", ("rev-parse",)): (
        "resolves local repository metadata and commit objects for a checkpoint; read-only"
    ),
    ("src/coding/git_checkpoint.py", ("rev-parse", "HEAD")): (
        "captures the local HEAD commit for a checkpoint; read-only"
    ),
    ("src/coding/git_checkpoint.py", ("branch",)): (
        "captures the current local branch for a checkpoint; read-only"
    ),
    ("src/coding/git_checkpoint.py", ("config", "remote.origin.url")): (
        "captures the configured origin URL without invoking a remote Git command; read-only"
    ),
    ("src/coding/git_checkpoint.py", ("config", "maintenance.strategy")): (
        "reports the local maintenance strategy; read-only"
    ),
    ("src/coding/git_checkpoint.py", ("config", "maintenance.auto")): (
        "reports the local maintenance auto setting; read-only"
    ),
    ("src/coding/git_checkpoint.py", ("worktree", "list")): (
        "reports registered worktrees; read-only"
    ),
    ("src/coding/git_checkpoint.py", ("worktree", "prune")): (
        "reports stale worktree candidates with --dry-run only; read-only"
    ),
    ("src/coding/git_checkpoint.py", ("range-diff",)): (
        "compares local patch ranges after a rebase; read-only"
    ),
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
    ("src/commands/coding.py", ("rev-parse",)): (
        "resolves --base-ref to a commit sha inside `coding fanout dispatch`; read-only"
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
