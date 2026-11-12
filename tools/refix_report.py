#!/usr/bin/env python3
"""List fix commits that replaced lines another pull request landed shortly before.

Maintainer script, not a product feature: `omh` never runs it, it reads git
history only, and it has no dependency beyond the standard library and `git`.

For every non-merge commit in the range whose subject starts with `fix` or
`hotfix`, it blames the lines that commit removes or replaces, at the commit's
parent. A line is *young* when the commit that wrote it landed no more than
`--window-hours` before the fix landed. "Landed" is the committer time of the
first-parent merge that brought the commit into the revision, or the commit's
own committer time when it sits directly on the first-parent line (a squash
merge or a direct push). The fix is then one of:

* ``none``     -- no replaced line is young;
* ``same``     -- young lines exist, and all were written inside the fix's own
  pull request (same first-parent merge);
* ``another``  -- at least one young line was written by a different pull
  request. A fix that touches both kinds counts here.

The ``another`` count is an upper bound on defects shipped and then repaired.
It includes follow-up work, a planned second step, a version bump or a wording
change as readily as a real defect: the script sees that a young line was
replaced, not why. A person or agent has to read each pair.

The window is measured back from the commit date of the revision, not from the
wall clock, so the same revision and options print the same report.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

CLASS_NONE = "none"
CLASS_SAME = "same"
CLASS_ANOTHER = "another"

UPPER_BOUND_NOTE = (
    "The 'another pull request' count is an upper bound: it holds real defects "
    "and ordinary follow-up work (a planned second step, a version bump, a "
    "wording change) alike, because a replaced young line does not say why it "
    "was replaced. Read each pair before you call it a defect."
)

_FIX_SUBJECT = re.compile(r"^(?:hotfix|fix)(?![A-Za-z0-9])", re.IGNORECASE)
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")
_FIELD = "\x1f"


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    landed: int  # epoch seconds the commit landed on the revision
    group: str  # first-parent merge (or the commit itself) that carried it


@dataclass(frozen=True)
class Pair:
    """One fix commit and one earlier commit (another pull request) whose young lines it replaced."""

    fix: Commit
    earlier: Commit
    files: tuple[tuple[str, int], ...]  # (path, replaced young lines), by path

    @property
    def lines(self) -> int:
        return sum(count for _, count in self.files)

    @property
    def age_hours(self) -> float:
        return round((self.fix.landed - self.earlier.landed) / 3600, 1)


@dataclass
class Report:
    revision: str
    days: int
    window_hours: float
    non_merge_commits: int = 0
    fix_commits: int = 0
    counts: dict[str, int] = field(
        default_factory=lambda: {CLASS_NONE: 0, CLASS_SAME: 0, CLASS_ANOTHER: 0}
    )
    blame_failed: int = 0  # (fix commit, file) pairs git could not blame: not "no lines", counted
    pairs: list[Pair] = field(default_factory=list)


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return done.stdout


def is_fix_subject(subject: str) -> bool:
    return bool(_FIX_SUBJECT.match(subject.strip()))


def classify(fix_group: str, young: list[Commit]) -> str:
    """Class of one fix, given the commits that wrote its young replaced lines."""
    if any(commit.group != fix_group for commit in young):
        return CLASS_ANOTHER
    if young:
        return CLASS_SAME
    return CLASS_NONE


def _landing_map(repo: Path, revision: str, floor: int) -> dict[str, Commit]:
    """Every non-merge commit that landed on `revision` at or after `floor`."""
    landed: dict[str, Commit] = {}
    log = _git(repo, "log", "--first-parent", f"--since={floor}", f"--format=%H{_FIELD}%P{_FIELD}%ct", revision)
    for row in log.splitlines():
        sha, parents, stamp = row.split(_FIELD)
        parent_list = parents.split()
        if len(parent_list) > 1:  # a merge: its group is every non-merge commit it brought in
            members = _git(repo, "rev-list", "--no-merges", f"{parent_list[0]}..{sha}").split()
        else:  # a root or a commit made directly on the first-parent line
            members = [sha]
        subjects = _subjects(repo, members)
        for member in members:
            landed[member] = Commit(member, subjects[member], int(stamp), sha)
    return landed


def _subjects(repo: Path, shas: list[str]) -> dict[str, str]:
    if not shas:
        return {}
    out = _git(repo, "show", "-s", f"--format=%H{_FIELD}%s", *shas)
    return {row.split(_FIELD)[0]: row.split(_FIELD, 1)[1] for row in out.splitlines() if row}


def _removed_ranges(repo: Path, fix: str) -> dict[str, list[tuple[int, int]]]:
    """Old-side line ranges per file that `fix` removes or replaces.

    Paths come from `git diff -z --name-only`, which prints them raw: the
    `---` header of a plain diff C-quotes a name with a space-tab, quote or
    non-ASCII byte, and a parser of that header drops the file. Hunks are then
    read one path at a time, where only the `@@` lines matter. A path is a
    literal one (no glob), so a name holding `*` or `[` matches itself.
    """
    names = _git(repo, "diff", "-z", "--name-only", "--no-renames", "--no-ext-diff", f"{fix}^", fix)
    ranges: dict[str, list[tuple[int, int]]] = {}
    for path in filter(None, names.split("\0")):
        diff = _git(
            repo, "--literal-pathspecs", "diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames",
            f"{fix}^", fix, "--", path,
        )
        for line in diff.splitlines():
            if match := _HUNK.match(line):
                start = int(match.group(1))
                count = 1 if match.group(2) is None else int(match.group(2))
                if count:
                    ranges.setdefault(path, []).append((start, start + count - 1))
    return ranges


def _blame(repo: Path, parent: str, path: str, spans: list[tuple[int, int]]) -> list[str] | None:
    """Commit sha for every non-blank line of `spans` in `path` at `parent`; None when git cannot blame it."""
    args = ["blame", "--line-porcelain", "-w"]
    for first, last in spans:
        args += ["-L", f"{first},{last}"]
    try:
        out = _git(repo, *args, parent, "--", path)
    except subprocess.CalledProcessError:
        return None
    shas: list[str] = []
    current = ""
    for line in out.splitlines():
        if re.match(r"^[0-9a-f]{40} \d+ \d+", line):
            current = line[:40]
        elif line.startswith("\t") and line.strip():
            shas.append(current)
    return shas


def build_report(repo: Path, revision: str, days: int = 7, window_hours: float = 48) -> Report:
    head = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}").strip()
    head_time = int(_git(repo, "show", "-s", "--format=%ct", head).strip())
    since = head_time - days * 86400
    window = int(window_hours * 3600)
    landed = _landing_map(repo, head, since - window)
    report = Report(revision=head, days=days, window_hours=window_hours)
    report.non_merge_commits = sum(1 for c in landed.values() if c.landed >= since)

    fixes = sorted(
        (c for c in landed.values() if c.landed >= since and is_fix_subject(c.subject)),
        key=lambda c: (c.landed, c.sha),
    )
    report.fix_commits = len(fixes)
    for fix in fixes:
        young: list[Commit] = []
        found: dict[str, dict[str, int]] = {}
        for path, spans in _removed_ranges(repo, fix.sha).items():
            blamed = _blame(repo, f"{fix.sha}^", path, spans)
            if blamed is None:
                report.blame_failed += 1
                continue
            for sha in blamed:
                earlier = landed.get(sha)
                if earlier is None or fix.landed - earlier.landed > window:
                    continue  # landed before the map starts, or outside the window
                young.append(earlier)
                if earlier.group != fix.group:
                    per_file = found.setdefault(sha, {})
                    per_file[path] = per_file.get(path, 0) + 1
        verdict = classify(fix.group, young)
        report.counts[verdict] += 1
        for sha, per_file in sorted(found.items(), key=lambda kv: (landed[kv[0]].landed, kv[0])):
            report.pairs.append(Pair(fix, landed[sha], tuple(sorted(per_file.items()))))
    return report


def render_text(report: Report) -> str:
    out = [
        f"revision {report.revision}  last {report.days} days  window {report.window_hours:g} h",
        "",
        "Fix commits that replaced lines another pull request landed inside the window:",
    ]
    if not report.pairs:
        out.append("  (none)")
    for pair in report.pairs:
        shown = ", ".join(path for path, _ in pair.files[:3])
        more = f" (+{len(pair.files) - 3} more)" if len(pair.files) > 3 else ""
        out.append(
            f"  {pair.fix.sha[:9]} {pair.fix.subject}\n"
            f"    replaced lines from {pair.earlier.sha[:9]} {pair.earlier.subject}\n"
            f"    {pair.age_hours:g} h earlier, {pair.lines} line(s) in {shown}{more}"
        )
    pair_fixes = len({pair.fix.sha for pair in report.pairs})
    out += [
        "",
        f"non-merge commits landed in range: {report.non_merge_commits}",
        f"fix/hotfix commits:                {report.fix_commits}",
        f"  no young line:                   {report.counts[CLASS_NONE]}",
        f"  same pull request:               {report.counts[CLASS_SAME]}",
        f"  another pull request:            {report.counts[CLASS_ANOTHER]}",
        f"pairs listed (fix commit, earlier commit): {len(report.pairs)} across {pair_fixes} fix commits",
        f"blame failed: {report.blame_failed} file(s)",
        "",
        UPPER_BOUND_NOTE,
    ]
    return "\n".join(out)


def render_json(report: Report) -> str:
    return json.dumps(
        {
            "revision": report.revision,
            "days": report.days,
            "window_hours": report.window_hours,
            "totals": {
                "non_merge_commits": report.non_merge_commits,
                "fix_commits": report.fix_commits,
                "no_young_line": report.counts[CLASS_NONE],
                "same_pull_request": report.counts[CLASS_SAME],
                "another_pull_request": report.counts[CLASS_ANOTHER],
                "pairs": len(report.pairs),
                "blame_failed": report.blame_failed,
            },
            "pairs": [
                {
                    "fix": pair.fix.sha,
                    "fix_subject": pair.fix.subject,
                    "earlier": pair.earlier.sha,
                    "earlier_subject": pair.earlier.subject,
                    "age_hours": pair.age_hours,
                    "lines": pair.lines,
                    "files": [{"path": path, "lines": count} for path, count in pair.files],
                }
                for pair in report.pairs
            ],
            "note": UPPER_BOUND_NOTE,
        },
        indent=2,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0],
        epilog=UPPER_BOUND_NOTE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("revision", nargs="?", default="origin/main", help="revision to read (default origin/main)")
    parser.add_argument("--days", type=int, default=7, help="look back this many days from the revision's commit date (default 7)")
    parser.add_argument("--window-hours", type=float, default=48, help="a line is young when it landed this many hours or fewer before the fix (default 48)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--repo", type=Path, default=Path("."), help="repository to read (default: current directory)")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.repo, args.revision, args.days, args.window_hours)
    except subprocess.CalledProcessError as exc:
        print(f"git failed: {' '.join(map(str, exc.cmd))}\n{exc.stderr}", file=sys.stderr)
        return 1
    print(render_json(report) if args.json else render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
