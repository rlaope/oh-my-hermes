"""`omh capability-policy pr-delivery {show,on,off}` -- the person's PR delivery grant.

Audience: the person who owns the bot, at their own terminal. Owner-approved,
2026-11-23 (`docs/PR-DELIVERY-GRANT.md`). The grant lets this profile's bot,
in a run nobody can answer, push a branch under its prefix, open a pull
request from it, and push fix commits to and comment on a pull request it
opened. Nothing else, and never a merge, a force push, a push to the default
branch, or anything on a pull request it did not open.

This module holds the one writer of the grant, `write_pr_delivery_grant`.
`tests/test_pr_delivery_grant.py` holds that nothing else in `src/` calls it:
no plugin tool, hook or skill can turn the grant on. `on` and `off` also
refuse to run inside a Hermes session (a `HERMES_SESSION_ID` in the
environment, which Hermes sets for every command its terminal tool runs),
they also refuse when any other marker Hermes puts in a child's environment
is present (`HERMES_MARKERS`), `on` needs a yes typed at a terminal a person
can see, and the plugin's tool hook refuses any command line naming them.
That stops a cooperating agent and an agent without a terminal. A bot that
spells the command past the hook, unsets every marker and spawns its own
pseudo-terminal (the terminal tool's `pty=true`) can answer the prompt
itself: the same class as the other stated residuals, not a case this module
claims to stop.

The grant is per Hermes profile: the file names the profile's Hermes home,
and a grant for one profile never reads as on for another, even when both
share one OMH home.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..plugin_bundle.omh import pr_delivery
from .common import _paths, _print_json, _wants_json

CHANGE_SCHEMA_VERSION = "omh_pr_delivery_grant_change/v1"
# Hermes sets this for every command its terminal tool runs
# (`tools/environments/local.py` copies the session's context variables into
# the child's environment). A person's own shell does not have it.
HERMES_SESSION_ENV = "HERMES_SESSION_ID"
# Variables Hermes puts in its own and its children's environment, read from
# its source: the session context (`gateway/session_context.py`, every
# `HERMES_SESSION_*`, `HERMES_UI_SESSION_ID`, `HERMES_CRON_SESSION`), the
# agent process (`HERMES_AGENT`, set by `hermes_cli/main.py` and
# `gateway/run.py`), the gateway's approval mode (`HERMES_EXEC_ASK`) and a
# one-shot run (`HERMES_SINGLE_QUERY_SESSION`). `HERMES_HOME` is not one: a
# person sets it in their own shell.
HERMES_MARKERS = ("HERMES_UI_SESSION_ID", "HERMES_CRON_SESSION", "HERMES_AGENT", "HERMES_EXEC_ASK",
                  "HERMES_SINGLE_QUERY_SESSION")
HERMES_MARKER_PREFIX = "HERMES_SESSION_"


def hermes_marker(environ) -> str:
    """The first Hermes marker in an environment, or "": seen without spawning anything."""
    for name in sorted(environ):
        value = str(environ.get(name, "") or "").strip()
        if value and (name.startswith(HERMES_MARKER_PREFIX) or name in HERMES_MARKERS):
            return name
    return ""
EXIT_REFUSED = 2


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _profile(paths) -> str:
    return pr_delivery.profile_key(paths.hermes_home)


def write_pr_delivery_grant(paths, *, state: str, branch_prefix: str, previous: dict | None) -> dict[str, object]:
    """Write this profile's grant atomically, mode 600. The only writer; the person's CLI is its only caller."""
    document: dict[str, object] = {
        "schema_version": pr_delivery.GRANT_SCHEMA_VERSION,
        "state": state,
        "hermes_home": _profile(paths),
        "branch_prefix": branch_prefix,
        "allowed_actions": list(pr_delivery.ALLOWED_ACTIONS),
        "never_allowed_actions": list(pr_delivery.NEVER_ALLOWED_ACTIONS),
        "granted_at": _now() if state == "on" else str((previous or {}).get("granted_at") or ""),
        "changed_by": pr_delivery.TURN_ON_COMMAND if state == "on" else pr_delivery.TURN_OFF_COMMAND,
        "enforcement": (
            "OMH's tool hook refuses the never-allowed actions in a session nobody can answer (a webhook, "
            "api_server, cron, one-shot or delegated run), and the grant-covered ones too while the grant is "
            "off. It holds a cooperating model, not one that sets out to evade it. omh itself runs no forge "
            "command."
        ),
    }
    if state == "off":
        document["turned_off_at"] = _now()
    path = pr_delivery.grant_path(paths.omh_home, paths.hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError:
        Path(temporary).unlink(missing_ok=True)
        raise
    return document


def on_windows() -> bool:
    """Whether the console rules apply. A seam, so tests decide it on every host."""
    return os.name == "nt"


def terminal_devices() -> tuple[str, str]:
    """(read, write) devices of the controlling terminal: the console on Windows, `/dev/tty` elsewhere."""
    return ("CONIN$", "CONOUT$") if on_windows() else ("/dev/tty", "/dev/tty")


def console_is_visible() -> bool:
    """Whether this process's console has a window a person can see. Windows only.

    Hermes spawns every terminal child with `CREATE_NO_WINDOW`
    (`tools/environments/local.py`, `windows_hide_flags`): such a child has a
    console, so `CONIN$` opens, but no visible window, so nobody can type the
    yes. Any failure to ask answers no.
    """
    try:
        import ctypes

        window = ctypes.windll.kernel32.GetConsoleWindow()  # type: ignore[attr-defined]
        return bool(window) and bool(ctypes.windll.user32.IsWindowVisible(window))  # type: ignore[attr-defined]
    except (AttributeError, OSError, ImportError):
        return False


def confirm_on_terminal(prompt: str) -> bool:
    """A yes typed at a terminal a person can see; every doubt is a no.

    A Hermes pipe-mode child has no controlling terminal, so `/dev/tty`
    fails and the answer is no. A child Hermes spawns with `pty=true` does
    have one, and so can answer: that is why the marker check runs first and
    why this is stated as a residual, not a proof.

    POSIX reads `/dev/tty`. Windows has none; its equivalent is the console
    itself, `CONIN$` and `CONOUT$`. A Hermes child owns a hidden console
    (`CREATE_NO_WINDOW`) where those open with nobody at it, so on Windows
    the console window must also be visible. A missing or hidden terminal is
    a no, never a wait and never a crash.
    """
    if on_windows() and not console_is_visible():
        return False  # a hidden console (Hermes spawns its children with CREATE_NO_WINDOW) has nobody at it
    reader, writer = terminal_devices()
    try:
        with open(writer, "w", encoding="utf-8") as out:
            out.write(prompt)
            out.flush()
        with open(reader, encoding="utf-8") as tty:
            answer = tty.readline()
    except OSError:
        return False
    return answer.strip().lower() in ("y", "yes")


def _previous(path: Path) -> dict | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def cmd_pr_delivery_show(args: argparse.Namespace) -> int:
    paths = _paths(args)
    payload = dict(pr_delivery.read_grant(paths.omh_home, paths.hermes_home))
    payload["profile"] = _profile(paths)
    payload["scope_if_on"] = list(pr_delivery.ALLOWED_ACTIONS)
    if _wants_json(args):
        _print_json(payload)
        return 0
    print(f"PR delivery grant for {payload['profile']}: {str(payload['state']).upper()}")
    if payload["state"] == "on":
        print(f"  Branch prefix: {payload['branch_prefix']}  (turned on {payload['granted_at']})")
    else:
        print(f"  Reason: {payload['reason']}")
    _print_scope(on=payload["state"] == "on")
    print(f"  Change it: {pr_delivery.TURN_ON_COMMAND} | {pr_delivery.TURN_OFF_COMMAND}")
    return 0


def cmd_pr_delivery_on(args: argparse.Namespace) -> int:
    return _change(args, state="on")


def cmd_pr_delivery_off(args: argparse.Namespace) -> int:
    return _change(args, state="off")


def _change(args: argparse.Namespace, *, state: str) -> int:
    marker = hermes_marker(os.environ)
    if marker:
        message = (
            f"Refused: this runs inside a Hermes session ({marker} is set). Only the person changes "
            "the PR delivery grant, at their own terminal, outside Hermes."
        )
        if _wants_json(args):
            _print_json({"schema_version": CHANGE_SCHEMA_VERSION, "refused": True, "reason": "inside_hermes_session",
                         "message": message})
        else:
            print(message)
        return EXIT_REFUSED
    prefix = str(getattr(args, "branch_prefix", "") or pr_delivery.DEFAULT_BRANCH_PREFIX)
    if state == "on" and not pr_delivery.valid_branch_prefix(prefix):
        print(f"Refused: {prefix!r} is not a branch prefix. Use one path segment ending in '/', for example 'bot/'.")
        return EXIT_REFUSED
    paths = _paths(args)
    if state == "on" and not confirm_on_terminal(
        f"Let the bot of {_profile(paths)} push branches under {prefix} and open and update its own pull "
        "requests when nobody can answer? Type yes: "
    ):
        print("Refused: turning the grant on needs a yes typed at your own terminal.")
        return EXIT_REFUSED
    before = pr_delivery.read_grant(paths.omh_home, paths.hermes_home)
    path = pr_delivery.grant_path(paths.omh_home, paths.hermes_home)
    previous = _previous(path)
    if state == "off":
        prefix = str((previous or {}).get("branch_prefix") or "")
        prefix = prefix if pr_delivery.valid_branch_prefix(prefix) else pr_delivery.DEFAULT_BRANCH_PREFIX
    already = before["state"] == state and (state == "off" or before["branch_prefix"] == prefix)
    document = previous if already else write_pr_delivery_grant(
        paths, state=state, branch_prefix=prefix, previous=previous)
    payload = {
        "schema_version": CHANGE_SCHEMA_VERSION,
        "profile": _profile(paths),
        "requested_state": state,
        "already_in_state": already,
        "branch_prefix": prefix if state == "on" else "",
        "allowed_actions": list(pr_delivery.ALLOWED_ACTIONS) if state == "on" else [],
        "never_allowed_actions": list(pr_delivery.NEVER_ALLOWED_ACTIONS),
        "grant": document or {},
        "path": str(path),
        "reverse_command": pr_delivery.TURN_OFF_COMMAND if state == "on" else pr_delivery.TURN_ON_COMMAND,
    }
    if _wants_json(args):
        _print_json(payload)
        return 0
    verb = "already" if already else "now"
    print(f"PR delivery grant for {payload['profile']} is {verb} {state.upper()}.")
    if state == "on":
        print(f"  Branch prefix: {prefix}")
    _print_scope(on=state == "on")
    print(f"  Reverse: {payload['reverse_command']}")
    return 0


def _print_scope(*, on: bool) -> None:
    if on:
        print("  In a run nobody can answer, this bot may:")
        for action in pr_delivery.ALLOWED_ACTIONS:
            print(f"    - {action}")
    else:
        print("  In a run nobody can answer, this bot pushes nothing and opens no pull request: a person's turn does.")
    print("  It never may, grant or no grant:")
    for action in pr_delivery.NEVER_ALLOWED_ACTIONS:
        print(f"    - {action}")


def add_pr_delivery_commands(capability_policy_sub) -> None:
    """Register `show`, `on` and `off` under `omh capability-policy pr-delivery`."""
    group = capability_policy_sub.add_parser(
        "pr-delivery",
        help=(
            "Operator: show or change whether this profile's bot may push its own branch and open and update "
            "its own pull request when nobody can answer. Off by default; only you can change it."
        ),
    )
    sub = group.add_subparsers(dest="pr_delivery_command", required=True)
    show = sub.add_parser("show", help="Show this profile's PR delivery grant and its fixed scope.")
    show.add_argument("--json", action="store_true", help="Print the machine-readable grant status.")
    show.set_defaults(func=cmd_pr_delivery_show)
    turn_on = sub.add_parser(
        "on",
        help="Let this profile's bot, unattended, push a branch under its prefix, open a PR from it, and push "
        "fixes to and comment on PRs it opened. Never merge, force-push, or push to the default branch.",
    )
    turn_on.add_argument(
        "--branch-prefix",
        default=pr_delivery.DEFAULT_BRANCH_PREFIX,
        help="The bot's branch namespace, one path segment ending in '/' (default: bot/).",
    )
    turn_on.add_argument("--json", action="store_true", help="Print the machine-readable change.")
    turn_on.set_defaults(func=cmd_pr_delivery_on)
    turn_off = sub.add_parser("off", help="Withdraw the grant: unattended runs hand the push and the PR to you again.")
    turn_off.add_argument("--json", action="store_true", help="Print the machine-readable change.")
    turn_off.set_defaults(func=cmd_pr_delivery_off)
