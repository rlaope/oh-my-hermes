"""Shared platform-capability probes and skip decorators (issue #781).

Windows lacks the POSIX primitives several OMH surfaces are built on
(O_NOFOLLOW / O_DIRECTORY dirfd-anchored opens, mode-bit enforcement, mkfifo,
killpg). Product code fails closed on such platforms by design; these
decorators keep the corresponding tests scoped to hosts where the exercised
contract can hold, following the guard conventions established by #771 and
#778.

Mutual exclusion is deliberately *not* on that list. `fcntl` is POSIX-only,
but the capability built on it is not: `local_store.file_lock` falls back to
`msvcrt.locking` and reports `enforced: True` either way, so a concurrency
contract holds on both platforms. Pick the gate that names the capability
under test, not the primitive the POSIX half happens to use --
`requires_enforced_file_lock` for mutual exclusion, `requires_fcntl_locks`
only where the test asserts something about `fcntl` itself. Gating mutual
exclusion on `fcntl` left Windows with no concurrent coverage of the lock
path at all, and that is where a silent data-loss defect lived until #1467.
"""

from __future__ import annotations

import functools
import os
import subprocess
import unittest

try:  # probe only; mirrors the product's degraded-import pattern
    import fcntl as _fcntl  # noqa: F401
except ImportError:
    HAS_FCNTL = False
else:
    HAS_FCNTL = True

try:  # the Windows half of the same capability
    import msvcrt as _msvcrt  # noqa: F401
except ImportError:
    HAS_MSVCRT = False
else:
    HAS_MSVCRT = True

# `file_lock` takes a real OS lock through fcntl on POSIX and msvcrt on
# Windows, and reports `enforced: True` for either. Mutual exclusion is
# therefore a cross-platform property, and gating a concurrency test on
# `HAS_FCNTL` skips it on the one platform where the product has no second
# backend to fall back on. That gate hid a Windows-only data-loss defect in
# `ensure_file` (PR #1467): the only test reaching the lock path concurrently
# on Windows was one nobody had gated, and it was the one that failed.
HAS_ENFORCED_FILE_LOCK = HAS_FCNTL or HAS_MSVCRT

HAS_SECURE_DIR_IO = bool(
    getattr(os, "O_NOFOLLOW", 0)
    and getattr(os, "O_DIRECTORY", 0)
    and os.open in os.supports_dir_fd
    and hasattr(os, "fchmod")
)

requires_posix = unittest.skipUnless(
    os.name == "posix",
    "exercises POSIX-only process or filesystem semantics",
)
requires_windows = unittest.skipUnless(
    os.name == "nt",
    "exercises Windows-only process or filesystem semantics",
)
requires_posix_permissions = unittest.skipUnless(
    os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() != 0,
    "POSIX permission bits do not restrict root and do not exist off POSIX",
)


@functools.cache
def _imports_hermes_cli(python: str) -> bool:
    """Whether this interpreter, on its own import path, can import Hermes.

    Asked once per interpreter per process. `PYTHONPATH` is left out because
    the loader observation runs its child without the runner's, so a tree
    that is only importable through it is not a host those tests can use.
    A probe that does not answer in time has not shown Hermes absent: the
    test then runs and its own bounded call reports what happened.
    """
    env = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    try:
        return subprocess.run([python, "-c", "import hermes_cli"], capture_output=True, env=env, timeout=30).returncode == 0
    except subprocess.TimeoutExpired:
        return True
    except OSError:
        return False


def requires_hermes_host(test):
    """Skip a test method unless the interpreter it would run Hermes on has Hermes.

    The interpreter is the product's own choice (`_find_hermes_python`: a
    `HERMES_PYTHON` override first, then discovery), read when the test runs
    rather than when this module is imported. A file at that path was the
    whole question before, and an override can name a file that cannot
    import `hermes_cli` (Hermes' TUI launcher exports its own interpreter,
    which needs the launcher's import path too): the tests then ran and
    failed on the runner's environment instead of skipping (#2794).

    This answers for the interpreter only. With no override the loader
    observation reaches Hermes through the `hermes` launcher on PATH, and
    a launcher it cannot trace to a code tree still fails these tests.
    """

    @functools.wraps(test)
    def gated(*args, **kwargs):
        from _local_package import load_local_package

        load_local_package()
        from omh.install.plugin_loader_observation import _find_hermes_python

        python = _find_hermes_python()
        if python is None:
            raise unittest.SkipTest("real plugin admission requires an installed Hermes host")
        if not _imports_hermes_cli(str(python)):
            raise unittest.SkipTest(f"real plugin admission requires a Hermes host; {python} cannot import hermes_cli")
        return test(*args, **kwargs)

    return gated


requires_symlinks = unittest.skipUnless(
    os.name == "posix",
    "symlink creation and resolution differ off POSIX",
)
requires_fcntl_locks = unittest.skipUnless(
    HAS_FCNTL,
    "fcntl advisory locking is POSIX-only",
)
requires_enforced_file_lock = unittest.skipUnless(
    HAS_ENFORCED_FILE_LOCK,
    "mutual exclusion requires an enforced OS file lock (fcntl or msvcrt)",
)
requires_secure_dir_io = unittest.skipUnless(
    HAS_SECURE_DIR_IO,
    "secure dirfd-anchored file access requires POSIX O_NOFOLLOW/O_DIRECTORY/dir_fd",
)
requires_domain_intelligence_store = unittest.skipUnless(
    HAS_SECURE_DIR_IO and HAS_FCNTL,
    "domain-intelligence safe stores require POSIX dirfd/O_NOFOLLOW/fcntl primitives",
)
requires_posix_select = unittest.skipUnless(
    os.name == "posix",
    "select() on Windows accepts only sockets, not pipe/tty descriptors",
)
