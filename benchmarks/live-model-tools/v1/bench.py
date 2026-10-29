#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "lib"))

from common import CONDITIONS, load_object  # noqa: E402
from corpus import generate_public  # noqa: E402
from runner import doctor, execute_one, run_matrix  # noqa: E402


def emit(value: object) -> None:
    print(json.dumps(value, sort_keys=True, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline-first OMH-native Hermes Agent model calibration benchmark"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--manifest", type=Path, default=BASE / "manifest.json")
    corpus_parser = sub.add_parser("corpus")
    corpus_parser.add_argument("--output", type=Path, default=BASE / "artifacts" / "corpus")
    corpus_parser.add_argument("--verify", action="store_true")
    for name in ("smoke", "run"):
        command = sub.add_parser(name)
        command.add_argument("--harness", choices=("fake", "omh", "hermes_current_session"), default="fake")
        command.add_argument("--manifest", type=Path, default=BASE / "manifest.json")
        command.add_argument("--model", action="append")
        command.add_argument("--condition", choices=CONDITIONS, default="baseline")
        command.add_argument("--split", choices=("development", "evaluation", "lsp-ab"), default="development")
        command.add_argument("--output", type=Path)
        command.add_argument("--omh-executable", default="omh")
        command.add_argument("--hermes-executable", default="hermes")
        command.add_argument(
            "--current-session-provider",
            help="Registered provider ID to use only with --harness hermes_current_session.",
        )
        command.add_argument(
            "--edit-surface",
            choices=("patch", "hashline", "lsp"),
            default="patch",
            help="Edit surface for hermes_current_session harness: 'patch' (default, builtin file toolset), 'hashline' (plugin toolset omh-hashline with OMH_HASHLINE_TOOLS=1) or 'lsp' (file,terminal plus plugin toolset omh-lsp).",
        )
        command.add_argument(
            "--edit-directive",
            nargs="?",
            const=True,
            default=False,
            choices=("rename",),
            help="Prepend the same edit-tool rule to both surfaces (names the surface's read/edit tools). "
            "'--edit-directive rename' prepends the rename rule pair (patch vs lsp) instead.",
        )
        command.add_argument(
            "--git-init-workspace",
            action="store_true",
            help="Run `git init -q` in the materialized workspace before the trial (Hermes LSP needs a git worktree).",
        )
        command.add_argument(
            "--test-env",
            action="store_true",
            help="Give the live session a ready test interpreter (pytest + workspace src/ on sys.path) and name it "
            "in the task, so neither arm spends turns installing packages.",
        )
        command.add_argument(
            "--extra-model",
            action="append",
            default=None,
            help="Additional live model to schedule without editing manifest.json. Format: id=...,provider=...,effort=...,family=... (repeatable).",
        )
        command.add_argument(
            "--templates",
            default=None,
            help="Comma-separated template IDs to include (e.g. E-RENAME,E-BUGFIX). Applies to the 'run' command.",
        )
        command.add_argument("--allow-paid-live", action="store_true")
        command.add_argument("--max-paid-calls", type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == "doctor":
        result = doctor(BASE, args.manifest)
    elif args.command == "corpus":
        result = generate_public(BASE, args.output, verify=args.verify)
    else:
        if args.current_session_provider and args.harness != "hermes_current_session":
            parser.error("--current-session-provider requires --harness hermes_current_session")
        if args.edit_surface and args.edit_surface != "patch" and args.harness != "hermes_current_session":
            parser.error(f"--edit-surface {args.edit_surface} requires --harness hermes_current_session")
        if args.edit_directive == "rename" and args.edit_surface not in {"patch", "lsp"}:
            parser.error("--edit-directive rename requires --edit-surface patch or lsp")
        if args.harness in {"omh", "hermes_current_session"} and not args.allow_paid_live:
            parser.error("live Hermes harness requires --allow-paid-live")
        if args.harness in {"omh", "hermes_current_session"} and args.max_paid_calls < 1:
            parser.error("live Hermes harness requires --max-paid-calls")
        manifest = load_object(args.manifest)
        live_models = [item for item in manifest["models"] if item.get("live")]
        if args.extra_model:
            for spec in args.extra_model:
                kv = {}
                for pair in spec.split(","):
                    if "=" not in pair:
                        parser.error(f"--extra-model must use key=value pairs: {spec}")
                    k, v = pair.split("=", 1)
                    kv[k.strip()] = v.strip()
                missing = {"id", "provider", "effort", "family"} - kv.keys()
                if missing:
                    parser.error(f"--extra-model is missing required keys: {', '.join(sorted(missing))}")
                if any(item["id"] == kv["id"] for item in live_models):
                    parser.error(f"duplicate model id in --extra-model: {kv['id']}")
                live_models.append({
                    "id": kv["id"],
                    "provider": kv["provider"],
                    "effort": kv["effort"],
                    "family": kv["family"],
                    "live": True,
                })
        if args.model:
            # Filter after --extra-model merges, so an extra model can be selected by id.
            live_models = [item for item in live_models if item["id"] in set(args.model)]
            if not live_models:
                parser.error("no manifest or --extra-model model matched --model")
        output = args.output or BASE / "artifacts" / args.condition / f"{args.split}-runs.jsonl"
        if args.command == "smoke":
            template_id, task_class, seed = ("D-RENAME", "edit", 7919)
            model = live_models[0] if args.harness in {"omh", "hermes_current_session"} else None
            result = execute_one(
                BASE,
                manifest,
                "development",
                template_id,
                task_class,
                seed,
                args.condition,
                output,
                args.harness,
                model=model,
                omh_executable=args.omh_executable,
                hermes_executable=args.hermes_executable,
                current_session_provider=args.current_session_provider,
                edit_surface=args.edit_surface,
                edit_directive=args.edit_directive,
                git_init_workspace=args.git_init_workspace,
                test_env=args.test_env,
            )
        else:
            result = run_matrix(
                BASE,
                manifest,
                args.split,
                args.condition,
                output,
                args.harness,
                models=live_models if args.harness in {"omh", "hermes_current_session"} else None,
                omh_executable=args.omh_executable,
                hermes_executable=args.hermes_executable,
                current_session_provider=args.current_session_provider,
                edit_surface=args.edit_surface,
                edit_directive=args.edit_directive,
                git_init_workspace=args.git_init_workspace,
                test_env=args.test_env,
                max_paid_calls=args.max_paid_calls,
                templates=args.templates.split(",") if args.templates else None,
            )
    emit(result)
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
