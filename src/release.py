from __future__ import annotations

from dataclasses import dataclass

REPOSITORY_ARCHIVE_ROOT = "https://github.com/rlaope/oh-my-hermes-agent/archive/refs"
RELEASE_CHANNELS = ("stable", "preview", "local")


@dataclass(frozen=True)
class ReleaseSelection:
    channel: str
    version: str
    package_url: str
    source_label: str


def package_url_for(channel: str, version: str = "", package_url: str = "") -> ReleaseSelection:
    if channel not in RELEASE_CHANNELS:
        raise ValueError(f"unsupported release channel: {channel}")
    if package_url:
        return ReleaseSelection(channel, version, package_url, "custom-url")
    if channel == "stable":
        if not version:
            raise ValueError("stable channel requires --version or OMH_VERSION")
        tag = version if version.startswith("v") else f"v{version}"
        return ReleaseSelection(channel, version, f"{REPOSITORY_ARCHIVE_ROOT}/tags/{tag}.zip", tag)
    if channel == "preview":
        return ReleaseSelection(channel, version, f"{REPOSITORY_ARCHIVE_ROOT}/heads/main.zip", "main")
    return ReleaseSelection(channel, version, "local", "local")
