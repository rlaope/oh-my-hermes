from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config_adapter import external_dirs, read_config
from .paths import OmhPaths

PROBE_STATUSES = ("available", "missing", "unknown", "unverified")


@dataclass(frozen=True)
class Capability:
    name: str
    status: str
    evidence: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "evidence": self.evidence,
            "message": self.message,
        }


def _has_file(path: Path) -> bool:
    return path.exists() and path.is_file()


def _has_dir(path: Path) -> bool:
    return path.exists() and path.is_dir()


def _wrapper_artifacts(paths: OmhPaths) -> list[Path]:
    if not paths.runtime_runs_dir.exists():
        return []
    return sorted(paths.runtime_runs_dir.glob("*/wrapper.json"))


def probe_capabilities(paths: OmhPaths) -> dict:
    config_text = read_config(paths.hermes_config_path)
    configured_dirs = external_dirs(config_text)
    skills_registered = str(paths.skills_dir) in configured_dirs
    capabilities: list[Capability] = []

    capabilities.append(
        Capability(
            "external_skill_dirs",
            "available" if skills_registered else ("missing" if paths.hermes_config_path.exists() else "unknown"),
            str(paths.hermes_config_path),
            "Hermes config registers the managed skill directory" if skills_registered else "Managed skill directory is not registered in this Hermes config",
        )
    )
    capabilities.append(
        Capability(
            "managed_skills",
            "available" if _has_file(paths.skills_dir / "oh-my-hermes" / "SKILL.md") else "missing",
            str(paths.skills_dir),
            "Managed oh-my-hermes skill is installed" if _has_file(paths.skills_dir / "oh-my-hermes" / "SKILL.md") else "Managed skills are not installed",
        )
    )
    hooks_markers = [paths.hermes_home / "hooks.yaml", paths.hermes_home / "hooks.json"]
    capabilities.append(
        Capability(
            "native_hooks",
            "unverified" if any(_has_file(path) for path in hooks_markers) else "unknown",
            ", ".join(str(path) for path in hooks_markers),
            "Hook-like files exist, but omh has no stable Hermes hook contract to claim native integration"
            if any(_has_file(path) for path in hooks_markers)
            else "No stable Hermes hook surface detected by file probe",
        )
    )
    capabilities.append(
        Capability(
            "plugin_bundles",
            "unverified" if _has_dir(paths.hermes_home / "plugins") else "unknown",
            str(paths.hermes_home / "plugins"),
            "Plugin directory exists, but omh has no stable Hermes plugin bundle contract"
            if _has_dir(paths.hermes_home / "plugins")
            else "No Hermes plugin directory detected by file probe",
        )
    )
    capabilities.append(
        Capability(
            "apps",
            "unverified" if _has_dir(paths.hermes_home / "apps") else "unknown",
            str(paths.hermes_home / "apps"),
            "Apps directory exists, but omh has no stable Hermes app contract"
            if _has_dir(paths.hermes_home / "apps")
            else "No Hermes app directory detected by file probe",
        )
    )
    mcp_markers = [paths.hermes_home / ".mcp.json", paths.hermes_home / "mcp.json"]
    capabilities.append(
        Capability(
            "mcp",
            "unverified" if any(_has_file(path) for path in mcp_markers) else "unknown",
            ", ".join(str(path) for path in mcp_markers),
            "MCP-like config exists, but omh has not verified a Hermes MCP extension contract"
            if any(_has_file(path) for path in mcp_markers)
            else "No Hermes MCP config detected by file probe",
        )
    )
    capabilities.append(
        Capability(
            "native_skill_metadata",
            "unknown",
            str(paths.hermes_config_path),
            "No stable Hermes-native skill metadata contract is known to omh yet",
        )
    )
    wrappers = _wrapper_artifacts(paths)
    capabilities.append(
        Capability(
            "wrapper_metadata",
            "available" if wrappers else "missing",
            ", ".join(str(path) for path in wrappers[:5]) if wrappers else str(paths.runtime_runs_dir),
            "Wrapper observation artifacts are present" if wrappers else "No wrapper observation artifacts recorded yet",
        )
    )

    return {
        "schema_version": 1,
        "omh_home": str(paths.omh_home),
        "hermes_home": str(paths.hermes_home),
        "capabilities": [capability.to_dict() for capability in capabilities],
        "native_integration_claim_ready": False,
        "claim_boundary": "Prompt-level routing is the default unless a future stable Hermes extension surface and runtime evidence prove deeper integration.",
    }
