"""Repository-owned adapters for bounded local diagnostic execution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath
import re
import shutil
import subprocess

from .diagnostic_execution import (
    DiagnosticExecutionEngine,
    DiagnosticExecutionSettings,
)
from .diagnostic_providers import (
    DEFAULT_PROVIDER_CAPABILITIES,
    DiagnosticProviderConfig,
    ProviderCapability,
)
from .local_diagnostic_process import LocalDiagnosticProviderRunner


SUPPORTED_LOCAL_PROVIDERS = ("pyright", "basedpyright", "ruff")
_FIXED_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_MAX_GIT_OUTPUT_BYTES = 65_536
_OVER_LIMIT_CHANGED_PATHS = 201


class GitChangedFileResolver:
    """Resolve changed paths from the Git worktree named by the request."""

    def resolve(
        self,
        workspace_id: str,
        baseline_revision: str,
        end_revision: str,
    ) -> tuple[str, ...]:
        completed = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                "-z",
                "--diff-filter=ACDMR",
                baseline_revision,
                end_revision,
                "--",
            ],
            cwd=workspace_id,
            check=True,
            capture_output=True,
            timeout=30,
        )
        if len(completed.stdout) > _MAX_GIT_OUTPUT_BYTES:
            raise OSError("local diagnostics changed-file output exceeded its byte bound")
        try:
            changed = (
                value.decode("utf-8")
                for value in completed.stdout.split(b"\0")
                if value
            )
            paths = tuple(dict.fromkeys(_checked_changed_path(path) for path in changed))
        except UnicodeDecodeError as exc:
            raise OSError("local diagnostics changed-file output was not UTF-8") from exc
        return paths[:_OVER_LIMIT_CHANGED_PATHS]


class GitRevisionReader:
    """Resolve fixed revisions in the Git worktree named by the request."""

    def read(self, workspace_id: str, revision: str) -> str:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
            cwd=workspace_id,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        resolved = completed.stdout.strip()
        if _FIXED_COMMIT.fullmatch(resolved) is None:
            raise OSError("local diagnostics revision did not resolve to a fixed commit")
        if revision == "HEAD":
            status = subprocess.run(
                [
                    "git",
                    "status",
                    "--porcelain",
                    "--untracked-files=normal",
                ],
                cwd=workspace_id,
                check=True,
                capture_output=True,
                timeout=30,
            )
            if status.stdout:
                return "workspace-dirty"
        return resolved


def build_local_diagnostic_engine(
    *,
    executable_lookup: Callable[[str], str | None] = shutil.which,
) -> DiagnosticExecutionEngine:
    """Discover allowlisted local providers and build the bounded engine."""
    executables = {
        provider_id: executable
        for provider_id in SUPPORTED_LOCAL_PROVIDERS
        if (executable := executable_lookup(provider_id)) is not None
    }
    capabilities = tuple(
        _with_enabled(capability, capability.provider_id in executables)
        for capability in DEFAULT_PROVIDER_CAPABILITIES
        if capability.provider_id in (*SUPPORTED_LOCAL_PROVIDERS, "mypy")
    )
    return DiagnosticExecutionEngine(
        config=DiagnosticProviderConfig(capabilities),
        resolver=GitChangedFileResolver(),
        revisions=GitRevisionReader(),
        runner=LocalDiagnosticProviderRunner(executables),
        settings=DiagnosticExecutionSettings(
            max_global_concurrency=2,
            max_provider_concurrency=1,
            stateful_providers=frozenset(("pyright", "basedpyright")),
            revalidate_workspace_head=True,
        ),
    )


def _with_enabled(
    capability: ProviderCapability,
    enabled: bool,
) -> ProviderCapability:
    return ProviderCapability(
        provider_id=capability.provider_id,
        languages=capability.languages,
        file_suffixes=capability.file_suffixes,
        max_timeout_ms=capability.max_timeout_ms,
        max_diagnostics_per_check=capability.max_diagnostics_per_check,
        max_files_per_check=capability.max_files_per_check,
        enabled=enabled,
    )


def _checked_changed_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or ".git" in path.parts
    ):
        raise OSError("local diagnostics received an unsafe changed path")
    return path.as_posix()


__all__ = (
    "GitChangedFileResolver",
    "GitRevisionReader",
    "LocalDiagnosticProviderRunner",
    "SUPPORTED_LOCAL_PROVIDERS",
    "build_local_diagnostic_engine",
)
