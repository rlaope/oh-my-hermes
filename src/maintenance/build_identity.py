"""Diagnostic build identity for the ``omh`` command that is actually running.

``omh --version`` and ``omh doctor`` both render this contract. The semantic
package version alone cannot tell two same-version checkouts apart, cannot say
whether a development tree carries uncommitted changes, and cannot distinguish
a stale command earlier on ``PATH`` from the checkout the operator is editing.
This module answers "which code is behind the command that just ran".

Three rules shape the implementation:

- **The package's own source location decides, never the caller's directory.**
  Every probe starts from this module's own file, walks up to the repository
  that ships it, and confirms that repository declares this project in its
  ``pyproject.toml``. Running ``git rev-parse`` in the caller's working
  directory would happily identify an unrelated repository, and a virtualenv
  nested inside somebody else's checkout would borrow that project's revision.
  The project declaration check is what closes both holes.
- **Nothing is invented.** A source archive without ``.git``, an installed
  wheel with no stamped identity, a missing ``git`` binary that also leaves no
  readable refs: each returns ``identity_status: unavailable`` with the
  observed ``install_kind`` and a ``reason``, never a guessed revision.
- **Only identity is serialized.** The full commit SHA and a clean/dirty
  result, and nothing else: no branch name, no remote URL, no diff, no changed
  file list, no environment data.

The payload is diagnostic provenance. It is not release evidence, and it never
claims the identified revision was tested, reviewed, passed CI, or published --
``omh_release_source_identity/v1`` in ``release_source_identity.py`` is the
separate contract that binds a *published* revision to release evidence.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit
from urllib.request import url2pathname

from ..version import __version__

BUILD_IDENTITY_SCHEMA = "build_identity/v1"
BUILD_IDENTITY_STAMP_SCHEMA = "build_identity_stamp/v1"

# The distribution this package is published as, normalized the way
# `importlib.metadata` names are compared (lowercase, `_` folded to `-`).
DISTRIBUTION_NAME = "oh-my-hermes"
# Packaging may ship this file inside the installed package to give a built
# artifact an immutable identity. Nothing in this repository writes one today,
# so shipped wheels report `unavailable` / `no_stamped_identity`; see
# docs/INSTALLATION.md. The reader exists so a packager that does stamp an
# artifact is read rather than ignored.
STAMP_FILE_NAME = "_build_identity.json"

INSTALL_KINDS = (
    "source_checkout",
    "editable_install",
    "installed_package",
    "standalone_artifact",
    "unknown",
)
IDENTITY_STATUSES = ("verified", "unavailable")
IDENTITY_SOURCES = ("git_command", "git_refs", "stamped_artifact", "none")
UNAVAILABLE_REASONS = (
    "git_unavailable",
    "git_probe_failed",
    "no_stamped_identity",
    "malformed_stamped_identity",
    "no_source_identity",
)

BUILD_IDENTITY_CLAIM_BOUNDARY = (
    "Diagnostic provenance for the command that ran. It is not evidence that this revision "
    "was tested, reviewed, passed CI, was published, or behaved correctly at runtime."
)

_INSTALL_KIND_LABELS = {
    "source_checkout": "source checkout",
    "editable_install": "editable install",
    "installed_package": "installed package",
    "standalone_artifact": "standalone artifact",
    "unknown": "unknown install",
}
_ORIGIN_LABELS = {
    "source_checkout": "source",
    "editable_install": "editable",
    "installed_package": "build",
    "standalone_artifact": "build",
    "unknown": "build",
}
_REASON_LABELS = {
    "git_unavailable": "git not available",
    "git_probe_failed": "git probe failed",
    "no_stamped_identity": "no stamped identity",
    "malformed_stamped_identity": "malformed stamped identity",
    "no_source_identity": "no source identity",
}
_DIRTY_WORDS = {"clean": "clean", "dirty": "dirty", "unknown": "dirty state unknown"}

_GIT_TIMEOUT_SECONDS = 15
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHORT_SHA_CHARS = 8
_DEFAULT_GIT_RUNNER = subprocess.run
# Reading `.git` by hand is bounded on purpose: a packed-refs file is line
# oriented and small, and refusing to read an oversized one keeps a corrupt or
# hostile repository from being loaded into memory by `omh --version`.
_MAX_REF_FILE_BYTES = 4 * 1024 * 1024


def probe_build_identity(
    *,
    package_root: str | Path | None = None,
    argv0: str | None = None,
    runner: Callable[..., Any] = _DEFAULT_GIT_RUNNER,
    which: Callable[[str], str | None] = shutil.which,
    distributions: Callable[[], Iterable[Any]] | None = None,
    frozen: bool | None = None,
    version: str | None = None,
) -> dict[str, object]:
    """Build the ``build_identity/v1`` record for the running command.

    ``package_root`` defaults to the installed package directory this module
    belongs to, which is what makes the result describe the code that ran
    rather than the directory the operator happened to be standing in. Every
    other keyword is a seam so the states this contract has to cover -- missing
    ``git``, a detached HEAD, an archive with no ``.git``, a stamped artifact,
    several ``omh`` commands on ``PATH`` -- are testable without those
    conditions existing on the machine running the tests.
    """
    root = _resolved_package_root(package_root)
    package_version = str(version) if version is not None else __version__
    command_path, command_path_status = resolve_command_path(argv0, which=which)
    source = _probe_source_tree(root, runner=runner, which=which)

    repo_root = source["repo_root"]
    if repo_root is not None:
        install_kind = _work_tree_install_kind(repo_root, distributions)
    else:
        install_kind = _installed_install_kind(root, frozen=frozen)

    commit_sha = source["commit_sha"]
    dirty = source["dirty"]
    identity_source = str(source["identity_source"])
    reason = str(source["reason"])

    if commit_sha is None and repo_root is None:
        stamp = read_stamped_identity(root)
        if stamp["status"] == "verified":
            commit_sha = stamp["commit_sha"]
            dirty = stamp["dirty"]
            identity_source = "stamped_artifact"
            reason = ""
        elif stamp["status"] == "malformed":
            reason = "malformed_stamped_identity"
        elif install_kind == "unknown":
            reason = "no_source_identity"
        else:
            reason = "no_stamped_identity"

    identity_status = "verified" if commit_sha is not None else "unavailable"
    if identity_status == "verified":
        reason = ""
    identity = {
        "schema_version": BUILD_IDENTITY_SCHEMA,
        "version": package_version,
        "install_kind": install_kind,
        "command_path": command_path,
        "command_path_status": command_path_status,
        "identity_status": identity_status,
        "identity_source": identity_source if identity_status == "verified" else "none",
        "commit_sha": commit_sha,
        "dirty": dirty,
        "dirty_status": _dirty_status(dirty) if identity_status == "verified" else "unknown",
        "reason": reason,
        "claim_boundary": BUILD_IDENTITY_CLAIM_BOUNDARY,
    }
    identity["summary"] = build_identity_summary(identity)
    return identity


def build_identity_summary(identity: dict[str, object]) -> str:
    """Render the one-line human form used by `--version` and `omh doctor`."""
    version = str(identity.get("version", ""))
    install_kind = str(identity.get("install_kind", "unknown"))
    if identity.get("identity_status") == "verified":
        origin = _ORIGIN_LABELS.get(install_kind, "build")
        short_sha = str(identity.get("commit_sha", ""))[:_SHORT_SHA_CHARS]
        dirty_word = _DIRTY_WORDS[_dirty_status(identity.get("dirty"))]
        return f"omh {version} ({origin} {short_sha}, {dirty_word})"
    kind_label = _INSTALL_KIND_LABELS.get(install_kind, _INSTALL_KIND_LABELS["unknown"])
    reason_label = _REASON_LABELS.get(str(identity.get("reason", "")), "reason not recorded")
    return f"omh {version} (build identity unavailable: {kind_label}, {reason_label})"


def resolve_command_path(
    argv0: str | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[str | None, str]:
    """Resolve the command that actually ran, from its own ``argv[0]``.

    Doctor already reports whether `omh` is discoverable on ``PATH`` and which
    entry wins there. This answers the different question a stale-command
    report needs: when several `omh` commands exist, which one produced this
    output. An absolute ``argv[0]`` is therefore trusted over the ``PATH``
    lookup, because the operator may have invoked a command that ``PATH`` would
    never have selected.
    """
    raw = sys.argv[0] if argv0 is None else argv0
    text = str(raw or "").strip()
    if not text:
        return None, "unresolved"
    if _looks_like_path(text):
        # Only a name carrying a separator is a path. A bare `omh` must go
        # through the lookup even when a directory of that name happens to sit
        # in the working directory, or the identity would name a folder that
        # never ran anything.
        candidate = Path(text).expanduser()
        if candidate.exists():
            return str(candidate.resolve()), "resolved"
    located = which(text)
    if located:
        return str(Path(located).resolve()), "resolved"
    return None, "unresolved"


def read_stamped_identity(package_root: Path) -> dict[str, object]:
    """Read an identity a packager stamped into the installed package.

    Returns ``status`` ``absent`` (no stamp), ``malformed`` (a stamp that does
    not carry a usable full commit SHA under the expected schema), or
    ``verified``. A malformed stamp is reported as malformed rather than
    treated as absent, so a broken packaging step is visible instead of quietly
    reading like an ordinary unstamped wheel.
    """
    path = Path(package_root) / STAMP_FILE_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {"status": "absent", "commit_sha": None, "dirty": None}
    try:
        data = json.loads(raw)
    except ValueError:
        return {"status": "malformed", "commit_sha": None, "dirty": None}
    if not isinstance(data, dict):
        return {"status": "malformed", "commit_sha": None, "dirty": None}
    if str(data.get("schema_version", "")) != BUILD_IDENTITY_STAMP_SCHEMA:
        return {"status": "malformed", "commit_sha": None, "dirty": None}
    commit_sha = str(data.get("commit_sha", "") or "")
    if not _FULL_SHA_RE.match(commit_sha):
        return {"status": "malformed", "commit_sha": None, "dirty": None}
    dirty = data.get("dirty")
    return {
        "status": "verified",
        "commit_sha": commit_sha,
        "dirty": dirty if isinstance(dirty, bool) else None,
    }


def declares_this_project(root: Path) -> bool:
    """Whether ``root`` is the repository that ships this package.

    The guard against identifying the wrong repository. A wheel installed into
    a virtualenv that lives inside an unrelated git checkout is the concrete
    case: without this, walking up from the package directory finds that
    project's ``.git`` and reports its revision as the command's identity.
    """
    try:
        raw = (Path(root) / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError:
        return False
    project = data.get("project")
    if not isinstance(project, dict):
        return False
    return _normalized_distribution_name(str(project.get("name", ""))) == DISTRIBUTION_NAME


def _resolved_package_root(package_root: str | Path | None) -> Path:
    if package_root is not None:
        return Path(package_root).expanduser().resolve()
    # This module lives at `<package>/maintenance/build_identity.py` in a wheel
    # install and at `<repo>/src/maintenance/build_identity.py` in a checkout.
    # Both make `parents[1]` the directory to look for a stamp in and to walk
    # up from when locating the repository.
    return Path(__file__).resolve().parents[1]


def _probe_source_tree(
    root: Path,
    *,
    runner: Callable[..., Any],
    which: Callable[[str], str | None],
) -> dict[str, object]:
    git_binary = which("git")
    if git_binary:
        probed = _probe_with_git(root, runner=runner)
        if probed is not None:
            return probed
    return _probe_from_git_files(root, git_available=bool(git_binary))


def _probe_with_git(root: Path, *, runner: Callable[..., Any]) -> dict[str, object] | None:
    # Every argv below is spelled out in full so the enumerated-git-command
    # gate can read the subcommand as a literal. `-c core.fsmonitor=false` is
    # the only repository config this identity read overrides, so a
    # repo-configured fsmonitor cannot execute anything on its behalf.
    toplevel = _git_output(
        runner, root, ["git", "-c", "core.fsmonitor=false", "rev-parse", "--show-toplevel"]
    )
    if toplevel is None or not toplevel.strip():
        return None
    repo_root = Path(toplevel.strip()).expanduser()
    try:
        repo_root = repo_root.resolve()
    except OSError:
        return None
    if not declares_this_project(repo_root):
        return None
    head = _git_output(runner, root, ["git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD"])
    status = _git_output(
        runner,
        root,
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "--no-optional-locks",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
    )
    if head is None or not _FULL_SHA_RE.match(head.strip()) or status is None:
        # The work tree is confirmed but the revision is not. An unborn branch
        # and a failing status call both land here; neither may be reported as
        # a revision, so identity stays unavailable while install kind stands.
        return {
            "repo_root": repo_root,
            "commit_sha": None,
            "dirty": None,
            "identity_source": "none",
            "reason": "git_probe_failed",
        }
    changed = [line for line in status.splitlines() if line.strip()]
    return {
        "repo_root": repo_root,
        "commit_sha": head.strip(),
        "dirty": bool(changed),
        "identity_source": "git_command",
        "reason": "",
    }


def _probe_from_git_files(root: Path, *, git_available: bool) -> dict[str, object]:
    """Resolve the revision from ``.git`` directly when git cannot be run.

    A container without a ``git`` binary is a real support case, and refusing
    to identify the checkout there would leave the operator with the same
    version-only output the issue is about. Reading ``HEAD`` and the ref it
    names is deterministic; deriving a clean/dirty result is not, so dirty
    state stays unknown on this path rather than being guessed.
    """
    repo_root = _walk_to_project_repo(root)
    if repo_root is None:
        return {
            "repo_root": None,
            "commit_sha": None,
            "dirty": None,
            "identity_source": "none",
            "reason": "",
        }
    commit_sha = _head_sha_from_git_files(repo_root)
    if commit_sha is None:
        return {
            "repo_root": repo_root,
            "commit_sha": None,
            "dirty": None,
            "identity_source": "none",
            "reason": "git_probe_failed" if git_available else "git_unavailable",
        }
    return {
        "repo_root": repo_root,
        "commit_sha": commit_sha,
        "dirty": None,
        "identity_source": "git_refs",
        "reason": "",
    }


def _walk_to_project_repo(root: Path) -> Path | None:
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists() and declares_this_project(candidate):
            return candidate
    return None


def _git_directories(repo_root: Path) -> tuple[Path, Path] | None:
    """The work tree's git directory and the common directory it shares.

    A linked worktree records ``gitdir:`` in a ``.git`` file and keeps its own
    ``HEAD`` beside a ``commondir`` pointer, while ``packed-refs`` stays in the
    main repository. Both paths are needed to resolve a ref by hand.
    """
    entry = repo_root / ".git"
    git_dir: Path | None = None
    if entry.is_dir():
        git_dir = entry
    elif entry.is_file():
        text = _read_small_text(entry)
        if text is None:
            return None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("gitdir:"):
                pointed = Path(stripped.split(":", 1)[1].strip()).expanduser()
                git_dir = pointed if pointed.is_absolute() else (repo_root / pointed)
                break
    if git_dir is None or not git_dir.is_dir():
        return None
    common_dir = git_dir
    common_text = _read_small_text(git_dir / "commondir")
    if common_text and common_text.strip():
        pointed = Path(common_text.strip()).expanduser()
        common_dir = pointed if pointed.is_absolute() else (git_dir / pointed)
    return git_dir, common_dir


def _head_sha_from_git_files(repo_root: Path) -> str | None:
    directories = _git_directories(repo_root)
    if directories is None:
        return None
    git_dir, common_dir = directories
    head = _read_small_text(git_dir / "HEAD")
    if head is None:
        return None
    head = head.strip()
    if _FULL_SHA_RE.match(head):
        # A detached HEAD stores the revision directly, which is exactly the
        # identity wanted; no branch name exists and none is needed.
        return head
    if not head.startswith("ref:"):
        return None
    ref = head.split(":", 1)[1].strip()
    if not ref:
        return None
    for base in (git_dir, common_dir):
        loose = _read_small_text(base / Path(ref))
        if loose and _FULL_SHA_RE.match(loose.strip()):
            return loose.strip()
    return _packed_ref_sha(common_dir / "packed-refs", ref)


def _packed_ref_sha(packed_refs: Path, ref: str) -> str | None:
    text = _read_small_text(packed_refs)
    if text is None:
        return None
    for line in text.splitlines():
        if not line or line.startswith(("#", "^")):
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        sha, name = parts[0].strip(), parts[1].strip()
        if name == ref and _FULL_SHA_RE.match(sha):
            return sha
    return None


def _read_small_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_REF_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _work_tree_install_kind(
    repo_root: Path,
    distributions: Callable[[], Iterable[Any]] | None,
) -> str:
    for editable_root in _editable_distribution_roots(distributions):
        if editable_root == repo_root:
            return "editable_install"
    return "source_checkout"


def _editable_distribution_roots(
    distributions: Callable[[], Iterable[Any]] | None,
) -> tuple[Path, ...]:
    """Checkouts an editable install of this distribution points at.

    PEP 610 records the origin of a `pip install -e` / `uv` editable install in
    ``direct_url.json``, which is the same signal `omh setup` reads to name the
    real owner of an install. Matching it against the discovered repository is
    what separates "the operator is running an editable install of this
    checkout" from "the operator is running the checkout directly".
    """
    source = importlib.metadata.distributions if distributions is None else distributions
    try:
        found = list(source())
    except (OSError, ValueError):
        return ()
    roots: list[Path] = []
    for distribution in found:
        raw = _editable_direct_url_text(distribution)
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        directory = data.get("dir_info")
        url = str(data.get("url", "") or "")
        if not isinstance(directory, dict) or directory.get("editable") is not True:
            continue
        if not url.startswith("file://"):
            continue
        # url2pathname keeps Windows drive letters (`file:///C:/...`) usable,
        # which a bare unquote of the URL path would not.
        candidate = Path(url2pathname(urlsplit(url).path))
        try:
            roots.append(candidate.resolve())
        except OSError:
            continue
    return tuple(roots)


def _editable_direct_url_text(distribution: Any) -> str | None:
    try:
        metadata = distribution.metadata
        name = str(metadata.get("Name", "") if metadata is not None else "")
    except (OSError, ValueError, KeyError):
        return None
    if _normalized_distribution_name(name) != DISTRIBUTION_NAME:
        return None
    try:
        return distribution.read_text("direct_url.json")
    except (OSError, ValueError):
        return None


def _installed_install_kind(package_root: Path, *, frozen: bool | None) -> str:
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    if is_frozen:
        return "standalone_artifact"
    parts = set(package_root.parts)
    if "site-packages" in parts or "dist-packages" in parts:
        return "installed_package"
    if _has_distribution_metadata_sibling(package_root):
        return "installed_package"
    return "unknown"


def _has_distribution_metadata_sibling(package_root: Path) -> bool:
    """Whether install metadata for this distribution sits beside the package.

    The staged-wheel layout the npm and Homebrew launchers unpack keeps the
    package and its ``.dist-info`` in a plain directory that is not named
    ``site-packages``, so the path check alone would call a real installed
    artifact ``unknown``.
    """
    try:
        return any(package_root.parent.glob("oh_my_hermes-*.dist-info"))
    except OSError:
        return False


def _looks_like_path(command: str) -> bool:
    separators = [os.sep]
    if os.altsep:
        separators.append(os.altsep)
    return any(separator in command for separator in separators)


def _normalized_distribution_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _dirty_status(dirty: object) -> str:
    if dirty is True:
        return "dirty"
    if dirty is False:
        return "clean"
    return "unknown"


def _git_output(runner: Callable[..., Any], root: Path, command: list[str]) -> str | None:
    try:
        completed = runner(
            command,
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(completed, "returncode", 1) != 0:
        return None
    return str(getattr(completed, "stdout", "") or "")
