<div align="center">

<br>

<img src="assets/oh-my-hermes-wordmark.png?v=spectrum" alt="OH-MY-HERMES" width="70%">

<br>
<br>

<img src="assets/omh-logo.png" alt="oh-my-hermes-Logo: die oh-my-hermes-Figur in kräftiger schwarzer Linienzeichnung auf einer weißen Kachel mit abgerundeten Ecken" width="200">

<br>
<br>

**Das All-in-one-Paket für Hermes Agent. Einmal installieren, dann einfach `dag-ulw` eingeben.**

[![GitHub Release](https://img.shields.io/github/v/release/rlaope/oh-my-hermes?color=58a6ff&labelColor=black&logo=github&style=flat-square)](https://github.com/rlaope/oh-my-hermes/releases)
[![npm downloads](https://img.shields.io/npm/dt/oh-my-hermes?color=3fb950&labelColor=black&logo=npm&label=downloads&style=flat-square)](https://www.npmjs.com/package/oh-my-hermes)
[![GitHub Contributors](https://img.shields.io/github/contributors/rlaope/oh-my-hermes?color=bc8cff&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/graphs/contributors)
[![GitHub Stars](https://img.shields.io/github/stars/rlaope/oh-my-hermes?color=e3b341&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/stargazers)
[![License](https://img.shields.io/github/license/rlaope/oh-my-hermes?color=white&labelColor=black&style=flat-square)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-omher.app-58a6ff?labelColor=black&logo=readthedocs&logoColor=white&style=flat-square)](https://omher.app/)

[English](README.md) | [简体中文](README.zh.md) | [日本語](README.ja.md) | [Русский](README.ru.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md) | [Italiano](README.it.md)

**oh-my-hermes** ist eine Betriebsschicht für [Hermes Agent](https://github.com/NousResearch/hermes-agent).<br>
Du sprichst weiter mit Hermes. OMH wählt den Skill und ein Modell für jede Lane und arbeitet parallel.<br>
Es patcht oder ersetzt Hermes nie und meldet geplante Arbeit nie als erledigt.

</div>

## Installation

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
```

**Windows (PowerShell 5.1+):**

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
omh setup
```

**Oder füge das in deinen KI-Agenten ein:**

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, agent setup path, model-chain interview, and doctor steps. Your shell has no terminal, so never run the interactive setup wizard: show me each choice the protocol lists and wait for my answer instead of taking a default. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

[Weitere Optionen →](docs/INSTALLATION.md)

<br>

## Was du bekommst

- **Das passende Modell für jede Lane.**<br>
  Jede Lane trägt eine Arbeitskategorie: `ultrabrain`, `deep`, `visual-engineering`, `quick` und mehr.<br>
  Die Kategorie bestimmt Modellkette und Reasoning-Aufwand der Lane, und jede Kette ist editierbar.<br>
  Lehnt ein Provider ein Modell ab, geht die Kette zum nächsten weiter, statt still herabzustufen.<br>
  `omh model` öffnet die Auswahl; [sieh nach, welches Modell jede Lane ausführt](docs/INSTALLATION.md#guided-model-setup).

- **Graph-Läufe mit `/dag-ulw`.**<br>
  Dein Ziel wird zu einem Graphen kleiner Knoten, und die bereiten laufen parallel.<br>
  Jeder Knoten nutzt Modell und Aufwand seiner Kategorie; parallele Knoten teilen nie einen Schreibbereich.<br>
  Ein eigener Knoten prüft das Ziel, und fehlgeschlagene Knoten werden vor dem Bericht repariert.

- **Experten-Skills auf Abruf.**<br>
  Über hundert `omh-*`-Spezialisten: Frontend, Backend, Rust, Security-Review, Verification-Gates.<br>
  Du rufst sie nie selbst auf; der Router lädt die passenden als Tool-Aufrufe in den Lauf.

- **Langzeitgedächtnis, dem du vertrauen kannst.**<br>
  Nichts wird still gemerkt: Jeder Kandidat wird behalten, abgelehnt oder vertagt, mit schriftlichem Grund.<br>
  Die nächste Sitzung bekommt ein Recall-Paket, nach ihrer Aufgabe gerankt und auf ein Token-Budget gekürzt.<br>
  Das eigene Gedächtnis von Hermes wird nie gelesen oder gepatcht.

- **OMH Native.**<br>
  `omh` allein öffnet OMHs eigene TUI auf dem Gateway von Hermes; den Startlook wechselst du mit `/theme`.<br>
  `/dag-ulw` zeigt den Box-Graphen, dann einen Live-Baum der Lanes mit Modell, Aufwand und Tokens.<br>
  Steuere oder unterbrich Agenten aus ihrer Liste, führe mit `!` Shell-Zeilen aus, spule mit Esc Esc zurück.

- **Belege vor „fertig“.**<br>
  Jeder Status nennt seine Stufe und wie sicher sich OMH ist.<br>
  `Plan · not run` · `Code · reported done` · `Test · verified`<br>
  Ein Lauf gilt nur dann als verifiziert, wenn ein Test, Review oder CI-Gate wirklich bestanden ist.

<br>

## DAG-ULW

**Tipp einfach `/dag-ulw`, und du bist ein Meister des Graph-Engineerings.**

Dein Ziel wird zu einem Graphen kleiner Knoten, die parallel laufen, jeder auf seinem eigenen Modell.<br>
Ein eigener Knoten prüft das Ziel, bevor du den Bericht bekommst.

<p align="center">
  <img src="assets/omh-dag-ulw-tui.gif" alt="Die OMH-TUI führt /dag-ulw aus: Der Prompt wird getippt, der Box-Graph mit sieben Lanes wird definiert, die Lanes laufen Schicht für Schicht auf Claude Opus 5.5, GPT-6.1 Sol, DeepSeek V4.1 Flash, GLM 5.3 und Kimi K3.1 Pro, und jede Lane endet als akzeptiert" width="900">
</p>

> [!TIP]
> Sei dabei!
>
> <table>
>   <tr>
>     <td width="124"><a href="https://x.com/rlaope"><img alt="X link" src="https://img.shields.io/badge/Follow-%40rlaope-00CED1?style=flat-square&logo=x&labelColor=black" width="112" /></a></td>
>     <td>Neuigkeiten zu <code>oh-my-hermes</code> teilt <a href="https://x.com/rlaope">@rlaope</a> auf X, zusammen mit Release Notes und Projekt-News.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope"><img alt="GitHub Follow" src="https://img.shields.io/github/followers/rlaope?style=flat-square&logo=github&labelColor=black&color=24292f" width="112" /></a></td>
>     <td>Folge <a href="https://github.com/rlaope">@rlaope</a> auf GitHub für weitere Projekte, Releases und laufende Arbeit.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://discord.gg/6EjTP3cWM"><img alt="Discord invite" src="https://img.shields.io/badge/Join-Discord-5865F2?style=flat-square&logo=discord&logoColor=white&labelColor=black" width="112" /></a></td>
>     <td>Tritt der <a href="https://discord.gg/6EjTP3cWM">Oh-My-Hermes Community</a> auf Discord bei, um Fragen zu stellen, Workflows zu teilen und dich mit anderen auszutauschen.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors"><img alt="AI agent collaborators" src="https://img.shields.io/badge/With-AI%20agents-6f42c1?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Gebaut mit den KI-Agenten <a href="https://github.com/frirenai"><strong>Friren</strong></a> und <a href="https://github.com/sionic-khope"><strong>Kami</strong></a>, die als Mitwirkende <code>oh-my-hermes</code> mit ausliefern.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://nousresearch.com/"><img alt="Thanks to Nous Research" src="https://img.shields.io/badge/Thanks-Nous%20Research-4B2E83?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Danke an <a href="https://nousresearch.com/">Nous Research</a> für Hermes Agent.</td>
>   </tr>
> </table>

> **Sponsoren** Das sind unsere Sponsoren. Sie helfen, oh-my-hermes am Laufen zu halten.
>
> <table>
>   <tr>
>     <td width="160" align="center"><a href="https://opengateway.ai/"><img alt="OpenGateway" src="assets/sponsors/opengateway.svg" width="140" /></a></td>
>     <td><a href="https://opengateway.ai/"><strong>OpenGateway</strong></a> sponsert oh-my-hermes, danke für die Unterstützung von Open Source.<br>Ein OpenAI-kompatibler Endpoint für viele Modell-Provider, mit automatischem Failover.</td>
>   </tr>
> </table>

<br>

## Weiteres

[Doku](docs/README.md) · [Installation](docs/INSTALLATION.md) · [Capabilities](docs/CAPABILITIES.md) · [Workflows](docs/WORKFLOWS.md) · [Website](https://omher.app/)

Weitere Installationsoptionen und die Referenz findest du im [englischen README](README.md#others).

## Lizenz

MIT, siehe [LICENSE](LICENSE).<br>
Offen entwickelt mit [unseren Mitwirkenden](https://github.com/rlaope/oh-my-hermes/graphs/contributors) als Teil von [Team Art & Engineering](https://rlaope.github.io/artengine-lab/).
