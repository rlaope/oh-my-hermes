from __future__ import annotations

import ast
import os
import tomllib
from pathlib import Path
from typing import Any

from .schema import CLAIM_BOUNDARY, CODEGRAPH_SCHEMA_VERSION, resolve_repo_root, utc_now


EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
}
EXCLUDED_RELATIVE_DIRS = {(".omh", "codegraph")}


def build_codegraph(repo: str | Path, *, generated_at: str | None = None) -> dict[str, Any]:
    repo_root = resolve_repo_root(repo)
    warnings: list[str] = []
    python_paths = list(_iter_python_files(repo_root, warnings))
    scripts, package_dirs = _read_pyproject_scripts(repo_root, warnings)
    module_to_paths = _module_to_paths(repo_root, python_paths, package_dirs)
    package_script_tags = _package_script_tags_by_path(repo_root, module_to_paths, scripts, package_dirs)

    files: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str, str]] = set()
    parse_error_count = 0
    parsed_file_count = 0

    for path in python_paths:
        rel_path = _relative_path(repo_root, path)
        module_names = _module_names_for_path(repo_root, path, package_dirs)
        primary_module = module_names[0] if module_names else rel_path.removesuffix(".py").replace("/", ".")
        record: dict[str, Any] = {
            "path": rel_path,
            "kind": "python",
            "imports": [],
            "defines": [],
            "entrypoint_tags": _entrypoint_tags(rel_path, package_script_tags.get(rel_path, [])),
        }
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel_path)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            parse_error_count += 1
            message = f"{type(exc).__name__}: {exc}"
            record["parse_error"] = message
            warnings.append(f"parse_error: {rel_path}: {message}")
            files.append(record)
            continue

        parsed_file_count += 1
        imports = _extract_imports(tree, rel_path=rel_path, current_module=primary_module)
        file_symbols = _extract_symbols(tree, rel_path=rel_path, module_name=primary_module)
        record["imports"] = imports
        record["defines"] = [symbol["qualified_name"] for symbol in file_symbols]
        files.append(record)
        symbols.extend(file_symbols)

        for qualified_name in record["defines"]:
            edge_keys.add((rel_path, qualified_name, "defines"))
        for item in imports:
            module = str(item["module"])
            name = item.get("name")
            edge_keys.add((rel_path, _import_edge_target(item), "imports"))
            for internal_path in _resolve_internal_import(module, str(name) if name else None, module_to_paths):
                edge_keys.add((rel_path, internal_path, "imports_internal"))

    edges = [
        {"from": source, "to": target, "kind": kind}
        for source, target, kind in sorted(edge_keys, key=lambda item: (item[0], item[2], item[1]))
    ]
    files = sorted(files, key=lambda item: item["path"])
    symbols = sorted(symbols, key=lambda item: (item["path"], item["line"], item["qualified_name"]))
    warnings = sorted(dict.fromkeys(warnings))
    stats = {
        "file_count": len(files),
        "python_file_count": len(files),
        "parsed_file_count": parsed_file_count,
        "parse_error_count": parse_error_count,
        "symbol_count": len(symbols),
        "edge_count": len(edges),
        "internal_import_edge_count": sum(1 for edge in edges if edge["kind"] == "imports_internal"),
        "entrypoint_file_count": sum(1 for record in files if record["entrypoint_tags"]),
        "warning_count": len(warnings),
    }
    return {
        "schema_version": CODEGRAPH_SCHEMA_VERSION,
        "repo_root": str(repo_root),
        "generated_at": generated_at or utc_now(),
        "files": files,
        "symbols": symbols,
        "edges": edges,
        "stats": stats,
        "warnings": warnings,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def _iter_python_files(repo_root: Path, warnings: list[str]) -> list[Path]:
    paths: list[Path] = []

    def on_walk_error(exc: OSError) -> None:
        location = exc.filename or str(repo_root)
        warnings.append(f"walk_error: {location}: {exc}")

    for current_root, dir_names, file_names in os.walk(
        repo_root,
        topdown=True,
        onerror=on_walk_error,
        followlinks=False,
    ):
        current = Path(current_root)
        try:
            rel_parts = current.relative_to(repo_root).parts
        except ValueError:
            continue
        dir_names[:] = [
            name
            for name in sorted(dir_names)
            if not _is_excluded_dir(rel_parts + (name,))
        ]
        for file_name in sorted(file_names):
            if not file_name.endswith(".py"):
                continue
            path = current / file_name
            if _is_excluded_dir(path.parent.relative_to(repo_root).parts):
                continue
            if path.is_symlink():
                warnings.append(f"skipped_symlink: {_relative_path(repo_root, path)}")
                continue
            paths.append(path)
    return sorted(paths, key=lambda path: _relative_path(repo_root, path))


def _is_excluded_dir(parts: tuple[str, ...]) -> bool:
    if not parts:
        return False
    if any(part in EXCLUDED_DIR_NAMES for part in parts):
        return True
    return any(parts[: len(excluded)] == excluded for excluded in EXCLUDED_RELATIVE_DIRS)


def _relative_path(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _module_to_paths(repo_root: Path, paths: list[Path], package_dirs: dict[str, str]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for path in paths:
        rel_path = _relative_path(repo_root, path)
        for module_name in _module_names_for_path(repo_root, path, package_dirs):
            mapping.setdefault(module_name, []).append(rel_path)
    return {module: sorted(dict.fromkeys(items)) for module, items in sorted(mapping.items())}


def _module_names_for_path(repo_root: Path, path: Path, package_dirs: dict[str, str]) -> list[str]:
    rel = path.relative_to(repo_root)
    parts = list(rel.with_suffix("").parts)
    if not parts:
        return []
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return []
    names = _package_dir_module_names(rel, package_dirs)
    names.append(".".join(parts))
    if parts[0] == "src" and len(parts) > 1:
        names.append(".".join(parts[1:]))
    return list(dict.fromkeys(name for name in names if name))


def _package_dir_module_names(rel: Path, package_dirs: dict[str, str]) -> list[str]:
    rel_parts = list(rel.with_suffix("").parts)
    if rel_parts and rel_parts[-1] == "__init__":
        rel_parts = rel_parts[:-1]
    names: list[str] = []
    for package_name, package_path in sorted(package_dirs.items()):
        base_parts = tuple(part for part in Path(package_path).parts if part not in (".", ""))
        if base_parts:
            if tuple(rel_parts[: len(base_parts)]) != base_parts:
                continue
            suffix_parts = rel_parts[len(base_parts) :]
        else:
            suffix_parts = rel_parts
        package_parts = [part for part in package_name.split(".") if part]
        module_parts = [*package_parts, *suffix_parts]
        if module_parts:
            names.append(".".join(module_parts))
    return names


def _extract_imports(tree: ast.AST, *, rel_path: str, current_module: str) -> list[dict[str, Any]]:
    imports: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                item: dict[str, Any] = {
                    "kind": "import",
                    "module": alias.name,
                    "name": None,
                    "line": node.lineno,
                }
                if alias.asname:
                    item["alias"] = alias.asname
                imports.append(item)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_from_import_module(node, rel_path=rel_path, current_module=current_module)
            for alias in node.names:
                item = {
                    "kind": "from_import",
                    "module": module,
                    "name": alias.name,
                    "line": node.lineno,
                }
                if node.level:
                    item["level"] = node.level
                if alias.asname:
                    item["alias"] = alias.asname
                imports.append(item)
    return sorted(
        imports,
        key=lambda item: (int(item["line"]), str(item["kind"]), str(item["module"]), str(item["name"])),
    )


def _resolve_from_import_module(node: ast.ImportFrom, *, rel_path: str, current_module: str) -> str:
    if node.level == 0:
        return node.module or ""
    package = (
        current_module
        if rel_path.endswith("/__init__.py") or rel_path == "__init__.py"
        else current_module.rsplit(".", 1)[0]
    )
    package_parts = [part for part in package.split(".") if part]
    drop = node.level - 1
    if drop:
        package_parts = package_parts[: max(0, len(package_parts) - drop)]
    if node.module:
        package_parts.extend(part for part in node.module.split(".") if part)
    return ".".join(package_parts)


def _import_edge_target(item: dict[str, Any]) -> str:
    if item["kind"] == "from_import" and item.get("name"):
        return f"{item['module']}:{item['name']}"
    return str(item["module"])


def _resolve_internal_import(module: str, name: str | None, module_to_paths: dict[str, list[str]]) -> list[str]:
    candidates = [module]
    if name and name != "*":
        candidates.append(f"{module}.{name}" if module else name)
    resolved: list[str] = []
    for candidate in candidates:
        resolved.extend(module_to_paths.get(candidate, []))
    return sorted(dict.fromkeys(resolved))


class _SymbolVisitor(ast.NodeVisitor):
    def __init__(self, *, rel_path: str, module_name: str) -> None:
        self.rel_path = rel_path
        self.module_name = module_name
        self.stack: list[str] = []
        self.symbols: list[dict[str, Any]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._add_symbol(node.name, "class", node.lineno)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._add_symbol(node.name, "function", node.lineno)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._add_symbol(node.name, "async_function", node.lineno)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def _add_symbol(self, name: str, kind: str, line: int) -> None:
        qualified_parts = [self.module_name, *self.stack, name]
        self.symbols.append(
            {
                "name": name,
                "qualified_name": ".".join(part for part in qualified_parts if part),
                "kind": kind,
                "path": self.rel_path,
                "line": line,
            }
        )


def _extract_symbols(tree: ast.AST, *, rel_path: str, module_name: str) -> list[dict[str, Any]]:
    visitor = _SymbolVisitor(rel_path=rel_path, module_name=module_name)
    visitor.visit(tree)
    return visitor.symbols


def _entrypoint_tags(rel_path: str, package_script_tags: list[str]) -> list[str]:
    tags: list[str] = []
    path = Path(rel_path)
    parts = path.parts
    if rel_path.startswith("tests/") or path.name.startswith("test_"):
        tags.append("test")
    if len(parts) >= 3 and parts[0] == "src" and parts[1] == "commands" and path.name != "__init__.py":
        tags.append("cli_command")
    if rel_path in {"src/cli/__init__.py", "src/cli/__main__.py"}:
        tags.append("cli_entrypoint")
    if (
        len(parts) >= 5
        and parts[0] == "src"
        and parts[1] == "plugin_bundle"
        and parts[2] == "omh"
        and parts[3] == "tools"
        and path.name != "__init__.py"
    ):
        tags.append("plugin_tool")
    tags.extend(package_script_tags)
    return sorted(dict.fromkeys(tags))


def _package_script_tags_by_path(
    repo_root: Path,
    module_to_paths: dict[str, list[str]],
    scripts: dict[str, str],
    package_dirs: dict[str, str],
) -> dict[str, list[str]]:
    tags_by_path: dict[str, list[str]] = {}
    for script_name, target in sorted(scripts.items()):
        module = target.split(":", 1)[0].strip()
        if not module:
            continue
        rel_paths = list(module_to_paths.get(module, []))
        rel_paths.extend(_resolve_module_paths_from_package_dirs(module, package_dirs))
        for rel_path in sorted(dict.fromkeys(rel_paths)):
            if (repo_root / rel_path).exists():
                tags_by_path.setdefault(rel_path, []).append(f"package_script:{script_name}")
    return {path: sorted(tags) for path, tags in tags_by_path.items()}


def _read_pyproject_scripts(repo_root: Path, warnings: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    path = repo_root / "pyproject.toml"
    if not path.exists():
        return {}, {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        warnings.append(f"pyproject_read_error: {type(exc).__name__}: {exc}")
        return {}, {}
    project = data.get("project", {})
    scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
    tool = data.get("tool", {})
    setuptools = tool.get("setuptools", {}) if isinstance(tool, dict) else {}
    package_dir = setuptools.get("package-dir", {}) if isinstance(setuptools, dict) else {}
    clean_scripts = {str(name): str(target) for name, target in scripts.items()} if isinstance(scripts, dict) else {}
    clean_package_dir = (
        {str(name): str(target) for name, target in package_dir.items()} if isinstance(package_dir, dict) else {}
    )
    return clean_scripts, clean_package_dir


def _resolve_module_paths_from_package_dirs(module: str, package_dirs: dict[str, str]) -> list[str]:
    paths: list[str] = []
    for package_name, package_path in sorted(package_dirs.items(), key=lambda item: len(item[0]), reverse=True):
        if not package_name:
            continue
        if module != package_name and not module.startswith(package_name + "."):
            continue
        suffix = module[len(package_name) :].lstrip(".")
        base = Path(package_path)
        rel_base = base / Path(*suffix.split(".")) if suffix else base
        paths.append(rel_base.with_suffix(".py").as_posix())
        paths.append((rel_base / "__init__.py").as_posix())
    return paths
