"""The bot opens threads itself (`split`): the threads note on main-chat turns, the strict parser for ```omher-thread```
/ ```omher-thread-route``` blocks in a main-chat final answer, and what they do (thread made + task sent + link
event; route = an ask event only, never a thread). FakeGateway only; no Hermes, no model."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402
from test_threads import HermesStore, ThreadEnv, ok  # noqa: E402
from test_bridge import BridgeCase  # noqa: E402


def block(obj, kind="omher-thread") -> str:
    return f"```{kind}\n{json.dumps(obj, ensure_ascii=False)}\n```"


def open_line(obj, kind="omher-thread") -> str:
    """The layout the real model writes: the JSON on the opening fence line, the closing fence on the next line."""
    return f"```{kind} {json.dumps(obj, ensure_ascii=False)}\n```"


A = {"title": "OG 502 원인", "task": "gateway 로그에서 502 원인 찾아줘"}
B = {"title": "릴리스 노트", "task": "v0.3 릴리스 노트 초안"}


class Parser(unittest.TestCase):
    def test_table(self):
        two = f"두 갈래로 나눠서 진행할게요.\n\n{block(A)}\n\n{block(B)}"
        cases = [
            # (name, text, thread blocks kept, route)
            ("plain block ok", f"나눌게요.\n\n{block(A)}", [A], None),
            ("inline one-line block ok", f'나눌게요.\n```omher-thread {json.dumps(A, ensure_ascii=False)}```', [A], None),
            ("two blocks", two, [A, B], None),
            ("inside a > quote ignored", "예시:\n> ```omher-thread\n> " + json.dumps(A) + "\n> ```", [], None),
            ("inside a ```md fence ignored", f"형식은 이래요:\n````md\n{block(A)}\n````", [], None),
            ("inside a ~~~ fence ignored", f"~~~\n{block(A)}\n~~~", [], None),
            ("4 blocks -> 3", "\n".join(block({"title": f"t{n}", "task": "x"}) for n in range(4)),
             [{"title": f"t{n}", "task": "x"} for n in range(3)], None),
            ("bad JSON dropped", "```omher-thread\n{\"title\": \"a\", \"task\": }\n```", [], None),
            ("extra key dropped", block({**A, "cwd": "/tmp"}), [], None),
            ("missing key dropped", block({"title": "a"}), [], None),
            ("non-string dropped", block({"title": "a", "task": 3}), [], None),
            ("long title dropped", block({"title": "x" * 81, "task": "y"}), [], None),
            ("80-char title ok", block({"title": "x" * 80, "task": "y"}), [{"title": "x" * 80, "task": "y"}], None),
            ("long task dropped", block({"title": "a", "task": "y" * 4001}), [], None),
            ("unclosed fence dropped", "```omher-thread\n" + json.dumps(A), [], None),
            ("route ok", "이건 그 스레드 이야기예요.\n" + block({"thread": "stored-th-1"}, "omher-thread-route"), [],
             {"thread": "stored-th-1"}),
            ("route extra key dropped", block({"thread": "x", "title": "y"}, "omher-thread-route"), [], None),
            ("second route ignored", block({"thread": "a"}, "omher-thread-route") + "\n" +
             block({"thread": "b"}, "omher-thread-route"), [], {"thread": "a"}),
            ("no block", "그냥 답이에요. `omher-thread` 라는 말만.", [], None),
            # the JSON on the opening fence line, closed on the next line (what the model writes under the hint)
            ("open-line block ok", f"나눌게요.\n\n{open_line(A)}\n\n{open_line(B)}\n\n한 줄 메모.", [A, B], None),
            ("open-line block with `code` in its task ok", open_line({"title": "t", "task": "run `git log`"}),
             [{"title": "t", "task": "run `git log`"}], None),
            ("open-line route ok", open_line({"thread": "stored-th-1"}, "omher-thread-route") + "\n이어서 할게요.", [],
             {"thread": "stored-th-1"}),
            ("open-line block inside a > quote ignored", "> " + open_line(A).replace("\n", "\n> "), [], None),
            ("open-line block inside a ````md fence ignored", f"````md\n{open_line(A)}\n````", [], None),
            ("open-line block inside a ~~~ fence ignored", f"~~~\n{open_line(A)}\n~~~", [], None),
            ("open-line block with a body ignored", f"```omher-thread {json.dumps(A)}\nmore\n```", [], None),
            ("open-line block never closed dropped", f"```omher-thread {json.dumps(A)}", [], None),
            ("open-line block extra key dropped", open_line({**A, "cwd": "/tmp"}), [], None),
            ("open-line long title dropped", open_line({"title": "x" * 81, "task": "y"}), [], None),
        ]
        for name, text, want, route in cases:
            with self.subTest(name):
                got, r, _ = ob.split_blocks(text)
                self.assertEqual(got, want)
                self.assertEqual(r, route)

    def test_blocks_are_hidden_from_the_shown_text(self):
        _, _, shown = ob.split_blocks(f"두 갈래로 나눠서 진행할게요.\n\n{block(A)}\n\n{block(B)}")
        self.assertEqual(shown, "두 갈래로 나눠서 진행할게요.")
        # a quoted / fenced example stays as written
        text = f"형식은 이래요:\n````md\n{block(A)}\n````"
        self.assertEqual(ob.split_blocks(text)[2], text)
        # an invalid block is not acted on, and its machine syntax is not shown either
        bad = block({**A, "cwd": "/tmp"})
        self.assertEqual(ob.split_blocks(bad)[2], "")
        # the open-line layout is hidden too; quoted it stays as written
        _, _, shown = ob.split_blocks(f"나눌게요.\n\n{open_line(A)}\n\n{open_line(B)}\n\n한 줄 메모.")
        self.assertEqual(shown, "나눌게요.\n\n한 줄 메모.")
        quoted = "> " + open_line(A).replace("\n", "\n> ")
        self.assertEqual(ob.split_blocks(quoted)[2], quoted)

    def test_hint_size_and_strip(self):
        rows = [{"thread": f"20261115_2{n:05d}_{'abcdef01'}", "title": "긴 스레드 제목 " * 6, "last": "마지막 줄 " * 30}
                for n in range(12)]
        note = ob.thread_hint(rows)
        self.assertLess(len(note), ob.THREAD_HINT_MAX)
        self.assertLess(len(ob.thread_hint([])), ob.THREAD_HINT_MAX)
        self.assertLessEqual(note.count("\n"), 8 + 3)  # head + at most 8 rows + two rules
        self.assertIn("```omher-thread {", note)
        self.assertIn("```omher-thread-route {", note)
        self.assertIn("written on one line as ```omher-thread {", ob.THREAD_HINT_SPLIT)
        self.assertIn("written on one line", ob.THREAD_HINT_ROUTE)
        self.assertLess(len(ob.thread_hint(rows[:1])), 700)  # one open thread, full last line: ~640
        sent = f"이거 해줘\n\n{note}"
        self.assertEqual(ob.split_thread_hint(sent), "이거 해줘")
        rows_out = ob.chat_messages([{"role": "user", "text": sent, "row_id": 1}])
        self.assertEqual(rows_out[0]["text"], "이거 해줘")
        # a person who types the head themselves keeps their words
        own = "[omher] Open threads: what is this?"
        self.assertEqual(ob.split_thread_hint(own), own)

    def test_reopened_main_chat_shows_answers_without_blocks(self):
        rows = [{"role": "user", "text": "둘 다 해줘", "row_id": 1},
                {"role": "assistant", "text": f"나눌게요.\n\n{block(A)}", "row_id": 2}]
        self.assertEqual(ob.chat_messages(rows, main=True)[1]["text"], "나눌게요.")
        self.assertIn("omher-thread", ob.chat_messages(rows)[1]["text"])  # a thread's own answer is left as is


class Effects(BridgeCase):
    async def opened(self, env):
        s = await self.open(env)
        ok(await s.req("chat.open", bot="kami"))
        return s

    async def test_no_note_until_the_app_shows_threads(self):
        async with ThreadEnv() as env:
            s = await self.opened(env)
            ok(await s.req("chat.send", bot="kami", text="hello"))
            self.assertEqual(env.clients["kami"].find("prompt.submit")[-1]["text"], "hello")
            ok(await s.req("thread.list", bot="kami"))
            ok(await s.req("chat.send", bot="kami", text="hello"))
            sent = env.clients["kami"].find("prompt.submit")[-1]["text"]
            self.assertTrue(sent.startswith("hello\n\n[omher] Open threads: none."), sent)
            self.assertEqual(ob.split_thread_hint(sent), "hello")

    async def test_note_lists_open_threads_and_never_rides_a_thread_turn(self):
        async with ThreadEnv(HermesStore()) as env:
            s = await self.opened(env)
            ok(await s.req("thread.list", bot="kami"))
            tid = ok(await s.req("thread.create", bot="kami", title="Nightly 빌드"))["thread"]
            ok(await s.req("chat.send", bot="kami", session=tid, text="원인 찾아줘"))
            c = env.clients["kami"]
            self.assertEqual(c.find("prompt.submit")[-1]["text"], "원인 찾아줘")  # a thread turn: no note
            c.push("message.start", sid=f"rt-{tid}")
            c.push("message.complete", {"text": "원인은 캐시예요.\n\n고쳤어요: CI 캐시 키 갱신", "status": "complete"}, sid=f"rt-{tid}")
            await s.until(lambda ev: any(e["event"] == "turn.end" and e.get("session") == tid for e in ev))
            ok(await s.req("chat.send", bot="kami", text="상태 어때?"))
            sent = c.find("prompt.submit")[-1]["text"]
            self.assertIn(f'{tid} "Nightly 빌드" — 고쳤어요: CI 캐시 키 갱신', sent)
            self.assertLess(len(sent) - len("상태 어때?\n\n"), ob.THREAD_HINT_MAX)

    async def test_two_blocks_make_two_threads_with_their_tasks(self):
        async with ThreadEnv(HermesStore()) as env:
            s = await self.opened(env)
            ok(await s.req("thread.list", bot="kami"))
            c = env.clients["kami"]
            c.push("message.start")
            c.push("message.complete", {"text": f"두 갈래로 나눠서 진행할게요.\n\n{block(A)}\n\n{block(B)}",
                                        "status": "complete", "persisted_turn": {"final_assistant_row_id": 77}})
            await s.until(lambda ev: sum(e["event"] == "thread.split" for e in ev) == 2
                          and len(c.find("prompt.submit")) == 2)
            msg = next(e for e in s.events if e["event"] == "message")
            self.assertEqual(msg["text"], "두 갈래로 나눠서 진행할게요.")  # no raw block in the bubble
            splits = [e for e in s.events if e["event"] == "thread.split"]
            self.assertEqual([e["title"] for e in splits], ["OG 502 원인", "릴리스 노트"])
            self.assertEqual({e["message"] for e in splits}, {"77"})
            subs = c.find("prompt.submit")
            self.assertEqual([x["session_id"] for x in subs], [f"rt-{e['thread']}" for e in splits])
            self.assertEqual([x["text"] for x in subs], [A["task"], B["task"]])  # the task, without any note
            creates = [x for x in c.find("session.create") if x["title"].startswith(ob.THREAD_PREFIX)]
            self.assertEqual([env.store.rows[e["thread"]]["title"] for e in splits], ["omher · OG 502 원인", "omher · 릴리스 노트"])
            self.assertEqual(len(creates), 2)
            self.assertTrue(all(x.get("request_id", "").startswith("omher-thread:kami:split-") for x in creates))
            listed = ok(await s.req("thread.list", bot="kami"))["threads"]
            self.assertEqual(len(listed), 2)

    async def test_open_line_blocks_make_two_threads_too(self):
        """The real model's layout (JSON on the opening fence line, close on the next) opens threads the same way."""
        async with ThreadEnv(HermesStore()) as env:
            s = await self.opened(env)
            ok(await s.req("thread.list", bot="kami"))
            c = env.clients["kami"]
            c.push("message.start")
            c.push("message.complete", {"text": f"{open_line(A)}\n\n{open_line(B)}\n\n두 작업이라 나눴어요.",
                                        "status": "complete", "persisted_turn": {"final_assistant_row_id": 78}})
            await s.until(lambda ev: sum(e["event"] == "thread.split" for e in ev) == 2
                          and len(c.find("prompt.submit")) == 2)
            msg = next(e for e in s.events if e["event"] == "message")
            self.assertEqual(msg["text"], "두 작업이라 나눴어요.")
            self.assertEqual([x["text"] for x in c.find("prompt.submit")], [A["task"], B["task"]])

    async def test_four_blocks_make_three_and_a_thread_answer_makes_none(self):
        async with ThreadEnv(HermesStore()) as env:
            s = await self.opened(env)
            c = env.clients["kami"]
            text = "\n".join(block({"title": f"part {n}", "task": "do it"}) for n in range(4))
            c.push("message.start")
            c.push("message.complete", {"text": text, "status": "complete"})
            await s.until(lambda ev: sum(e["event"] == "thread.split" for e in ev) == 3)
            await s.until(lambda ev: any(e["event"] == "turn.end" for e in ev))
            n = len(c.find("session.create"))
            # a thread's own answer with a block: never parsed (main chat only)
            tid = next(e for e in s.events if e["event"] == "thread.split")["thread"]
            c.push("message.start", sid=f"rt-{tid}")
            c.push("message.complete", {"text": block(A), "status": "complete"}, sid=f"rt-{tid}")
            await s.until(lambda ev: any(e["event"] == "message" and e.get("session") == tid for e in ev))
            self.assertEqual(len(c.find("session.create")), n)
            self.assertEqual(sum(e["event"] == "thread.split" for e in s.events), 3)

    async def test_block_in_a_tool_result_or_an_interrupted_turn_is_ignored(self):
        async with ThreadEnv(HermesStore()) as env:
            s = await self.opened(env)
            c = env.clients["kami"]
            n = len(c.find("session.create"))
            c.push("message.start")
            c.push("tool.start", {"tool_id": "t1", "name": "read_file", "context": "README.md"})
            c.push("tool.complete", {"tool_id": "t1", "name": "read_file", "result": block(A), "summary": block(A)})
            c.push("tool.start", {"tool_id": "t2", "name": "read_file", "context": "NOTES.md"})
            c.push("tool.complete", {"tool_id": "t2", "name": "read_file", "result": open_line(A),
                                     "summary": open_line(A)})
            c.push("message.complete", {"text": "README를 읽었어요.", "status": "complete"})
            c.push("message.start")
            c.push("message.complete", {"text": block(B), "status": "interrupted"})
            await s.until(lambda ev: sum(e["event"] == "turn.end" for e in ev) == 2)
            self.assertEqual(len(c.find("session.create")), n)
            self.assertNotIn("thread.split", s.kinds())

    async def test_route_to_an_open_thread_asks_and_never_creates(self):
        async with ThreadEnv(HermesStore()) as env:
            s = await self.opened(env)
            tid = ok(await s.req("thread.create", bot="kami", title="Nightly 빌드"))["thread"]
            c = env.clients["kami"]
            n = len(c.find("session.create"))
            c.push("message.start")
            c.push("message.complete", {"text": "이건 Nightly 빌드 스레드 이야기 같아요.\n" +
                                        block({"thread": tid}, "omher-thread-route"), "status": "complete"})
            await s.until(lambda ev: any(e["event"] == "thread.route" for e in ev))
            ask = next(e for e in s.events if e["event"] == "thread.route")
            self.assertEqual((ask["thread"], ask["title"]), (tid, "Nightly 빌드"))
            self.assertEqual(len(c.find("session.create")), n)  # never a thread
            self.assertEqual([x for x in c.find("prompt.submit")], [])  # nothing moved without the click
            msg = next(e for e in s.events if e["event"] == "message")
            self.assertEqual(msg["text"], "이건 Nightly 빌드 스레드 이야기 같아요.")

    async def test_route_to_an_unknown_id_or_the_main_chat_is_ignored(self):
        async with ThreadEnv(HermesStore()) as env:
            s = await self.opened(env)
            c = env.clients["kami"]
            n = len(c.find("session.create"))
            for target in ("stored-th-404", ob_main()):
                c.push("message.start")
                c.push("message.complete", {"text": "이어서요.\n" + block({"thread": target}, "omher-thread-route"),
                                            "status": "complete"})
            await s.until(lambda ev: sum(e["event"] == "turn.end" for e in ev) == 2)
            self.assertNotIn("thread.route", s.kinds())
            self.assertEqual(len(c.find("session.create")), n)
            self.assertEqual(c.find("prompt.submit"), [])


def ob_main() -> str:
    from test_bridge import MAIN_STORED
    return MAIN_STORED


if __name__ == "__main__":
    unittest.main()
