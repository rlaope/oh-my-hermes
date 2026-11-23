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

    def test_only_the_first_entries_are_looked_at(self):
        rollup = [self.run_()] * ob.PR_ROLLUP_MAX + [self.run_(conclusion="FAILURE")]
        self.assertEqual(ob.pr_checks_of(rollup), "passing")


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

    def test_at_most_thirty_calls_a_minute_across_plans_and_threads(self):
        calls, now = [], [1000.0]

        def view(repo, n):
            calls.append(n)
            return {"state": "MERGED", "mergedAt": "t"}

        prs = ob.PrStates(view=view, clock=lambda: now[0])
        self.assertEqual(ob.PR_CALLS_PER_MIN, 30)
        for n in range(1, 21):  # 20 from threads
            prs.thread([{"number": n, "repo": "o/r", "url": "u"}])
        run = {"nodes": [{"id": str(n), "pr": {"number": n, "repo": "p/q"}} for n in range(1, 16)]}
        got = prs.states(run)  # 15 from a plan: 10 fit
        self.assertEqual(len(calls), 30)
        self.assertEqual(sorted(v["state"] for v in got.values()), ["merged"] * 10 + ["unknown"] * 5)
        # past the cap: a PR already known keeps its answer even on a refresh, a new one reads unknown and is not kept
        now[0] = 1000.0 + 30
        self.assertEqual(prs.thread([{"number": 1, "repo": "o/r", "url": "u"}], fresh=True)[0]["state"], "merged")
        self.assertEqual(prs.thread([{"number": 99, "repo": "o/r", "url": "u"}])[0]["state"], "unknown")
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
        # rule 31: thread ops stay on this computer, so a peer bot's thread has no PR state (the number only)
        self.assertNotIn("thread.prs", ob.PEER_FORWARD)
        self.assertNotIn("thread.list", ob.PEER_FORWARD)


class ThreadPrsOp(BridgeCase):
    async def open(self, env):
        s = await super().open(env)
        ok(await s.req("chat.open", bot="kami"))
        return s

    HISTORY = [
        {"role": "user", "text": "fix it; the old one was https://github.com/o/r/pull/1", "row_id": 1},
        {"role": "assistant", "text": "Now I'll open https://github.com/o/r/pull/2", "row_id": 2},  # commentary
        {"role": "tool", "text": "created https://github.com/o/r/pull/3", "row_id": 3},
        {"role": "assistant", "text": "Opened https://github.com/o/r/pull/4 (checks running).", "row_id": 4},
    ]

    async def test_thread_prs_reads_the_threads_own_history_and_asks_gh_for_its_bots_links(self):
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
            c = env.clients["kami"]
            c.history[tid] = self.HISTORY
            got = ok(await s.req("thread.prs", bot="kami", thread=tid))
            self.assertEqual(got, {"prs": [{"number": 4, "repo": "o/r", "url": "https://github.com/o/r/pull/4",
                                            "state": "open", "checks": "failing", "head": SHA}]})
            self.assertEqual(asked, [("o/r", 4)])
            self.assertEqual([p["session_id"] for p in c.find("session.history")], [tid])  # read, never resumed
            self.assertEqual([x for x in c.find("session.resume") if x["session_id"] == tid], [])
            # nothing named yet: no gh call at all
            other = ok(await s.req("thread.create", bot="kami"))["thread"]
            self.assertEqual(ok(await s.req("thread.prs", bot="kami", thread=other)), {"prs": []})
            self.assertEqual(asked, [("o/r", 4)])
            # the main chat, an unknown id and a missing one are refused
            main = ok(await s.req("chat.open", bot="kami"))["session_id"]
            self.assertEqual((await s.req("thread.prs", bot="kami", thread=main))["error"]["code"], "bad_request")
            self.assertEqual((await s.req("thread.prs", bot="kami", thread="stored-th-99"))["error"]["code"], "not_found")
            self.assertEqual((await s.req("thread.prs", bot="kami"))["error"]["code"], "bad_request")

    async def test_a_listed_thread_not_attached_is_read_by_its_stored_id(self):
        store = HermesStore()
        async with ThreadEnv(store) as env:
            s = await self.open(env)
            tid = ok(await s.req("thread.create", bot="kami"))["thread"]
            ok(await s.req("chat.send", bot="kami", session=tid, text="first"))
        async with ThreadEnv(store) as env2:
            env2.bridge.prs = ob.PrStates(view=lambda repo, n: None)  # gh missing, signed out or offline
            s2 = await self.open(env2)
            ok(await s2.req("thread.list", bot="kami"))
            env2.clients["kami"].history[tid] = self.HISTORY
            got = ok(await s2.req("thread.prs", bot="kami", thread=tid, fresh=True))
            self.assertEqual(got, {"prs": [{"number": 4, "repo": "o/r", "url": "https://github.com/o/r/pull/4",
                                            "state": "unknown", "checks": "none"}]})
            self.assertEqual([x for x in env2.clients["kami"].find("session.resume") if x["session_id"] == tid], [])


if __name__ == "__main__":
    unittest.main()
