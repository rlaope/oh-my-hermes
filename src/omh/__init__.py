from __future__ import annotations

from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parents[1]

# Source checkouts keep the readable implementation folders directly under
# src/ while built wheels install them under the omh package namespace.
if (_SOURCE_ROOT / "routing").is_dir():
    __path__.append(str(_SOURCE_ROOT))

from .version import __version__
