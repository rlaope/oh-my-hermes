from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_local_package() -> None:
    if "omh" in sys.modules:
        return

    package_dir = Path(__file__).resolve().parents[1] / "src" / "omh"
    spec = importlib.util.spec_from_file_location(
        "omh",
        package_dir / "__init__.py",
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load local package")

    module = importlib.util.module_from_spec(spec)
    sys.modules["omh"] = module
    spec.loader.exec_module(module)
