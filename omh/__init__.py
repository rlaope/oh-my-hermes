from __future__ import annotations

from pathlib import Path

_SOURCE_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "omh"

# Source checkouts use src/omh/ as the implementation package while built wheels
# expose it as omh. Point local omh imports at the same implementation tree.
__path__ = [str(_SOURCE_PACKAGE)]

_SOURCE_INIT = _SOURCE_PACKAGE / "__init__.py"
exec(compile(_SOURCE_INIT.read_text(), str(_SOURCE_INIT), "exec"), globals())
