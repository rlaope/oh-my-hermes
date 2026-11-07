"""`omh`'s entry point (`omh.cli:main`).

A bare launch, an argv with only top-level options, opens the terminal from
`omh.commands.bare_launch` without importing the command tree. Every other
argv that opens with a known subcommand builds only that subcommand's parser
(`omh.commands.fast_dispatch`); every other argv goes to
`omh.commands.main.main`. This module used to star-import
`omh.commands.main`; its names are still reachable here, imported on first use.
"""

from __future__ import annotations

import sys
from typing import Any


def main(argv: list[str] | None = None) -> int:
    from ..commands.bare_launch import bare_launch_args, run_bare_launch

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = bare_launch_args(raw_argv)
    if args is not None:
        return run_bare_launch(args)
    # A subcommand imports only the module that registers it; anything else
    # (help, version, an unknown word) reads the full parser (`fast_dispatch`).
    from ..commands.fast_dispatch import fast_main

    ran = fast_main(raw_argv)
    if ran is not None:
        return ran
    from ..commands.main import main as command_main

    return command_main(raw_argv)


def __getattr__(name: str) -> Any:
    from ..commands import main as command_module

    return getattr(command_module, name)
