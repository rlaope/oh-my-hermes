<div align="center">

<br>

<img src="assets/oh-my-hermes-wordmark.png?v=spectrum" alt="OH-MY-HERMES" width="70%">

<br>
<br>

<img src="assets/omh-logo.png" alt="Логотип oh-my-hermes: персонаж oh-my-hermes жирной чёрной линией на белой плитке со скруглёнными углами" width="200">

<br>
<br>

**Пакет «всё в одном» для Hermes Agent. Установите один раз и просто наберите `dag-ulw`.**

[![GitHub Release](https://img.shields.io/github/v/release/rlaope/oh-my-hermes?color=58a6ff&labelColor=black&logo=github&style=flat-square)](https://github.com/rlaope/oh-my-hermes/releases)
[![npm downloads](https://img.shields.io/npm/dt/oh-my-hermes?color=3fb950&labelColor=black&logo=npm&label=downloads&style=flat-square)](https://www.npmjs.com/package/oh-my-hermes)
[![GitHub Contributors](https://img.shields.io/github/contributors/rlaope/oh-my-hermes?color=bc8cff&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/graphs/contributors)
[![GitHub Stars](https://img.shields.io/github/stars/rlaope/oh-my-hermes?color=e3b341&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/stargazers)
[![License](https://img.shields.io/github/license/rlaope/oh-my-hermes?color=white&labelColor=black&style=flat-square)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-omher.app-58a6ff?labelColor=black&logo=readthedocs&logoColor=white&style=flat-square)](https://omher.app/)

[English](README.md) | [简体中文](README.zh.md) | [日本語](README.ja.md) | [Русский](README.ru.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md) | [Italiano](README.it.md)

**oh-my-hermes** — операционный слой поверх [Hermes Agent](https://github.com/NousResearch/hermes-agent).<br>
Вы общаетесь с Hermes. OMH выбирает навык и модель для каждой lane и ведёт работу параллельно.<br>
Он никогда не патчит и не заменяет Hermes и не выдаёт запланированную работу за сделанную.

</div>

## Установка

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
```

**Windows (PowerShell 5.1+):**

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
omh setup
```

**Или вставьте это в своего ИИ-агента:**

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, agent setup path, model-chain interview, and doctor steps. Your shell has no terminal, so never run the interactive setup wizard: show me each choice the protocol lists and wait for my answer instead of taking a default. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

[Другие варианты →](docs/INSTALLATION.md)

<br>

## Что вы получаете

- **Подходящая модель для каждой lane.**<br>
  Каждой lane присваивается рабочая категория: `ultrabrain`, `deep`, `visual-engineering`, `quick` и другие.<br>
  Категория задаёт цепочку моделей и усилие рассуждения для lane; любую цепочку можно изменить.<br>
  Если provider отклоняет модель, цепочка переходит к следующей, а не понижает её молча.<br>
  `omh model` открывает выбор модели; [какая модель работает в каждой lane](docs/INSTALLATION.md#guided-model-setup).

- **Графовые прогоны `/dag-ulw`.**<br>
  Ваша цель превращается в граф небольших узлов, и готовые узлы выполняются параллельно.<br>
  Узел работает на модели и усилии своей категории; одновременные узлы не пишут в одну область.<br>
  Отдельный узел проверяет цель, а упавшие узлы исправляются до отчёта.

- **Экспертные навыки по запросу.**<br>
  Более сотни специалистов `omh-*`: фронтенд, бэкенд, Rust, ревью безопасности, гейты проверки.<br>
  Вызывать их не нужно: роутер сам подгружает нужные в прогон как вызовы инструментов.

- **Долговременная память, которой можно доверять.**<br>
  Ничего не запоминается молча: каждый кандидат принят, отклонён или отложен с записанной причиной.<br>
  Следующая сессия получает подборку памяти под свою задачу в пределах бюджета токенов.<br>
  Собственная память Hermes никогда не читается и не изменяется.

- **OMH Native.**<br>
  Просто `omh` открывает собственный TUI OMH поверх gateway Hermes; вид запуска меняет `/theme`.<br>
  `/dag-ulw` выводит граф из блоков, затем живое дерево lane с моделью, усилием и токенами.<br>
  Управляйте агентами из их списка, запускайте shell через `!` и откатывайтесь по Esc Esc.

- **Сначала доказательства, потом «готово».**<br>
  Каждый статус называет свой этап и степень уверенности OMH.<br>
  `Plan · not run` · `Code · reported done` · `Test · verified`<br>
  Прогон считается проверенным, только если тест, ревью или гейт CI действительно прошли.

<br>

## DAG-ULW

**Просто наберите `/dag-ulw`, и вы мастер графовой инженерии.**

Ваша цель превращается в граф небольших узлов, которые идут параллельно, каждый на своей модели.<br>
Отдельный узел проверяет цель, прежде чем вы получите отчёт.

<p align="center">
  <img src="assets/omh-dag-ulw-tui.gif" alt="OMH TUI выполняет /dag-ulw: вводится запрос, задаётся граф из семи lane, lane выполняются слой за слоем на Claude Opus 5.5, GPT-6.1 Sol, DeepSeek V4.1 Flash, GLM 5.3 и Kimi K3.1 Pro, и каждая lane завершается со статусом accepted" width="900">
</p>

> [!TIP]
> Будьте с нами!
>
> <table>
>   <tr>
>     <td width="124"><a href="https://x.com/rlaope"><img alt="X link" src="https://img.shields.io/badge/Follow-%40rlaope-00CED1?style=flat-square&logo=x&labelColor=black" width="112" /></a></td>
>     <td>Новости <code>oh-my-hermes</code> публикуются в X у <a href="https://x.com/rlaope">@rlaope</a> вместе с заметками о релизах и новостями проекта.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope"><img alt="GitHub Follow" src="https://img.shields.io/github/followers/rlaope?style=flat-square&logo=github&labelColor=black&color=24292f" width="112" /></a></td>
>     <td>Подписывайтесь на <a href="https://github.com/rlaope">@rlaope</a> в GitHub, чтобы следить за другими проектами, релизами и текущей работой.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://discord.gg/6EjTP3cWM"><img alt="Discord invite" src="https://img.shields.io/badge/Join-Discord-5865F2?style=flat-square&logo=discord&logoColor=white&labelColor=black" width="112" /></a></td>
>     <td>Присоединяйтесь к <a href="https://discord.gg/6EjTP3cWM">Oh-My-Hermes Community</a> в Discord: задавайте вопросы, делитесь workflow и общайтесь с другими пользователями.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors"><img alt="AI agent collaborators" src="https://img.shields.io/badge/With-AI%20agents-6f42c1?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Сделано вместе с AI-агентами <a href="https://github.com/frirenai"><strong>Friren</strong></a> и <a href="https://github.com/sionic-khope"><strong>Kami</strong></a>, которые помогают выпускать <code>oh-my-hermes</code>.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://nousresearch.com/"><img alt="Thanks to Nous Research" src="https://img.shields.io/badge/Thanks-Nous%20Research-4B2E83?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Спасибо <a href="https://nousresearch.com/">Nous Research</a> за создание Hermes Agent.</td>
>   </tr>
> </table>

> **Спонсоры** Это наши спонсоры. Благодаря им oh-my-hermes продолжает развиваться.
>
> <table>
>   <tr>
>     <td width="160" align="center"><a href="https://opengateway.ai/"><img alt="OpenGateway" src="assets/sponsors/opengateway.svg" width="140" /></a></td>
>     <td><a href="https://opengateway.ai/"><strong>OpenGateway</strong></a> спонсирует oh-my-hermes. Спасибо, что поддерживаете open source.<br>Один OpenAI-совместимый endpoint для множества провайдеров моделей с автоматическим failover.</td>
>   </tr>
> </table>

<br>

## Прочее

[Документация](docs/README.md) · [Установка](docs/INSTALLATION.md) · [Capabilities](docs/CAPABILITIES.md) · [Workflows](docs/WORKFLOWS.md) · [Сайт](https://omher.app/)

Другие варианты установки и справочник есть в [английском README](README.md#others).

## Лицензия

MIT, см. [LICENSE](LICENSE).<br>
Создаётся открыто вместе с [нашими контрибьюторами](https://github.com/rlaope/oh-my-hermes/graphs/contributors) в рамках [Team Art & Engineering](https://rlaope.github.io/artengine-lab/).
