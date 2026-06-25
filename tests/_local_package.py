from __future__ import annotations

from importlib.machinery import ModuleSpec
import sys
from types import ModuleType
from pathlib import Path


def load_local_package() -> None:
    if "omh" in sys.modules:
        return

    package_dir = Path(__file__).resolve().parents[1] / "src" / "omh"
    module = ModuleType("omh")
    module.__file__ = str(package_dir)
    module.__package__ = "omh"
    module.__path__ = [str(package_dir)]  # type: ignore[attr-defined]
    module.__spec__ = ModuleSpec("omh", loader=None, is_package=True)
    sys.modules["omh"] = module

    from omh.version import __version__

    module.__version__ = __version__
