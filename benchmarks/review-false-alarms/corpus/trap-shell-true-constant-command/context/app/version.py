import subprocess

VERSION = "2.4.0"


def build_label() -> str:
    result = subprocess.run(
        "git describe --tags --always --dirty",
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    described = result.stdout.strip()
    return f"{VERSION}+{described}" if described else VERSION
