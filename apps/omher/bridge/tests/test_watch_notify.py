"""Watch results reach the person: the recorded probe (fixtures/watch-hit-events.jsonl, real kami profile) replayed
through the bridge. A bot-chat automation's delivered run attaches the bot's EXISTING Bot Chat (never makes one), so
the delivered turn becomes exactly one `message` tagged `watch`; silent runs (`wakeAgent: false`, `[SILENT]`) send no
`routine.ran` at all."""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402
from test_bridge import MAIN_RUNTIME, BridgeCase, Env  # noqa: E402

FIXTURE = HERE / "fixtures" / "watch-hit-events.jsonl"
LINES = [json.loads(x) for x in FIXTURE.read_text(encoding="utf-8").splitlines() if x.strip()]
HEADER, FRAMES = LINES[0], LINES[1:]
JOB = HEADER["job"]
REOPEN = next(f["frame"]["result"]["messages"] for f in FRAMES if f["phase"] == "hit.reopen" and f["dir"] == "in")
CRON_ROW, ANSWER_ROW = REOPEN
# the Bot Chat as session.history returns it: an older turn, then the cron delivery and its answer
HISTORY = [{"role": "user", "text": "hi", "timestamp": 100.0, "row_id": 1},
           {"role": "assistant", "text": "hello", "timestamp": 101.0, "row_id": 2},
           {"role": "user", "text": CRON_ROW["text"], "timestamp": CRON_ROW["ts"], "row_id": int(CRON_ROW["id"]),
            "display_kind": "internal_notification"},
           {"role": "assistant", "text": ANSWER_ROW["text"], "timestamp": ANSWER_ROW["ts"], "row_id": int(ANSWER_ROW["id"])}]


# the probe's job ran a stand-in script; a channel watch's script is the collector, named after the watch
WATCH_SCRIPT = f"channel_watch_{JOB['name']}.py"


def job(run_at: str, delivered: bool, status: str = "ok", deliver: str = JOB["deliver"], script: str = WATCH_SCRIPT,
        queued_key: str = "bot-chat:kami") -> dict:
    return {"id": JOB["id"], "name": JOB["name"], "deliver": deliver, "script": script, "prompt": "",
            "schedule_display": "every 1440m", "last_run_at": run_at, "last_status": status,
            "last_delivery_queued": {queued_key: {"status": "queued", "delivery_id": "d1"}} if delivered else None}


def gateway_events(phase: str) -> list[tuple[str, dict]]:
    """The recorded UI frames of `phase` turned back into the gateway events that produced them."""
    out = []
    for f in FRAMES:
        fr = f["frame"]
        if f["phase"] != phase or f["dir"] != "in" or "event" not in fr:
            continue
        ev = fr["event"]
        if ev == "turn.start":
            out.append(("message.start", {}))
        elif ev == "status":
            out.append(("status.update", {"text": fr["text"]}))
        elif ev == "thinking":
            out.append(("thinking.delta", {"text": "…"}))
        elif ev == "delta":
            out.append(("message.delta", {"text": fr["text"]}))
        elif ev == "message":
            out.append(("message.complete", {"text": fr["text"], "persisted_turn": {
                "row_ids": [int(CRON_ROW["id"]), int(fr["id"])], "complete": True,
                "user_row_id": int(CRON_ROW["id"]), "final_assistant_row_id": int(fr["id"])}}))
    return out


class WatchNotify(BridgeCase):
    def write_jobs(self, env: Env, jobs: list[dict]) -> None:
        p = env.home / "profiles" / "kami" / "cron"
        p.mkdir(exist_ok=True)
        f = p / "jobs.json"
        before = f.stat().st_mtime_ns if f.exists() else 0
        f.write_text(json.dumps({"jobs": jobs}))
        while f.stat().st_mtime_ns == before:  # a coarse clock: make the change visible to the mtime check
            f.write_text(json.dumps({"jobs": jobs}))

    def test_fixture_has_the_phases_this_test_replays(self):
        phases = {f["phase"] for f in FRAMES}
        self.assertLessEqual({"hit.run", "silent.wakeAgent_false", "silent.agent_SILENT", "hit.botchat_turn",
                              "hit.reopen"}, phases)
        self.assertEqual(JOB["deliver"], "bot-chat:kami")
        # recorded unattached: the hit gave only routine.ran, no message
        self.assertEqual([f["frame"]["event"] for f in FRAMES if f["phase"] == "hit.run"], ["routine.ran"])

    async def test_unopened_bot_gets_exactly_one_watch_message(self):
        await self._one_watch_message()

    async def test_a_bare_bot_chat_deliver_is_the_jobs_own_bot(self):
        # Hermes reads `bot-chat` alone as the job's own profile, and the token in any case (parse_bot_chat_deliver_token)
        # (no subTest: inside this async case a subtest failure went unreported)
        for deliver, key in (("bot-chat", "canonical"), ("Bot-Chat", "bot-chat:(own)"), ("BOT-CHAT:kami", "canonical")):
            await self._one_watch_message(deliver=deliver, queued_key=key)

    async def test_a_bare_bot_chat_silent_run_draws_no_line(self):
        async with Env(history={MAIN_RUNTIME: HISTORY}) as env:
            self.write_jobs(env, [job("2026-11-15T19:00:00+09:00", False, deliver="bot-chat")])
            s = await self.open(env)
            env.bridge.poll_routines()
            self.write_jobs(env, [job("2026-11-15T19:05:00+09:00", False, deliver="bot-chat")])
            self.assertEqual(await env.bridge.poll_routines_once(), 1)
            await asyncio.sleep(0.05)
            self.assertEqual([e for e in s.events if e["event"] in ("routine.ran", "message")], [])

    async def test_a_bot_chat_automation_that_is_not_a_watch_is_not_tagged(self):
        async with Env(history={MAIN_RUNTIME: HISTORY}) as env:
            brief = {"script": None}
            self.write_jobs(env, [job("2026-11-15T19:00:00+09:00", False, **brief)])
            s = await self.open(env)
            env.bridge.poll_routines()
            self.write_jobs(env, [job("2026-11-15T19:10:31+09:00", True, **brief)])
            await env.bridge.poll_routines_once()
            c = env.clients["kami"]  # still attached, so its answer reaches omher
            for typ, payload in gateway_events("hit.botchat_turn"):
                c.push(typ, payload)
            await s.until(lambda ev: any(e["event"] == "turn.end" for e in ev))
            msgs = [e for e in s.events if e["event"] == "message"]
            self.assertEqual(len(msgs), 1, msgs)
            self.assertNotIn("watch", msgs[0])

    async def _one_watch_message(self, deliver: str = JOB["deliver"], queued_key: str = "bot-chat:kami"):
        async with Env(history={MAIN_RUNTIME: HISTORY}) as env:
            self.write_jobs(env, [job("2026-11-15T19:00:00+09:00", False, deliver=deliver)])
            s = await self.open(env)
            env.bridge.poll_routines()  # baseline
            self.assertEqual(env.connects, [])  # the person never opened kami
            self.write_jobs(env, [job("2026-11-15T19:10:31+09:00", True, deliver=deliver, queued_key=queued_key)])
            await env.bridge.poll_routines_once()
            c = env.clients["kami"]
            self.assertEqual(env.connects, ["kami"])  # attached for its watch results
            self.assertEqual(c.find("session.create"), [])  # its existing Bot Chat, never a new one
            self.assertEqual(len(c.find("session.resume")), 1)
            for typ, payload in gateway_events("hit.botchat_turn"):
                c.push(typ, payload)
            await s.until(lambda ev: any(e["event"] == "turn.end" for e in ev))
            msgs = [e for e in s.events if e["event"] == "message"]
            self.assertEqual(len(msgs), 1, msgs)
            self.assertEqual((msgs[0]["bot"], msgs[0]["id"], msgs[0]["text"]), ("kami", ANSWER_ROW["id"], ANSWER_ROW["text"]))
            self.assertEqual(msgs[0]["watch"]["name"], JOB["name"])
            self.assertAlmostEqual(msgs[0]["watch"]["ts"], CRON_ROW["ts"], delta=0.01)
            ran = [e for e in s.events if e["event"] == "routine.ran"]
            self.assertEqual([(e["name"], e["delivered"]) for e in ran], [(JOB["name"], "kami")])
            # no write op reached Hermes
            self.assertEqual([m for m, _ in c.calls if m in ("prompt.submit", "session.mutate", "session.title")], [])

    async def test_an_ordinary_turn_after_it_carries_no_watch(self):
        async with Env(history={MAIN_RUNTIME: HISTORY}) as env:
            self.write_jobs(env, [job("2026-11-15T19:00:00+09:00", False)])
            s = await self.open(env)
            env.bridge.poll_routines()
            self.write_jobs(env, [job("2026-11-15T19:10:31+09:00", True)])
            await env.bridge.poll_routines_once()
            c = env.clients["kami"]
            c.push("message.start", {})
            c.push("message.complete", {"text": "hello", "persisted_turn": {"row_ids": [1, 2], "complete": True,
                                                                            "user_row_id": 1, "final_assistant_row_id": 2}})
            await s.until(lambda ev: any(e["event"] == "message" for e in ev))
            self.assertNotIn("watch", [e for e in s.events if e["event"] == "message"][0])

    async def test_silent_runs_send_no_routine_line(self):
        async with Env(history={MAIN_RUNTIME: HISTORY}) as env:
            self.write_jobs(env, [job("2026-11-15T19:00:00+09:00", False)])
            s = await self.open(env)
            env.bridge.poll_routines()
            for at in ("2026-11-15T19:12:54+09:00", "2026-11-15T19:23:19+09:00"):  # wakeAgent false, then [SILENT]
                self.write_jobs(env, [job(at, False)])
                self.assertEqual(await env.bridge.poll_routines_once(), 1)  # a run happened...
            await asyncio.sleep(0.05)
            self.assertEqual([e for e in s.events if e["event"] in ("routine.ran", "message")], [])  # ...and said nothing
            self.assertIn("routines.update", s.kinds())  # the Automations page still re-reads

    async def test_a_failed_bot_chat_run_still_draws_its_line(self):
        async with Env() as env:
            self.write_jobs(env, [job("2026-11-15T19:00:00+09:00", False)])
            s = await self.open(env)
            env.bridge.poll_routines()
            self.write_jobs(env, [job("2026-11-15T19:30:00+09:00", False, status="error")])
            await env.bridge.poll_routines_once()
            await s.until(lambda ev: any(e["event"] == "routine.ran" for e in ev))
            ev = [e for e in s.events if e["event"] == "routine.ran"][0]
            self.assertEqual((ev["status"], "delivered" in ev), ("error", False))

    async def test_a_bot_without_a_bot_chat_is_not_given_one(self):
        async with Env(bot_chat=False) as env:
            self.write_jobs(env, [job("2026-11-15T19:00:00+09:00", False)])
            await self.open(env)
            env.bridge.poll_routines()
            self.write_jobs(env, [job("2026-11-15T19:10:31+09:00", True)])
            await env.bridge.poll_routines_once()
            c = env.clients["kami"]
            self.assertEqual(c.find("session.create"), [])
            self.assertEqual(c.find("session.resume"), [])

    def test_reopen_hides_the_cron_row_and_tags_its_answer(self):
        rows = [{"role": r["role"], "text": r["text"], "timestamp": r["ts"], "row_id": int(r["id"]),
                 **({"display_kind": "internal_notification"} if r["role"] == "user" else {})} for r in REOPEN]
        out = ob.chat_messages(rows, {JOB["name"]})
        self.assertEqual([m["role"] for m in out], ["assistant"])
        self.assertEqual(out[0]["watch"]["name"], JOB["name"])
        # an automation that is not a channel watch keeps its rows as they are, untagged
        other = ob.chat_messages(rows, {"some-other-watch"})
        self.assertEqual([m["role"] for m in other], ["user", "assistant"])
        self.assertNotIn("watch", other[1])
        # a person's own message that only quotes the header is never hidden
        mine = ob.chat_messages([{"role": "user", "text": "what does [Cronjob mean?", "row_id": 1}])
        self.assertEqual([m["role"] for m in mine], ["user"])

    def test_delivered_to_and_targets(self):
        self.assertEqual(ob.delivered_to(job("x", True)), "kami")
        self.assertIsNone(ob.delivered_to(job("x", False)))
        self.assertEqual(ob.bot_chat_targets("bot-chat:kami, local ,bot-chat:friren"), {"kami", "friren"})
        self.assertEqual(ob.bot_chat_targets("origin"), set())
        self.assertEqual(ob.bot_chat_targets("bot-chat", "kami"), {"kami"})
        self.assertEqual(ob.bot_chat_targets("Bot-Chat:friren, BOT-CHAT", "kami"), {"friren", "kami"})
        self.assertEqual(ob.bot_chat_targets("bot-chat"), set())  # no owner known: nothing to attach
        own = {**job("x", True, deliver="bot-chat", queued_key="canonical")}
        self.assertEqual(ob.delivered_to(own, "kami"), "kami")
        self.assertEqual(ob.delivered_to({**own, "last_delivery_queued": {"bot-chat:(own)": {}}}, "kami"), "kami")


if __name__ == "__main__":
    unittest.main()
