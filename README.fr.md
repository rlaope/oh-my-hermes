<div align="center">

<br>

<img src="assets/oh-my-hermes-wordmark.png?v=spectrum" alt="OH-MY-HERMES" width="70%">

<br>
<br>

<img src="assets/omh-logo.png" alt="Logo d'oh-my-hermes : le personnage d'oh-my-hermes en trait noir épais sur une tuile blanche aux coins arrondis" width="200">

<br>
<br>

**Le pack tout-en-un pour Hermes Agent. Installez-le une fois, puis tapez simplement `dag-ulw`.**

[![GitHub Release](https://img.shields.io/github/v/release/rlaope/oh-my-hermes?color=58a6ff&labelColor=black&logo=github&style=flat-square)](https://github.com/rlaope/oh-my-hermes/releases)
[![npm downloads](https://img.shields.io/npm/dt/oh-my-hermes?color=3fb950&labelColor=black&logo=npm&label=downloads&style=flat-square)](https://www.npmjs.com/package/oh-my-hermes)
[![GitHub Contributors](https://img.shields.io/github/contributors/rlaope/oh-my-hermes?color=bc8cff&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/graphs/contributors)
[![GitHub Stars](https://img.shields.io/github/stars/rlaope/oh-my-hermes?color=e3b341&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/stargazers)
[![License](https://img.shields.io/github/license/rlaope/oh-my-hermes?color=white&labelColor=black&style=flat-square)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-omher.app-58a6ff?labelColor=black&logo=readthedocs&logoColor=white&style=flat-square)](https://omher.app/)

[English](README.md) | [简体中文](README.zh.md) | [日本語](README.ja.md) | [Русский](README.ru.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md) | [Italiano](README.it.md)

**oh-my-hermes** est une couche d'exploitation pour [Hermes Agent](https://github.com/NousResearch/hermes-agent).<br>
Vous parlez toujours à Hermes. OMH choisit la skill et le modèle de chaque lane, puis parallélise le travail.<br>
Il ne modifie ni ne remplace jamais Hermes, et ne présente jamais un travail prévu comme terminé.

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

**Ou collez ceci dans votre agent IA :**

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, agent setup path, model-chain interview, and doctor steps. Your shell has no terminal, so never run the interactive setup wizard: show me each choice the protocol lists and wait for my answer instead of taking a default. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

[Autres options →](docs/INSTALLATION.md)

<br>

## Ce que vous obtenez

- **Le bon modèle pour chaque lane.**<br>
  Chaque lane porte une catégorie de travail : `ultrabrain`, `deep`, `visual-engineering`, `quick` et d'autres.<br>
  La catégorie fixe la chaîne de modèles et l'effort de raisonnement de la lane ; chaque chaîne se modifie.<br>
  Si un provider refuse un modèle, la chaîne passe au suivant au lieu de rétrograder en silence.<br>
  `omh model` ouvre le sélecteur ; [voir quel modèle exécute chaque lane](docs/INSTALLATION.md#guided-model-setup).

- **Des exécutions en graphe avec `/dag-ulw`.**<br>
  Votre objectif devient un graphe de petits nœuds, et ceux qui sont prêts tournent en parallèle.<br>
  Un nœud suit le modèle et l'effort de sa catégorie ; deux nœuds parallèles n'écrivent jamais au même endroit.<br>
  Un nœud distinct vérifie l'objectif, et les nœuds en échec sont réparés avant le rapport.

- **Des skills expertes à la demande.**<br>
  Plus d'une centaine de spécialistes `omh-*` : frontend, backend, Rust, revue de sécurité, contrôles de vérification.<br>
  Vous ne les appelez jamais ; le routeur charge les bons dans l'exécution sous forme d'appels d'outils.

- **Une mémoire à long terme fiable.**<br>
  Rien n'est mémorisé en silence : chaque candidat est gardé, refusé ou reporté, avec une raison écrite.<br>
  La session suivante reçoit un pack de rappel classé pour sa tâche et limité à un budget de tokens.<br>
  La mémoire propre d'Hermes n'est jamais lue ni modifiée.

- **OMH Native.**<br>
  `omh` seul ouvre la TUI d'OMH sur la gateway d'Hermes ; changez son style de lancement avec `/theme`.<br>
  `/dag-ulw` affiche le graphe en boîtes, puis un arbre de lanes en direct avec modèle, effort et tokens.<br>
  Pilotez ou interrompez un agent depuis la liste, lancez une ligne shell avec `!`, revenez en arrière avec Esc Esc.

- **Des preuves avant « terminé ».**<br>
  Chaque statut indique son étape et le degré de certitude d'OMH.<br>
  `Plan · not run` · `Code · reported done` · `Test · verified`<br>
  Une exécution n'est vérifiée que si un test, une revue ou un contrôle CI a réellement réussi.

<br>

## DAG-ULW

**Tapez simplement `/dag-ulw`, et vous voilà maître de l'ingénierie de graphes.**

Votre objectif devient un graphe de petits nœuds qui tournent en parallèle, chacun sur son modèle.<br>
Un nœud distinct vérifie l'objectif avant que vous receviez le rapport.

<p align="center">
  <img src="assets/omh-dag-ulw-tui.gif" alt="La TUI d'OMH exécutant /dag-ulw : le prompt est saisi, le graphe de sept lanes est défini, les lanes tournent couche par couche sur Claude Opus 5.5, GPT-6.1 Sol, DeepSeek V4.1 Flash, GLM 5.3 et Kimi K3.1 Pro, et chaque lane se termine acceptée" width="900">
</p>

> [!TIP]
> Rejoignez-nous !
>
> <table>
>   <tr>
>     <td width="124"><a href="https://x.com/rlaope"><img alt="X link" src="https://img.shields.io/badge/Follow-%40rlaope-00CED1?style=flat-square&logo=x&labelColor=black" width="112" /></a></td>
>     <td>Les nouveautés d'<code>oh-my-hermes</code> sont partagées par <a href="https://x.com/rlaope">@rlaope</a> sur X, avec les notes de version et les actualités du projet.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope"><img alt="GitHub Follow" src="https://img.shields.io/github/followers/rlaope?style=flat-square&logo=github&labelColor=black&color=24292f" width="112" /></a></td>
>     <td>Suivez <a href="https://github.com/rlaope">@rlaope</a> sur GitHub pour d'autres projets, les versions et le travail en cours.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://discord.gg/6EjTP3cWM"><img alt="Discord invite" src="https://img.shields.io/badge/Join-Discord-5865F2?style=flat-square&logo=discord&logoColor=white&labelColor=black" width="112" /></a></td>
>     <td>Rejoignez l'<a href="https://discord.gg/6EjTP3cWM">Oh-My-Hermes Community</a> sur Discord pour poser vos questions, partager vos workflows et échanger avec d'autres utilisateurs.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors"><img alt="AI agent collaborators" src="https://img.shields.io/badge/With-AI%20agents-6f42c1?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Construit avec les agents IA <a href="https://github.com/frirenai"><strong>Friren</strong></a> et <a href="https://github.com/sionic-khope"><strong>Kami</strong></a>, des collaborateurs qui aident à livrer <code>oh-my-hermes</code>.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://nousresearch.com/"><img alt="Thanks to Nous Research" src="https://img.shields.io/badge/Thanks-Nous%20Research-4B2E83?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Merci à <a href="https://nousresearch.com/">Nous Research</a> d'avoir créé Hermes Agent.</td>
>   </tr>
> </table>

> **Sponsors** Voici nos sponsors. Ils aident oh-my-hermes à avancer.
>
> <table>
>   <tr>
>     <td width="160" align="center"><a href="https://opengateway.ai/"><img alt="OpenGateway" src="assets/sponsors/opengateway.svg" width="140" /></a></td>
>     <td><a href="https://opengateway.ai/"><strong>OpenGateway</strong></a> sponsorise oh-my-hermes, merci de soutenir l'open source.<br>Un seul endpoint compatible OpenAI pour de nombreux fournisseurs de modèles, avec basculement automatique.</td>
>   </tr>
> </table>

<br>

## Autres

[Documentation](docs/README.md) · [Installation](docs/INSTALLATION.md) · [Capabilities](docs/CAPABILITIES.md) · [Workflows](docs/WORKFLOWS.md) · [Site web](https://omher.app/)

D'autres options d'installation et la référence complète se trouvent dans le [README en anglais](README.md#others).

## Licence

MIT, voir [LICENSE](LICENSE).<br>
Développé en open source avec [nos contributeurs](https://github.com/rlaope/oh-my-hermes/graphs/contributors) au sein de [Team Art & Engineering](https://rlaope.github.io/artengine-lab/).
