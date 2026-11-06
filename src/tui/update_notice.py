"""The OMH TUI's update notice: whether npm has published a newer oh-my-hermes than the one running.

One of the two network clients in `src/` (`tests/test_handoff_safety_contract_enforcement.py`
INVARIANT 2 pins it, and that only `tui/app.py` and, for the explicit stable
`omh update`, `commands/setup.py` import it). Everything here
keeps one small read narrow:

* One URL, fixed in `LATEST_URL`: npm's `latest` dist-tag of the package. It
  never comes from an argument, a setting or an environment variable.
* HTTPS only, default certificate verification, a `TIMEOUT_SECONDS` socket
  timeout, and a redirect followed only to an https URL on `REGISTRY_HOST`.
  The reply is read to `MAX_RESPONSE_BYTES` at most, and only its `version`
  is kept: no key, no identifier, nothing about the person is sent.
* At most once a day per OMH home: the answer and when it was asked are kept
  in `<omh_home>/tui/update-check.json`, and a launch inside
  `INTERVAL_SECONDS` of the last ask reuses it. A failed ask counts as an ask.
* Off the screen's thread: `UpdateCheck.start` asks on a daemon thread, and
  the loop takes the answer (`take`) when the thread wakes it. Any failure
  (offline, a timeout, a bad reply, a version that is not plain numbers)
  keeps the answer the cache already had and is recorded there as `problem`;
  nothing is said on screen.
* Off with `OMH_TUI_UPDATE_CHECK=0`, `update_check` off in the OMH TUI's
  settings (`omh theme update-check off`), or the launch check `omh update-check`
  stored as `off` (`update_notice_switch.held_off_by`): then nothing is read,
  written or sent. Without an OMH home there is nowhere to keep the day's
  answer, so nothing is asked either.

Proxy variables such as `HTTPS_PROXY` are honored by urllib, so a configured
proxy sees the registry's host.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

from ..system.local_store import atomic_write_json, read_json_object_result

LATEST_URL = "https://registry.npmjs.org/oh-my-hermes/latest"
REGISTRY_HOST = "registry.npmjs.org"
TIMEOUT_SECONDS = 3.0
INTERVAL_SECONDS = 24 * 60 * 60
MAX_RESPONSE_BYTES = 1024 * 1024
CACHE_SCHEMA = "omh_tui_update_check/v1"
NOT_A_RELEASE = "not_a_release_version"  # the `problem` of an answer whose version is not plain numbers
# A release version is dotted numbers and nothing else: a pre-release or build tag (`4.1.0-rc.1`, `4.0.5.dev1`) is no
# release to announce, and is ignored rather than ordered.
_RELEASE_VERSION = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,9}){0,5}")


def cache_path(omh_home: Path) -> Path:
    """Where the day's answer is kept: under the OMH home, beside the TUI's other choices."""
    return Path(omh_home) / "tui" / "update-check.json"


def release_version(text: object) -> tuple[int, ...] | None:
    """`4.0.5` as (4, 0, 5); None for anything but dotted numbers, a pre-release or build tag included."""
    if not isinstance(text, str) or not _RELEASE_VERSION.fullmatch(text):
        return None
    return tuple(int(part) for part in text.split("."))


def is_newer(latest: object, current: object) -> bool:
    """Whether `latest` is a later release than `current`, missing parts read as 0 (`4.1` is `4.1.0`); False when
    either is not a release version, so a pre-release on either side never announces anything."""
    ahead, here = release_version(latest), release_version(current)
    if ahead is None or here is None:
        return False
    width = max(len(ahead), len(here))
    return ahead + (0,) * (width - len(ahead)) > here + (0,) * (width - len(here))


def read_cache(omh_home: Path) -> tuple[float, str] | None:
    """(when it was last asked, on the wall clock; the version npm named then, "" when none was read), or None when
    nothing this module wrote is there."""
    record, _error = read_json_object_result(cache_path(omh_home))
    if record is None or record.get("schema_version") != CACHE_SCHEMA:
        return None
    checked, latest = record.get("checked_at"), record.get("latest")
    if isinstance(checked, bool) or not isinstance(checked, int | float):
        return None
    return float(checked), latest if isinstance(latest, str) else ""


def write_cache(omh_home: Path, checked_at: float, latest: str, problem: str = "") -> None:
    record: dict[str, object] = {"schema_version": CACHE_SCHEMA, "checked_at": checked_at, "latest": latest}
    if problem:
        record["problem"] = problem
    atomic_write_json(cache_path(omh_home), record)


def fetch_latest(timeout: float = TIMEOUT_SECONDS) -> str:
    """The `version` of npm's `latest` oh-my-hermes; raises on any failure.

    urllib is imported here, on the checking thread, so the TUI's start does
    not pay for it.
    """
    from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

    class SameHostRedirects(HTTPRedirectHandler):
        """Follow a redirect only to an https URL on the registry's own host; any other is refused."""

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            target = urlsplit(newurl)
            if target.scheme != "https" or target.hostname != REGISTRY_HOST:
                return None
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    request = Request(LATEST_URL, headers={"Accept": "application/json", "User-Agent": "oh-my-hermes-tui"})
    opener = build_opener(SameHostRedirects(), HTTPSHandler())
    with opener.open(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("the registry's reply is over the size bound")
    document = json.loads(body.decode("utf-8"))
    version = document.get("version") if isinstance(document, dict) else None
    if not isinstance(version, str):
        raise ValueError("the registry's reply names no version")
    return version


class UpdateCheck:
    """The newest published release known for one OMH home (`latest`, "" while none is newer than `current`)."""

    def __init__(
        self,
        omh_home: Path,
        current: str,
        *,
        fetch: Callable[[], str] = fetch_latest,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.omh_home = Path(omh_home)
        self.current = current
        self.fetch = fetch
        self.now = now
        self.latest = ""
        self.thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._answer: str | None = None  # what the thread read, until `take` takes it

    def start(self, wake: Callable[[], None] | None = None) -> bool:
        """Show the cached answer at once, and ask npm on a thread when the last ask is a day old (or none is kept, or
        it is dated in the future); whether it asked. `wake` is called, on the thread, once the answer is kept."""
        cached = read_cache(self.omh_home)
        known = cached[1] if cached is not None else ""
        self.latest = known if is_newer(known, self.current) else ""
        if cached is not None and 0 <= self.now() - cached[0] < INTERVAL_SECONDS:
            return False
        self.thread = threading.Thread(target=self._ask, args=(known, wake), name="omh-update-check", daemon=True)
        self.thread.start()
        return True

    def _ask(self, known: str, wake: Callable[[], None] | None) -> None:
        asked_at = self.now()
        try:
            answer = self.fetch()
        except Exception as error:  # recorded as `problem`; a raise would print a traceback over the TUI's screen
            answer, problem = known, type(error).__name__
        else:
            problem = "" if release_version(answer) is not None else NOT_A_RELEASE
            answer = answer if not problem else known
        try:
            write_cache(self.omh_home, asked_at, answer, problem)
        except OSError:
            pass  # the next launch asks again: there is no day's answer to reuse
        with self._lock:
            self._answer = answer
        if wake is not None:
            wake()

    def take(self) -> bool:
        """Take the thread's answer into `latest`; whether there was one since the last take."""
        with self._lock:
            answer, self._answer = self._answer, None
        if answer is None:
            return False
        self.latest = answer if is_newer(answer, self.current) else ""
        return True
