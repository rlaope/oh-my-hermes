from __future__ import annotations

import importlib.resources as resources
import importlib.util
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .hashutil import sha256_file, sha256_text
from .local_store import atomic_write_json, ensure_dir, read_json_object, utc_now
from .paths import OmhPaths

PLUGIN_NAME = "omh"
PLUGIN_SCHEMA_VERSION = "plugin_distribution/v1"
PLUGIN_MANAGED_MANIFEST = ".omh-plugin-manifest.json"
PLUGIN_ENABLE_HINT = "Hermes may require `hermes plugins enable omh` after the bundle is installed."


class PluginPackError(Exception):
    pass


@dataclass(frozen=True)
class PluginFileRecord:
    path: str
    sha256: str


class _SmokeContext:
    def __init__(self) -> None:
        self.tools: list[str] = []
        self.hooks: list[str] = []

    def register_tool(self, name: str, *args: object, **kwargs: object) -> None:
        self.tools.append(name)

    def register_hook(self, name: str, *args: object, **kwargs: object) -> None:
        self.hooks.append(name)


def install_plugin_bundle(paths: OmhPaths, *, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    target = paths.hermes_plugin_dir
    source_records = bundled_plugin_records()
    existing_manifest = read_plugin_manifest(target)
    dirty = plugin_local_modifications(existing_manifest, target)
    unmanaged = target.exists() and existing_manifest is None
    if unmanaged and not force:
        raise PluginPackError(f"{target} exists without an OMH plugin manifest; use --force to replace it")
    if dirty and not force:
        raise PluginPackError(f"managed plugin files changed: {', '.join(dirty)}; use --force to replace them")

    changed = force or unmanaged or existing_manifest is None or _manifest_file_map(existing_manifest) != _record_file_map(source_records)
    result = _plugin_distribution_payload(
        paths,
        dry_run=dry_run,
        observed=False if dry_run else True,
        changed=changed,
        file_records=source_records,
        dirty_files=dirty,
    )
    if dry_run:
        result["observed_scope"] = "dry run only; no plugin files were written"
        return result
    _copy_plugin_bundle(target, source_records)
    smoke = inspect_plugin_bundle(paths)
    result.update(
        {
            "import_smoke": smoke["plugin_import_smoke"],
            "register_smoke": smoke["plugin_register_smoke"],
            "registered_tools": smoke["registered_tools"],
            "registered_hooks": smoke["registered_hooks"],
        }
    )
    return result


def inspect_plugin_bundle(paths: OmhPaths) -> dict[str, Any]:
    target = paths.hermes_plugin_dir
    manifest = read_plugin_manifest(target)
    plugin_yaml = target / "plugin.yaml"
    init_py = target / "__init__.py"
    errors: list[str] = []
    if target.exists() and not target.is_dir():
        errors.append(f"{target} is not a directory")
    if target.exists() and not manifest:
        errors.append(f"{target / PLUGIN_MANAGED_MANIFEST} is missing or unreadable")
    manifest_valid = _manifest_valid(manifest, target)
    if target.exists() and not manifest_valid:
        errors.append("plugin manifest is invalid or stale")
    if target.exists() and not plugin_yaml.exists():
        errors.append(f"{plugin_yaml} is missing")
    if target.exists() and not init_py.exists():
        errors.append(f"{init_py} is missing")
    smoke = _register_smoke(target) if target.exists() and plugin_yaml.exists() and init_py.exists() else {}
    import_smoke = bool(smoke.get("import_smoke", False))
    register_smoke = bool(smoke.get("register_smoke", False))
    if target.exists() and smoke.get("error"):
        errors.append(str(smoke["error"]))
    return {
        "schema_version": PLUGIN_SCHEMA_VERSION,
        "plugin_name": PLUGIN_NAME,
        "plugin_dir": str(target),
        "plugin_dir_installed": target.exists() and target.is_dir(),
        "plugin_manifest_path": str(target / PLUGIN_MANAGED_MANIFEST),
        "plugin_manifest_present": manifest is not None,
        "plugin_manifest_valid": manifest_valid,
        "plugin_yaml_present": plugin_yaml.exists(),
        "plugin_import_smoke": import_smoke,
        "plugin_register_smoke": register_smoke,
        "registered_tools": smoke.get("registered_tools", []),
        "registered_hooks": smoke.get("registered_hooks", []),
        "plugin_distribution_ready": bool(target.exists() and manifest_valid and import_smoke and register_smoke),
        "plugin_runtime_observed": False,
        "requires_hermes_plugin_enable": target.exists(),
        "enable_hint": PLUGIN_ENABLE_HINT,
        "errors": errors,
    }


def bundled_plugin_records() -> list[dict[str, str]]:
    root = resources.files("omh.plugin_bundle.omh")
    records: list[PluginFileRecord] = []
    _collect_resource_records(root, Path("."), records)
    return [record.__dict__ for record in sorted(records, key=lambda item: item.path)]


def read_plugin_manifest(plugin_dir: Path) -> dict[str, Any] | None:
    try:
        return read_json_object(plugin_dir / PLUGIN_MANAGED_MANIFEST)
    except (OSError, ValueError):
        return None


def plugin_local_modifications(manifest: dict[str, Any] | None, plugin_dir: Path) -> list[str]:
    if not manifest:
        return []
    modified: list[str] = []
    for record in manifest.get("files", []):
        rel = str(record.get("path", ""))
        expected = str(record.get("sha256", ""))
        if not rel or not expected:
            continue
        path = plugin_dir / rel
        if not path.exists():
            modified.append(rel)
        elif sha256_file(path) != expected:
            modified.append(rel)
    return modified


def _collect_resource_records(root: Any, rel: Path, records: list[PluginFileRecord]) -> None:
    for item in root.iterdir():
        if item.name == "__pycache__" or item.name.endswith(".pyc"):
            continue
        item_rel = rel / item.name
        if item.is_dir():
            _collect_resource_records(item, item_rel, records)
        elif item.is_file():
            records.append(PluginFileRecord(str(item_rel), sha256_text(item.read_text(encoding="utf-8"))))


def _copy_plugin_bundle(target: Path, file_records: list[dict[str, str]]) -> None:
    root = resources.files("omh.plugin_bundle.omh")
    parent = target.parent
    tmp = parent / f".{target.name}.installing"
    backup = parent / f".{target.name}.previous"
    ensure_dir(parent)
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    try:
        _copy_resource_tree(root, tmp)
        atomic_write_json(tmp / PLUGIN_MANAGED_MANIFEST, _new_plugin_manifest(target, file_records))
        if target.exists():
            target.rename(backup)
        tmp.rename(target)
        shutil.rmtree(backup, ignore_errors=True)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        if backup.exists() and not target.exists():
            backup.rename(target)
        raise


def _copy_resource_tree(root: Any, dest: Path) -> None:
    ensure_dir(dest)
    for item in root.iterdir():
        if item.name == "__pycache__" or item.name.endswith(".pyc"):
            continue
        target = dest / item.name
        if item.is_dir():
            _copy_resource_tree(item, target)
        elif item.is_file():
            target.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")


def _new_plugin_manifest(target: Path, file_records: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "schema_version": PLUGIN_SCHEMA_VERSION,
        "package": "oh-my-hermes",
        "version": __version__,
        "plugin_name": PLUGIN_NAME,
        "plugin_dir": str(target),
        "installed_at": utc_now(),
        "source": "builtin",
        "files": file_records,
        "requires_hermes_plugin_enable": True,
        "enable_hint": PLUGIN_ENABLE_HINT,
    }


def _plugin_distribution_payload(
    paths: OmhPaths,
    *,
    dry_run: bool,
    observed: bool,
    changed: bool,
    file_records: list[dict[str, str]],
    dirty_files: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": PLUGIN_SCHEMA_VERSION,
        "plugin_name": PLUGIN_NAME,
        "plugin_dir": str(paths.hermes_plugin_dir),
        "dry_run": dry_run,
        "observed": observed,
        "changed": changed,
        "files": len(file_records),
        "dirty_files": dirty_files,
        "requires_hermes_plugin_enable": True,
        "enable_hint": PLUGIN_ENABLE_HINT,
        "observed_scope": (
            "local plugin bundle install and import/register smoke only; this does not prove Hermes loaded or used the plugin"
        ),
    }


def _manifest_valid(manifest: dict[str, Any] | None, target: Path) -> bool:
    if not manifest:
        return False
    if manifest.get("schema_version") != PLUGIN_SCHEMA_VERSION or manifest.get("plugin_name") != PLUGIN_NAME:
        return False
    return not plugin_local_modifications(manifest, target)


def _register_smoke(plugin_dir: Path) -> dict[str, Any]:
    module_name = "_omh_plugin_smoke"
    _clear_smoke_modules(module_name)
    try:
        spec = importlib.util.spec_from_file_location(
            module_name,
            plugin_dir / "__init__.py",
            submodule_search_locations=[str(plugin_dir)],
        )
        if spec is None or spec.loader is None:
            return {"import_smoke": False, "register_smoke": False, "error": "could not load plugin spec"}
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        ctx = _SmokeContext()
        register = getattr(module, "register", None)
        if not callable(register):
            return {"import_smoke": True, "register_smoke": False, "error": "register(ctx) is missing"}
        register(ctx)
        required_tools = {"omh_gather_evidence", "omh_hud", "omh_role", "omh_status"}
        required_hooks = {"on_session_end", "pre_llm_call", "pre_tool_call"}
        return {
            "import_smoke": True,
            "register_smoke": required_tools.issubset(set(ctx.tools)) and required_hooks.issubset(set(ctx.hooks)),
            "registered_tools": sorted(ctx.tools),
            "registered_hooks": sorted(ctx.hooks),
        }
    except Exception as exc:
        return {"import_smoke": False, "register_smoke": False, "error": f"plugin smoke failed: {exc}"}
    finally:
        _clear_smoke_modules(module_name)


def _clear_smoke_modules(module_name: str) -> None:
    for name in list(sys.modules):
        if name == module_name or name.startswith(f"{module_name}."):
            sys.modules.pop(name, None)


def _manifest_file_map(manifest: dict[str, Any] | None) -> dict[str, str]:
    if not manifest:
        return {}
    return {str(item.get("path", "")): str(item.get("sha256", "")) for item in manifest.get("files", [])}


def _record_file_map(records: list[dict[str, str]]) -> dict[str, str]:
    return {record["path"]: record["sha256"] for record in records}
