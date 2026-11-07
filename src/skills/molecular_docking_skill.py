"""Original optional standalone Vina workflow; discovery never runs the toolkit."""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json

from .catalog_types import ExpertQuestion, ProcedureCheck, ProcedureBail, ProcedureStep, SkillDefinition, SkillExample

_INPUTS = ("prepared receptor and ligand PDBQT paths", "binding box and preparation provenance", "approved local resource budget")
_OUTPUTS = ("molecular_docking_preflight/v1", "molecular_docking_run/v1 and real pose/score files")

DEFINITION = SkillDefinition(
    name="molecular-docking",
    description="Prepared PDBQT inputs: run bounded standalone Vina docking with real poses, scores and replay provenance; never infer efficacy or safety.",
    triggers=("molecular-docking", "rigid-receptor docking", "PDBQT docking", "ligand docking poses", "AutoDock Vina"),
    use_when="Use when prepared receptor/ligand files and an explicit binding box need a bounded rigid-receptor computational run.",
    category="analysis", phase="docking-validation", hermes_role="operator",
    delegation_boundary="retained-catalog-intent", progressive_disclosure=True,
    required_inputs=_INPUTS, expected_outputs=_OUTPUTS,
    expert_questions=(
        ExpertQuestion(_INPUTS[0], "Which prepared, rights-cleared single-ligand and rigid-receptor PDBQT files are authorized?", "사용이 허가된, 준비를 마친 단일 리간드와 강체 수용체 PDBQT 파일은 무엇인가요?"),
        ExpertQuestion(_INPUTS[1], "What are the center and box dimensions in angstrom, and which protonation, charge, tautomer and preparation choices produced these files?", "박스 중심과 크기(옹스트롬)는 얼마이고, 어떤 양성자화, 전하, 호변이성질체, 준비 방식으로 이 파일들을 만들었나요?"),
        ExpertQuestion(_INPUTS[2], "Which isolated optional backend, finite host deadline and new evidence directory are approved?", "승인된 격리 선택 백엔드, 유한한 호스트 제한 시간, 새 증거 폴더는 무엇인가요?"),
    ),
    why_this_exists="Input validation and tutorial numbers are not measured docking. Require a real engine search and digest-bound poses, finite energies and replay settings.",
    opening_steps=(
        "Read `toolkit/README.md` and `references/execution-and-qa.md`. Use the explicitly invoked standalone Vina Python helper, not an invented ToolUniverse tool or hidden core execution service.",
        "Recover prepared file paths, source/license and preparation receipts, angstrom binding box, seed, CPU, new output directory and host deadline. Never guess a site, silently prepare a molecule or install dependencies on skill load. If the person has a SMILES or a PDB id rather than PDBQT, stop and list the preparation steps they must approve (protonation state, charges, tautomer, receptor cleanup, box) with a named converter such as Meeko or ADFR; do not convert silently.",
        "Use `--validate-only` for dependency-free prerequisites, or explicitly invoke actual docking in an approved environment with a host-enforced timeout and stdout/stderr capture. Missing dependencies must refuse, not produce guessed findings.",
    ),
    handoff_policy="Keep framing and evidence assessment with the host. Report actual docking only after reading genuine pose/score/version/log/hash/replay evidence. Optional dependency or native failures remain BLOCKED for that run; preflight, source inspection and a successful install alone are not execution. No ToolUniverse execution is claimed.",
    procedure_checks=(
        ProcedureCheck("docking_input_check", ("file_hashes", "format_validation", "source_license", "preparation_choices", "binding_box"), "Require safe new output paths, valid finite PDBQT atoms, rigid receptor/single ligand, rights and preparation provenance; HOLD absent binding center or preparation facts."),
        ProcedureCheck("docking_budget_check", ("cpu", "seed", "exhaustiveness", "n_poses", "host_deadline"), "Require CPU 1-2, positive fixed seed, exhaustiveness 1-4, poses 1-5, box dimensions 1-24 angstrom and a host-enforced deadline at most 180 seconds; the helper records but cannot interrupt native code itself."),
        ProcedureCheck("docking_execution_check", ("backend_identity", "pose_score_readback", "hashes", "replay", "claim_boundary"), "Require actual dock(), matching MODEL/ENDMDL and VINA RESULT records, finite energies in kcal/mol, engine version, stdout/stderr, exit/deadline evidence and digest-bound replay. A mock, score-only or optimize-only call cannot pass."),
    ),
    procedure_steps=(
        ProcedureStep("docking_scope", "analysis", _INPUTS, (_OUTPUTS[0],), ("docking_input_check", "docking_budget_check"), "Bind rights-cleared prepared files, protonation/tautomer/charges, receptor assumptions, site and resource budget. Run optional --validate-only to read back input digests, never as completed docking."),
        ProcedureStep("docking_execute", "production", _INPUTS, (_OUTPUTS[1],), ("docking_input_check", "docking_budget_check"), "Explicitly run toolkit/scripts/dock.py in the chosen isolated Vina environment with a new output directory, captured logs and a real finite host timeout. Never auto-install or silently substitute a provider.",
            on_fail=ProcedureBail(
                still_stands=('molecular_docking_preflight/v1',),
                downgrade_to='not_observed',
                handback='Return molecular_docking_preflight/v1 with captured stdout, stderr, exit or deadline evidence and any partial pose/score files for backend review before a retry in a new output directory.',
            ),
        ),
        ProcedureStep("docking_verify", "validation", _INPUTS, (_OUTPUTS[1],), ("docking_execution_check",), "Read poses.pdbqt, scores.json and manifest.json; reconcile saved pose energies and atom records with actual inputs and all hashes. Replay with a new output directory when needed; qualify reproducibility by version/platform.",
            on_fail=ProcedureBail(
                still_stands=('molecular_docking_preflight/v1',),
                downgrade_to='tentative',
                handback='Return poses.pdbqt, scores.json and manifest.json with failed pose, energy, atom-record, hash or replay checks and engine version/platform limits; keep the docking run unverified.',
            ),
        ),
    ),
    artifact_expectations=("Keep raw inputs, stdout/stderr and pose/score files in the approved evidence directory, outside metadata-only OMH state. Preflight/run/score JSON schemas are standalone file contracts, not new registered operations artifacts.",),
    safety_rules=(
        "Never infer efficacy, safety, affinity certainty, target validation, dosing or treatment advice. PDBQT syntax validation is not chemical validity or a preparation review.",
        "No hidden execution, network, credentials, global install or paid compute. Dependencies are optional and task-isolated; discovery, routing and skill installation never execute the helper.",
        "ToolUniverse registrations were inspected, not invoked. This toolkit uses standalone AutoDock Vina Python only; do not invent a ToolUniverse adapter or tool name.",
        "Exhaustiveness is capped at 4 here (Vina's default is 8): treat energies as one under-sampled run, never as a ranking or a comparison across ligands. Before reporting a site, redock the co-crystal ligand when one exists and report its pose RMSD to the crystal pose; with none, say the site is unvalidated.",
    ),
    quality_bar=(
        "Reject symlinks, existing output directories, unsupported formats, non-finite inputs and resource-cap violations before output writes. Preserve existing user files and keep failed-run partial files distinct from success manifests.",
        "Retain actual setup and runtime errors. Never fill a missing backend gate with tutorial numbers, fake poses, optimizer output or a success stub.",
    ),
    do_not_use_when=(
        "A general literature question belongs to `research`; one supplied paper belongs to `paper-learning`.",
        "A boat reservation, molecular mechanism explanation without computation, drug recommendation or clinical decision is outside this scope.",
    ),
    good_example=SkillExample("Run these prepared PDBQT inputs in this declared box with one CPU and fixed seed, preserving actual poses and replay settings.", "Validate inputs, run the explicit optional Vina helper under a host deadline, then read back poses/scores/hashes and state limitations.", "Actual engine output is distinguishable from preflight and source inspection."),
    bad_example=SkillExample("These scores prove the compound is safe and effective; recommend a dose.", "Reject the unsupported inference and do not produce clinical advice.", "Computational score evidence cannot establish those claims."),
    final_checklist=(
        "Input/format/resource checks and exact input hashes are observed; source rights and preparation assumptions remain explicit.",
        "Actual poses, finite matching energies, backend version/settings, host logs/exit/deadline and replay manifest are read back, or the run is reported BLOCKED without invented results.",
    ),
    recovery_notes=("Preserve failed setup receipts. PyPI ships Vina 1.2.7 wheels only for x86_64 Linux, so macOS arm64 needs a source build with Boost and SWIG, and its setup.py checks CONDA_DEFAULT_ENV, not only CONDA_PREFIX. If the build fails, return the failure log and do not retry blindly; the observed 1IEP smoke is one platform, not a promise for others.", "If a native run fails or times out, retain its logs and partial files without a success claim; review the backend failure before retrying in a new output directory."),
    situations=("prepared receptor files need a measured pose search", "a search box needs a bounded run budget", "a docking result has no genuine pose file", "tutorial numbers are being mistaken for measured scores", "a saved pose energy differs from the engine output"),
)


def molecular_docking_definition():
    return DEFINITION


REFERENCE_TEXT = {"execution-and-qa": """# Explicit standalone Vina execution and QA

Read `toolkit/README.md` before invoking `toolkit/scripts/dock.py`. Nothing
executes or installs on discovery. Python 3.11+ suffices for --help/preflight;
actual docking requires the optional Vina package in the chosen environment.

## Backend identity and source provenance

ToolUniverse was inspected at `53b4f8eb48d304f947bab85182b88d7c2a5c6794`:
`src/tooluniverse/tools/NvidiaNIM_diffdock.py` forwards NVIDIA NIM requests;
`ClusPro_submit_peptide_docking.py` submits peptide jobs, not completed
small-molecule poses; `src/tooluniverse/data/remote_tools/boltz_tools.json`
registers `boltz2_docking`, whose remote README requires Linux/CUDA. None was
invoked. No ToolUniverse Vina tool is invented. The backend here is explicitly
standalone AutoDock Vina Python, not ToolUniverse integration.

Official Vina tutorial/API/Apache-2.0 license and 1IEP inputs were inspected at
`bb64e5e26b520569a86360d69248069b5e665b3f`; input bytes remain in external
evidence, not bundled. The tutorial box is center 15.190 53.903 16.917, sides
20 20 20 angstrom; never reuse that site for another target without justification.
The closed provenance manifest records reviewed source revisions/hashes.

## Explicit operator invocation

Use installed skill-relative paths. The host must enforce a real finite timeout
for the whole command and capture stdout/stderr, argv, UTC times and exit status:

```sh
python toolkit/scripts/dock.py --receptor RECEPTOR.pdbqt --ligand LIGAND.pdbqt \\
  --center 15.190 53.903 16.917 --box-size 20 20 20 \\
  --cpu 1 --seed 20261022 --exhaustiveness 1 --n-poses 1 \\
  --host-timeout-seconds 180 --output-dir NEW_DIRECTORY
```

--host-timeout-seconds records the outer deadline contract; it cannot safely
interrupt native code itself. Add --validate-only for dependency-free preflight,
which writes preflight.json and execution_status not_observed, never poses/scores.
Ordinary execution lazily imports Vina, calls set_receptor/set_ligand_from_file,
compute_vina_maps, actual dock(), energies() and nonoverwriting write_poses().
Missing/unusable optional dependencies exit 3 without creating the output
directory. Invalid inputs or execution/readback failures exit 2; partial files
from a failed native run are not success and no success manifest is written.

## Validation and evidence gates

Require ASCII fixed-column PDBQT with finite coordinates/charge and supported
atom types, one ligand with balanced ROOT/ENDROOT, BRANCH/ENDBRANCH and final
TORSDOF, and a rigid receptor. Reject PDB/SDF, multi-model and flexible-receptor
inputs, duplicate serials and unsafe/existing output paths. Caps: 4 MiB per
input, 30000 receptor atoms, 128 ligand atoms, 16 branches/TORSDOF; CPU 1-2,
positive seed up to 2147483647, exhaustiveness 1-4, poses 1-5, box sides 1-24
angstrom, host deadline 1-180 seconds. Never silently convert or repair.
Protonation, charge assignment, tautomer, stereochemistry, missing atoms,
cofactors, preparation validity and the binding site still require domain review.

Read poses.pdbqt, scores.json and manifest.json. Every sequential MODEL must
close before the next begins, contain exactly one valid VINA RESULT record and
nonempty fixed-column atoms with finite coordinates. Each model must retain
the ligand's unique serial-keyed atom identities/count (record kind, name,
residue/chain/insertion identity, charge and type), without missing/extra atoms.
Require finite five-column Vina energies in kcal/mol, matching each saved total
to its engine row in model order within an absolute 0.001, with finite
nonnegative RMSDs. The helper parses and reconciles all models before writing
scores.json or a success manifest; corrupt poses remain failed-run diagnostics.
Input/output/helper SHA-256 hashes bind bytes, not scientific validity. Require
engine version/platform, seed, all settings and replay argv. Preserve host raw
logs and the deadline/exit receipt alongside outputs. For replay, change only
--output-dir to a new path and rerun under the host deadline. Reconcile outputs
rather than promising universal byte identity across versions/platforms.
The manifest records fixed grid spacing, energy range, RMSD, refinement and
heuristic max_evals defaults plus engine.info(). It does not hash itself;
external host evidence should hash the manifest and logs.

## Observed bounded smoke, not biological validation

The first wheel-only setup failed on macOS arm64. The existing Boost 1.85/SWIG
native environment initially failed to locate Boost because upstream in_conda()
checks CONDA_DEFAULT_ENV, which was absent. Actual PyPI 1.2.7 source matched the
pinned setup audit. One authorized correction supplied CONDA_DEFAULT_ENV,
CONDA_PREFIX and PATH; the same native build succeeded. Earlier errors remain
preserved; no Docker, global package, paid service or third installation strategy
was used. Python 3.12.15, Vina 1.2.7 and NumPy 2.5.4 ran the real 1IEP helper
with CPU 1, seed 20261022, exhaustiveness 1 and one pose under a 180-second host
cap. Saved 41-atom pose total -10.871 kcal/mol matched engine energies. A second
same-host seeded run produced equal pose/score bytes; this is only that observed
version/platform. It is not ToolUniverse execution, chemical preparation review,
affinity certainty, efficacy, safety, clinical utility or a dosing conclusion.
"""}


def molecular_docking_reference_templates():
    from .render import SkillReferenceTemplate, loadable_skill_mentions
    return [SkillReferenceTemplate(DEFINITION.name, f"references/{key}.md", loadable_skill_mentions(text))
            for key, text in REFERENCE_TEXT.items()]


TOOLKIT_RESOURCES = ("README.md", "NOTICE.md", "scripts/dock.py", "examples/settings.json", "upstream-manifest.json")


def _resource_texts():
    root = files("omh.skills").joinpath("molecular_docking_toolkit")
    texts = {}
    for relative in TOOLKIT_RESOURCES:
        data = root.joinpath(relative).read_bytes()
        if len(data) > 1_048_576 or b"\x00" in data:
            raise ValueError("docking toolkit resource is not bounded UTF-8 text")
        texts[relative] = data.decode("utf-8")
    return texts


def _provenance(texts):
    return {
        "schema": "molecular_docking_toolkit_provenance/v1", "runtime_status": "observed_native_smoke",
        "backend_candidate": "standalone-autodock-vina-python", "tooluniverse_execution": False,
        "repository": "oh-my-hermes", "revision": "original-uncommitted-producer; per-file hashes authoritative",
        "license": "MIT", "copyright": "Copyright (c) 2026 oh-my-hermes contributors",
        "self_hash": "excluded; outer native/portable inventories hash this file",
        "native_smoke": {"vina": "1.2.7", "python": "3.12.15", "numpy": "2.5.4", "platform": "macOS-26.5.1-arm64-arm-64bit", "seed": 20261022, "cpu": 1, "exhaustiveness": 1, "n_poses": 1, "host_deadline_seconds": 180, "pose_sha256": "121d02cca19d3d5ae9073fed722ae25524991abeab5887631f901b5249e8923d", "same_host_seeded_replay": "observed equal pose and score bytes; not a cross-platform guarantee"},
        "files": {relative: {
            "source_path": "src/skills/molecular_docking_toolkit/" + relative,
            "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "local_path": relative, "local_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "classification": "original_omh", "upstream": [], "license": "MIT",
            "copyright": "Copyright (c) 2026 oh-my-hermes contributors",
            "modification_notice": "Original standalone direct Vina helper and guidance; no upstream code, molecular inputs or result files copied",
        } for relative, text in texts.items() if relative != "upstream-manifest.json"},
        "inspected_sources": [
            {"repository": "https://github.com/mims-harvard/ToolUniverse", "revision": "53b4f8eb48d304f947bab85182b88d7c2a5c6794", "path": "src/tooluniverse/tools/NvidiaNIM_diffdock.py", "sha256": "059e79a4aa1336f0570ffba2f1f6eaa3f43ec2fdc5e2db686c74d105996f83aa", "license": "Apache-2.0", "classification": "inspected_not_copied"},
            {"repository": "https://github.com/mims-harvard/ToolUniverse", "revision": "53b4f8eb48d304f947bab85182b88d7c2a5c6794", "path": "src/tooluniverse/tools/ClusPro_submit_peptide_docking.py", "sha256": "fae6f51dbaa1e540f14e85461c24e1bc1015c2b2a7e4682785d62ae5e9a381be", "license": "Apache-2.0", "classification": "inspected_not_copied"},
            {"repository": "https://github.com/mims-harvard/ToolUniverse", "revision": "53b4f8eb48d304f947bab85182b88d7c2a5c6794", "path": "src/tooluniverse/data/remote_tools/boltz_tools.json", "sha256": "6c8e652b611d6816c4873a804a6da4a93f2b6291e95c7e5afa28ad073389b74b", "license": "Apache-2.0", "classification": "inspected_not_copied"},
            {"repository": "https://github.com/ccsb-scripps/AutoDock-Vina", "revision": "bb64e5e26b520569a86360d69248069b5e665b3f", "path": "docs/source/docking_python.rst", "sha256": "b07bd00ae051bf2d54cb55725c760012006176fea0d9ca5289aea4a4fffa62fd", "license": "Apache-2.0", "classification": "inspected_not_copied"},
            {"repository": "https://github.com/ccsb-scripps/AutoDock-Vina", "revision": "bb64e5e26b520569a86360d69248069b5e665b3f", "path": "example/python_scripting/1iep_receptor.pdbqt", "sha256": "761469710e3915b89b274483076dfe49754be7956661bc42f4cc36a182399d59", "license": "Apache-2.0", "classification": "external_smoke_input_not_bundled"},
            {"repository": "https://github.com/ccsb-scripps/AutoDock-Vina", "revision": "bb64e5e26b520569a86360d69248069b5e665b3f", "path": "example/python_scripting/1iep_ligand.pdbqt", "sha256": "37a20e58e77072c6b3ff07f285a345e647dd4e564af316a06e49518b15b7aa61", "license": "Apache-2.0", "classification": "external_smoke_input_not_bundled"},
            {"repository": "PyPI/vina", "revision": "1.2.7", "path": "vina-1.2.7.tar.gz", "sha256": "79e5288d10207b85f20adac3dd6f4708eac761c2d8070fbad76ff997cf48e4f9", "setup_py_sha256": "bd9bc6a60c3ff03ad5fd395941898c76c18fdce3f0258a37aa65b4ffe57a8d41", "license": "Apache-2.0", "classification": "external_native_build_source_not_bundled"},
        ],
    }


def molecular_docking_provenance_manifest():
    return _provenance(_resource_texts())


def molecular_docking_support_templates():
    from .support_files import SkillSupportTemplate, validate_support_templates
    texts = _resource_texts()
    if json.loads(texts["upstream-manifest.json"]) != _provenance(texts):
        raise ValueError("docking closed toolkit provenance mismatch; review canonical resources")
    return validate_support_templates([
        SkillSupportTemplate(DEFINITION.name, "toolkit/" + relative, texts[relative])
        for relative in TOOLKIT_RESOURCES
    ])
