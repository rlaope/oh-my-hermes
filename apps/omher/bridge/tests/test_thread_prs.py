"""A thread's pull requests (`thread.prs`, BOUNDARY rule 21): the full PR links in the bot's own answers of that thread,
newest first, at most three, validated strictly; GitHub's state and check result for each through the person's own
`gh` (stubbed here), sharing the plans' cache, pool and per-minute cap. No Hermes, no gh, no network."""
from __future__ import annotations

import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402
from test_threads import HermesStore, ThreadEnv, ok  # noqa: E402
from test_bridge import BridgeCase  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"


def said(text: str) -> dict:
    return {"role": "assistant", "text": text}


class ThreadPrLinks(unittest.TestCase):
    def test_only_the_bots_answers_count_newest_first_each_once_three_at_most(self):
        msgs = [
            {"role": "user", "text": "look at https://github.com/o/r/pull/1"},
            said("opened https://github.com/o/r/pull/2 and https://github.com/o/r/pull/3"),
            {"role": "tool", "text": "https://github.com/o/r/pull/4"},
            said("also https://github.com/a/b/pull/5"),
            said("back to https://github.com/o/r/pull/2, then https://github.com/c/d/pull/6"),
        ]
        self.assertEqual([(r["repo"], r["number"]) for r in ob.thread_pr_refs(msgs)],
                         [("c/d", 6), ("o/r", 2), ("a/b", 5)])
        self.assertEqual(ob.thread_pr_refs(msgs, limit=1),
                         [{"number": 6, "repo": "c/d", "url": "https://github.com/c/d/pull/6"}])
        self.assertEqual(ob.thread_pr_refs([]), [])
        self.assertEqual(ob.thread_pr_refs([said("PR #12 is open"), {"role": "assistant", "text": None}, "x"]), [])

    def test_look_alikes_extra_segments_and_huge_numbers_are_not_prs(self):
        bad = (
            "https://github.com.evil.io/o/r/pull/1",
            "https://evilgithub.com/o/r/pull/1",
            "https://www.github.com/o/r/pull/1",
            "https://GitHub.com/o/r/pull/1",
            "http://github.com/o/r/pull/1",
            "https://user@github.com/o/r/pull/1",
            "xhttps://github.com/o/r/pull/1",
            "https://evil.io/https://github.com/o/r/pull/1",
            "https://github.com/o/r/pull/1/files",
            "https://github.com/o/r/pull/1/",
            "https://github.com/o/r/x/pull/1",
            "https://github.com/o/r/pull/12345678",
            "https://github.com/o/r/pull/0012",
            "https://github.com/o/r/pull/0",
            "https://github.com/-o/r/pull/1",
            "https://github.com/o/../pull/1",
            "https://github.com/o/./pull/1",
            "https://github.com/o/r/pull/1a",
            "https://github.com/o/r/issues/1",
            "https://github.com/o/r/pull/١",
        )
        for link in bad:
            self.assertEqual(ob.thread_pr_refs([said(f"see {link} now")]), [], link)
        good = (
            "https://github.com/o/r/pull/7",
            "(https://github.com/o/r/pull/7)",
            "[#7](https://github.com/o/r/pull/7)",
            "https://github.com/o/r/pull/7.",
            "https://github.com/o/r/pull/7#issuecomment-1",
            "https://github.com/o/r/pull/7?w=1",
        )
        for link in good:
            self.assertEqual(ob.thread_pr_refs([said(f"opened {link}")]),
                             [{"number": 7, "repo": "o/r", "url": "https://github.com/o/r/pull/7"}], link)


class Checks(unittest.TestCase):
    def run_(self, status="COMPLETED", conclusion="SUCCESS", name="test"):
        return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}

    def ctx(self, state, context="ci/x"):
        return {"__typename": "StatusContext", "context": context, "state": state}

    def test_rollup_reduces_to_one_word(self):
        r = self.run_
        cases = (
            (None, "none"),
            ([], "none"),
            ("FAILURE", "none"),
            ([r(conclusion="SKIPPED"), r(conclusion="NEUTRAL")], "none"),
            ([r(), r(conclusion="SKIPPED")], "passing"),
            ([r(), r(conclusion="NEUTRAL"), self.ctx("SUCCESS")], "passing"),
            ([r(), r(conclusion="FAILURE")], "failing"),
            ([r(), r(status="IN_PROGRESS", conclusion="")], "running"),
            ([r(status="QUEUED", conclusion=None), r(conclusion="TIMED_OUT")], "failing"),
            ([r(conclusion="CANCELLED")], "failing"),
            ([r(conclusion="ACTION_REQUIRED")], "failing"),
            ([self.ctx("PENDING"), r()], "running"),
            ([self.ctx("EXPECTED")], "running"),
            ([self.ctx("ERROR"), r()], "failing"),
            ([self.ctx("FAILURE")], "failing"),
            ([{"state": "SUCCESS"}], "passing"),
            ([r(conclusion="WHATEVER")], "running"),  # not understood: never claimed as a result
            ([r(), "x", 3, None], "passing"),
        )
        for rollup, want in cases:
            self.assertEqual(ob.pr_checks_of(rollup), want, rollup)

    def test_a_check_name_never_makes_a_state(self):
        r = self.run_
        self.assertEqual(ob.pr_checks_of([r(name="FAILURE"), r(name="conclusion: FAILURE")]), "passing")
        self.assertEqual(ob.pr_checks_of([r(conclusion="FAILURE", name="passing ✓ SUCCESS")]), "failing")
        self.assertEqual(ob.pr_checks_of([self.ctx("SUCCESS", context="FAILURE")]), "passing")
        self.assertEqual(ob.pr_checks_of([{**r(), "description": "FAILURE", "detailsUrl": "x"}]), "passing")

    def test_entries_past_the_bound_are_not_looked_at_and_never_read_as_passing(self):
        rollup = [self.run_()] * ob.PR_ROLLUP_MAX + [self.run_(conclusion="FAILURE")]
        self.assertEqual(ob.pr_checks_of(rollup), "running")  # the unread failure could be there
        self.assertEqual(ob.pr_checks_of([self.run_()] * ob.PR_ROLLUP_MAX), "passing")
        self.assertEqual(ob.pr_checks_of([self.run_(conclusion="FAILURE")] + [self.run_()] * ob.PR_ROLLUP_MAX), "failing")

class Limits(unittest.TestCase):
    def test_a_view_gives_state_checks_and_a_head_only_when_it_is_a_commit_id(self):
        def view(repo, n):
            return {"state": "OPEN", "isDraft": False, "url": f"https://github.com/{repo}/pull/{n}",
                    "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "FAILURE", "name": "x"}],
                    "headRefOid": SHA if n == 1 else "not-a-sha‮", "title": "ignored"}

        prs = ob.PrStates(view=view)
        got = prs.thread([{"number": 1, "repo": "o/r", "url": "https://github.com/o/r/pull/1"},
                          {"number": 2, "repo": "o/r", "url": "https://github.com/o/r/pull/2"}])
        self.assertEqual(got, [
            {"number": 1, "repo": "o/r", "url": "https://github.com/o/r/pull/1", "state": "open", "checks": "failing", "head": SHA},
            {"number": 2, "repo": "o/r", "url": "https://github.com/o/r/pull/2", "state": "open", "checks": "failing"},
        ])

    def test_no_gh_or_a_timeout_reads_unknown_with_no_checks(self):
        with mock.patch.object(ob, "_gh_path", return_value=None):
            self.assertEqual(ob.PrStates().thread([{"number": 1, "repo": "o/r", "url": "u"}]),
                             [{"number": 1, "repo": "o/r", "url": "u", "state": "unknown", "checks": "none"}])

        def slow(argv, **kw):
            raise ob.subprocess.TimeoutExpired(argv, kw["timeout"])

        with mock.patch.object(ob.subprocess, "run", slow), mock.patch.object(ob, "_gh_path", return_value="/bin/gh"):
            self.assertEqual(ob.PrStates().thread([{"number": 2, "repo": "o/r", "url": "u"}])[0]["state"], "unknown")

    def test_the_cache_window_and_an_explicit_refresh(self):
        calls, now = [], [1000.0]

        def view(repo, n):
            calls.append(n)
            return {"state": "OPEN", "statusCheckRollup": [{"status": "IN_PROGRESS"}]}

        prs = ob.PrStates(view=view, clock=lambda: now[0])
        ref = [{"number": 9, "repo": "o/r", "url": "u"}]
        prs.thread(ref)
        prs.thread(ref)
        self.assertEqual(calls, [9])  # kept
        now[0] += ob.PR_FRESH_MIN - 1
        prs.thread(ref, fresh=True)
        self.assertEqual(calls, [9])  # a refresh this soon reuses the answer
        now[0] += 2
        prs.thread(ref, fresh=True)
        self.assertEqual(calls, [9, 9])  # older than PR_FRESH_MIN: asked again
        now[0] += ob.PR_TTL - 1
        prs.thread(ref)
        self.assertEqual(calls, [9, 9])
        now[0] += 2
        prs.thread(ref)
        self.assertEqual(calls, [9, 9, 9])  # the 5 minute window ran out
        self.assertEqual((ob.PR_TTL, ob.PR_FRESH_MIN), (300.0, 10.0))

    def test_at_most_thirty_calls_a_minute_of_which_threads_take_twenty(self):
        calls, now = [], [1000.0]

        def view(repo, n):
            calls.append(n)
            return {"state": "MERGED", "mergedAt": "t"}

        prs = ob.PrStates(view=view, clock=lambda: now[0])
        self.assertEqual((ob.PR_CALLS_PER_MIN, ob.PR_THREAD_CALLS_PER_MIN), (30, 20))
        got = [prs.thread([{"number": n, "repo": "o/r", "url": "u"}])[0] for n in range(1, 26)]  # 25 from threads
        self.assertEqual(len(calls), 20)  # threads stop at 20
        self.assertEqual([g["state"] for g in got[20:]], ["unknown"] * 5)
        self.assertTrue(all(g.get("limited") is True for g in got[20:]))  # over the cap, not "no gh"
        self.assertNotIn("limited", got[0])
        run = {"nodes": [{"id": str(n), "pr": {"number": n, "repo": "p/q"}} for n in range(1, 16)]}
        states = prs.states(run)  # a plan still has 10
        self.assertEqual(len(calls), 30)
        self.assertEqual(sorted(v["state"] for v in states.values()), ["merged"] * 10 + ["unknown"] * 5)
        # past the cap: a PR already known keeps its answer even on a refresh; a new one is not kept as unknown
        now[0] = 1000.0 + 30
        self.assertEqual(prs.thread([{"number": 1, "repo": "o/r", "url": "u"}], fresh=True)[0]["state"], "merged")
        self.assertEqual(prs.thread([{"number": 99, "repo": "o/r", "url": "u"}])[0], {"number": 99, "repo": "o/r", "url": "u",
                                                                                    "state": "unknown", "checks": "none", "limited": True})
        self.assertEqual(len(calls), 30)
        now[0] = 1000.0 + 61  # the window moved on
        self.assertEqual(prs.thread([{"number": 99, "repo": "o/r", "url": "u"}])[0]["state"], "merged")
        self.assertEqual(len(calls), 31)

    def test_at_most_four_look_ups_at_once(self):
        lock, live, peak = threading.Lock(), [0], [0]

        def view(repo, n):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.05)
            with lock:
                live[0] -= 1
            return {"state": "OPEN"}

        prs = ob.PrStates(view=view)
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda n: prs.thread([{"number": n, "repo": "o/r", "url": "u"}]), range(1, 13)))
        self.assertLessEqual(peak[0], ob.PR_POOL)
        self.assertEqual(ob.PR_POOL, 4)

    def test_a_peer_bots_thread_is_never_read_over_ssh(self):
        # rule 31: a peer bot's threads cross (#3172), but its PRs are read on this computer only, so a thread over
        # there has no PR state (the number only); the session-taking ops never include the PR read either
        self.assertNotIn("thread.prs", ob.PEER_FORWARD)
        self.assertNotIn("thread.prs", ob.PEER_SESSION_OPS)


def save_rows(profile: Path, sid: str, rows: list[tuple], display_kind: bool = True) -> None:
    """The thread's rows as Hermes saves them in the profile's state.db: (role, content[, display_kind])."""
    import sqlite3
    con = sqlite3.connect(profile / "state.db")
    cols = "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, tool_calls TEXT, timestamp REAL"
    con.execute(f"CREATE TABLE IF NOT EXISTS messages ({cols}{', display_kind TEXT' if display_kind else ''})")
    for i, r in enumerate(rows):
        if display_kind:
            con.execute("INSERT INTO messages (session_id, role, content, timestamp, display_kind) VALUES (?, ?, ?, ?, ?)",
                        (sid, r[0], r[1], 1000.0 + i, r[2] if len(r) > 2 else None))
        else:
            con.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                        (sid, r[0], r[1], 1000.0 + i))
    con.commit()
    con.close()


ROWS = [
    ("user", "fix it; the old one was https://github.com/o/r/pull/1"),
    ("assistant", "Now I'll open https://github.com/o/r/pull/2"),  # commentary beside a tool call: not the answer
    ("tool", "created https://github.com/o/r/pull/3"),
    ("assistant", "Opened https://github.com/o/r/pull/4 (checks running)."),
    ("user", "and the docs?"),
    ("assistant", "https://github.com/o/r/pull/5", "hidden"),
    ("assistant", "Docs are in the same PR."),
]


class ReadThreadRows(unittest.TestCase):
    def test_reads_only_that_threads_user_and_assistant_rows_read_only(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            prof = Path(d)
            self.assertEqual(ob.read_thread_rows(prof, "th-1"), [])  # no state.db
            save_rows(prof, "th-1", ROWS)
            save_rows(prof, "other", [("assistant", "https://github.com/x/y/pull/9")])
            before = os.stat(prof / "state.db").st_mtime_ns
            rows = ob.read_thread_rows(prof, "th-1")
            self.assertEqual([r["role"] for r in rows], ["user", "assistant", "assistant", "user", "assistant", "assistant"])
            self.assertEqual(rows[4]["display_kind"], "hidden")
            refs = ob.thread_pr_refs(ob.chat_messages(rows))
            self.assertEqual([r["number"] for r in refs], [4])  # never the person's, a tool's, commentary or a hidden row
            self.assertEqual(os.stat(prof / "state.db").st_mtime_ns, before)
            with mock.patch.object(ob, "THREAD_ROWS_MAX", 2):
                self.assertEqual([r["content"] for r in ob.read_thread_rows(prof, "th-1")],
                                 ["https://github.com/o/r/pull/5", "Docs are in the same PR."])

    def test_an_older_state_db_without_display_kind(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            save_rows(Path(d), "th-1", [("assistant", "Opened https://github.com/o/r/pull/6")], display_kind=False)
            rows = ob.read_thread_rows(Path(d), "th-1")
            self.assertEqual([(r["role"], r["content"]) for r in rows], [("assistant", "Opened https://github.com/o/r/pull/6")])
            (Path(d) / "state.db").write_bytes(b"not a database")
            self.assertEqual(ob.read_thread_rows(Path(d), "th-1"), [])


class CompressionLineage(unittest.TestCase):
    """Hermes moves a long conversation to a continuation session when it compresses it; the thread's links are read
    across that chain both ways, never into a branch, a reset, a subagent or a tool session."""

    def lineage_db(self, prof: Path) -> None:
        import sqlite3
        con = sqlite3.connect(prof / "state.db")
        con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT, end_reason TEXT,"
                    " model_config TEXT, source TEXT)")
        con.executemany("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)", [
            ("root", None, "compression", None, "tui"),
            ("cont", "root", "compression", "{}", "tui"),
            ("cont2", "cont", None, None, "tui"),
            ("branch", "root", None, '{"_branched_from": "root"}', "tui"),
            ("deleg", "cont", None, '{"_delegate_from": "cont"}', "tui"),
            ("tool", "cont", None, None, "tool"),
            ("other", None, None, None, "tui"),
        ])
        con.commit()
        con.close()
        save_rows(prof, "root", [("user", "fix it"), ("assistant", "Opened https://github.com/o/r/pull/1")])
        save_rows(prof, "branch", [("assistant", "https://github.com/o/r/pull/90")])
        save_rows(prof, "cont", [("user", "more"), ("assistant", "Opened https://github.com/o/r/pull/2")])
        save_rows(prof, "deleg", [("assistant", "https://github.com/o/r/pull/91")])
        save_rows(prof, "tool", [("assistant", "https://github.com/o/r/pull/92")])
        save_rows(prof, "cont2", [("user", "and?"), ("assistant", "Opened https://github.com/o/r/pull/3")])
        save_rows(prof, "other", [("assistant", "https://github.com/o/r/pull/93")])

    def test_links_after_and_before_a_compression_are_both_read(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            prof = Path(d)
            self.lineage_db(prof)
            for start in ("root", "cont", "cont2"):
                rows = ob.read_thread_rows(prof, start)
                self.assertEqual([r["number"] for r in ob.thread_pr_refs(ob.chat_messages(rows))], [3, 2, 1], start)
                self.assertEqual(ob.thread_last_row(prof, start), max(r["row_id"] for r in rows))
            self.assertEqual([r["number"] for r in ob.thread_pr_refs(ob.chat_messages(ob.read_thread_rows(prof, "branch")))], [90])

    def test_hermes_compaction_summary_is_never_the_bots_answer(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            prof = Path(d)
            self.lineage_db(prof)
            summary = ("[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below. ...\n"
                       "The user pasted https://github.com/o/r/pull/9 and a tool printed https://github.com/o/r/pull/8\n"
                       "--- END OF CONTEXT SUMMARY — respond to the message below, not the summary above ---")
            merged = ("[PRIOR CONTEXT — for reference only; not a new message]\nsee https://github.com/o/r/pull/7\n"
                      "[END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW]\nsummary")
            save_rows(prof, "fresh", [("assistant", summary), ("user", "go on"), ("assistant", merged),
                                      ("assistant", "[CONTEXT SUMMARY]: https://github.com/o/r/pull/6"),
                                      ("user", "and?"), ("assistant", "Opened https://github.com/o/r/pull/10")])
            rows = ob.read_thread_rows(prof, "fresh")
            self.assertEqual([r["number"] for r in ob.thread_pr_refs(ob.chat_messages(rows))], [10])
            self.assertFalse(any("COMPACTION" in r["content"] or "CONTEXT SUMMARY" in r["content"] for r in rows))
            # a user-role carrier still ends the turn before it: the bot's earlier answer stays that turn's answer
            save_rows(prof, "user-carrier", [("user", "ship it"), ("assistant", "Opened https://github.com/o/r/pull/11"),
                                             ("user", summary), ("assistant", "Rebased.")])
            rows = ob.read_thread_rows(prof, "user-carrier")
            self.assertEqual([r["number"] for r in ob.thread_pr_refs(ob.chat_messages(rows))], [11])

    def test_the_walk_is_bounded(self):
        import sqlite3
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            con = sqlite3.connect(Path(d) / "state.db")
            con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT, end_reason TEXT,"
                        " model_config TEXT, source TEXT)")
            con.executemany("INSERT INTO sessions VALUES (?, ?, 'compression', NULL, 'tui')",
                            [(f"s{i}", f"s{i - 1}" if i else None) for i in range(200)])
            con.commit()
            self.assertLessEqual(len(ob.thread_lineage(con, "s100")), ob.LINEAGE_MAX)
            self.assertEqual(ob.thread_lineage(con, "s100")[0], "s100")
            con.close()


class ThreadPrsOp(BridgeCase):
    async def open(self, env):
        s = await super().open(env)
        ok(await s.req("chat.open", bot="kami"))
        return s

    async def test_thread_prs_reads_the_saved_rows_and_asks_gh_for_its_bots_links(self):
        store = HermesStore()
        asked = []

        def view(repo, n):
            asked.append((repo, n))
            return {"state": "OPEN", "isDraft": False, "url": f"https://github.com/{repo}/pull/{n}", "headRefOid": SHA,
                    "statusCheckRollup": [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]}

        async with ThreadEnv(store) as env:
            env.bridge.prs = ob.PrStates(view=view)
            s = await self.open(env)
            tid = ok(await s.req("thread.create", bot="kami"))["thread"]
            save_rows(env.home / "profiles" / "kami", tid, ROWS)
            c = env.clients["kami"]
            before = len(c.calls)
            got = ok(await s.req("thread.prs", bot="kami", thread=tid))
            self.assertEqual(got, {"prs": [{"number": 4, "repo": "o/r", "url": "https://github.com/o/r/pull/4",
                                            "state": "open", "checks": "failing", "head": SHA}]})
            self.assertEqual(asked, [("o/r", 4)])
            self.assertEqual(c.calls[before:], [])  # no gateway call at all: no history read, no resume
            # nothing named yet: no gh call at all
            other = ok(await s.req("thread.create", bot="kami"))["thread"]
            self.assertEqual(ok(await s.req("thread.prs", bot="kami", thread=other)), {"prs": []})
            self.assertEqual(asked, [("o/r", 4)])
            # the main chat, an unknown id and a missing one are refused
            main = ok(await s.req("chat.open", bot="kami"))["session_id"]
            self.assertEqual((await s.req("thread.prs", bot="kami", thread=main))["error"]["code"], "bad_request")
            self.assertEqual((await s.req("thread.prs", bot="kami", thread="stored-th-99"))["error"]["code"], "not_found")
            self.assertEqual((await s.req("thread.prs", bot="kami"))["error"]["code"], "bad_request")

    async def test_the_links_are_read_again_only_when_the_thread_has_a_new_row(self):
        async with ThreadEnv(HermesStore()) as env:
            env.bridge.prs = ob.PrStates(view=lambda repo, n: {"state": "OPEN"})
            s = await self.open(env)
            tid = ok(await s.req("thread.create", bot="kami"))["thread"]
            prof = env.home / "profiles" / "kami"
            save_rows(prof, tid, ROWS)
            with mock.patch.object(ob, "read_thread_rows", wraps=ob.read_thread_rows) as rows:
                self.assertEqual([p["number"] for p in ok(await s.req("thread.prs", bot="kami", thread=tid))["prs"]], [4])
                ok(await s.req("thread.prs", bot="kami", thread=tid))
                self.assertEqual(rows.call_count, 1)  # no new row: the kept links
                save_rows(prof, tid, [("user", "and?"), ("assistant", "Opened https://github.com/o/r/pull/8 too.")])
                got = ok(await s.req("thread.prs", bot="kami", thread=tid))["prs"]
                self.assertEqual(rows.call_count, 2)
                self.assertEqual([p["number"] for p in got], [8, 4])

    async def test_a_listed_thread_not_attached_is_read_without_attaching_it(self):
        store = HermesStore()
        async with ThreadEnv(store) as env:
            s = await self.open(env)
            tid = ok(await s.req("thread.create", bot="kami"))["thread"]
            ok(await s.req("chat.send", bot="kami", session=tid, text="first"))
        async with ThreadEnv(store) as env2:
            env2.bridge.prs = ob.PrStates(view=lambda repo, n: None)  # gh missing, signed out or offline
            s2 = await self.open(env2)
            ok(await s2.req("thread.list", bot="kami"))
            save_rows(env2.home / "profiles" / "kami", tid, ROWS)
            c = env2.clients["kami"]
            before = len(c.calls)
            got = ok(await s2.req("thread.prs", bot="kami", thread=tid, fresh=True))
            self.assertEqual(got, {"prs": [{"number": 4, "repo": "o/r", "url": "https://github.com/o/r/pull/4",
                                            "state": "unknown", "checks": "none"}]})
            self.assertEqual(c.calls[before:], [])
            self.assertNotIn(tid, env2.bridge.conns["kami"].folders)  # still not attached


if __name__ == "__main__":
    unittest.main()
