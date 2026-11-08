"""Where a copy from the OMH TUI's pager goes: OSC 52, or `pbcopy` on the Mac the screen is on.

OSC 52 is never answered, so nothing confirms it reached the clipboard. It
counts as copied only for a terminal that honours it as it ships (kitty,
Ghostty, WezTerm, Alacritty) and outside tmux, which passes it on only with
`set-clipboard on`. Terminal.app ignores it and iTerm2 takes it only once its
preference allows it, so on a Mac whose screen is the one the TUI runs on (no
SSH between them) the copy goes through `pbcopy` instead, whose exit status
does confirm it. Anywhere else it goes out as OSC 52 and is reported as sent.
Inside tmux the pane's own environment says nothing about a client that
attached later over SSH, so there `pbcopy` is used only once `tmux
show-environment SSH_CONNECTION` (tmux's `update-environment` keeps it for the
last client that attached) says the variable is not set; an answer that does
not come, or does not say so, counts as remote. Both are fixed argvs, run only
for a copy the person made with the mouse in the pager, `pbcopy` with the text
on stdin.

A herdr pane (herdr, a terminal workspace manager) is the exception to both.
herdr strips TMUX from its panes and keeps no SSH variables per client (a pane
inherits the long-lived server's), so the pane's environment says nothing
about where the screen is. herdr itself puts the pane's OSC 52 on the
clipboard of the machine its client runs on (as OSC 52 again when that client
runs under SSH), so there the copy always goes out as OSC 52 and counts as
copied, up to the most herdr takes (HERDR_CLIPBOARD_BYTES); a larger one is
reported as sent. A tmux started inside the pane sets TMUX again and is tmux.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import subprocess

from .terminal import terminal_name

COPY_OSC52 = "osc52"
COPY_PBCOPY = "pbcopy"
COPY_UNCONFIRMED = "osc52-unconfirmed"
COPY_TOO_LARGE = "osc52-too-large"  # a herdr pane's copy past HERDR_CLIPBOARD_BYTES: herdr drops it
# herdr hands a pane's OSC 52 on only up to this many bytes of decoded text (ghostty-vt's MAX_CLIPBOARD_BYTES).
HERDR_CLIPBOARD_BYTES = 192 * 1024
OSC52_TERMINALS = frozenset({"kitty", "ghostty", "WezTerm", "alacritty"})  # by `terminal_name`
SSH_VARIABLES = ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")  # set: the screen is on another machine than pbcopy's
PBCOPY_SECONDS = 2.0
TMUX_QUERY_SECONDS = 1.0
TMUX_SSH_VARIABLE = "SSH_CONNECTION"  # the one of SSH_VARIABLES in tmux's default `update-environment`


def tmux_client_over_ssh(environ: Mapping[str, str]) -> bool:
    """Whether the tmux session this pane is in has `SSH_CONNECTION` set (its last client attached over SSH); True too
    when tmux does not answer within TMUX_QUERY_SECONDS or answers anything but the variable's absence."""
    try:
        done = subprocess.run(
            ["tmux", "show-environment", TMUX_SSH_VARIABLE], env=dict(environ), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=TMUX_QUERY_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    # Measured on tmux 3.7b: `-NAME` for a variable a client removed, `unknown variable: NAME` (status 1) for one the
    # session never had, `NAME=value` when set; a server it cannot reach fails with another message.
    said = done.stdout.strip()
    never_had = done.returncode != 0 and done.stderr.strip() == f"unknown variable: {TMUX_SSH_VARIABLE}"
    return not (said == f"-{TMUX_SSH_VARIABLE}" or never_had)


def in_herdr(environ: Mapping[str, str]) -> bool:
    """Whether the TUI runs in a herdr pane: herdr's `HERDR_ENV=1` (the gate `herdr.py` reads) or its
    `TERM_PROGRAM`."""
    return environ.get("HERDR_ENV") == "1" or terminal_name(environ) == "herdr"


def herdr_drops(environ: Mapping[str, str], size: int) -> bool:
    """Whether herdr drops an OSC 52 written in this pane that carries `size` bytes of text."""
    return in_herdr(environ) and size > HERDR_CLIPBOARD_BYTES


def copy_route(
    environ: Mapping[str, str], platform: str, tmux_over_ssh: Callable[[Mapping[str, str]], bool] = tmux_client_over_ssh,
    size: int = 0,
) -> str:
    """How a copy of `size` bytes from the pager reaches the clipboard: COPY_OSC52 in a herdr pane outside tmux
    (COPY_TOO_LARGE past what herdr takes) or for a terminal outside tmux that honours OSC 52 as it ships, COPY_PBCOPY
    on a Mac the screen is on (no SSH between them, tmux's last client included), else COPY_UNCONFIRMED."""
    if in_herdr(environ) and not environ.get("TMUX"):
        return COPY_TOO_LARGE if herdr_drops(environ, size) else COPY_OSC52
    if terminal_name(environ) in OSC52_TERMINALS and not environ.get("TMUX"):
        return COPY_OSC52
    if platform != "darwin" or any(environ.get(name) for name in SSH_VARIABLES):
        return COPY_UNCONFIRMED
    if environ.get("TMUX") and tmux_over_ssh(environ):
        return COPY_UNCONFIRMED
    return COPY_PBCOPY


def pbcopy(text: str, environ: Mapping[str, str]) -> bool:
    """`text` on the Mac's clipboard through `pbcopy`, read as UTF-8 whatever the locale says; False when it did not
    run or failed."""
    try:
        done = subprocess.run(
            ["pbcopy"], input=text.encode("utf-8", "replace"), env={**environ, "LC_ALL": "en_US.UTF-8"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=PBCOPY_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0
