<div align="center">

<br>

<img src="assets/oh-my-hermes-wordmark.png?v=spectrum" alt="OH-MY-HERMES" width="70%">

<br>
<br>

<img src="assets/omh-logo.png" alt="Logo do oh-my-hermes: o personagem do oh-my-hermes em traço preto grosso sobre um bloco branco de cantos arredondados" width="200">

<br>
<br>

**Pacote tudo-em-um para o Hermes Agent. Instale uma vez e depois é só digitar `dag-ulw`.**

[![GitHub Release](https://img.shields.io/github/v/release/rlaope/oh-my-hermes?color=58a6ff&labelColor=black&logo=github&style=flat-square)](https://github.com/rlaope/oh-my-hermes/releases)
[![npm downloads](https://img.shields.io/npm/dt/oh-my-hermes?color=3fb950&labelColor=black&logo=npm&label=downloads&style=flat-square)](https://www.npmjs.com/package/oh-my-hermes)
[![GitHub Contributors](https://img.shields.io/github/contributors/rlaope/oh-my-hermes?color=bc8cff&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/graphs/contributors)
[![GitHub Stars](https://img.shields.io/github/stars/rlaope/oh-my-hermes?color=e3b341&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/stargazers)
[![License](https://img.shields.io/github/license/rlaope/oh-my-hermes?color=white&labelColor=black&style=flat-square)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-omher.app-58a6ff?labelColor=black&logo=readthedocs&logoColor=white&style=flat-square)](https://omher.app/)

[English](README.md) | [简体中文](README.zh.md) | [日本語](README.ja.md) | [Русский](README.ru.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md) | [Italiano](README.it.md)

**oh-my-hermes** é uma camada de operação para o [Hermes Agent](https://github.com/NousResearch/hermes-agent).<br>
Você continua falando com o Hermes. O OMH escolhe skill e modelo por lane e roda o trabalho em paralelo.<br>
Ele nunca altera nem substitui o Hermes, e nunca relata trabalho planejado como concluído.

</div>

## Instalação

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
```

**Windows (PowerShell 5.1+):**

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
omh setup
```

**Ou cole isto no seu agente de IA:**

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, agent setup path, model-chain interview, and doctor steps. Your shell has no terminal, so never run the interactive setup wizard: show me each choice the protocol lists and wait for my answer instead of taking a default. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

[Mais opções →](docs/INSTALLATION.md)

<br>

## O que você ganha

- **O modelo certo para cada lane.**<br>
  Cada lane recebe uma categoria de trabalho: `ultrabrain`, `deep`, `visual-engineering`, `quick` e outras.<br>
  A categoria define a cadeia de modelos e o esforço de raciocínio da lane, e toda cadeia é editável.<br>
  Se um provider recusa um modelo, a cadeia passa ao próximo em vez de rebaixar em silêncio.<br>
  `omh model` abre o seletor; [veja qual modelo roda em cada lane](docs/INSTALLATION.md#guided-model-setup).

- **Execuções em grafo com `/dag-ulw`.**<br>
  Seu objetivo vira um grafo de nós pequenos, e os que estão prontos rodam em paralelo.<br>
  Cada nó usa o modelo e o esforço da sua categoria; nós simultâneos nunca compartilham escopo de escrita.<br>
  Um nó separado verifica o objetivo, e os nós que falharam são reparados antes do relatório.

- **Skills especialistas sob demanda.**<br>
  Mais de cem especialistas `omh-*`: frontend, backend, Rust, revisão de segurança, gates de verificação.<br>
  Você nunca os chama; o router carrega os certos na execução como chamadas de ferramenta.

- **Memória de longo prazo confiável.**<br>
  Nada é lembrado em silêncio: cada candidato é mantido, recusado ou adiado com um motivo escrito.<br>
  A próxima sessão recebe lembranças ordenadas para a tarefa, dentro de um orçamento de tokens.<br>
  A memória própria do Hermes nunca é lida nem alterada.

- **OMH Native.**<br>
  `omh` sozinho abre a TUI própria do OMH sobre o gateway do Hermes; troque o visual com `/theme`.<br>
  `/dag-ulw` mostra o grafo em caixas e depois uma árvore de lanes ao vivo com modelo, esforço e tokens.<br>
  Guie ou interrompa um agente pela lista de agentes, rode uma linha de shell com `!` e volte com Esc Esc.

- **Evidência antes do “pronto”.**<br>
  Todo status mostra sua etapa e o quanto o OMH tem certeza dela.<br>
  `Plan · not run` · `Code · reported done` · `Test · verified`<br>
  Uma execução só conta como verificada quando um teste, revisão ou gate de CI passou de fato.

<br>

## DAG-ULW

**É só digitar `/dag-ulw` e você vira mestre em engenharia de grafos.**

Seu objetivo vira um grafo de nós pequenos que rodam em paralelo, cada um no seu próprio modelo.<br>
Um nó separado verifica o objetivo antes de você receber o relatório.

<p align="center">
  <img src="assets/omh-dag-ulw-tui.gif" alt="A TUI do OMH rodando /dag-ulw: o prompt é digitado, o grafo de sete lanes é definido, as lanes rodam camada por camada em Claude Opus 5.5, GPT-6.1 Sol, DeepSeek V4.1 Flash, GLM 5.3 e Kimi K3.1 Pro, e todas terminam aceitas" width="900">
</p>

> [!TIP]
> Venha com a gente!
>
> <table>
>   <tr>
>     <td width="124"><a href="https://x.com/rlaope"><img alt="X link" src="https://img.shields.io/badge/Follow-%40rlaope-00CED1?style=flat-square&logo=x&labelColor=black" width="112" /></a></td>
>     <td>As novidades do <code>oh-my-hermes</code> saem no <a href="https://x.com/rlaope">@rlaope</a> no X, junto com notas de versão e notícias do projeto.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope"><img alt="GitHub Follow" src="https://img.shields.io/github/followers/rlaope?style=flat-square&logo=github&labelColor=black&color=24292f" width="112" /></a></td>
>     <td>Siga <a href="https://github.com/rlaope">@rlaope</a> no GitHub para ver mais projetos, versões e o trabalho em andamento.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://discord.gg/6EjTP3cWM"><img alt="Discord invite" src="https://img.shields.io/badge/Join-Discord-5865F2?style=flat-square&logo=discord&logoColor=white&labelColor=black" width="112" /></a></td>
>     <td>Entre na <a href="https://discord.gg/6EjTP3cWM">Oh-My-Hermes Community</a> no Discord para tirar dúvidas, compartilhar workflows e conversar com outros usuários.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors"><img alt="AI agent collaborators" src="https://img.shields.io/badge/With-AI%20agents-6f42c1?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Feito com os agentes de IA <a href="https://github.com/frirenai"><strong>Friren</strong></a> e <a href="https://github.com/sionic-khope"><strong>Kami</strong></a>, colaboradores que ajudam a entregar o <code>oh-my-hermes</code>.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://nousresearch.com/"><img alt="Thanks to Nous Research" src="https://img.shields.io/badge/Thanks-Nous%20Research-4B2E83?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Obrigado à <a href="https://nousresearch.com/">Nous Research</a> por criar o Hermes Agent.</td>
>   </tr>
> </table>

> **Patrocinadores** Estes são nossos patrocinadores. Eles ajudam o oh-my-hermes a seguir em frente.
>
> <table>
>   <tr>
>     <td width="160" align="center"><a href="https://opengateway.ai/"><img alt="OpenGateway" src="assets/sponsors/opengateway.svg" width="140" /></a></td>
>     <td><a href="https://opengateway.ai/"><strong>OpenGateway</strong></a> patrocina o oh-my-hermes, obrigado por apoiar o código aberto.<br>Um único endpoint compatível com OpenAI para muitos provedores de modelos, com failover automático.</td>
>   </tr>
> </table>

<br>

## Outros

[Documentação](docs/README.md) · [Instalação](docs/INSTALLATION.md) · [Capabilities](docs/CAPABILITIES.md) · [Workflows](docs/WORKFLOWS.md) · [Site](https://omher.app/)

Mais opções de instalação e a referência completa estão no [README em inglês](README.md#others).

## Licença

MIT, veja [LICENSE](LICENSE).<br>
Feito em aberto com [nossos colaboradores](https://github.com/rlaope/oh-my-hermes/graphs/contributors) como parte do [Team Art & Engineering](https://rlaope.github.io/artengine-lab/).
