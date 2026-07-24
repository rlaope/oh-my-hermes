from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from ..system.local_store import atomic_write_json
from ..system.local_store import ensure_dir
from ..system.paths import OmhPaths
from .fanout_contracts import FANOUT_ID_PATTERN

_FANOUT_ID_RE = re.compile(FANOUT_ID_PATTERN)


def write_fanout_contract(paths: OmhPaths, contract: dict[str, object]) -> dict[str, object]:
    fanout_id = _validated_fanout_id(contract.get("fanout_id"))
    contract_dir = _managed_fanout_dir(paths, fanout_id)
    contract_path = contract_dir / "fanout_contract.json"
    ensure_dir(paths.fanout_contracts_dir, private=True)
    ensure_dir(contract_dir, private=True)

    payload = deepcopy(contract)
    payload["artifacts"] = {"contract_path": str(contract_path), "privacy": "metadata_only"}
    atomic_write_json(contract_path, payload, private=True)
    return payload


def read_fanout_contract(paths: OmhPaths, fanout_id: str) -> dict[str, object]:
    import json

    contract_path = _managed_fanout_dir(paths, _validated_fanout_id(fanout_id)) / "fanout_contract.json"
    return json.loads(contract_path.read_text(encoding="utf-8"))


def _validated_fanout_id(value: object) -> str:
    fanout_id = str(value or "")
    if not _FANOUT_ID_RE.match(fanout_id):
        raise ValueError(f"invalid fanout_id: {fanout_id!r}")
    return fanout_id


def _managed_fanout_dir(paths: OmhPaths, fanout_id: str) -> Path:
    root = paths.fanout_contracts_dir
    if root.is_symlink():
        raise ValueError("fanout contract storage must not be a symlink")
    root_resolved = root.resolve(strict=False)
    if not root_resolved.is_relative_to(paths.omh_home.resolve(strict=False)):
        raise ValueError("fanout contract storage must resolve under OMH home")

    contract_dir = root / fanout_id
    if contract_dir.is_symlink():
        raise ValueError("fanout contract directory must not be a symlink")
    if contract_dir.resolve(strict=False).parent != root_resolved:
        raise ValueError("fanout_id must resolve under the fanout contracts directory")
    return contract_dir
