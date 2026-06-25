from __future__ import annotations

import sys

from .surfaces import menubar_app as _implementation

sys.modules[__name__] = _implementation
