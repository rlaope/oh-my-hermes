"""The bundle imports the oh-my-hermes package OMH's installer recorded beside it (#2166, #2415).

Hermes' package-manager install loads this bundle with an interpreter whose
import path holds only Hermes' own dependency environment, and nothing a
person may do adds `oh-my-hermes` there. These tests build that host for real:
a fresh interpreter with no `omh` on its path, the bundle loaded under a
foreign name the way Hermes' loader names it, and a real wheel of this
checkout installed into a separate venv -- the shape every documented OMH
install leaves on disk. The bundle's `.omh-plugin-manifest.json` records that
venv's `site-packages` the way `omh setup` writes it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from _distribution_helpers import build_wheel, require_tool
from _local_package import load_local_package
from _standalone_bundle import bundle_dir

load_local_package()

from omh.install import plugin_pack  # noqa: E402
from omh.version import __version__  # noqa: E402

_HOST = r"""
import importlib.util
import json
import sys
from pathlib import Path

bundle = sys.argv[1]
before = importlib.util.find_spec("omh") is not None
spec = importlib.util.spec_from_file_location(
    "hermes_plugin_omh", bundle + "/__init__.py", submodule_search_locations=[bundle]
)
module = importlib.util.module_from_spec(spec)
sys.modules["hermes_plugin_omh"] = module
spec.loader.exec_module(module)


class Ctx:
    def __init__(self):
        self.tools = []
        self.hooks = []

    def register_tool(self, name, *args, **kwargs):
        self.tools.append(name)

    def register_hook(self, name, *args, **kwargs):
        self.hooks.append(name)


ctx = Ctx()
module.register(ctx)
from hermes_plugin_omh import package_site
from hermes_plugin_omh.tools.chat_tool import omh_interact_handler
from hermes_plugin_omh.tools.loop_tool import omh_loop_handler
from hermes_plugin_omh.tools.probe_tool import omh_probe_handler

start = {
    "action": "start",
    "goal_summary": "Make OMH a credible Hermes workflow pack with install, docs, QA, and feedback cycles.",
    "goal_reframe": "Ship one reviewed install-path fix with docs and a passing QA gate.",
    "success_criteria": ["install path fixed"],
    "permission_profile": "observe_only",
}
started = json.loads(omh_loop_handler(start, session_id="s"))
status = json.loads(omh_loop_handler({"action": "status"}, session_id="s"))
probe = json.loads(omh_probe_handler({}))
interact = json.loads(omh_interact_handler({"message": "fix the login bug"}))
omh = sys.modules.get("omh")
print(json.dumps({
    "omh_before": before,
    "tools": sorted(ctx.tools),
    "site": package_site.package_site_state(),
    "omh_file": getattr(omh, "__file__", None),
    "pip_importable": importlib.util.find_spec("pip") is not None,
    "loop_start": started,
    "loop_status": status,
    "probe": probe,
    "interact": interact,
}))
"""


# A gateway that stays up through `omh update`: its finder was installed on one
# generation's site, the update recorded the next, and GC later removed the
# first. Only `package_site` is loaded, under the foreign package name.
_FALL_FORWARD_HOST = r"""
import json
import shutil
import sys
import types

bundle, old, new = sys.argv[1:4]
package = types.ModuleType("hermes_plugin_omh")
package.__path__ = [bundle]
sys.modules["hermes_plugin_omh"] = package
from hermes_plugin_omh import package_site

manifest_path = bundle + "/.omh-plugin-manifest.json"


def record(site):
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest["package_site"]["path"] = site
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)


first = package_site.ensure_recorded_package_site()
import omh
import omh.sub

record(new)
kept = package_site.ensure_recorded_package_site()
kept_site = package_site.active_site()
import omh.early

shutil.rmtree(old)
moved = package_site.ensure_recorded_package_site()
import omh.late
import omh.sub.leaf

print(json.dumps({
    "first": first,
    "kept": kept,
    "kept_site": kept_site,
    "early": omh.early.__file__,
    "moved": moved,
    "moved_site": package_site.active_site(),
    "late": omh.late.__file__,
    "leaf": omh.sub.leaf.__file__,
}))
"""


def _fake_site(site: Path, version: str) -> None:
    """An installed-looking `omh` in `site`: the metadata the finder checks, and a few modules."""
    for relative in ("omh/__init__.py", "omh/early.py", "omh/late.py", "omh/sub/__init__.py", "omh/sub/leaf.py"):
        (site / relative).parent.mkdir(parents=True, exist_ok=True)
        (site / relative).write_text("", encoding="utf-8")
    info = site / f"oh_my_hermes-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: oh-my-hermes\nVersion: {version}\n", encoding="utf-8")
    (info / "RECORD").write_text("omh/__init__.py,,\n", encoding="utf-8")


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


class _InstalledPackage:
    """One real wheel of this checkout, installed once for the whole module."""

    root: Path | None = None
    site: Path | None = None
    holder: TemporaryDirectory | None = None

    @classmethod
    def get(cls) -> Path:
        if cls.site is None:
            cls.holder = TemporaryDirectory(prefix="omh-package-site-")
            cls.root = Path(cls.holder.name).resolve()
            wheel = build_wheel(cls.root / "wheel")
            venv = cls.root / "venv"
            uv = require_tool("uv")
            subprocess.run([uv, "venv", "-q", "--python", sys.executable, str(venv)], check=True, timeout=300)
            python = _venv_python(venv)
            subprocess.run([uv, "pip", "install", "-q", "-p", str(python), str(wheel)], check=True, timeout=300)
            purelib = subprocess.run(
                [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                check=True, capture_output=True, text=True, timeout=60,
            ).stdout.strip()
            cls.site = Path(purelib).resolve()
        return cls.site

    @classmethod
    def cleanup(cls) -> None:
        if cls.holder is not None:
            cls.holder.cleanup()
            cls.holder = None
            cls.site = None


def tearDownModule() -> None:  # noqa: N802 - unittest hook name
    _InstalledPackage.cleanup()


@unittest.skipIf(os.name == "nt", "the recorded package site is exercised on the POSIX lanes")
class RecordedPackageSiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.bundle = self.root / "hermes" / "plugins" / "omh"
        shutil.copytree(bundle_dir(), self.bundle, ignore=shutil.ignore_patterns("__pycache__"))
        (self.root / "hermes" / ".omh").mkdir(parents=True)

    def record(self, site: Path | str | None, version: str = __version__) -> None:
        manifest = {"schema_version": "plugin_distribution/v1", "plugin_name": "omh", "files": []}
        if site is not None:
            manifest["package_site"] = {"path": str(site), "version": version}
        (self.bundle / ".omh-plugin-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def host(self) -> dict:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(self.root / "home"),
            "HERMES_HOME": str(self.root / "hermes"),
            "OMH_HOME": str(self.root / "hermes" / ".omh"),
            "TMPDIR": str(self.root),
        }
        # `-I -S`: Hermes' interpreter with nothing of OMH's on its path.
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-c", _HOST, str(self.bundle)],
            env=env, cwd=str(self.root), capture_output=True, text=True, timeout=300, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_the_recorded_package_runs_every_package_backed_tool(self) -> None:
        site = _InstalledPackage.get()
        self.record(site)
        for pyc in site.rglob("*.pyc"):
            pyc.unlink()
        observed = self.host()
        self.assertFalse(observed["omh_before"])
        self.assertEqual(observed["site"]["status"], "added")
        self.assertEqual(Path(observed["omh_file"]).resolve(), site / "omh" / "__init__.py")
        # Nothing else in that directory becomes importable (its venv `pip`).
        self.assertFalse(observed["pip_importable"])
        self.assertEqual(observed["loop_start"]["status"], "ok", observed["loop_start"])
        self.assertEqual(observed["loop_status"]["status"], "ok")
        self.assertEqual(len(list((self.root / "hermes" / ".omh").rglob("cycle.json"))), 1)
        probe = observed["probe"]
        self.assertEqual(probe["source"], "package_probe_backend")
        rows = {row["name"]: row for row in probe["capabilities"]}
        self.assertEqual(rows["package_backend"]["status"], "available")
        self.assertIn(str(site), rows["package_backend"]["message"])
        self.assertTrue(observed["interact"]["wrapper_session"]["recorded"])
        # The installer's tree gains no bytecode from Hermes' interpreter.
        self.assertEqual(list(site.rglob("*.pyc")), [])

    def test_a_recorded_package_of_another_version_is_never_imported(self) -> None:
        site = _InstalledPackage.get()
        self.record(site)
        (self.bundle / "plugin.yaml").write_text(
            (self.bundle / "plugin.yaml").read_text(encoding="utf-8").replace(
                f'version: "{__version__}"', 'version: "999.0.0"'
            ),
            encoding="utf-8",
        )
        observed = self.host()
        self.assertEqual(observed["site"]["status"], "version_mismatch")
        self.assertEqual(observed["site"]["installed_version"], __version__)
        self.assertIsNone(observed["omh_file"])
        backend = observed["loop_status"]["package_backend"]
        self.assertEqual(backend["status"], "absent")
        detail = observed["loop_status"]["error_detail"]
        self.assertIn(f"that package is {__version__} while this plugin is 999.0.0", detail)
        self.assertIn("Run `omh update` (or `omh setup`)", detail)

    def test_a_recorded_directory_that_is_gone_says_so(self) -> None:
        self.record(self.root / "uninstalled" / "site-packages")
        observed = self.host()
        self.assertEqual(observed["site"]["status"], "missing")
        self.assertEqual(observed["loop_status"]["package_backend"]["status"], "absent")
        self.assertIn("is no longer there", observed["loop_status"]["error_detail"])

    def test_a_bundle_with_no_record_keeps_the_ordinary_refusal(self) -> None:
        self.record(None)
        observed = self.host()
        self.assertEqual(observed["site"]["status"], "not_recorded")
        self.assertEqual(observed["loop_status"]["error"], "service_unavailable")
        self.assertIn("Run `omh update` (or `omh setup`)", observed["loop_status"]["error_detail"])
        self.assertEqual(observed["probe"]["source"], "standalone_plugin_bundle_fallback")

    def test_a_malformed_manifest_adds_nothing_and_raises_nothing(self) -> None:
        (self.bundle / ".omh-plugin-manifest.json").write_text("{not json", encoding="utf-8")
        observed = self.host()
        self.assertEqual(observed["site"]["status"], "unreadable")
        self.assertEqual(len(observed["tools"]), len(set(observed["tools"])))
        self.assertEqual(observed["loop_status"]["error"], "service_unavailable")

    def test_a_directory_without_matching_metadata_is_not_imported(self) -> None:
        stray = self.root / "stray"
        (stray / "omh").mkdir(parents=True)
        (stray / "omh" / "__init__.py").write_text("raise SystemExit('must not import')\n", encoding="utf-8")
        self.record(stray)
        observed = self.host()
        self.assertEqual(observed["site"]["status"], "version_mismatch")
        self.assertEqual(observed["site"]["installed_version"], "")
        self.assertIsNone(observed["omh_file"])


    def test_a_finder_keeps_its_site_until_it_is_gone_then_falls_forward(self) -> None:
        old, new = self.root / "generations" / "a" / "site", self.root / "generations" / "b" / "site"
        _fake_site(old, __version__)
        _fake_site(new, __version__)
        self.record(old)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.root / "home"), "TMPDIR": str(self.root)}
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", _FALL_FORWARD_HOST, str(self.bundle), str(old), str(new)],
            env=env, cwd=str(self.root), capture_output=True, text=True, timeout=120, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["first"], "added")
        # While the first site is there the process keeps importing from it.
        self.assertEqual(observed["kept"], "added")
        self.assertEqual(observed["kept_site"], str(old))
        self.assertTrue(observed["early"].startswith(str(old)), observed["early"])
        # Once it is gone, the recorded site serves the next import, and a
        # subpackage loaded from the old site finds its submodules there too.
        self.assertEqual(observed["moved"], "added")
        self.assertEqual(observed["moved_site"], str(new))
        self.assertTrue(observed["late"].startswith(str(new)), observed["late"])
        self.assertTrue(observed["leaf"].startswith(str(new)), observed["leaf"])

class PackageSiteRecordTests(unittest.TestCase):
    """What `omh setup` writes beside the bundle."""

    def test_a_source_checkout_records_nothing(self) -> None:
        # This test process imports `omh` from the checkout's `src/`, where no
        # oh-my-hermes metadata sits beside the package.
        self.assertIsNone(plugin_pack.package_site_record())

    @unittest.skipIf(os.name == "nt", "the recorded package site is exercised on the POSIX lanes")
    def test_an_installed_wheel_records_its_own_site_packages(self) -> None:
        site = _InstalledPackage.get()
        python = site
        while python.name != "lib" and python != python.parent:
            python = python.parent
        interpreter = python.parent / "bin" / "python"
        result = subprocess.run(
            [str(interpreter), "-I", "-c",
             "import json; from omh.install.plugin_pack import package_site_record as r; print(json.dumps(r()))"],
            capture_output=True, text=True, timeout=120, check=True,
        )
        self.assertEqual(json.loads(result.stdout), {"path": str(site), "version": __version__})


if __name__ == "__main__":
    unittest.main()
