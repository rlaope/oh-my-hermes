from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from wrapper_shim_common import run_shim


if __name__ == "__main__":
    raise SystemExit(run_shim("telegram"))
