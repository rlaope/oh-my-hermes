"""Copy-only host boundaries recorded in docs/AGENT-SKILLS.md#host-support-matrix.

Claude's installers copy their own committed pack (`CLAUDE_PACK_SOURCE`), the
portable pack with Claude Code's listing change applied at generation; the
other five copy `agent-skills/` as is.

These are installation contracts, not evidence of host selection/execution.
Claude's correction was observed with 2.1.270 on 2026-09-13; the other rows
retain the recorded documentation/source assessment and its caveats.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import TypedDict

from ..install.agent_skills_projection import MANIFEST_NAME


@dataclass(frozen=True)
class HostAdapter:
    host: str
    repo_path: str
    user_path: str  # Relative to home, not a shell-expanded tilde.
    evidence: str
    caveat: str = ""
    transform: str = "copy-only"
    # The committed pack this host's installers copy, relative to the checkout.
    source: str = "agent-skills"


_EVIDENCE = "docs/AGENT-SKILLS.md#host-support-matrix"
# Claude Code's own copy: the portable pack plus its listing change
# (`claude_skill_files`), committed beside its installers.
CLAUDE_PACK_SOURCE = ".claude/agent-skills"
HOST_ADAPTERS = (
    HostAdapter("cursor", ".agents/skills", ".agents/skills", _EVIDENCE,
                "User-scope scanning not independently verified."),
    HostAdapter("claude", ".claude/skills", ".claude/skills", _EVIDENCE,
                "Repo discovery observed in Claude Code 2.1.270, 2026-09-13; not workflow execution.",
                source=CLAUDE_PACK_SOURCE),
    HostAdapter("codex", ".agents/skills", ".agents/skills", _EVIDENCE),
    HostAdapter("opencode", ".agents/skills", ".agents/skills", _EVIDENCE,
                "Skill tool is permission-gated."),
    HostAdapter("openclaw", ".agents/skills", ".agents/skills", _EVIDENCE,
                "Custom OPENCLAW_STATE_DIR skips the standard user path; workspace skills can take precedence."),
    HostAdapter("pi", ".agents/skills", ".agents/skills", _EVIDENCE,
                "Trusted projects only; first duplicate name wins."),
)


def host_adapter(host: str) -> HostAdapter:
    for adapter in HOST_ADAPTERS:
        if adapter.host == host:
            return adapter
    raise ValueError(f"Unknown Agent Skills host: {host}")


def host_pack_files(host: str, files: dict[str, str]) -> dict[str, str]:
    """The files `host` installs, given the portable pack's `files`."""
    if host_adapter(host).source == CLAUDE_PACK_SOURCE:
        from ..install.agent_skills_projection import claude_skill_files

        return claude_skill_files(files)
    return files


class HostAdapterManifest(TypedDict):
    schema_version: str
    host: str
    targets: dict[str, str]
    transform: str
    evidence: str
    caveat: str
    source: str
    inventory: str
    skills: list[str]


def checksum_inventory(hashes: dict[str, str]) -> str:
    """SHA256SUMS-compatible UTF-8, sorted POSIX paths, LF including final line."""
    return "".join(f"{digest}  {path}\n" for path, digest in sorted(hashes.items()))


def source_digest(hashes: dict[str, str]) -> str:
    """sha256 of ``checksum_inventory``; one value per pack, shared by the five `.agents` hosts."""
    return hashlib.sha256(checksum_inventory(hashes).encode("utf-8")).hexdigest()


def host_adapter_manifest(host: str, files: dict[str, str]) -> HostAdapterManifest:
    """Static per-host row. File digests live once per pack, in the ``inventory`` receipt under
    ``source``, so a skill body edit moves that receipt instead of every host's adapter."""
    adapter = host_adapter(host)
    files = host_pack_files(host, files)
    return {
        "schema_version": "omh_host_adapter/v1",
        "host": adapter.host,
        "targets": {"repo": adapter.repo_path, "user": adapter.user_path},
        "transform": adapter.transform,
        "evidence": adapter.evidence,
        "caveat": adapter.caveat,
        "source": adapter.source,
        "inventory": MANIFEST_NAME,
        "skills": sorted({path.split("/")[0] for path in files}),
    }
