"""Import the oh-my-hermes package OMH's own installer put on this machine (#2166, #2415).

Hermes loads this bundle with its own interpreter. On a Hermes install its
package manager prepares, that interpreter imports only from the dependency
environment the package manager built, and nothing a person may do puts
`oh-my-hermes` there: the package manager admits only what a plugin declares
from a package index, it takes the interpreter's own `site-packages` off
`sys.path` when Hermes starts, and `oh-my-hermes` is on no index. Every
documented OMH install -- the curl/PowerShell installer, Homebrew, npm, Bun,
`uv tool`, `pip` -- still leaves a complete, pure-Python `omh` package on disk,
in OMH's own environment. The `omh setup` / `omh update` that copies this
bundle records where, as `package_site` in the bundle's own
`.omh-plugin-manifest.json`, and this module lets the bundle import `omh` from
there.

The reach is deliberately narrow:

* `sys.path` is not touched. One finder joins `sys.meta_path`, only when the
  interpreter has no `omh` of its own, and answers only for `omh` and for
  `omh.*` submodules of the package it loaded from that directory. Nothing
  else in the directory (OMH's `pip`, anything an installer added) becomes
  importable, so nothing can shadow a module Hermes or its dependency
  environment provides, and an `omh` the interpreter can already import (a
  self-managed Hermes environment with the package in it, a source checkout
  under test) is never displaced.
* The recorded directory is used only when it holds an `oh-my-hermes`
  distribution whose version equals this bundle's `plugin.yaml` version, and
  an `omh/__init__.py`. A stale or mismatched install is reported, never
  imported. The package needs Python 3.11 or newer and has no third-party
  dependencies (`dependencies = []`), so it runs on Hermes' interpreter as it
  runs on its own.
* Modules loaded this way never write bytecode: the directory belongs to OMH's
  installer (the npm/Bun launcher hashes its cache tree, so an extra file is
  tampering to it), not to Hermes.
* The manifest that names the directory sits beside this file and is written
  by the same `omh setup` that wrote the bundle's code, so whoever could change
  it could already change the code it would import beside.

Stdlib only, like every module of the bundle.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

from . import runtime_reader as _runtime_reader

PLUGIN_MANIFEST_NAME = ".omh-plugin-manifest.json"
PACKAGE_SITE_KEY = "package_site"
DISTRIBUTION_NAME = "oh-my-hermes"

# Why the last attempt did or did not make the recorded package importable.
SITE_ADDED = "added"
SITE_ALREADY_IMPORTABLE = "already_importable"
SITE_NOT_RECORDED = "not_recorded"
SITE_MISSING = "missing"
SITE_VERSION_MISMATCH = "version_mismatch"
SITE_UNREADABLE = "unreadable"
SITE_UNSUPPORTED_PYTHON = "unsupported_python"

_state: dict[str, Any] = {"status": "", "path": "", "installed_version": "", "bundle_version": ""}


def _bundle_dir() -> Path:
    return Path(__file__).resolve().parent


def _bundle_version() -> str:
    bundle = _bundle_dir()
    return _runtime_reader._plugin_version(bundle, root=bundle)


def _record(status: str, path: str = "", installed_version: str = "", bundle_version: str = "") -> str:
    _state.update(status=status, path=path, installed_version=installed_version, bundle_version=bundle_version)
    return status


def _installed_finder() -> "_OmhSiteFinder | None":
    return next((finder for finder in sys.meta_path if isinstance(finder, _OmhSiteFinder)), None)


def _omh_importable() -> bool:
    if "omh" in sys.modules:
        return True
    import importlib.util

    try:
        return importlib.util.find_spec("omh") is not None
    except Exception:  # noqa: BLE001 - see the classified-site verdict
        # Something answers for the name (an import hook that raises, a
        # module with no spec), so it is not absent: the recorded directory
        # is left alone, and the backend import that follows meets the same
        # failure and is classified `broken` or `incompatible`.
        return True


def recorded_site() -> str:
    """The directory the bundle's own manifest records, or "" when it records none."""
    payload = json.loads((_bundle_dir() / PLUGIN_MANIFEST_NAME).read_text(encoding="utf-8"))
    block = payload.get(PACKAGE_SITE_KEY) if isinstance(payload, dict) else None
    path = block.get("path") if isinstance(block, dict) else None
    return path if isinstance(path, str) and os.path.isabs(path) else ""


def installed_distribution_version(directory: str) -> str:
    """The version of the oh-my-hermes installed in `directory`, or "".

    Installed means a wheel install: an `oh_my_hermes-*.dist-info` whose
    RECORD lists `omh/__init__.py` in that same directory. A source checkout
    can hold an `oh_my_hermes.egg-info` beside an `omh/` shim, and an editable
    install's metadata names a package that lives elsewhere; neither is the
    package in that directory, so neither counts.
    """
    import importlib.metadata

    for found in importlib.metadata.distributions(name=DISTRIBUTION_NAME, path=[directory]):
        if not str(getattr(found, "_path", "")).endswith(".dist-info"):
            continue
        record = found.read_text("RECORD") or ""
        if any(line.split(",", 1)[0] == "omh/__init__.py" for line in record.splitlines()):
            return str(found.version or "")
    return ""


def active_site() -> str:
    """The directory this bundle imports `omh` from through its finder, or ""."""
    finder = _installed_finder()
    return finder.site if finder is not None else ""


def ensure_recorded_package_site() -> str:
    """Make the recorded oh-my-hermes importable when it is safe to; return why or why not.

    Called at `register()` and again before every backend import, so an
    install that finishes after Hermes started is picked up by the next call.
    """
    finder = _installed_finder()
    if finder is not None:
        return _record(SITE_ADDED, finder.site, finder.version, finder.version)
    if _omh_importable():
        return _record(SITE_ALREADY_IMPORTABLE)
    if sys.version_info < (3, 11):
        return _record(SITE_UNSUPPORTED_PYTHON)
    try:
        path = recorded_site()
    except FileNotFoundError:
        return _record(SITE_NOT_RECORDED)
    except Exception:  # noqa: BLE001 - see the classified-site verdict
        # An unreadable or malformed manifest is no evidence of an install:
        # nothing is added, and the backend import then fails the ordinary
        # way and is classified.
        return _record(SITE_UNREADABLE)
    bundle_version = _bundle_version()
    if not path:
        return _record(SITE_NOT_RECORDED, bundle_version=bundle_version)
    if not os.path.isfile(os.path.join(path, "omh", "__init__.py")):
        return _record(SITE_MISSING, path, bundle_version=bundle_version)
    try:
        installed_version = installed_distribution_version(path)
    except Exception:  # noqa: BLE001 - same verdict as the manifest read
        return _record(SITE_UNREADABLE, path, bundle_version=bundle_version)
    if not bundle_version or installed_version != bundle_version:
        return _record(SITE_VERSION_MISMATCH, path, installed_version, bundle_version)
    # First on `sys.meta_path`, so `omh.*` submodules are loaded by this
    # finder's read-only loader rather than by the default path finder, which
    # would write `.pyc` files into the installer's tree. It answers for
    # nothing outside `omh`, and only after `_omh_importable` found no `omh`
    # of the interpreter's own, so it shadows nothing.
    sys.meta_path.insert(0, _OmhSiteFinder(path, installed_version))
    import importlib

    importlib.invalidate_caches()
    return _record(SITE_ADDED, path, installed_version, bundle_version)


def package_site_state() -> dict[str, Any]:
    """What the last `ensure_recorded_package_site` decided."""
    return dict(_state)


class _OmhSiteFinder:
    """Find `omh` and `omh.*` in one directory, loading them without writing bytecode.

    `importlib.abc.MetaPathFinder` is not subclassed: importing `importlib.abc`
    costs the plugin load more than the protocol is worth, and the import
    system needs only `find_spec`.
    """

    def __init__(self, site: str, version: str) -> None:
        self.site = site
        self.version = version

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname != "omh" and not fullname.startswith("omh."):
            return None
        import importlib.machinery

        search = [self.site] if fullname == "omh" else list(path or ())
        # A submodule is ours only when its parent package came from this
        # directory; any other `omh` is left to the finders after this one.
        if fullname != "omh" and not all(_under(entry, self.site) for entry in search):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, search)
        if spec is not None and spec.origin is not None and type(spec.loader) is importlib.machinery.SourceFileLoader:
            # Same file, same spec; only the loader differs, so nothing is
            # loaded from a path the path finder did not already resolve.
            spec.loader = _ReadOnlySourceLoader(fullname, spec.origin)
        return spec

    def invalidate_caches(self) -> None:
        return None


def _under(entry: Any, root: str) -> bool:
    if not isinstance(entry, str) or not entry:
        return False
    child = os.path.normcase(os.path.realpath(entry))
    parent = os.path.normcase(os.path.realpath(root))
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def _read_only_loader_class() -> type:
    import importlib.machinery

    class ReadOnlySourceLoader(importlib.machinery.SourceFileLoader):
        def set_data(self, path: Any, data: Any, *, _mode: int = 0o666) -> None:
            # The one call that writes a `.pyc`; OMH's installer owns this tree.
            return None

    return ReadOnlySourceLoader


def _ReadOnlySourceLoader(fullname: str, origin: str) -> Any:
    global _READ_ONLY_LOADER
    if _READ_ONLY_LOADER is None:
        _READ_ONLY_LOADER = _read_only_loader_class()
    return _READ_ONLY_LOADER(fullname, origin)


_READ_ONLY_LOADER: type | None = None


__all__ = [
    "PACKAGE_SITE_KEY",
    "SITE_ADDED",
    "SITE_ALREADY_IMPORTABLE",
    "SITE_MISSING",
    "SITE_NOT_RECORDED",
    "SITE_UNREADABLE",
    "SITE_UNSUPPORTED_PYTHON",
    "SITE_VERSION_MISMATCH",
    "active_site",
    "installed_distribution_version",
    "ensure_recorded_package_site",
    "package_site_state",
    "recorded_site",
]
