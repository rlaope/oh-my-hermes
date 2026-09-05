#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ─── How to run ───
# uv run tools/package_manager/bump_version.py

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

try:
    from tools.package_manager.metadata import (
        PROJECT_ROOT,
        VERSION_PATTERN,
        DistributionError,
        canonical_version,
    )
except ImportError:  # running as a standalone script from tools/package_manager
    from metadata import (
        PROJECT_ROOT,
        VERSION_PATTERN,
        DistributionError,
        canonical_version,
    )


PYPROJECT_VERSION_PATTERN = re.compile(r'^version = "([^"]+)"$', re.MULTILINE)
SOURCE_VERSION_PATTERN = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)
PLUGIN_VERSION_PATTERN = re.compile(r'^version: "([^"]+)"$', re.MULTILINE)
# The landing page's hero badge: one static line in index.html plus one string
# per locale in i18n.js. Both are gated against __version__ by
# VersionSurfaceParityTests, so a bump that skipped them would fail the suite
# the release workflow runs on the bumped tree.
SITE_BADGE_PATTERN = re.compile(r'(data-i18n="hero\.badge">[^<]*?· v)(\d+\.\d+\.\d+)(</span>)')
SITE_I18N_BADGE_PATTERN = re.compile(r'((?:en|ko|ja|zh): "[^"\n]*?· v)(\d+\.\d+\.\d+)(")')
STABLE_CHANNEL = "stable"


def next_patch_version(version: str) -> str:
    """Return the next patch release after one canonical X.Y.Z version."""

    if not VERSION_PATTERN.fullmatch(version):
        raise DistributionError("release versions must use X.Y.Z")
    major, minor, patch = (int(part) for part in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def _rewrite_one_version(
    path: Path,
    pattern: re.Pattern[str],
    replacement: str,
    *,
    surface: str,
) -> str:
    try:
        content = path.read_text()
    except OSError as exc:
        raise DistributionError(f"could not read {surface}") from exc
    matches = pattern.findall(content)
    if len(matches) != 1:
        raise DistributionError(
            f"{surface} must carry exactly one literal version line"
        )
    return pattern.sub(replacement, content, count=1)


def _rewrite_badge_versions(
    path: Path,
    pattern: re.Pattern[str],
    new_version: str,
    *,
    surface: str,
    expected: int,
) -> str:
    """Rewrite every hero-badge version in one site file, requiring exactly `expected` of them."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DistributionError(f"could not read {surface}") from exc
    matches = pattern.findall(content)
    if len(matches) != expected:
        raise DistributionError(
            f"{surface} must carry exactly {expected} hero-badge version string(s)"
        )
    return pattern.sub(lambda match: f"{match.group(1)}{new_version}{match.group(3)}", content)


def bump_version_surfaces(
    project_root: Path,
    *,
    target: str | None = None,
    dry_run: bool = False,
) -> str:
    """Move every version surface to the next release and return it.

    The pyproject/version.py parity refusal in ``canonical_version`` runs
    first, so a tree whose enforced surfaces already disagree is never
    bumped further apart. The plugin manifest is rewritten to the same
    target even when it lags behind, which heals historical drift instead
    of freezing it. The channel file is reset to ``stable`` because an
    automated bump is by definition the commit that cuts the next stable
    release.
    """

    current = canonical_version(project_root)
    new_version = target if target is not None else next_patch_version(current)
    if not VERSION_PATTERN.fullmatch(new_version):
        raise DistributionError("release versions must use X.Y.Z")
    if target is not None and new_version == current:
        raise DistributionError("target version must differ from the current one")

    rewrites = {
        project_root / "pyproject.toml": _rewrite_one_version(
            project_root / "pyproject.toml",
            PYPROJECT_VERSION_PATTERN,
            f'version = "{new_version}"',
            surface="pyproject.toml",
        ),
        project_root / "src" / "omh" / "version.py": _rewrite_one_version(
            project_root / "src" / "omh" / "version.py",
            SOURCE_VERSION_PATTERN,
            f'__version__ = "{new_version}"',
            surface="src/omh/version.py",
        ),
        project_root
        / "src"
        / "plugin_bundle"
        / "omh"
        / "plugin.yaml": _rewrite_one_version(
            project_root / "src" / "plugin_bundle" / "omh" / "plugin.yaml",
            PLUGIN_VERSION_PATTERN,
            f'version: "{new_version}"',
            surface="src/plugin_bundle/omh/plugin.yaml",
        ),
        project_root / "site" / "index.html": _rewrite_badge_versions(
            project_root / "site" / "index.html",
            SITE_BADGE_PATTERN,
            new_version,
            surface="site/index.html",
            expected=1,
        ),
        project_root / "site" / "i18n.js": _rewrite_badge_versions(
            project_root / "site" / "i18n.js",
            SITE_I18N_BADGE_PATTERN,
            new_version,
            surface="site/i18n.js",
            expected=4,
        ),
    }
    if dry_run:
        return new_version
    for path, content in rewrites.items():
        # The locale strings are CJK; a platform default encoding (cp1252 on
        # Windows CI) would refuse them, so every surface is written as UTF-8.
        path.write_text(content, encoding="utf-8")
    (project_root / ".release-channel").write_text(f"{STABLE_CHANNEL}\n")
    return new_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bump every OMH version surface to the next patch release and "
            "reset the release channel to stable."
        )
    )
    parser.add_argument("--set", dest="target", help="explicit X.Y.Z target")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="repository root holding the version surfaces",
    )
    arguments = parser.parse_args(argv)
    try:
        new_version = bump_version_surfaces(
            arguments.project_root,
            target=arguments.target,
            dry_run=arguments.dry_run,
        )
    except DistributionError as exc:
        print(f"bump refused: {exc}", file=sys.stderr)
        return 1
    print(new_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
