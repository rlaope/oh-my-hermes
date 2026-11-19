"""The waiting row names what it waits on (the owner, 2026-11-19).

Between turns the row above the composer said only `✻ Waiting… (33m 47s · 1
agent · terminal)`. It now names the longest wait from structure alone (a
background process's command words in command position, the delegation
graph's lane fields, the open slot's method), counts the rest, narrows back to
the old row on a narrow terminal, and leaves a 3-second end line as the wait
ends. During a turn the `? waiting on you` row names an approval and a clarify
question.
"""

from __future__ import annotations

import unittest

from _delegation_graphs import graph, lane, root
from test_tui_agent_view import with_graph
from test_tui_modes import SID, drawn, make_app
from omh.tui.app import WAIT_END_SECONDS, WORKING_GLYPHS
from omh.tui.background import BackgroundProcess
from omh.tui.gateway import Event, ServerRequest
from omh.tui.panels import HudSnapshot
from omh.tui.wait_kinds import classify


def after_glyph(row: str) -> str:
    """A wait row's words after its spinner frame and the space (a frame can be two code points, `✳︎`)."""
    return row.split(" ", 1)[1] if " " in row else row

NOW = 1_800_000_000.0
CI = ("bash ~/.hermes/skills/oh-my-hermes-contribution/scripts/merge_when_green.sh 2975 /tmp/w.log", 2280)
TESTS = ("cd wt && uv run python -m unittest discover -s tests", 600)
SONNET = "claude-sonnet-5-5"


def kind_of(command: str) -> tuple[str, str] | None:
    found = classify(command)
    return None if found is None else (found.verb, found.detail)


class ClassifierTests(unittest.TestCase):
    """`wait_kinds.classify`: the words in command position of each segment, in the kinds' priority order."""

    POSITIVE = (
        ("gh pr checks 2975 --watch", "Waiting for CI", "#2975"),
        ("gh run watch 1234567", "Waiting for CI", ""),
        ("gh pr merge 12 --squash --auto", "Waiting for CI", "#12"),
        ("merge_when_green.sh 2975 /tmp/log", "Waiting for CI", "#2975"),
        ("bash ~/s/merge_when_green.sh 2975 /tmp/log", "Waiting for CI", "#2975"),
        ("sh scripts/merge_train.sh /tmp/logs --after 1 2:wt:b", "Waiting for CI", "#1"),
        ("vercel --prod", "Deploying", ""),
        ("fly deploy", "Deploying", ""),
        ("flyctl deploy -a x", "Deploying", ""),
        ("kubectl rollout status deploy/x", "Deploying", ""),
        ("wrangler deploy", "Deploying", ""),
        ("netlify deploy --prod", "Deploying", ""),
        ("pytest -q", "Testing", ""),
        ("python -m pytest tests", "Testing", ""),
        ("python3 -m unittest discover", "Testing", ""),
        ("npm test", "Testing", ""),
        ("pnpm test", "Testing", ""),
        ("yarn test", "Testing", ""),
        ("bun test", "Testing", ""),
        ("npm run test:unit", "Testing", ""),
        ("cargo test --all", "Testing", ""),
        ("go test ./...", "Testing", ""),
        ("vitest run", "Testing", ""),
        ("jest", "Testing", ""),
        ("run_test_modules.sh wt /tmp/log test_a", "Testing", ""),
        ("npm run build", "Building", ""),
        ("bun run build:prod", "Building", ""),
        ("cargo build --release", "Building", ""),
        ("go build ./cmd/x", "Building", ""),
        ("tsc -p .", "Building", ""),
        ("vite build", "Building", ""),
        ("make -j8", "Building", ""),
        ("docker build -t x .", "Building", ""),
        ("tauri build", "Building", ""),
        ("uv sync", "Installing", ""),
        ("uv pip install -e .", "Installing", ""),
        ("pip install x", "Installing", ""),
        ("npm install", "Installing", ""),
        ("pnpm i", "Installing", ""),
        ("yarn add react", "Installing", ""),
        ("bun install", "Installing", ""),
        ("brew install ffmpeg", "Installing", ""),
        ("cargo install ripgrep", "Installing", ""),
        ("ffmpeg -i a.mov b.mp4", "Rendering", ""),
        ("hyperframes render out", "Rendering", ""),
        ("manim -qh scene.py", "Rendering", ""),
        ("blender -b f.blend -a", "Rendering", ""),
        ("git push origin HEAD", "Pushing", ""),
        ("git clone https://x/y", "Downloading", ""),
        ("git fetch origin", "Downloading", ""),
        ("git pull --rebase", "Downloading", ""),
        ("curl -L -o f.zip https://x", "Downloading", ""),
        ("curl -O https://x/f", "Downloading", ""),
        ("wget https://x/f", "Downloading", ""),
        ("hf download org/model", "Downloading", ""),
        ("huggingface-cli download org/model", "Downloading", ""),
        ("sleep 240", "Sleeping", ""),
        ("sleep 5m", "Sleeping", ""),
    )
    NEGATIVE = ("echo pytest", "git status", "grep build", "cat Makefile", "ls test", "printf 'npm test'",
                "vim pytest.ini", "rg 'gh pr checks'", "curl https://x", "sleep 5; pytest-like", "blender f.blend",
                "sleep 60; echo done", "cd x", "export A=1", "", "   ")

    def test_every_kind_names_its_command(self) -> None:
        for command, verb, detail in self.POSITIVE:
            with self.subTest(command=command):
                self.assertEqual(kind_of(command), (verb, detail))

    def test_a_word_that_is_only_an_argument_names_nothing(self) -> None:
        for command in self.NEGATIVE:
            with self.subTest(command=command):
                self.assertIsNone(classify(command))

    def test_wrappers_setup_and_assignments_are_skipped(self) -> None:
        for command in ("uv run pytest", "uv run --with x --python 3.12 pytest", "uvx pytest", "npx jest",
                        "pnpm exec vitest", "bunx vitest", "poetry run pytest", "time pytest", "nice -n 5 pytest",
                        "env A=1 B=2 pytest", "A=1 B=2 pytest", "cd wt && export X=1 && unset Y; pytest",
                        "bash scripts/run_test_modules.sh wt log m", "time uv run python -m unittest"):
            with self.subTest(command=command):
                self.assertEqual(kind_of(command), ("Testing", ""))

    def test_the_first_kind_in_priority_wins_across_segments(self) -> None:
        self.assertEqual(kind_of("pytest && gh pr checks 7 --watch"), ("Waiting for CI", "#7"))
        self.assertEqual(kind_of("npm run build && npm test"), ("Testing", ""), "tests come before builds")
        self.assertEqual(kind_of("uv sync; make"), ("Building", ""))
        self.assertEqual(kind_of("pytest | tee log"), ("Testing", ""))
        self.assertEqual(kind_of("make || vercel"), ("Deploying", ""))
        self.assertEqual(kind_of("git fetch && git push"), ("Pushing", ""))

    def test_quoted_operators_and_heredoc_bodies_are_data(self) -> None:
        # Review round 1: a quoted `;`, or a heredoc body, is data; a newline ends a command as `;` does.
        self.assertIsNone(classify('printf "%s\\n" ";" pytest'))
        self.assertIsNone(classify('echo "a && pytest"'))
        self.assertIsNone(classify("cat <<'EOF'\ndocumentation; pytest\nEOF"))
        self.assertIsNone(classify("cat <<-EOF\n\tgh pr checks 7\n\tEOF"))
        self.assertEqual(kind_of("cat <<'EOF'\nrun; gh pr checks 7\nEOF\ncd wt && uv run python -m unittest"),
                         ("Testing", ""), "the real command after the body, not the body's")
        self.assertEqual(kind_of("echo setup\nuv run python -m unittest"), ("Testing", ""))
        self.assertIsNone(classify("command -v pytest"), "a lookup, not a run")
        self.assertEqual(kind_of("bash -e scripts/run_test_modules.sh wt log t"), ("Testing", ""))
        self.assertIsNone(classify('bash -c "pytest"'), "an inline string is not read as commands")

    def test_a_pr_number_is_the_positional_argument_not_an_option_value(self) -> None:
        self.assertEqual(kind_of("gh pr checks --watch --interval 5 2975"), ("Waiting for CI", "#2975"))
        self.assertEqual(kind_of("gh pr checks --interval=5 2975"), ("Waiting for CI", "#2975"))
        self.assertEqual(kind_of("gh pr checks -R rlaope/x --watch 12"), ("Waiting for CI", "#12"))
        self.assertEqual(kind_of("gh pr merge --match-head-commit 1234567 2975"), ("Waiting for CI", "#2975"))
        self.assertEqual(kind_of("gh pr checks --watch --interval 5"), ("Waiting for CI", ""), "no PR: none guessed")
        self.assertEqual(kind_of("gh pr checks feature/x"), ("Waiting for CI", ""), "a branch is no number")

    def test_the_sleep_says_how_long_is_left_never_below_zero(self) -> None:
        self.assertEqual(classify("sleep 240", started_at=NOW, now=NOW + 100).detail, "2m 20s left")
        self.assertEqual(classify("sleep 2m", started_at=NOW, now=NOW + 119.5).detail, "1s left", "rounded up")
        self.assertEqual(classify("sleep 1h", started_at=NOW, now=NOW + 60).detail, "59m 0s left")
        self.assertEqual(classify("sleep 30", started_at=NOW, now=NOW + 90).detail, "0s left")
        self.assertEqual(classify("sleep 30").detail, "", "no clock: nothing said")
        self.assertIsNone(classify("sleep 30 && echo x"), "only a command that is only a sleep")


def waiting_app(*, procs=(), built=None, cols=120, rows=30, busy=False, host=True):
    """An app between turns whose session waits on `procs` (command, seconds) and the lanes of `built`. Its processes
    are host processes OMH can ask about (`askable`) unless `host` is false."""
    clock, wall = [100.0], [NOW]
    app, client = make_app(busy=busy, rows=rows, cols=cols, clock=lambda: clock[0], wall_clock=lambda: wall[0])
    app.bg_session = app.stored_id
    app.bg_running = tuple(BackgroundProcess(f"proc_{number}", 4000 + number if host else None, host, None, command,
                                             NOW - age, True, False) for number, (command, age) in enumerate(procs))
    with_graph(app, built)
    app.hud = HudSnapshot(app.hud.session_id, app.hud.payload, wall[0])  # read just now
    return app, clock, wall


def wait_rows(app) -> list[str]:
    """The tail's rows that say a wait: the spinner's (a frame can be two code points, `✳︎`), the end line's."""
    return [row for row in drawn(app) if row.startswith((*WORKING_GLYPHS, "✓", "✗", "·")) and " (" in row
            and "background" not in row]


def single(category: str, *, model: str = SONNET, state: str = "running", role: str = "") -> dict:
    child = lane("c", "Look at the diff", category, model, "medium", state, elapsed=300, order=1)
    if role:
        child["role"] = role
    return graph([root(), child], [("root", "c", "dispatch")])


def dag_run(states: dict[str, str], *, open_run: bool = True) -> dict:
    keys = list(states)
    nodes = [root()] + [lane(f"d:x:{key}", key, "quick", "?", "", state, elapsed=900 if state == "running" else 60,
                             order=order) for order, (key, state) in enumerate(states.items(), 1)]
    edges = [("root", f"d:x:{keys[0]}", "dispatch")] + [(f"d:x:{keys[0]}", f"d:x:{key}", "depends_on")
                                                         for key in keys[1:]]
    built = graph(nodes, edges, name="tui waiting kinds", source="dag")
    built["dag_open"] = open_run
    return built


class RowTests(unittest.TestCase):
    """The row through `make_app` and `_tail`, at 40, 80 and 120 columns."""

    def test_a_single_ci_wait(self) -> None:
        for cols in (40, 80, 120):
            with self.subTest(cols=cols):
                app, _clock, _wall = waiting_app(procs=(CI,), cols=cols)
                (row,) = wait_rows(app)
                self.assertEqual(after_glyph(row), "Waiting for CI… (38m 0s · #2975)")
                self.assertEqual(app._working_rows(), 1)

    def test_tests_and_an_agent_beside_ci_are_counted(self) -> None:
        agent = single("quick", model="glm-5.3-flash")
        expected = {120: "Waiting for CI… (38m 0s · #2975 · +1 test run · 1 agent)",
                    80: "Waiting for CI… (38m 0s · #2975 · +1 test run · 1 agent)",
                    40: "Waiting… (38m 0s · 1 agent · 2 termin…"}
        for cols, said in expected.items():
            with self.subTest(cols=cols):
                app, _clock, _wall = waiting_app(procs=(CI, TESTS), built=agent, cols=cols)
                self.assertEqual([after_glyph(row) for row in wait_rows(app)], [said])

    def test_a_narrow_row_drops_the_kind_words_then_the_detail_then_reads_as_before(self) -> None:
        agent = single("quick", model="glm-5.3-flash")
        for cols, said in ((70, "Waiting for CI… (38m 0s · #2975 · +1 test run · 1 agent)"),
                           (57, "Waiting for CI… (38m 0s · #2975 · 1 agent · terminal)"),
                           (54, "Waiting for CI… (38m 0s · 1 agent · terminal)"),
                           (46, "Waiting… (38m 0s · 1 agent · 2 terminals)")):
            with self.subTest(cols=cols):
                app, _clock, _wall = waiting_app(procs=(CI, TESTS), built=agent, cols=cols)
                self.assertEqual([after_glyph(row) for row in wait_rows(app)], [said])

    def test_a_dag_run_with_a_failed_node(self) -> None:
        built = dag_run({"a": "done", "b": "failed", "c": "running", "d": "waiting"})
        for cols, said in ((120, "Running tui waiting kinds… (15m 0s · 1/4 nodes · 1 failed)"),
                           (80, "Running tui waiting kinds… (15m 0s · 1/4 nodes · 1 failed)"),
                           (40, "Running tui waiting kinds… (15m 0s)")):
            with self.subTest(cols=cols):
                app, _clock, _wall = waiting_app(built=built, cols=cols)
                self.assertEqual([after_glyph(row) for row in wait_rows(app)], [said])

    def test_a_review_child_with_its_model(self) -> None:
        for cols in (40, 80, 120):
            with self.subTest(cols=cols):
                app, _clock, _wall = waiting_app(built=single("review"), cols=cols)
                self.assertEqual([after_glyph(row) for row in wait_rows(app)], ["Reviewing… (5m 0s · claude-sonnet-5-5)"])

    def test_a_child_by_its_category_or_role(self) -> None:
        for category, role, model, said in (("google-search", "", SONNET, "Researching… (5m 0s · claude-sonnet-5-5)"),
                                            ("writing", "", "?", "Writing… (5m 0s)"),
                                            ("quick", "review", SONNET, "Reviewing… (5m 0s · claude-sonnet-5-5)"),
                                            ("quick", "", "?", "Running agent… (5m 0s)")):
            with self.subTest(category=category, role=role):
                app, _clock, _wall = waiting_app(built=single(category, role=role, model=model))
                self.assertEqual([after_glyph(row) for row in wait_rows(app)], [said])

    def test_an_unnamed_command_keeps_todays_row(self) -> None:
        app, _clock, _wall = waiting_app(procs=(("./run-the-thing.py --long", 65),))
        self.assertEqual([after_glyph(row) for row in wait_rows(app)], ["Waiting… (1m 5s · terminal)"])

    def test_a_watched_process_names_its_first_pattern_cut(self) -> None:
        app, _clock, _wall = waiting_app(procs=(("tail -f server.log", 30),))
        app._take_waking({"name": "terminal", "result": {"session_id": "proc_0", "notify_on_complete": False,
                                                         "watch_patterns": ["", "Listening on http://127.0.0.1:8000/ready",
                                                                            "x"]}})
        self.assertEqual([after_glyph(row) for row in wait_rows(app)], ['Watching for "Listening on http://127…"… (30s)'])

    def test_never_during_a_turn(self) -> None:
        app, _clock, _wall = waiting_app(procs=(CI,), busy=True)
        self.assertFalse([row for row in drawn(app) if "Waiting for CI" in row])


class EndLineTests(unittest.TestCase):
    """As the longest wait ends between turns with nothing else waiting, one muted row says so for 3 s."""

    def test_a_process_end_is_never_called_passed_or_failed(self) -> None:
        app, clock, _wall = waiting_app(procs=(TESTS,))
        self.assertEqual([after_glyph(row) for row in wait_rows(app)], ["Testing… (10m 0s)"])
        app.bg_running = ()
        self.assertEqual(wait_rows(app), ["· Tests ended (10m 0s)"])
        self.assertEqual(app._working_rows(), 1)
        clock[0] += WAIT_END_SECONDS - 0.1
        app._expire_notification()
        self.assertEqual(wait_rows(app), ["· Tests ended (10m 0s)"])
        self.assertAlmostEqual(app._read_timeout(), 0.1, places=6, msg="a frame is due as the end line goes")
        clock[0] += 0.2
        app.dirty = False
        app._expire_notification()
        self.assertIsNone(app.wait_end)
        self.assertTrue(app.dirty, "the loop repaints without it")
        self.assertEqual(wait_rows(app), [], "gone after 3 s")
        self.assertEqual(app._working_rows(), 0)

    def test_a_lane_that_finished_or_failed(self) -> None:
        for state, said in (("done", "✓ Review finished (5m 0s)"), ("failed", "✗ Review failed (5m 0s)"),
                            ("interrupted", "· Review ended (5m 0s)")):
            with self.subTest(state=state):
                app, _clock, _wall = waiting_app(built=single("review"))
                self.assertTrue(wait_rows(app))
                with_graph(app, single("review", state=state))
                self.assertEqual(wait_rows(app), [said])

    def test_a_dag_run_that_ends_by_its_name(self) -> None:
        app, _clock, _wall = waiting_app(built=dag_run({"a": "done", "b": "running"}))
        self.assertTrue(wait_rows(app))
        with_graph(app, dag_run({"a": "done", "b": "failed"}, open_run=False))
        self.assertEqual(wait_rows(app), ["✗ tui waiting kinds failed (15m 0s)"])

    def test_a_later_wait_still_running_takes_the_row_straight_back(self) -> None:
        app, _clock, _wall = waiting_app(procs=(CI, TESTS))
        self.assertIn("Waiting for CI…", wait_rows(app)[0])
        app.bg_running = app.bg_running[1:]
        self.assertEqual([after_glyph(row) for row in wait_rows(app)], ["Testing… (10m 0s)"])
        self.assertIsNone(app.wait_end)

    def test_not_during_a_turn_and_not_after_one(self) -> None:
        app, _clock, _wall = waiting_app(procs=(TESTS,))
        drawn(app)
        app._on_event(Event("message.start", SID, {}))
        app.bg_running = ()
        self.assertFalse([row for row in drawn(app) if "ended" in row])
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertFalse([row for row in drawn(app) if "ended" in row], "the turn saw it end; no late end line")

    def test_a_parked_or_partial_dag_ticks_no_run_and_keeps_an_earlier_failure(self) -> None:
        # Review round 1: a parked node is waiting, not over; the run ticks only when the panel's summary says over.
        app, _clock, _wall = waiting_app(built=dag_run({"a": "running", "b": "waiting"}))
        self.assertTrue(wait_rows(app))
        with_graph(app, dag_run({"a": "waiting", "b": "waiting"}))
        self.assertEqual(wait_rows(app), [], "a parked node has not ended")
        app, _clock, _wall = waiting_app(built=dag_run({"a": "failed", "b": "running"}))
        self.assertTrue(wait_rows(app))
        with_graph(app, dag_run({"a": "failed", "b": "done"}, open_run=False))
        self.assertEqual(wait_rows(app), ["✗ tui waiting kinds failed (15m 0s)"], "the earlier failure counts")
        app, _clock, _wall = waiting_app(built=dag_run({"a": "done", "b": "running"}))
        self.assertTrue(wait_rows(app))
        partial = dag_run({"a": "done", "b": "done"}, open_run=False)
        partial["hidden_nodes"] = 1
        with_graph(app, partial)
        self.assertEqual(wait_rows(app), ["✓ tui waiting kinds: 1 node finished (15m 0s)"], "a partial graph: no run tick")

    def test_an_end_line_stays_with_its_session_and_its_idle_stretch(self) -> None:
        app, _clock, _wall = waiting_app(procs=(TESTS,))
        drawn(app)
        app.bg_running = ()
        self.assertEqual(wait_rows(app), ["· Tests ended (10m 0s)"])
        app._adopt_stored("another-session")
        self.assertEqual(wait_rows(app), [], "not drawn in the session switched to")
        # A whole turn between two frames: its start forgets the wait, so no end line follows it.
        app, _clock, _wall = waiting_app(procs=(TESTS,))
        drawn(app)
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        app.bg_running = ()
        self.assertEqual(wait_rows(app), [])

    def test_a_process_omh_cannot_ask_about_never_ends_on_screen(self) -> None:
        app, _clock, _wall = waiting_app(procs=(TESTS,), host=False)
        self.assertEqual([after_glyph(row) for row in wait_rows(app)], ["Testing… (10m 0s)"])
        app.bg_running = ()
        self.assertEqual(wait_rows(app), [], "its row may be one another writer dropped")

    def test_working_rows_counts_exactly_the_rows_drawn(self) -> None:
        # Every state of the row: none, the wait, its end line, after the end line.
        app, clock, _wall = waiting_app(procs=(TESTS,), rows=10, cols=60)
        for step in ("wait", "end", "gone"):
            if step == "end":
                app.bg_running = ()
            if step == "gone":
                clock[0] += WAIT_END_SECONDS
            with self.subTest(step=step):
                lines = app._tail(60)
                drawn_rows = sum(1 for line in lines[-1:] if line and "".join(span.text for span in line)[:1] in (
                    *WORKING_GLYPHS, "·", "✓", "✗"))
                self.assertEqual(app._working_rows(), drawn_rows)
                self.assertEqual(drawn_rows, {"wait": 1, "end": 1, "gone": 0}[step], "the end line goes on its own clock")


class WaitsOnThePersonTests(unittest.TestCase):
    """During a turn, the `?` row names an approval and a clarify question; other slots keep `waiting on you`."""

    def turn(self):
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0], cols=80)
        app.busy_since = 90.0
        return app, now

    def test_approval_and_answer_by_the_slots_method(self) -> None:
        from omh.tui.app import HERDR_STATES, STATE_WAITING

        for request, said in ((ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}),
                               "? waiting for your approval (5s)"),
                              (ServerRequest("srq-2", "clarify", {"questions": [{"qid": "q", "question": "Which?"}]}),
                               "? waiting for your answer (5s)"),
                              (ServerRequest("srq-3", "sudo", {"command": "apt install x"}), "? waiting on you (5s)")):
            with self.subTest(method=request.method):
                app, now = self.turn()
                app._on_server_request(request)
                now[0] += 5
                self.assertIn(said, drawn(app))
                self.assertIn(STATE_WAITING, app.title_words, "the title keeps its state word")
                self.assertEqual(HERDR_STATES[STATE_WAITING], "blocked")


if __name__ == "__main__":
    unittest.main()
