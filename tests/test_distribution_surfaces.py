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
    "curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh",
    "irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex",
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

        ids = (
            "cmd-brew",
            "cmd-bun",
            "cmd-npm",
            "cmd-unix",
            "cmd-win",
            "cmd-setup",
            "cmd-doctor",
        )
        expected = (*INSTALL_COMMANDS, SETUP_COMMAND, DOCTOR_COMMAND)
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
        # "other installation paths" toggle after doctor, INSTALLATION.md
        # lists it first.
        script_run = (*INSTALL_COMMANDS[3:], SETUP_COMMAND, DOCTOR_COMMAND)
        manager_run = INSTALL_COMMANDS[:3]

        for relative in surfaces:
            with self.subTest(surface=relative):
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

                script_positions = [first_block(c) for c in script_run]
                self.assertEqual(script_positions, sorted(script_positions))
                self.assertNotEqual(
                    script_positions[-2],
                    script_positions[-1],
                    f"{relative} groups canonical setup with doctor",
                )
                manager_positions = [first_block(c) for c in manager_run]
                self.assertEqual(manager_positions, sorted(manager_positions))

    def test_agent_protocol_pins_script_installers_after_package_managers(
        self,
    ) -> None:
        protocol = (PROJECT_ROOT / "INSTALL_FOR_AGENTS.md").read_text(
            encoding="utf-8"
        )
        protocol = protocol.split("## Step 1: Install OMH", 1)[1]
        ordered = (
            "brew install rlaope/tap/omh",
            "bun install -g oh-my-hermes",
            "npm install -g oh-my-hermes",
            'git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main',
            'raw.githubusercontent.com/rlaope/oh-my-hermes/$OMH_REF/install.sh',
            'raw.githubusercontent.com/rlaope/oh-my-hermes/$Ref/install.ps1',
            "omh setup --model-setup --interactive",
            "omh doctor",
        )
        positions = tuple(protocol.index(value) for value in ordered)
        self.assertEqual(positions, tuple(sorted(positions)))

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
        ):
            self.assertIn(f'"{key}"', translations)
