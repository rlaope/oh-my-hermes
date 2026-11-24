from __future__ import annotations

import sqlite3
from typing import Any

from ..version import __version__
from ..paths import OmhPaths
from ..maintenance.cache_report import CacheReportError, main_read_share
from ..plugin_bundle.omh.runtime_reader import _hud_segments, read_omh_hud


def build_hud_payload(
    paths: OmhPaths,
    *,
    preset: str = "focused",
    limit: int = 3,
    token_metadata: dict[str, Any] | None = None,
    graph_preference: str = "auto",
    session_ref: str = "",
    delegation_graph: bool = True,
) -> dict[str, Any]:
    payload = read_omh_hud(
        omh_home=paths.omh_home,
        hermes_home=paths.hermes_home,
        preset=preset,
        limit=limit,
        token_metadata=token_metadata or {},
        package_version=__version__,
        graph_preference=graph_preference,
        session_ref=session_ref,
        delegation_graph=delegation_graph,
    )
    cache = _cache_field(paths)
    if cache is not None:
        payload["cache"] = cache
        # The display was drawn before the field existed; draw it again so the text line carries `cache:`.
        segments = _hud_segments(payload, preset=str(payload.get("preset", "focused")))
        payload["display"]["segments"] = segments
        payload["display"]["line"] = " | ".join(segments)
    return payload


def _cache_field(paths: OmhPaths) -> dict[str, Any] | None:
    """Last 24h prompt-cache read share of the main sessions; left out when it cannot be read, so it never breaks the HUD.

    Every failure a read-only sqlite read can raise lands here: no or unopenable database (`CacheReportError`), a
    locked, corrupt or foreign file (`sqlite3.Error`), a filesystem fault (`OSError`), odd column values.
    """
    try:
        return main_read_share(paths.hermes_home, hours=24)
    except (CacheReportError, sqlite3.Error, OSError, ValueError, TypeError):
        return None
