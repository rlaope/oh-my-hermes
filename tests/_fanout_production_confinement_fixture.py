from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
from typing import TypeAlias

from omh.coding.fanout import build_fanout_contract
from omh.coding.fanout_artifacts import write_fanout_contract
from omh.system.paths import OmhPaths


JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


class ProductionConfinementUnavailable(RuntimeError):
    pass


def git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=repository,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


@dataclass(frozen=True, slots=True)
class ProductionConfinementFixture:
    paths: OmhPaths
    repository: Path
    contract: Mapping[str, JsonValue]
    base_sha: str
    environment: Mapping[str, str]
    owner_state: Path
    hook_marker: Path
    fsmonitor_marker: Path


def prepare_production_confinement_fixture(root: Path) -> ProductionConfinementFixture:
    paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
    repository = root / "repo"
    repository.mkdir()
    git(repository, "init", "-q")
    (repository / "seed").write_text("seed\n", encoding="utf-8")
    git(repository, "add", "seed")
    git(
        repository,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.test",
        "commit",
        "-qm",
        "init",
    )
    base_sha = git(repository, "rev-parse", "HEAD")
    contract = write_fanout_contract(
        paths,
        build_fanout_contract(
            "confined linked-worktree commit",
            [
                {
                    "unit_id": "core",
                    "title": "Core work",
                    "owner": "claude-code",
                    "file_scope": ["change.txt"],
                }
            ],
        ),
    )
    run_ref = str(contract["units"][0]["run_ref"])
    fanout_id = str(contract["fanout_id"])
    owner_state = root / "claude-state"
    owner_state.mkdir()
    hook_marker = root / "host-reference-hook-executed"
    fsmonitor_marker = root / "host-fsmonitor-executed"
    hooks = root / "hostile-hooks"
    hooks.mkdir()
    reference_hook = hooks / "reference-transaction"
    reference_hook.write_text(
        "#!/bin/sh\n"
        f'test ! -f "{owner_state / "enable-hook"}" || printf escaped > "{hook_marker}"\n',
        encoding="utf-8",
    )
    reference_hook.chmod(0o755)
    git(repository, "config", "core.hooksPath", str(hooks))
    fsmonitor = root / "hostile-fsmonitor"
    fsmonitor.write_text(
        f'#!/bin/sh\nprintf escaped > "{fsmonitor_marker}"\nexit 0\n',
        encoding="utf-8",
    )
    fsmonitor.chmod(0o755)
    hostile_global = root / "hostile.gitconfig"
    hostile_global.write_text(
        f"[core]\n\tfsmonitor = {fsmonitor}\n\thooksPath = {hooks}\n",
        encoding="utf-8",
    )
    unrelated = root / "unrelated"
    unrelated.mkdir()
    git(unrelated, "init", "-q")
    worker = root / "worker.py"
    worker.write_text(
        textwrap.dedent(
            f"""
            import json
            import os
            from pathlib import Path
            import re
            import subprocess
            import sys

            state = Path(os.environ["CLAUDE_CONFIG_DIR"])
            attempt = state / "attempt"
            if not attempt.exists():
                attempt.write_text("1", encoding="utf-8")
                print(json.dumps({{"type": "result", "result": "Error: socket hang up"}}))
                raise SystemExit(1)
            if os.environ["GIT_DIR"] == {json.dumps(str(unrelated / ".git"))}:
                raise SystemExit(71)
            if os.environ.get("GIT_INDEX_FILE") == {json.dumps(str(root / "ambient-index"))}:
                raise SystemExit(72)
            if os.environ.get("GIT_CONFIG_GLOBAL") != os.devnull:
                raise SystemExit(73)
            git_file = Path(".git").read_text(encoding="utf-8").strip()
            shared_git = Path(git_file.removeprefix("gitdir: "))
            try:
                (shared_git / "child-escape").write_text("escaped", encoding="utf-8")
            except OSError:
                pass
            else:
                raise SystemExit(74)
            Path("change.txt").write_text("committed through confinement\\n", encoding="utf-8")
            subprocess.run(("/usr/bin/git", "add", "change.txt"), check=True)
            subprocess.run(
                (
                    "/usr/bin/git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.test",
                    "commit",
                    "-qm",
                    "unit change",
                ),
                check=True,
            )
            subprocess.run(("/usr/bin/git", "config", "core.fsmonitor", {json.dumps(str(fsmonitor))}), check=True)
            (state / "enable-hook").write_text("enabled", encoding="utf-8")
            prompt = " ".join(sys.argv[1:])
            match = re.search(r"JSON sidecar to exactly (.+)\\.", prompt)
            if match is None:
                raise SystemExit(75)
            head = subprocess.run(
                ("/usr/bin/git", "rev-parse", "HEAD"),
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            Path(match[1]).write_text(
                json.dumps(
                    {{
                        "schema_version": "fanout_unit_result/v1",
                        "unit_id": "core",
                        "run_id": {json.dumps(run_ref)},
                        "fanout_id": {json.dumps(fanout_id)},
                        "base_sha": {json.dumps(base_sha)},
                        "head_sha": head,
                        "process_status": "process_succeeded",
                        "changed_paths": ["change.txt"],
                        "checks": [],
                        "findings": [],
                    }}
                ),
                encoding="utf-8",
            )
            print(json.dumps({{"type": "result", "subtype": "success", "session_id": "session-e2e"}}))
            """
        ).lstrip(),
        encoding="utf-8",
    )
    compiler = shutil.which("cc")
    if compiler is None:
        raise ProductionConfinementUnavailable(
            "the production confinement test requires a C compiler"
        )
    binary_directory = root / "bin"
    binary_directory.mkdir()
    target = binary_directory / "mise"
    source = root / "mise.c"
    source.write_text(
        textwrap.dedent(
            f"""
            #include <libgen.h>
            #include <stdio.h>
            #include <string.h>
            #include <unistd.h>

            int main(int argc, char **argv) {{
                if (strcmp(basename(argv[0]), "claude") != 0) return 86;
                if (argc == 2 && strcmp(argv[1], "--version") == 0) {{
                    puts("1.2.3 (Claude Code)");
                    return 0;
                }}
                if (argc == 2 && strcmp(argv[1], "--help") == 0) {{
                    puts("--output-format stream-json --verbose --resume");
                    return 0;
                }}
                char *next[argc + 2];
                next[0] = {json.dumps(sys.executable)};
                next[1] = {json.dumps(str(worker))};
                for (int index = 1; index < argc; index++) next[index + 1] = argv[index];
                next[argc + 1] = NULL;
                execv(next[0], next);
                return 87;
            }}
            """
        ).lstrip(),
        encoding="utf-8",
    )
    subprocess.run((compiler, str(source), "-o", str(target)), check=True)
    (binary_directory / "claude").symlink_to(target)
    environment = {
        **os.environ,
        "PATH": os.pathsep.join((str(binary_directory), "/usr/bin", "/bin")),
        "CLAUDE_CONFIG_DIR": str(owner_state),
        "GIT_DIR": str(unrelated / ".git"),
        "GIT_WORK_TREE": str(unrelated),
        "GIT_INDEX_FILE": str(root / "ambient-index"),
        "GIT_CONFIG_GLOBAL": str(hostile_global),
        "GIT_CONFIG_SYSTEM": str(hostile_global),
        "GIT_OBJECT_DIRECTORY": str(unrelated / ".git" / "objects"),
    }
    return ProductionConfinementFixture(
        paths,
        repository,
        contract,
        base_sha,
        environment,
        owner_state,
        hook_marker,
        fsmonitor_marker,
    )
