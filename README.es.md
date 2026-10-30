<div align="center">

<br>

<img src="assets/oh-my-hermes-wordmark.png?v=spectrum" alt="OH-MY-HERMES" width="70%">

<br>
<br>

<img src="assets/omh-logo.png" alt="Logo de oh-my-hermes: el personaje de oh-my-hermes en trazo negro grueso sobre un mosaico blanco de esquinas redondeadas" width="200">

<br>
<br>

**Paquete todo en uno para Hermes Agent. Instálalo una vez y luego solo escribe `dag-ulw`.**

[![GitHub Release](https://img.shields.io/github/v/release/rlaope/oh-my-hermes?color=58a6ff&labelColor=black&logo=github&style=flat-square)](https://github.com/rlaope/oh-my-hermes/releases)
[![npm downloads](https://img.shields.io/npm/dt/oh-my-hermes?color=3fb950&labelColor=black&logo=npm&label=downloads&style=flat-square)](https://www.npmjs.com/package/oh-my-hermes)
[![GitHub Contributors](https://img.shields.io/github/contributors/rlaope/oh-my-hermes?color=bc8cff&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/graphs/contributors)
[![GitHub Stars](https://img.shields.io/github/stars/rlaope/oh-my-hermes?color=e3b341&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/stargazers)
[![License](https://img.shields.io/github/license/rlaope/oh-my-hermes?color=white&labelColor=black&style=flat-square)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-omher.app-58a6ff?labelColor=black&logo=readthedocs&logoColor=white&style=flat-square)](https://omher.app/)

[English](README.md) | [简体中文](README.zh.md) | [日本語](README.ja.md) | [Русский](README.ru.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md) | [Italiano](README.it.md)

**oh-my-hermes** es una capa de operación para [Hermes Agent](https://github.com/NousResearch/hermes-agent).<br>
Sigues hablando con Hermes. OMH elige la skill y un modelo para cada lane, y ejecuta el trabajo en paralelo.<br>
Nunca parchea ni reemplaza Hermes, y nunca presenta como hecho un trabajo solo planificado.

</div>

## Instalación

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
```

**Windows (PowerShell 5.1+):**

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
omh setup
```

**O pega esto en tu agente de IA:**

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, agent setup path, model-chain interview, and doctor steps. Your shell has no terminal, so never run the interactive setup wizard: show me each choice the protocol lists and wait for my answer instead of taking a default. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

[Más opciones →](docs/INSTALLATION.md)

<br>

## Qué obtienes

- **El modelo adecuado para cada lane.**<br>
  Cada lane lleva una categoría de trabajo: `ultrabrain`, `deep`, `visual-engineering`, `quick` y más.<br>
  La categoría fija la cadena de modelos y el esfuerzo de razonamiento de esa lane, y puedes editar cada cadena.<br>
  Si un provider rechaza un modelo, la cadena pasa al siguiente en vez de degradarlo en silencio.<br>
  `omh model` abre el selector; [mira qué modelo ejecuta cada lane](docs/INSTALLATION.md#guided-model-setup).

- **Ejecuciones en grafo con `/dag-ulw`.**<br>
  Tu objetivo se convierte en un grafo de nodos pequeños, y los que están listos corren en paralelo.<br>
  Cada nodo usa el modelo y el esfuerzo de su categoría; nodos simultáneos no comparten ámbito de escritura.<br>
  Un nodo aparte verifica el objetivo, y los nodos fallidos se reparan antes del informe.

- **Skills expertas bajo demanda.**<br>
  Más de cien especialistas `omh-*`: frontend, backend, Rust, revisión de seguridad, gates de verificación.<br>
  Nunca los llamas tú; el router carga los adecuados en la ejecución como llamadas a herramientas.

- **Memoria a largo plazo en la que puedes confiar.**<br>
  Nada se recuerda en silencio: cada candidato se guarda, se rechaza o se aplaza con un motivo escrito.<br>
  La siguiente sesión recibe recuerdos ordenados para su tarea, dentro de un presupuesto de tokens.<br>
  La memoria propia de Hermes nunca se lee ni se modifica.

- **OMH Native.**<br>
  `omh` a secas abre la TUI propia de OMH sobre el gateway de Hermes; cambia su aspecto con `/theme`.<br>
  `/dag-ulw` imprime el grafo en cajas y luego un árbol de lanes en vivo con modelo, esfuerzo y tokens.<br>
  Dirige o interrumpe un agente desde su lista, ejecuta una línea de shell con `!` y retrocede con Esc Esc.

- **Evidencia antes de “hecho”.**<br>
  Cada estado indica su etapa y cuán seguro está OMH de ella.<br>
  `Plan · not run` · `Code · reported done` · `Test · verified`<br>
  Una ejecución cuenta como verificada solo cuando un test, una revisión o un gate de CI pasó de verdad.

<br>

## DAG-ULW

**Solo escribe `/dag-ulw` y serás un maestro de la ingeniería de grafos.**

Tu objetivo se convierte en un grafo de nodos pequeños que corren en paralelo, cada uno con su modelo.<br>
Un nodo aparte verifica el objetivo antes de que recibas el informe.

<p align="center">
  <img src="assets/omh-dag-ulw-tui.gif" alt="La TUI de OMH ejecutando /dag-ulw: se escribe el prompt, se define el grafo de siete lanes, las lanes corren capa por capa en Claude Opus 5.5, GPT-6.1 Sol, DeepSeek V4.1 Flash, GLM 5.3 y Kimi K3.1 Pro, y todas terminan aceptadas" width="900">
</p>

> [!TIP]
> ¡Únete a nosotros!
>
> <table>
>   <tr>
>     <td width="124"><a href="https://x.com/rlaope"><img alt="X link" src="https://img.shields.io/badge/Follow-%40rlaope-00CED1?style=flat-square&logo=x&labelColor=black" width="112" /></a></td>
>     <td>Las novedades de <code>oh-my-hermes</code> se publican en <a href="https://x.com/rlaope">@rlaope</a> en X, junto con las notas de versión y noticias del proyecto.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope"><img alt="GitHub Follow" src="https://img.shields.io/github/followers/rlaope?style=flat-square&logo=github&labelColor=black&color=24292f" width="112" /></a></td>
>     <td>Sigue a <a href="https://github.com/rlaope">@rlaope</a> en GitHub para ver más proyectos, versiones y trabajo en curso.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://discord.gg/6EjTP3cWM"><img alt="Discord invite" src="https://img.shields.io/badge/Join-Discord-5865F2?style=flat-square&logo=discord&logoColor=white&labelColor=black" width="112" /></a></td>
>     <td>Únete a la <a href="https://discord.gg/6EjTP3cWM">Oh-My-Hermes Community</a> en Discord para hacer preguntas, compartir workflows y hablar con otros usuarios.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors"><img alt="AI agent collaborators" src="https://img.shields.io/badge/With-AI%20agents-6f42c1?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Hecho con los agentes de IA <a href="https://github.com/frirenai"><strong>Friren</strong></a> y <a href="https://github.com/sionic-khope"><strong>Kami</strong></a>, colaboradores que ayudan a publicar <code>oh-my-hermes</code>.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://nousresearch.com/"><img alt="Thanks to Nous Research" src="https://img.shields.io/badge/Thanks-Nous%20Research-4B2E83?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Gracias a <a href="https://nousresearch.com/">Nous Research</a> por crear Hermes Agent.</td>
>   </tr>
> </table>

> **Patrocinadores** Estos son nuestros patrocinadores. Ayudan a que oh-my-hermes siga adelante.
>
> <table>
>   <tr>
>     <td width="160" align="center"><a href="https://opengateway.ai/"><img alt="OpenGateway" src="assets/sponsors/opengateway.svg" width="140" /></a></td>
>     <td><a href="https://opengateway.ai/"><strong>OpenGateway</strong></a> patrocina oh-my-hermes; gracias por apoyar el código abierto.<br>Un único endpoint compatible con OpenAI para muchos proveedores de modelos, con failover automático.</td>
>   </tr>
> </table>

<br>

## Otros

[Documentación](docs/README.md) · [Instalación](docs/INSTALLATION.md) · [Capabilities](docs/CAPABILITIES.md) · [Workflows](docs/WORKFLOWS.md) · [Sitio web](https://omher.app/)

Más opciones de instalación y la referencia completa están en el [README en inglés](README.md#others).

## Licencia

MIT, consulta [LICENSE](LICENSE).<br>
Desarrollado en abierto con [nuestros colaboradores](https://github.com/rlaope/oh-my-hermes/graphs/contributors) como parte de [Team Art & Engineering](https://rlaope.github.io/artengine-lab/).
