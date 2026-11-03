#!/usr/bin/env python3
"""OMH TUI and plugin-hook performance bench.

Offline by construction: a byte-counting fake terminal, the tests' recording client and replay gateway, temp homes.
No live gateway, no network, nothing under the real ~/.hermes or ~/.omh.

  uv run python -P tools/benchmarks/tui_perf.py                  # table
  uv run python -P tools/benchmarks/tui_perf.py --json           # machine-readable
  uv run python -P tools/benchmarks/tui_perf.py --case frame --case stream
  uv run python -P tools/benchmarks/tui_perf.py --compare ../other-checkout [--rounds 3] [--tolerance 15]

`--compare TREE` measures TREE (base) and this checkout (head) with this same script, alternating rounds on the same
machine, and reports per-metric medians. The repo-root `omh/` shim selects a tree through PYTHONPATH, so the child
processes run with PYTHONPATH=<tree>:<tree>/tests. Time metrics (`*_ms`, `*_pct`, `*_per_s`) are judged against
`--tolerance` percent; byte and count metrics against 1 percent.
"""

from __future__ import annotations

import argparse
import atexit
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# The tree being measured: this checkout, or the base tree `--compare` hands a child process.
TREE = Path(os.environ.get("OMH_PERF_TREE") or ROOT)
SCHEMA = "omh_tui_perf/v1"
CASES = ("frame", "redraw", "stream", "keystroke", "idle", "plugin", "startup")

SIZES = {
    "full": {"turns": (10, 100, 1000, 5000), "redraw_repeat": 5, "stream_chars": 40000, "composer": (100, 1000, 5000, 20000),
             "idle_seconds": 3.0, "samples": 60, "plugin_turns": 40},
    "tiny": {"turns": (3, 12), "redraw_repeat": 2, "stream_chars": 1500, "composer": (50, 400),
             "idle_seconds": 0.3, "samples": 4, "plugin_turns": 4},
}

_ns: dict = {}


def _load() -> dict:
    """Point every home at a temp dir, then import the harness. Deferred so importing this module has no side effects."""
    if _ns:
        return _ns
    for path in (str(TREE / "tests"), str(TREE)):  # the tree's repo-root omh/ shim then selects that tree
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    from _test_temp_root import make_test_tempdir
    holder = make_test_tempdir(prefix="omh-tui-perf-")
    atexit.register(holder.cleanup)
    tmp = holder.name
    drive, tail = os.path.splitdrive(tmp)
    os.environ.update({"HOME": tmp, "USERPROFILE": tmp, "HOMEDRIVE": drive, "HOMEPATH": tail or tmp,
                       "HERMES_HOME": os.path.join(tmp, "hermes"), "OMH_HOME": os.path.join(tmp, "omh")})
    import omh
    from test_tui_app import ScriptedTerminal, FakePoller
    from test_tui_modes import RecordingClient, SID
    from omh.tui.app import App
    from omh.tui.gateway import Event
    _ns.update(tmp=tmp, omh_file=str(Path(omh.__file__).resolve()), ScriptedTerminal=ScriptedTerminal, FakePoller=FakePoller, RecordingClient=RecordingClient,
               SID=SID, App=App, Event=Event)

    class CountingTerminal(ScriptedTerminal):
        """Writes are only counted: no VT emulation."""

        def __init__(self, rows: int, cols: int) -> None:
            super().__init__(rows, cols)
            self.bytes = 0

        def write(self, text: str) -> None:
            self.bytes += len(text.encode("utf-8"))

    _ns["CountingTerminal"] = CountingTerminal
    return _ns


def make_app(rows: int = 40, cols: int = 120, environ: dict | None = None, **options):
    n = _load()
    env = {"OMH_TUI_GLOW": "0", "OMH_TUI_WALLPAPER": "0", "OMH_TUI_UPDATE_CHECK": "0", "HOME": n["tmp"],
           "HERMES_HOME": os.environ["HERMES_HOME"], "OMH_HOME": os.environ["OMH_HOME"],
           "COLORTERM": "truecolor", "TERM": "xterm-256color", **(environ or {})}
    term = n["CountingTerminal"](rows, cols)
    app = n["App"](term, n["RecordingClient"](), env, poller=n["FakePoller"](), **options)
    app.sid = n["SID"]
    app.launch_layout = False
    return app, term


def ev(app, kind: str, **payload) -> None:
    n = _load()
    app._on_event(n["Event"](kind, n["SID"], payload))


_CODE = "```python\ndef fib(n: int) -> int:\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n```"
_KOREAN = "한국어 문장입니다. 렌더링 폭이 두 칸인 글자들이 섞여 있습니다 — 줄바꿈을 확인합니다."
_EMOJI = "Done 🎉 ✅ 🚀 👩‍💻 🇰🇷 and **bold** with `code` and a [link](https://example.com)."


def reply_text(i: int) -> str:
    return (f"## Answer {i}\n\n{_KOREAN}\n\n- item one {_EMOJI}\n- item two\n\n{_CODE}\n\n"
            f"Paragraph {i}: " + "lorem ipsum dolor sit amet " * 6)


def add_turn(app, i: int) -> None:
    app.transcript.add_user(f"question {i}: 한국어 질문 🎯 please explain")
    ev(app, "message.start")
    text = reply_text(i)
    ev(app, "message.delta", text=text)
    ev(app, "message.complete", text=text, status="complete")


def render(app) -> None:
    app.dirty = True
    app.last_render = -1e9
    app._render_when_due()


def sample(fn, repeat: int) -> list[float]:
    out = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000)
    return sorted(out)


def p50(xs: list[float]) -> float:
    return statistics.median(xs)


def p95(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[max(math.ceil(0.95 * len(xs)) - 1, 0)]


def row(case: str, label: str, **metrics: float) -> dict:
    return {"case": case, "label": label, "metrics": {k: round(float(v), 4) for k, v in metrics.items()}}


# --- cases ---------------------------------------------------------------------------------------------------------

def case_frame(size: dict) -> list[dict]:
    from omh.tui.keys import CHAR, Key
    rows = []
    for turns in size["turns"]:
        now = [1000.0]  # a fake clock: the busy frame's bytes then depend on ticks, not on how fast the machine ran
        app, term = make_app(clock=lambda: now[0])
        for i in range(turns):
            add_turn(app, i)
        b0 = term.bytes
        t0 = time.perf_counter()
        render(app)
        first_ms, first_bytes = (time.perf_counter() - t0) * 1000, term.bytes - b0
        reps = size["samples"]
        b0 = term.bytes
        steady = sample(lambda: render(app), reps)
        steady_bytes = (term.bytes - b0) / reps

        def key() -> None:
            app._on_input(Key(CHAR, "x"))
            render(app)
        b0 = term.bytes
        keyed = sample(key, reps)
        key_bytes = (term.bytes - b0) / reps
        app.turn_pending = True
        app.busy_since = app.clock()
        from omh.tui.app import TICK_SECONDS

        def tick_frame() -> None:
            now[0] += TICK_SECONDS
            render(app)
        b0 = term.bytes
        tick = sample(tick_frame, reps)
        tick_bytes = (term.bytes - b0) / reps
        rows.append(row("frame", f"{turns} turns", first_frame_ms=first_ms, first_frame_bytes=first_bytes,
                        steady_frame_p50_ms=p50(steady), steady_frame_p95_ms=p95(steady),
                        steady_frame_bytes=steady_bytes, key_frame_p50_ms=p50(keyed), key_frame_bytes=key_bytes,
                        busy_tick_p50_ms=p50(tick), busy_tick_bytes=tick_bytes))
    return rows


def case_redraw(size: dict) -> list[dict]:
    rows = []
    for turns in size["turns"]:
        app, term = make_app()
        for i in range(turns):
            add_turn(app, i)
        render(app)

        def redraw() -> None:
            app._full_redraw()
            render(app)
        reps = size["redraw_repeat"]
        b0 = term.bytes
        ms = sample(redraw, reps)
        rows.append(row("redraw", f"{turns} turns", full_redraw_p50_ms=p50(ms), full_redraw_max_ms=ms[-1],
                        full_redraw_bytes=(term.bytes - b0) / reps))
    return rows


def case_stream(size: dict) -> list[dict]:
    text = " ".join(reply_text(i) for i in range(400))[: size["stream_chars"]]
    app, term = make_app()
    app.transcript.add_user("go")
    ev(app, "message.start")
    app.turn_pending = True
    chunks = [text[at:at + 8] for at in range(0, len(text), 8)]
    per = []
    t_all = time.perf_counter()
    for chunk in chunks:
        t0 = time.perf_counter()
        ev(app, "message.delta", text=chunk)
        render(app)
        per.append((time.perf_counter() - t0) * 1000)
    total = (time.perf_counter() - t_all) * 1000
    tenth = max(len(per) // 10, 1)
    return [row("stream", f"{len(text)} chars, 8-char chunks", chunks_count=len(per), total_ms=total,
                first_tenth_chunk_p50_ms=p50(per[:tenth]), last_tenth_chunk_p50_ms=p50(per[-tenth:]),
                chunk_max_ms=max(per), bytes_out=term.bytes)]


def case_keystroke(size: dict) -> list[dict]:
    line = "한국어 입력과 emoji 🎉 mixed with ascii words to wrap the composer line "
    rows = []
    for chars in size["composer"]:
        app, term = make_app()
        for i in range(5):
            add_turn(app, i)
        app.composer.replace(0, 0, ((line + "\n") * (chars // len(line) + 1))[:chars])
        render(app)

        def key(data: bytes):
            def go() -> None:
                app._take_input(data)
                render(app)
            return go
        reps = size["samples"]
        b0 = term.bytes
        typed = sample(key(b"x"), reps)
        typed_bytes = (term.bytes - b0) / reps
        back = sample(key(b"\x7f"), reps)
        left = sample(key(b"\x1b[D"), reps)
        rows.append(row("keystroke", f"composer {chars} chars", key_p50_ms=p50(typed), key_bytes=typed_bytes,
                        backspace_p50_ms=p50(back), left_arrow_p50_ms=p50(left)))
    return rows


def case_idle(size: dict) -> list[dict]:
    seconds = size["idle_seconds"]
    off = {"OMH_TUI_GLOW": "0", "OMH_TUI_WALLPAPER": "0"}
    on = {"OMH_TUI_GLOW": "1", "OMH_TUI_WALLPAPER": "1"}
    rows = []
    for label, env, busy, look in (("idle, glow and wallpaper off", off, False, None),
                                   ("busy, glow and wallpaper off", off, True, None),
                                   ("idle, glow on, look=aurora", on, False, "aurora"),
                                   ("busy, glow on, look=aurora", on, True, "aurora")):
        app, term = make_app(environ=env)
        for i in range(20 if seconds >= 1 else 3):
            add_turn(app, i)
        app.adopt_background("#101018")
        if look:
            app.launch_look = look
            app.rows_ground = app._ground()
        stats = {"reads": 0, "renders": 0, "end": None}
        deadline = time.monotonic() + seconds

        def read(timeout: float, wake=None) -> bytes:
            if time.monotonic() >= deadline:
                if stats["end"] is None:  # stop counting here: the shutdown flush is not idle cost either
                    stats["end"] = (time.process_time(), time.monotonic(), term.bytes)
                raise EOFError
            stats["reads"] += 1
            time.sleep(min(timeout, max(deadline - time.monotonic(), 0)))
            return b""

        term.read = read
        real_render = app._render

        def counted() -> None:
            if stats["end"] is None:
                stats["renders"] += 1
            real_render()

        app._render = counted
        if busy:
            app.turn_pending = True
            app.busy_since = app.clock()
        render(app)  # the first paint is not idle cost
        app.dirty = False
        stats["renders"] = 0
        b0 = term.bytes
        c0, w0 = time.process_time(), time.monotonic()
        app.run()
        c1, w1, b1 = stats["end"]
        cpu, wall = c1 - c0, w1 - w0
        rows.append(row("idle", label, wakeups_per_s=stats["reads"] / wall, frames_per_s=stats["renders"] / wall,
                        kib_per_s=(b1 - b0) / 1024 / wall, cpu_pct=100 * cpu / wall))
    return rows


def case_plugin(size: dict) -> list[dict]:
    _load()
    from _local_package import load_local_package
    load_local_package()
    from omh.plugin_bundle.omh.hooks import llm_hooks, nudge_budget
    from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
    from omh.plugin_bundle.omh.hooks.result_transforms import transform_tool_result
    from omh.plugin_bundle.omh.hooks.tool_hooks import post_tool_call, pre_tool_call
    from omh.plugin_bundle.omh.tools import recommend_tool

    omh_home, hermes_home = os.environ["OMH_HOME"], os.environ["HERMES_HOME"]
    for path in (omh_home, hermes_home):
        os.makedirs(path, exist_ok=True)
    messages = ["fix the flaky test in tests/test_cli.py and open a PR", "이 저장소의 라우터 구조를 설명해줘",
                "research the best vector database for 10M embeddings and compare costs", "what's 2+2",
                "refactor src/routing/chat.py to remove duplicate helpers, then run the full suite",
                "make a promo video for the product launch", "review this diff for security problems", "thanks!"]
    llm_hooks._reset_awareness_section_state()
    nudge_budget.reset_nudge_budget()
    common = dict(omh_home=omh_home, hermes_home=hermes_home, session_id="perf", platform="tui", model="claude-opus-5-5")
    t0 = time.perf_counter()
    pre_llm_call(user_message=messages[0], is_first_turn=True, **common)
    cold = (time.perf_counter() - t0) * 1000
    times, sizes = [], []
    for turn in range(size["plugin_turns"]):
        t0 = time.perf_counter()
        payload = pre_llm_call(user_message=messages[turn % len(messages)], is_first_turn=False,
                               turn_id=f"turn{turn}", **common)
        times.append((time.perf_counter() - t0) * 1000)
        sizes.append(len(str((payload or {}).get("context", "")).encode("utf-8")))
    rows = [row("plugin", "pre_llm_call", cold_ms=cold, warm_p50_ms=p50(times), warm_p95_ms=p95(times),
                context_bytes_p50=p50(sizes), context_bytes_max=max(sizes))]
    firsts, laters, posts, transforms = [], [], [], []
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        for turn in range(max(size["plugin_turns"] // 5, 2)):
            for call in range(4):
                kwargs = dict(tool_name="terminal", args={"command": "pytest -q tests/test_cli.py"},
                              session_id="perf-tools", turn_id=f"t{turn}", tool_call_id=f"c{turn}-{call}",
                              omh_home=omh_home, hermes_home=hermes_home)
                t0 = time.perf_counter()
                pre_tool_call(**kwargs)
                (firsts if call == 0 else laters).append((time.perf_counter() - t0) * 1000)
                t0 = time.perf_counter()
                post_tool_call(**kwargs, result="ok\n" * 200)
                posts.append((time.perf_counter() - t0) * 1000)
                t0 = time.perf_counter()
                transform_tool_result(**kwargs, result="ok\n" * 200)
                transforms.append((time.perf_counter() - t0) * 1000)
    finally:
        os.chdir(cwd)
    rows.append(row("plugin", "tool hooks (repo cwd)", pre_tool_first_of_turn_p50_ms=p50(firsts),
                    pre_tool_later_p50_ms=p50(laters), post_tool_p50_ms=p50(posts),
                    transform_tool_result_p50_ms=p50(transforms)))
    rec, rec_sizes = [], []
    for message in messages:
        t0 = time.perf_counter()
        out = recommend_tool.omh_recommend_handler({"message": message, "limit": 5}, session_id="perf")
        rec.append((time.perf_counter() - t0) * 1000)
        rec_sizes.append(len(out))
    rows.append(row("plugin", "omh_recommend", p50_ms=p50(rec), max_ms=max(rec), result_bytes_p50=p50(rec_sizes)))
    return rows


def case_startup(size: dict) -> list[dict]:
    _load()
    from omh.tui import terminal as tui_terminal
    if tui_terminal.termios is None:
        return []  # Windows: main() takes its fallback path, so there is no launch to time
    from test_tui_app import BOX_MARK, AppTestCase, Step, startup_answers
    from _tui_gateway_replay import Scenario, spans
    marks_all = []
    for _ in range(2 if size is SIZES["tiny"] else 4):
        case = AppTestCase()
        run = case.prepare(Scenario("session", spans("session", "startup", "create"), answers=startup_answers()),
                           rows=40, cols=120)
        marks: dict = {}
        original = run.terminal.write
        t0 = time.perf_counter()

        def write(text: str, original=original, marks=marks, t0=t0) -> None:
            now = (time.perf_counter() - t0) * 1000
            marks.setdefault("first_write_ms", now)
            if BOX_MARK in text:
                marks.setdefault("first_composer_frame_ms", now)
            original(text)

        run.terminal.write = write
        run.terminal.script(Step(b"\x04", when=lambda run=run, marks=marks, t0=t0: run.terminal.idle() and
                                 marks.setdefault("idle_ms", (time.perf_counter() - t0) * 1000) is not None,
                                 label="idle"))
        case.run_main(run)
        marks["main_returned_ms"] = (time.perf_counter() - t0) * 1000
        try:
            case.assert_clean_run(run)  # a launch that stalled or exited non-zero is not a launch time
        except AssertionError as error:
            raise SystemExit(f"startup case: main() did not run cleanly: {error}")
        marks_all.append(marks)
        case.doCleanups()
    names = sorted(set().union(*marks_all))
    return [row("startup", "main() to first frame, replay gateway",
                **{name: p50([m[name] for m in marks_all if name in m]) for name in names})]


RUNNERS = {"frame": case_frame, "redraw": case_redraw, "stream": case_stream, "keystroke": case_keystroke,
           "idle": case_idle, "plugin": case_plugin, "startup": case_startup}


def run_cases(cases: tuple[str, ...], size_name: str) -> dict:
    size = SIZES[size_name]
    results = []
    for name in cases:
        results.extend(RUNNERS[name](size))
    return {"schema": SCHEMA, "size": size_name, "python": sys.version.split()[0], "tree": str(TREE),
            "omh_file": _load()["omh_file"], "results": results}


# --- output and comparison -----------------------------------------------------------------------------------------

def format_table(payload: dict) -> str:
    lines = [f"{'case':10s} {'label':40s} {'metric':32s} {'value':>14s}"]
    for result in payload["results"]:
        for metric, value in result["metrics"].items():
            lines.append(f"{result['case']:10s} {result['label']:40s} {metric:32s} {value:14.3f}")
    return "\n".join(lines)


def _flatten(payload: dict) -> dict:
    return {(r["case"], r["label"], m): v for r in payload["results"] for m, v in r["metrics"].items()}


def _is_time(metric: str) -> bool:
    return metric.endswith(("_ms", "_pct", "_per_s"))


def verdict(metric: str, base: float, head: float, tolerance: float) -> tuple[float | None, str]:
    """(percent change or None when base is 0, verdict). A time maximum is one sample: no verdict.
    A p95 is a tail sample: tripled tolerance."""
    limit = 1.0
    if _is_time(metric):
        limit = tolerance * (3 if "p95" in metric.split("_") else 1)
    if _is_time(metric) and "max" in metric.split("_"):
        return ((head - base) / base * 100 if base else None), "info"
    if base == head or (metric.endswith("_ms") and abs(head - base) < 0.02) or (metric.endswith("_pct") and abs(head - base) < 0.5):
        return (0.0 if base == head else (head - base) / base * 100 if base else None), "~"
    delta = (head - base) / base * 100 if base else None
    if delta is not None and abs(delta) <= limit:
        return delta, "~"
    return delta, "worse" if head > base else "better"


def median_payload(payloads: list[dict]) -> dict:
    flat = [_flatten(p) for p in payloads]
    merged: dict = {}
    for key in flat[0]:
        case, label, metric = key
        merged.setdefault((case, label), {})[metric] = statistics.median(f[key] for f in flat if key in f)
    return {**payloads[0], "results": [{"case": c, "label": lb, "metrics": m} for (c, lb), m in merged.items()]}


def compare(base_tree: Path, cases: tuple[str, ...], size_name: str, rounds: int, tolerance: float) -> dict:
    runs: dict[str, list[dict]] = {"base": [], "head": []}
    for index in range(rounds):
        order = (("base", base_tree), ("head", ROOT))
        for side, tree in (order if index % 2 == 0 else order[::-1]):  # ABBA: no side always runs second
            env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(tree), str(tree / "tests")]),
                   "OMH_PERF_TREE": str(tree)}
            cmd = [sys.executable, "-P", str(Path(__file__).resolve()), "--json", "--size", size_name]
            for name in cases:
                cmd += ["--case", name]
            done = subprocess.run(cmd, env=env, cwd=str(tree), capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", check=False)
            if done.returncode != 0:
                raise SystemExit(f"{side} run failed in {tree}:\n{done.stderr[-2000:]}")
            payload = json.loads(done.stdout)
            if not Path(payload["omh_file"]).is_relative_to(tree.resolve()):
                raise SystemExit(f"{side} run measured {payload['omh_file']}, not {tree}")
            runs[side].append(payload)
    base, head = _flatten(median_payload(runs["base"])), _flatten(median_payload(runs["head"]))
    rows = []
    for key in list(head) + [k for k in base if k not in head]:
        if key not in base:
            delta, word = None, "new-in-head"
        elif key not in head:
            delta, word = None, "missing-in-head"
        else:
            delta, word = verdict(key[2], base[key], head[key], tolerance)
        rows.append({"case": key[0], "label": key[1], "metric": key[2], "base": base.get(key), "head": head.get(key),
                     "delta_pct": None if delta is None else round(delta, 1), "verdict": word})
    return {"schema": SCHEMA + "+compare", "size": size_name, "rounds": rounds, "tolerance_pct": tolerance,
            "base_tree": str(base_tree), "head_tree": str(ROOT), "rows": rows}


def format_compare(payload: dict) -> str:
    lines = [f"base={payload['base_tree']}  head={payload['head_tree']}  rounds={payload['rounds']}  "
             f"tolerance={payload['tolerance_pct']}%",
             f"{'case':10s} {'label':32s} {'metric':30s} {'base':>12s} {'head':>12s} {'delta%':>8s}  verdict"]
    for r in payload["rows"]:
        cell = lambda v, w: f"{'-' if v is None else format(v, '.3f'):>{w}s}"  # noqa: E731
        delta = "-" if r["delta_pct"] is None else f"{r['delta_pct']:.1f}"
        lines.append(f"{r['case']:10s} {r['label']:32s} {r['metric']:30s} {cell(r['base'], 12)} {cell(r['head'], 12)} "
                     f"{delta:>8s}  {r['verdict']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--case", action="append", choices=CASES, help="run only this case (repeatable)")
    parser.add_argument("--size", choices=tuple(SIZES), default="full", help="'tiny' is the smoke size")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--compare", metavar="TREE", help="another checkout to use as base")
    parser.add_argument("--rounds", type=int, default=3, help="alternating base/head rounds for --compare")
    parser.add_argument("--tolerance", type=float, default=15.0, help="percent noise tolerance for time metrics")
    args = parser.parse_args(argv)
    cases = tuple(args.case or CASES)
    if args.compare:
        payload = compare(Path(args.compare).resolve(), cases, args.size, args.rounds, args.tolerance)
        print(json.dumps(payload, indent=2) if args.json else format_compare(payload))
    else:
        payload = run_cases(cases, args.size)
        print(json.dumps(payload, indent=2) if args.json else format_table(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
