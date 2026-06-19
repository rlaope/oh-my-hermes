from __future__ import annotations

import unicodedata


def is_skill_catalog_question(message: str) -> bool:
    lowered = message.strip().lower()
    if not lowered:
        return False
    search_texts = _catalog_search_texts(lowered)
    if _is_operator_command_question(search_texts):
        return False
    if _is_file_or_text_search_question(search_texts):
        return False
    explicit_catalog_phrases = (
        "what commands are available",
        "which commands are available",
        "commands do you have",
        "what skills are available",
        "which skills are available",
        "skills do you have",
        "what workflows are available",
        "which workflows are available",
        "workflows do you have",
        "available commands",
        "available skills",
        "available workflows",
        "list commands",
        "list skills",
        "list workflows",
        "show commands",
        "show skills",
        "show workflows",
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
    context_markers = ("omh", "oh-my-hermes", "oh my hermes", "hermes", "헤르메스")
    catalog_words = (
        "skill",
        "skills",
        "workflow",
        "workflows",
        "command",
        "commands",
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
        "workflows",
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
    has_context = _contains_catalog_token(search_texts, context_markers)
    has_catalog_word = _contains_catalog_token(search_texts, catalog_words)
    if not has_catalog_word:
        return False
    if _contains_catalog_token(search_texts, explicit_catalog_phrases):
        return True
    catalog_collection_words = (
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
    has_catalog_collection_word = _contains_catalog_token(search_texts, catalog_collection_words)
    availability_markers = (
        "available",
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
        "목록",
        "리스트",
    )
    if not has_context and has_catalog_collection_word and _contains_catalog_token(search_texts, availability_markers):
        return True
    if has_context and has_catalog_collection_word and _contains_catalog_token(search_texts, availability_markers):
        return True
    words = lowered.replace("?", " ").replace("!", " ").split()
    plural_catalog_words = (
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
    return has_context and len(words) <= 4 and _contains_catalog_token(search_texts, plural_catalog_words)


def _catalog_search_texts(lowered: str) -> tuple[str, ...]:
    folded = "".join(
        character for character in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(character)
    )
    return (lowered,) if folded == lowered else (lowered, folded)


def _is_operator_command_question(search_texts: tuple[str, ...]) -> bool:
    command_question_markers = (
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
    operator_action_markers = (
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
    return _contains_catalog_token(search_texts, command_question_markers) and _contains_catalog_token(
        search_texts, operator_action_markers
    )


def _is_file_or_text_search_question(search_texts: tuple[str, ...]) -> bool:
    file_or_text_markers = (
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
    catalog_collision_markers = (
        "command",
        "commands",
        "skill",
        "skills",
        "workflow",
        "workflows",
        "명령",
        "명령어",
        "스킬",
        "워크플로",
        "워크플로우",
    )
    return _contains_catalog_token(search_texts, file_or_text_markers) and _contains_catalog_token(
        search_texts, catalog_collision_markers
    )


def _contains_catalog_token(search_texts: tuple[str, ...], tokens: tuple[str, ...]) -> bool:
    return any(token in text for text in search_texts for token in tokens)
