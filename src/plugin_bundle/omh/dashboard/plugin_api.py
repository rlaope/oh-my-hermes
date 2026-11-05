"""Backend half of the OMH Hermes Desktop plugin.

Hermes' web server (``hermes_cli/web_server_dashboard.py``,
``_mount_plugin_api_routes``) imports this file by path as the module
``hermes_dashboard_plugin_omh`` and mounts ``router`` under
``/api/plugins/omh`` -- only while ``omh`` is in the host's ``plugins.enabled``
allow-list, the registration ``omh setup`` and ``omh update`` write. That
import is standalone -- no package, no ``omh`` on the path, and the same
process as the agent -- so the bundle's reader is loaded here by path as well,
under a private package name, and everything it needs resolves through the
bundle's own relative imports.

``GET /hud?session=<stored session id>`` answers with the ``omh_hud/v1``
payload the OMH TUI's panels draw, read for the gateway process's own
Hermes home. The ``profile`` query Hermes Desktop appends when it routes a
non-primary profile through a shared backend is not read: the route answers
for the launch profile, as the host's own bundled plugin backends do. A reader
failure is answered with HTTP 200 and an error record: in the pane a thrown
error is indistinguishable from a transport failure, so the reader's failure
is returned as a record the pane can label ``reader error`` instead.

``cols`` is the width of the pane's drawing in monospace cells, measured by
the pane. With it, an active delegation graph comes back drawn as well, under
``delegation_drawing``: the box drawing the OMH TUI prints into its
transcript (``src/tui/dag_block.py``), made by the bundle's own
``delegation_view``, so the pane shows the TUI's drawing rather than an
imitation of it. A run of up to ``SMALL_GRAPH_LANES`` lanes is drawn as boxes
with no Dependencies or Node details, as the TUI prints it; where boxes do not
fit the width, or the run is bigger, the renderer's tree is drawn instead.
Each segment keeps the role the renderer gave it (``node:running``), which is
what the pane colours by. A drawing that fails is answered as a record with
``error`` beside a HUD that still reads.

The pure functions, ``load_reader``, ``delegation_drawing`` and
``hud_payload``, are kept apart from the route so OMH's own tests can call
them without FastAPI, which is the host's dependency and not OMH's.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
import types
from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter
    from fastapi.concurrency import run_in_threadpool
except ImportError:  # OMH's own gates import this file on a host without FastAPI
    APIRouter = None
    run_in_threadpool = None

DESKTOP_HUD_SCHEMA_VERSION = "omh_desktop_hud/v1"
DRAWING_SCHEMA_VERSION = "omh_desktop_dag/v1"
# The lanes a run may have and still print as boxes: `dag_block.SMALL_GRAPH_LANES`, held equal by
# tests/test_desktop_half.py. A bigger run is drawn as the tree.
SMALL_GRAPH_LANES = 12
# The cells a drawing may take: the renderer's own floor, and a ceiling no pane reaches.
MIN_COLS = 8
MAX_COLS = 240
# The tree of a big run is kept to this many lines; the renderer folds the rest into its `+N more` line.
TREE_MAX_LINES = 48

# The name the bundle is loaded under here. It is neither ``omh`` (the package
# is not on this interpreter's path and must not be assumed) nor the name
# Hermes' plugin lane gives the same files, so the two loads never share a
# half-initialised module (#1623).
READER_PACKAGE = "omh_desktop_bundle"
BUNDLE_ROOT = Path(__file__).resolve().parent.parent

# Hermes serves the route from a thread pool, so two first polls -- two
# Desktop windows, or Desktop beside the browser dashboard -- can arrive
# together. The module is registered in ``sys.modules`` before it has
# executed, so without this lock the second caller takes the half-initialised
# module as its cache hit and, on its own failure, pops the package the first
# load is still executing.
_LOAD_LOCK = threading.Lock()


def _forget_reader_package() -> None:
    for name in list(sys.modules):
        if name == READER_PACKAGE or name.startswith(f"{READER_PACKAGE}."):
            sys.modules.pop(name, None)


def load_reader(bundle_root: str | Path = BUNDLE_ROOT) -> types.ModuleType:
    """The bundle's ``runtime_reader``, loaded by path under a private package.

    A bare parent module whose ``__path__`` is the bundle root is registered
    first, so ``from . import runtime_paths`` and the reader's other relative
    imports resolve to the sibling files of the same bundle. The loaded module
    is reused on later calls while it still comes from ``bundle_root``; a
    module that failed to exec is dropped rather than left half-initialised.
    One caller loads at a time; the others wait and take the finished module.
    """
    root = Path(bundle_root).resolve()
    reader_path = root / "runtime_reader.py"
    module_name = f"{READER_PACKAGE}.runtime_reader"
    with _LOAD_LOCK:
        cached = sys.modules.get(module_name)
        if cached is not None and str(getattr(cached, "__file__", "") or "") == str(reader_path):
            return cached
        _forget_reader_package()
        package = types.ModuleType(READER_PACKAGE)
        package.__path__ = [str(root)]
        sys.modules[READER_PACKAGE] = package
        spec = importlib.util.spec_from_file_location(module_name, reader_path)
        if spec is None or spec.loader is None:
            _forget_reader_package()
            raise ImportError(f"no loadable runtime_reader at {reader_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        loaded = False
        try:
            spec.loader.exec_module(module)
            loaded = True
        finally:
            if not loaded:
                _forget_reader_package()
        return module


def resolve_hermes_home() -> Path:
    """The Hermes home this request reads: the host's own answer when it is
    importable, else the process ``HERMES_HOME``, else Hermes' platform default."""
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        get_hermes_home = None
    if get_hermes_home is not None:
        return Path(get_hermes_home())
    configured = os.environ.get("HERMES_HOME", "").strip()
    if configured:
        return Path(configured)
    # Mirrors the bundle's ``runtime_paths.platform_default_hermes_home`` (and
    # Hermes' ``hermes_constants._platform_default_hermes_home``); this file is
    # imported standalone, so it cannot import that sibling directly. A parity test in
    # tests/test_desktop_half.py keeps the two copies equal.
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
        return base / ("hermes" + os.environ.get("HERMES_DATA_DIR_SUFFIX", ""))
    return Path.home() / (".hermes" + os.environ.get("HERMES_DATA_DIR_SUFFIX", ""))


def _lane_count(graph: dict[str, Any]) -> int:
    """The run's lanes, the ones the graph reader left out (`hidden_nodes`) included, as `dag_block` counts them."""
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    hidden = graph.get("hidden_nodes")
    lanes = sum(1 for node in nodes if isinstance(node, dict) and node.get("kind") != "root")
    return lanes + (hidden if isinstance(hidden, int) and not isinstance(hidden, bool) else 0)


def delegation_drawing(
    graph: dict[str, Any], cols: int, *, bundle_root: str | Path = BUNDLE_ROOT
) -> dict[str, Any]:
    """``graph`` drawn ``cols`` cells wide, as the TUI prints a dag-ulw run: boxes, else the tree.

    ``layout`` is what was drawn (``box``, ``tree``, or ``header`` when not
    even the tree fits), and every line is a list of ``{text, role}``
    segments, the renderer's own, so the pane paints a state where the
    drawing carries one and never re-lays a cell. A segment whose width in
    cells is not its length (a wide CJK character counts two) carries
    ``cells``, since a browser's fallback font draws such a character
    narrower than two monospace cells.
    """
    load_reader(bundle_root)  # registers the private package whose `__path__` is the bundle root
    from omh_desktop_bundle import delegation_view  # a sibling of the reader, through that package

    width = min(MAX_COLS, max(MIN_COLS, int(cols)))
    lines: Any = None
    layout = "box"
    if _lane_count(graph) <= SMALL_GRAPH_LANES:
        boxes = delegation_view._box_view(graph, width, delegation_view.UNICODE, sections=0)
        lines = boxes.lines if boxes is not None else None
    if lines is None:
        view = delegation_view.render_delegation_view(graph, width=width, max_lines=TREE_MAX_LINES, layout="tree")
        lines, layout = view.lines, view.layout
    return {
        "schema_version": DRAWING_SCHEMA_VERSION,
        "layout": layout,
        "cols": width,
        "lines": [[_segment(segment, delegation_view.cells) for segment in line] for line in lines],
    }


def _segment(segment: Any, cells: Any) -> dict[str, Any]:
    """One drawing segment; ``cells``, the renderer's own width for it, only where that is not one per character
    (a wide CJK character counts two), so the pane can hold the segment to the cells the layout gave it."""
    drawn = {"text": segment.text, "role": segment.role}
    width = cells(segment.text)
    if width != len(segment.text):
        drawn["cells"] = width
    return drawn


def hud_payload(
    hermes_home: str | Path,
    session: str = "",
    *,
    cols: int = 0,
    bundle_root: str | Path = BUNDLE_ROOT,
) -> dict[str, Any]:
    """The HUD the pane renders, or the error record it shows instead.

    ``omh_home`` is left to the reader, which resolves the store from the
    gateway's own Hermes home -- the same ``get_hermes_home()`` this route
    resolves, not the ``hermes_home`` handed in -- through that home's
    ``plugins.entries.omh.settings.omh_home``, as it does for every reader
    that names no store.
    ``session`` is the focused stored session id the app names, and naming
    one is what makes the plan todo session-scoped rather than a
    most-recent-TUI guess. ``cols``, when positive, adds the active delegation
    graph's drawing (`delegation_drawing`) under ``delegation_drawing``.
    """
    session_ref = str(session or "").strip()
    try:
        reader = load_reader(bundle_root)
        payload = reader.read_omh_hud(
            None,
            hermes_home,
            graph_preference="auto",
            tui_session_ref=session_ref,
            session_scoped=True,
            tui_identity_expected=bool(session_ref),
        )
    except Exception as exc:  # the failure becomes the record the pane shows
        return {
            "error": f"{type(exc).__name__}: {exc}",
            "schema_version": DESKTOP_HUD_SCHEMA_VERSION,
        }
    if not isinstance(payload, dict):
        return {
            "error": f"reader returned {type(payload).__name__}, not a HUD payload",
            "schema_version": DESKTOP_HUD_SCHEMA_VERSION,
        }
    graph = payload.get("delegation_graph")
    if isinstance(cols, int) and not isinstance(cols, bool) and cols > 0 and isinstance(graph, dict) \
            and graph.get("status") == "active":
        try:
            payload["delegation_drawing"] = delegation_drawing(graph, cols, bundle_root=bundle_root)
        except Exception as exc:  # the HUD still reads; the pane draws its lane rows instead
            payload["delegation_drawing"] = {
                "error": f"{type(exc).__name__}: {exc}",
                "schema_version": DRAWING_SCHEMA_VERSION,
            }
    return payload


if APIRouter is not None:
    router = APIRouter()

    @router.get("/hud")
    async def hud(session: str = "", cols: int = 0) -> dict[str, Any]:
        # The reader's file and sqlite reads run off the loop so a slow home
        # never stalls the stream. The home is the gateway's own; the
        # ``profile`` query is not read (see the module docstring).
        home = resolve_hermes_home()
        return await run_in_threadpool(lambda: hud_payload(home, session, cols=cols))
