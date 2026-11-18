"""The fixed onboarding prompts the OMH TUI sends once, as the first turn of a new session, under `omh --onboard`.

Only `omh --onboard <name>` sets `OMH_TUI_ONBOARD` (`launch.ONBOARD_ENV`), and
only the last question of an interactive `omh setup` runs it: it is the one
place the TUI sends a prompt the person did not type, and it sends it once, in
a new session (`App._send_onboarding`). The text is a message from the person
to Hermes, packaged here so that it is the same on every machine; Hermes'
skill does the work. English is the master; `ko`, `ja` and `zh` say the same
with product, command and model names left as they are.
"""

from __future__ import annotations

ONBOARDING_NAMES = ("model-setup",)
ONBOARDING_LANGUAGES = ("en", "ko", "ja", "zh")

_MODEL_SETUP = {
    "en": (
        "I just installed oh-my-hermes. Set up my models with the model-setup skill, by conversation, one step at a "
        "time.\n"
        "\n"
        "1. First show me what this machine already has: Hermes' main model, the configured providers, the "
        "credential pools, and which provider API-key environment variable NAMES are present. Show names only, never "
        "values, and never ask me to paste a key into this chat.\n"
        "2. Ask which of those I want to use, and whether I want to add another provider (Claude, OpenAI, Gemini, "
        "Kimi, GLM, DeepSeek, Grok, OpenRouter, ...). For one I want but have no key for, tell me exactly what to run "
        "in another terminal (`hermes auth add <provider>`, or `hermes model` for OAuth/login), wait for me, then "
        "check again.\n"
        "3. Set the main model, and at most one fallback model (none if I have only one provider).\n"
        "4. Set the subagent category chains from OMH's shipped recommendations, ordered to the providers I have "
        "(`omh model-chains provider set`, `omh model-chains show`), and keep the rest of the shipped chain.\n"
        "5. Show me every change as one preview, apply it only after I say yes, then re-read the configuration and "
        "show me the result.\n"
        "6. End by telling me that to change any of this later, I can just say it in chat (for example \"use GPT for "
        "code review\").\n"
        "\n"
        "Reply in my language."
    ),
    "ko": (
        "방금 oh-my-hermes를 설치했어요. model-setup 스킬로 제 모델 설정을 대화로, 한 단계씩 진행해 주세요.\n"
        "\n"
        "1. 먼저 이 컴퓨터에 이미 있는 것을 보여 주세요: Hermes의 메인 모델, 설정된 provider, credential pool, 그리고 "
        "어떤 provider API 키 환경 변수의 이름(NAME)이 있는지. 이름만 보여 주고 값은 절대 보여 주지 마세요. 이 채팅에 "
        "키를 붙여 넣으라고 절대 요청하지 마세요.\n"
        "2. 그중 무엇을 쓸지, 그리고 다른 provider(Claude, OpenAI, Gemini, Kimi, GLM, DeepSeek, Grok, OpenRouter 등)를 "
        "추가할지 물어봐 주세요. 쓰고 싶은데 키가 없는 provider는 다른 터미널에서 실행할 명령(`hermes auth add "
        "<provider>`, OAuth/로그인은 `hermes model`)을 정확히 알려 주고, 제가 마칠 때까지 기다린 뒤 다시 확인해 주세요.\n"
        "3. 메인 모델을 설정하고, fallback 모델은 최대 하나만 설정해 주세요(provider가 하나뿐이면 fallback 없음).\n"
        "4. 서브에이전트 카테고리 체인을 OMH가 함께 제공하는 권장안에서 제가 가진 provider 순서에 맞춰 설정하고"
        "(`omh model-chains provider set`, `omh model-chains show`), 제공된 체인의 나머지는 그대로 두세요.\n"
        "5. 모든 변경을 하나의 미리보기로 보여 주고, 제가 좋다고 한 뒤에만 적용한 다음, 설정을 다시 읽어 결과를 보여 "
        "주세요.\n"
        "6. 마지막으로, 나중에 무엇이든 바꾸고 싶으면 채팅에서 그냥 말하면 된다고 알려 주세요(예: \"코드 리뷰에는 GPT를 "
        "써 줘\").\n"
        "\n"
        "제가 쓰는 언어로 답해 주세요."
    ),
    "ja": (
        "oh-my-hermes をインストールしたところです。model-setup スキルを使って、会話で一歩ずつ私のモデルを設定してください。\n"
        "\n"
        "1. まず、このマシンにすでにあるものを見せてください: Hermes のメインモデル、設定済みの provider、credential "
        "pool、そしてどの provider API キーの環境変数の名前 (NAME) があるか。名前だけを示し、値は決して表示しないでください。"
        "このチャットにキーを貼り付けるよう決して求めないでください。\n"
        "2. その中からどれを使うか、また別の provider (Claude、OpenAI、Gemini、Kimi、GLM、DeepSeek、Grok、OpenRouter "
        "など) を追加するかを聞いてください。使いたいのにキーがない provider については、別のターミナルで実行するコマンド "
        "(`hermes auth add <provider>`、OAuth/ログインなら `hermes model`) を正確に伝え、私が終えるのを待ってから、もう一度"
        "確認してください。\n"
        "3. メインモデルを設定し、fallback モデルは最大 1 つにしてください (provider が 1 つだけなら fallback はなし)。\n"
        "4. サブエージェントのカテゴリチェーンを、OMH に同梱の推奨から、私の持つ provider に合わせた順序で設定し "
        "(`omh model-chains provider set`、`omh model-chains show`)、同梱チェーンの残りはそのままにしてください。\n"
        "5. すべての変更を 1 つのプレビューで見せ、私が「はい」と言ってから適用し、設定を読み直して結果を見せてください。\n"
        "6. 最後に、あとで何かを変えたいときはチャットでそう言うだけでよい (例:「コードレビューには GPT を使って」) と"
        "伝えてください。\n"
        "\n"
        "私の言語で返答してください。"
    ),
    "zh": (
        "我刚安装了 oh-my-hermes。请用 model-setup 技能，通过对话一步一步帮我设置模型。\n"
        "\n"
        "1. 先给我看这台机器上已有的内容：Hermes 的主模型、已配置的 provider、credential pool，以及存在哪些 provider "
        "API 密钥环境变量的名称（NAME）。只显示名称，绝不显示值，也绝不要让我把密钥粘贴到这个聊天里。\n"
        "2. 问我想用其中哪些，以及是否要添加其他 provider（Claude、OpenAI、Gemini、Kimi、GLM、DeepSeek、Grok、"
        "OpenRouter 等）。对于我想用但没有密钥的 provider，准确告诉我在另一个终端里运行什么（`hermes auth add "
        "<provider>`，OAuth/登录用 `hermes model`），等我完成后再检查一次。\n"
        "3. 设置主模型，以及最多一个 fallback 模型（如果我只有一个 provider，就不设 fallback）。\n"
        "4. 按照 OMH 自带的推荐、依我拥有的 provider 排好顺序来设置子代理分类链（`omh model-chains provider set`、"
        "`omh model-chains show`），自带链的其余部分保持不变。\n"
        "5. 把所有改动作为一个预览给我看，等我同意后再应用，然后重新读取配置并给我看结果。\n"
        "6. 最后告诉我：以后想改任何设置，直接在聊天里说就行（例如“代码审查用 GPT”）。\n"
        "\n"
        "请用我的语言回复。"
    ),
}

_PROMPTS = {"model-setup": _MODEL_SETUP}


def onboarding_prompt(name: str, language: str = "en") -> str:
    """The onboarding prompt `name` in `language`; English for a language it has none in.

    Raises ValueError for a name that is not in `ONBOARDING_NAMES`.
    """
    prompts = _PROMPTS.get(name)
    if prompts is None:
        raise ValueError(f"unknown onboarding {name!r}; expected one of: {', '.join(ONBOARDING_NAMES)}")
    return prompts.get(language, prompts["en"])
