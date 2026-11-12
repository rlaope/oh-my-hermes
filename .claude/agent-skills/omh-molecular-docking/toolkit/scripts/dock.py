#!/usr/bin/env python3
"""Explicit standalone AutoDock Vina docking with bounded validated local inputs.

Native imports are lazy. The host must enforce the declared outer deadline;
--validate-only performs NO docking execution and writes prerequisites only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys

MAX_BYTES = 4 * 1024 * 1024
MAX_ATOMS = {"receptor": 30000, "ligand": 128}
ATOM_TYPES = frozenset("C A N NA O OA S SA P F Cl Br I H HD Mg Mn Zn Ca Fe Cu Ni Co Cd Si B".split())


def system_alias(candidate):
    """Trust only macOS's own /etc, /tmp and /var links into /private.

    The default temp dir lives under /var. Only root can create a top-level
    entry, so the exact name and the exact link text are both required.
    """
    if sys.platform != "darwin" or candidate.parent != Path("/") or candidate.name not in ("etc", "tmp", "var"):
        return False
    try:
        return os.readlink(candidate) in ("private/" + candidate.name, "/private/" + candidate.name)
    except OSError:
        return False


def checked_path(value):
    """Reject symlink components before resolving an explicit local path."""
    path = Path(value).absolute()
    for candidate in (path, *path.parents):
        if candidate.is_symlink() and not system_alias(candidate):
            raise ValueError("symlink paths are not accepted")
    return path


def same_file(first, second):
    """True when two checked paths name one file, however spelled (`..`, hard links)."""
    try:
        return os.path.samefile(first, second)
    except OSError:
        # Either is missing; compare where both would resolve.
        return os.path.realpath(first) == os.path.realpath(second)


def read_pdbqt(value, role):
    """Validate a deliberately narrow single-ligand, rigid-receptor PDBQT subset."""
    path = checked_path(value)
    if path.suffix.lower() != ".pdbqt" or not path.is_file():
        raise ValueError(f"{role} requires an existing regular .pdbqt file")
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError(f"{role} exceeds the {MAX_BYTES}-byte cap or is empty")
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError(f"{role} exceeds the byte cap")
    text = data.decode("ascii")
    atoms = pdbqt_atoms(text, role)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "atoms": len(atoms)}


def pdbqt_atoms(text, role):
    """Validate one structure and retain serial-keyed immutable atom identities."""
    if "\x00" in text:
        raise ValueError(f"{role} contains NUL")
    atoms = {}
    root_open = False
    root_seen = False
    root_closed = False
    torsdof = None
    branches = []
    branch_pairs = []
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        record = fields[0]
        if torsdof is not None and record not in ("REMARK", "TER", "END"):
            raise ValueError("ligand TORSDOF must be the final structural record")
        if record in ("ATOM", "HETATM"):
            if role == "ligand" and (not root_seen or (root_closed and not branches)):
                raise ValueError("ligand atom must be in ROOT or BRANCH")
            if len(line) < 78 or line[:6] not in ("ATOM  ", "HETATM"):
                raise ValueError(f"{role} atom requires fixed-column PDBQT coordinates/charge/type")
            serial = int(line[6:11])
            xyz = [float(line[start:start + 8]) for start in (30, 38, 46)]
            charge = float(line[70:76])
            atom_type = line[77:].strip()
            if not all(math.isfinite(number) and abs(number) <= 100000 for number in xyz):
                raise ValueError(f"{role} atom coordinates must be finite and bounded")
            if not math.isfinite(charge) or abs(charge) > 10 or atom_type not in ATOM_TYPES:
                raise ValueError(f"{role} invalid PDBQT charge or unsupported atom type")
            if serial <= 0 or serial in atoms:
                raise ValueError(f"{role} atom serials must be positive and unique")
            # Preserve name, alternate location, residue/chain/insertion identity,
            # record kind, partial charge and AutoDock type; coordinates may move.
            atoms[serial] = (record, line[12:30], charge, atom_type)
            if len(atoms) > MAX_ATOMS[role]:
                raise ValueError(f"{role} exceeds the {MAX_ATOMS[role]}-atom cap")
        elif record in ("REMARK", "TER", "END"):
            continue
        elif role == "ligand" and record == "ROOT":
            if fields != ["ROOT"] or root_seen:
                raise ValueError("ligand requires exactly one ROOT")
            root_open = root_seen = True
        elif role == "ligand" and record == "ENDROOT":
            if fields != ["ENDROOT"] or not root_open or root_closed or not atoms:
                raise ValueError("unbalanced ligand ROOT")
            root_open = False
            root_closed = True
        elif role == "ligand" and record in ("BRANCH", "ENDBRANCH"):
            if len(fields) != 3 or not root_closed or torsdof is not None:
                raise ValueError("invalid ligand branch record")
            pair = tuple(int(field) for field in fields[1:])
            if pair[0] <= 0 or pair[1] <= 0 or pair[0] == pair[1]:
                raise ValueError("invalid ligand branch atom identifiers")
            if record == "BRANCH":
                if pair[0] not in atoms or len(branch_pairs) >= 16:
                    raise ValueError("ligand branch source missing or 16-branch cap exceeded")
                branches.append(pair)
                branch_pairs.append(pair)
            elif not branches or branches.pop() != pair or pair[1] not in atoms:
                raise ValueError("unbalanced ligand BRANCH")
        elif role == "ligand" and record == "TORSDOF":
            if len(fields) != 2 or torsdof is not None or not root_closed or branches:
                raise ValueError("invalid ligand TORSDOF placement")
            torsdof = int(fields[1])
            if not 0 <= torsdof <= 16:
                raise ValueError("ligand TORSDOF must be between 0 and 16")
        else:
            raise ValueError(f"unsupported {role} PDBQT record: {record}")
    if not atoms:
        raise ValueError(f"{role} requires atom records")
    if role == "ligand" and (not root_closed or root_open or branches or torsdof is None):
        raise ValueError("ligand requires balanced ROOT/BRANCH and TORSDOF")
    return atoms


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--receptor", required=True)
    result.add_argument("--ligand", required=True)
    result.add_argument("--center", required=True, type=float, nargs=3, metavar=("X", "Y", "Z"))
    result.add_argument("--box-size", required=True, type=float, nargs=3, metavar=("X", "Y", "Z"))
    result.add_argument("--cpu", type=int, default=1)
    result.add_argument("--seed", type=int, default=20261022)
    result.add_argument("--exhaustiveness", type=int, default=1)
    result.add_argument("--n-poses", type=int, default=1)
    result.add_argument("--host-timeout-seconds", type=int, default=180,
                        help="Required outer-tool deadline contract, NOT an in-process native interrupt")
    result.add_argument("--output-dir", required=True)
    result.add_argument("--validate-only", action="store_true",
                        help="Write only prerequisite evidence; never run docking or produce scores/poses")
    return result


def validate(args):
    for label, value, low, high in (
        ("cpu", args.cpu, 1, 2), ("seed", args.seed, 1, 2147483647),
        ("exhaustiveness", args.exhaustiveness, 1, 4), ("n-poses", args.n_poses, 1, 5),
        ("host-timeout-seconds", args.host_timeout_seconds, 1, 180),
    ):
        if not low <= value <= high:
            raise ValueError(f"{label} must be between {low} and {high}")
    if not all(math.isfinite(v) and abs(v) <= 100000 for v in args.center):
        raise ValueError("center coordinates must be finite and bounded")
    if not all(math.isfinite(v) and 1 <= v <= 24 for v in args.box_size):
        raise ValueError("box dimensions must be finite, between 1 and 24 angstrom")
    if math.prod(args.box_size) > 13824:
        raise ValueError("box volume exceeds 13824 cubic angstrom")
    # Before parsing: no file passes both role checks, so a repeated input would fail as a role error instead.
    if same_file(checked_path(args.receptor), checked_path(args.ligand)):
        raise ValueError("receptor and ligand must be different files")
    receptor = read_pdbqt(args.receptor, "receptor")
    ligand = read_pdbqt(args.ligand, "ligand")
    output = checked_path(args.output_dir)
    if output.exists() or not output.parent.is_dir():
        raise ValueError("output directory must be new with an existing directory parent")
    return receptor, ligand, output


def write_json(path, payload):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def read_pose_scores(path, energies, expected_atoms):
    """Validate each saved model before exposing any score or success receipt."""
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("saved poses exceed the byte cap or are empty")
    text = path.read_text(encoding="ascii")
    if "\x00" in text:
        raise ValueError("saved poses contain NUL")
    scores = []
    model_lines = None
    score = None
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        record = fields[0]
        if record == "MODEL":
            if model_lines is not None or fields != ["MODEL", str(len(scores) + 1)]:
                raise ValueError("saved poses require nonnested sequential MODEL records")
            if len(scores) >= len(energies):
                raise ValueError("saved pose model count exceeds engine energies")
            model_lines = []
            score = None
        elif record == "ENDMDL":
            if fields != ["ENDMDL"] or model_lines is None:
                raise ValueError("saved poses have unbalanced ENDMDL records")
            if score is None:
                raise ValueError("saved pose requires exactly one VINA RESULT record per model")
            atoms = pdbqt_atoms("\n".join(model_lines), "ligand")
            if atoms != expected_atoms:
                raise ValueError("saved pose atom identities/count do not match the ligand")
            if not math.isclose(score, energies[len(scores)][0], rel_tol=0.0, abs_tol=0.001):
                raise ValueError("saved pose score does not match finite engine energies")
            scores.append(score)
            model_lines = None
        else:
            if model_lines is None:
                raise ValueError("saved pose record outside MODEL/ENDMDL")
            if fields[:2] == ["REMARK", "VINA"]:
                if score is not None or len(fields) != 6 or fields[2] != "RESULT:":
                    raise ValueError("saved pose has duplicate or malformed VINA RESULT record")
                values = [float(field) for field in fields[3:]]
                if not all(math.isfinite(value) for value in values) or any(value < 0 for value in values[1:]):
                    raise ValueError("saved pose VINA RESULT requires finite total and nonnegative RMSDs")
                score = values[0]
            model_lines.append(line)
    if model_lines is not None or len(scores) != len(energies):
        raise ValueError("saved poses have unclosed models or do not match engine energy count")
    return scores


def run_docking(backend, args, receptor, ligand, output):
    """Call the real global search, not score/optimize; reconcile saved poses."""
    expected_atoms = pdbqt_atoms(Path(ligand["path"]).read_text(encoding="ascii"), "ligand")
    engine = backend.Vina(sf_name="vina", cpu=args.cpu, seed=args.seed,
                          no_refine=False, verbosity=1)
    engine.set_receptor(receptor["path"])
    engine.set_ligand_from_file(ligand["path"])
    engine.compute_vina_maps(center=args.center, box_size=args.box_size,
                             spacing=0.375, force_even_voxels=False)
    engine.dock(exhaustiveness=args.exhaustiveness, n_poses=args.n_poses,
                min_rmsd=1.0, max_evals=0)
    energies = engine.energies(n_poses=args.n_poses, energy_range=3.0).tolist()
    if (not energies or len(energies) > args.n_poses
            or any(len(row) != 5 or not all(math.isfinite(v) for v in row) for row in energies)):
        raise ValueError("engine returned missing, malformed or non-finite energies")
    pose_path = output / "poses.pdbqt"
    engine.write_poses(str(pose_path), n_poses=args.n_poses, energy_range=3.0, overwrite=False)
    pose_scores = read_pose_scores(pose_path, energies, expected_atoms)
    # Do not publish a success receipt if inputs changed while native code read them.
    for record in (receptor, ligand):
        if hashlib.sha256(Path(record["path"]).read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("input changed during docking")
    write_json(output / "scores.json", {
        "schema": "molecular_docking_scores/v1", "scoring_function": "vina",
        "units": "kcal/mol", "columns": ["total", "inter", "intra", "torsions", "intra_best_pose"],
        "energies": energies, "pose_totals": pose_scores,
    })
    return engine.info()


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        receptor, ligand, output = validate(args)
        backend = None
        if not args.validate_only:
            try:
                import vina as backend
            except (ImportError, OSError) as error:
                print(f"Missing or unusable optional Vina dependency: {error}. "
                      "Install it explicitly into an isolated environment; nothing was installed or run.", file=sys.stderr)
                return 3
        settings = {
            "center_angstrom": args.center, "box_size_angstrom": args.box_size,
            "cpu": args.cpu, "seed": args.seed, "exhaustiveness": args.exhaustiveness,
            "n_poses": args.n_poses, "scoring_function": "vina",
            "grid_spacing_angstrom": 0.375, "force_even_voxels": False,
            "no_refine": False, "verbosity": 1, "min_rmsd_angstrom": 1.0,
            "max_evals": 0, "energy_range_kcal_mol": 3.0,
            "host_timeout_seconds": args.host_timeout_seconds,
            "timeout_enforcement": "outer host tool required; not enforced in native Python call",
        }
        # Canonical absolute paths make replay independent of the launch directory.
        replay = [sys.executable, str(Path(__file__).absolute()),
                  "--receptor", receptor["path"], "--ligand", ligand["path"],
                  "--center", *map(str, args.center), "--box-size", *map(str, args.box_size),
                  "--cpu", str(args.cpu), "--seed", str(args.seed),
                  "--exhaustiveness", str(args.exhaustiveness), "--n-poses", str(args.n_poses),
                  "--host-timeout-seconds", str(args.host_timeout_seconds),
                  "--output-dir", str(output)]
        if args.validate_only:
            replay.append("--validate-only")
        manifest = {
            "schema": "molecular_docking_preflight/v1" if args.validate_only else "molecular_docking_run/v1",
            "status": "prerequisites_validated" if args.validate_only else "docked",
            "execution_status": "not_observed" if args.validate_only else "observed",
            "backend": "standalone-autodock-vina-python", "tooluniverse_execution": False,
            "backend_version": None if args.validate_only else backend.__version__,
            "python_version": platform.python_version(), "platform": platform.platform(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "inputs": {"receptor": receptor, "ligand": ligand}, "settings": settings,
            "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "replay_argv": replay, "replay_requires_new_output_dir": True,
            "log_capture": "Host must capture stdout/stderr, exit status and enforce the outer deadline.",
            "claim_boundary": "Not affinity certainty, efficacy, safety or clinical evidence; preflight is not docking.",
        }
        output.mkdir(mode=0o700)
        if not args.validate_only:
            manifest["engine_settings"] = run_docking(backend, args, receptor, ligand, output)
            manifest["outputs"] = {}
            for name in ("poses.pdbqt", "scores.json"):
                data = (output / name).read_bytes()
                manifest["outputs"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(output / ("preflight.json" if args.validate_only else "manifest.json"), manifest)
        print("Prerequisites validated; no docking executed." if args.validate_only else "Docking complete; poses, scores and replay manifest written.")
        return 0
    except (ValueError, RuntimeError, OSError, UnicodeError) as error:
        print(f"Docking refused or failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
