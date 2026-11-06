"""When a message reaches `dag-ulw`: one reading for the router and the in-Hermes route hint.

By name. People type the name with a space, either way round ("dag ulw", "ulw dag"), and in Korean with the
verb glued to it ("dag ulw해줘"). A message invokes the skill when the name opens the request (after a sigil,
``use``, ``run``, ``please`` or a polite ``can you``), when the request runs something with it ("refactor auth
with dag ulw"), or when a Korean run ending follows it ("결제 모듈 dag ulw로 고쳐줘"). A negated mention never does
("don't use dag ulw", "dag ulw 말고"), and neither does a question about the skill ("dag ulw는 뭐야?",
"dag ulw 설명해줘", "dag ulw 결과 알려줘", "how does dag-ulw handle repairs?"): those are answered, the
way a question about any other skill is, and so is one after the sigil ("/dag-ulw 이게 뭐야?"). A word for the
run in progress ("dag ulw stop", "dag ulw 취소", "dag ulw 상태 보여줘", "dag ulw 뭐 남았어?") never does either: it
points at that run's `omh_dag` cancel or status. A Korean stop noun
after other words ("dag ulw 주문 취소"), or an English stop word beside them ("dag ulw cancel order"), is neither a run
nor a cancel until the person says which. A complaint or a question after the bare name is answered too ("dag ulw
broke my build", "dag ulw 결제 api 뭐야"): `name_report_cues` reads it, for every skill's name.

By size. A request that says how the work splits or how wide it reaches (`work_has_several_parts`), does not ask
to be told how, and does not name ultrawork is big work for `dag-ulw`; the router reads it only on a route it
already gave `ultrawork`, and the route hint on its coding-delivery hint. Where no hint rule matched, the hint
reads only an outright split (`work_is_split`).

Callers pass the executable text, so a quoted, fenced or relayed mention never reaches these readers.
Stdlib only: the plugin bundle loads this file with Hermes' interpreter (#1623).
"""

from __future__ import annotations

from functools import lru_cache
import re
import unicodedata
from typing import Final

from . import skill_shortlist as _skill_shortlist
from .name_report_cues import COINED_NAMES, asks_after_the_name, asks_for_something, reports_on_the_name

DAG_ULW: Final = "dag-ulw"

_NAME: Final = r"(?:dag[\s_-]*(?:ulw|ultrawork)|(?:ulw|ultrawork)[\s_-]*dag)(?![a-z0-9_-])"
# A request put politely as a question ("can you dag ulw the migration?") still asks to run it.
_POLITE_OPENER: Final = r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)"
_LEAD: Final = re.compile(
    rf"^(?:(?:please|pls)\s+)?{_POLITE_OPENER}?(?:(?:use|run|start)\s+(?:omh\s+)?)?(?:\$|\./|/|@)?{_NAME}"
)
_WITH: Final = re.compile(rf"\b(?:with|via|using|through)\s+(?:the\s+)?{_NAME}")
# The name with a run ending right after it ("dag ulw해줘"), or the name as an instrument ("dag ulw로") and,
# within four words, a request ending ("dag ulw로 결제 모듈 고쳐줘").
_KOREAN_RUN: Final = re.compile(
    rf"{_NAME}\s*(?:해\s*줘|해\s*주세요|해\b|돌려|실행|진행|부탁)"
    rf"|{_NAME}\s*(?:으로|로)\s+(?:\S+\s+){{0,3}}\S*(?:줘|주세요)"
)
_NEGATED: Final = re.compile(
    rf"(?:\b(?:don'?t|do not|never|not|without|instead of|other than)\s+(?:use\s+|run\s+)?(?:the\s+)?{_NAME})"
    rf"|(?:\b(?:stop|quit)\s+(?:using|running)\s+(?:the\s+)?{_NAME})"
    rf"|(?:{_NAME}\s*(?:은|는|을|를)?\s*(?:말고|쓰지|하지\s*마|대신|아니))"
)
# A question about the skill, not a request to run it: a topic or subject particle on the name ("dag ulw는",
# "dag ulw가"); a word right after the name that asks about it (what it is, how it works, what it costs, its
# docs or result); an English verb that describes it ("dag ulw is broken"); or an English question that opens
# before the name, put politely or not ("can you explain dag ulw?"). A question mark anywhere at the end is read
# by `asks_about_dag_ulw` itself.
_ASKED_ABOUT: Final = re.compile(
    rf"{_NAME}\s*(?:은|는|이란|란|이|가)(?![가-힣])"
    rf"|{_NAME}\s*(?:설명|뭐|뭔|무엇|무슨|알려|결과|문서|사용법|어떻게|어때|쓰면|비용|원리|왜)"
    rf"|{_NAME}\s+(?:is|are|was|were|does|should|has|seems?|vs\.?|versus)\b"
    rf"|^{_POLITE_OPENER}?(?:how|what|why|when|where|who|which|is|are|does|should|tell\s+me|explain|describe)\b"
    rf"(?:\s+\S+){{0,6}}?\s+(?:the\s+)?(?:\$|/)?{_NAME}"
)
_POLITE_REQUEST: Final = re.compile(rf"^(?:(?:please|pls)\s+)?{_POLITE_OPENER}")
# The name with nothing before it, as a report or a question opens (`name_report_cues`).
_BARE_LEAD: Final = re.compile(rf"^{_NAME}")
# A polite question that weighs the run against another way asks about it, not for it ("can you dag ulw this or
# should I just fix it myself?", "could you dag ulw this, or is that overkill?", "would you dag ulw it, if you were
# me?"). An `or` between two targets weighs nothing ("can you dag ulw the auth or billing refactor?").
_OR_ANOTHER_WAY: Final = (
    r"\bor\s+(?:should|shall|is|are|would|will|could|can|do|does|just|not|maybe|keep|leave|skip|ultrawork|ulw)\b"
)
_WEIGHED: Final = re.compile(rf"{_NAME}.*(?:{_OR_ANOTHER_WAY}|아니면)|\bif\s+you\s+were\b")
# A word for the run a person already has, said to the name: stop or cancel it ("dag ulw stop", "dag ulw 멈춰",
# "dag ulw 돌린 거 취소해줘", "cancel dag ulw", "can you stop dag ulw"), or show how it stands ("dag ulw status",
# "dag ulw 상태 보여줘", "dag ulw 진행 상황"). The words must end the request, or be all it asks about, so a thing
# named for them stays work ("dag ulw add a cancel button", "dag ulw 결제 취소 기능 구현해줘",
# "dag ulw 상태 관리 모듈 리팩터링해줘").
_RUN_OBJECT: Final = r"(?:\s+(?:it|this|that|now|please|everything|all|the\s+(?:run|dag|graph|job)))*"
# Korean says a stop two ways. 멈춰, 그만 and 꺼 are a stop whatever comes before them. 취소, 중지, 중단, 정지 and 종료
# are nouns too, and after other words they can name the thing to stop as easily as the run ("dag ulw 주문 취소" is an
# order cancel as much as a cancel of the run). They stop the run with a verb ending, plain or polite, after up to
# three words ("dag ulw 주문 취소해줘", "dag ulw 취소해줘요", "dag ulw 취소 부탁해"); or alone, after stop adverbs or
# after words for the run itself, with a verb ending or a bare 요, 좀 or ㄱ ("dag ulw 취소요", "dag ulw 지금 바로 취소",
# "dag ulw 진행 중인 작업 취소", "dag ulw 그것도 취소"). After other words a bare 요, 좀 or ㄱ is no verb, so
# "dag ulw 주문 취소요" stays the noun phrase. The folded text is NFKC, which turns the jamo ㄱ into its conjoining
# form, so the pattern carries that form.
_KOREAN_STOP_NOUN: Final = r"(?:취소|중지|중단|정지|종료|스톱|스탑|멈춤)"
_KOREAN_VERB_TAIL: Final = (
    r"\s*(?:좀\s*)?(?:해\s*(?:줘|주세요|줄래|주라|봐|라|버려|줄\s*수\s*있(?:어|나|을까)|주시겠어|주실래|주실\s*수\s*있(?:나|을까))?"
    r"|하자|하세요|할게|할래|합니다|하고\s*싶어"
    r"|해야\s*(?:해|돼|겠어)|시켜\s*(?:줘|주세요)?|둬\s*(?:줘|주세요)?|부탁(?:해|드려|드립니다|합니다)?|줘|주세요|줄래)\s*요?"
)
_KOREAN_PARTICLE_TAIL: Final = rf"\s*(?:요|좀|{unicodedata.normalize('NFKC', 'ㄱ')}+)"
_KOREAN_RUN_MODIFIER: Final = (
    r"(?:현재|지금|이번|이전|방금|아까|다른|모든|전체|전부|모두|그|이|저|진행\s*중인|실행\s*중인|돌리던|돌리는|돌던|돌아가는"
    r"|돌린)"
)
_KOREAN_RUN_NOUN: Final = (
    r"(?:작업|실행|런|run|job|그것도|이것도|그거도|이거도|그거|이거|저거|거|것|전부|모두|다|전체)"
)
_KOREAN_STOP_ADVERB: Final = r"(?:바로|당장|즉시|일단|그냥|얼른|빨리|지금)"
# A stop said as the act of stopping, after the bare stop word or words for the run ("dag ulw 작업 취소 처리해줘",
# "dag ulw 런 중단 요청 보내줘", "dag ulw 취소 눌러줘"): a stop of the run, not work on one.
_KOREAN_STOP_ACT: Final = (
    rf"\s*(?:좀\s*)?(?:(?:처리|진행|요청|실행)(?:{_KOREAN_VERB_TAIL})?|(?:요청|명령)\s*(?:보내|내려)\s*(?:줘|주세요)"
    r"|(?:눌러|걸어)\s*(?:줘|주세요))\s*요?"
)
# The same act after other words, alone after the stop word or with the button it is pressed on ("dag ulw 결제 취소
# 처리해줘", "dag ulw 결제 작업 중단 걸어줘", "dag ulw 취소 버튼 눌러줘"): it names no work of its own, so the words
# before the stop word decide, as for a bare stop noun (owner decision O7).
_KOREAN_STOP_ACT_ALONE: Final = re.compile(rf"^{_KOREAN_STOP_ACT}(?:{_KOREAN_PARTICLE_TAIL})?\s*[.!?~]*$")
# The button a stop is pressed on is the stop's own ("dag ulw 취소 버튼 눌러줘", "dag ulw 취소 버튼 눌렀는데 계속
# 돌아가"), not work, unless other work words follow ("… 버튼 눌러도 안 멈추는 버그 고쳐줘").
_KOREAN_STOP_BUTTON: Final = re.compile(r"^\s*버튼\s*(?:을|를)?(?=\s*눌)")
_STOP: Final = re.compile(
    rf"{_NAME}[\s,:]*(?:please\s+)?(?:stop|cancel|abort|halt|kill){_RUN_OBJECT}\s*[.!?]*$"
    rf"|^(?:please\s+)?{_POLITE_OPENER}?(?:stop|cancel|abort|halt|kill)\s+(?:the\s+|this\s+|that\s+|my\s+)?"
    rf"(?:current\s+|running\s+)?(?:\$|/)?{_NAME}(?:\s+(?:run|job|graph))?(?:\s+(?:now|please))*\s*[.!?]*$"
    rf"|{_NAME}[\s,:]*(?!으?로\s)(?:의\s*)?(?:\S+\s+){{0,3}}?(?:멈춰(?:라)?|멈추(?:세요|자)?|그만(?:\s*(?:돌려|돌리자))?)"
    rf"(?:{_KOREAN_VERB_TAIL}|{_KOREAN_PARTICLE_TAIL})?\s*[.!?~]*$"
    rf"|{_NAME}[\s,:]*(?!으?로\s)(?:의\s*)?(?:\S+\s+){{0,3}}?\S*?{_KOREAN_STOP_NOUN}{_KOREAN_VERB_TAIL}\s*[.!?~]*$"
    rf"|{_NAME}[\s,:]*(?:의\s*)?(?:\S+\s+말고\s+)?(?:(?:{_KOREAN_RUN_MODIFIER}\s*){{0,2}}{_KOREAN_RUN_NOUN}\s*)?"
    rf"(?:{_KOREAN_STOP_ADVERB}\s*){{0,2}}"
    rf"(?:{_KOREAN_STOP_NOUN}(?:{_KOREAN_VERB_TAIL}|{_KOREAN_PARTICLE_TAIL}|{_KOREAN_STOP_ACT}(?:{_KOREAN_PARTICLE_TAIL})?)?"
    rf"|꺼\s*(?:줘|주세요|라)?\s*요?)\s*[.!?~]*$"
)
# Any other Korean stop word after the name is never a run (owner decision O7). The last stop word decides. With
# nothing after it that names work, it may stop the run or name the work, so it asks which ("dag ulw 주문 취소",
# "dag ulw 취소 요청", "dag ulw 결제 취소 기능 만드는 거 그만해줘"). The message is work instead when:
# - a work noun or verb follows it ("dag ulw 주문 취소 기능 만들어요", "dag ulw 결제 취소 이슈 해결해줘"), or a clause
#   after it makes the stop a condition of the work ("dag ulw 주문 취소 시 환불되게 해줘");
# - past the stop word's own ending, a request verb with its own stem ends the message ("dag ulw 결제 취소 내역
#   확인해줘", "dag ulw 종료 훅 등록해줘"), where a stop request leaves nothing but its ending ("… 작업 취소해줘");
# - a condition clause comes right before it ("dag ulw 결제 모듈 리팩터링하고 실패하면 중단해줘");
# - a work word is the object of 꺼줘 ("dag ulw 다크모드 꺼줘"), unless a word for the run is ("dag ulw 결제 모듈
#   작업 꺼줘").
# A how word after it asks about stopping, and so does a past or passive form ("dag ulw 취소됐어?", "dag ulw
# 멈췄어?") or 여부: those are answered (`asks_about_dag_ulw`).
_STOP_AFTER_NAME: Final = re.compile(
    rf"{_NAME}(?P<before>.*)(?P<stem>{_KOREAN_STOP_NOUN}|멈추|멈춰|멈출|멈췄|멈춘|그만(?!큼)|꺼\s*(?:줘|주세요|라))(?P<after>.*)$",
    re.DOTALL,
)
_KOREAN_WORK_WORD: Final = re.compile(
    r"기능|로직|버튼|화면|페이지|모듈|컴포넌트|서비스|엔드포인트|핸들러|함수|메서드|클래스|코드|처리|구현|만들|추가|리팩터"
    r"|고쳐|고치|수정|정리|작성|개발|테스트|변경|개선|설계|연동|적용|배포|마이그레이션|흐름|플로우|정책|조건|이벤트|알림|넣"
    r"|붙여|바꿔|분리|나눠|해결|잡아|버그|이슈|디버깅|디버그|최적화|캐싱|캐시|검토|스펙|문서|써\s*(?:줘|주세요)|정의|쿼리"
    r"|스키마|설정|중단점|모드|로그|\b(?:api|ui|button|page|feature|logic|flow|handler|endpoint|dto|tests?)\b"
)
_KOREAN_WORK_CONDITION: Final = re.compile(r"^\s*시\s|[할될]\s*때|[하되]면(?!\s*(?:돼|된다|되잖아))|\S(?:되게|되도록|하도록)")
_KOREAN_CONDITION_BEFORE: Final = re.compile(r"(?:[하되]면|[할될]\s*때|다가|\s시)\s*$")
_KOREAN_RUN_OBJECT_BEFORE: Final = re.compile(r"(?:작업|거|것|run|job|그거|이거|저거)\s*$")
_KOREAN_STOP_ENDING: Final = re.compile(rf"(?:{_KOREAN_VERB_TAIL}|{_KOREAN_PARTICLE_TAIL})")
_KOREAN_REQUEST_VERB: Final = re.compile(r"(?P<stem>\S*?)(?:해)?(?:줘|주세요|줄래|주라)요?|(?P<stem2>\S*?)(?:해요|하자|해라|하세요)")
_KOREAN_NOT_A_VERB_STEM: Final = frozenset(
    {"", "해", "하", "좀", "부탁", "다시", "빨리", "지금", "그냥", "일단", "바로", "얼른", "당장", "꼭", "제발", "어서",
     "게", "되게", "하게", "도록", "되도록"}
)
_KOREAN_HOW: Final = re.compile(r"어떻게|방법|뭐|왜|가능|(?:^|[할될])\s*수\s*있|되나|될까|돼\s*요?\s*[?？]")
_KOREAN_PAST: Final = re.compile(r"^\s*(?:완료\s*)?(?:됐|되었|됨|된|했|하였|한\s*거|뒀|눌렀)|여부")
# A sigil before a question is a question, not a command ("/dag-ulw what is it?", "/dag-ulw how do I cancel it?"),
# unless a request for work follows it ("/dag-ulw explain the plan, then run the migration", "/dag-ulw is the auth
# refactor done? if not, finish it").
_SIGIL_QUESTION: Final = re.compile(
    r"^(?!.*(?:\b(?:then|and)\s+(?:run|do|start|finish|implement|fix|migrate|build)\b|\bif\s+not\b"
    r"|[,?!.]\s*(?:finish|run|do|fix|start|implement)\b))"
    rf"(?:\$|\./|/){_NAME}[\s,:]+(?:how|what|why|when|where|who|which|is|are|does|do\s+i|can\s+i|should|tell\s+me"
    r"|explain|describe)\b",
    re.DOTALL,
)
# A stop the person already made, said while the run still goes ("dag ulw 취소했는데 계속 돌아가", "dag ulw 취소
# 눌렀는데 계속 돌아가"): stop it again.
_KOREAN_PRESSED: Final = re.compile(r"\s*눌렀")
_REQUEST_BEFORE_STOP: Final = re.compile(r"(?:^|\s)(?:다시\s*)?(?!해|하|좀)\S+?(?:해)?(?:줘|주세요)(?=[\s,.]|$)|(?:다시|이어서|계속|마저)\s*해\s*(?:줘|주세요)")
_STATUS_REQUEST: Final = re.compile(r"(?:확인|체크|봐|보여|알려|살펴|점검|조회)\S*?(?:해)?(?:줘|주세요)")
_KOREAN_STILL_RUNNING: Final = re.compile(r"(?:계속|아직|여전히)\s*(?:돌아|돌고|실행|진행|안\s*멈)|안\s*(?:멈춰|멈추|꺼져|꺼지)")
# A stop of the run right after the name, then more work ("dag ulw 지금 거 취소하고 결제 모듈부터 다시 해줘",
# "dag ulw 취소하고 다시 처음부터 구현해줘"): stop and restart, or work on a cancel, so it asks before either.
_STOP_THEN_WORK: Final = re.compile(
    rf"{_NAME}[\s,:]*(?:의\s*)?(?:(?:{_KOREAN_RUN_MODIFIER}\s*){{0,2}}{_KOREAN_RUN_NOUN}\s*)?"
    rf"(?:{_KOREAN_STOP_ADVERB}\s*){{0,2}}(?:{_KOREAN_STOP_NOUN}|멈추|그만)\s*(?:하|시키)?고(?:서)?\s"
)
# An English stop word with other words after the name, none of them the run's own ("dag ulw cancel order", "dag ulw
# order cancel", "dag ulw cancel the migration"): like a Korean stop noun after other words, it may stop the run or
# name the work, so it asks which (owner decision O7). A work word makes it work ("dag ulw add a cancel button",
# "dag ulw cancel order flow", "dag ulw implement order cancel").
_EN_STOP_WORD: Final = r"(?:stop|cancel|abort|halt|kill)"
_EN_STOP_AFTER_NAME: Final = re.compile(
    rf"^{_NAME}[\s,:]+(?:(?:\S+\s+){{1,3}}{_EN_STOP_WORD}|{_EN_STOP_WORD}\s+\S+(?:\s+\S+){{0,3}})\s*[.!?]*$"
)
_EN_WORK_WORD: Final = re.compile(
    r"\b(?:add|implement|build|create|make|write|fix|refactor|support|design|migrate|handle|handling|test|tests"
    r"|button|feature|flow|endpoint|api|handler|logic|page|ui|function|method|module|service|bug|issue|dto|schema"
    r"|query|filter|words?|tokens?|signals?|conditions?|switch(?:es)?|flags?|toggles?)\b"
)
_STATUS: Final = re.compile(
    rf"{_NAME}[\s,:]*(?:status|progress|logs?)(?:\s+(?:please|now|of\s+the\s+(?:run|dag|graph)))*\s*[.!?]*$"
    rf"|{_NAME}[\s,:]*(?:의\s*)?(?:상태|진행\s*상황|진행\s*상태|진행도|로그)\s*(?:좀\s*)?"
    rf"(?:보여|알려|확인|어때|어떻게|는\s*[?？]|[?？]|$)"
    # What is left of the run is how it stands ("dag ulw 뭐 남았어?", "dag ulw what's left?").
    rf"|{_NAME}[\s,:]*(?:뭐|얼마나|몇\s*개)\s*(?:더\s*)?남았(?:어|나|니|어요|나요|습니까)?\s*[.!?？]*$"
    rf"|{_NAME}[\s,:]*(?:what'?s|what\s+is|how\s+much\s+is)\s+(?:still\s+)?left\s*[.!?]*$"
)


# Words said to a run, read on their own, after any skill's name: a stop with nothing but the run as its object, and
# a request to see how the run stands. English, Korean, Japanese and Chinese; Japanese and Chinese have a short closed
# list, since no trigger pack carries a stop or status word. A stop word with a task object is work ("kill the zombie
# processes", "로그 폭주 멈춰줘", "abort the rebase"). After an invoked skill the run may also be named by the skill's
# own words (`_run_stop_alone`).
def _run_stop_source(names: str = "", nouns: str = "") -> str:
    """`_RUN_STOP_ALONE`'s pattern, with ``names`` (the invoked skill's names, said bare: "stop ulw-loop") and
    ``nouns`` (the words for its own run, which a determiner may come before: "stop the loop", "stop debugging",
    "리뷰 취소") as alternations that may also be the stop's object."""
    objects = [r"it|this|that|now|please|everything|all|the\s+(?:run|dag|graph|job)"]
    korean_nouns = [_KOREAN_RUN_NOUN]
    own = "|".join(words for words in (names, nouns) if words)
    if names:
        objects.append(rf"(?:{names})(?:\s+(?:run|job|session))?")
        korean_nouns.append(names)
    if nouns:
        objects.append(rf"(?:(?:the|this|that|my|your|current|running)\s+)*(?:{nouns})(?:\s+(?:run|job|session))?")
        korean_nouns.append(nouns)
    run_object = rf"(?:\s+(?:{'|'.join(objects)}))*"
    run_noun = rf"(?:{'|'.join(korean_nouns)})"
    # The skill's own run in Japanese and Chinese, before or after the stop ("ループを止めて", "停止循环", "计划取消").
    ja_noun = rf"作業|実行|これ|それ{'|' + own if own else ''}"
    zh_after = rf"运行|执行|任务|吧{'|' + own if own else ''}"
    zh_before = rf"|^(?:{own})(?:停止|取消|中止)吧?[。.!！]*$" if own else ""
    korean_run_phrase = (
        rf"(?:(?:{_KOREAN_RUN_MODIFIER}\s*){{0,2}}{run_noun}\s*(?:을|를|은|는|도)?\s*)?(?:{_KOREAN_STOP_ADVERB}\s*){{0,2}}"
    )
    return (
        rf"^(?:please\s+)?(?:stop|cancel|abort|halt|kill){run_object}\s*[.!?]*$"
        rf"|^{korean_run_phrase}"
        rf"(?:{_KOREAN_STOP_NOUN}(?:{_KOREAN_VERB_TAIL}|{_KOREAN_PARTICLE_TAIL}|{_KOREAN_STOP_ACT}(?:{_KOREAN_PARTICLE_TAIL})?)?"
        rf"|(?:멈춰(?:라)?|멈추(?:세요|자)?|그만(?:\s*(?:돌려|돌리자))?)(?:{_KOREAN_VERB_TAIL}|{_KOREAN_PARTICLE_TAIL})?"
        rf"|꺼\s*(?:줘|주세요|라)?\s*요?)\s*[.!?~]*$"
        rf"|^(?:(?:{ja_noun})を?)?(?:停止|中止|キャンセル)(?:して)?(?:ください)?[。.!！]*$"
        rf"|^(?:(?:{ja_noun})を)?(?:止めて|やめて)(?:ください)?[。.!！]*$"
        rf"|^(?:请)?(?:停止|取消|停下|中止)(?:{zh_after})?[。.!！]*${zh_before}"
        r"|^(?:别做了|不要做了|算了|停一下)吧?[。.!！]*$"
    )


_RUN_STOP_ALONE: Final = re.compile(_run_stop_source())


def _alternation(words: tuple[str, ...]) -> str:
    return "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True))


@lru_cache(maxsize=256)
def _run_stop_alone(names: tuple[str, ...], nouns: tuple[str, ...]) -> re.Pattern[str]:
    if not names and not nouns:
        return _RUN_STOP_ALONE
    return re.compile(_run_stop_source(_alternation(names), _alternation(nouns)))


_STOP_WORD: Final = re.compile(r"stop|cancel|abort|halt|kill|멈춰|그만|그만해|취소|중단|중지|정지")
# A Korean stop said as a verb, then why ("그만해 비싸", "멈춰 너무 오래 걸려"), as "stop, too expensive" says it with a
# comma. A bare stop noun is not a verb: after "취소" the words may be its object ("취소 버튼"). The why closes on a
# predicate: a noun after the stop is its object ("취소해 주문", "cancel the order"), and so is a why that names work or
# asks how or why (`stops_the_run`). The stop is a few words at most (`_KOREAN_STOP_WORDS_MAX`).
_KOREAN_STOP_VERB_END: Final = re.compile(
    rf"(?:(?:멈춰(?:라)?|멈추(?:세요|자))(?:{_KOREAN_VERB_TAIL})?|(?:그만|{_KOREAN_STOP_NOUN})(?:{_KOREAN_VERB_TAIL}))$"
)
_KOREAN_STOP_WORDS_MAX: Final = 6
# A why after a Korean stop verb is a reason when it closes on a predicate ending ("필요 없어", "내가 할게", "이거
# 아니야", "지금 회의 중"), reads as a report on the run (`reports_on_the_name`: "비싸", "너무 오래 걸려"), or is only
# fillers and stop words ("일단", "잠깐만", "멈춰 멈춰 제발"). A noun is the stop's object, so a loanword that closes
# on a vowel is too ("취소해 주문", "멈춰 서버").
_KOREAN_REASON_END: Final = re.compile(
    r"(?:[어아여해워야냐요다네게걸까래대데든군음함됨임듯]|아니라고|아님|중)$"
)
# A noun that closes like a reason: a loanword ("플레이어", "하드웨어", "리뷰어") or a lone counter or quantifier ("서버 두
# 대", "주문 다"), the stop's object.
_KOREAN_NOUN_LIKE_A_REASON: Final = re.compile(r"(?:^|\s)(?:다|대)$|(?:레이어|웨어|뷰어)$")


def _ends_in_a_past(word: str) -> bool:
    """Whether a Korean word ends in a past tense, a syllable closing on ㅆ then 어 or 아 ("보냈어", "됐어")."""
    if len(word) < 2:
        return False
    code = ord(word[-2]) - 0xAC00
    return word[-1] in "어아" and 0 <= code < 11172 and code % 28 == 20


_KOREAN_FILLER_REASON: Final = re.compile(
    r"^(?:(?:일단|잠깐만?|제발|좀|그냥|지금|빨리|당장|얼른|바로|멈춰|그만|그만해|취소|중단)\s*)+$"
)
# A word that only answers or interrupts before the stop ("no stop", "no, stop", "잠깐 멈춰").
_INTERJECTION: Final = re.compile(r"^(?:no|nope|wait|ok|okay|아니|아니야|잠깐|야)(?:\s*[,!.]+\s*|\s+)(?=\S)")
# What the skill is, in Japanese and Chinese, which `asks_after_the_name` does not read.
_JA_ZH_META: Final = re.compile(
    r"^(?:何これ|これ(?:は)?何(?:ですか)?|使い方(?:は)?|どうやって使う(?:の)?|(?:这|这个)是什么|是什么|怎么用)[?？。]*$"
)
_RUN_STATUS: Final = re.compile(
    r"^(?:(?:please\s+)?show\s+(?:me\s+)?(?:the\s+)?)?(?:status|progress|logs?)"
    r"(?:\s+(?:please|now|of\s+the\s+(?:run|dag|graph|job)))*\s*[.!?]*$"
    r"|^(?:please\s+)?show\s+(?:me\s+)?(?:the\s+)?(?:run|dag|graph|job)\s*[.!?]*$"
    r"|^(?:is\s+it|is\s+the\s+(?:run|job)|are\s+we)\s+(?:still\s+)?(?:running|done|finished|stuck)\s*\?*$"
    r"|^(?:still\s+)?(?:running|done|finished|stuck)\s*\?+$"
    r"|^(?:what'?s|what\s+is|how\s+much\s+is)\s+(?:still\s+)?left\s*[.!?]*$"
    r"|^how\s+(?:much|many)\s+(?:\S+\s+){0,2}(?:is|are)\s+(?:done|left|remaining|finished)\s*\?*$"
    r"|^(?:지금\s*)?(?:상태|진행\s*상황|진행\s*상태|진행도|로그)\s*(?:좀\s*)?"
    r"(?:(?:보여|알려|확인)\S*|어때\S*|어떻게\s*돼\S*|는\s*[?？])?\s*[.!?？]*$"
    r"|^(?:뭐|얼마나|몇\s*개)\s*(?:더\s*)?남았(?:어|나|니|어요|나요|습니까)?\s*[.!?？]*$"
    r"|^(?:다\s*)?(?:끝났|돌아가고\s*있|진행\s*중이)(?:어|나|니|어요|나요|습니까)?\s*[?？]\s*$"
    r"|^어디까지\s*(?:됐|했|왔)\S*\s*[?？]*$"
    r"|^(?:今の)?(?:状態|進捗|進行状況)(?:は|を)?(?:どう|教えて|見せて)?(?:ですか|ください)?[?？。]*$"
    r"|^(?:当前)?(?:状态|进度|进展)(?:怎么样|如何)?[?？。]*$"
)


def _folded(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


def stops_the_run(rest: str, *, names: tuple[str, ...] = (), nouns: tuple[str, ...] = ()) -> bool:
    """Whether ``rest``, the words after a skill's name, stop its run and name no task: a stop word alone, said twice,
    or with only the run as its object ("stop", "멈춰 멈춰", "cancel the run", "이거 취소", "작업 중단해줘", "실행 중인
    거 멈춰줘", "停止", "止めて", "取消", "别做了"), then at most a clause that asks for nothing ("stop, too expensive",
    "그만해 비싸"). After an invoked skill the run may be named by the skill's ``names``, said bare ("stop ulw-loop"),
    or by the ``nouns`` for its own run ("stop the loop", "stop debugging", "리뷰 취소"). A past or a question about
    stopping is no stop ("취소됐어?")."""
    folded = _INTERJECTION.sub("", _folded(rest).strip(" ,:"), count=1)
    parts = re.split(r"\s*[,;.!~]+\s*", folded, maxsplit=1)
    first, after = parts[0], parts[1] if len(parts) > 1 else ""
    if not first or (after and asks_for_something(", " + after)):
        return False
    if all(_STOP_WORD.fullmatch(word) for word in first.split()):
        return True
    alone = _run_stop_alone(names, nouns)
    if alone.match(first):
        return True
    words = first.split()
    for cut in range(1, min(len(words), _KOREAN_STOP_WORDS_MAX + 1)):
        if not _KOREAN_STOP_VERB_END.search(" ".join(words[max(0, cut - 2) : cut])):  # "그만 해줘"
            continue
        stop, why = " ".join(words[:cut]), " ".join(words[cut:])
        if alone.match(stop):
            # Not a why that asks how or why, which asks about stopping ("취소해줘 왜 안 돼": `_asks_about_stopping`).
            reason = why.rstrip(".!?~ ")
            return bool(
                _KOREAN_FILLER_REASON.match(reason)
                or (_KOREAN_REASON_END.search(reason) and not _KOREAN_NOUN_LIKE_A_REASON.search(reason))
                or _ends_in_a_past(reason)
                or reports_on_the_name(reason)
            ) and not (
                asks_for_something(", " + why) or _KOREAN_WORK_WORD.search(why) or _KOREAN_HOW.search(why)
            )
    return False


def ja_zh_asks_what_it_is(rest: str) -> bool:
    """Whether ``rest`` asks, in Japanese or Chinese, what the skill is or how to use it ("何これ", "这是什么")."""
    return bool(_JA_ZH_META.match(_folded(rest).strip(" ,:")))


def asks_how_the_run_stands(rest: str) -> bool:
    """Whether ``rest``, the words after a skill's name, ask to see how its run stands ("status", "show status", "show
    me the run", "is it running?", "what's left?", "상태 보여줘", "뭐 남았어?", "끝났어?", "状態", "状态")."""
    return bool(_RUN_STATUS.match(_folded(rest).strip(" ,:")))


def dag_ulw_control(text: str) -> str:
    """``cancel`` or ``status`` when ``text`` says that word to dag-ulw about the run in progress,
    ``cancel_or_run`` when another Korean stop word follows the name with no work after it (`_STOP_AFTER_NAME`), an
    English stop word comes with other words and no work (`_EN_STOP_AFTER_NAME`), or a stop of the run is followed
    by more work (`_STOP_THEN_WORK`), else "". After the sigil the same words read the same ("/dag-ulw cancel order"
    asks, as "dag ulw cancel order" does)."""
    folded = _folded(text)
    if _SIGIL_LEAD.match(folded):
        folded = folded.lstrip("$./")
        name = _BARE_LEAD.match(folded)
        stacked = _STACKED_SIGILS.match(folded[name.end() :]) if name else None
        if name and stacked:  # "/dag-ulw /ulw-plan 상태 보여줘": the words after the stacked skills
            folded = folded[: name.end()] + folded[name.end() + stacked.end() :]
    if _STOP.search(folded):
        return "cancel"
    first = re.match(r"^(.*?)\s*[,;.!?~]+\s*(\S.*)$", folded)
    if first and _STOP.search(first.group(1)) and not asks_for_something(", " + first.group(2)):
        return "cancel"  # "dag ulw stop, too expensive": a stop, then why
    if _STATUS.search(folded):
        return "status"
    name = _BARE_LEAD.match(folded)
    if name and stops_the_run(folded[name.end() :]):
        return "cancel"  # "dag ulw 停止", "dag ulw 止めて"
    if name and asks_how_the_run_stands(folded[name.end() :]):
        return "status"  # "dag ulw show status", "dag ulw show me the run", "dag ulw 状态"
    if _STOP_THEN_WORK.search(folded):
        return "cancel_or_run"
    if _EN_STOP_AFTER_NAME.match(folded) and not _EN_WORK_WORD.search(folded):
        return "cancel_or_run"
    stop = _STOP_AFTER_NAME.search(folded)
    if not stop or _stop_names_work(stop):
        return ""
    after = _after_the_stop(stop)
    if (_KOREAN_PAST.search(after) or _KOREAN_PRESSED.match(after)) and _KOREAN_STILL_RUNNING.search(after):
        return "cancel"
    return "" if _asks_about_stopping(stop) else "cancel_or_run"


def _ends_in_its_own_request(after: str) -> bool:
    """Whether, past the stop word's own ending, ``after`` ends in a request verb with its own stem."""
    ending = _KOREAN_STOP_ENDING.match(after)
    words = after[ending.end() if ending else 0 :].strip(" .!?~").split()
    verb = _KOREAN_REQUEST_VERB.fullmatch(words[-1]) if words else None
    if not verb:
        return False
    stem = verb.group("stem") if verb.group("stem") is not None else verb.group("stem2")
    if stem in ("", "해", "하") and len(words) > 1:
        stem = words[-2]
    return stem not in _KOREAN_NOT_A_VERB_STEM


def _after_the_stop(stop: re.Match[str]) -> str:
    """The words after the last stop word, without the button it is pressed on (`_KOREAN_STOP_BUTTON`)."""
    return _KOREAN_STOP_BUTTON.sub("", stop.group("after"), count=1)


def _stop_names_work(stop: re.Match[str]) -> bool:
    """Whether the words around the last stop word (`_STOP_AFTER_NAME`) make the message work, not a stop."""
    before, stem = stop.group("before", "stem")
    after = _after_the_stop(stop)
    if stem.startswith("꺼"):
        return bool(_KOREAN_WORK_WORD.search(before)) and not _KOREAN_RUN_OBJECT_BEFORE.search(before)
    if _KOREAN_STOP_ACT_ALONE.match(after):
        return False  # "dag ulw 결제 취소 처리해줘": the act of stopping, after words that may name the work
    if _KOREAN_WORK_WORD.search(after):
        return True
    if _KOREAN_HOW.search(after):
        return False  # a question about stopping (`_asks_about_stopping`), even after …하면 ("중단하면 어떻게 돼")
    if _KOREAN_WORK_CONDITION.search(after) or _KOREAN_CONDITION_BEFORE.search(before):
        return True
    past = bool(_KOREAN_PAST.search(after)) or stem in ("멈췄", "멈춘")
    if past and _REQUEST_BEFORE_STOP.search(before) and not _STATUS_REQUEST.search(before):
        return True  # a request of its own, then the stop it names: "dag ulw 다시 돌려줘, 아까 취소한 거"
    if past and _STATUS_REQUEST.search(after):
        return False  # a status check of a past stop: "dag ulw 멈춘 거 확인해줘", "dag ulw 취소 여부 확인해줘"
    return _ends_in_its_own_request(after)


def _asks_about_stopping(stop: re.Match[str] | None) -> bool:
    """Whether the last stop word asks how to stop, or whether it stopped, rather than stopping or naming work."""
    if stop is None or _stop_names_work(stop):
        return False
    after = _after_the_stop(stop)
    return bool(_KOREAN_HOW.search(after) or _KOREAN_PAST.search(after) or stop.group("stem") in ("멈췄", "멈춘"))


def reports_or_asks_after_the_name(text: str) -> bool:
    """Whether ``text`` opens with the bare name and goes on to report on dag-ulw or ask a question
    (`name_report_cues`), rather than to say a stop or status word for its run (`dag_ulw_control`)."""
    folded = _folded(text)
    bare = _BARE_LEAD.match(folded)
    if not bare or dag_ulw_control(folded):
        return False
    rest = folded[bare.end() :]
    return (not re.search(_NAME, rest) and reports_on_the_name(rest)) or asks_after_the_name(rest, about_anything=True)


def reports_on_dag_ulw(text: str) -> bool:
    """Whether ``text`` opens with the bare name and goes on to report on dag-ulw, asking nothing ("dag-ulw is
    broken"): after another skill's sigil that is work for the skill, not a question about dag-ulw."""
    folded = _folded(text)
    bare = _BARE_LEAD.match(folded)
    if not bare:
        return False
    rest = folded[bare.end() :]
    return reports_on_the_name(rest) and not asks_after_the_name(rest, about_anything=True)


def asks_about_dag_ulw(text: str) -> bool:
    """Whether ``text`` names `dag-ulw` to ask about it rather than to run it."""
    folded = _folded(text)
    if not re.search(_NAME, folded):
        return False
    if _ASKED_ABOUT.search(folded) or _SIGIL_QUESTION.match(folded) or _sigil_asks(folded):
        return True
    if _asks_about_stopping(_STOP_AFTER_NAME.search(folded)):
        return True  # "dag ulw 취소 어떻게 해", "dag ulw 멈출 수 있어", "dag ulw 취소됐어?"
    if reports_or_asks_after_the_name(folded):
        return True  # "dag ulw broke my build", "dag ulw 또 실패했어", "dag ulw 결제 api 뭐야", "dag ulw run finished, now what"
    if _POLITE_REQUEST.match(folded):
        return bool(_WEIGHED.search(folded))
    return folded.endswith(("?", "？"))


_SIGIL_LEAD: Final = re.compile(rf"^(?:\$|\./|/){_NAME}")
# Further skills stacked after the sigil ("/dag-ulw /ulw-plan what is it?"): Hermes loads each, and the words after
# the last one are the instruction.
_STACKED_SIGILS: Final = re.compile(r"(?:\s+(?:\$|\./|/)[a-z0-9][a-z0-9_-]*)+(?=\s|$)")
# A Korean question that asks for the work to be done for the person, with 주다 ("구현해줄 수 있어?", "나눠서 해주실래요?",
# "고쳐주시겠어요?"): a polite request, as "can you dag ulw the migration?" is.
_KOREAN_ASKS_TO_BE_DONE: Final = re.compile(r"(?:줄|주실)\s*(?:수\s*있|래|거)|주시겠|줄래")
# Work proposed as a question is a request for it ("can we split the api, ui and docs work into parallel lanes?").
_PROPOSED: Final = re.compile(r"^(?:can|could|shall)\s+we\b")


def _sigil_asks(folded: str) -> bool:
    """Whether the instruction after a sigil, and after any skills stacked on it, is a question rather than a command.

    A question word opens it in English (`_SIGIL_QUESTION`), or it asks a question and asks for nothing
    (`asks_after_the_name`: "/dag-ulw 이게 뭐야?", "/dag-ulw 어떻게 써?", "/dag-ulw we committed a secret, what now"), or
    it weighs the run against another way (`_WEIGHED`). In any language it is a question when it ends
    in a question mark and asks for nothing, as after the bare name ("/dag-ulw CI 통과했어?", "/dag-ulw did the sweep
    finish?", "/dag-ulw Kubernetes是什么？"). A request that holds a question word stays one ("/dag-ulw 왜 깨졌는지
    찾아서 고쳐줘"), and so does one that opens on a request verb, is asked politely or is proposed ("/dag-ulw migrate
    the billing service?", "/dag-ulw 나눠서 구현해줄 수 있어?", "/dag-ulw can you dag ulw the migration?", "/dag-ulw can
    we split the work into parallel lanes?").
    """
    lead = _SIGIL_LEAD.match(folded)
    if not lead:
        return False
    if _WEIGHED.search(folded):
        return True  # it weighs the run against another way, as a polite question does ("/dag-ulw … or should I …?")
    rest = folded[lead.end() :]
    stacked = _STACKED_SIGILS.match(rest)
    if stacked:
        rest = rest[stacked.end() :]
        if _SIGIL_QUESTION.match(f"/{DAG_ULW} {rest.strip()}"):
            return True
    rest = rest.strip(" ,:")
    if asks_after_the_name(rest, about_anything=True) or _ASKED_ABOUT.search(rest) or ja_zh_asks_what_it_is(rest):
        return True  # _ASKED_ABOUT: the name again, asked about ("/dag-ulw can you explain dag ulw?")
    # ", " makes the opening clause one `asks_for_something` reads too: "/dag-ulw migrate the billing service?" opens
    # on a request verb, so it is a request with a question mark.
    return rest.endswith(("?", "？")) and not (
        asks_for_something(f", {rest}") or _KOREAN_ASKS_TO_BE_DONE.search(rest) or _PROPOSED.match(rest)
    )


def asks_after_the_sigil(text: str) -> bool:
    """Whether ``text`` opens with the `dag-ulw` sigil and asks a question after it, and after any skills stacked on
    it ("/dag-ulw what is it?", "/dag-ulw 이게 뭐야?", "/dag-ulw /ulw-plan what is it?"): the stacked skills are not
    invoked either."""
    folded = _folded(text)
    return bool(_SIGIL_LEAD.match(folded)) and bool(_SIGIL_QUESTION.match(folded) or _sigil_asks(folded))


def invokes_dag_ulw(text: str) -> bool:
    """Whether ``text`` (the executable part of a message) asks to run `dag-ulw`.

    A sigil (``/dag-ulw``, ``$dag-ulw``) is a command whatever follows it, as it is for every skill, except a word
    for the run in progress (`dag_ulw_control`), a question after it, in English or Korean and after any skills
    stacked on it (`_sigil_asks`), or a question about stopping it: stopping, checking or asking never starts a run.
    Hermes sends every `/dag-ulw` turn this way, so it is the form that runs.
    """
    folded = _folded(text)
    if not folded or _NEGATED.search(folded) or dag_ulw_control(folded):
        return False
    if _SIGIL_LEAD.match(folded):
        return not (
            _SIGIL_QUESTION.match(folded) or _sigil_asks(folded) or _asks_about_stopping(_STOP_AFTER_NAME.search(folded))
        )
    if asks_about_dag_ulw(folded):
        return False
    return bool(_LEAD.match(folded) or _WITH.search(folded) or _KOREAN_RUN.search(folded))


def declines_dag_ulw(text: str) -> bool:
    """Whether ``text`` names `dag-ulw` only to decline it ("don't use dag ulw", "dag ulw 말고")."""
    return bool(_NEGATED.search(_folded(text)))


# ── big work by size ─────────────────────────────────────────────────────

# How the WORK is split (lanes, a fan-out, parts integrated afterwards) or how wide it reaches (every module, the
# whole codebase). A bare concurrency word is not one: "in parallel", "concurrently", "병렬로" and "동시에" name
# the bug or the feature as often as the work's shape ("fix the bug where uploads run in parallel",
# "동시에 두 요청이 오면 캐시가 깨지는 버그 고쳐줘"), so they count only beside several named parts
# (`_PART_WORDS`). Each of these left the list after an unrelated sentence using it moved: "then integrate" alone,
# "parallel lanes" alone, "parallel work" and "parallel implementation" as nouns ("the parallel work queue drops
# jobs, fix it"), "fan out" as a noun or of something other than the work ("the fan out of this function is too
# high", "fan out the notifications to all subscribers"), and a Korean concurrency word with a work verb
# ("병렬로 구현", "동시에 진행"); the probes are kept with the measurement.
SHAPE_CUES: Final = (
    "into parallel lanes",
    "into parallel work",
    "into parallel parts",
    "into parallel tasks",
    "in parallel lanes",
    "parallel then integrate",
    "fan out across",
    "병렬로 나눠",
    "나눠서 병렬로",
)
BREADTH_CUES: Final = (
    "across the codebase",
    "across every module",
    "across all modules",
    "across modules",
    "every module",
    "all modules",
    "whole codebase",
    "entire codebase",
    "여러 모듈",
    "모든 모듈",
    "전체 모듈",
    "코드베이스 전체",
)
CONCURRENCY_CUES: Final = ("in parallel", "concurrently", "simultaneously", "at the same time", "병렬로", "동시에")
# Several named parts: an English plural part noun, or a Korean part noun said at least twice
# ("api 모듈과 ui 모듈"), since Korean marks no plural.
_PART_WORDS: Final = frozenset(
    {"modules", "services", "packages", "components", "apps", "repos", "repositories", "microservices", "libraries"}
)
_KOREAN_PART_WORDS: Final = ("모듈", "서비스", "패키지", "컴포넌트")
_ULTRAWORK_STEMS: Final = ("ultrawork", "ulw", "울트라워크")
# A shape cue counts only where the work is asked for. Not in the subject of a remark ("the fan out across the
# services is too high"), and not where the split's object is one paragraph or sentence, a small text task ("split
# the paragraph into parallel parts for the translation", "이 문단을 병렬로 나눠서 번역해줘"); a paragraph named
# elsewhere ("the paragraph parser", "fix the paragraph in the README") changes nothing.
_REMARK_SUBJECT: Final = re.compile(
    r"^(?:the|a|an|this|that|these|those|our|its|their|my|your)\s+([^.?!,;]*?)\s(?:is|are|was|were|seems|looks)\b"
)
_SMALL_TEXT_OBJECT: Final = re.compile(
    r"\bsplit\s+(?:the|this|that|a|one|my|your)\s+(?:paragraph|sentence)\s+into\b|(?:이|그|저|한)\s*(?:문단|문장|단락)(?:을|를)\s"
)
# A fault the parts cause together, with one fix asked for: the concurrency word says when the bug happens, not how
# the work splits ("api 모듈과 ui 모듈이 동시에 요청하면 캐시가 깨져, 고쳐줘").
_FAULT: Final = re.compile(
    r"\b(?:breaks|broke|fails|failed|crash(?:es|ed)|hangs|hung|deadlocks|deadlocked|corrupts|corrupted"
    r"|(?:is|are|gets?|got)\s+(?:broken|corrupted|stuck)|times?\s+out|timed\s+out)\b"
    r"|깨져|깨지|깨졌|터져|터지|터졌|죽어|죽었|실패해|실패하|실패했|꼬여|꼬이|꼬였|(?:에러|오류)가?\s*(?:나|났|떠|뜨)"
    r"|충돌이?\s*(?:나|났)|데드락|교착"
)
_FIX_REQUEST: Final = re.compile(r"\b(?:fix|resolve|debug|repair)\b|고쳐|수정해|해결해")
# Unless the concurrency word says how the work or the fixes run ("테스트가 실패하는데 병렬로 고쳐줘", "병렬로 각각
# 고쳐줘", "동시에 진행해줘, 실패하는 테스트도 고쳐줘", "fix them in parallel"): a request, a verb with a request
# ending, follows it at most two words on. In the fault it is a condition ("동시에 요청하면 캐시가 깨져", "동시에
# 처리해서 캐시가 깨져").
_PARALLEL_WORK: Final = re.compile(
    r"(?:병렬로|동시에)\s*(?:(?:각각|따로|모두|전부|다|같이|함께|한꺼번에|\S+해서)\s*){0,2}"
    r"(?:고쳐|수정해|해결해|진행해|작업해|처리해|구현해)\s*(?:줘|주세요|줄래|봐)"
    r"|\bfix\s+(?:them|both|all|each|these|those)(?:\s+of\s+them)?\s+"
    r"(?:in\s+parallel|concurrently|simultaneously|at\s+the\s+same\s+time)\b"
)
# A question or an explain request about how work splits asks to be told, not for the work ("explain how to split
# the work into parallel lanes", "show me how to split ...", "is it possible to split ...", "how do I split the work
# into parallel lanes?", "병렬로 나누는 방법 설명해줘", "병렬로 나눠서 하는 법 알려줘"). Not an opener that proposes the
# work ("how about we split ...", "why don't we split ...", "what we need is to split ...", "tell me when done:
# split ..."), not a Korean explain clause after the work it explains ("... 구현하고 나눈 방법 설명해줘"), and not a
# request put as a question ("can we split ...?", "let's split ...?", "..., ok?", "... 구현해줄 수 있어?").
_ASKS_TO_BE_TOLD: Final = re.compile(
    rf"^{_POLITE_OPENER}?(?:how(?!\s+about)|what(?!\s+(?:we|i)\s+(?:need|want)(?:\s+is\s+to\b|\s*:))|why\s+not\s+just\s+explain"
    r"|why(?!\s+(?:don'?t|not)\b)|explain|describe|tell\s+me(?!\s+when)|show\s+me\s+how|help\s+me\s+understand"
    r"|i(?:\s+(?:want|need)|['’]d\s+like|\s+would\s+like)\s+to\s+know|is\s+it\s+possible)\b"
)
# Talking it over is not asking for it either ("can we talk about how to split ...", "can we discuss whether to
# split ..."), nor is a question that weighs the split against another way ("could we split ..., or is it overkill?").
_TALKS_IT_OVER: Final = re.compile(r"\b(?:talk|think)\s+(?:about|through)\b|\bdiscuss\b|\bwhether\s+(?:to|we|i)\b")
_WEIGHS_THE_SPLIT: Final = re.compile(_OR_ANOTHER_WAY)
_KOREAN_ASKS_TO_BE_TOLD: Final = re.compile(
    r"(?:방법|는\s*법)\s*(?:을|를|이|가)?\s*(?:좀\s*)?(?:설명해|알려|뭐)|지\s*(?:를\s*)?(?:좀\s*)?(?:설명해|알려)"
)
_KOREAN_WORK_FIRST: Final = re.compile(
    r"(?:구현|만들|고치|고쳐|수정|작성|리팩터링|추가|개발|빌드|배포|진행|테스트|마이그레이션|적용|처리)\S*(?:고|서)\s"
)
_REQUEST_AS_QUESTION: Final = re.compile(
    rf"^(?:(?:please|pls)\s+)?(?:{_POLITE_OPENER}|(?:can|could|shall)\s+we\b|let'?s\b)"
    r"|,\s*(?:ok|okay|alright|right)\s*[?？]$|(?:줄\s*수\s*있|주실\s*수\s*있|줄래|주시겠|주겠)\S*\s*[?？]$"
    r"|면\s*어때요?\s*[?？]$"
)


def _cue_text(text: str) -> str:
    """Lower-cased and accent-folded, the way the router's `contains_cue_phrase` reads a message."""
    folded = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(character for character in folded if not unicodedata.combining(character))


def _compact(text: str) -> str:
    return "".join(character for character in text if character.isalnum())


def _contains(text: str, cues: tuple[str, ...]) -> bool:
    """`contains_cue_phrase`'s match: the cue in the text, or with every space and mark taken out of both."""
    compact = _compact(text)
    return any(_cue_text(cue) in text or _compact(_cue_text(cue)) in compact for cue in cues)


def names_ultrawork(text: str) -> bool:
    """Whether a word of ``text`` carries ultrawork's name or alias (`ulw`, `ulw-work`, `ultrawork로`)."""
    words = re.findall(r"[^\W_]+", _folded(text))
    return any(stem in word for word in words for stem in _ULTRAWORK_STEMS)


def _asks_for_a_split(text: str) -> bool:
    """Whether a `SHAPE_CUES` phrase in ``text`` asks for the work to split (`_REMARK_SUBJECT`, `_SMALL_TEXT_OBJECT`).

    The regular expressions read the composed text: `_cue_text` takes Hangul apart into its letters."""
    if not _contains(_cue_text(text), SHAPE_CUES):
        return False
    folded = _folded(text)
    subject = _REMARK_SUBJECT.match(folded)
    if subject and _contains(_cue_text(subject.group(1)), SHAPE_CUES):
        return False
    return not _SMALL_TEXT_OBJECT.search(folded)


def _asks_to_be_told(text: str) -> bool:
    folded = _folded(text)
    if _ASKS_TO_BE_TOLD.search(folded) or _TALKS_IT_OVER.search(folded):
        return True
    if _KOREAN_ASKS_TO_BE_TOLD.search(folded) and not _KOREAN_WORK_FIRST.search(folded):
        return True
    if not folded.endswith(("?", "？")):
        return False
    return bool(_WEIGHS_THE_SPLIT.search(folded)) or not _REQUEST_AS_QUESTION.search(folded)


# Work said over many targets, which splits into parallel parts (owner decision: only multi-part work moves). Two
# readings, with the same hard excludes (`_hard_excluded`):
# - `dispatches_dag_ulw`, positive evidence the router dispatches and the route hint starts on: a change verb from a
#   closed allow list, in request form, on a breadth object that names independent units ("열린 PR들 전부
#   리베이스해줘", "fix all the failing tests", "update every service to node 22", two named parts in parallel);
# - `work_over_many_targets`, a breadth word on such units with a request that may be work but is not that evidence
#   ("review all open PRs"): the router may only ask once with dag-ulw as the candidate, and the hint offers it.
_KOREAN_UNIT: Final = r"(?:pr|prs|pull\s*request|레포|리포|저장소|서비스|모듈|패키지|컴포넌트|엔드포인트|테스트|이슈|파일|페이지|브랜치)"
# A count of units is breadth only for PRs, repos and branches, and only with a breadth word after it ("PR 3개 전부",
# "PR 5개 다", "레포 3개 전부"; lead decision on the #2232 review). A count of anything else, or one with no breadth
# word, is a small single task ("파일 2개 수정해줘", "테스트 3개 고쳐줘", "PR 3개 리베이스해줘"). A count is never one
# PR's number either (`_ONE_SCOPE`).
_KOREAN_COUNTED_UNIT: Final = r"(?:pr|pull\s*request|풀\s*리퀘(?:스트)?|레포|리포|repo|브랜치|branch)"
_KOREAN_COUNT: Final = r"(?:두|세|네|다섯|여러|[2-9]|\d{2,})\s*(?:개|건)"
_KOREAN_BREADTH_OBJECT: Final = (
    rf"(?:(?<![가-힣])(?:마이크로)?{_KOREAN_UNIT}(?:들)?\s*(?:을|를|은|는)?\s*(?:전부|모두|다|싹|몽땅|쭉|하나하나|각각"
    rf"|(?:하나도\s*)?빠짐없이)(?![가-힣])"
    rf"|(?<![가-힣a-z]){_KOREAN_COUNTED_UNIT}(?:들)?\s*{_KOREAN_COUNT}\s*(?:을|를|은|는)?\s*(?:전부|모두|다|몽땅)(?![가-힣])"
    rf"|(?<![가-힣])(?:모든|전체|각)\s*(?:마이크로)?{_KOREAN_UNIT}(?:들)?(?:을|를|에|의|에서)?)"
)
_EN_UNITS: Final = (
    r"(?:prs?|pull\s+requests?|repos?|repositor(?:y|ies)|(?:micro)?services?|modules?|packages?|components?|endpoints?"
    r"|tests?|issues?|files?|pages?|apps?|branch(?:es)?)"
)
# A fault word that only describes the units ("실패하는 테스트", "the failing tests") names which units, not one fault.
_FAULTY_UNIT: Final = re.compile(
    r"(?:실패하는|실패한|실패했(?:었)?던|깨진|깨지는|깨졌(?:었)?던|터진|터졌(?:었)?던|충돌난|충돌났(?:었)?던|failing|failed|broken"
    rf"|flaky)\s+(?:{_KOREAN_UNIT}|{_EN_UNITS})"
)
# One fault said in Korean as something that does not work, in any words, with one fix asked: 안 or 못 before a
# predicate ("안 돌아가", "안 먹어", "못 해"), …지 않 or …지 못 ("돌지 않아"), a fault noun ("먹통", "고장"), or a symptom
# clause, a subject with 이 or 가 and its predicate right before the fix ("페이지가 하얗게 나와 고쳐줘", "아이콘이 깨져 보여
# 고쳐줘", "페이지가 느려 고쳐줘").
_KOREAN_NEGATED_PREDICATE: Final = re.compile(
    r"(?<![가-힣])(?:안|못)\s*(?!(?:의|에|에서|으로|을|이)(?![가-힣]))(?P<word>[가-힣]+)|지\s*(?P<negation>(?:않|못)[가-힣]*)"
)
_KOREAN_FAULT_NOUN: Final = re.compile(r"먹통|고장")
_KOREAN_SYMPTOM_BEFORE_FIX: Final = re.compile(
    r"[가-힣](?:이|가)\s+(?:\S+\s+){0,2}?(?P<word>[가-힣]+)\s*[,.~]?\s+(?:고쳐|고치|수정|해결|fix\b)"
)
_FIX_VERB: Final = re.compile(r"\b(?:fix|resolve|debug|repair)\b|고쳐|고치|수정|해결")


def _closes_a_clause(word: str) -> bool:
    """Whether a Korean predicate ``word`` closes its clause, as a symptom does ("안 돌아가", "느려", "나와", "안됨"), rather
    than aiming the change (…게, …게끔, …도록: "안 되게 고쳐줘", "안 되게끔 수정해줘", "쓰지 않게"), going on to more (…고), or
    describing a noun (…는, …던, …은, a final ㄴ: "안 돌아가는 테스트")."""
    code = ord(word[-1]) - 0xAC00
    return not (word.endswith(("게", "게끔", "도록", "고", "는", "던", "은")) or (0 <= code < 11172 and code % 28 == 4))


def _one_fault(folded: str) -> bool:
    """Whether ``folded`` asks to fix one fault however wide it reaches (`_FAULT`, or a Korean "does not work"), rather
    than for work on each unit; a fault word that only describes the units names which units (`_FAULTY_UNIT`), and
    a concurrency word that says how the fixes run is no fault (`_PARALLEL_WORK`)."""
    plain = _FAULTY_UNIT.sub(" ", folded)
    if not _FIX_VERB.search(plain) or _PARALLEL_WORK.search(plain):
        return False
    if _FAULT.search(plain) or _KOREAN_FAULT_NOUN.search(plain):
        return True
    if any(
        _closes_a_clause(match.group("word") or match.group("negation"))
        for match in _KOREAN_NEGATED_PREDICATE.finditer(plain)
    ):
        return True
    return any(
        match.group("word") not in ("해", "돼") and _closes_a_clause(match.group("word"))
        for match in _KOREAN_SYMPTOM_BEFORE_FIX.finditer(plain)
    )
_EN_PARTS_IN_PARALLEL: Final = re.compile(
    r"^(?:please\s+)?(?:implement|build|develop|ship|write|add|create)\s+(?:the\s+)?\S+(?:,\s*\S+)*\s+(?:and|&)\s+\S+\s+"
    r"(?:features|endpoints|pages|screens|apis|modules|services|components)\s+(?:in\s+parallel|concurrently)\b"
)
_G: Final = unicodedata.normalize("NFKC", "ㄱ")
# The owner writes some English change verbs inside a Korean request ("rebase까지 ㄱㄱ", "upgrade해줘", "close하고"): one is
# a change where a Korean request ending, 까지 or 하고 follows it.
_KOREAN_ENDING_AFTER_EN: Final = rf"(?=\s*(?:까지|하고|해|부탁|진행|{_G}|고고|$))"
_EN_VERB_IN_KOREAN: Final = (
    rf"(?<![a-z])(?:rebase|merge|bump|fix|upgrade|update|close){_KOREAN_ENDING_AFTER_EN}"
)
# A push is one command over everything ("모든 브랜치 push 해줘", as "모든 브랜치 푸시해줘"); said last, after a change, it is
# that change's final step ("리뷰 코멘트 반영하고 force push ㄱㄱ").
_PUSH_IN_KOREAN: Final = re.compile(rf"(?<![a-z])(?:force\s*)?push{_KOREAN_ENDING_AFTER_EN}")
# The change verbs the router dispatches a graph on: a closed allow list. Reading, explaining, summarising,
# measuring, comparing, surveying, sharing, notifying, checking, reviewing and auditing are not on it, and neither is
# one command over everything (run, restart, push, deploy, format, delete, merge into one).
_KOREAN_CHANGE_VERB: Final = (
    r"(?:고쳐|고치|수정|업데이트|업그레이드|올려|올리|교체|추가|옮겨|옮기|바꿔|바꾸|리베이스|반영|닫|적용|붙여|붙이|통일|만들"
    rf"|마이그레이션|변경|리팩터링|리팩토링|머지|이전|해결|넣|최신화|{_EN_VERB_IN_KOREAN})"
)
_EN_CHANGE_VERB: Final = (
    r"(?:fix|update|upgrade|migrate|refactor|port|convert|add|rename|rebase|close|merge|bump|address|resolve|implement"
    r"|build|replace|move|apply|patch|rewrite|reimplement)"
)
# The verbs a request may be offered dag-ulw on, without starting it: the change verbs, and reviewing or triaging
# each unit ("review all open PRs", "PR들 전부 리뷰해줘").
_KOREAN_OFFER_VERB: Final = rf"(?:{_KOREAN_CHANGE_VERB}|리뷰|검토|트리아지|라벨)"
_EN_OFFER_VERB: Final = rf"(?:{_EN_CHANGE_VERB}|review|triage|label)"
_EN_BREADTH: Final = (
    rf"(?:\b(?:all|every|each)\s+(?:of\s+)?(?:the\s+|my\s+|our\s+)?(?:\S+\s+){{0,2}}?{_EN_UNITS}\b"
    rf"|\bacross\s+(?:all\s+|every\s+)?(?:the\s+)?{_EN_UNITS}\b)"
)
# An English request over many targets: an imperative whose verb is on the offer list, or a read first and a change
# after it ("check all open pull requests and close the stale ones").
# The units said first, then what to do with each ("for each of my PRs: rebase onto main", "for every open PR, rebase
# it").
_EN_FOR_EACH: Final = (
    rf"for\s+(?:each|every|all)\s+(?:of\s+)?(?:the\s+|my\s+|our\s+)?(?:\S+\s+){{0,2}}?{_EN_UNITS}\b\s*[:,]?\s*(?:please\s+)?"
)
_EN_PLURAL_UNITS: Final = (
    r"(?:prs|pull\s+requests|repos|repositories|(?:micro)?services|modules|packages|components|endpoints|tests|issues|files"
    r"|pages|apps|branches)"
)
_EN_OFFER: Final = re.compile(
    rf"^(?:please\s+)?{_POLITE_OPENER}?(?:{_EN_OFFER_VERB}\b[^.?!]*?{_EN_BREADTH}"
    rf"|(?:check|go\s+through|look\s+at)\b[^.?!]*?{_EN_BREADTH}[^.?!]*?\band\s+(?:then\s+)?{_EN_CHANGE_VERB}\b"
    rf"|{_EN_FOR_EACH}{_EN_OFFER_VERB}\b)"
    rf"|\b{_EN_PLURAL_UNITS}\b[^.?!]*?\b{_EN_OFFER_VERB}\s+them\s+all\b"
)
_EN_LATER_CLAUSE_VERB: Final = re.compile(r"\band\s+(?:then\s+)?(?:just\s+)?([a-z]+)")
_KOREAN_OFFER: Final = re.compile(
    rf"{_KOREAN_BREADTH_OBJECT}\s*(?:\S+\s+){{0,3}}\S*{_KOREAN_OFFER_VERB}"
    rf"|{_KOREAN_BREADTH_OBJECT}\s*(?:\S+\s+){{0,4}}\S*(?:게|게끔|도록)\s+(?:좀\s+)?\S*{_KOREAN_OFFER_VERB}"
)
# An explicit request: a Korean request ending on the verb, the message's last word ("리베이스해줘", "리베이스해줘요",
# "리베이스해", "올려놔", "올리자", "리베이스해주셈"), or said as a word of its own right after the verb ("리베이스 해줘",
# "업데이트 좀 해 주세요", "업데이트 해 놔줘", "업데이트 시켜줘", "업데이트 부탁", "고쳐 줘", "리베이스 ㄱ", "리베이스 고"); or a
# chain of two or more change verbs joined by 고 ("닫을건 닫고 리뷰반영할건 리뷰반영하고 rebase할건 리베이스하고").
_KOREAN_GIVE: Final = r"(?:줘요|줘|주세요|주세용|주셈|주라|주십쇼|주십시오|줄래)"
# A casual imperative of a change verb closes a request on its own ("PR들 전부 닫아", "모든 테스트 고쳐", "모든 패키지
# 올려라").
_KOREAN_PLAIN_IMPERATIVE: Final = r"(?:닫아|고쳐|올려|바꿔|옮겨|붙여|만들어|넣어)(?:라)?"
_KOREAN_REQUEST_END: Final = re.compile(
    rf"(?:해\s*{_KOREAN_GIVE}|하자|{_KOREAN_GIVE}|해라|해|놔라|둬라|놔|둬|자|{_KOREAN_PLAIN_IMPERATIVE}|{_G}+|고고싱|고고)"
    r"\s*[.!~]*$"
)
_KOREAN_BARE_REQUEST_END: Final = re.compile(
    r"\s(?:(?:좀|꼭|다시|빨리|얼른|바로|제발)\s+)?"
    rf"(?:(?:진행\s*)?해\s*(?:{_KOREAN_GIVE}|(?:놔|둬)\s*{_KOREAN_GIVE}?)?|{_KOREAN_GIVE}|시켜\s*{_KOREAN_GIVE}?|하자"
    rf"|부탁(?:해요|해|드려요|드립니다|합니다|요)?|(?:해\s*)?주시기\s*바랍니다|바랍니다|(?:해\s*)?주시면\s*감사하겠습니다|요망"
    rf"|(?:놔|둬)(?:라|\s*{_KOREAN_GIVE})?|{_G}+|고고싱|고고|고)"
    r"\s*[.!~]*$"
)
# The verb a bare ending is said after closes its word, or carries only its own ending ("고쳐", "만들어", "업데이트해",
# "rebase까지"): not a clause before it ("리베이스하려고 해", "리베이스해야 해").
_VERB_BEFORE_A_BARE_END: Final = r"(?:아|어|여|해|하)?(?:까지|도|만)?$"
_KOREAN_CHAIN_END: Final = re.compile(r"고\s*[.!~]*$")


def _korean_request_verb(folded: str) -> tuple[str, bool]:
    """The word that holds a Korean request's verb, and whether a request ending said on its own follows it (the
    word before it) rather than closing it (the last word); "" when the message makes no request."""
    bare = _KOREAN_BARE_REQUEST_END.search(folded)
    if bare:
        words = folded[: bare.start()].split()
        return (words[-1] if words else ""), True
    return (folded.rstrip(" .!~").split()[-1] if _KOREAN_REQUEST_END.search(folded) else ""), False


# What follows a request in a later clause is read on positive evidence only (lead decision on the #2243 review). A
# clause after the request keeps it when it is a keeper by shape (`_KEEPER_CLAUSE`: an urgency or a deadline, a start
# cue, thanks or politeness, with an intensifier or a request ending of its own: "…해줘, 최대한 빨리", "…해줘,
# 금요일까지", "…해줘, 지금 바로", "…해줘, 부탁할게", "…, by friday please", "…, no rush"), or a follow-on that opens with a
# sequencing connective and asks for more work (`_follows_on`: "…해줘, 그 다음 테스트 돌려줘", "…해줘, 끝나고 문서도
# 정리해줘", "…해줘, 패키지마다 changelog도 써줘", "…, then integrate the findings"). No clause after the request may hold,
# cancel or joke about it (`_HOLD`), and every clause between must keep it too (`_keeps_the_request`); a clause that opens
# on a back-reference ("…해줘, 는 아니고 리뷰해줘") is neither a keeper nor a follow-on. Anything else after a Korean
# request keeps nothing, and the message is read whole, as on main ("…해줘, 해도 되나", "…해줘, 이거 맞아?", "…해줘,
# 확인해줘"). After an English request a remark keeps it too, and only a refusal or a new request does not ("…, what do
# you think", "…, not sure though", "…, run the tests": `_remarks_keep_the_request`, `_trails_off`).
# The leading space is read only where a run of it starts (`(?<!\s)`), or not at all right after an earlier cut: the
# same cuts, but a search no longer re-reads a run of spaces from each of its positions, which is quadratic in the run,
# and a fenced log masked to spaces by `executable_routing_text` is one long run.
_CLAUSE_BREAK: Final = re.compile(r"(?:(?<!\s)\s*)?(?:[,;—–…]|\.{2,}|\s-\s)\s*")
_INTENSIFIER: Final = r"(?:(?:최대한|가능한(?:\s*한)?|되도록|좀|진짜|정말|제발|너무|완전)\s*)?"
_TIME_WORD: Final = (
    r"(?:오늘|내일|모레|글피|이번\s*주|다음\s*주|이번\s*달|다음\s*달|주말|월말|연말|[월화수목금토일]요일|오전|오후|점심|저녁|아침|밤"
    r"|퇴근\s*전|퇴근|\d+\s*(?:시|일)(?:\s*\d+\s*분)?|eod)"
)
_KEEPER_WORD: Final = (
    rf"(?:{_INTENSIFIER}(?:빨리|얼른|급히|서둘러|빠르게|신속히)|{_INTENSIFIER}급(?:해|해요|함|합니다|하다)"
    rf"|{_TIME_WORD}(?:\s*{_TIME_WORD})*\s*(?:까지(?:는|만)?|안에|중으로|중에|내로|이내)"
    rf"|지금(?:\s*바로)?|바로|당장|즉시|(?:바로\s*|지금\s*)?시작(?:해|하자)?|가자|고고|{_G}+"
    r"|부탁\S*|고마\S*|고맙\S*|감사\S*|땡큐"
    r"|asap|urgent(?:ly)?|quickly|right\s+away|no\s+rush|today|(?:right\s+)?now|go(?:\s+ahead)?|let'?s\s+go"
    r"|by\s+(?:the\s+)?(?:eod|eow|cob|end\s+of\s+(?:the\s+)?(?:day|week|month|sprint)|today|tonight|tomorrow(?:\s+morning)?"
    r"|noon|midnight|(?:this\s+|next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|weekend)"
    r"|\d{1,2}(?::\d{2})?\s*(?:am|pm)?)"
    r"|please|pls|plz|thanks(?:\s+(?:a\s+lot|so\s+much|in\s+advance))?|thank\s+you(?:\s+so\s+much)?|thx|ty|cheers"
    r"|(?:much\s+)?appreciated"
    # how the work is cut per unit, by shape ("one PR per service", "a separate PR per repo", "one commit per package",
    # "per repo", "each in its own branch")
    r"|(?:(?:with|in|as|using)\s+)?(?:one|a|a\s+single|a\s+separate|one\s+separate|its\s+own|their\s+own|separate)"
    r"\s+(?:[a-z][\w-]*\s+){0,2}?[a-z][\w-]*\s+(?:per|for\s+each|for\s+every)\s+[a-z][\w-]*"
    r"|(?:one\s+)?per\s+[a-z][\w-]*|each\s+(?:in|on)\s+(?:its|their)\s+own\s+[a-z][\w-]*)"
)
_KEEPER_CLAUSE: Final = re.compile(
    rf"{_KEEPER_WORD}(?:\s*(?:and\s+)?{_KEEPER_WORD})*(?:\s*(?:해\s*{_KOREAN_GIVE}|해요|해|{_KOREAN_GIVE}|요))?\s*[.!~]*"
)
# A follow-on opens with a sequencing connective (끝나면 is a condition, not one), or on each of the units ("패키지마다"),
# and asks for more work: a Korean work verb in request form, not narrowed to that work alone ("확인만") or undoing the
# request ("되돌려줘"), or an English one ("…, then run the tests", "…, and then integrate").
_KOREAN_CONNECTIVE: Final = re.compile(
    r"^(?:그리고(?:\s*나서)?|그\s*다음(?:에|엔|으로)?|그\s*담에|다음으로|이어서|끝나고(?:\s*나서)?|그러고\s*나서|그\s*(?:뒤|후)에"
    rf"|(?:각\s*)?(?:{_KOREAN_UNIT}|풀\s*리퀘(?:스트)?)(?:들)?\s*마다)\s+"
)
_FOLLOW_ON_VERB: Final = rf"(?:{_KOREAN_OFFER_VERB}|갱신|써|작성|확인|(?<!되)돌려|실행|시작|진행|정리)"
_EN_FOLLOW_ON_VERB: Final = (
    rf"(?:{_EN_OFFER_VERB}|integrate|develop|ship|test|run|rerun|deploy|write|document|verify|check|clean\s+up|push|tag"
    r"|release)"
)
_EN_FOLLOW_ON: Final = re.compile(
    rf"^(?:and\s+then|and|then|after\s+that|next|afterwards)\s*,?\s+(?:please\s+|just\s+|also\s+)*{_EN_FOLLOW_ON_VERB}\b"
)
# A colon list after a breadth head is one request, not trailing clauses, when every item opens on a verb of work
# ("for each of my upstream PRs: rebase, resolve conflicts, push", "for each open PR: rebase, squash, merge"): any word
# but a read, a report, a hold, a negation, a hedge or a function word (`_NOT_A_WORK_VERB`).
_READ_OR_HOLD_VERB: Final = (
    r"(?:check|review|look|list|see|read|inspect|audit|scan|summari[sz]e|explain|describe|comment|report|tell|show|send"
    r"|let|ping|notify|message|wait|hold|pause|stop|halt|cancel|skip|leave)"
)
_NOT_A_WORK_VERB: Final = (
    rf"(?:{_READ_OR_HOLD_VERB}|don'?t|do|does|not|no|never|nothing|none"
    r"|maybe|perhaps|probably|possibly|might|may|could|would|should|will|can|is|are|was|were|be|it|this|that|these"
    r"|those|the|a|an|i|we|you|they|my|our|your|what|which|who|why|how|when|where|if|whether|though|but|although"
    r"|unless|so|because|since|or|also|just|only|lol|haha|hmm|idk|imo|imho|tbh|fwiw|btw|fyi|ok|okay|yes|yeah|nah"
    r"|sure|thanks|thank|please|all|every|each|both|some|any|most|everything|everyone)"
)
# An item that opens on a status is a report on the unit, not work ("done", "failed", "green", "conflict", "rebased").
_STATUS_WORD: Final = (
    r"(?:done|failed|failing|passing|passed|green|red|ok|fine|good|blocked|stuck|broken|gone|conflict(?:s|ing)?|clean"
    r"|dirty|stale|pending|wip|[a-z]+(?<!e)ed)"
)
_EN_LIST_ITEM: Final = re.compile(rf"^(?:and\s+)?(?:please\s+)?(?!(?:{_NOT_A_WORK_VERB}|{_STATUS_WORD})\b)[a-z][a-z-]*\b")
# A hedge or a refusal anywhere in an item ends the list and holds the request ("…, too risky though", "…, someday",
# "…, eh, rather not", "…, someone else's call though", "…, nope").
_HEDGE_IN_AN_ITEM: Final = re.compile(
    r"\b(?:maybe|perhaps|though|eventually|some\s*day|nope|nah|rather|not\s+my\s+call|someone\s+else'?s|not\s+sure"
    r"|too|risky|idk|eh|meh|ugh)\b"
)
# The head: the request so far ends in the first item of a colon list after a breadth word; a colon after a whole
# request opens a list too ("rebase all my open PRs: done, done, conflict"), and a colon between digits is a time.
_EN_LIST_HEAD: Final = re.compile(rf"(?:{_EN_BREADTH}|\bfor\s+(?:each|every|all)\b|\b{_EN_PLURAL_UNITS}\b)[^:,.!?]*:[^,]*$")
_LIST_COLON: Final = re.compile(r"(?:(?<!\s)\s*)?(?<!\d):(?!\d)\s*")  # leading space as in `_CLAUSE_BREAK`
_HOLD: Final = re.compile(
    r"농담|장난|됐어|됐고|(?<![가-힣])(?:아냐|아니야|아니다|아니|잠깐만?|잠시만?|말고)(?![가-힣])"
    r"|\b(?:jk|j/k|kidding|never\s*mind|nvm|wait|hold\s+on)\b"
)
_EN_TAKE_BACK: Final = re.compile(
    r"^(?:oh\s+|um\s+|no\s+)?(?:never\s*mind|nvm|jk|j/k|just\s+kidding|kidding|scratch\s+that|or\s+not|actually\s+(?:don'?t|no)"
    r"|don'?t|wait|hold\s+on|cancel\s+that|forget\s+(?:it|that)|not\s+now|later)\b"
)
_EN_TAKE_BACK_AT_THE_END: Final = re.compile(
    r"\b(?:jk|j/k|just\s+kidding|nvm|never\s*mind|or\s+(?:maybe\s+)?not)\s*[.!]*$"
)


def _takes_it_back(folded: str) -> bool:
    """Whether the last clause of a request takes it back (`_EN_TAKE_BACK`), or its last words do with no clause
    break before them ("rebase all open PRs or maybe not"): a guard on top of `_keeps_the_request`."""
    clauses = [clause for clause in _CLAUSE_BREAK.split(folded) if clause]
    return (len(clauses) > 1 and bool(_EN_TAKE_BACK.match(clauses[-1]))) or bool(_EN_TAKE_BACK_AT_THE_END.search(folded))


def _follows_on(clause: str) -> bool:
    """Whether ``clause`` opens with a sequencing connective and asks for more work (`_KOREAN_CONNECTIVE`,
    `_EN_FOLLOW_ON`)."""
    connective = _KOREAN_CONNECTIVE.match(clause)
    if connective:
        verb, _bare = _korean_request_verb(clause[connective.end():])
        return bool(verb) and bool(re.search(_FOLLOW_ON_VERB, verb)) and not verb.endswith("만")
    return bool(_EN_FOLLOW_ON.match(clause))


def _keeps_the_request(trailing: list[str]) -> bool:
    """Whether every clause after a request keeps it: a keeper (`_KEEPER_CLAUSE`) or a follow-on (`_follows_on`), with
    no hold or joke in any of them (`_HOLD`)."""
    return all(
        not _HOLD.search(clause) and bool(_KEEPER_CLAUSE.fullmatch(clause) or _follows_on(clause)) for clause in trailing
    )


def _korean_clauses(folded: str) -> list[str]:
    """``folded``, then each clause of it, read on its own only when the clauses after the first one in request form
    keep the request (`_keeps_the_request`): otherwise only the whole message is read, as on main ("모든 패키지
    업데이트해줘, 패키지마다 changelog도 써줘" and "PR들 전부 리베이스해줘, 급해" run, "PR들 전부 리베이스해줘, 아 잠깐만" does
    not)."""
    clauses = [clause for clause in _CLAUSE_BREAK.split(folded) if clause]
    request = next((index for index, clause in enumerate(clauses) if _korean_request_verb(clause)[0]), len(clauses))
    if request >= len(clauses) - 1 or not _keeps_the_request(clauses[request + 1 :]):
        return [folded]
    return [folded, *clauses]


# What a request may end with besides the work, read off before it is read: one confirmation tag that ends the message
# ("…, ok?", "…, alright?"), and a report on the result, by its opening: tell, ping, notify, message, show or send me,
# let me know, or report (back), alone or followed by which, what, any, the ones, those, each, all, every, when, once,
# after or a result noun, and any words after that ("… and report any that fail", "… and let me know which ones break",
# "…, and send me the ones that fail", "…, then ping me with the results", "…, and notify me when it's done"). Any
# other "let me <verb>" is the person's own step ("…, and let me check with the team first"), and a tail that asks for
# anything before the work or about whether to do it is no report ("…, then tell me why we shouldn't", "…, then tell me the risks first", "…, and tell me what
# would break before you do"): both stay trailing clauses that keep nothing (`_trails_off`).
_FINAL_CONFIRMATION_TAG: Final = re.compile(r"(?:(?<!\s)\s*)?,\s*(?:ok|okay|alright|right)\s*[?？]+\s*$")  # as `_CLAUSE_BREAK`
_DONE_CLAUSE: Final = (
    r"(?:when|once|after)\s+(?:[a-z']+\s+){0,3}?(?:(?:is|are|has|have)\s+)?(?:been\s+|all\s+)?"
    r"(?:done|finished|finishes|complete[ds]?|merged|lands?|landed|green|through|ready|over|deployed|shipped|in|passes"
    r"|passed)\b"
)
_RESULT_NOUN: Final = (
    r"(?:results?|diffs?|links?|list|summary|summaries|counts?|report|status|outcome|changes|numbers?|output|logs?"
    r"|failures?|errors?|files?|tests?|conflicts?|warnings?)"
)
# Deliberation is never a result, by meaning: reasons, objections, concerns, thoughts, opinions, doubts, pros and cons,
# a plan or an approach, risks, alternatives, and the verbs that weigh ("what you think", "which ones you'd recommend").
_DELIBERATION: Final = (
    r"(?:reasons?|objections?|concerns?|thoughts?|opinions?|doubts?|pros|cons|plans?|approach(?:es)?|risks?|alternatives?"
    r"|options?|ideas?|feedback|take|views?|worries|worry|caveats?|trade-?offs?|considerations?|pushback|questions?"
    r"|suggestions?|recommendations?|advice|preferences?|misgivings?|reservations?|hesitations?|qualms?|fears?"
    r"|apprehensions?|feelings?|input|perspectives?|angles?|stance|positions?|viewpoints?|outlook|judg(?:e)?ments?"
    r"|assessments?|evaluations?|estimates?|guess(?:es)?|hunch(?:es)?|instincts?|intuitions?|impressions?|rationale"
    r"|justifications?|arguments?|pitfalls?|downsides?|upsides?|drawbacks?|benefits?|merits?|strategy|strategies"
    r"|proposals?|think|reckon|feel|suggest|recommend|prefer|propose|advise|believe|expect|consider|weigh|suppose"
    r"|imagine|wonder|doubt|favou?r|lean)"
)
# After a quantifier the report's clause turns on its subject. With the targets as the subject (the quantifier
# itself, or that/which/who) any finite verb reports on them, modal or negated too ("which ones break", "any that won't
# build", "every package that needs to be rebuilt", "which ones will break"). With a person as the subject, a modal,
# an intention or a weighing verb asks before the work ("which ones you'd skip", "every branch you plan to delete",
# "which ones we should keep"), while a plain verb reports ("the ones you changed", "every file we touched"). A bare
# infinitive right after the quantifier asks ("which ones to keep", "what to drop").
_PERSON: Final = r"(?:i|you|we|they|he|she)"
_MODAL_OR_INTENT: Final = (
    r"(?:would|could|should|might|must|shall|will|can|may|wo?n'?t|can'?t|couldn'?t|shouldn'?t|wouldn'?t|plans?|planning"
    r"|wants?|intends?|means?|going|gonna|needs?|ha(?:ve|s)|ought)\b"
)
_REPORT_FOLLOWER: Final = (
    r"(?:which|what|any|anything|all|every|each|the\s+ones|those)"
    rf"(?>(?:\s+(?:of\s+)?(?:the\s+)?(?!(?:{_DELIBERATION}|that|which|who|{_PERSON}|to|[a-z]+ed|broke|went|ran|did|made"
    r"|built|wrote)\b)[a-z][\w-]*)?)(?:\s+(?:that|which|who))?"
    rf"(?:\s+(?!(?:to|{_DELIBERATION}|{_PERSON}|ones?)\b)[a-z][\w'-]*"
    rf"|\s+{_PERSON}\s+(?!(?:to|{_DELIBERATION})\b|{_MODAL_OR_INTENT})[a-z][\w-]*)\b"
)
# Anywhere in the tail, a person with a modal or an intention, or deliberation, asks before the work ("which ones
# failed and which you want to retry", "which ones you'd recommend").
_NOT_A_REPORT: Final = re.compile(
    rf"\b{_PERSON}(?:'(?:d|ll)\b|'re\s+going\b|\s+{_MODAL_OR_INTENT})|\b{_DELIBERATION}\b"
)
_REPORT_OPENER: Final = r"(?:(?:tell|ping|notify|message|show|send)\s+me|let\s+me\s+know|report(?:\s+back)?)"
_EN_REPORT_TAIL: Final = re.compile(
    r"(?:,\s*|\s+)(?:and\s+then|and|then)\s+(?:also\s+|just\s+|please\s+)*"
    rf"(?:let\s+me\s+know|report(?:\s+back)?|{_REPORT_OPENER}\s+"
    rf"(?:(?P<done>{_DONE_CLAUSE})|(?:(?:about|on|with|of)\s+)?{_REPORT_FOLLOWER}[^?]*?"
    rf"|(?:with\s+)?(?:(?:the|a|an|all\s+the|any|all)\s+)?(?:[a-z][\w-]*\s+){{0,2}}?{_RESULT_NOUN}\b[^?]*?))"
    r"\s*[.!]*$"
)
_ASKS_BEFORE_THE_WORK: Final = re.compile(
    r"[?？]|\b(?:why|would|should|could|risks?|how\s+(?:you|we|i|to|it)|first|before|beforehand|whether|if|unless)\b"
)


# What follows an English request in a later clause keeps it only as a remark of a keep kind (lead decision (D) on
# the #2243 review). A leaked refusal costs a paid graph start and a missed keeper only an offer, so an unknown remark
# holds; and a keep kind is a word family with light structure, which tolerates intensifiers ("…, thanks a ton",
# "…, cheers mate", "…, so grateful!!"), where the old closed list matched a phrase whole:
# - gratitude (`_GRATITUDE`): "…, thanks a bunch", "…, much obliged", "…, I'd appreciate it", "…, you're the best";
# - a sign-off (`_SIGN_OFF`): "…, have a good one", "…, talk soon", "…, regards";
# - a wish (`_WISH`): "…, fingers crossed", "…, hope it goes smoothly", "…, wish me luck", "…, good luck";
# - a back-reference (`_BACK_REFERENCE`): "…, as discussed", "…, like we agreed", "…, same as last time", "…, per our
#   chat";
# - who asked (`_ATTRIBUTION`): "…, my manager asked for it", "…, legal approved it", "…, requested by QA";
# - an aside marker and the statement after it (`_ASIDE_MARKER`): "…, fwiw the tests are flaky", "…, btw, CI is slow";
# - no pressure (`_NO_PRESSURE`): "…, no worries", "…, take your time", "…, whenever works", "…, not urgent".
# The keepers by shape stay a fast path (`_KEEPER_CLAUSE`: an urgency, a deadline, a start cue, a per-unit spec), and a
# follow-on keeps it too (`_follows_on`). The refusal classes apply first, each by meaning, so a keep kind that carries
# one holds ("…, btw, not sure about this", "…, fwiw last time this broke CI"):
# - a new request (`_EN_ASKS_FOR_MORE`: "…, run the tests", "…, let me check first"), a hold or a joke (`_HOLD`, read
#   on every clause; `_LAUGH_ALONE`), a retraction (`_RETRACTS`; a take-back as the last clause is read on the whole
#   text, `_takes_it_back`), a verb on the request itself (`_ACTS_ON_IT`);
# - a status alone (`_STATUS_ALONE`), something asked before the work (`_BEFORE_THE_WORK`), a warning (`_WARNS`);
# - a hedge about wanting it (`_HEDGE`), thinking aloud (`_THINKING_ALOUD`), a hesitation alone (`_HESITATION`);
# - deliberation (`_WEIGHS`), the decision handed back (`_HANDS_IT_BACK`), a person's modal or intention
#   (`_ASKER_INTENT`), a question (`_QUESTION`);
# - a negation of doing the work (`_NOT_DOING`), or a contrast that turns against the request (`_TURNS_AGAINST`); a
#   negated outcome keeps, and a warning or a retraction said under a negation is none (`_NEGATED_BEFORE`).
# A deferral and a condition are refused before it, on the whole text (`_hard_excluded`; no pressure is read off there
# too, so "…, whenever works" is none). A Korean message keeps the keepers alone, since main reads it whole.
_EN_ASKS_FOR_MORE: Final = re.compile(
    rf"^(?:and\s+|then\s+|also\s+|please\s+|pls\s+|just\s+|so\s+)*(?!let'?s\s+hope\b)(?:{_EN_FOLLOW_ON_VERB}|{_READ_OR_HOLD_VERB}(?!\s+(?:you|ya)\b)"
    r"|(?!(?:wish|bless|excuse)\b)[a-z]+\s+me)\b"
)
_HEDGE: Final = re.compile(
    r"\b(?:ma+y+b+e+|perhaps|probably|possibly|not\s+(?:\w+\s+)?(?:sure|certain|convinced|positive|confident|clear|decided|settled)"
    r"|unsure|uncertain|undecided|indecisive|i\s+guess|i\s+suppose|idk"
    r"|dunno|who\s+(?:knows|can\s+say)|or\s+whatever|or\s+something|kinda|sorta|hmm+|eh|meh|nah|nope|rather\s+not|torn"
    r"|iffy|deciding|uneasy|wary|hesitant|reluctant|skeptical|sceptical|50\s*/\s*50|fifty[-\s]fifty|object(?:ing|ion)?"
    r"|part\s+of\s+me|in\s+two\s+minds|of\s+two\s+minds"
    r"|second[-\s]+(?:thoughts?|guess\w*)|on\s+the\s+fence|not\s+convinced|doubt\w*|scared|nervous|afraid|risky|though"
    r"|ugh|not\s+my\s+call|someone\s+else'?s)\b"
)
# Thinking aloud offers an idea, not a request ("…, thinking out loud", "…, just musing", "…, spitballing"); a
# retraction cancels what was said, by its verb ("…, scrap that", "…, forget I said that", "…, ignore that",
# "…, pretend I didn't say it", "…, on reflection no"); handing the decision back asks before the work ("…, your call",
# "…, up to you", "…, up to the team", "…, you decide"); and a clause that is only a hesitation hesitates ("…, umm",
# "…, welp").
_THINKING_ALOUD: Final = re.compile(
    r"\b(?:think\w*|musing|muse|brainstorm\w*|spitball\w*|toying|ponder\w*|mull\w*|riffing|wondering|weighing|debating"
    r"|consider\w*|inkling|hunch|brainwave|off\s+the\s+top\s+of\s+my\s+head|gut\s+(?:says|feeling|check|call))\b"
)
_RETRACTS: Final = re.compile(
    r"\b(?:scrap\w*|scratch\w*|forget\w*|disregard\w*|ignor\w*|strike|retract\w*|nix\w*|belay|withdraw\w*|pretend\w*|undo\w*"
    r"|cancel\w*|abort\w*|call\w*\s+(?:\w+\s+){0,3}?off|skip\w*|shelv\w*|park\w*|pass\s+on\s+(?:it|this|that)"
    r"|back\w*\s+out|pull\w*\s+(?:out|the\s+plug)|bail\w*|drop\w*\s+(?:it|this|that)|walk\w*\s+(?:it\s+|that\s+)?back"
    r"|rescind\w*|revok\w*"
    r"|hang\s+on|hold\s+up|stand\s*by|sit\s+tight"
    r"|take\s+(?:it|that|this|all\s+that)\s+back|on\s+(?:second\s+thought|reflection))\b"
)
_HANDS_IT_BACK: Final = re.compile(
    r"\byour\s+(?:call|choice|pick|decision|preference)\b|\byou\s+(?:decide|choose|pick)\b|\bup\s+to\s+(?!date\b)\w+"
    r"|\bdealer'?s\s+choice\b|\bwhatever\s+you\b"
)
_HESITATION: Final = re.compile(r"(?:u+h+m*|u+m+|e+r+m*|e+h+|h+m+|h+r+m+|w+e+l+p+|m+e+h+|m{2,}|a+h+|o+o+f+)\W*")
# A verb said on the request itself acts on it, as a retraction or a new request does ("…, shelve it", "…, park it for
# now", "…, scrap it", "…, nix that"), except a wish or thanks ("…, hope it goes smoothly", "…, love it").
_ACTS_ON_IT: Final = re.compile(
    r"^(?:just\s+|maybe\s+|so\s+|and\s+)?(?!(?:hope|hoping|wish|love|bless|thank|thanks|appreciate|may)\b)[a-z]+\s+"
    r"(?:it|that|this|everything|all\s+(?:of\s+)?(?:it|that|this))\b"
)
# A clause that is only a laugh after the work is a joke about it ("…, lol"), while a laugh inside a remark is not
# ("…, long day lol"); a clause that is only a status says the work is done or where it stands ("…: done, done,
# conflict", "…, all done"); and a clause that ends on first or beforehand asks for something before the work ("…, let
# me check first", "…: the billing one first").
_LAUGH_ALONE: Final = re.compile(r"(?:lol|lmao|rofl|haha+|hehe+)\s*[.!]*")
_STATUS_ALONE: Final = re.compile(rf"(?:all\s+|already\s+)?{_STATUS_WORD}(?:\s+already)?\s*[.!]*")
_BEFORE_THE_WORK: Final = re.compile(
    r"\b(?:first|beforehand)\s*[.!]*$|\b(?:need|needs|have|has|got|gotta|want|wanna)\s+(?:to\s+)?(?:confirm|check|verify|validate"
    r"|make\s+sure|double[-\s]?check|ask|clear\s+it|run\s+(?:it|this|that)\s+by|sign\s+off|get\s+(?:sign[-\s]?off|approval|a\s+green))\b"
    r"|\b(?:pending|awaiting|waiting\s+(?:on|for))\b"
)
_WEIGHS: Final = re.compile(rf"(?<!\bper\sthe\s)(?<!\bsame\s)(?<!\bgood\s)\b(?!take\s+care\b|feel\s+free\b){_DELIBERATION}\b")
_ASKER_INTENT: Final = re.compile(
    rf"\b(?:i|you|we)(?:'(?:d|ll)\b|'re\s+going\b|\s+(?!ha(?:ve|s)\s+(?!to\b)){_MODAL_OR_INTENT})"
    r"(?!\s+(?:\w+\s+)?(?:appreciate|be\s+(?:\w+\s+)?(?:grateful|thankful)|owe\s+you)\b)"
)
_QUESTION: Final = re.compile(
    r"[?？]|^(?:what|why|how|which|who|where|whether|is|are|am|was|were|do|does|did|should|shall|could|would(?!\s+love\b)|can|will"
    r"|may(?!\s+(?:the|it|this|our|all|your)\b)|might|must)(?![\w'])|\b(?:curious|wondering|wdyt|wyt|hbu|wbu)\b"
)
# A negation said before a warning or a retraction negates it: "…, hope nothing breaks", "…, fingers crossed we don't
# regress", "…, fyi don't skip any" warn and take back nothing.
_NEGATED_BEFORE: Final = re.compile(
    r"\b(?:not|no|nothing|never|without|\w+n['’]t|dont|wont|cant|doesnt|isnt|wouldnt|shouldnt)\s+(?:\w+\s+){0,2}$"
)
# A warning about the work is no harmless aside ("…, fwiw last time this broke CI", "…, careful, prod is fragile").
_WARNS: Final = re.compile(
    r"\b(?:broke|break(?:s|ing)?|blew\s+up|blow\s+up|went\s+down|outage|incident|regress\w*|careful|beware|watch\s+out"
    r"|caution|danger\w*|yikes|fragile|bricked|bit\s+us|burned\s+us|could|might|(?<=\s)may|los[et]|losing|corrupt\w*|wipe\w*"
    r"|data\s+loss)\b"
)
_GRATITUDE: Final = re.compile(
    r"\b(?:thanks?|thank\s*(?:you|u|ya|ye)|thx|thnx|tnx|tx|ty|tysm|tyvm|ta|cheers|appreciat\w*|grateful|thankful|obliged"
    r"|kudos|much\s+love|bless\s+you|you\s+rock|you(?:'re|\s+are)\s+(?:the\s+best|a\s+(?:star|legend|lifesaver|gem|hero))"
    r"|legend|lifesaver|owe\s+you|(?:big|much|so\s+much)\s+love|props|shout[-\s]?out|hats\s+off|bear\s+with\s+(?:me|us))\b"
    r"|^(?:awesome|amazing|great|perfect|nice|sweet|lovely|brilliant|excellent|wonderful|fantastic)\W*$"
)
_SIGN_OFF: Final = re.compile(
    r"\b(?:have\s+a\s+(?:\w+\s+)?(?:one|day|weekend|evening|night|week|afternoon|morning)|talk\s+soon|ttyl|signing\s+off"
    r"|regards|best\s+wishes|all\s+the\s+best|take\s+care|see\s+(?:ya|you)|cya|bye|good\s*night|peace\s+out"
    r"|over\s+and\s+out|(?:catch|see|talk|speak)\s+(?:you\s+|ya\s+)?later|laters|later\s+gators?)\b"
    r"|^(?:hey|hi|hello|hiya|yo|howdy|morning|good\s+(?:morning|afternoon|evening))\b"
)
_WISH: Final = re.compile(
    r"^(?:i\s+|we\s+|and\s+|so\s+|let'?s\s+)?(?:(?:really|so|truly|just|sure)\s+)?(?:hope|hoping|here'?s\s+hoping|wish|wishing"
    r"|(?:(?:keeping|keep|got)\s+(?:my\s+|our\s+|the\s+)?)?(?:fingers|toes)\s+(?:\w+\s+){0,2}crossed|pray\w*|knock\s+on\s+wood|touch\s+wood"
    r"|(?:good|best\s+of)\s+luck|(?:i'?d\s+|would\s+)love|keen|excited|eager|stoked|can'?t\s+wait|looking\s+forward|wouldn'?t\s+mind"
    r"|optimistic|(?:got\s+a\s+)?good\s+feeling|feeling\s+(?:good|positive|optimistic)|here'?s\s+to|may\s+(?:the|it|this|our|all|your)"
    r"|cheers\s+to)\b"
)
_BACK_REFERENCE: Final = re.compile(
    r"\b(?:as|like|per|what|how|the\s+way)\s+(?:(?:we|i|you|they)\s+(?:\w+\s+)?(?:discussed|agreed|said|mentioned|planned|talked|decided"
    r"|spoke|chatted|covered|sorted|settled|aligned|landed|went\s+over|figured|mapped|outlined|scoped|laid)|(?:discussed|agreed"
    r"|mentioned|planned|promised|usual|always|before))\b"
    r"|\b(?:we|i|they)\s+(?:all\s+|both\s+)?(?:agreed|discussed|settled|landed|decided|hashed|sketched|mapped|laid|planned|talked"
    r"|chatted|covered|sorted|aligned|figured|went\s+over|outlined|scoped|whiteboarded|spec'?d)\b"
    r"|\b(?:like|as|per)\s+the\s+\w+\s+(?:says|said|states|describes|spells\s+out)\b"
    r"|\b(?:same\s+(?:\w+\s+)?as|like)\s+(?:(?:the\s+)?(?:last|earlier|previous|prior|original|usual)\s+\w+|before|usual|always)\b"
    r"|\bsame\s+(?:\w+\s+)?as\s+the\s+\w+|\b(?:as|like)\s+in\s+the\s+\w+"
    r"|\bfollowing\s+(?:up\s+on|the\s+\w+)\b|\bper\s+(?:our|the|my|your|yesterday'?s|today'?s|last\s+week'?s)\s+\w+"
    r"|\b(?:consistent|in\s+line|in\s+keeping)\s+with\b|\b(?:like|as)\s+(?:we|i|they)\s+(?:did|do|handled|did\s+it)\b"
    r"|^agreed\s+(?:in|at|during|over)\s+(?:the\s+)?\w+"
)
_ATTRIBUTION: Final = re.compile(
    r"^(?!(?:i|we|you)\b)(?:\w+(?:'s)?\s+){1,4}?(?:asked|requested|wants?|wanted|needs?|needed|approved|okayed|ok'?d|signed\s+off"
    r"|flagged|greenlit|insisted|ordered|mandated|cleared|blessed|backed|endorsed|sanctioned|authori[sz]ed|said|says|told)\b"
    r"|\b(?:as\s+)?(?:requested|approved|okayed|signed\s+off|cleared|blessed|backed|endorsed|ordered|mandated|greenlit"
    r"|authori[sz]ed|asked\s+for)\s+(?:by|in)\b|\bper\s+\w+'?s\s+request\b|\b\w+'?s\s+orders\b|\bgave\s+(?:it\s+|this\s+)?the\s+nod\b"
    r"|^(?!(?:i|we|you)\b)(?:\w+(?:'s)?\s+){1,4}?(?:is|are|'s|'re)\s+(?:fine|ok|okay|good|happy|cool)\s+with\s+(?:it|this|that)\b"
    r"|^(?!(?:it|that|this|there|what|who)'s)\w+'s\s+(?:fine|ok|okay|good|happy|cool)\s+with\s+(?:it|this|that)\b"
    r"|\b(?:it|this|that|the\s+\w+)\s+(?:came|comes|is|'s)\s+(?:straight\s+|directly\s+)?from\s+(?:the\s+)?\w+|\bit'?s\s+from\s+(?:the\s+)?\w+"
    r"|\b(?:gave|got|has|have|had)\s+(?:\w+\s+)?(?:green\s*light|thumbs\s+up|go[-\s]ahead|blessing|sign[-\s]?off|ok|okay)\b"
    r"|\bper\s+(?:the\s+)?(?:cto|ceo|cfo|vp|pm|po|boss|lead|manager|team|qa|legal|security|client|customer|product|design|ops)\b"
    r"|\b(?!(?:my|our|your)\b)\w+'s\s+(?:request|ask|call|orders?)\b|\bat\s+(?:the\s+)?(?:\w+'s\s+)?request(?:\s+of)?\b"
    r"|\bon\s+behalf\s+of\b|\b(?:it'?s|this\s+is|that'?s|all)\s+for\s+(?:the\s+)?\w+"
    r"|^for\s+(?:the\s+)?(?:\w+\s+)?(?:team|cto|ceo|pm|po|lead|manager|client|customer|boss|qa|legal|security|audit|release|launch|demo"
    r"|board|folks|squad|crew|org)\b"
)
# A contrast followed by a negation turns against the request ("…, fingers crossed but let's not", "…, thanks but
# no", "…, approved by the CTO but not yet").
_TURNS_AGAINST: Final = re.compile(
    r"\b(?:but|though|although|however|except|yet)\b[^,;]*?\b(?:not|no|never|nope|nah|\w+n['’]t|dont|wont|cant)\b"
)
# An aside marker, by meaning: the remark that follows is on something else ("…, fyi …", "…, btw …", "…, also …", "…, oh
# and …", "…, off topic, …", "…, random but …", "…, tangent, …", "…, unrelated but …", "…, on another note, …",
# "…, incidentally …").
_ASIDE_MARKER: Final = re.compile(
    r"^(?:just\s+(?:an?\s+)?|oh\s+)?(?:fyi|btw|by\s+the\s+way|ps|psa|p\.s\.?|(?:side|quick|random)\s*note|note|for\s+what\s+it'?s\s+worth"
    r"|fwiw|for\s+the\s+record|heads\s+up|nb|jsyk|just\s+so\s+you\s+know|fun\s+fact|(?:random\s+|quick\s+)?aside|also|and\s+also"
    r"|oh\s+and|off[-\s]topic|random(?:ly)?(?:\s+but)?|tangent(?:ially)?|(?:totally\s+|completely\s+)?unrelated(?:ly)?(?:\s+but)?"
    r"|not\s+related(?:\s+but)?|on\s+(?:an)?other\s+note|on\s+a\s+(?:side|different|separate|lighter|related)\s+note|incidentally"
    r"|separately|in\s+other\s+news|speaking\s+of\s+which)\b"
)
# A sign-off that says later, a back-reference to before and a plan named are no deferral, take-back, condition or
# deliberation ("…, catch you later", "…, later gators", "…, same deal as before", "…, following the plan from last
# sprint"): they are read off before the whole-text checks and the refusals, as no pressure is.
_KEEP_IDIOM: Final = re.compile(
    r"\b(?:(?:catch|see|talk|speak)\s+(?:you\s+|ya\s+)?later|laters|later\s+gators?|(?:same\s+(?:\w+\s+)?as|like)\s+before"
    r"|(?:the|our|same)\s+plan(?:\s+from\s+(?:last\s+)?\w+)?)\b"
)
# No pressure is no refusal, whatever words it borrows from one ("…, no worries", "…, take your time", "…, whenever
# works", "…, nothing urgent"): it is read off before the refusals are, and before the whole-text condition.
_NO_PRESSURE: Final = re.compile(
    r"\b(?:(?:no|zero|0)\s+(?:\w+\s+)?(?:rush|pressure|worries|hurry|stress|problem|biggie|big\s+deal|panic|drama|urgency"
    r"|deadline|hard\s+deadline|eta|timeline)"
    r"|not\s+(?:urgent|a\s+big\s+deal|in\s+a\s+(?:hurry|rush))|nothing\s+(?:urgent|pressing)|take\s+your\s+(?:sweet\s+)?time"
    r"|all\s+good(?:\s+on\s+\w+)?|breathing\s+room|plenty\s+of\s+time|don'?t\s+sweat(?:\s+(?:it|the\s+\w+))?"
    r"|(?:go\s+)?at\s+(?:your|whatever|any|its)\s+(?:own\s+)?(?:pace|leisure|convenience|speed)(?:\s+works)?|easy\s+does\s+it"
    r"|low\s+prio(?:rity)?|(?:chill|relaxed|easy|loose|flexible)\s+(?:pace|timeline|deadline|schedule)(?:\s+is\s+fine)?"
    r"|(?:chill|relaxed|easygoing|easy-going)(?:\s+about\s+(?:\w+\s+){0,2}\w+)?"
    r"|happy\s+(?:for\s+it\s+)?to\s+(?:wait|take\s+(?:a\s+bit|a\s+while|its\s+time|longer)))\b"
    r"(?:\s+(?:on|with|for|about)\s+(?:this|it|that)(?:\s+one)?\b)?(?:\s+(?:honestly|really|seriously|tbh|either))?|\bwhenever\b[^,;]*"
)


# Negating or abandoning the work itself, which a wish never excuses ("…, here's to not doing it", "…, cheers to not
# touching it", "…, here's to leaving it alone", "…, hope we just let it be"); a negated outcome is no such thing
# ("…, here's to no conflicts", "…, hope it doesn't break").
# The verbs of an outcome rather than of the work: a negation of one negates what might go wrong, not doing the work
# ("…, hope nothing breaks", "…, hope we don't regress"). `_NOT_DOING` and `_NO_WORK_ASKED` both except them.
_OUTCOME_VERB: Final = r"(?:fail|break|crash|explod|regress|flak|conflict|tim|blow|los|corrupt|wip|leak)\w*"
# Thanks whose object is a negation mocks ("…, thanks for nothing", "…, cheers for nothing, really", "…, ty for no help"),
# except thanks for an outcome that did not happen ("…, thanks for not breaking prod").
_MOCKED_THANKS: Final = re.compile(
    r"\b(?:thanks?|thank\s+(?:you|u|ya)|thx|cheers|ta|ty)\s+(?:\w+\s+){0,2}?for\s+(?:nothing|none|nada|zilch|no\s+help|zero\s+help"
    rf"|not\b(?!\s+(?:\w+\s+)?{_OUTCOME_VERB}))"
)
_NOT_DOING: Final = re.compile(
    rf"\bnot\s+(?:even\s+|just\s+|really\s+)?(?!{_OUTCOME_VERB})"
    r"(?:\w+ing|do|touch|bother|start|proceed|ship|merge|run)\b"
    r"|\bnot\s+(?:yet|now|today|tonight|right\s+now|anymore|this\s+(?:time|sprint|week))\b|\blet'?s\s+not\b|\bno\s+thank(?:s|\s+you)\b"
    r"|\b(?:not|never|\w+n['’]t)\b[^,;.]*\byet\b"
    r"|\b(?:haven'?t|hasn'?t|have\s+not|has\s+not|didn'?t|not)\s+(?:\w+\s+)?(?:cleared|checked|confirmed|verified|asked|validated"
    r"|tested|approved|signed\s+off|run\s+it\s+by)\b"
    r"|\bdon'?t\s+(?:bother|start|proceed|go\s+ahead|do\s+(?:it|this|that|anything)|touch\s+(?:it|this|that|them|anything))\b"
    r"|\b(?:we|i|you)\s+(?:won'?t|wouldn'?t|don'?t|shouldn'?t|can'?t|do\s+not|will\s+not)\s+(?:need|have|want|bother|do|go|start"
    r"|touch|proceed|run|ship|merge)\b"
    r"|\b(?:asked|told|want|wants|wanted)\s+(?:us|me|you)\s+not\s+to\b|\bhold\s+off\b|\bno\s+need\b(?!\s+to\s+(?:rush|hurry|stress))"
    r"|\b(?:nobody|no[-\s]?one|not\s+a\s+soul|none\s+of\s+(?:us|them|the\s+\w+)|not\s+(?:a\s+single|one)(?:\s+\w+)?"
    r"|neither(?:\s+of\s+(?:us|them))?)(?:\s+(?:on|in|from|at|of)\s+(?:the\s+)?\w+(?:\s+\w+)?)?"
    r"\s+(?:(?:has|have|had|ever|actually|really|even)\s+)*(?:asked|wants|wanted|needs|needed|requested|said|says|told|gave"
    r"|given|approved|signed\s+off|okayed|ok'?d|greenlit|cleared|agreed|blessed)\b"
    r"|\blea(?:ve|ving)\s+(?:it|this|that|them|everything)(?:\s+(?:alone|be|as\s+is|untouched|for\s+now))?\s*[.!]*$"
    r"|\blea(?:ve|ving)\s+(?:it|this|that|them|everything)\s+(?:alone|be|as\s+is|untouched|for\s+now)\b"
    r"|\blet(?:ting|s)?\s+(?:\w+\s+){1,3}?(?:be|lie|slide)\b|\bnever\s+(?:touch|do|bother|start|run|ship|merge)\w*"
)


def _unnegated(pattern: re.Pattern[str], text: str) -> bool:
    """Whether ``pattern`` matches ``text`` somewhere no negation said just before it negates (`_NEGATED_BEFORE`)."""
    return any(not _NEGATED_BEFORE.search(text[: match.start()]) for match in pattern.finditer(text))


# A flat refusal said on its own ("…, btw, no", "…, my manager asked: no", "…, hard pass").
_FLAT_REFUSAL: Final = re.compile(
    r"(?:no+|nope|nah|no\s+way|absolutely\s+not|not\s+a\s+chance|not\s+happening|hard\s+pass|count\s+(?:me|us)\s+out"
    r"|no\s+can\s+do|none\s+of\s+it|veto(?:ed)?|denied|rejected|negative|nope\s+nope)\W*"
)
# Reported speech sets off what a third party said, wanted or told us ("ops said go", "the lead told us to go ahead",
# "the client wants it done"), read on to the next follow-on request (`_without_an_unapproved_report`). A negator before
# the reporting verb holds whatever was said ("…, nobody said yes", "…, ops never said go"). The reported object is read
# by the kinds a bare remark is (`_reported_object_keeps`): a clean approval keeps (`_APPROVAL`: "…, legal said a big
# yes", "…, ops says totally fine!", "…, the client wants it by friday"), and so do thanks, a greeting, a sign-off and a
# wish ("…, the lead said thanks for picking it up", "…, the PM says hi", "…, the lead said good luck"); after an aside
# marker a plain statement keeps too ("…, fwiw QA says the suite is faster now"). A refusal or a hedge holds ("…, QA
# says hard no", "…, fyi the lead said meh"), and so does sarcasm: a mocking idiom (`_MOCKING`: "…, the lead said yeah
# right", "…, ops said sure, good luck with that"), or an approval dressed in filler or said twice ("…, the lead said oh
# sure", "…, QA said yeah yeah", "…, QA said great idea… not"). Anything else reported holds ("…, ops said something
# about the docs"). Asking for it is no reported speech ("…, my manager asked for it" keeps as an attribution), and
# neither is a relative what ("…, hope it's what the PM wants" keeps as a wish).
_REPORTED_SPEECH: Final = re.compile(
    r"\b(?:said|says|saying|told\s+(?:us|me|them)|tells\s+(?:us|me)|wants|wanted)\b(?:\s+that\b(?!'))?\s*[:,]?\s*"
)
_SPEAKER_BACK_REFERENCE: Final = re.compile(r"\b(?:as|like|what|how)\s+(?:i|we|you|they)\s+(?:\w+\s+)?$")
_RELATIVE_WHAT: Final = re.compile(r"\bwhat(?:ever)?\s+(?:\w+(?:'s)?\s+){0,3}$")
_ATTRIBUTION_VERB: Final = re.compile(
    r"\b(?:gave|give[sn]?|sign(?:ed|s)?\s+off|clear(?:ed|s)?|approv(?:ed|es|e)|okay(?:ed|s)?|ok'?d|greenl(?:it|ight(?:ed|s)?)"
    r"|bless(?:ed|es)?)\b"
)
_NEGATOR: Final = re.compile(
    r"\b(?:nobody|no\s*one|none|not|never|neither|nor|\w+n['’]t|dont|didnt|doesnt|hasnt|havent|wont|cant|wasnt)\b"
)
_APPROVAL_INTENSIFIER: Final = (
    r"(?:big|huge|firm|clear|total|totally|absolutely|definitely|fully|super|very|really|so|quite|100%|resounding|solid"
    r"|strong|full|enthusiastic|happy|hearty|emphatic|honestly|seriously|truly|for\s+sure|of\s+course|tbh|ngl|all)"
)
_APPROVAL_AROUND: Final = rf"(?:{_APPROVAL_INTENSIFIER}|too|already|now|asap|today|then)"
_APPROVAL_SEP: Final = r"(?:\s*[,;.!…—–]+\s*|\s+)"
# A one-word assent stands at most once, first ("…, QA said yes, absolutely", "…, ops said ok, ship it"); said twice it
# is sarcasm ("…, the PM said sure, sure", "…, the lead said yeah, sure").
_APPROVAL_ASSENT: Final = (
    r"(?:yes+|yep|yeah|yup|sure|ok(?:ay)?|fine|good|great|cool|nice|perfect|awesome|sweet|excellent|brilliant|lovely"
    r"|amazing|fantastic|wonderful)"
)
_APPROVAL_WORD: Final = (
    r"(?:go(?:\s+(?:for\s+it|ahead|nuts|wild))?|go[-\s]ahead|approved?"
    r"|lgtm|ship\s+it|do\s+it|let'?s\s+(?:go|do\s+it)|make\s+it\s+happen|green\s*light|thumbs\s+up|(?:full\s+)?steam\s+ahead"
    r"|all\s+good|so|good\s+to\s+go|(?:the\s+)?(?:blessing|sign[-\s]?off|nod)"
    r"|(?:it'?s|that'?s|this\s+is|all|we'?re|they'?re|everything'?s|it\s+is|we\s+are)\s+"
    rf"(?:{_APPROVAL_INTENSIFIER}\s+)?(?:fine|good|ok(?:ay)?|clear|set|great|cool|a\s+go|approved|green|good\s+to\s+go)"
    rf"|sounds?\s+(?:{_APPROVAL_INTENSIFIER}\s+)?(?:good|great|fine)"
    r"|(?:(?:he|she|they|we|i)(?:'s|'re|'m|\s+is|\s+are|\s+am)\s+)?(?:on\s+board|in|good\s+with\s+it|fine\s+with\s+it|happy\s+with\s+it)"
    r"|(?:it|this|that|them)(?:\s+(?:done|shipped|merged|fixed|in))?|👍|✅)"
)
# When or what for the approval is ("…, the client wants it by friday", "…, the PM wants this this sprint", "…, the
# lead wants it done in Q3", "…, ops said yes for the release").
_APPROVAL_TAIL: Final = (
    r"(?:by\s+(?:the\s+)?(?:end\s+of\s+(?:the\s+)?)?(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day|day|week|month|sprint|quarter"
    r"|eod|eow|tonight|tomorrow)|this\s+(?:sprint|week|month|quarter|cycle|iteration)|in\s+q[1-4]"
    r"|for\s+(?:the\s+|this\s+|our\s+)?(?:release|launch|demo|milestone|deploy(?:ment)?|cut|freeze|sprint))"
)
_APPROVAL: Final = re.compile(
    rf"(?:(?:(?:us|me|them|him|her|you)\s+)?to\s+)?(?:{_APPROVAL_AROUND}{_APPROVAL_SEP})*"
    rf"(?:(?:a|an|the|their|his|her)\s+(?:{_APPROVAL_INTENSIFIER}{_APPROVAL_SEP})*)?"
    rf"(?:{_APPROVAL_ASSENT}|{_APPROVAL_WORD})"
    rf"(?:{_APPROVAL_SEP}(?:{_APPROVAL_AROUND}|{_APPROVAL_WORD}|{_APPROVAL_TAIL}))*[\s.!,;:)…]*"
)
# An object that opens like an approval and is no clean one is dressed: filler before it, an assent said twice, or a
# word after it ("…, ops said oh fine", "…, the PM said sure 🙄", "…, the lead said ok, sure, totally").
_APPROVAL_LEAD: Final = re.compile(
    rf"(?:oh|ah|well|um+|uh+|hm+|{_APPROVAL_ASSENT}|go|go[-\s]ahead|approved?|lgtm|ship\s+it|do\s+it|green\s*light"
    r"|thumbs\s+up)(?![\w'])|👍|✅"
)
_MOCKING: Final = re.compile(
    r"\b(?:yeah\s+right|in\s+your\s+dreams|dream\s+on|as\s+if|nice\s+try|said\s+no\s+one"
    r"|(?:good\s+luck|have\s+fun)\s+with\s+that|over\s+my\s+dead\s+body|when\s+pigs\s+fly|not\s+in\s+a\s+million\s+years)\b"
    r"|(?:^|\s)/s\b|🙄|😒|🙃"
)
# A part that is only an assent is never thanks, even said twice ("…, QA said great, great", "…, the PM said nice,
# nice"); a reported wish keeps only as a wish alone or a wish that the work goes well (`_REPORTED_WISH`: "…, the lead
# said good luck", "…, QA said hope the rollout is smooth"), so a wish with anything else after it holds ("…, the PM
# said good luck lol", "…, legal said best of luck explaining that", "…, ops said hope you enjoy debugging").
_ASSENT_ALONE: Final = re.compile(rf"(?:{_APPROVAL_INTENSIFIER}\s+)?{_APPROVAL_ASSENT}[\s.!…]*")
_REPORTED_WISH: Final = re.compile(
    rf"(?:(?:{_APPROVAL_INTENSIFIER}|so|just)\s+)*(?:good\s+luck|best\s+of\s+luck|(?:fingers|toes)\s+crossed|break\s+a\s+leg"
    r"|godspeed|knock\s+on\s+wood|touch\s+wood)(?:\s+(?:to\s+(?:you|us|all|everyone)|with\s+the\s+(?:\w+\s+)?(?:rollout|migration"
    r"|release|deploy(?:ment)?|launch|upgrade|rebase|work|change|refactor|rewrite)))?[\s.!…]*"
    r"|(?:i\s+|we\s+)?(?:hope|hoping|wish(?:ing)?)\s+(?:it|this|that|everything|all|the\s+\w+(?:\s+\w+)?)\s+(?:goes|go|went|runs?"
    r"|lands?|is|are|stays?|will\s+(?:go|be|run|land))\s+(?:\w+\s+)?(?:well|smooth(?:ly)?|fine|great|green|clean(?:ly)?|ok(?:ay)?"
    r"|to\s+plan)[\s.!…]*"
)
# Under an aside a reported statement that blocks the work holds (`_reported_blocks`):
# - any negated copula or auxiliary, whatever follows ("…, btw legal says the contract isn't signed", "…, fyi ops says
#   staging isn't up", "…, btw the CFO said the budget isn't there"), except a negated problem or outcome, which is good
#   news ("…, fwiw QA says it isn't a problem", "…, btw ops says it won't break anything");
# - reluctance ("…, fwiw the CTO said she'd rather we didn't", "…, btw the lead said he'd sooner we waited");
# - a blocking status said of anything (frozen, blocked, locked down, on hold, paused, over budget, not ready);
# - a status word that is also good news only with its subject: a person who is out, off, away or sick ("…, fyi the
#   lead said she's out today"), or a system that is down, offline, frozen or locked ("…, btw ops says the cluster is
#   down"), while a work item keeps ("…, btw ops says the fix is out", "…, fwiw QA said the old ticket is closed",
#   "…, fyi the error rate is down").
_PROBLEM: Final = (
    rf"(?:{_OUTCOME_VERB}|(?:(?:be|been|really|actually|even|that|too|going\s+to\s+be|gonna\s+be|much\s+of|such)\s+)*"
    r"(?:an?\s+|any\s+)?(?:big\s+|real\s+|major\s+|huge\s+)?(?:problems?|issues?|blockers?|blocking|deal|urgent|broken|failing"
    r"|worry|worries|concerns?|risky|risks?|dealbreaker|showstopper|flaky|dangerous))"
)
_NEGATED_STATE: Final = re.compile(
    r"\b(?:isn'?t|aren'?t|wasn'?t|weren'?t|hasn'?t|haven'?t|won'?t|can'?t|cannot|doesn'?t|don'?t|didn'?t|is\s+not|are\s+not"
    rf"|was\s+not|were\s+not|has\s+not|have\s+not|will\s+not|does\s+not|did\s+not)\b(?!\s+{_PROBLEM}\b)"
)
_RELUCTANCE: Final = re.compile(
    r"\b(?:rather|sooner)\s+(?:not|we|they|you)\b|\bprefer(?:s|red)?\s+(?:not|we|us|they|you|to\s+(?:not|wait|hold)|waiting)\b"
)
_COPULA: Final = r"(?:\s+(?:is|are|was|were|will\s+be|stays?|remains?)|'s|'re)\s+(?:still\s+|currently\s+|now\s+|totally\s+|completely\s+|all\s+)?"
_BLOCKING_STATUS: Final = re.compile(
    r"(?:\b(?:is|are|was|were|be|been|stays?|remains?|still|now|currently)|'s|'re)\s+(?:still\s+|currently\s+|now\s+|totally\s+"
    r"|completely\s+|all\s+)?(?:frozen|blocked|locked\s+down|on\s+hold|paused|over\s+budget|not\s+ready)\b"
)
_WORK_ITEM: Final = (
    r"(?:fix(?:es)?|builds?|releases?|tickets?|bugs?|incidents?|prs?|pull\s+requests?|issues?|migrations?|patch(?:es)?|hotfix(?:es)?"
    r"|versions?|updates?|changes?|features?|errors?|error\s+rate|alerts?|outage|it|everything|that|this)"
)
_PERSON_AWAY: Final = re.compile(
    r"(?:she|he|they|i|we|(?:the\s+|our\s+|my\s+)?(?:lead|tech\s+lead|team\s+lead|pm|po|cto|ceo|cfo|vp|manager|boss|owner"
    rf"|reviewer|approver|on-?call|maintainer|admin|dba|sre|engineer|designer|team)|(?!(?:the|a|an|our|my|their|this|{_WORK_ITEM})\b)"
    rf"[a-z][\w-]*){_COPULA}(?:out|off|away|sick|ooo|on\s+(?:leave|vacation|pto))\b"
)
_SYSTEM_DOWN: Final = re.compile(
    r"(?:(?:the|our|all)\s+)?(?:prod(?:uction)?|staging|dev|ci|cd|main|master|pipelines?|clusters?|db|databases?|deploys?"
    r"|deployments?|(?:build\s+)?servers?|registry|env(?:ironment)?s?|infra|vpn|runners?|\w+\s+(?:server|cluster|env|environment|db"
    rf"|database)){_COPULA}(?:down|offline|frozen|locked)\b"
)


def _reported_blocks(reported: str) -> bool:
    """Whether a reported statement said under an aside blocks the work: a negated state, reluctance, a blocking
    status, or a status word that is also good news said of a person away or a system down."""
    return bool(
        _NEGATED_STATE.search(reported)
        or _RELUCTANCE.search(reported)
        or _BLOCKING_STATUS.search(reported)
        or _PERSON_AWAY.match(reported)
        or _SYSTEM_DOWN.match(reported)
    )


def _reported_object_keeps(reported: str, aside: bool) -> bool:
    """Whether what a third party is reported to have said keeps the request, read by the kinds a bare remark is: a
    clean approval (`_APPROVAL`), thanks, a greeting, a sign-off or a clean wish (`_REPORTED_WISH`) in every part, a part
    that is only an assent never counting as thanks (`_ASSENT_ALONE`), or after an aside marker a plain statement that
    neither opens like an approval (`_APPROVAL_LEAD`) nor blocks the work (`_reported_blocks`); never a mocking idiom
    (`_MOCKING`) or a part that refuses (`_refuses`). Anything else holds."""
    if _MOCKING.search(reported):
        return False
    if _APPROVAL.fullmatch(reported):
        return True
    parts = [part for part in _CLAUSE_BREAK.split(reported) if part]
    if not parts or any(_refuses(part) for part in parts):
        return False
    if any(_WISH.match(part) and not _REPORTED_WISH.fullmatch(part) for part in parts):
        return False
    if all(
        not _ASSENT_ALONE.fullmatch(part) and (_GRATITUDE.search(part) or _SIGN_OFF.search(part) or _WISH.match(part))
        for part in parts
    ):
        return True
    return aside and not _APPROVAL_LEAD.match(reported) and not _reported_blocks(reported)


def _without_an_unapproved_report(trailing: list[str]) -> list[str] | None:
    """``trailing`` with what a third party is reported to have said read as one object, on to the next follow-on request
    (`_REPORTED_SPEECH`, `_follows_on`), and kept only as its reporting clause; None when a negator stands before the
    reporting verb or an attribution verb (`_NEGATOR`, `_ATTRIBUTION_VERB`: "…, no one on the team gave the go-ahead") or
    the object does not keep (`_reported_object_keeps`). A speaker's own back-reference
    and a relative what report nothing ("…, as I said, …", "…, like the ticket says", "…, hope it's what the PM
    wants")."""
    kept: list[str] = []
    index = 0
    aside = False
    while index < len(trailing):
        clause = trailing[index]
        aside = aside or bool(_ASIDE_MARKER.match(clause))
        attributed = _ATTRIBUTION_VERB.search(clause)
        if attributed and _NEGATOR.search(clause[: attributed.start()]):
            return None
        said = _REPORTED_SPEECH.search(clause)
        before = clause[: said.start()] if said else ""
        reported = clause[said.end() :].strip() if said else ""
        if (
            not said
            or _SPEAKER_BACK_REFERENCE.search(before)
            or _RELATIVE_WHAT.search(before)
            or (not reported and _BACK_REFERENCE.search(clause))
        ):
            kept.append(clause)
            index += 1
            continue
        if _NEGATOR.search(before):
            return None
        end = next((later for later in range(index + 1, len(trailing)) if _follows_on(trailing[later])), len(trailing))
        if not _reported_object_keeps(", ".join(part for part in (reported, *trailing[index + 1 : end]) if part), aside):
            return None
        kept.append(clause)
        index = end
    return kept


def _statement_refuses(clause: str) -> bool:
    """Whether the statement a keep kind's opener sets off with a colon or a dash refuses, read on its own as an
    aside's is: after a toast or a wish (`_WISH`), a back-reference (`_BACK_REFERENCE`) or an attribution
    (`_ATTRIBUTION`) ("…, legal's request: leave it alone", "…, as discussed: hold off"). An object said straight on
    is read with its opener (`_refuses` on the whole clause, `_NOT_DOING`), since its first word is no verb ("…, may
    the build be green")."""
    for opener in (_WISH.match(clause), _BACK_REFERENCE.search(clause), _ATTRIBUTION.search(clause)):
        if not opener:
            continue
        rest = clause[opener.end() :]
        set_off = _STATEMENT_SET_OFF.match(rest)
        if set_off and rest[set_off.end() :].strip() and _refuses(rest[set_off.end() :].strip()):
            return True
    return False


_STATEMENT_SET_OFF: Final = re.compile(r"\s*[:;—–]\s*|\s+-\s+")


def _refuses(clause: str) -> bool:
    """Whether a trailing English ``clause`` carries a refusal class: a laugh, a status or a hesitation that is the whole
    clause, or any other class once no pressure and the keep idioms are read off. A negation refuses only when it
    negates doing the work (`_NOT_DOING`) or turns against the request after a contrast (`_TURNS_AGAINST`); a negated
    outcome, side effect or constraint keeps ("…, hope nothing breaks", "…, btw it won't touch prod", "…, fwiw no
    exceptions")."""
    bare = _KEEP_IDIOM.sub("", _NO_PRESSURE.sub("", clause)).strip()
    return bool(
        _LAUGH_ALONE.fullmatch(clause)
        or _FLAT_REFUSAL.fullmatch(clause)
        or _MOCKED_THANKS.search(clause)
        or _STATUS_ALONE.fullmatch(clause)
        or _HESITATION.fullmatch(clause)
        or _EN_ASKS_FOR_MORE.match(bare)
        or _BEFORE_THE_WORK.search(bare)
        or _unnegated(_WARNS, bare)
        or _HEDGE.search(bare)
        or _THINKING_ALOUD.search(bare)
        or _unnegated(_RETRACTS, bare)
        or _HANDS_IT_BACK.search(bare)
        or _ACTS_ON_IT.match(bare)
        or _WEIGHS.search(bare)
        or _ASKER_INTENT.search(bare)
        or _QUESTION.search(bare)
        or _NOT_DOING.search(bare)
        or _TURNS_AGAINST.search(bare)
    )


# A clause that is only an intensifier adds nothing of its own ("…, you rock, seriously!!", "…, thanks, truly").
_INTENSIFIER_ALONE: Final = re.compile(r"(?:seriously|honestly|truly|really|totally|for\s+real|fr|ngl|tbh|so\s+much|a\s+lot)\W*")


def _of_a_keep_kind(clause: str) -> bool:
    """Whether a trailing English ``clause`` is a remark of a keep kind, or only an intensifier."""
    return bool(
        _INTENSIFIER_ALONE.fullmatch(clause)
        or _GRATITUDE.search(clause)
        or _SIGN_OFF.search(clause)
        or _WISH.match(clause)
        or _BACK_REFERENCE.search(clause)
        or _ATTRIBUTION.search(clause)
        or _NO_PRESSURE.search(clause)
    )


def _remarks_keep_the_request(trailing: list[str]) -> bool:
    """Whether the clauses after an English request keep it: each is a keeper by shape (`_KEEPER_CLAUSE`), a follow-on
    (`_follows_on`) or a remark of a keep kind with no refusal in it, and an aside marker opens a statement that runs to
    the message's end with no refusal in it (`_ASIDE_MARKER`), where a new request is read by the follow-on rule ("…,
    also, fix the lint" holds as before). What a third party is reported to have said keeps only as an approval as a
    whole (`_without_an_unapproved_report`). No clause may hold or joke (`_HOLD`); anything else holds."""
    reported = _without_an_unapproved_report(trailing)
    if reported is None:
        return False
    trailing = reported
    for index, clause in enumerate(trailing):
        if _HOLD.search(clause):
            return False
        if _ASIDE_MARKER.match(clause):
            statements = [_ASIDE_MARKER.sub("", rest, count=1).strip() for rest in trailing[index:]]
            return not any(
                _HOLD.search(rest) or (not _follows_on(statement) and _refuses(statement))
                for rest, statement in zip(trailing[index:], statements)
            )
        if not (
            _KEEPER_CLAUSE.fullmatch(clause)
            or _follows_on(clause)
            or (_of_a_keep_kind(clause) and not _refuses(clause) and not _statement_refuses(clause))
        ):
            return False
    return True


def _closed(folded: str) -> tuple[str, str]:
    """``folded`` read two ways: the request, with a confirmation tag that ends it and a report on the result after a
    change read off (`_FINAL_CONFIRMATION_TAG`, `_EN_REPORT_TAIL`); and the whole text for the hard excludes, with only
    that report's own time clause read off ("…, and notify me when it's done": that when is the report's)."""
    untagged = _FINAL_CONFIRMATION_TAG.sub("", folded, count=1)
    tail = _EN_REPORT_TAIL.search(untagged)
    if not tail or _NOT_A_REPORT.search(tail.group()) or _ASKS_BEFORE_THE_WORK.search(tail.group()) or _HOLD.search(tail.group()):
        return untagged, folded
    head = untagged[: tail.start()]
    changes = _EN_CHANGE_ON_BREADTH.search(head) or _EN_PARTS_IN_PARALLEL.search(head)
    changes = changes or (_EN_OFFER.search(head) and re.match(rf"(?:please\s+)?{_POLITE_OPENER}?{_EN_CHANGE_VERB}\b", head))
    if not changes and not (_EN_SPLIT_REQUEST.search(head) and _EN_SPLIT_EVIDENCE.search(head)):
        return untagged, folded
    done = tail.span("done") if tail.group("done") else None
    return head, (folded[: done[0]] + folded[done[1] :] if done else folded)


def _reads_as_an_english_request(text: str) -> bool:
    """Whether ``text`` alone reads as an English request for work over many targets or split into parallel parts."""
    return bool(
        _EN_CHANGE_ON_BREADTH.search(text)
        or _EN_OFFER.search(text)
        or _EN_PARTS_IN_PARALLEL.search(text)
        or (_EN_SPLIT_REQUEST.search(text) and _EN_SPLIT_EVIDENCE.search(text))
    )


def _trails_off(folded: str) -> bool:
    """Whether an English request is followed by a clause that does not keep it (`_remarks_keep_the_request`): the
    request is the shortest run of clauses that reads as one (`_reads_as_an_english_request`), and every clause after
    it is read."""
    if re.search(r"[가-힣]", folded):
        return False  # a Korean message is read whole instead (`_korean_clauses`)
    cuts = sorted([*_CLAUSE_BREAK.finditer(folded), *_LIST_COLON.finditer(folded)], key=lambda cut: cut.start())
    for cut in cuts:
        head = folded[: cut.start()]
        if not _reads_as_an_english_request(head):
            continue
        trailing = [clause for clause in _CLAUSE_BREAK.split(folded[cut.end() :]) if clause]
        if ":" in cut.group() or _EN_LIST_HEAD.search(head):
            # the rest of a colon list: items that open on a verb of work, with no hedge or hold in them
            while trailing and _is_a_work_item(trailing[0]):
                trailing = trailing[1:]
        return not _remarks_keep_the_request(trailing)
    return False


def _is_a_work_item(item: str) -> bool:
    """Whether a colon list ``item`` opens on a verb of work (`_EN_LIST_ITEM`) with no hedge, refusal or hold in it, and
    is no status in either order (`_STATUS_ALONE`: "already merged")."""
    return (
        bool(_EN_LIST_ITEM.match(item))
        and not _HEDGE_IN_AN_ITEM.search(item)
        and not _HOLD.search(item)
        and not _STATUS_ALONE.fullmatch(item)
    )


def _asks_for(folded: str, verbs: str) -> bool:
    """Whether a Korean ``folded`` asks, in request form, for one of ``verbs``: on the request's own verb, a push after
    a change, or a chain of two or more changes closed by 고 or ㄱ."""
    verb, bare = _korean_request_verb(folded)
    if re.search(rf"(?:{verbs}){_VERB_BEFORE_A_BARE_END}" if bare else verbs, verb):
        return True  # the request is the change ("… 리베이스해줘", "… 리베이스 해줘", "… rebase까지 ㄱㄱ")
    if _PUSH_IN_KOREAN.match(verb) and re.search(_KOREAN_CHANGE_VERB, folded):
        return True  # "… 리뷰 코멘트 반영하고 force push ㄱㄱ"
    closed = _KOREAN_CHAIN_END.search(folded) or folded.rstrip(" .!~").endswith(_G)
    return bool(closed) and len(re.findall(_KOREAN_CHANGE_VERB, folded)) >= 2


# The change verb is on the breadth object: right after it in Korean (a few words of its own between), or as an
# English imperative whose object is the breadth phrase ("fix all the failing tests", "rebase all my open pull
# requests"), a bare object on every unit ("add auth to every endpoint"), or a plural object in all of them ("update
# the dependencies in all services"). A singular object in many places is one change ("fix the login bug on every
# page", "update the license header in every file").
# A clause that aims the change may sit between them, a few words longer ("모든 서비스에서 중복 결제가 안 되게 수정해줘").
_KOREAN_CHANGE_ON_BREADTH: Final = re.compile(
    rf"{_KOREAN_BREADTH_OBJECT}\s*(?:\S+\s+){{0,3}}\S*{_KOREAN_CHANGE_VERB}"
    rf"|{_KOREAN_BREADTH_OBJECT}\s*(?:\S+\s+){{0,4}}\S*(?:게|게끔|도록)\s+(?:좀\s+)?\S*{_KOREAN_CHANGE_VERB}"
)
_EN_CHANGE_ON_BREADTH: Final = re.compile(
    rf"^(?:please\s+)?{_POLITE_OPENER}?{_EN_CHANGE_VERB}\s+"
    rf"(?:(?:all|every|each)\s+(?:of\s+)?(?:the\s+|my\s+|our\s+)?(?:\S+\s+){{0,2}}?{_EN_UNITS}\b"
    rf"|(?!(?:the|a|an|this|that)\b)\S+(?:\s+\S+)?\s+(?:to|in|on|across|for)\s+(?:all|every|each)\s+(?:of\s+)?(?:the\s+)?(?:\S+\s+){{0,2}}?{_EN_UNITS}\b"
    rf"|(?:the|all\s+(?:of\s+)?the|all)\s+(?:\S+\s+)?\S+s\s+(?:in|across|for|of)\s+(?:all|every|each)\s+(?:of\s+)?(?:the\s+)?"
    rf"(?:\S+\s+){{0,2}}?{_EN_UNITS}\b)"
    # A read first, then a change on the same targets by pronoun ("go through all my open PRs and rebase them").
    rf"|^(?:please\s+)?{_POLITE_OPENER}?(?:go\s+through|check|look\s+at)\b[^.?!]*?{_EN_BREADTH}[^.?!]*?"
    rf"\band\s+(?:then\s+)?{_EN_CHANGE_VERB}\s+(?:them|each(?:\s+one)?|all\s+of\s+them)\b"
    # Plural units, then a change on them all ("take the failing tests and fix them all", "open PRs: rebase them all").
    rf"|\b{_EN_PLURAL_UNITS}\b[^.?!]*?\b{_EN_CHANGE_VERB}\s+them\s+all\b"
    rf"|^(?:please\s+)?{_EN_FOR_EACH}{_EN_CHANGE_VERB}\b"
)


# Hard excludes, which win over every reading above (lead decision on the #2232 review):
# - a stop or a hold on the work ("PR들 전부 머지 보류해줘", "모든 서비스 배포 멈춰줘", "PR들 전부 머지 금지");
_STOP_OR_HOLD: Final = re.compile(
    r"중단|취소|멈춰|멈추|멈춤|보류|금지|그만|\b(?:stop|cancel|hold|halt|pause|abort|freeze)\b"
)
# - a condition ("테스트 다 통과하면 머지해줘", "PR 다 올렸으면 리뷰 요청해줘", "if all the tests pass, merge"); a noun that ends in
#   면 (화면, 측면, 전면) is no condition; a subordinating condition opener is one where it opens a clause, at the start
#   or after a comma, a semicolon, a colon or a dash, and so is "provided that" anywhere ("…, assuming QA says it's
#   fine", "…, provided the CTO says ok", "…; as soon as the lead says go"). Inside a clause it constrains the work and
#   keeps, as on main ("rename every module as long as the import paths stay the same", "update every service assuming
#   the defaults are fine", "rebase all open PRs as soon as possible"), and so does an adjective or a participle ("…
#   using the provided helper", "… with the fixtures provided", "fix all the failing tests provided by QA");
_CONDITION: Final = re.compile(
    r"(?<![화측전양단표방내외평])면(?=[\s,.!?~]|$)(?!\s*감사)|거든|\b(?:if|when|once|after|unless|whenever|before)\b"
    r"|(?:^|[,;:—–]\s*|\s-\s)(?:assuming|supposing|provided|providing\s+that|as\s+long\s+as|so\s+long\s+as|in\s+case"
    r"|on\s+(?:the\s+)?condition|as\s+soon\s+as)\b"
    r"|\bprovided\s+that\b"
)
# - a deferral of the work past now ("rebase all the open PRs later", "update every service tonight", "… next week",
#   "… on monday", "PR들 전부 나중에 리베이스해줘", "모든 서비스 내일 업데이트해줘"); a deadline is none ("… by tonight",
#   "…해줘, 내일까지"), and now, today and asap keep;
_DEFERRAL: Final = re.compile(
    r"(?<!\bby\s)\b(?:later|tomorrow|tonight|next\s+(?:week|month|sprint|quarter|year|time|monday|tuesday|wednesday"
    r"|thursday|friday|saturday|sunday)|on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|the\s+weekend)"
    r"|this\s+weekend|over\s+the\s+weekend|eventually|some\s+other\s+time|another\s+time|at\s+some\s+point"
    r"|after\s+the\s+freeze|some\s*day|in\s+a\s+(?:bit|while)|later\s+on|down\s+the\s+line|when\s+i\s+get\s+a\s+chance"
    r"|in\s+(?:\d+|a\s+few|a\s+couple(?:\s+of)?|two|three|four|five|several)\s+(?:minutes?|hours?|days?|weeks?))\b"
    r"|(?<![가-힣])(?:나중에|이따가?|언젠가|(?:이번\s*)?주말에|내일|모레|다음\s*(?:주|달|번)(?:에)?|[월화수목금토일]요일에)"
    rf"(?!(?:\s*{_TIME_WORD})*\s*(?:까지|안에|중으로|중에|내로|이내))"
)
# A weekday inside a clause with a past verb of its own says when that happened, not when to work ("update every
# service we deployed on monday", "지난 월요일에 배포한 서비스 전부 업데이트해줘", "월요일에 배포한 서비스 전부 …").
_PAST_VERB: Final = re.compile(
    r"(?:[a-z]+(?<!e)ed|broke|went|ran|did|made|built|wrote|sent|took|got|put|set|found|began|came|saw|left|lost|split"
    r"|shipped)"
)
_KOREAN_PAST_AROUND: Final = re.compile(r"지난\s*$")
# The times a past clause may carry: a weekday or the weekend, which point back as well as ahead ("we deployed on
# monday", "월요일에 배포한"); tomorrow, next week, later or 나중에 never point back.
_BACKWARD_TIME: Final = re.compile(r"on\s+\S+|over\s+the\s+weekend|[월화수목금토일]요일에|주말에")
_KOREAN_PAST_RELATIVE_AFTER: Final = re.compile(r"\s*\S*(?:한|했던|된|됐던|던)(?=\s|$)")


def _says_a_deferral(folded: str) -> bool:
    """Whether ``folded`` puts the work past now (`_DEFERRAL`), outside a clause with a past verb of its own."""
    for match in _DEFERRAL.finditer(folded):
        if not _BACKWARD_TIME.fullmatch(match.group()):
            return True  # a time ahead of now is a deferral whatever clause it sits in
        if any(_PAST_VERB.fullmatch(word) for word in folded[: match.start()].split()[-3:]):
            continue
        if _KOREAN_PAST_AROUND.search(folded[: match.start()]) or _KOREAN_PAST_RELATIVE_AFTER.match(folded[match.end() :]):
            continue
        return True
    return False
# - a completion said as a noun or a bare word ("브랜치들 다 정리됨", "upstream PR들 다 리뷰 반영 끝", "테스트 수정 완료"),
#   not one that names the units ("완료된 이슈들 전부 닫아줘") or asks for it ("… 리베이스 완료해줘");
_COMPLETED: Final = re.compile(
    r"됨(?=[\s,.!?~]|$)|(?<![가-힣])끝(?=[\s,.!?~]|$)|완료(?=[\s,.!?~]|$|됨|됐|되었|했|함|임|입니다|이에요|예요|요)"
)
# - a recurring schedule, which stays on ulw-loop, Hermes' /loop or an automation ("매일 아침 PR들 전부 리베이스해줘", "30분마다
#   …", "PR 올릴 때마다 …", "rebase all my open PRs every hour", "update every service nightly");
# The shapes a schedule takes, not a word list:
# - a recurring period: any noun with 마다 but a unit of work (아침마다, 반나절마다, 스프린트마다, 배포마다, 커밋마다,
#   때마다, while "서비스마다" and "PR마다" mean each of them: `_says_a_schedule`), 매일, 매주, 매 + a noun (매 분기, 매
#   스프린트, 매 릴리즈), every <time>, each <time>;
# - a frequency over a period (2시간에 한 번씩, 일주일에 한 번, 하루 두 번, 주 2회, 2회씩, twice a day, 3 times a week), an
#   interval (3일 간격, 하루 걸러, every other day), an alternating period (격일, 격주, 격월);
# - a clock time (9시에, 자정, 정오, 새벽, at 9am), and a scheduler named for it (cron, 크론, 스케줄, schedule로, 스케줄
#   걸어서, 예약해서);
# - an event that repeats the work (on every push, after each deploy, on every PR), as 배포마다 and 커밋마다 do.
# A one-off request in the now stays work ("지금 바로", "이번에 한 번만", "now").
_KOREAN_NUMBER: Final = r"(?:\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|몇)"
_TIME_UNIT_KO: Final = r"(?:초|분|시간|일|주일|주|달|개월|년|해)"
_TIME_UNIT_EN: Final = (
    r"(?:second|minute|min|hour|day|week|month|year|morning|afternoon|evening|night|weekday|weekend|monday|tuesday"
    r"|wednesday|thursday|friday|saturday|sunday)"
)
_SCHEDULE: Final = re.compile(
    r"(?<![가-힣])매(?:일|주|달|월|년|시간|분)(?![가-힣])|(?<![가-힣])매일(?=아침|밤|저녁|오전|오후)|(?<![가-힣])매\s+(?=\S)"
    r"|주기적|정기적|\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?\s*(?:에|마다|정각)|(?<![가-힣])(?:자정|정오|새벽)(?:에|마다)?(?![가-힣])"
    rf"|(?:(?<![가-힣]){_KOREAN_NUMBER}|일)\s*{_TIME_UNIT_KO}\s*에\s*{_KOREAN_NUMBER}\s*번|하루\s*(?:에\s*)?{_KOREAN_NUMBER}\s*번"
    rf"|{_KOREAN_NUMBER}\s*{_TIME_UNIT_KO}\s*간격|(?:일정한?|정해진|규칙적인?)\s*간격|(?:하루|이틀|사흘|나흘|한\s*주|일주일|\d+\s*일)\s*걸러"
    r"|(?<![가-힣])(?:주|월|연|하루)\s*\d+\s*회|\d+\s*회\s*씩|(?<![가-힣])격(?:일|주|월)(?:로|으로|에|마다|씩)?(?![가-힣])"
    r"|(?<![a-z])cron(?![a-z])|크론|스케줄(?!러)|schedule(?=\s*(?:으로|로|에|을|를|걸))|예약(?:해서|으로|을\s*걸)"
    rf"|\bevery\s+(?:\d+\s+|other\s+)?{_TIME_UNIT_EN}s?\b|\beach\s+{_TIME_UNIT_EN}\b"
    r"|\b(?:once|twice|thrice|(?:\d+|two|three|four|five|several)\s+times)\s+(?:a|per|each|every)\s+(?:hour|day|week|month|year)\b"
    r"|\b(?:on|after|upon)\s+(?:every|each)\s+(?:new\s+)?(?:push|commit|merge|deploy|deployment|release|build|pr|pull\s+request)\b"
    r"|\b(?:hourly|daily|nightly|weekly|monthly|periodically)\b|\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)\b"
    r"|\bon\s+a\s+schedule\b"
)
# What comes before 마다: a unit of work makes it "each of them" (`_KOREAN_UNIT`), anything else a recurrence.
_BEFORE_MADA: Final = re.compile(r"(?P<noun>[^\s,.!?~]+?)(?:들)?\s*마다")
_WORK_UNIT_BEFORE_MADA: Final = re.compile(rf"(?:마이크로)?(?:{_KOREAN_UNIT}|풀\s*리퀘(?:스트)?|repos?)")


def _says_a_schedule(folded: str) -> bool:
    """Whether ``folded`` says a recurring schedule (`_SCHEDULE`), or a noun other than a unit of work with 마다."""
    return bool(_SCHEDULE.search(folded)) or any(
        not _WORK_UNIT_BEFORE_MADA.fullmatch(match.group("noun")) for match in _BEFORE_MADA.finditer(folded)
    )
# A pull request's address, written bare or as a link the caller passes (`reference_regions(...).links`: the
# executable text has none).
_PULL_REQUEST_ADDRESS: Final = re.compile(r"/pulls?/\d+|/merge_requests/\d+")
# - one numbered pull request, or the person's own one ("PR 2232", "#2232", "2232번 PR", "내 PR", "pull request 2232",
#   "pull 951", "files touched by PR 2232", "this PR", "이 PR"); 이 or 그 must open its word, so 버그 and 블로그 are no
#   scope, and a number with a counter is a count of PRs, not one ("PR 3개", "PR 5건": `_KOREAN_COUNT`). One branch is
#   one scope the same way: a named one ("feature/dag-default", "fix/login-bug") and the current one ("current
#   branch", "this branch", "이 브랜치");
_ONE_SCOPE: Final = re.compile(
    r"\bpr\s*#?\s*\d+(?!\d|\s*(?:개|건))|#\s*\d+|\d+\s*번\s*(?:pr|이슈)|(?<![가-힣])내\s*pr(?!\s*들)"
    r"|\bpull\s+request\s+#?\d+(?!\d|\s*(?:개|건))|\bpull\s*#?\s*\d+(?!\d|\s*(?:개|건))"
    r"|(?<![\w/.-])(?:feature|feat|fix|bugfix|hotfix|release|chore|docs|refactor|omh|dev|wip)/[\w.-]+"
    r"|\b(?:current|my\s+current)\s+branch\b"
    # A pull request's address or its number said in words ("github.com/…/pull/2240", "PR number 2240", "2240번
    # 풀리퀘", "풀 리퀘스트 2240").
    rf"|{_PULL_REQUEST_ADDRESS.pattern}|\b(?:pr|pull\s+request)\s+(?:number|no\.?|num\.?)\s*#?\s*\d+|\bpr\s*번호\s*\d+"
    r"|\d+\s*번?\s*풀\s*리퀘(?:스트)?|풀\s*리퀘(?:스트)?\s*#?\s*\d+(?!\d|\s*(?:개|건))"
    r"|\b(?:this|that)\s+(?:pr|pull\s+request|branch|commit|diff)\b|(?<![가-힣])(?:이|그)\s*(?:pr|브랜치|커밋)(?![a-z])"
    r"|\b(?:in|of|from|on)\s+(?:the|my)\s+(?:pr|pull\s+request|branch|commit|diff)\b|\btouched\s+by\b"
    # One PR or branch picked out by an adjective or a possessive, or by 하나, never a plural ("my latest pull request",
    # "the last PR", "PR 하나").
    r"|(?<![a-z가-힣])(?:pr|pull\s*request|풀\s*리퀘(?:스트)?|브랜치)\s*(?:하나|한\s*개|1\s*개)(?![가-힣])"
    r"|\b(?:my|the|your|our)\s+(?:latest|last|newest|most\s+recent|current)\s+(?:pr|pull\s+request)\b"
)
# - one PR or one branch singled out by a modifier, with the breadth on what is inside it ("어제 내가 연 PR 테스트 전부",
#   "방금 올린 PR 파일들 전부", "feature/x 브랜치 테스트 전부", "현재 브랜치 테스트 전부"): no 들 and no breadth word on the PR
#   or the branch itself, and no 모든, 전체, 각 or 여러 before it ("PR들 전부", "모든 PR 테스트", "열린 PR 전부" stay many).
_ONE_CONTAINER: Final = re.compile(
    r"(?:(?P<before>\S+)\s+)?(?<![a-z가-힣])(?:pr|pull\s*request|풀\s*리퀘(?:스트)?|브랜치)(?:의|에서|에\s*있는|안의|안에\s*있는)?"
    r"\s+(?:리뷰\s+)?(?:테스트|파일|라인|줄|커밋|코드|변경|스냅샷|함수|코멘트|충돌|에러|오류|경고|린트|타입)"
)
_MANY_BEFORE_A_CONTAINER: Final = frozenset({"모든", "전체", "각", "여러", "all", "every", "each"})


def _names_one_container(folded: str) -> bool:
    return any(match.group("before") not in _MANY_BEFORE_A_CONTAINER for match in _ONE_CONTAINER.finditer(folded))


# A past: a syllable closing on ㅆ, other than 있 and 겠 ("리베이스했습니다", "머지했어요", "머지됐네", "닫혔네"). A past
# in a modifier names which units, and reports nothing ("내가 올렸던 PR들", "어제 실패했던 테스트", "충돌났었던 브랜치들"),
# and neither does one in an embedded question ("어떻게 나눴는지 설명해줘", "리베이스했는지 확인하고").
_NOT_A_PAST: Final = frozenset("있겠")


def _closes_on_ss(character: str) -> bool:
    code = ord(character) - 0xAC00
    return 0 <= code < 11172 and code % 28 == 20


def _says_a_past(folded: str) -> bool:
    """Whether ``folded`` says a past: the work done, not asked for. A fault said in the past is no such past when the
    message ends asking to fix it (`_asks_to_fix_a_fault`: "api 모듈과 ui 모듈 테스트가 깨졌어, 동시에 고쳐줘")."""
    faults = [match.span() for match in _FAULT.finditer(folded)] if _asks_to_fix_a_fault(folded) else []
    return any(
        _closes_on_ss(character)
        and character not in _NOT_A_PAST
        and folded[index + 1 :].lstrip("었았였")[:1] != "던"
        and folded[index + 1 :].lstrip("었았였")[:2] != "는지"
        and not any(start <= index < end for start, end in faults)
        for index, character in enumerate(folded)
    )


def _asks_to_fix_a_fault(folded: str) -> bool:
    """Whether ``folded`` reports a fault (`_FAULT`) and its last clause asks, in request form, to fix it
    (`_FIX_REQUEST`)."""
    last = [clause for clause in _CLAUSE_BREAK.split(folded) if clause][-1:] or [folded]
    request = _korean_request_verb(last[0])[0] or re.match(r"(?:please\s+)?(?:fix|resolve|repair|debug)\b", last[0])
    return bool(_FAULT.search(folded) and request and _FIX_REQUEST.search(last[0]))


# Words that ask for no work, or only a report: a negation, no need, a lookup or a status, a question ("PR들 전부
# 머지하지 마", "PR들 전부 알려줘", "모든 서비스 상태 확인해줘", "check the status of all open PRs", "review all open PRs and
# just tell me which are safe"), and one thing in many places ("fix the bug in all three services").
_NO_WORK_ASKED: Final = re.compile(
    r"했다|됐다|했음|됐음|했잖아|했는데|했지만|했더니|지\s*마(?!다)|지\s*말|안\s*해|필요\s*없|도\s*돼|도\s*된다|도\s*괜찮"
    r"|알려\s*줘|알려\s*주세요|보여\s*줘|찾아|링크\s*(?:줘|주세요|보내)|읽어|상태|몇\s*개|목록|리스트|어때|뭐야|[?？]"
    r"|pr\s*들?\s*(?:을|를)?\s*(?:전부|모두|다)\s*정리"
    r"|\b(?:tell\s+me|let\s+me\s+know|report|summari[sz]e|show\s+me|status|which\s+(?:ones|are|is)"
    rf"|(?:do\s+not|don'?t)(?!\s+(?:\w+\s+)?{_OUTCOME_VERB})"
    r"|without|but\s+not|never|only)\b|\band\s+list\b|\blist\s+(?:them|the|which|all)\b"
    r"|\b(?:the|this|that|a)\s+(?:\S+\s+){0,2}\S+(?<!s)\s+(?:in|on)\s+(?:all|every|each)\b"
)
# Parallel running is the work's subject, not its shape ("fix the race where uploads run in parallel across modules").
_RUNTIME_PARALLEL: Final = re.compile(
    r"\b(?:run|runs|running|execute|executes|load|loads)\s+in\s+parallel\b|\brace(?:\s+condition)?s?\b|\bdeadlock"
)
# Work until a condition holds stays on the loop and ultrawork lanes ("… until every test passes", "다 통과할 때까지").
_UNTIL: Final = re.compile(r"\buntil\b|\btill\b|때까지")
# A retired engine's name, which opens a request for that engine as a skill's name does ("team 실패하는 테스트 다 고쳐"),
# and a name said in Korean ("루프로 모든 서비스 업데이트해줘").
_RETIRED_ENGINE_NAMES: Final = frozenset({"team", "maestro", "ralph", "ultrapilot", "ultraprocess", "ultragoal"})
_KOREAN_NAMES: Final = frozenset({"루프"})
# A Korean particle on the name keeps it the name ("loop로", "refactor-plan으로", "github-event-ops에서"), and so does
# OMH's own name before it ("omh loop …", "use omh github-event-ops …").
_NAME_PARTICLE: Final = re.compile(r"(?:으로|로|을|를|에서|에게|한테|이랑|랑|와|과)$")
_OMH_OPENER: Final = re.compile(r"^(?:use\s+)?(?:omh|oh-my-hermes(?:-agent)?)\s+")
# A skill named as the instrument anywhere names it for the work too, as dag-ulw's own name does (`_WITH`,
# `_KOREAN_RUN`): "열린 PR들 전부 git-workflow로 리베이스해줘", "rebase all my open PRs with git-workflow".
_KOREAN_INSTRUMENT: Final = re.compile(r"(?P<name>\S+?)(?:으로|로)(?:\s|$)")
_EN_INSTRUMENT: Final = re.compile(r"\b(?:with|using|via|through)\s+(?:the\s+)?(?P<name>[a-z0-9][a-z0-9_-]*)")


# The catalog's names, kept once the sidecar answered. A missing sidecar is not kept: the next call reads it again.
_CATALOG_SKILL_NAMES: dict[str, frozenset[str]] = {}


def _skill_names() -> frozenset[str]:
    names = _CATALOG_SKILL_NAMES.get("names")
    if names is None:
        catalog = _skill_shortlist.catalog_skill_names()
        if not catalog:
            return COINED_NAMES | _RETIRED_ENGINE_NAMES | _KOREAN_NAMES
        names = _CATALOG_SKILL_NAMES.setdefault("names", catalog | COINED_NAMES | _RETIRED_ENGINE_NAMES | _KOREAN_NAMES)
    return names


def _opens_with_a_skill_name(folded: str) -> bool:
    """Whether ``folded`` opens with a skill's name, its label or a retired engine's, with or without a Korean
    particle: a request named for that skill."""
    words = re.findall(r"[^\s,:]+", _OMH_OPENER.sub("", folded, count=1))[:3]
    names = _skill_names()
    return any(
        joined in names or _NAME_PARTICLE.sub("", joined) in names
        for length in (1, 2, 3)
        for joined in ("-".join(words[:length]), " ".join(words[:length]))
    )


def _names_a_skill_as_the_instrument(folded: str) -> bool:
    """Whether ``folded`` names a skill, the loop or a retired engine as what the work is done with, anywhere."""
    names = _skill_names()
    return any(
        match.group("name").strip(",:") in names
        for pattern in (_KOREAN_INSTRUMENT, _EN_INSTRUMENT)
        for match in pattern.finditer(folded)
    )


def _hard_excluded(folded: str, links: tuple[str, ...], request: str | None = None) -> bool:
    """Whether ``folded`` is no request for work over many targets whatever else it says: a sigil (the invoked skill's
    work), a skill or engine named first or as the instrument, a stop or a hold, a condition, a past or a completion,
    one pull request's or one branch's scope (in its words or its ``links``), a recurring schedule, work until a
    condition, or parallel running as its subject."""
    return bool(
        folded.startswith(("/", "$", "@", "./"))
        or any(_PULL_REQUEST_ADDRESS.search(link.casefold()) for link in links)
        or _opens_with_a_skill_name(folded)
        or _names_a_skill_as_the_instrument(folded)
        or _STOP_OR_HOLD.search(folded)
        or _CONDITION.search(_KEEP_IDIOM.sub("", _NO_PRESSURE.sub("", folded)))
        or _says_a_deferral(_KEEP_IDIOM.sub("", folded))
        or _COMPLETED.search(folded)
        or _says_a_past(folded)
        or _ONE_SCOPE.search(folded)
        or _names_one_container(folded)
        or _says_a_schedule(folded)
        or _takes_it_back(_KEEP_IDIOM.sub("", folded))
        or _trails_off(folded if request is None else request)
        or _UNTIL.search(folded)
        or _RUNTIME_PARALLEL.search(folded)
        or names_ultrawork(folded)
    )


def _work_over_many_targets(text: str, links: tuple[str, ...]) -> bool:
    """Whether ``text`` asks, in request form, for an offer-list verb on a breadth object that names independent units
    (`_KOREAN_OFFER`, `_EN_OFFER`), or for two named parts in parallel, and nothing excludes it."""
    folded, whole = _closed(_folded(text))
    if _hard_excluded(whole, links, folded):
        return False
    if _NO_WORK_ASKED.search(folded):
        return False
    if _EN_PARTS_IN_PARALLEL.search(folded):
        return True
    if _EN_OFFER.search(folded):
        # Every clause after the first is a change or a review too, not a report ("… and send me a list").
        return all(re.fullmatch(_EN_OFFER_VERB, verb) for verb in _EN_LATER_CLAUSE_VERB.findall(folded))
    # The request is the change or the review, not a summary, in the message or in one clause of it.
    return any(
        _KOREAN_OFFER.search(clause) and _asks_for(clause, _KOREAN_OFFER_VERB) for clause in _korean_clauses(folded)
    )


# Work asked to split into parallel parts, with the work named: the split itself (`work_is_split`), asked for, and a
# work verb after it ("fan out across the services and migrate each one", "…, then integrate", "모듈을 병렬로 나눠서
# 리팩터링해줘") or a work noun as what splits ("split the migration into parallel lanes", "this refactor is too big for
# one agent, fan out across the services"). Not text to translate ("split the paragraphs into parallel parts for
# translation", "문단을 병렬로 나눠서 번역해줘"), not a proposal or a plan said ("how about we …", "why not …", "my plan is
# to …", "the goal is to …", "maybe …": no imperative, `_EN_SPLIT_REQUEST`), and nothing hard-excluded or asking for no
# work (rule A for the size cues).
_SPLIT_TEXT: Final = re.compile(r"\btranslat|번역")
_SPLIT_WORK_NOUN: Final = r"(?:migration|refactor(?:ing)?|rewrite|work|implementation|port|upgrade)"
# The split asked for: an imperative, whatever its verb ("split …", "fan out …", "do the api and the ui in parallel …",
# "analyze API and UI in parallel, then integrate"), put politely, after a clause ("…, fan out across the services",
# "tell me when done: split …"), or said as what the person wants ("what we need is to split …"). A sentence that
# opens on a determiner, a pronoun, a question word or an auxiliary is no imperative.
_EN_SPLIT_REQUEST: Final = re.compile(
    rf"^(?:please\s+)?(?:{_POLITE_OPENER}|(?:can|could|shall)\s+we\s+|let'?s\s+)?(?:just\s+)?"
    r"(?!(?:the|a|an|this|that|these|those|my|our|your|their|its|we|i|you|it|they|there|here|which|what|who|why|how"
    r"|when|where|is|are|was|were|am|do\s+(?:you|we|i)|does|did|should|would|could|can|will|shall|may|might|must|if"
    r"|so|and|but|or|maybe|perhaps)\b)[a-z]+\b"
    r"|[,:]\s*(?:so\s+|just\s+|please\s+)?(?:fan\s+out|split)\b"
    r"|^(?:what\s+(?:i|we)\s+(?:want|need)\s+is\s+to|(?:i|we)\s+(?:want|need)\s+(?:you\s+)?to)\s+(?:fan\s+out|split)\b"
)
_EN_SPLIT_EVIDENCE: Final = re.compile(
    rf"(?:\band|\bthen|,\s*then)\s+(?:then\s+)?(?:{_EN_CHANGE_VERB}|integrate|develop|ship)\b"
    rf"|\bsplit\s+(?:the\s+|this\s+|that\s+|our\s+|my\s+)?(?:\S+\s+){{0,6}}?{_SPLIT_WORK_NOUN}\s+into\b"
    r"|\binto\s+parallel\s+work\b"
    rf"|\b{_SPLIT_WORK_NOUN}\b[^.?!]*?,\s*(?:so\s+|just\s+|please\s+)?(?:split|fan\s+out)\b"
)
_KOREAN_WORK_VERB: Final = rf"(?:{_KOREAN_CHANGE_VERB}|구현|개발|통합)"
# One named object split into parallel parts is one task, offered and not run ("이 함수 병렬로 나눠서 구현해줘", "로그인
# 페이지 하나 병렬로 나눠서 고쳐줘", "README 병렬로 나눠서 업데이트해줘", "fan out the image resize into parallel workers"):
# a demonstrative and its noun, a noun and 하나, a single file or function name, or "the" and a singular noun. Several
# objects ("api, ui, docs 작업을", "결제/주문/배송 모듈", "분리기와 파서") and the work itself as what splits ("split the
# migration into …") are not one object.
_KOREAN_SPLIT_OBJECT: Final = re.compile(r"(?P<object>[^.!?]*?)\s*(?:을|를|은|는)?\s*(?:병렬로\s*나눠|나눠서\s*병렬로)")
_EN_SPLIT_OBJECT: Final = re.compile(
    r"\b(?:split|fan\s+out|break\s+(?:up|down)|parallelize)\s+(?P<object>(?:the|this|that|my|our)\s+[^,.!?]*?)\s+"
    r"(?:into|across)\b"
)
# The object said first, as the topic the split refers back to ("the checkout page: split it into parallel parts …").
_EN_SPLIT_TOPIC: Final = re.compile(
    r"^(?P<object>(?:(?:the|this|that|my|our)\s+)?[^,:.!?]+?)\s*:\s*(?:please\s+|just\s+)?"
    r"(?:split|fan\s+out|break\s+(?:up|down)|parallelize)\s+(?:it|this)\s+(?:into|across)\b"
)
_SEVERAL_OBJECTS: Final = re.compile(
    r"[,/&]|\band\b|(?:와|과|랑|하고)(?:\s|$)|(?<![가-힣])(?:및|모든|전체|여러|각)(?![가-힣])|들(?:\s|$)"
    r"|(?<![가-힣])(?:두|세|네|다섯|여섯|일곱|여덟|아홉|열|몇)(?![가-힣])|\d+\s*개"
)


def _splits_one_object(request: str) -> bool:
    """Whether ``request`` splits one named object into parallel parts (`_KOREAN_SPLIT_OBJECT`, `_EN_SPLIT_OBJECT`,
    `_EN_SPLIT_TOPIC`)."""
    korean = _KOREAN_SPLIT_OBJECT.search(request) if re.search(r"[가-힣]", request) else None
    english = None if korean else (_EN_SPLIT_OBJECT.search(request) or _EN_SPLIT_TOPIC.search(request))
    found = korean or english
    if not found or _SEVERAL_OBJECTS.search(found.group("object")):
        return False
    words = found.group("object").split()
    if english:
        return not words[-1].endswith("s") and not re.fullmatch(_SPLIT_WORK_NOUN, words[-1])
    return bool(
        words
        and (
            (words[0] in ("이", "그", "저") and len(words) <= 3)
            or words[-1].endswith("하나")
            or (len(words) == 1 and not re.search(r"[가-힣]", words[0]))
        )
    )


# What a split request may carry besides the work: a request put as a question ("can you split …?", "… 구현해줄래?"), a
# "tell me when done" before it, and a report on the work after it ("…, then tell me which failed", "… 구현하고 나눈 방법
# 설명해줘"): the work asked for is still the split.
_EN_DONE_OPENER: Final = re.compile(r"^tell\s+me\s+when\s+(?:it'?s\s+|you'?re\s+)?done\s*[:,]\s*")
_KOREAN_REPORT_TAIL: Final = re.compile(
    r"(?P<work>\S*(?:고|해서))\s+(?:\S+\s+){0,3}\S*(?:설명|알려|보고|공유)\S*\s*[.!~]*$"
)


def _splits_named_work(text: str, folded: str, links: tuple[str, ...]) -> bool:
    """Whether ``text`` asks to split named work into parallel parts (`_EN_SPLIT_EVIDENCE`, a Korean work verb in
    request form), rather than to split text or one named object (`_splits_one_object`), to propose a split (no
    imperative), or to be told how."""
    request, whole = _closed(_EN_DONE_OPENER.sub("", folded, count=1))
    if not work_is_split(text) or _hard_excluded(whole, links, request):
        return False
    if _splits_one_object(request):
        return False
    if _REQUEST_AS_QUESTION.search(request):
        request = request.rstrip(" ?？")
        if re.search(rf"{_KOREAN_WORK_VERB}\S*\s*{_KOREAN_ASKS_TO_BE_DONE.pattern}", request):
            return not _SPLIT_TEXT.search(request) and not _one_fault(request)  # "… 구현해 주시겠어요?"
    tail = _KOREAN_REPORT_TAIL.search(request)
    if tail and re.search(_KOREAN_WORK_VERB, tail.group("work")):
        return not _SPLIT_TEXT.search(request) and not _one_fault(request)  # "… 구현하고 변경 내용 설명해줘"
    if _NO_WORK_ASKED.search(request) or _SPLIT_TEXT.search(request):
        return False
    if _one_fault(request):
        return False
    if re.search(r"[가-힣]", request):
        return _asks_for(request, _KOREAN_WORK_VERB)
    return bool(_EN_SPLIT_REQUEST.search(request) and _EN_SPLIT_EVIDENCE.search(request))


def refuses_dag_ulw(text: str, links: tuple[str, ...] = ()) -> bool:
    """Whether the cue reader refuses ``text`` whatever its size: a hard exclude on the whole text, or a clause after
    the request that keeps nothing (`_hard_excluded` over `_closed`). The router's and the hint's size-cue paths read
    this, so neither starts a run the cue reader holds."""
    request, whole = _closed(_folded(text))
    return _hard_excluded(whole, links, request)


def splits_without_evidence(text: str, links: tuple[str, ...] = ()) -> bool:
    """Whether ``text`` asks for a split (`work_is_split`) without naming the work to split (`_splits_named_work`):
    the router asks about dag-ulw instead of dispatching it, and the route hint offers it, rather than either starting a
    run ("split the paragraphs into parallel parts for translation", "how about we split the work into parallel
    lanes")."""
    return work_is_split(text) and not _splits_named_work(text, _folded(text), links)


def sized_without_evidence(text: str, links: tuple[str, ...] = ()) -> bool:
    """Whether ``text`` is big work by size (`big_work_for_dag_ulw`) only through a split with no work named
    (`splits_without_evidence`) or a breadth phrase alone ("여러 모듈에 걸친 결제 기능 구현해줘"), without the evidence
    `dispatches_dag_ulw` needs: the route hint offers dag-ulw there instead of starting it (rule A)."""
    if not big_work_for_dag_ulw(text) or dispatches_dag_ulw(text, links):
        return False
    if splits_without_evidence(text, links) or refuses_dag_ulw(text, links):
        return True
    folded = _cue_text(text)
    return _contains(folded, BREADTH_CUES) and not _asks_for_a_split(text) and not _contains(folded, CONCURRENCY_CUES)


def dispatches_dag_ulw(text: str, links: tuple[str, ...] = ()) -> bool:
    """Whether ``text`` gives the positive evidence the router dispatches a dag-ulw graph on, and the route hint starts
    one on: a change verb from the closed allow list (`_KOREAN_CHANGE_VERB`, `_EN_CHANGE_VERB`), on a breadth object
    that names independent units, in request form ("열린 PR들 전부 리베이스해줘", "fix all the failing tests", the owner's
    "pr들 전부 확인해서 닫을건 닫고 … 리베이스하고"), two named parts asked for in parallel, or named work asked to split
    into parallel parts (`_splits_named_work`). Nothing hard-excluded (`_hard_excluded`) qualifies, and neither does a
    request that only reads, reports or runs one command. ``links`` are the message's links, which the executable text
    leaves out."""
    folded = _folded(text)
    if _splits_named_work(text, folded, links):
        return True
    folded = _closed(folded)[0]
    if not _work_over_many_targets(text, links) or _asks_to_be_told(text):
        return False
    if _one_fault(folded):
        return False  # one fault to fix, however wide ("모든 테스트가 깨졌어, 고쳐줘", "모든 테스트가 안 돌아가 고쳐줘")
    if _EN_CHANGE_ON_BREADTH.search(folded) or _EN_PARTS_IN_PARALLEL.search(folded):
        return True
    # A chain of changes joined by 고 counts too, closed by 고 or ㄱㄱ ("닫을건 닫고 … 리베이스하고 ㄱㄱ"), and so does one
    # clause of the message that asks for the change ("모든 패키지 업데이트해줘, 패키지마다 changelog도 써줘").
    return any(
        _KOREAN_CHANGE_ON_BREADTH.search(clause) and _asks_for(clause, _KOREAN_CHANGE_VERB)
        for clause in _korean_clauses(folded)
    )


def work_has_several_parts(text: str) -> bool:
    """Whether ``text`` says its work splits into parts or reaches across many (`SHAPE_CUES`, `BREADTH_CUES`), or
    runs at once across several named parts (a `CONCURRENCY_CUES` phrase beside `_PART_WORDS`) for a reason other
    than a fault it asks to fix (`_FAULT`)."""
    folded = _cue_text(text)
    if _asks_for_a_split(text) or _contains(folded, BREADTH_CUES):
        return True
    if not _contains(folded, CONCURRENCY_CUES):
        return False
    plain = _folded(text)
    if _FAULT.search(plain) and _FIX_REQUEST.search(plain) and not _PARALLEL_WORK.search(plain):
        return False
    words = set(re.findall(r"[^\W_]+", folded))
    korean_parts = sum(folded.count(_cue_text(word)) for word in _KOREAN_PART_WORDS)
    return not words.isdisjoint(_PART_WORDS) or korean_parts >= 2


def work_is_split(text: str) -> bool:
    """Whether ``text`` asks outright for its work to split (`SHAPE_CUES`), does not ask to be told how
    (`_ASKS_TO_BE_TOLD`), and does not name ultrawork.

    The route hint reads this where no rule of its own matched: breadth ("all modules") or a concurrency word
    alone is ordinary in a question about code, while a split ("fan out", "split into parallel") asks for work.
    """
    return not names_ultrawork(text) and not _asks_to_be_told(text) and _asks_for_a_split(text)


def work_over_many_targets(text: str, links: tuple[str, ...] = ()) -> bool:
    """Whether ``text`` asks for work over many targets without the evidence `dispatches_dag_ulw` needs ("review all
    open PRs", "PR들 전부 확인해서 정리해줘"): nothing hard-excluded, no question, and not one fault with one fix. The
    router may ask once with dag-ulw as the candidate, and the route hint offers it; neither starts a run."""
    if not _work_over_many_targets(text, links) or _asks_to_be_told(text):
        return False
    return not _one_fault(_folded(text))


def big_work_for_dag_ulw(text: str) -> bool:
    """Whether ``text`` asks for big work by size, rather than to be told about it, and does not name ultrawork,
    which keeps a request named for it."""
    return not names_ultrawork(text) and not _asks_to_be_told(text) and work_has_several_parts(text)


# Several features or stages, each named, asked to be built: a list of three or more ("메일 가져오기, 파일 업로드,
# 검색 기능 개발해줘", "장바구니랑 주문이랑 배송조회 기능 구현해", "build the upload, preview and download screens") or a
# range from one stage to another ("회원가입부터 결제까지 개발해줘", "implement everything from onboarding to checkout").
# The list or the range is the verb's own object: only a feature noun, a particle and adverbs of extent or order sit
# between them ("기능을", "전부", "순서대로", "설계에 맞게"). It is read on positive evidence, so whatever cannot be placed stays
# as on main. A list counts with a noun that is a feature by itself on it, with a softer noun or items of two words each
# under a verb that builds software and nothing else, or when its items, the last among them, are common product
# features (`_KOREAN_PRODUCT_FEATURE`, `_EN_PRODUCT_FEATURE`). "빨강, 파랑, 초록 버튼 만들어줘", "김철수, 이영희, 박민수 명단
# 만들어줘", "add alice, bob and carol" and "build api, web and worker" show none of them. A verb that changes what exists
# is no build ("빨강, 파랑, 초록으로 버튼 색만 바꿔줘"). Nor is a range of numbers, pages, dates or positions ("1부터 10까지 더하는
# 함수 만들어줘", "처음부터 끝까지 만들어줘"), a comparison or a question. Like work over many targets, it is offered, not
# started: the person names the parts, not how each is run.
_FEATURE_NOUN: Final = r"(?:기능|화면|모듈|탭)"
_SOFT_FEATURE_NOUN: Final = r"(?:페이지|단계|과정|흐름|플로우|플로|api|메뉴|부분)"
_EN_FEATURE_NOUN: Final = r"(?:features?|screens?|modules?|endpoints?|tabs?|views?)"
_EN_SOFT_FEATURE_NOUN: Final = r"(?:pages?|flows?|stages?|steps?|parts?)"
_KOREAN_PRODUCT_FEATURE: Final = re.compile(
    r"(?:로그인|로그아웃|회원가입|가입|탈퇴|온보딩|프로필|마이페이지|대시보드|검색|필터|정렬|알림|댓글|좋아요|공유|업로드|다운로드|미리보기|결제|장바구니"
    r"|주문|환불|배송|쿠폰|포인트|정산|채팅|쪽지|즐겨찾기|북마크|리뷰|팔로우|신고|리포트)$"
)
_EN_PRODUCT_FEATURE: Final = re.compile(
    r"(?:log-?in|log-?out|sign-?in|sign-?up|sign-?out|registration|onboarding|password\s+reset|profiles?|dashboards?|search"
    r"|filters?|sorting|notifications?|comments?|likes?|sharing|uploads?|downloads?|previews?|checkout|cart|payments?"
    r"|billing|refunds?|invoices?|orders?|bookmarks?|favorites?|tagging|exports?|imports?|reports?|mentions?|reactions?"
    r"|subscriptions?|coupons?|messaging|chat)$"
)
_KOREAN_NEW_VERB: Final = r"(?:만들|구현|개발|추가|붙여|붙이|넣|연결|완성)"
_KOREAN_SOFTWARE_VERB: Final = r"(?:구현|개발)"
_KOREAN_RANGE_VERB: Final = r"(?:구현|개발|만들|완성)"
# Adverbs of extent, order or fit that may stand between the list and its verb, or carry a bare 해 ("다 해줘", "순서대로해").
_KOREAN_EXTENT: Final = (
    r"(?:다|전부|전부다|모두|모두다|다같이|같이|함께|한번에|한\s*번에|한꺼번에|순서대로|차례대로|단계별로|각각|하나씩|하나하나|모조리"
    r"|\S+에\s*맞게|\S+대로|끝까지|이어붙여서|이어서|붙여서|나눠서)"
)
_KOREAN_LIST_TAIL: Final = re.compile(
    rf"(?:(?<!\s)\s*)?(?:(?:(?P<noun>{_FEATURE_NOUN})|(?P<soft>{_SOFT_FEATURE_NOUN}))(?:들)?)?\s*"
    rf"(?:을|를|도|까지|들|들을|까지도|이랑|랑)?(?:\s*{_KOREAN_EXTENT})*\s*$"
)
# A joining 와, 과, 랑 or 하고 follows a word of two syllables or more: 사과, 결과 and 사랑 hold no join.
_KOREAN_JOINER: Final = re.compile(r"(?<=[가-힣a-z0-9]{2})(?:이랑|랑|하고|와|과|및)\s+|\s*[,/]\s*|\s+및\s+")
# A word in the list that a case particle or a colon ties to something else: the list sits inside that thing ("설정 페이지에
# 테마, 언어, 시간대 탭 추가해줘", "빨강, 파랑, 초록으로 화면 만들어줘", "다음 문장을 교정해줘: 로그인, 회원가입, 검색 기능 만들어줘").
_KOREAN_TIED_WORD: Final = re.compile(r"(?:에|에서|에게|한테|으로|로|의|을|를)(?:\s|$)|[:：]")
# The last word of an item that names one thing rather than a feature: the list is that thing's content.
_ONE_THING_NOUN: Final = re.compile(r"(?:^|\s)(?:목록|리스트|표|문서|메모|함수|변수|테이블|그래프|차트|색|색깔|글자|문구|이름)(?:만|을|를)?$")
_NUMBER_OR_TIME: Final = re.compile(
    r"\d|요일|^(?:오늘|내일|어제|모레|이번|다음|지난)|^[일이삼사오육칠팔구십백천]+(?:페이지|쪽|번|장|줄|시|일)?$"
)
# An end of a range that names a place in the work rather than a stage ("처음부터 끝까지", "위부터 아래까지").
_KOREAN_POSITION: Final = re.compile(r"처음|시작|끝|마지막|맨\S*|위|아래|왼쪽|오른쪽|앞|뒤|여기|거기|저기")
_KOREAN_RANGE: Final = re.compile(
    rf"(?P<start>[^\s,]+)부터\s+(?:[^\s,]+\s+){{0,3}}?(?P<end>[^\s,]+?)까지(?P<tail>(?:\s*(?:도|{_KOREAN_EXTENT}))*)\s*$"
)
# Several features counted rather than named, as the verb's own object ("여러 기능 나눠서 다 해줘", "기능 여러 개 한꺼번에
# 개발해줘"). Only a noun that is a feature by itself counts: "두 단계 인증", "세 페이지 보고서" and "여러 탭" are one thing.
_KOREAN_COUNTED_NOUN: Final = r"(?:기능|화면|모듈)"
_KOREAN_COUNTED_FEATURES: Final = re.compile(
    rf"(?:^|\s)(?:(?:여러|두|세)\s*(?:개의?\s*)?|(?:몇|\d+)\s*개의?\s*){_KOREAN_COUNTED_NOUN}(?:들)?(?:을|를|도)?"
    rf"(?:\s*{_KOREAN_EXTENT})*\s*$"
    rf"|(?:^|\s){_KOREAN_COUNTED_NOUN}\s*(?:들\s*)?(?:을\s*|를\s*)?여러\s*개(?:를|을)?(?:\s*{_KOREAN_EXTENT})*\s*$"
)
_EN_SOFTWARE_VERB: Final = r"(?:build|implement|develop)"
_EN_BUILD_VERB: Final = rf"(?:{_EN_SOFTWARE_VERB}|add|create|make|ship|wire\s+up|set\s+up|code)"
_EN_REQUEST_LEAD: Final = rf"^(?:please\s+)?{_POLITE_OPENER}?(?:let'?s\s+)?"
_EN_ITEM: Final = r"(?!(?:a|an|the|this|that|it|me|us|them)\b)[a-z][\w-]*(?:\s+(?!and\b)[a-z][\w-]*)?"
_EN_EXTENT: Final = r"(?:\s+(?:end\s+to\s+end|too|as\s+well|all|in\s+order|one\s+by\s+one|together|at\s+once))*"
_EN_LIST_OPENING: Final = rf"{_EN_REQUEST_LEAD}{_EN_BUILD_VERB}\s+(?:the\s+|our\s+|my\s+)?"
_EN_SEVERAL_FEATURES: Final = re.compile(
    rf"{_EN_LIST_OPENING}(?P<many>(?:{_EN_ITEM}\s*,\s*(?:the\s+)?){{2,}}?(?:and\s+)?(?:the\s+)?{_EN_ITEM})"
    rf"|{_EN_LIST_OPENING}(?P<three>{_EN_ITEM}\s*,\s*(?:the\s+)?{_EN_ITEM},?\s+and\s+(?:the\s+)?{_EN_ITEM})"
)
_EN_ITEM_BREAK: Final = re.compile(r"\s*,\s*(?:and\s+)?(?:the\s+)?|\s+and\s+(?:the\s+)?")
_EN_LIST_END: Final = re.compile(rf"{_EN_EXTENT}\s*[.!]*$")
_EN_SOFTWARE_REQUEST: Final = re.compile(rf"{_EN_REQUEST_LEAD}{_EN_SOFTWARE_VERB}\b")
_EN_COUNTED_FEATURES: Final = re.compile(
    rf"{_EN_REQUEST_LEAD}{_EN_SOFTWARE_VERB}\s+(?:several|multiple)\s+(?:features|screens|modules){_EN_EXTENT}\s*[.!]*$"
)
_EN_RANGE: Final = re.compile(
    rf"{_EN_REQUEST_LEAD}{_EN_SOFTWARE_VERB}\s+"
    r"(?:it|everything|all\s+of\s+it|the\s+(?:whole\s+)?(?:app|product|service|system|flow|thing))\s+"
    r"from\s+(?:the\s+)?(?P<start>[a-z][\w-]*(?:\s+[a-z][\w-]*)?)\s+(?:to|through|until)\s+(?:the\s+)?"
    rf"(?P<end>[a-z][\w-]*(?:\s+[a-z][\w-]*)?){_EN_EXTENT}\s*[.!]*$"
)
# An end of a range that names a place or a date rather than a stage ("from start to finish", "from monday to friday").
_EN_NOT_A_STAGE: Final = re.compile(
    r"\d|^(?:start|finish|beginning|end|top|bottom|left|right|front|back|scratch|here|there|today|tomorrow|yesterday"
    r"|(?:mon|tues|wednes|thurs|fri|satur|sun)day|january|february|march|april|may|june|july|august|september|october"
    r"|november|december)$"
)


# Past this a message is a brief or a pasted log, not one sentence naming features: it reads as on main, and this reader,
# run on every turn, adds nothing to what the long input already costs the others.
_SEVERAL_FEATURES_MAX_CHARS: Final = 1000


def _names_product_features(items: list[str], pattern: re.Pattern[str]) -> bool:
    """Whether two or more ``items`` end on a common product feature, the last among them: unknown words prove nothing."""
    ended = [bool(pattern.search(item)) for item in items]
    return ended[-1] and sum(ended) >= 2


def _korean_feature_list(head: str, software_verb: bool) -> bool:
    """Whether ``head``, the request before its verb, ends in a list of three or more features as the verb's object."""
    tail = _KOREAN_LIST_TAIL.search(head)
    if not tail:
        return False
    items = [item.strip() for item in _KOREAN_JOINER.split(head[: tail.start()])]
    if len(items) < 3 or not all(items):
        return False
    # The first item may carry words before it ("회원가입 로그인부터 일반채팅"); every later one is a feature of one or two
    # words, and no word in the list is tied by a case particle to something the list sits inside.
    if any(_KOREAN_TIED_WORD.search(item) for item in items):
        return False
    if any(len(item.split()) > 2 or _NUMBER_OR_TIME.search(item) for item in items[1:]):
        return False
    if not tail.group("noun") and not tail.group("soft") and _names_product_features(items, _KOREAN_PRODUCT_FEATURE):
        return True
    # One-word items and a last one of two ("아이디, 비밀번호, 이메일 가입 화면", "상품명, 가격, 재고 표시 화면"): the last word
    # describes the one screen the list fills, unless the items are product features themselves.
    describes_one_thing = len(items[-1].split()) == 2 and all(len(item.split()) == 1 for item in items[:-1])
    if tail.group("noun"):
        return not describes_one_thing or sum(bool(_KOREAN_PRODUCT_FEATURE.search(item)) for item in items) >= 2
    if not software_verb or describes_one_thing:
        return False
    if tail.group("soft") or all(len(item.split()) == 2 for item in items):
        return not _ONE_THING_NOUN.search(items[-1]) and not items[-1].endswith("만")
    return False


def _en_feature_list(words: str) -> bool:
    """Whether ``words`` asks to build a list of three or more features: with a noun that is a feature by itself on it,
    or under a verb that builds software and nothing else, with a softer noun or items that are product features."""
    listed = _EN_SEVERAL_FEATURES.match(words)
    if not listed or not _EN_LIST_END.fullmatch(words[listed.end() :]):
        return False
    last = (listed.group("many") or listed.group("three")).rsplit(maxsplit=1)[-1]
    if re.fullmatch(_EN_FEATURE_NOUN, last):
        return True
    if not _EN_SOFTWARE_REQUEST.match(words):
        return False
    items = _EN_ITEM_BREAK.split(listed.group("many") or listed.group("three"))
    return bool(re.fullmatch(_EN_SOFT_FEATURE_NOUN, last)) or _names_product_features(items, _EN_PRODUCT_FEATURE)


def _korean_build_request(folded: str) -> tuple[str, str] | None:
    """The request's head and its build verb, when a Korean request ends on a verb that builds something new; the verb
    is empty for a bare 해 after an adverb of extent or order ("여러 기능 나눠서 다 해줘", "결제, 쿠폰, 환불 기능을 순서대로해")."""
    verb, bare = _korean_request_verb(folded)
    if not verb:
        return None
    head = folded[: folded.rfind(verb)].rstrip()
    build = re.search(_KOREAN_NEW_VERB, verb)
    if build:
        return (head + " " + verb[: build.start()]).strip(), verb[build.start() :]
    if bare and re.fullmatch(_KOREAN_EXTENT, verb):
        return (head + " " + verb).strip(), ""  # "다 해줘": the extent is the head's, the bare ending its verb
    extent = re.fullmatch(rf"(?P<extent>{_KOREAN_EXTENT})해(?:\s*{_KOREAN_GIVE})?", verb)
    if extent:
        return (head + " " + extent.group("extent")).strip(), ""
    return None


def _korean_stage_range(head: str, verb: str) -> bool:
    """Whether ``head`` ends in a range from one stage to another under a verb that makes the whole of it."""
    if not re.match(_KOREAN_RANGE_VERB, verb):
        return False
    span = _KOREAN_RANGE.search(head)
    return bool(span) and not any(
        _NUMBER_OR_TIME.search(end) or re.fullmatch(_TIME_WORD, end) or _KOREAN_POSITION.fullmatch(end)
        for end in (span.group("start"), span.group("end"))
    )


def names_several_features(text: str, links: tuple[str, ...] = ()) -> bool:
    """Whether ``text`` asks to build several named features or stages: a list of three or more, a range from one stage
    to another, or several counted, as the build verb's object (`_korean_feature_list`, `_korean_stage_range`,
    `_KOREAN_COUNTED_FEATURES`, `_en_feature_list`, `_EN_RANGE`, `_EN_COUNTED_FEATURES`). Nothing hard-excluded qualifies,
    and neither does a question, a request to be told, or one fault to fix. The router asks once with dag-ulw as the
    candidate, and the route hint offers it; neither starts a run."""
    if len(text) > _SEVERAL_FEATURES_MAX_CHARS:
        return False
    request, whole = _closed(_folded(text))
    if "?" in request or "？" in request or _asks_to_be_told(text) or _hard_excluded(whole, links, request):
        return False
    if _one_fault(request):
        return False
    if re.search(r"[가-힣]", request):
        found = _korean_build_request(request)
        if found is None:
            return False
        head, verb = found
        return (
            _korean_feature_list(head, bool(re.match(_KOREAN_SOFTWARE_VERB, verb)))
            or bool(_KOREAN_COUNTED_FEATURES.search(head))
            or _korean_stage_range(head, verb)
        )
    words = request.rstrip(" .!")
    if _en_feature_list(words) or _EN_COUNTED_FEATURES.match(words):
        return True
    span = _EN_RANGE.match(words)
    return bool(span) and not any(_EN_NOT_A_STAGE.search(span.group(end)) for end in ("start", "end"))
