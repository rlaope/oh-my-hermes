"""Public facade for the opt-in, bounded update-availability watch.

State, curl transport, and rewritten-history recovery are deliberately separate
so the launch-facing API remains stable while each concern stays auditable.
"""
from __future__ import annotations

from .update_check_probe import AncestryProbeResult, GITHUB_COMMITS_API_URL, GITHUB_COMPARE_API_URL_TEMPLATE, GITHUB_RELEASES_API_URL, GITHUB_REPOSITORY_API_URL, GITHUB_TAGS_API_URL, PROBE_RESPONSE_BOUNDARY, ReleasesProbeResult, RemoteProbeResult, TagsProbeResult, UPDATE_CHECK_NETWORK_TIMEOUT_SECONDS, WatchedBranchProbe, fetch_cursor_ancestry, fetch_recovery_releases, fetch_recovery_tags, fetch_remote_main_identity, fetch_watched_branch_state
from .update_check_recovery import RECOVERY_LEDGER_LIMIT, UPDATE_CHECK_ANCESTRY_CLASSES, accept_update_check_gap, cursor_advance_allowed, evaluate_update_check, format_notice_line, refresh_cache_after_auto_update
from .update_check_state import DEFAULT_UPDATE_CHECK_INTERVAL_HOURS, DEFAULT_UPDATE_CHECK_MODE, MAX_UPDATE_CHECK_INTERVAL_HOURS, MIN_UPDATE_CHECK_INTERVAL_HOURS, UPDATE_CHECK_CACHE_SCHEMA_VERSION, UPDATE_CHECK_MODES, UPDATE_CHECK_POLICY_SCHEMA_VERSION, UPDATE_CHECK_RESULT_SCHEMA_VERSION, WATCHED_BRANCH, acquire_auto_update_lock, local_installed_channel, local_installed_commit, read_update_check_cache, read_update_check_policy, update_check_cache_path, update_check_policy_recorded, write_update_check_policy


def record_remote_commit_for_install(paths, *, runner=None, timeout: float = UPDATE_CHECK_NETWORK_TIMEOUT_SECONDS) -> str:
    """Best-effort main cursor for an already-explicit install or update."""
    return fetch_remote_main_identity(timeout=timeout, runner=runner).sha or ""


__all__ = (
    "AncestryProbeResult", "DEFAULT_UPDATE_CHECK_INTERVAL_HOURS", "DEFAULT_UPDATE_CHECK_MODE", "GITHUB_COMMITS_API_URL", "GITHUB_COMPARE_API_URL_TEMPLATE", "GITHUB_RELEASES_API_URL", "GITHUB_REPOSITORY_API_URL", "GITHUB_TAGS_API_URL", "MAX_UPDATE_CHECK_INTERVAL_HOURS", "MIN_UPDATE_CHECK_INTERVAL_HOURS", "PROBE_RESPONSE_BOUNDARY", "RECOVERY_LEDGER_LIMIT", "ReleasesProbeResult", "RemoteProbeResult", "TagsProbeResult", "UPDATE_CHECK_ANCESTRY_CLASSES", "UPDATE_CHECK_CACHE_SCHEMA_VERSION", "UPDATE_CHECK_MODES", "UPDATE_CHECK_NETWORK_TIMEOUT_SECONDS", "UPDATE_CHECK_POLICY_SCHEMA_VERSION", "UPDATE_CHECK_RESULT_SCHEMA_VERSION", "WATCHED_BRANCH", "WatchedBranchProbe", "accept_update_check_gap", "acquire_auto_update_lock", "cursor_advance_allowed", "evaluate_update_check", "fetch_cursor_ancestry", "fetch_recovery_releases", "fetch_recovery_tags", "fetch_remote_main_identity", "fetch_watched_branch_state", "format_notice_line", "local_installed_channel", "local_installed_commit", "read_update_check_cache", "read_update_check_policy", "record_remote_commit_for_install", "refresh_cache_after_auto_update", "update_check_cache_path", "update_check_policy_recorded", "write_update_check_policy",
)
