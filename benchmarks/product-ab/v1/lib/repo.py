"""Read-only git plumbing plus the disposable candidate workspace.

Every fact about a pull request's tree comes from the local object store, not
from the network: the corpus pins digests at build time and the run re-derives
the same bytes from git, so a run needs no GitHub access at all.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import hashlib
from pathlib import Path
import shutil
import subprocess

GIT_TIMEOUT_SECONDS = 120


class GitError(RuntimeError):
    """A git command this lane needs did not succeed."""


def git(repo: Path, *arguments: str, timeout: int = GIT_TIMEOUT_SECONDS) -> str:
    """Run one git command and decode its output as UTF-8, explicitly.

    The decode is named rather than inherited. `text=True` alone decodes with
    the ambient locale, and this repository's diffs are not ASCII: twelve of
    the pinned test diffs carry non-ASCII bytes, so the same `git diff` that
    digests one way under a UTF-8 locale raises `UnicodeDecodeError` under
    `LC_ALL=C`. A pinned digest that depends on the caller's environment is
    not a pin, and a build that dies on a differently-configured machine is
    not reproducible. `errors="replace"` keeps a stray undecodable byte from
    killing a build; it cannot silently change a digest, because the
    replacement is deterministic.
    """

    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )
    if completed.returncode:
        raise GitError(
            f"git {' '.join(arguments[:3])} failed with exit {completed.returncode}: "
            f"{completed.stderr.strip()[:400]}"
        )
    return completed.stdout


def git_ok(repo: Path, *arguments: str, timeout: int = GIT_TIMEOUT_SECONDS) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )
    return completed.returncode == 0


def resolve(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def parents(repo: Path, commit: str) -> list[str]:
    line = git(repo, "rev-list", "--parents", "-n", "1", commit).split()
    return line[1:]


def merge_base_of(repo: Path, merge_commit: str) -> str:
    """The commit a candidate starts from.

    A GitHub merge commit has two parents: the base branch tip and the pull
    request head. Their merge base is where the branch actually started. A
    squash or rebase merge has one parent, and that parent is the same thing.
    """

    commit_parents = parents(repo, merge_commit)
    if len(commit_parents) >= 2:
        return git(repo, "merge-base", commit_parents[0], commit_parents[1]).strip()
    if len(commit_parents) == 1:
        return commit_parents[0]
    raise GitError(f"commit has no parent: {merge_commit}")


def changed_paths(repo: Path, base: str, head: str) -> list[tuple[str, str]]:
    """`(status, path)` for every path the range changed, rename-aware."""

    raw = git(repo, "diff", "--name-status", "-M", "--no-renames", base, head)
    rows: list[tuple[str, str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        rows.append((fields[0].strip(), fields[-1].strip()))
    return rows


def numstat(repo: Path, base: str, head: str) -> dict[str, tuple[int, int]]:
    """Added and deleted line counts per path; binary files count as zero."""

    raw = git(repo, "diff", "--numstat", "-M", "--no-renames", base, head)
    counts: dict[str, tuple[int, int]] = {}
    for line in raw.splitlines():
        fields = line.split("\t")
        if len(fields) != 3:
            continue
        added, deleted, path = fields
        if added == "-" or deleted == "-":
            counts[path.strip()] = (0, 0)
            continue
        counts[path.strip()] = (int(added), int(deleted))
    return counts


def diff_text(repo: Path, base: str, head: str, paths: Sequence[str]) -> str:
    if not paths:
        return ""
    # This text is hashed into the corpus. Object-count-dependent short IDs and
    # the operator's display preferences must not change its identity.
    return git(
        repo, "diff", "--no-renames", "--full-index", "--no-color",
        "--no-ext-diff", "--no-textconv", "--default-prefix", "--no-relative",
        "--diff-algorithm=myers", "--indent-heuristic", "--unified=3",
        "--inter-hunk-context=0", base, head, "--", *paths,
    )


def file_bytes(repo: Path, commit: str, path: str) -> bytes | None:
    """One path's exact blob at one commit, or ``None`` when git has no such path.

    Bytes, not text, and every caller that writes a file uses these. Two
    reasons, and the first was found the hard way. A text-mode read decodes
    with the ambient codec, so the first binary blob in this repository's
    history -- a PNG, reached only once the corpus read was widened past the
    recent pull requests -- crashed the build with a `UnicodeDecodeError` from
    inside `subprocess`. The second is Windows: a text-mode round trip
    translates newlines, so the file written into a candidate workspace would
    not be the file git holds, and every digest over it would drift by
    platform.
    """

    completed = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"],
        capture_output=True,
        check=False,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if completed.returncode:
        return None
    return completed.stdout


def file_at(repo: Path, commit: str, path: str) -> str | None:
    """One path's content as text, or ``None`` when it is missing or not text."""

    raw = file_bytes(repo, commit, path)
    if raw is None:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def grep_paths(repo: Path, commit: str, needles: Sequence[str], prefix: str) -> list[str]:
    """Paths under ``prefix`` at ``commit`` containing any fixed needle."""

    if not needles:
        return []
    arguments = ["grep", "-l", "-F"]
    for needle in needles:
        arguments.extend(["-e", needle])
    arguments.extend([commit, "--", prefix])
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    # git grep exits 1 when nothing matched, which is not an error here.
    if completed.returncode not in {0, 1}:
        raise GitError(f"git grep failed with exit {completed.returncode}")
    found = []
    for line in completed.stdout.splitlines():
        _commit, separator, path = line.partition(":")
        if separator and path.strip():
            found.append(path.strip())
    return sorted(set(found))


def present_needles(repo: Path, commit: str, needles: Sequence[str]) -> set[str]:
    """Which of ``needles`` occur anywhere in the tree at ``commit``.

    One subprocess for the whole batch. The novelty question is asked of tens
    of literals per candidate over a hundred and fifty candidates, and a `git
    grep` each turns a corpus build into an hour; `-o` reports the matched text
    itself, so a single call partitions the batch into present and absent.
    """

    if not needles:
        return set()
    wanted = sorted({needle for needle in needles if needle})
    arguments = ["grep", "-o", "-F"]
    for needle in wanted:
        arguments.extend(["-e", needle])
    arguments.extend([commit, "--", "."])
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=GIT_TIMEOUT_SECONDS * 4,
    )
    # git grep exits 1 when nothing matched, which is not an error here.
    if completed.returncode not in {0, 1}:
        raise GitError(f"git grep -o failed with exit {completed.returncode}")
    found: set[str] = set()
    for line in completed.stdout.splitlines():
        _before, separator, matched = line.rpartition(":")
        if separator and matched in set(wanted):
            found.add(matched)
    return found


def blob_sizes(repo: Path, commit: str, prefix: str) -> dict[str, int]:
    """Byte size of every blob under ``prefix`` at ``commit``."""

    raw = git(repo, "ls-tree", "-r", "-l", commit, "--", prefix)
    sizes: dict[str, int] = {}
    for line in raw.splitlines():
        head, separator, path = line.partition("\t")
        if not separator:
            continue
        fields = head.split()
        if len(fields) < 4 or not fields[3].isdigit():
            continue
        sizes[path.strip()] = int(fields[3])
    return sizes


def blob_digest(repo: Path, commit: str, path: str) -> str:
    """sha256 of one path's bytes at one commit; a missing path digests as ``-``.

    Over the bytes git holds, not over decoded text: a digest that depends on
    a codec or on newline translation is not a pin, and a binary path has no
    text to digest at all.
    """

    raw = file_bytes(repo, commit, path)
    if raw is None:
        return "-"
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def candidate_workspace(repo: Path, commit: str, root: Path, name: str) -> Iterator[Path]:
    """A detached worktree at ``commit``, removed however the block exits.

    Detached on purpose: the lane never creates a branch, so two runs of the
    same task can never collide on a branch name, and a leaked worktree is
    one `git worktree prune` away rather than a stale branch to reap.
    """

    workspace = root / name
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    # Removing the directory does not remove git's registration of it, and an
    # earlier crashed run leaves exactly that: an entry pointing at a path that
    # no longer exists, which makes the next `worktree add` refuse. Prune first
    # so a crash costs one run, not every run after it.
    git(repo, "worktree", "prune")
    git(repo, "worktree", "add", "--detach", str(workspace), commit)
    try:
        yield workspace
    finally:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(workspace)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "prune"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
