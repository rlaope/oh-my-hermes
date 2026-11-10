from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]

INSTALL_COMMANDS = (
    "brew install rlaope/tap/omh",
    "bun install -g oh-my-hermes",
    "npm install -g oh-my-hermes",
    # The short forms omher.app serves (site/install, site/install.ps1); each
    # downloads the main-branch installer and runs it with no added argument.
    "curl -fsSL https://omher.app/install | sh",
    "irm https://omher.app/install.ps1 | iex",
)
SETUP_COMMAND = "omh setup"
DOCTOR_COMMAND = "omh doctor"
LIFECYCLE_COMMANDS = (
    "brew upgrade rlaope/tap/omh",
    "brew uninstall omh",
    "bun update -g --latest oh-my-hermes",
    "bun remove -g oh-my-hermes",
    "npm update -g oh-my-hermes",
    "npm uninstall -g oh-my-hermes",
)


class _CodeCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.codes: dict[str, str] = {}
        self._active_id: str | None = None
        self._text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag != "code":
            return
        code_id = dict(attrs).get("id")
        if code_id:
            self._active_id = code_id
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._active_id is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "code" and self._active_id is not None:
            self.codes[self._active_id] = "".join(self._text).strip()
            self._active_id = None
            self._text = []


def _fenced_blocks(markdown: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] | None = None
    for line in markdown.splitlines():
        if line.startswith("```"):
            if current is None:
                current = []
            else:
                blocks.append("\n".join(current).strip())
                current = None
            continue
        if current is not None:
            current.append(line)
    return blocks


class DistributionInstallSurfaceTests(unittest.TestCase):
    def test_site_public_status_drives_unique_styles_and_translations(
        self,
    ) -> None:
        page = (PROJECT_ROOT / "site" / "index.html").read_text(
            encoding="utf-8"
        )
        styles = (PROJECT_ROOT / "site" / "home.css").read_text(
            encoding="utf-8"
        )
        translations = (PROJECT_ROOT / "site" / "i18n.js").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            translations.count('"install.availability.note":'),
            1,
        )
        self.assertEqual(styles.count(".install-availability {"), 1)
        self.assertIn(
            '[data-package-manager-status="public"]',
            styles,
        )
        self.assertNotIn(
            '[data-package-manager-status="pending"]',
            styles,
        )
        self.assertEqual(
            page.count("install-method--package-manager"),
            3,
        )

    def test_launcher_cache_location_retention_and_removal_are_documented(
        self,
    ) -> None:
        for relative in ("docs/INSTALLATION.md", "packaging/npm/README.md"):
            with self.subTest(surface=relative):
                content = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("OMH_CACHE_DIR", content)
                self.assertIn(
                    "~/Library/Caches/oh-my-hermes/npm",
                    content,
                )
                self.assertIn(
                    "~/.cache/oh-my-hermes/npm",
                    content,
                )
                self.assertIn(
                    "%LOCALAPPDATA%\\oh-my-hermes\\Cache\\npm",
                    content,
                )

    def test_localized_installers_use_separate_copyable_blocks(self) -> None:
        for relative in ("README.ko.md", "README.ja.md", "README.zh.md"):
            with self.subTest(surface=relative):
                content = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
                blocks = [
                    block.strip()
                    for block in re.findall(
                        r"```(?:sh|powershell)\n(.*?)```",
                        content,
                        flags=re.DOTALL,
                    )
                ]
                for command in INSTALL_COMMANDS:
                    self.assertIn(command, blocks)
        # The short READMEs carry only the two script installers, each in its
        # own block; package managers live in the English README.
        for locale in ("de", "es", "fr", "it", "pt-BR", "ru"):
            with self.subTest(surface=f"README.{locale}.md"):
                content = (PROJECT_ROOT / f"README.{locale}.md").read_text(encoding="utf-8")
                first_lines = [
                    block.strip().splitlines()[0]
                    for block in re.findall(
                        r"```(?:sh|powershell)\n(.*?)```",
                        content,
                        flags=re.DOTALL,
                    )
                ]
                for command in INSTALL_COMMANDS[3:]:
                    self.assertIn(command, first_lines)
                for command in INSTALL_COMMANDS[:3]:
                    self.assertNotIn(command, content)

    def test_package_manager_lifecycle_and_state_ownership_are_documented(
        self,
    ) -> None:
        for relative in (
            "README.md",
            "docs/INSTALLATION.md",
            "INSTALL_FOR_AGENTS.md",
        ):
            with self.subTest(surface=relative):
                content = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
                for command in LIFECYCLE_COMMANDS:
                    self.assertIn(command, content)
                self.assertIn("omh uninstall --all", content)

    def test_windows_package_manager_boundary_is_explicit(self) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
        ).read_text(encoding="utf-8")
        windows = workflow[workflow.index("test-windows:") :]
        self.assertIn("actions/setup-node@", windows)
        self.assertIn("oven-sh/setup-bun@", windows)

    def test_published_package_manager_commands_are_marked_public(self) -> None:
        html = (PROJECT_ROOT / "site" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('data-package-manager-status="public"', html)
        self.assertNotIn('data-package-manager-status="pending"', html)

    def test_site_exposes_ordered_copyable_install_commands(self) -> None:
        html = (PROJECT_ROOT / "site" / "index.html").read_text(
            encoding="utf-8"
        )
        parser = _CodeCollector()
        parser.feed(html)

        # The script installers lead, as on every other front door; the
        # package managers follow with their prerequisite note.
        ids = (
            "cmd-unix",
            "cmd-win",
            "cmd-brew",
            "cmd-bun",
            "cmd-npm",
            "cmd-setup",
            "cmd-doctor",
        )
        expected = (*INSTALL_COMMANDS[3:], *INSTALL_COMMANDS[:3], SETUP_COMMAND, DOCTOR_COMMAND)
        self.assertEqual(
            tuple(parser.codes.get(code_id) for code_id in ids),
            expected,
        )
        positions = tuple(html.index(f'id="{code_id}"') for code_id in ids)
        self.assertEqual(positions, tuple(sorted(positions)))
        self.assertNotEqual(
            parser.codes["cmd-setup"],
            parser.codes["cmd-doctor"],
        )
        note = html.index('data-i18n="install.prereq.note"')
        self.assertLess(html.index('id="cmd-npm"'), note)
        self.assertLess(note, html.index('id="cmd-setup"'))

    def test_markdown_install_surfaces_share_order_and_separate_steps(self) -> None:
        surfaces = (
            "README.md",
            "README.ko.md",
            "README.ja.md",
            "README.zh.md",
            "docs/INSTALLATION.md",
        )
        # Two ordered runs share every markdown surface: the script installers
        # lead into setup and then doctor, and the package managers keep their
        # brew -> bun -> npm order. Where the package-manager run sits relative
        # to the script run is the surface's call: the READMEs fold it into an
        # "install options" toggle after the quick install, INSTALLATION.md
        # lists it first. The READMEs open with the owner's two-line quick
        # install (the POSIX script, then setup) and keep the Windows script
        # in that toggle, so their ordered run is curl -> setup -> doctor and
        # the Windows script only has to be present; INSTALLATION.md keeps the
        # full curl -> irm -> setup -> doctor order.
        full_script_run = (*INSTALL_COMMANDS[3:], SETUP_COMMAND, DOCTOR_COMMAND)
        readme_script_run = (INSTALL_COMMANDS[3], SETUP_COMMAND, DOCTOR_COMMAND)
        manager_run = INSTALL_COMMANDS[:3]

        for relative in surfaces:
            with self.subTest(surface=relative):
                is_readme = relative.startswith("README")
                script_run = readme_script_run if is_readme else full_script_run
                blocks = _fenced_blocks(
                    (PROJECT_ROOT / relative).read_text(encoding="utf-8")
                )

                def first_block(command: str) -> int:
                    matches = [
                        index
                        for index, block in enumerate(blocks)
                        if command in block.splitlines()
                    ]
                    self.assertTrue(matches, f"{relative} is missing {command}")
                    return matches[0]

                if is_readme:
                    first_block(INSTALL_COMMANDS[4])
                script_positions = [first_block(c) for c in script_run]
                self.assertEqual(script_positions, sorted(script_positions))
                self.assertNotEqual(
                    script_positions[-2],
                    script_positions[-1],
                    f"{relative} groups canonical setup with doctor",
                )
                manager_positions = [first_block(c) for c in manager_run]
                self.assertEqual(manager_positions, sorted(manager_positions))

    def test_agent_protocol_leads_with_pinned_script_installers(
        self,
    ) -> None:
        # An agent picks one path by rule: the SHA-pinned script installer for
        # its OS, and a package manager only when the user asks for one. The
        # setup step it runs is the non-interactive one, because an agent's
        # shell has no terminal and the wizard would take every default.
        protocol = (PROJECT_ROOT / "INSTALL_FOR_AGENTS.md").read_text(
            encoding="utf-8"
        )
        protocol = protocol.split("## Step 1: Install OMH", 1)[1]
        ordered = (
            'git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main',
            'raw.githubusercontent.com/rlaope/oh-my-hermes/$OMH_REF/install.sh',
            'raw.githubusercontent.com/rlaope/oh-my-hermes/$Ref/install.ps1',
            'uv tool install "git+https://github.com/rlaope/oh-my-hermes@$OMH_REF"',
            "brew install rlaope/tap/omh",
            "bun install -g oh-my-hermes",
            "npm install -g oh-my-hermes",
            "omh setup --model-setup --no-interactive --json",
            "omh doctor",
        )
        positions = tuple(protocol.index(value) for value in ordered)
        self.assertEqual(positions, tuple(sorted(positions)))
        self.assertNotIn("(recommended)", protocol)
        for block in _fenced_blocks(protocol):
            self.assertIsNone(re.search(r"(?<!no-)--interactive\b", block), block)
            self.assertNotIn("exit 1", block)
        # A chosen project scope is carried through every later command:
        # HERMES_HOME is exported once from the repository root, and the
        # commands name the scope, or they read and write ~/.omh and ~/.hermes.
        self.assertIn('export HERMES_HOME="$root/.hermes"', protocol)
        self.assertIn("project scope needs a git repository", protocol)
        for command in (
            "omh setup --model-setup --scope project --no-interactive --json",
            "omh --scope project model-chains show",
            "omh --scope project doctor",
            "omh --scope project update-check set",
            "omh --scope project coding category-maestro show",
        ):
            self.assertIn(command, protocol)

    def test_site_translations_cover_new_install_labels(self) -> None:
        translations = (PROJECT_ROOT / "site" / "i18n.js").read_text(
            encoding="utf-8"
        )
        for key in (
            "install.method.brew",
            "install.method.bun",
            "install.method.npm",
            "install.method.unix",
            "install.method.windows",
            "install.doctor.title",
            "install.doctor.note",
            "install.prereq.note",
        ):
            self.assertIn(f'"{key}"', translations)
