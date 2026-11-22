"""Inert preset rows for third-party headless coding CLIs.

A preset is a *shape*, never a registration and never an installation: this
module holds literal argv tokens, a model fragment, an insertion index, a
version probe and the vendor page each row was read from. Nothing here looks
at PATH, spawns a process, writes a file or touches a home, so importing it
is free and a caller can render a plan without a vendor CLI present.

`user_executors.py` is the only consumer: an operator opts in with

    [executors.devin]
    preset = "devin"

and the loader expands that reference into a validated `ExecutorSpec`. The
presets are one-way dependencies of the loader -- this module must not import
dispatch, readiness or the plugin bundle, because it is data an operator sees
before any of those exist.

**Every preset is `validated=False`.** The vendor documentation and a fake
process in the tests prove an argv shape; neither proves an account, a
permission policy or a run that committed. The first live dispatch is the
validation, the same precedent as the `opencode` dispatch template. Do not
flip a row to validated on documentation alone, and let an installed CLI
refuse a write by its own policy rather than retrying in a looser permission
mode to make a lane green.

Sources were read on 2026-11-22; `source_url` records the page that documents
the flags below, so a later reader can re-check a flag without guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping


@dataclass(frozen=True)
class Preset:
    """One vendor's documented headless invocation, with no side effects.

    Token fields are tuples and an absent fragment is `()` -- never `None` --
    so a caller can splice `model`/`effort`/`export`/`resume` without a
    per-field type branch. `remote_adapter` names the shipped cloud lane
    builder a dispatch may use; `None` means this CLI has no remote lane here.
    """

    id: str
    label: str
    argv: tuple[str, ...]
    model: tuple[str, ...]
    effort: tuple[str, ...]
    insert: int
    version: tuple[str, ...]
    export: tuple[str, ...]
    resume: tuple[str, ...]
    remote_adapter: str | None
    source_url: str
    validated: bool = False


def _preset(
    preset_id: str,
    label: str,
    argv: tuple[str, ...],
    insert: int,
    model: tuple[str, ...],
    source_url: str,
    *,
    effort: tuple[str, ...] = (),
    export: tuple[str, ...] = (),
    resume: tuple[str, ...] = (),
    remote_adapter: str | None = None,
) -> Preset:
    """Build one row; `version` is always the CLI's own version probe.

    Every vendor below answers `--version`, and the probe must begin with the
    same literal program as `argv` (the loader enforces it), so deriving it
    here keeps the two from drifting apart.
    """
    return Preset(
        id=preset_id,
        label=label,
        argv=argv,
        model=model,
        effort=effort,
        insert=insert,
        version=(argv[0], "--version"),
        export=export,
        resume=resume,
        remote_adapter=remote_adapter,
        source_url=source_url,
        validated=False,
    )


# `insert` is the zero-based index into `argv` where a model/effort/session
# fragment is spliced: after the required subcommand and before any `--` or
# prompt-taking switch, so a spliced flag can never be read as prompt text or
# as the value of `--`.
PRESETS: Final[Mapping[str, Preset]] = MappingProxyType(
    {
        # Devin is the authoritative row (docs.devin.ai Commands & Flags).
        # `--respect-workspace-trust false` is required in a headless run: the
        # CLI otherwise stops on an interactive trust prompt. `--export` writes
        # an ATIF file per turn, which is the only session evidence this lane
        # records (see docs/FANOUT-EXECUTOR-EVIDENCE.md); `-r` re-enters that
        # session on a budgeted repair. `--cloud` is deliberately absent: only
        # the remote builder emits the cloud form, after two independent
        # opt-ins. ATIF does not establish that a given release emits a usable
        # session id, so a file without one is file-only evidence.
        "devin": _preset(
            "devin",
            "Devin CLI",
            (
                "devin",
                "-p",
                "--permission-mode",
                "accept-edits",
                "--respect-workspace-trust",
                "false",
                "--",
                "{prompt}",
            ),
            6,
            ("--model", "{model}"),
            "https://docs.devin.ai/cli/reference/commands",
            export=("--export", "{session_file}"),
            resume=("-r", "{session_id}"),
            remote_adapter="devin_cloud_v1",
        ),
        # `-p` takes the prompt as its value, so the fragment is inserted
        # before it (index 1) and the prompt stays attached to `-p`.
        "gemini": _preset(
            "gemini",
            "Gemini CLI",
            ("gemini", "-p", "{prompt}", "--approval-mode", "auto_edit"),
            1,
            ("-m", "{model}"),
            "https://geminicli.com/docs/cli/cli-reference/",
        ),
        # Qwen Code's non-interactive mode mirrors Gemini's; the approval value
        # is spelled `auto-edit` here (hyphen), unlike Gemini's `auto_edit`.
        "qwen": _preset(
            "qwen",
            "Qwen Code",
            ("qwen", "-p", "{prompt}", "--approval-mode", "auto-edit"),
            1,
            ("-m", "{model}"),
            "https://qwenlm.github.io/qwen-code-docs/1.x/en/users/cli-reference/",
        ),
        # `--print` is kimi-cli's non-interactive mode and `-c` its documented
        # alias for a one-shot prompt (print-mode page). No approval flag
        # exists; a policy refusal is reported, never escalated.
        "kimi": _preset(
            "kimi",
            "Kimi CLI",
            ("kimi", "--print", "-c", "{prompt}"),
            1,
            ("--model", "{model}"),
            "https://moonshotai.github.io/kimi-cli/en/customization/print-mode.html",
        ),
        # Vendor examples now spell the launcher `agent`; picking that name
        # would silently accept any unrelated `agent` on PATH, so the preset
        # requires the selected `cursor-agent` name and never substitutes.
        # `--force` broadens tool approvals beyond the default queue; the CLI
        # surfaces that on add.
        "cursor-agent": _preset(
            "cursor-agent",
            "Cursor CLI",
            ("cursor-agent", "-p", "--force", "{prompt}"),
            1,
            ("--model", "{model}"),
            "https://cursor.com/docs/cli/headless",
        ),
        # `-x` is Amp's execute (non-interactive) mode.
        "amp": _preset(
            "amp",
            "Amp",
            ("amp", "-x", "{prompt}"),
            1,
            ("--model", "{model}"),
            "https://ampcode.com/docs/cli/execute-mode",
        ),
        # `low` is the edit level. `medium` additionally grants git and remote
        # operations: a lane that needs the unit's commit must say so, never
        # receive it by silently widening this row.
        "droid": _preset(
            "droid",
            "Factory Droid",
            ("droid", "exec", "--auto", "low", "{prompt}"),
            2,
            ("--model", "{model}"),
            "https://docs.factory.ai/cli/droid-exec/overview",
        ),
        # `--yes-always` answers aider's confirmation prompts so the lane can
        # finish unattended; `--message` is the one-shot scripted form.
        "aider": _preset(
            "aider",
            "Aider",
            ("aider", "--yes-always", "--message", "{prompt}"),
            1,
            ("--model", "{model}"),
            "https://aider.chat/docs/config/options.html",
        ),
        # `run -t <text>` is goose's headless one-shot form.
        "goose": _preset(
            "goose",
            "Goose",
            ("goose", "run", "-t", "{prompt}"),
            2,
            ("--model", "{model}"),
            "https://github.com/aaif-goose/goose/blob/main/documentation/docs/guides/goose-cli-commands.md",
        ),
    }
)


def preset_ids() -> tuple[str, ...]:
    """Every preset id, sorted, as a fresh tuple (never the mapping's view)."""
    return tuple(sorted(PRESETS))


def get_preset(executor_id: str) -> Preset | None:
    """The preset for `executor_id`, or None. Case-sensitive: no aliases."""
    if not isinstance(executor_id, str):
        return None
    return PRESETS.get(executor_id)
