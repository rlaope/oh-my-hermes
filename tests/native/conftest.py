"""Opt-in real-host integration; OMH's standalone unittest suite has no host dependency."""
import sys
from pathlib import Path


def pytest_addoption(parser):
    parser.addoption("--native-source", help="Hermes source checkout (use its scripts/run_tests.sh)")


def pytest_configure(config):
    source = config.getoption("--native-source")
    if source:
        sys.path.insert(0, str(Path(source).resolve()))


def pytest_ignore_collect(collection_path, config):
    if collection_path.name == "test_profile_runtime.py" and not config.getoption("--native-source"):
        return True
    return None
