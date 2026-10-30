<div align="center">

<br>

<img src="assets/oh-my-hermes-wordmark.png?v=spectrum" alt="OH-MY-HERMES" width="70%">

<br>
<br>

<img src="assets/omh-logo.png" alt="Logo di oh-my-hermes: il personaggio di oh-my-hermes a tratto nero spesso su una tessera bianca con angoli arrotondati" width="200">

<br>
<br>

**Il pacchetto all-in-one per Hermes Agent. Installalo una volta, poi digita semplicemente `dag-ulw`.**

[![GitHub Release](https://img.shields.io/github/v/release/rlaope/oh-my-hermes?color=58a6ff&labelColor=black&logo=github&style=flat-square)](https://github.com/rlaope/oh-my-hermes/releases)
[![npm downloads](https://img.shields.io/npm/dt/oh-my-hermes?color=3fb950&labelColor=black&logo=npm&label=downloads&style=flat-square)](https://www.npmjs.com/package/oh-my-hermes)
[![GitHub Contributors](https://img.shields.io/github/contributors/rlaope/oh-my-hermes?color=bc8cff&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/graphs/contributors)
[![GitHub Stars](https://img.shields.io/github/stars/rlaope/oh-my-hermes?color=e3b341&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/stargazers)
[![License](https://img.shields.io/github/license/rlaope/oh-my-hermes?color=white&labelColor=black&style=flat-square)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-omher.app-58a6ff?labelColor=black&logo=readthedocs&logoColor=white&style=flat-square)](https://omher.app/)

[English](README.md) | [简体中文](README.zh.md) | [日本語](README.ja.md) | [Русский](README.ru.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md) | [Italiano](README.it.md)

**oh-my-hermes** è un livello operativo per [Hermes Agent](https://github.com/NousResearch/hermes-agent).<br>
Continui a parlare con Hermes. OMH sceglie la skill e un modello per ogni lane, ed esegue il lavoro in parallelo.<br>
Non modifica né sostituisce mai Hermes, e non presenta mai come fatto un lavoro solo pianificato.

</div>

## Installazione

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
```

**Windows (PowerShell 5.1+):**

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
omh setup
```

**Oppure incolla questo nel tuo agente IA:**

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, agent setup path, model-chain interview, and doctor steps. Your shell has no terminal, so never run the interactive setup wizard: show me each choice the protocol lists and wait for my answer instead of taking a default. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

[Altre opzioni →](docs/INSTALLATION.md)

<br>

## Cosa ottieni

- **Il modello giusto per ogni lane.**<br>
  Ogni lane ha una categoria di lavoro: `ultrabrain`, `deep`, `visual-engineering`, `quick` e altre.<br>
  La categoria sceglie la catena di modelli e lo sforzo di ragionamento della lane; ogni catena è modificabile.<br>
  Se un provider rifiuta un modello, la catena passa al successivo invece di declassare in silenzio.<br>
  `omh model` apre il selettore; [guarda quale modello esegue ogni lane](docs/INSTALLATION.md#guided-model-setup).

- **Esecuzioni a grafo con `/dag-ulw`.**<br>
  Il tuo obiettivo diventa un grafo di piccoli nodi, e quelli pronti girano in parallelo.<br>
  Ogni nodo usa modello e sforzo della sua categoria; nodi in parallelo non scrivono mai nello stesso ambito.<br>
  Un nodo separato verifica l'obiettivo, e i nodi falliti vengono riparati prima del report.

- **Skill esperte su richiesta.**<br>
  Oltre cento specialisti `omh-*`: frontend, backend, Rust, security review, gate di verifica.<br>
  Non li chiami mai tu; il router carica quelli giusti nell'esecuzione come chiamate di tool.

- **Memoria a lungo termine di cui fidarti.**<br>
  Niente viene ricordato in silenzio: ogni candidato è tenuto, rifiutato o rinviato con un motivo scritto.<br>
  La sessione successiva riceve ricordi ordinati per il suo compito, entro un budget di token.<br>
  La memoria di Hermes non viene mai letta né modificata.

- **OMH Native.**<br>
  `omh` da solo apre la TUI di OMH sul gateway di Hermes; cambia il look di avvio con `/theme`.<br>
  `/dag-ulw` stampa il grafo a riquadri, poi un albero di lane dal vivo con modello, sforzo e token.<br>
  Guida o interrompi un agente dalla lista agenti, esegui una riga di shell con `!` e torna indietro con Esc Esc.

- **Prove prima del “fatto”.**<br>
  Ogni stato indica la sua fase e quanto OMH ne è sicuro.<br>
  `Plan · not run` · `Code · reported done` · `Test · verified`<br>
  Un'esecuzione conta come verificata solo quando un test, una review o un gate di CI è davvero passato.

<br>

## DAG-ULW

**Digita `/dag-ulw` e diventi un maestro dell'ingegneria dei grafi.**

Il tuo obiettivo diventa un grafo di piccoli nodi che girano in parallelo, ognuno sul proprio modello.<br>
Un nodo separato verifica l'obiettivo prima che tu riceva il report.

<p align="center">
  <img src="assets/omh-dag-ulw-tui.gif" alt="La TUI di OMH che esegue /dag-ulw: il prompt viene digitato, il grafo a riquadri di sette lane viene definito, le lane girano strato per strato su Claude Opus 5.5, GPT-6.1 Sol, DeepSeek V4.1 Flash, GLM 5.3 e Kimi K3.1 Pro, e ogni lane termina accettata" width="900">
</p>

> [!TIP]
> Unisciti a noi!
>
> <table>
>   <tr>
>     <td width="124"><a href="https://x.com/rlaope"><img alt="X link" src="https://img.shields.io/badge/Follow-%40rlaope-00CED1?style=flat-square&logo=x&labelColor=black" width="112" /></a></td>
>     <td>Gli aggiornamenti di <code>oh-my-hermes</code> escono su <a href="https://x.com/rlaope">@rlaope</a> su X, insieme alle note di rilascio e alle novità del progetto.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope"><img alt="GitHub Follow" src="https://img.shields.io/github/followers/rlaope?style=flat-square&logo=github&labelColor=black&color=24292f" width="112" /></a></td>
>     <td>Segui <a href="https://github.com/rlaope">@rlaope</a> su GitHub per altri progetti, rilasci e lavori in corso.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://discord.gg/6EjTP3cWM"><img alt="Discord invite" src="https://img.shields.io/badge/Join-Discord-5865F2?style=flat-square&logo=discord&logoColor=white&labelColor=black" width="112" /></a></td>
>     <td>Entra nella <a href="https://discord.gg/6EjTP3cWM">Oh-My-Hermes Community</a> su Discord per fare domande, condividere workflow e parlare con altri utenti.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors"><img alt="AI agent collaborators" src="https://img.shields.io/badge/With-AI%20agents-6f42c1?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Costruito con gli agenti IA <a href="https://github.com/frirenai"><strong>Friren</strong></a> e <a href="https://github.com/sionic-khope"><strong>Kami</strong></a>, collaboratori che aiutano a rilasciare <code>oh-my-hermes</code>.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://nousresearch.com/"><img alt="Thanks to Nous Research" src="https://img.shields.io/badge/Thanks-Nous%20Research-4B2E83?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Grazie a <a href="https://nousresearch.com/">Nous Research</a> per aver creato Hermes Agent.</td>
>   </tr>
> </table>

> **Sponsor** Questi sono i nostri sponsor. Aiutano oh-my-hermes ad andare avanti.
>
> <table>
>   <tr>
>     <td width="160" align="center"><a href="https://opengateway.ai/"><img alt="OpenGateway" src="assets/sponsors/opengateway.svg" width="140" /></a></td>
>     <td><a href="https://opengateway.ai/"><strong>OpenGateway</strong></a> sponsorizza oh-my-hermes, grazie per sostenere l'open source.<br>Un unico endpoint compatibile con OpenAI per molti provider di modelli, con failover automatico.</td>
>   </tr>
> </table>

<br>

## Altro

[Documentazione](docs/README.md) · [Installazione](docs/INSTALLATION.md) · [Capabilities](docs/CAPABILITIES.md) · [Workflows](docs/WORKFLOWS.md) · [Sito web](https://omher.app/)

Altre opzioni di installazione e il riferimento completo sono nel [README in inglese](README.md#others).

## Licenza

MIT, vedi [LICENSE](LICENSE).<br>
Sviluppato in modo aperto con [i nostri contributori](https://github.com/rlaope/oh-my-hermes/graphs/contributors) come parte di [Team Art & Engineering](https://rlaope.github.io/artengine-lab/).
