#!/usr/bin/env python3
"""Fail-closed leak guard: no private identifier may appear in a tracked file.

The committed denylist holds only sha256 hashes of lowercased identifiers, so
the repo never carries the names it protects. Every git-tracked text file is
lowercased and split into `[a-z0-9]+` words; every 1-, 2- and 3-word shingle is
hashed (2- and 3-word shingles in space, hyphen and joined forms, so `foo-bar`,
`foo bar` and `foobar` meet one entry, which `--hash` writes as the joined form) and looked up. Every path
is checked the same way, binary files included. A hit is reported as path:line
plus the hash, never the name; a path that itself holds a name is shown only as
`<redacted path #n>`, n being its position in the scanned listing.

Exit codes: 0 clean, 1 hit, 2 the guard could not run (no/empty/malformed
denylist, git failure, unreadable file). A guard that cannot look must not pass.

    uv run python tools/qa/identifier_guard.py            # all tracked files
    uv run python tools/qa/identifier_guard.py --staged   # index blobs (hook)
    uv run python tools/qa/identifier_guard.py PATH...    # explicit files
    uv run python tools/qa/identifier_guard.py --hash "name"
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import hashlib
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Iterator

ROOT = Path(__file__).resolve().parents[2]
DENYLIST = Path("tools/qa/identifier-denylist.sha256")
LOCAL_OVERRIDE = Path("tools/qa/identifier-denylist.local.txt")

WORD = re.compile(r"[a-z0-9]+")
HEX_HASH = re.compile(r"[0-9a-f]{64}")
MAX_SHINGLE = 3
BINARY_SUFFIXES = frozenset(
    ".png .jpg .jpeg .gif .webp .ico .icns .bmp .tif .tiff .avif .heic .svgz "
    ".pdf .zip .gz .tgz .bz2 .xz .zst .7z .rar .tar .whl .jar .woff .woff2 "
    ".ttf .otf .eot .mp3 .mp4 .m4a .mov .wav .ogg .webm .flac .mkv .avi "
    ".so .dylib .dll .exe .bin .o .a .pyc .pyd .class .wasm .db .sqlite "
    ".sqlite3 .pptx .docx .xlsx .hwp .psd .lockb".split()
)


class GuardError(Exception):
    """The guard cannot give a trustworthy answer; the caller exits 2."""


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_hashes(root: Path) -> set[str]:
    path = root / DENYLIST
    if not path.is_file():
        raise GuardError(f"denylist missing: {DENYLIST} (the guard fails closed)")
    hashes: set[str] = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip().lower()
        if not line:
            continue
        if not HEX_HASH.fullmatch(line):
            raise GuardError(f"{DENYLIST}:{number}: not a sha256 hex hash")
        hashes.add(line)
    if not hashes:  # before the local merge: CI never has the local list
        raise GuardError(f"denylist empty: {DENYLIST} has no entries (the guard fails closed)")
    local = root / LOCAL_OVERRIDE
    if local.is_file():
        for raw in local.read_text(encoding="utf-8").splitlines():
            name = raw.split("#", 1)[0].strip().lower()
            if name:
                hashes.add(digest("".join(WORD.findall(name))))
    return hashes


def shingle_hashes(words: list[str], start: int) -> Iterator[str]:
    for size in range(1, MAX_SHINGLE + 1):
        window = words[start : start + size]
        if len(window) < size:
            return
        if size == 1:
            yield digest(window[0])
            continue
        for joiner in (" ", "-", ""):
            yield digest(joiner.join(window))


def scan_text(text: str, hashes: set[str]) -> list[tuple[int, str]]:
    """Return sorted unique (line, hash) hits; a shingle sits on its first word's line."""
    lowered = text.lower()
    newlines = [i for i, ch in enumerate(lowered) if ch == "\n"]
    matches = list(WORD.finditer(lowered))
    words = [m.group() for m in matches]
    hits: set[tuple[int, str]] = set()
    for index, match in enumerate(matches):
        for value in shingle_hashes(words, index):
            if value in hashes:
                hits.add((bisect_right(newlines, match.start()) + 1, value))
    return sorted(hits)


def is_binary(path: str, data: bytes) -> bool:
    return Path(path).suffix.lower() in BINARY_SUFFIXES or b"\0" in data[:8192]


def git(root: Path, *args: str) -> bytes:
    try:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise GuardError(f"git {args[0]} failed: {error}") from error
    return done.stdout


def tracked_files(root: Path) -> list[str]:
    return [p for p in git(root, "ls-files", "-z").decode("utf-8", "surrogateescape").split("\0") if p]


def staged_blobs(root: Path) -> list[tuple[str, str | None]]:
    blobs: list[tuple[str, str | None]] = []
    for entry in git(root, "ls-files", "-z", "--stage").decode("utf-8", "surrogateescape").split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        mode, blob, _stage = meta.split()
        # Symlinks and submodules have no text of their own, but their paths are checked.
        blobs.append((path, blob if mode in {"100644", "100755"} else None))
    return blobs


def read_disk(root: Path, path: str) -> bytes | None:
    target = root / path
    if target.is_symlink() or not target.exists():
        return None  # deleted in the working tree, or a link: nothing of its own to read
    if not target.is_file():
        return None
    try:
        return target.read_bytes()
    except OSError as error:
        raise GuardError(f"cannot read: {error.strerror}") from error


def read_required(root: Path, path: str) -> bytes:
    data = read_disk(root, path)
    if data is None:
        raise GuardError("cannot read")
    return data


def listing(root: Path, staged: bool, paths: list[str]) -> list[tuple[str, Callable[[], bytes | None]]]:
    """Every path to check, in listing order, with a reader for its text (None: no text)."""
    if paths:
        return [(path, lambda path=path: read_required(root, path)) for path in paths]
    if staged:
        return [
            (path, (lambda blob=blob: git(root, "cat-file", "blob", blob)) if blob else (lambda: None))
            for path, blob in staged_blobs(root)
        ]
    return [(path, lambda path=path: read_disk(root, path)) for path in tracked_files(root)]


def run(root: Path, staged: bool = False, paths: list[str] | None = None) -> int:
    try:
        hashes = load_hashes(root)
        hits = 0
        scanned = 0
        for number, (path, read) in enumerate(listing(root, staged, paths or []), 1):
            path_hits = scan_text(path, hashes)
            # A path holding a name is never printed, in hits or in errors.
            shown = f"<redacted path #{number}>" if path_hits else path
            for _line, value in path_hits:
                hits += 1
                print(f"{shown} (hash {value})")
            try:
                data = read()
            except GuardError as error:
                raise GuardError(f"{shown}: {error}") from error
            if data is None or is_binary(path, data):
                continue
            scanned += 1
            for line, value in scan_text(data.decode("utf-8", "replace"), hashes):
                hits += 1
                print(f"{shown}:{line}: private identifier hash {value}")
    except GuardError as error:
        print(f"identifier-guard: BLOCKED: {error}", file=sys.stderr)
        return 2
    if hits:
        print(
            f"identifier-guard: {hits} hit(s) in {scanned} files; remove the identifier"
            " (redacted path #n is entry n of `git ls-files`, `git ls-files --stage` with --staged,"
            " or the arguments)",
            file=sys.stderr,
        )
        return 1
    print(f"identifier-guard: clean ({scanned} text files, {len(hashes)} denylist entries)")
    return 0


def hash_line(name: str) -> str:
    lowered = name.strip().lower()
    words = WORD.findall(lowered)
    if not words or len(words) > MAX_SHINGLE or re.sub(r"[a-z0-9]+", "", lowered).strip(" -"):
        raise GuardError(
            f"an entry must be 1-{MAX_SHINGLE} words of [a-z0-9] joined by space or hyphen, or the scanner can never match it"
        )
    # The joined spelling is canonical: the scanner hashes the joined form of every
    # shingle, so `foo bar`, `foo-bar` and `foobar` all meet this one entry.
    return digest("".join(words))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="scan these files instead of every tracked file")
    parser.add_argument("--staged", action="store_true", help="scan index blobs (pre-commit hook)")
    parser.add_argument("--hash", dest="name", metavar="NAME", help="print the denylist line for NAME and exit")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.name is not None:
        try:
            print(hash_line(args.name))
        except GuardError as error:
            print(f"identifier-guard: {error}", file=sys.stderr)
            return 2
        return 0
    return run(args.root, staged=args.staged, paths=args.paths)


if __name__ == "__main__":
    sys.exit(main())
