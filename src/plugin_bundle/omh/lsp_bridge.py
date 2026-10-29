"""The only OMH module that touches Hermes' LSP service internals.

Hermes (`agent.lsp`) runs language servers for its post-write diagnostics but has no
public call for definition / references / rename. This bridge drives the service's
private loop and client the same way Hermes' own diagnostics path does. Every private
attribute is looked up with ``getattr``; an absent one means ``lsp_unavailable``.
"""

from __future__ import annotations

import os
from typing import Any, Callable

REQUEST_TIMEOUT = 20.0
_PRIVATE = ("_loop", "_get_or_spawn", "enabled_for")


class BridgeError(Exception):
    """A failure the handlers answer with ``code``."""

    def __init__(self, code: str, hint: str) -> None:
        super().__init__(hint)
        self.code, self.hint = code, hint


def available() -> tuple[Any, str | None]:
    """``(service, None)`` when Hermes' LSP service can be driven, else ``(None, reason)``."""
    try:
        from agent.lsp import get_service

        svc = get_service()
    except Exception as exc:  # noqa: BLE001 - host absent or broken
        return None, f"lsp_unavailable: cannot load Hermes LSP ({type(exc).__name__})"
    if svc is None:
        return None, "lsp_unavailable: Hermes LSP is disabled (lsp.enabled in config.yaml)"
    missing = [name for name in _PRIVATE if getattr(svc, name, None) is None]
    if missing:
        return None, f"lsp_unavailable: this Hermes LSP service lacks {', '.join(missing)}"
    return svc, None


def in_git_worktree(abs_path: str) -> bool:
    """True when Hermes would gate ``abs_path`` in (it sits inside a git worktree)."""
    try:
        from agent.lsp.workspace import resolve_workspace_for_file

        root, gated = resolve_workspace_for_file(abs_path)
    except Exception:  # noqa: BLE001
        return False
    return bool(root and gated)


def _language_id(svc: Any, abs_path: str) -> str:
    try:
        from agent.lsp.servers import language_id_for

        server_for = getattr(svc, "_server_for", None)
        return language_id_for(abs_path, server_for(abs_path) if server_for else None)
    except Exception:  # noqa: BLE001
        return "python" if abs_path.endswith((".py", ".pyi")) else "plaintext"


def request(
    abs_path: str,
    method_builder: Callable[[], tuple[str, dict[str, Any]]],
    open_paths: list[str],
    timeout: float = REQUEST_TIMEOUT,
    open_texts: dict[str, str] | None = None,
) -> Any:
    """Send one request to the server for ``abs_path``; return the raw result.

    ``method_builder`` returns ``(method, params)``; it is called after every path in
    ``open_paths`` was opened, so params may depend on what the caller read from disk.
    ``open_texts`` (path -> text) syncs exactly that text instead of re-reading the disk, so a
    caller that snapshotted the bytes can later prove the server's edit was computed on them.
    Raises ``BridgeError`` (``lsp_unavailable``, ``server_unavailable``, ``timeout``).
    """
    svc, reason = available()
    if svc is None:
        raise BridgeError("lsp_unavailable", reason or "lsp_unavailable")
    if not svc.enabled_for(abs_path):
        raise BridgeError(
            "server_unavailable",
            "Hermes LSP has no usable server for this file (unsupported extension, disabled or broken server)",
        )

    async def run() -> Any:
        client = await svc._get_or_spawn(abs_path)
        if client is None:
            raise BridgeError("server_unavailable", "the language server could not be started for this file")
        if open_texts:
            for path, text in open_texts.items():
                await client.open_file(path, language_id=_language_id(svc, path), text=text)
        else:
            for path in open_paths:
                await client.open_file(path, language_id=_language_id(svc, path))
        method, params = method_builder()
        return await client._send_request_with_retry(method, params, timeout=timeout)

    try:
        return svc._loop.run(run(), timeout=timeout + 5)
    except BridgeError:
        raise
    except TimeoutError:  # asyncio's and concurrent.futures' TimeoutError are this builtin on 3.11+
        raise BridgeError("timeout", f"the language server did not answer within {int(timeout)} s") from None
    except Exception as exc:  # noqa: BLE001
        raise BridgeError("server_unavailable", f"language server request failed ({type(exc).__name__})") from None


def notify_changed(abs_path: str, paths: list[str]) -> None:
    """Re-sync ``paths`` with the server after OMH wrote them; errors are ignored."""
    try:
        svc, _ = available()
        if svc is None:
            return

        async def run() -> None:
            client = await svc._get_or_spawn(abs_path)
            if client is None:
                return
            for path in paths:
                if os.path.exists(path):
                    await client.open_file(path, language_id=_language_id(svc, path))

        svc._loop.run(run(), timeout=REQUEST_TIMEOUT)
    except Exception:  # noqa: BLE001
        return


__all__ = ["REQUEST_TIMEOUT", "BridgeError", "available", "in_git_worktree", "notify_changed", "request"]
