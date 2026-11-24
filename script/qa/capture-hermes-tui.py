from __future__ import annotations

import fcntl
import os
from pathlib import Path
import pty
import select
import signal
import struct
import sys
import termios
import time


def main() -> int:
    home = Path(sys.argv[1])
    output = Path(sys.argv[2])
    columns = int(sys.argv[3])
    rows = int(sys.argv[4])
    settle_seconds = float(sys.argv[5])
    omh_home = Path(sys.argv[6]) if len(sys.argv) > 6 else None
    home.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)

    pid, fd = pty.fork()
    if pid == 0:
        env = os.environ.copy()
        env.update(
            {
                "HERMES_HOME": str(home),
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "COLUMNS": str(columns),
                "LINES": str(rows),
            }
        )
        if omh_home is not None:
            env["OMH_HOME"] = str(omh_home)
        os.execve(
            str(Path.home() / ".local" / "bin" / "hermes"),
            ["hermes", "--tui", "--ignore-user-config", "--ignore-rules", "--safe-mode"],
            env,
        )

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
    raw = bytearray()
    deadline = time.monotonic() + settle_seconds
    while time.monotonic() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.05)
        if readable:
            chunk = os.read(fd, 65_536)
            if not chunk:
                break
            raw.extend(chunk)
    captured = bytes(raw)
    os.write(fd, b"\x03")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    output.write_bytes(captured)
    print(f"captured={len(captured)} columns={columns} rows={rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
