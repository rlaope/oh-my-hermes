from __future__ import annotations

import importlib.resources as resources
import importlib.util
import io
import json
import marshal
import sys
import tempfile
from types import CodeType
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..version import __version__
from ..hashutil import sha256_file, sha256_text
from ..local_store import (
    atomic_write_json,
    discard_path,
    ensure_dir,
    is_directory_link,
    read_json_object,
    read_json_object_result,
    utc_now,
)
from ..paths import OmhPaths
from ..plugin_bundle.omh.host_compat import HERMES_RANGE_FIELD, parse_range
from ..plugin_bundle.omh.metadata import PROVIDED_HOOKS, PROVIDED_TOOLS, REQUIRED_HOOKS

PLUGIN_NAME = "omh"
PLUGIN_SCHEMA_VERSION = "plugin_distribution/v1"
PLUGIN_MANAGED_MANIFEST = ".omh-plugin-manifest.json"
PLUGIN_ENABLE_HINT = "Hermes may require `hermes plugins enable omh` after the bundle is installed."
# Hermes' own records of a plugin that `hermes plugins install` put in place:
# the profile-wide sidecar `<plugins>/.install-metadata.json` keyed by plugin
# name (hermes_cli/plugins_cmd.py `_install_metadata_path`,
# `_install_plugin_core`) and, for a curated-catalog install, the provenance
# file inside the plugin directory (hermes_cli/plugins_cmd_catalog.py
# `CATALOG_SIDECAR`). Read only; OMH never writes either.
HERMES_INSTALL_METADATA = ".install-metadata.json"
HERMES_CATALOG_SIDECAR = ".hermes-catalog.json"
HERMES_PLUGIN_UPDATE_COMMAND = "hermes plugins update omh"

# The enforcement probe's vocabulary (issue #1561). Every name here is
# fabricated: no host serves a tool by either name and `PROVIDED_TOOLS` lists
# neither, so the probe cannot be mistaken for a real call by anything that
# sees it. The marker is the only content the probe's arguments carry.
ENFORCEMENT_PROBE_SCOPED_TOOL = "omh_enforcement_probe_scoped"
ENFORCEMENT_PROBE_UNSCOPED_TOOL = "omh_enforcement_probe_unscoped"
ENFORCEMENT_PROBE_MARKER = "omh-doctor-enforcement-smoke"
ENFORCEMENT_PROBE_SESSION = "omh-doctor-enforcement-smoke"
ENFORCEMENT_PROBE_RULES_FILE = "toolcall-rules.json"


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


def host_managed_plugin(
    target: Path, *, metadata_parent: Path | None = None, metadata_name: str | None = None
) -> dict[str, str] | None:
    """Hermes' own record that `hermes plugins install` put *target* in place, or None.

    Both installers replace the whole directory, so the one that wrote last
    owns it: an OMH manifest inside means OMH wrote it, whatever Hermes'
    metadata still says; without one, a Hermes install-metadata entry or a
    catalog sidecar means Hermes did. That plugin is updated by Hermes
    (`hermes plugins update omh` re-pins a catalog install to its reviewed
    SHA), so OMH neither overwrites it nor reports it as drift -- even under
    `--force`, which would leave Hermes' pin recorded against files it no
    longer describes. Switching back is `hermes plugins remove omh`, then
    `omh setup`.
    """
    if not target.is_dir() or read_plugin_manifest(target) is not None:
        return None
    metadata, _ = read_json_object_result((metadata_parent or target.parent) / HERMES_INSTALL_METADATA)
    entry = metadata.get(metadata_name or target.name) if isinstance(metadata, dict) else None
    entry = entry if isinstance(entry, dict) else None
    sidecar, _ = read_json_object_result(target / HERMES_CATALOG_SIDECAR)
    sidecar = sidecar if isinstance(sidecar, dict) and sidecar.get("catalog_name") else None
    if entry is None and sidecar is None:
        return None
    return {
        "installer": "hermes_catalog" if sidecar is not None else "hermes_git",
        "source": str((sidecar or {}).get("repo") or (entry or {}).get("source") or ""),
        "revision": str((sidecar or {}).get("sha") or (entry or {}).get("revision") or ""),
        "update_command": HERMES_PLUGIN_UPDATE_COMMAND,
    }


def install_plugin_bundle(paths: OmhPaths, *, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    target = paths.hermes_plugin_dir
    source_records = bundled_plugin_records()
    host_install = host_managed_plugin(target)
    if host_install is not None:
        result = _plugin_distribution_payload(
            paths, dry_run=dry_run, observed=not dry_run, changed=False, file_records=source_records, dirty_files=[]
        )
        result.update(
            {
                "status": "host_managed",
                "host_install": host_install,
                "observed_scope": "Hermes installed this plugin directory; OMH wrote nothing to it",
            }
        )
        return result
    existing_manifest = read_plugin_manifest(target)
    dirty = plugin_local_modifications(existing_manifest, target)
    # `is_directory_link` as well as `exists`: `Path.exists` follows the link,
    # so a dangling plugin symlink or junction reads as absent and would slip
    # past the ownership guard into the replacement path without --force. The
    # guard asks whether anything occupies the path OMH cannot prove it wrote.
    unmanaged = (target.exists() or is_directory_link(target)) and existing_manifest is None
    if unmanaged and not force:
        raise PluginPackError(f"{target} exists without an OMH plugin manifest; use --force to replace it")
    if dirty and not force:
        raise PluginPackError(f"managed plugin files changed: {', '.join(dirty)}; use --force to replace them")
    if existing_manifest is not None and not force:
        unknown = _plugin_unmanaged_entries(existing_manifest, target)
        if unknown:
            raise PluginPackError(
                f"unmanaged plugin entries: {', '.join(unknown)}; plugin directory left unchanged; "
                "move these entries outside the plugin directory, or use --force to replace them"
            )

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
    _copy_plugin_bundle(
        target, source_records, existing_manifest=existing_manifest, initially_occupied=bool(unmanaged), force=force
    )
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
    host_install = host_managed_plugin(target)
    bundled_records = bundled_plugin_records()
    manifest_file_map = _manifest_file_map(manifest)
    bundled_file_map = _record_file_map(bundled_records)
    plugin_yaml = target / "plugin.yaml"
    init_py = target / "__init__.py"
    conformance = _plugin_manifest_conformance(plugin_yaml)
    errors: list[str] = []
    if target.exists() and not target.is_dir():
        errors.append(f"{target} is not a directory")
    if target.exists() and not manifest and host_install is None:
        errors.append(f"{target / PLUGIN_MANAGED_MANIFEST} is missing or unreadable")
    manifest_valid = _manifest_valid(manifest, target)
    manifest_current = manifest_valid and manifest_file_map == bundled_file_map
    if target.exists() and not manifest_valid and host_install is None:
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
    # Only after the bundle has been proven to import. A probe against a
    # bundle that does not load would report `unknown` for a reason the import
    # tier already named, which is noise, not a second finding.
    enforcement = (
        _enforcement_smoke(target)
        if import_smoke
        else _enforcement_unknown("the installed plugin bundle has not passed local import smoke")
    )
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
        "plugin_host_managed": host_install is not None,
        "plugin_host_install": host_install or {},
        # `plugin_distribution_ready` below cannot hold a Hermes-pinned tree
        # to the package's file map, so the skew is stated here instead.
        "plugin_host_matches_package": host_install is not None
        and not plugin_local_modifications({"files": bundled_records}, target),
        "plugin_yaml_present": plugin_yaml.exists(),
        "plugin_manifest_conformance": conformance,
        "plugin_import_smoke": import_smoke,
        "plugin_register_smoke": register_smoke,
        "plugin_enforcement_smoke": bool(enforcement["enforcement_smoke"]),
        "plugin_enforcement_status": str(enforcement["enforcement_status"]),
        "plugin_enforcement_decision": str(enforcement["enforcement_decision"]),
        "plugin_enforcement_detail": str(enforcement["enforcement_detail"]),
        "registered_tools": smoke.get("registered_tools", []),
        "registered_hooks": smoke.get("registered_hooks", []),
        "missing_registered_tools": missing_tools,
        "missing_registered_hooks": missing_hooks,
        "tool_schema_failures": schema_failures,
        "plugin_distribution_ready": bool(
            target.exists()
            and (manifest_current or host_install is not None)
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
    hermes_range = values.get(HERMES_RANGE_FIELD, "")
    try:
        parse_range(hermes_range)
    except ValueError:
        invalid_fields.append(HERMES_RANGE_FIELD)
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
        "declared_hermes_range": hermes_range,
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


def _plugin_unmanaged_entries(manifest: dict[str, Any], plugin_dir: Path) -> list[str]:
    """Find additions using the installed manifest, never the incoming bundle.

    Links below the bundle root are entries, not directories to traverse. The
    root may itself be a legacy managed link; replacing it leaves its referent
    intact. Empty user directories also need consent before replacement.
    """
    managed = set(_manifest_file_map(manifest)) | {PLUGIN_MANAGED_MANIFEST}
    managed_dirs = {parent.as_posix() for rel in managed for parent in Path(rel).parents}
    unknown: list[str] = []

    def visit(directory: Path) -> None:
        entries = list(directory.iterdir())
        relative = directory.relative_to(plugin_dir).as_posix()
        if not entries and relative not in managed_dirs:
            unknown.append(relative)
        for entry in entries:
            rel = entry.relative_to(plugin_dir).as_posix()
            if is_directory_link(entry):
                unknown.append(rel)
            elif entry.is_dir():
                visit(entry)
            elif rel not in managed and not _generated_plugin_bytecode(entry, plugin_dir, managed):
                unknown.append(rel)

    try:
        visit(plugin_dir)
    except OSError as exc:
        raise PluginPackError(f"could not inspect plugin additions; plugin directory left unchanged: {exc}") from exc
    return sorted(unknown)


def _generated_plugin_bytecode(path: Path, plugin_dir: Path, managed: set[str]) -> bool:
    if path.parent.name != "__pycache__" or path.suffix != ".pyc" or not path.is_file():
        return False
    try:
        source = Path(importlib.util.source_from_cache(str(path)))
    except ValueError:
        return False
    if source.relative_to(plugin_dir).as_posix() not in managed:
        return False
    # Parsing marshal data creates a code object but never executes it. Cap
    # bytes actually read and require exactly one complete code object, not a
    # plausible header followed by arbitrary user bytes or a trailing payload.
    with path.open("rb") as file:
        data = file.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        return False
    stream = io.BytesIO(data)
    header = stream.read(16)
    if len(header) != 16 or header[:4] != importlib.util.MAGIC_NUMBER:
        return False
    if int.from_bytes(header[4:8], "little") not in (0, 1, 3):
        return False
    try:
        code = marshal.load(stream)
    except (EOFError, TypeError, ValueError):
        return False
    return isinstance(code, CodeType) and stream.read(1) == b""


def _collect_resource_records(root: Any, rel: Path, records: list[PluginFileRecord]) -> None:
    for item in root.iterdir():
        if item.name == "__pycache__" or item.name.endswith(".pyc"):
            continue
        item_rel = rel / item.name
        if item.is_dir():
            _collect_resource_records(item, item_rel, records)
        elif item.is_file():
            # One spelling on every platform: the record is compared as a
            # string against the packaged tree and read back through
            # `plugin_dir / path`, which accepts a forward slash everywhere.
            # `str(WindowsPath)` spells a nested record with a backslash, which
            # the Windows smoke run compared against the posix form and lost.
            records.append(PluginFileRecord(item_rel.as_posix(), sha256_text(item.read_text(encoding="utf-8"))))


def _copy_plugin_bundle(
    target: Path,
    file_records: list[dict[str, str]],
    *,
    existing_manifest: dict[str, Any] | None,
    initially_occupied: bool,
    force: bool,
) -> None:
    root = resources.files("omh.plugin_bundle.omh")
    parent = target.parent
    ensure_dir(parent)
    # Atomically reserve a private sibling on the same filesystem. Fixed
    # `.omh.previous` / `.omh.installing` siblings may contain user data or a
    # recovery backup from an earlier invocation; neither belongs to this one.
    transaction = Path(tempfile.mkdtemp(prefix=f".{target.name}.install-", dir=parent))
    tmp = transaction / f".{target.name}.installing"
    backup = transaction / f".{target.name}.previous"
    try:
        _copy_resource_tree(root, tmp)
        atomic_write_json(tmp / PLUGIN_MANAGED_MANIFEST, _new_plugin_manifest(target, file_records))
        # `is_directory_link` as well as `exists`, for the same reason the
        # ownership guard needs it: a dangling link occupies the path while
        # `exists()` reports it absent. Skipping the rename-aside for it leaves
        # `tmp.rename(target)` renaming a directory over a link, which is the
        # ENOTDIR this change exists to stop -- so --force could not repair the
        # very machine the guard tells the operator to repair with it. The
        # initial guard established ownership or force; revalidate after the
        # rename before replacing anything that appeared while staging.
        if target.exists() or is_directory_link(target):
            # A relative link is resolved from its original parent. Moving it
            # under the transaction directory changes where the link points;
            # inspect that original referent for a late Hermes takeover.
            linked_target = target.resolve() if is_directory_link(target) else None
            target.rename(backup)
            if existing_manifest is None and not initially_occupied:
                raise PluginPackError("plugin directory appeared during staging; original bundle restored")
            if host_managed_plugin(
                linked_target or backup, metadata_parent=parent, metadata_name=target.name
            ) is not None:
                raise PluginPackError(
                    f"plugin became Hermes-managed during staging; original bundle restored; "
                    f"use {HERMES_PLUGIN_UPDATE_COMMAND}"
                )
            if not force and existing_manifest is not None and not is_directory_link(backup):
                if read_plugin_manifest(backup) != existing_manifest:
                    raise PluginPackError("plugin manifest changed during staging; original bundle restored")
                dirty = plugin_local_modifications(existing_manifest, backup)
                if dirty:
                    raise PluginPackError(f"managed plugin files changed: {', '.join(dirty)}; original bundle restored")
                unknown = _plugin_unmanaged_entries(existing_manifest, backup)
                if unknown:
                    raise PluginPackError(f"unmanaged plugin entries: {', '.join(unknown)}; original bundle restored")
        tmp.rename(target)
    except (OSError, PluginPackError) as exc:
        # Link-aware checks also restore a dangling legacy root link. If the
        # original cannot be restored, retain its private workspace and name
        # the recovery path rather than deleting it during final cleanup.
        if backup.exists() or is_directory_link(backup):
            if target.exists() or is_directory_link(target):
                raise OSError(f"plugin replacement failed; target is occupied; original bundle retained at {backup}") from exc
            try:
                backup.rename(target)
            except OSError as rollback_error:
                raise OSError(
                    f"plugin replacement failed; rollback failed; original bundle retained at {backup}: {rollback_error}"
                ) from exc
        raise
    else:
        discard_path(backup, ignore_errors=True)
    finally:
        discard_path(tmp, ignore_errors=True)
        if not (backup.exists() or is_directory_link(backup)):
            discard_path(transaction, ignore_errors=True)


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


def _enforcement_smoke(plugin_dir: Path) -> dict[str, Any]:
    """Ask the INSTALLED bundle for a decision and report the one it gave.

    The third tier proves `register()` is callable. It says nothing about
    whether the registered `pre_tool_call` seam still decides anything: a
    bundle whose rule matcher returns `None` for every call registers exactly
    as well as one that enforces, and every check that existed before this one
    passed it.

    Two probes, because one cannot tell enforcement from a stuck answer. The
    first names a tool the probe rule scopes and carries the rule's marker, so
    a working matcher must return the host's block directive. The second names
    a tool the same rule does not scope, so a working matcher must let it
    proceed. A bundle that blocks both is refusing indiscriminately, and a
    bundle that blocks neither is not enforcing; both are `no_decision`, and
    both still pass the import and register tiers, which is the distinction
    the issue asks the report to keep.

    Harmless by construction, not by choice of a realistic command. The tool
    names exist nowhere -- not in `PROVIDED_TOOLS`, not in any host -- and the
    arguments carry one marker string and no path, command, or content. The
    rules file is written into a temporary directory that is this probe's
    entire OMH home, so the operator's own rules are neither read nor claimed
    (a `repeat="always"` rule never touches the once-per-session ledger) and
    nothing outside the temporary directory is written.
    """
    module_name = "_omh_plugin_enforcement_smoke"
    _clear_smoke_modules(module_name)
    try:
        package = _load_installed_module(
            module_name,
            plugin_dir / "__init__.py",
            search_locations=[str(plugin_dir)],
        )
        if package is None:
            return _enforcement_unknown("could not load plugin spec for the enforcement probe")
        # The rules module by FILE, through the same loader the register tier
        # uses. INVARIANT 1 of
        # `tests/test_handoff_safety_contract_enforcement.py` allowlists both
        # spellings, and this file is on its path-load allowlist for the reason
        # recorded there: the path is COMPUTED, never caller-supplied. It is
        # `paths.hermes_plugin_dir` -- the managed directory OMH writes itself
        # -- plus a literal filename. Not because a path is inherently safer
        # than a name: a path load executes the file it names, and that file is
        # outside `src/`, so no static gate sees what it imports either. Note
        # also what this does not claim. The tiers run against the installed
        # bundle even when the manifest was already recorded invalid, which is
        # the point of a readiness probe, so these bytes are not
        # manifest-verified first.
        rules_module = _load_installed_module(
            f"{module_name}.toolcall_rules", plugin_dir / "toolcall_rules.py"
        )
        if rules_module is None:
            return _enforcement_unknown(
                "the installed bundle has no loadable toolcall_rules module, so no decision "
                "could be requested"
            )
        directive_for = getattr(rules_module, "toolcall_rule_directive", None)
        if not callable(directive_for):
            return _enforcement_unknown(
                "installed bundle exposes no toolcall_rule_directive(); it predates the "
                "enforcement seam, so no decision could be requested"
            )
        with tempfile.TemporaryDirectory(prefix="omh-enforcement-smoke-") as probe_home:
            rules_path = Path(probe_home) / "rules" / ENFORCEMENT_PROBE_RULES_FILE
            rules_path.parent.mkdir(parents=True, exist_ok=True)
            rules_path.write_text(
                json.dumps(_enforcement_probe_rules(rules_module), ensure_ascii=False),
                encoding="utf-8",
            )
            scoped = directive_for(
                tool_name=ENFORCEMENT_PROBE_SCOPED_TOOL,
                tool_input={"probe": ENFORCEMENT_PROBE_MARKER},
                session_id=ENFORCEMENT_PROBE_SESSION,
                omh_home=probe_home,
            )
            unscoped = directive_for(
                tool_name=ENFORCEMENT_PROBE_UNSCOPED_TOOL,
                tool_input={"probe": ENFORCEMENT_PROBE_MARKER},
                session_id=ENFORCEMENT_PROBE_SESSION,
                omh_home=probe_home,
            )
    except Exception as exc:  # noqa: BLE001 - classified below, never a pass
        # Classified and surfaced: the tier reports `unknown` with the error,
        # which is distinct from both `enforced` and `no_decision`. A probe
        # that cannot run has not observed a decision, and reporting it as a
        # pass is the exact failure this tier exists to prevent.
        return _enforcement_unknown(f"plugin enforcement probe failed: {exc}")
    finally:
        _clear_smoke_modules(module_name)
    scoped_action = str(scoped.get("action", "")) if isinstance(scoped, Mapping) else ""
    unscoped_action = str(unscoped.get("action", "")) if isinstance(unscoped, Mapping) else ""
    decision = f"scoped={scoped_action or 'proceed'} unscoped={unscoped_action or 'proceed'}"
    if scoped_action == "block" and not unscoped_action:
        return {
            "enforcement_smoke": True,
            "enforcement_status": "enforced",
            "enforcement_decision": decision,
            "enforcement_detail": (
                "the installed bundle returned the host block directive for the scoped probe "
                "and let the unscoped probe proceed"
            ),
        }
    return {
        "enforcement_smoke": False,
        "enforcement_status": "no_decision",
        "enforcement_decision": decision,
        "enforcement_detail": (
            "the installed bundle imports and registers, but its rule matcher did not decide: "
            f"expected scoped=block unscoped=proceed, observed {decision}"
        ),
    }


def _load_installed_module(
    module_name: str,
    path: Path,
    *,
    search_locations: list[str] | None = None,
) -> Any | None:
    """Execute one named file of the installed bundle as `module_name`, or None.

    The primitive `_register_smoke` already uses, factored out so the
    enforcement probe reaches the rules module the same way and by the same
    rule: a file path, never a module name. `sys.modules` is populated before
    execution so the loaded file's own relative imports (`from . import
    runtime_paths`) resolve against the package already registered under
    `module_name`'s parent.
    """
    spec = importlib.util.spec_from_file_location(
        module_name, path, submodule_search_locations=search_locations
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _enforcement_probe_rules(rules_module: Any) -> dict[str, Any]:
    """The one-rule probe document, versioned by the INSTALLED bundle's own constant.

    Read off the loaded module rather than this package's copy: a document
    stamped with the repo's schema version would be refused whole by an
    installed bundle at a different one, and the tier would report a matcher
    fault where the real finding is a stale bundle the freshness tier already
    names.
    """
    return {
        "schema_version": getattr(rules_module, "TOOLCALL_RULES_SCHEMA_VERSION", ""),
        "rules": [
            {
                "name": "omh-doctor-enforcement-probe",
                "pattern": ENFORCEMENT_PROBE_MARKER,
                "message": "OMH doctor enforcement probe; nothing was executed.",
                "tools": [ENFORCEMENT_PROBE_SCOPED_TOOL],
                # Always, never once: a once-rule claims a fire against a
                # session id, and this probe must leave no claim behind.
                "repeat": "always",
            }
        ],
    }


def _enforcement_unknown(detail: str) -> dict[str, Any]:
    return {
        "enforcement_smoke": False,
        "enforcement_status": "unknown",
        "enforcement_decision": "",
        "enforcement_detail": detail,
    }


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
