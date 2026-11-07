"""Dual-reviewer title/abstract screening for systematic, scoping and rapid reviews."""
from ..plugin_bundle.omh.native_tools import native_tool_presence_clause
from .catalog_types import SkillDefinition, SkillExample

_DELEGATE = native_tool_presence_clause("delegate_task", code=True)

DEFINITION = SkillDefinition(
    "systematic-review",
    "Literature screening against frozen criteria: two blind reviewers, a deterministic merge, open conflicts and agreement for systematic, scoping or rapid reviews.",
    ("systematic-review", "systematic review", "systematic literature review", "scoping review", "rapid review",
     "prisma screening", "title and abstract screening", "inclusion and exclusion criteria screening",
     "dual reviewer screening"),
    "Use when records for a systematic, scoping or rapid review must be screened against the person's inclusion and exclusion criteria by two independent reviewers, with every conflict and missing decision kept visible.",
    category="research", phase="literature-screening", hermes_role="retained-cognition",
    delegation_boundary="retained-catalog-intent",
    handoff_policy="Hermes owns the protocol conversation, the two reviewer children and the report. `omh research screening` only freezes, prepares and merges local files; it makes no model or network call and never decides a record itself.",
    required_inputs=("inclusion and exclusion criteria the person approved", "ordered exclusion codes (E1, E2, ...)",
                     "records JSONL with id, title and abstract", "new screening directory and an integer seed"),
    expected_outputs=("DIR/protocol.json (screening_protocol/v1, write-once)",
                      "DIR/tasks/A and DIR/tasks/B blind batches plus DIR/manifest.json (screening_manifest/v1)",
                      "screening_merge/v1 with counts, conflict and pending ids, agreement_stats/v1 and reviewer_independence"),
    why_this_exists="Two reviewers screening the same records only count as dual review when neither sees the other's answers and the merge is mechanical. This workflow freezes the criteria first, keeps each reviewer blind, and never turns a missing answer into an exclusion.",
    opening_steps=(
        "Records must be deduplicated across databases first (DOI or PMID, else normalized title plus year); record the identified, duplicate-removed and screened counts, because the PRISMA flow needs them and this workflow does not deduplicate.",
        "Agree the inclusion and exclusion criteria and the ordered exclusion codes with the person before any record is read; nothing is frozen until they say the criteria are final. To pilot the criteria, freeze a throwaway DIR, prepare it on 25 to 50 records, review the conflicts, then freeze the real DIR.",
        "Call `omh research screening freeze --criteria FILE --codes FILE --out DIR`. The protocol is write-once: a criteria change after freeze means a new DIR, never an edited protocol.json.",
        "Call `omh research screening prepare --dir DIR --records FILE --seed N`, then read DIR/manifest.json for the batch list.",
        f"When {_DELEGATE}, dispatch two children, A and B: give each only its own `DIR/tasks/<A|B>/` files and tell it to write answer lines to `DIR/answers/<A|B>/`. Never pass one child the other's tasks, answers or name; without the tool, ask the person to run the two reviewers separately. By default a child runs on the session's model (or the `delegation.model` pin) and `delegate_task` takes no per-child model, so A and B are then recorded as the same model: pass the real model for both and report `broken_independence`. Where the host routes each delegated task to a different model (a delegation backend or `omh_delegate_route`), give B another route and record the model it reports; otherwise ask the person to run reviewer B in a session on another model. Never write a model name you did not observe.",
        "Call `omh research screening merge --dir DIR --answers-a DIR/answers/A --answers-b DIR/answers/B --reviewer-models A=<model>,B=<model> --json`. Exit 1 means conflicts or pending records remain; exit 2 is an input error to fix, not a result.",
        "Show the conflict and pending ids to the person, or give a third child only the conflict records and the frozen criteria; pass its lines with `--adjudication` and merge again.",
    ),
    artifact_expectations=("Keep protocol.json, manifest.json, every task file and every answer file under DIR; the merge payload carries ids and codes only, never titles, abstracts or answer text.",),
    safety_rules=(
        "A record with no answer line, two different lines or an unknown code is pending for that reviewer; never read it as an exclusion.",
        "Same-model reviewers are not independent: report `reviewer_independence` as the merge prints it, and keep the `broken_independence` warning in the report.",
        "Agreement (kappa, PABAK) is agreement between two reviewers, not accuracy; never call it correctness against a human gold set.",
        "AI screening decisions are decision support; the review team verifies them before any PRISMA count is published.",
    ),
    quality_bar=("Counts in the report equal the merge payload's counts, with conflicts and pending reported separately from included and excluded.",
                 "The report names the protocol_sha256, the seed and the reviewer models it ran with."),
    do_not_use_when=(
        "Finding candidate papers, datasets or repositories on a topic belongs to `source-finder`.",
        "Explaining one supplied paper section by section belongs to `paper-learning`.",
        "Checking a HellaSwag log against the paper's reported conditions belongs to `repro-audit`.",
        "Full-text screening, search-string building, risk-of-bias and data extraction are not covered; this skill screens title and abstract only.",
        "Drafting the manuscript itself is paper writing: load Hermes' optional research-paper-writing skill when it is installed.",
    ),
    good_example=SkillExample(prompt="Screen these 400 abstracts for my systematic review of statin trials with two reviewers.", expected="Freeze the agreed criteria, prepare blind batches, dispatch reviewers A and B, merge, and report conflicts, pending records and agreement with the independence label.", why="The person has records and a review protocol, and needs dual screening."),
    bad_example=SkillExample(prompt="Do a systematic code review of this PR.", expected="Route to code review; nothing here screens literature.", why="Systematic describes the review style, not a literature screening protocol."),
    final_checklist=(
        "protocol.json was frozen before any reviewer saw a record.",
        "Each reviewer received only its own task files.",
        "The report gives included, excluded by code, conflicts, adjudicated and pending counts, agreement and the independence label from the observed merge output.",
    ),
    recovery_notes=(
        "If freeze refuses because protocol.json exists, choose a new DIR; never delete or edit the frozen protocol.",
        "If merge reports pending records, send the missing ids back to that reviewer only, then merge again.",
    ),
    situations=("screen abstracts before a meta-analysis", "two reviewers disagree on which studies to include",
                "PRISMA flow diagram counts for included studies", "inter-rater agreement for literature screening",
                "apply inclusion and exclusion criteria to search results"),
)
