#!/usr/bin/env python3
"""Obsidian vault folder monitor for a Hermes cron monitor job.

Hermes runs this as a cron job's `--monitor-script`, with no arguments, from
`<profile>/scripts/`, before the agent on every tick. Hermes hashes the exact
stdout bytes: unchanged output suppresses the agent run (no model call),
changed output wakes the agent with a diff. So the output is a digest of the
folder's note names, modification times and sizes, sorted, plus the names of
the most recently modified notes; never a note's content:

    monitor: obsidian watch=<name>
    folder=Inbox files=42 digest=3f9a0c1d2e4b5a69
    recent 2026-11-24T09:58:03Z Inbox/standup.md
    recent 2026-11-24T08:12:40Z Inbox/ideas.md

A note added, removed, renamed, saved with new bytes, or touched (its
modification time moved) changes the digest. With `"use_mtime": false` only
names and sizes count, for a vault a sync tool touches on every sync (no
`recent` lines then, and an edit that keeps the size is not seen). Names starting with a dot are
skipped, files and folders alike (`.obsidian/`, `.trash/`, `.git/`, editor swap
files), and symbolic links (and, on Python 3.12+, Windows junctions) are
neither followed during the walk nor accepted in the folder path.

The vault is the config's `vault`, else `OBSIDIAN_VAULT_PATH` from the
environment, else `~/Documents/Obsidian Vault`, the same order as Hermes'
obsidian skill. Local reads only: it lists folders and reads file metadata,
opens no file, makes no connection, starts no process and writes nothing; the
only output is stdout and stderr.

A missing vault or folder, a folder it cannot list, or a config error prints
one fixed line, `error reason=<reason>`, and exits 0: Hermes sees that line
change once, wakes the agent once to report it, and stays quiet while it
holds. A subfolder it cannot list is counted as `unreadable=<n>` and skipped.

Installed as `<profile>/scripts/vault_watch_<watch>.py`; the file name names
the watch, whose config is `<profile>/monitors/<watch>.json`. `--config PATH`
selects a config directly (manual runs, tests). Stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath

EXIT_OK = 0

SCRIPT_PREFIX = "vault_watch_"
CONFIG_DIR = "monitors"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
EXTENSION_RE = re.compile(r"^\.[A-Za-z0-9]{1,10}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
DEFAULT_VAULT = Path("~/Documents/Obsidian Vault")
MAX_ENTRIES = 50_000
MAX_SHOWN_NAME = 200


class ConfigError(Exception):
    pass


class Persistent(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------- config


def load_config(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise ConfigError("config file not readable") from None
    except ValueError:
        raise ConfigError("config file is not JSON") from None
    if not isinstance(raw, dict):
        raise ConfigError("config must be a JSON object")
    name = raw.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ConfigError("name must match [a-z0-9][a-z0-9_-]{0,63}")
    if raw.get("kind") != "obsidian":
        raise ConfigError("kind must be obsidian")
    vault = raw.get("vault")
    if vault is not None and (not isinstance(vault, str) or not vault.strip() or CONTROL_RE.search(vault)):
        raise ConfigError("vault must be a folder path")
    folder = raw.get("folder", "")
    if not isinstance(folder, str) or CONTROL_RE.search(folder) or len(folder) > 300:
        raise ConfigError("folder must be a path inside the vault")
    parts = PurePosixPath(folder.replace("\\", "/")).parts
    if any(part in ("..", "") or part.startswith(".") for part in parts) or folder.startswith(("/", "\\")) or ":" in folder:
        raise ConfigError("folder must be a relative path inside the vault, without dot folders")
    extensions = raw.get("extensions", [".md"])
    if (not isinstance(extensions, list) or not 0 < len(extensions) <= 10
            or not all(isinstance(e, str) and EXTENSION_RE.fullmatch(e) for e in extensions)):
        raise ConfigError("extensions must be a list such as [\".md\"]")
    recent = raw.get("recent", 10)
    if isinstance(recent, bool) or not isinstance(recent, int) or not 0 <= recent <= 50:
        raise ConfigError("recent must be a whole number from 0 to 50")
    use_mtime = raw.get("use_mtime", True)
    if not isinstance(use_mtime, bool):
        raise ConfigError("use_mtime must be true or false")
    return {"name": name, "vault": vault, "folder": "/".join(parts), "recent": recent if use_mtime else 0,
            "extensions": sorted({e.lower() for e in extensions}), "use_mtime": use_mtime}


def resolve_config(arg: str | None) -> tuple[Path, str | None]:
    """(config path, watch name from the script's file name or None)."""
    if arg:
        return Path(arg), None
    script = Path(sys.argv[0])
    env_home = os.environ.get("HERMES_HOME", "").strip()
    home = Path(env_home) if env_home else script.resolve().parent.parent
    stem = script.stem
    if not stem.startswith(SCRIPT_PREFIX) or len(stem) == len(SCRIPT_PREFIX):
        raise ConfigError(f"install this file as scripts/{SCRIPT_PREFIX}<watch>.py or pass --config")
    name = stem[len(SCRIPT_PREFIX):]
    return home / CONFIG_DIR / f"{name}.json", name


def vault_root(cfg: dict) -> Path:
    configured = cfg["vault"] or os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_VAULT.expanduser()


# ---------------------------------------------------------------- scan


def _is_link(path: Path) -> bool:
    isjunction = getattr(os.path, "isjunction", None)  # Python 3.12+; older Windows Pythons see a plain folder
    return path.is_symlink() or bool(isjunction and isjunction(path))


def scan(vault: Path, folder: str, extensions: list[str]) -> tuple[list[tuple[str, int, int]], int, bool]:
    """(sorted (vault-relative path, mtime_ns, size), unreadable folders, entry cap reached)."""
    if not vault.is_dir():
        raise Persistent("vault_missing")
    top = vault
    for part in folder.split("/") if folder else ():
        top = top / part
        if _is_link(top):  # no component below the vault may be a link (or, on Windows, a junction)
            raise Persistent("folder_missing")
    if not top.is_dir():
        raise Persistent("folder_missing")
    try:
        top.resolve().relative_to(vault.resolve())
    except (OSError, ValueError):
        raise Persistent("folder_missing") from None
    files: list[tuple[str, int, int]] = []
    unreadable, seen, capped = 0, 0, False
    stack = [(top, PurePosixPath(folder) if folder else PurePosixPath())]
    while stack:
        directory, relative = stack.pop()
        try:
            with os.scandir(directory) as entries:
                listed = list(entries)
        except OSError:
            if directory == top:
                raise Persistent("folder_unreadable") from None
            unreadable += 1
            continue
        for entry in listed:
            seen += 1
            if seen > MAX_ENTRIES:
                capped = True
                break
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if _is_link(Path(entry.path)):
                        continue
                    stack.append((Path(entry.path), relative / entry.name))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if os.path.splitext(entry.name)[1].lower() not in extensions:
                    continue
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                unreadable += 1
                continue
            files.append(((relative / entry.name).as_posix(), stat.st_mtime_ns, stat.st_size))
        if capped:
            break
    return sorted(files), unreadable, capped


def _shown(path: str) -> str:
    clean = CONTROL_RE.sub("?", path)
    return clean if len(clean) <= MAX_SHOWN_NAME else clean[: MAX_SHOWN_NAME - 1] + "…"


def digest_lines(cfg: dict, files: list[tuple[str, int, int]], unreadable: int, capped: bool) -> list[str]:
    digest = hashlib.sha256()
    for path, mtime_ns, size in files:
        stamp = mtime_ns if cfg["use_mtime"] else ""
        digest.update(f"{path}\t{stamp}\t{size}\n".encode("utf-8", errors="surrogateescape"))
    summary = f"folder={cfg['folder'] or '.'} files={len(files)} digest={digest.hexdigest()[:16]}"
    if unreadable:
        summary += f" unreadable={unreadable}"
    if capped:
        summary += " limit_reached=yes"
    lines = [summary]
    newest = sorted(files, key=lambda item: (-item[1], item[0]))[: cfg["recent"]]
    for path, mtime_ns, _size in newest:
        stamp = dt.datetime.fromtimestamp(mtime_ns / 1e9, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(f"recent {stamp} {_shown(path)}")
    return lines


# ---------------------------------------------------------------- main


def _emit(lines: list[str]) -> None:
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Obsidian vault folder monitor for a Hermes cron monitor job.")
    parser.add_argument("--config", help="watch config JSON (default: from this file's name)")
    args = parser.parse_args(argv)
    name = "?"
    try:
        config_path, expected = resolve_config(args.config)
        if expected is not None:
            name = expected
        cfg = load_config(config_path)
        if expected is not None and cfg["name"] != expected:
            raise ConfigError("config name does not match the script's watch name")
        name = cfg["name"]
    except ConfigError as exc:
        _emit([f"monitor: obsidian watch={name}", "error reason=config"])
        print(f"monitor: config error: {exc}", file=sys.stderr)
        return EXIT_OK
    header = f"monitor: obsidian watch={name}"
    try:
        files, unreadable, capped = scan(vault_root(cfg), cfg["folder"], cfg["extensions"])
    except Persistent as exc:
        _emit([header, f"error reason={exc.reason}"])
        return EXIT_OK
    _emit([header, *digest_lines(cfg, files, unreadable, capped)])
    return EXIT_OK


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    sys.exit(run(sys.argv[1:]))
