from __future__ import annotations

from pathlib import Path

_SOURCE_PACKAGE = Path(__file__).resolve().parents[1] / "src"

# Source checkouts use src/ as the implementation package while built wheels
# expose it as omh. Point local omh imports at the same implementation tree.
__path__ = [str(_SOURCE_PACKAGE)]

from .version import __version__
