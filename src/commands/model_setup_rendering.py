from __future__ import annotations

import shlex
from typing import Callable

from .language import tr


def print_model_preview_review(
    payload: dict[str, object],
    *,
    language: str,
    use_color: Callable[[], bool],
    color: Callable[[str, str, bool], str],
) -> None:
    print("")
    print(color(tr(language, "model_setup_preview_title"), "1;32", use_color()))
    print(f"  config: {payload.get('config_path', '')}")
    print(f"  digest: {payload.get('approval_digest', '') or payload.get('config_digest', '')}")
    changes = payload.get("changes", {})
    if isinstance(changes, dict):
        for alias, model in changes.items():
            print(f"  {alias} -> {model}")
    fallback = payload.get("fallback_model")
    if isinstance(fallback, dict):
        before = fallback.get("before")
        shown = ", ".join(str(item) for item in before) if isinstance(before, list) and before else "(none)"
        print(f"  fallback chain: {shown} -> {fallback.get('after', '')}")
        if fallback.get("replaces_chain"):
            print("  The existing fallback chain is replaced by this one entry.")
        if fallback.get("unchanged"):
            print("  The fallback chain already is this one entry; nothing to write.")
        if fallback.get("refusal"):
            print(f"  Apply is refused: {fallback['refusal']}")


def print_model_activation_summary(
    payload: dict[str, object],
    *,
    language: str,
    use_color: Callable[[], bool],
    color: Callable[[str, str, bool], str],
) -> None:
    print("")
    print(color(tr(language, "model_setup_title"), "1;32", use_color()))
    print(f"  {tr(language, 'model_setup_scan')}")
    discovery = payload.get("discovery", {})
    sources = discovery.get("sources", {}) if isinstance(discovery, dict) else {}
    if isinstance(sources, dict):
        for name, result in sources.items():
            if not isinstance(result, dict):
                continue
            reasons = result.get("truncated_reasons", [])
            suffix = (
                f" ({tr(language, 'model_setup_truncated', reasons=', '.join(str(item) for item in reasons))})"
                if reasons
                else ""
            )
            print(f"  - {name}: {result.get('status', 'unobserved')}{suffix}")
    candidates = payload.get("candidates", [])
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict):
                print(f"  - {candidate.get('model', '')}: {candidate.get('status', 'unobserved')}")
    if payload.get("status") == "hermes_unavailable":
        print(f"  {tr(language, 'model_setup_hermes_unavailable')}")
    elif payload.get("status") == "hermes_command_failed":
        print(f"  {tr(language, 'model_setup_hermes_command_failed', reason=payload.get('reason', ''))}")
    elif payload.get("status") == "hermes_config_unreadable":
        print(f"  {tr(language, 'model_setup_config_unreadable', path=payload.get('config_path', ''))}")
    elif payload.get("status") == "hermes_config_missing":
        key = "model_setup_config_missing_dry_run" if payload.get("dry_run") else "model_setup_config_missing"
        print(f"  {tr(language, key, path=payload.get('config_path', ''))}")
    elif not any(
        isinstance(candidate, dict) and candidate.get("status") == "confirmed_active"
        for candidate in candidates if isinstance(candidates, list)
    ):
        print(f"  {tr(language, 'model_setup_no_active')}")
    apply = payload.get("apply")
    if isinstance(apply, dict) and apply.get("status") == "dry_run":
        # Nothing ran; show the exact argv a real apply would run.
        for command in apply.get("commands") or []:
            if isinstance(command, list):
                print(f"  {tr(language, 'model_setup_would_run', command=shlex.join(str(part) for part in command))}")
    print(f"  {tr(language, 'model_setup_status', status=payload.get('status', 'unconfigured'))}")
    print(f"  {tr(language, 'model_setup_next', action=payload.get('next_action', ''))}")
    print(f"  {tr(language, 'model_setup_chains_hint')}")
    # The Maestro lane has its own category dial; naming it here keeps the
    # two mixtures discoverable from the one flow an operator actually runs.
    print(f"  {tr(language, 'model_setup_maestro_hint')}")
