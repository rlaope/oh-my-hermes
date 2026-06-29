from __future__ import annotations

from functools import lru_cache
import unicodedata


_EXPLICIT_CATALOG_PHRASES = (
    "what commands are available",
    "which commands are available",
    "commands do you have",
    "what skills are available",
    "which skills are available",
    "skills do you have",
    "what workflows are available",
    "which workflows are available",
    "what workflows are installed",
    "which workflows are installed",
    "what skills are installed",
    "which skills are installed",
    "what commands are installed",
    "which commands are installed",
    "workflows do you have",
    "what workflows can omh do",
    "what workflows can oh-my-hermes do",
    "what skills can omh do",
    "what skills can oh-my-hermes do",
    "what commands can omh do",
    "what commands can oh-my-hermes do",
    "available commands",
    "available skills",
    "available workflows",
    "installed commands",
    "installed skills",
    "installed workflows",
    "list commands",
    "list skills",
    "list workflows",
    "show commands",
    "show skills",
    "show workflows",
    "show me omh commands",
    "show me oh-my-hermes commands",
    "show me the omh commands",
    "show me the oh-my-hermes commands",
    "show me omh skills",
    "show me oh-my-hermes skills",
    "show me the omh skills",
    "show me the oh-my-hermes skills",
    "show me omh workflows",
    "show me oh-my-hermes workflows",
    "show me the omh workflows",
    "show me the oh-my-hermes workflows",
    "command menu",
    "skill menu",
    "workflow menu",
    "skill picker",
    "workflow picker",
    "what can omh do",
    "what can oh-my-hermes do",
    "catalog",
    "omh로 할 수 있는",
    "omh가 할 수 있는",
    "oh-my-hermes로 할 수 있는",
    "할 수 있는 workflow",
    "할 수 있는 workflows",
    "할 수 있는 워크플로",
    "할 수 있는 워크플로우",
    "할 수 있는 스킬",
    "할 수 있는 기능",
    "comandos disponibles",
    "habilidades disponibles",
    "flujos de trabajo disponibles",
    "commandes disponibles",
    "competences disponibles",
    "fluxos de trabalho disponiveis",
    "comandos disponiveis",
    "verfugbare befehle",
    "verfugbare workflows",
    "befehle verfugbar",
    "workflows verfugbar",
    "使えるスキル",
    "利用可能なスキル",
    "利用可能なワークフロー",
    "有哪些命令",
    "有哪些技能",
    "有哪些工作流",
    "可用命令",
    "可用技能",
    "可用工作流",
    "доступные команды",
    "доступные навыки",
    "доступные рабочие процессы",
    "список команд",
    "목록",
    "리스트",
)
_EXPLICIT_OMH_CAPABILITY_PHRASES = (
    "what can omh do",
    "what can oh-my-hermes do",
    "what can i do with omh",
    "what can i do with oh-my-hermes",
    "what can you do with omh",
    "what can you do with oh-my-hermes",
    "what does omh do",
    "what does oh-my-hermes do",
    "how can omh help",
    "how can oh-my-hermes help",
    "can omh help with",
    "can oh-my-hermes help with",
    "what is omh useful for",
    "what is oh-my-hermes useful for",
    "how should i use omh",
    "how should i use oh-my-hermes",
    "omh로 뭐 할 수",
    "omh로 무엇을 할 수",
    "oh-my-hermes로 뭐 할 수",
    "oh-my-hermes로 무엇을 할 수",
    "omh가 뭐 해",
    "omh가 무엇을 해",
    "omh가 뭘 도와",
    "omh가 무엇을 도와",
    "omh가 어떻게 도와",
    "omh가 우리 팀에서 어떻게 쓰",
    "omh는 뭐 해",
    "omh는 무엇을 해",
    "omh는 뭘 도와",
    "omh는 무엇을 도와",
    "omh는 어떻게 쓰",
    "omh를 어떻게 쓰",
    "omh 기능 뭐",
    "oh-my-hermes 기능 뭐",
)
_OMH_CONTEXT_MARKERS = ("omh", "oh-my-hermes", "oh my hermes")
_CONTEXT_MARKERS = _OMH_CONTEXT_MARKERS + ("hermes", "헤르메스")
_CONTEXT_CAPABILITY_MARKERS = (
    "help",
    "use",
    "useful",
    "support",
    "helpful",
    "도와",
    "쓰",
    "활용",
    "할 수",
    "가능",
)
_MISSED_WORKFLOW_MARKERS = (
    "did not use",
    "didn't use",
    "didnt use",
    "does not use",
    "doesn't use",
    "doesnt use",
    "not used",
    "was not used",
    "were not used",
    "not use",
    "not using",
    "without omh",
    "missed omh",
    "skipped omh",
    "forgot omh",
    "not aware",
    "did not know",
    "didn't know",
    "does not know",
    "몰랐",
    "모르",
    "안 썼",
    "안 써",
    "안쓰",
    "안 쓰",
    "놓쳤",
    "빠졌",
)
_NAMED_WORKFLOW_MARKERS = (
    "deep-interview",
    "ralplan",
    "ultragoal",
    "loop",
    "ultraprocess",
    "web-research",
    "research-department",
    "source-finder",
    "paper-learning",
    "feedback-triage",
    "materials-package",
    "img-summary",
    "automation-blueprint",
    "code-review",
)
_WORKFLOW_EXPLANATION_MARKERS = (
    "what",
    "which",
    "explain",
    "describe",
    "how",
    "뭐",
    "무엇",
    "어떤",
    "설명",
    "무슨",
)
_CATALOG_COLLECTION_WORDS = (
    "skills",
    "skill",
    "skill들",
    "workflows",
    "workflow",
    "commands",
    "command",
    "스킬",
    "워크플로",
    "워크플로우",
    "명령",
    "기능",
    "comandos",
    "habilidades",
    "flujos de trabajo",
    "fluxos de trabalho",
    "commandes",
    "competences",
    "befehle",
    "スキル",
    "ワークフロー",
    "コマンド",
    "技能",
    "工作流",
    "命令",
    "команды",
    "навыки",
    "рабочие процессы",
)
_CATALOG_WORDS = _CATALOG_COLLECTION_WORDS
_AVAILABILITY_MARKERS = (
    "available",
    "installed",
    "do you have",
    "are there",
    "can i use",
    "can you do",
    "menu",
    "picker",
    "disponible",
    "disponibles",
    "disponivel",
    "disponiveis",
    "liste",
    "lista",
    "mostrar",
    "afficher",
    "anzeigen",
    "gibt es",
    "verfugbar",
    "verfuegbar",
    "使える",
    "利用可能",
    "一覧",
    "有哪些",
    "可用",
    "列表",
    "доступ",
    "список",
    "متاحة",
    "قائمة",
    "उपलब्ध",
    "danh sach",
    "có những",
    "tersedia",
    "daftar",
    "뭐",
    "무엇",
    "어떤",
    "알려",
    "보여",
    "있어",
    "있나요",
    "가능",
    "설치",
    "설치된",
    "깔린",
    "깔려",
    "목록",
    "리스트",
)
_PLURAL_CATALOG_WORDS = (
    "command",
    "commands",
    "skill",
    "skills",
    "workflow",
    "workflows",
    "워크플로",
    "워크플로우",
    "스킬",
)
_COMMAND_QUESTION_MARKERS = (
    "command to",
    "command should i run",
    "what command",
    "which command",
    "show me the command",
    "comando deberia ejecutar",
    "comando debería ejecutar",
    "commande dois-je executer",
    "commande dois-je exécuter",
    "명령어 알려",
    "명령어 뭐",
)
_OPERATOR_ACTION_MARKERS = (
    "install",
    "installation",
    "setup",
    "verify",
    "verification",
    "doctor",
    "download",
    "curl",
    "installer",
    "instalar",
    "installer omh",
    "설치",
    "검증",
    "확인",
)
_COMMAND_ERROR_MARKERS = (
    "command not found",
    "permission denied",
    "modulenotfounderror",
    "module not found",
    "no such file or directory",
    "명령어를 찾을 수",
    "명령을 찾을 수",
    "권한 거부",
)
_FILE_OR_TEXT_MARKERS = (
    "file",
    "files",
    "path",
    "paths",
    "grep",
    "rg",
    "mention",
    "mentions",
    "containing",
    "contains",
    "파일",
    "경로",
    "언급",
    "포함",
    "찾아",
    "검색",
)
_REPO_LOOKUP_CONTEXT_MARKERS = (
    "repo",
    "repository",
    "project",
    "codebase",
    "workspace",
    "checkout",
    "working tree",
    "working-tree",
    "저장소",
    "레포",
    "프로젝트",
    "코드베이스",
    "작업공간",
)
_SOURCE_ACQUISITION_CONTEXT_MARKERS = (
    "github",
    "oss",
    "open source",
    "repo 찾아",
    "repo find",
    "repositories",
    "dataset",
    "datasets",
    "paper",
    "papers",
    "presentation",
    "presentations",
    "compare",
    "comparison",
    "비교",
    "자료",
    "데이터셋",
    "논문",
    "발표",
)
_WORKFLOW_REVIEW_INTENT_MARKERS = (
    "claim",
    "claims",
    "release",
    "review",
    "verify",
    "verification",
    "doctor",
    "harness",
    "matches",
    "match",
    "주장",
    "릴리즈",
    "검토",
    "검증",
    "실제",
    "맞는지",
    "통과",
)
_PATH_REFERENCE_MARKERS = (
    "src/",
    "tests/",
    "docs/",
    "site/",
    "assets/",
    "skills/",
    ".omh/",
    ".omx/",
    "~/",
    "../",
    "/users/",
    "c:\\",
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    "readme",
    "section",
)
_FILE_SUMMARY_TARGET_MARKERS = (
    "file",
    "files",
    "readme",
    "파일",
)
_FILE_LOOKUP_ACTION_MARKERS = (
    "find",
    "show",
    "open",
    "read",
    "summarize",
    "summarise",
    "summary",
    "search",
    "look up",
    "lookup",
    "locate",
    "찾아",
    "찾아줘",
    "보여",
    "보여줘",
    "열어",
    "열어줘",
    "읽어",
    "읽어줘",
    "요약",
    "검색",
    "어디",
)
_CATALOG_COLLISION_MARKERS = _CATALOG_COLLECTION_WORDS + ("명령어",)
_OPERATOR_ACTION_QUESTION_MARKERS = (
    "how can i",
    "how do i",
    "how should i",
    "what can",
    "can i",
    "help me",
    "어떻게",
    "방법",
)


@lru_cache(maxsize=4096)
def is_skill_catalog_question(message: str) -> bool:
    lowered = message.strip().lower()
    if not lowered:
        return False
    search_texts = _catalog_search_texts(lowered)
    if _contains_catalog_token(search_texts, _COMMAND_ERROR_MARKERS):
        return False
    if _is_operator_command_question(search_texts):
        return False
    if _is_operator_action_question(search_texts):
        return False
    if _is_file_or_text_search_question(search_texts):
        return False
    if _is_missed_workflow_feedback(search_texts):
        return False
    if _contains_catalog_token(search_texts, _EXPLICIT_OMH_CAPABILITY_PHRASES):
        return True
    if _is_named_workflow_catalog_question(search_texts):
        return True
    if _is_context_capability_question(search_texts):
        return True
    has_context = _contains_catalog_token(search_texts, _CONTEXT_MARKERS)
    has_catalog_word = _contains_catalog_token(search_texts, _CATALOG_WORDS)
    if not has_catalog_word:
        return False
    if _contains_catalog_token(search_texts, _EXPLICIT_CATALOG_PHRASES):
        return True
    has_catalog_collection_word = _contains_catalog_token(search_texts, _CATALOG_COLLECTION_WORDS)
    if not has_context and has_catalog_collection_word and _contains_catalog_token(search_texts, _AVAILABILITY_MARKERS):
        return True
    if has_context and has_catalog_collection_word and _contains_catalog_token(search_texts, _AVAILABILITY_MARKERS):
        return True
    words = lowered.replace("?", " ").replace("!", " ").split()
    return has_context and len(words) <= 4 and _contains_catalog_token(search_texts, _PLURAL_CATALOG_WORDS)


@lru_cache(maxsize=4096)
def is_file_or_text_lookup_question(message: str) -> bool:
    lowered = message.strip().lower()
    if not lowered:
        return False
    return _is_file_or_text_search_question(_catalog_search_texts(lowered))


@lru_cache(maxsize=4096)
def _catalog_search_texts(lowered: str) -> tuple[str, ...]:
    folded = "".join(
        character for character in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(character)
    )
    return (lowered,) if folded == lowered else (lowered, folded)


def _is_operator_command_question(search_texts: tuple[str, ...]) -> bool:
    return _contains_catalog_token(search_texts, _COMMAND_QUESTION_MARKERS) and _contains_catalog_token(
        search_texts, _OPERATOR_ACTION_MARKERS
    )


def _is_file_or_text_search_question(search_texts: tuple[str, ...]) -> bool:
    if _contains_catalog_token(search_texts, _WORKFLOW_REVIEW_INTENT_MARKERS):
        return False
    if _contains_catalog_token(search_texts, _SOURCE_ACQUISITION_CONTEXT_MARKERS):
        return False
    if _contains_catalog_token(search_texts, _FILE_OR_TEXT_MARKERS) and _contains_catalog_token(
        search_texts, _REPO_LOOKUP_CONTEXT_MARKERS
    ):
        return True
    if _contains_catalog_token(search_texts, _FILE_SUMMARY_TARGET_MARKERS) and _contains_file_lookup_action(
        search_texts
    ):
        return True
    if _contains_catalog_token(search_texts, _PATH_REFERENCE_MARKERS):
        if _contains_file_lookup_action(search_texts):
            return True
        return _contains_catalog_token(search_texts, _CONTEXT_MARKERS) or _contains_catalog_token(
            search_texts, _CATALOG_COLLISION_MARKERS
        ) or _contains_catalog_token(search_texts, _NAMED_WORKFLOW_MARKERS)
    return _contains_catalog_token(search_texts, _FILE_OR_TEXT_MARKERS) and _contains_catalog_token(
        search_texts, _CATALOG_COLLISION_MARKERS
    )


def _contains_file_lookup_action(search_texts: tuple[str, ...]) -> bool:
    for text in search_texts:
        word_text = _word_search_text(text)
        for marker in _FILE_LOOKUP_ACTION_MARKERS:
            if marker.isascii():
                if f" {marker} " in word_text:
                    return True
            elif marker in text:
                return True
    return False


def _word_search_text(text: str) -> str:
    cleaned = "".join(character if character.isalnum() else " " for character in text)
    return f" {' '.join(cleaned.split())} "


def _is_named_workflow_catalog_question(search_texts: tuple[str, ...]) -> bool:
    return (
        _contains_catalog_token(search_texts, _OMH_CONTEXT_MARKERS)
        and _contains_catalog_token(search_texts, _NAMED_WORKFLOW_MARKERS)
        and _contains_catalog_token(search_texts, _WORKFLOW_EXPLANATION_MARKERS)
    )


def _is_context_capability_question(search_texts: tuple[str, ...]) -> bool:
    return _contains_catalog_token(search_texts, _OMH_CONTEXT_MARKERS) and _contains_catalog_token(
        search_texts, _CONTEXT_CAPABILITY_MARKERS
    )


def _is_missed_workflow_feedback(search_texts: tuple[str, ...]) -> bool:
    return _contains_catalog_token(search_texts, _OMH_CONTEXT_MARKERS) and _contains_catalog_token(
        search_texts, _MISSED_WORKFLOW_MARKERS
    )


def _is_operator_action_question(search_texts: tuple[str, ...]) -> bool:
    return _contains_catalog_token(search_texts, _OPERATOR_ACTION_MARKERS) and _contains_catalog_token(
        search_texts, _OPERATOR_ACTION_QUESTION_MARKERS
    )


@lru_cache(maxsize=16384)
def _contains_catalog_token(search_texts: tuple[str, ...], tokens: tuple[str, ...]) -> bool:
    return any(token in text for text in search_texts for token in tokens)
