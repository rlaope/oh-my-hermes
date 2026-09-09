from __future__ import annotations

import importlib.resources as resources
import importlib.util
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..version import __version__
from ..hashutil import sha256_file, sha256_text
from ..local_store import atomic_write_json, ensure_dir, read_json_object, utc_now
from ..paths import OmhPaths
from ..plugin_bundle.omh.metadata import PROVIDED_HOOKS, PROVIDED_TOOLS, REQUIRED_HOOKS

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
        self.tool_definitions: list[dict[str, object]] = []

    def register_tool(self, name: str, *args: object, **kwargs: object) -> None:
        self.tools.append(name)
        toolset = args[0] if len(args) > 0 else None
        schema = args[1] if len(args) > 1 else None
        handler = args[2] if len(args) > 2 else None
        description = kwargs.get("description")
        if description is None and isinstance(schema, dict):
            description = schema.get("description")
        self.tool_definitions.append(
            {
                "name": name,
                "toolset": toolset,
                "schema": schema,
                "handler": handler,
                "description": description,
            }
        )

    def register_hook(self, name: str, *args: object, **kwargs: object) -> None:
        self.hooks.append(name)


# Stable rule identifiers for `validate_tool_definitions` failures. These are
# part of the contract callers (doctor, setup, tests) key off of, so treat
# renames as breaking.
TOOL_SCHEMA_RULE_NOT_A_MAPPING = "tool_schema_not_a_mapping"
TOOL_SCHEMA_RULE_NAME_MISMATCH = "tool_schema_name_mismatch"
TOOL_SCHEMA_RULE_DESCRIPTION_MISSING = "tool_description_missing"
TOOL_SCHEMA_RULE_PARAMETERS_MISSING = "tool_parameters_missing"
TOOL_SCHEMA_RULE_PARAMETERS_NOT_A_MAPPING = "tool_parameters_not_a_mapping"
TOOL_SCHEMA_RULE_PARAMETERS_TYPE_NOT_OBJECT = "tool_parameters_type_not_object"
TOOL_SCHEMA_RULE_REQUIRED_NOT_A_LIST = "tool_parameters_required_not_a_list"
TOOL_SCHEMA_RULE_REQUIRED_FIELD_UNKNOWN = "tool_parameters_required_field_unknown"


def validate_tool_definitions(tool_definitions: list[dict[str, object]]) -> list[dict[str, str]]:
    """Validate captured tool registrations against the minimum Hermes tool contract.

    Schema-only: never touches ``handler`` and never calls it. Each failure
    carries a stable ``rule`` id plus the ``tool`` name so callers can surface
    a bounded message without leaking handler internals or unrelated plugin
    data.
    """
    failures: list[dict[str, str]] = []
    for definition in tool_definitions:
        name = str(definition.get("name", ""))
        schema = definition.get("schema")
        if not isinstance(schema, dict):
            failures.append({"tool": name, "rule": TOOL_SCHEMA_RULE_NOT_A_MAPPING})
            continue
        if schema.get("name") != name:
            failures.append({"tool": name, "rule": TOOL_SCHEMA_RULE_NAME_MISMATCH})
        description = definition.get("description")
        if not str(description or "").strip():
            failures.append({"tool": name, "rule": TOOL_SCHEMA_RULE_DESCRIPTION_MISSING})
        if "parameters" not in schema:
            failures.append({"tool": name, "rule": TOOL_SCHEMA_RULE_PARAMETERS_MISSING})
            continue
        parameters = schema["parameters"]
        if not isinstance(parameters, dict):
            failures.append({"tool": name, "rule": TOOL_SCHEMA_RULE_PARAMETERS_NOT_A_MAPPING})
            continue
        if parameters.get("type") != "object":
            failures.append({"tool": name, "rule": TOOL_SCHEMA_RULE_PARAMETERS_TYPE_NOT_OBJECT})
        required = parameters.get("required")
        if required is not None:
            if not isinstance(required, (list, tuple)):
                failures.append({"tool": name, "rule": TOOL_SCHEMA_RULE_REQUIRED_NOT_A_LIST})
            else:
                properties = parameters.get("properties")
                known = set(properties) if isinstance(properties, dict) else set()
                if any(field not in known for field in required):
                    failures.append({"tool": name, "rule": TOOL_SCHEMA_RULE_REQUIRED_FIELD_UNKNOWN})
    return failures


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
            "tool_schema_failures": smoke["tool_schema_failures"],
        }
    )
    return result


def inspect_plugin_bundle(paths: OmhPaths) -> dict[str, Any]:
    target = paths.hermes_plugin_dir
    manifest = read_plugin_manifest(target)
    bundled_records = bundled_plugin_records()
    manifest_file_map = _manifest_file_map(manifest)
    bundled_file_map = _record_file_map(bundled_records)
    plugin_yaml = target / "plugin.yaml"
    init_py = target / "__init__.py"
    conformance = _plugin_manifest_conformance(plugin_yaml)
    errors: list[str] = []
    if target.exists() and not target.is_dir():
        errors.append(f"{target} is not a directory")
    if target.exists() and not manifest:
        errors.append(f"{target / PLUGIN_MANAGED_MANIFEST} is missing or unreadable")
    manifest_valid = _manifest_valid(manifest, target)
    manifest_current = manifest_valid and manifest_file_map == bundled_file_map
    if target.exists() and not manifest_valid:
        errors.append("plugin manifest is invalid or managed files changed")
    if target.exists() and manifest_valid and not manifest_current:
        errors.append("plugin bundle is stale relative to the installed OMH package; run `omh setup` to refresh it")
    if target.exists() and not plugin_yaml.exists():
        errors.append(f"{plugin_yaml} is missing")
    if target.exists() and not init_py.exists():
        errors.append(f"{init_py} is missing")
    if target.exists() and not conformance["ok"]:
        errors.extend(f"plugin.yaml conformance: {field}" for field in conformance["invalid_fields"])
    smoke = _register_smoke(target) if target.exists() and plugin_yaml.exists() and init_py.exists() else {}
    import_smoke = bool(smoke.get("import_smoke", False))
    register_smoke = bool(smoke.get("register_smoke", False))
    if target.exists() and smoke.get("error"):
        errors.append(str(smoke["error"]))
    missing_tools = [str(item) for item in smoke.get("missing_registered_tools", [])]
    missing_hooks = [str(item) for item in smoke.get("missing_registered_hooks", [])]
    schema_failures = [item for item in smoke.get("tool_schema_failures", []) if isinstance(item, dict)]
    if target.exists() and import_smoke and not register_smoke and (missing_tools or missing_hooks):
        detail = []
        if missing_tools:
            detail.append(f"missing tools={missing_tools}")
        if missing_hooks:
            detail.append(f"missing hooks={missing_hooks}")
        errors.append("plugin register smoke is incomplete: " + "; ".join(detail))
    if target.exists() and import_smoke and schema_failures:
        errors.append(
            "plugin tool schema validation failed: "
            + "; ".join(f"{item.get('tool', '')}={item.get('rule', '')}" for item in schema_failures)
        )
    return {
        "schema_version": PLUGIN_SCHEMA_VERSION,
        "plugin_name": PLUGIN_NAME,
        "plugin_dir": str(target),
        "plugin_dir_installed": target.exists() and target.is_dir(),
        "plugin_manifest_path": str(target / PLUGIN_MANAGED_MANIFEST),
        "plugin_manifest_present": manifest is not None,
        "plugin_manifest_valid": manifest_valid,
        "plugin_manifest_current": manifest_current,
        "plugin_bundle_stale": target.exists() and manifest_valid and not manifest_current,
        "plugin_yaml_present": plugin_yaml.exists(),
        "plugin_manifest_conformance": conformance,
        "plugin_import_smoke": import_smoke,
        "plugin_register_smoke": register_smoke,
        "registered_tools": smoke.get("registered_tools", []),
        "registered_hooks": smoke.get("registered_hooks", []),
        "missing_registered_tools": missing_tools,
        "missing_registered_hooks": missing_hooks,
        "tool_schema_failures": schema_failures,
        "plugin_distribution_ready": bool(
            target.exists()
            and manifest_current
            and conformance["ok"]
            and import_smoke
            and register_smoke
        ),
        "plugin_runtime_observed": False,
        "requires_hermes_plugin_enable": target.exists(),
        "enable_hint": PLUGIN_ENABLE_HINT,
        "errors": errors,
    }


def _plugin_manifest_conformance(plugin_yaml: Path) -> dict[str, Any]:
    # Hermes may classify a memory-provider bundle without an explicit kind as
    # exclusive and skip its general tools/hooks loader. Keep this field
    # explicit and compare the advertised surface with OMH's runtime metadata.
    values = _manifest_values(plugin_yaml)
    kind = values.get("kind", "")
    declared_tools = _manifest_list(plugin_yaml, "provides_tools")
    declared_hooks = _manifest_list(plugin_yaml, "provides_hooks")
    invalid_fields: list[str] = []
    if values.get("name", "") != PLUGIN_NAME:
        invalid_fields.append("name")
    if kind != "standalone":
        invalid_fields.append("kind")
    if sorted(declared_tools) != sorted(PROVIDED_TOOLS):
        invalid_fields.append("provides_tools")
    if sorted(declared_hooks) != sorted(PROVIDED_HOOKS):
        invalid_fields.append("provides_hooks")
    return {
        "ok": not invalid_fields,
        "name": values.get("name", ""),
        "kind": kind,
        "declared_tools": declared_tools,
        "declared_hooks": declared_hooks,
        "invalid_fields": invalid_fields,
    }


def _manifest_values(plugin_yaml: Path) -> dict[str, str]:
    try:
        lines = plugin_yaml.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        if line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        values[key.strip()] = raw_value.strip().strip("\"'")
    return values


def _manifest_list(plugin_yaml: Path, key: str) -> list[str]:
    try:
        lines = plugin_yaml.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    values: list[str] = []
    active = False
    for line in lines:
        if not line.startswith((" ", "\t")):
            active = line.strip() == f"{key}:"
            continue
        if active:
            item = line.strip()
            if item.startswith("- "):
                values.append(item[2:].strip().strip("\"'"))
    return values


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
            # newline="" keeps disk bytes equal to the manifest's LF-normalized
            # hashes; plugin freshness compares sha256_file against sha256_text.
            target.write_text(item.read_text(encoding="utf-8"), encoding="utf-8", newline="")


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
        required_tools = set(PROVIDED_TOOLS)
        required_hooks = set(REQUIRED_HOOKS)
        missing_tools = sorted(required_tools.difference(ctx.tools))
        missing_hooks = sorted(required_hooks.difference(ctx.hooks))
        schema_failures = validate_tool_definitions(ctx.tool_definitions)
        return {
            "import_smoke": True,
            "register_smoke": not missing_tools and not missing_hooks and not schema_failures,
            "registered_tools": sorted(ctx.tools),
            "registered_hooks": sorted(ctx.hooks),
            "missing_registered_tools": missing_tools,
            "missing_registered_hooks": missing_hooks,
            "tool_schema_failures": schema_failures,
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
