from __future__ import annotations

import argparse
import sys

from ..installer import OmhError
from .chat import (
    _add_chat_commands,
    cmd_chat_interact,
    cmd_chat_route,
    cmd_chat_session_decision,
    cmd_chat_session_list,
    cmd_chat_session_prepare_handoff,
    cmd_chat_session_select_executor,
    cmd_chat_session_show,
    cmd_chat_session_start,
    cmd_chat_session_status,
)
from .coding import (
    _add_coding_commands,
    cmd_coding_delegate,
    cmd_coding_lifecycle_dispatch,
    cmd_coding_lifecycle_report,
    cmd_coding_lifecycle_result,
    cmd_coding_lifecycle_start,
    cmd_coding_lifecycle_verify,
)
from .demo import _add_demo_commands, cmd_demo_orchestration
from .docs import (
    _add_docs_commands,
    _add_harness_commands,
    cmd_docs_workflows,
    cmd_harness_inspect,
    cmd_harness_list,
    cmd_harness_validate,
)
from .hermes import _add_hermes_commands, cmd_hermes_plan
from .memory import _add_memory_commands, cmd_memory_apply, cmd_memory_inspect, cmd_memory_pack
from .playbook import _add_playbook_commands, cmd_playbook_inspect, cmd_playbook_list, cmd_playbook_recommend
from .runtime import (
    _add_runtime_commands,
    cmd_runtime_ci,
    cmd_runtime_delegate,
    cmd_runtime_delegation_status,
    cmd_runtime_export,
    cmd_runtime_merge,
    cmd_runtime_record,
    cmd_runtime_review,
    cmd_runtime_runs,
    cmd_runtime_show,
    cmd_runtime_status,
    cmd_runtime_validate,
    cmd_runtime_wrapper,
)
from .setup import (
    _add_top_level_commands,
    cmd_apply,
    cmd_convert,
    cmd_doctor,
    cmd_install,
    cmd_list,
    cmd_profile_inspect,
    cmd_profile_list,
    cmd_probe,
    cmd_recommend,
    cmd_setup,
    cmd_snippet,
    cmd_uninstall,
    cmd_update,
)
from .state import _add_state_commands, cmd_state_clear, cmd_state_finish, cmd_state_start, cmd_state_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omh",
        description="Bootstrap, verify, and operate oh-my-hermes support contracts for Hermes Agent.",
    )
    parser.add_argument("--omh-home", default=None)
    parser.add_argument("--hermes-home", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    _add_top_level_commands(sub)
    _add_docs_commands(sub)
    _add_harness_commands(sub)
    _add_playbook_commands(sub)
    _add_demo_commands(sub)
    _add_chat_commands(sub)
    _add_coding_commands(sub)
    _add_hermes_commands(sub)
    _add_memory_commands(sub)
    _add_runtime_commands(sub)
    _add_state_commands(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except OmhError as exc:
        print(f"omh: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
