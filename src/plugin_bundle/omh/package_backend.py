"""Why a native tool's `omh` package backend did or did not import here (#2166).

Every documented install puts the `oh-my-hermes` package in OMH's own
environment, not in the interpreter Hermes loads this bundle with. Before a
backend import, `load_backend` lets the bundle reach the package OMH's
installer recorded beside it (`package_site`), so on an ordinary install the
package-backed tools work. Where that cannot happen -- no `omh setup` has
recorded a package yet, the recorded one moved or is another version -- Hermes
still registers every tool and hook, and a tool that needs the package refuses
with a bounded result that says which failure it met and the one repair, never
raises. The tools that import the package through `load_backend`
(`omh_loop`, `omh_decision_gate`, and `omh_probe`'s package path) get one
answer per host.

Stdlib only, like every module of the bundle: the classifier must work on the
very host it describes.

An `absent` block also says when an oh-my-hermes install sits in one of this
interpreter's own install directories that is not on its import path
(`off_path_install`, #2415). Hermes' package manager takes the interpreter's
own `site-packages` off `sys.path` when Hermes starts and imports from the
dependency environment it prepares instead, so a package installed into that
interpreter imports when the interpreter runs alone and never under Hermes.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from typing import Any, Callable, TypeVar

from . import package_site as _package_site
from . import runtime_reader as _runtime_reader

# `absent` is the supported metadata-only install, and only one failure is it:
# a ModuleNotFoundError naming an `omh` module while no top-level `omh` exists.
# Every other failure is never `absent`. With an `omh` present, a missing
# `omh.*` module or name is `incompatible` (it does not provide what this
# bundle imports); any other failure while importing is `broken`.
PACKAGE_BACKEND_AVAILABLE = "available"
PACKAGE_BACKEND_ABSENT = "absent"
PACKAGE_BACKEND_INCOMPATIBLE = "incompatible"
PACKAGE_BACKEND_BROKEN = "broken"
# What the top-level `omh` this interpreter finds is: nothing, an installed
# oh-my-hermes distribution, or some other module of that name (a namespace
# directory, a stray `omh.py`, a checkout on the path) whose version no
# distribution metadata vouches for.
FOUND_NONE = "none"
FOUND_OH_MY_HERMES = "oh-my-hermes"
FOUND_OTHER = "other"
# Where the package-dependent features, and the install routes that exist for
# each kind of Hermes environment, are written down.
PACKAGE_BACKEND_ROUTE = "docs/INSTALLATION.md#what-the-hermes-interpreter-must-be-able-to-import"

_T = TypeVar("_T")


def _found_omh(package_version: str) -> str:
    # Asked at call time, never cached: the answer is a property of the
    # interpreter now, and a module-level answer would outlive a package
    # installed, or an import finished, after this bundle loaded. A module
    # already in `sys.modules` answers first: `find_spec` raises ValueError
    # for one whose `__spec__` is None. A namespace package (a bare `omh/`
    # directory) has no file of its own, and no oh-my-hermes install is one.
    module = sys.modules.get("omh")
    if module is not None:
        namespace = getattr(module, "__file__", None) is None
    else:
        try:
            spec = importlib.util.find_spec("omh")
        except Exception:
            # This runs inside `load_backend`'s handler, so a raise here would
            # escape the tool. An import hook that raises for `omh` itself is
            # something answering for that name, and not a working
            # oh-my-hermes, so the failure reads `broken`, never `absent`.
            return FOUND_OTHER
        if spec is None:
            return FOUND_NONE
        namespace = spec.origin is None
    return FOUND_OH_MY_HERMES if package_version and not namespace else FOUND_OTHER


def _distribution_version() -> str:
    # Read from distribution metadata rather than by importing `omh.version`:
    # the classification adds no `omh.*` module to `sys.modules`. Imported
    # here: `importlib.metadata` costs about 18 ms cold, and only a refusal or
    # `omh_probe` asks, never the plugin load Hermes times.
    import importlib.metadata

    try:
        return importlib.metadata.version("oh-my-hermes")
    except importlib.metadata.PackageNotFoundError:
        return ""


def _bundle_version() -> str:
    # The `version:` of this bundle's own plugin.yaml, through the reader the
    # HUD already uses for it; "" when the manifest cannot be read.
    bundle = Path(__file__).resolve().parent
    return _runtime_reader._plugin_version(bundle, root=bundle)


def _path_key(entry: str) -> str:
    return os.path.normcase(os.path.realpath(entry))


def _off_path_install() -> str:
    """An oh-my-hermes install in this interpreter's own site directory that its import path skips.

    Only once `site` has run (no `-S`): its site directories were on the path
    and something took one off afterwards. Under Hermes that is the package
    manager's activation (`pm.environments.activate_dependencies`), which
    drops every `site-packages` entry and imports from the environment it
    prepared, so a package installed into the interpreter itself imports when
    that interpreter runs alone and never under Hermes (#2415). Read from
    distribution metadata, like `_distribution_version`, so it imports
    nothing from that directory. "" when there is no such install.
    """
    if sys.flags.no_site:
        return ""
    import importlib.metadata
    import site
    import sysconfig

    try:
        directories = list(getattr(site, "getsitepackages", list)())
        paths = sysconfig.get_paths()
        directories += [paths[key] for key in ("purelib", "platlib") if paths.get(key)]
        on_path = {_path_key(entry) for entry in sys.path if isinstance(entry, str) and entry}
        for directory in dict.fromkeys(directories):
            if _path_key(directory) in on_path:
                continue
            if next(iter(importlib.metadata.distributions(name="oh-my-hermes", path=[directory])), None):
                return directory
    except Exception:
        # This runs inside `load_backend`'s handler, like `_found_omh`, so a
        # raise here would escape the tool. An unreadable directory, an
        # unknown install scheme or a `site` that a customization broke is
        # no evidence of an install there: the block stays a plain `absent`.
        return ""
    return ""


def classify_backend_failure(error: BaseException) -> dict[str, Any]:
    """The `package_backend` block for a backend import that just failed."""
    failed = str(error.name or "") if isinstance(error, ImportError) else ""
    names_omh = failed == "omh" or failed.startswith("omh.")
    package_version = _distribution_version()
    found = _found_omh(package_version)
    if found == FOUND_NONE:
        absent = isinstance(error, ModuleNotFoundError) and names_omh
        status = PACKAGE_BACKEND_ABSENT if absent else PACKAGE_BACKEND_BROKEN
    elif names_omh:
        status = PACKAGE_BACKEND_INCOMPATIBLE
    else:
        status = PACKAGE_BACKEND_BROKEN
    return {
        "status": status,
        "failed_import": failed,
        "error_type": type(error).__name__,
        "found_omh": found,
        "package_version": "" if status == PACKAGE_BACKEND_ABSENT else package_version,
        "bundle_version": _bundle_version(),
        "install_route": PACKAGE_BACKEND_ROUTE,
        "off_path_install": _off_path_install() if status == PACKAGE_BACKEND_ABSENT else "",
        "package_site": _package_site.package_site_state(),
    }


def available_backend() -> dict[str, Any]:
    """The `package_backend` block for a backend import that succeeded."""
    package_version = _distribution_version()
    return {
        "status": PACKAGE_BACKEND_AVAILABLE,
        "failed_import": "",
        "error_type": "",
        "found_omh": _found_omh(package_version),
        "package_version": package_version,
        "bundle_version": _bundle_version(),
        "install_route": PACKAGE_BACKEND_ROUTE,
        "off_path_install": "",
        "package_site": _package_site.package_site_state(),
    }


def load_backend(importer: Callable[[], _T]) -> tuple[_T | None, dict[str, Any] | None]:
    """Run a tool's backend import: `(what it returned, None)`, or `(None, block)`.

    Every failure is classified, never raised. A skewed install can fail at
    import with something other than ImportError -- a module-scope
    AttributeError or RuntimeError -- and the tool must still refuse, bounded,
    exactly as it does on a host with no package at all.

    First, when this interpreter has no `omh` of its own, the package OMH's
    installer recorded beside this bundle is put within reach (`package_site`,
    #2166): on a Hermes install its package manager prepares, that is the only
    way the package can be imported at all.
    """
    _package_site.ensure_recorded_package_site()
    try:
        return importer(), None
    except Exception as error:
        return None, classify_backend_failure(error)


def package_backend_detail(backend: dict[str, Any], *, feature: str, cli_route: str = "") -> str:
    """The sentence a person reads for a `package_backend` block.

    It names only routes that exist. A Hermes environment its package manager
    prepares has none yet, so it is never told to take the package by hand.
    `cli_route` is the feature's own CLI path to the same store, when it has
    one a person may use in its place.
    """
    status = backend["status"]
    site = backend.get("package_site") if isinstance(backend.get("package_site"), dict) else {}
    site_status = str(site.get("status") or "")
    site_path = str(site.get("path") or "")
    if status == PACKAGE_BACKEND_AVAILABLE:
        source = (
            f", from the package OMH's installer put in {site_path}" if site_status == "added" and site_path else ""
        )
        return f"The Python interpreter running this plugin imports the oh-my-hermes backend for {feature}{source}."
    bundle_version = str(backend.get("bundle_version") or "")
    at_version = f" {bundle_version}" if bundle_version else ""
    failed = f" (failed import: {backend['failed_import']})" if backend["failed_import"] else ""
    foreign = backend.get("found_omh") == FOUND_OTHER
    off_path = str(backend.get("off_path_install") or "")
    # The one repair for every absent case: the `omh` command rewrites this
    # bundle with the location of its own package, which the bundle then
    # imports from (#2166). Restarting Hermes reloads the bundle.
    repair = (
        "Run `omh update` (or `omh setup`) with the `omh` command you installed, then restart "
        "Hermes; the plugin then imports the package that command runs from."
    )
    if status == PACKAGE_BACKEND_ABSENT and site_status == "version_mismatch":
        installed = str(site.get("installed_version") or "another version")
        lead = (
            "The OMH plugin is registered, and OMH's installer recorded its package in "
            f"{site_path}, but that package is {installed} while this plugin is{at_version}, so "
            f"{feature} does not run against it. {repair}"
        )
    elif status == PACKAGE_BACKEND_ABSENT and site_status == "missing":
        lead = (
            "The OMH plugin is registered, but the package OMH's installer recorded in "
            f"{site_path} is no longer there, so {feature} has no backend here. {repair}"
        )
    elif status == PACKAGE_BACKEND_ABSENT and off_path:
        # #2415: a copy put in Hermes' own interpreter, which Hermes' package
        # manager takes off the import path at startup.
        lead = (
            "The OMH plugin is registered, but the Python interpreter running it cannot import "
            f"the oh-my-hermes package, so {feature} has no backend here. oh-my-hermes is "
            f"installed in {off_path}, that interpreter's own site directory, which is not on "
            "its import path while it runs this plugin: Hermes' package manager takes it off when "
            "Hermes starts and imports from the dependency environment it prepares instead, so an "
            f"install there imports when the interpreter runs alone and never under Hermes. {repair}"
        )
    elif status == PACKAGE_BACKEND_ABSENT:
        lead = (
            "The OMH plugin is registered, but the Python interpreter running it cannot import "
            f"the oh-my-hermes package, so {feature} has no backend here. {repair}"
        )
    elif status == PACKAGE_BACKEND_INCOMPATIBLE and foreign:
        lead = (
            "The Python interpreter running this plugin finds an `omh` module that is not an "
            f"installed oh-my-hermes package{failed}, so {feature} does not run against it."
        )
    elif status == PACKAGE_BACKEND_INCOMPATIBLE:
        match = (
            f"This plugin is {bundle_version}: bring that package to that version"
            if bundle_version
            else "Bring that package to the version that matches this plugin"
        )
        lead = (
            f"The Python interpreter running this plugin imports oh-my-hermes "
            f"{backend['package_version']}, which does not provide what {feature} imports{failed}, "
            f"so {feature} does not run against it. {match}, the same way it was installed."
        )
    else:
        what = {
            FOUND_OH_MY_HERMES: "that package",
            FOUND_OTHER: "that `omh` module",
        }.get(backend.get("found_omh"), "what that interpreter resolves as `omh`")
        lead = (
            f"Importing the oh-my-hermes backend for {feature} on the Python interpreter running "
            f"this plugin failed with {backend['error_type']}{failed}. That is not the "
            f"missing-package case: repair {what} the same way it was installed."
        )
    route = f" {cli_route}" if cli_route else ""
    return f"{lead}{route} See {PACKAGE_BACKEND_ROUTE}."


__all__ = [
    "FOUND_NONE",
    "FOUND_OH_MY_HERMES",
    "FOUND_OTHER",
    "PACKAGE_BACKEND_ABSENT",
    "PACKAGE_BACKEND_AVAILABLE",
    "PACKAGE_BACKEND_BROKEN",
    "PACKAGE_BACKEND_INCOMPATIBLE",
    "PACKAGE_BACKEND_ROUTE",
    "available_backend",
    "classify_backend_failure",
    "load_backend",
    "package_backend_detail",
]
