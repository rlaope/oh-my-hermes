from __future__ import annotations

from importlib.machinery import ModuleSpec
import sys
from types import ModuleType
from pathlib import Path


def load_local_package() -> None:
    if "omh" in sys.modules:
        return

    source_root = Path(__file__).resolve().parents[1] / "src"
    package_dir = source_root / "omh"
    module = ModuleType("omh")
    module.__file__ = str(package_dir)
    module.__package__ = "omh"
    module.__path__ = [str(package_dir), str(source_root)]  # type: ignore[attr-defined]
    module.__spec__ = ModuleSpec("omh", loader=None, is_package=True)
    sys.modules["omh"] = module

    from omh.version import __version__

    module.__version__ = __version__
