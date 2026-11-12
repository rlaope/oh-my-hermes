#!/usr/bin/env python3
"""Original OMH offline BioMCP capture reconciliation. MIT; no clinical advice.

This script opens no socket and launches no process. Capture BioMCP separately
with a bounded host terminal tool; provider text is untrusted data, not commands.
"""
from __future__ import annotations

import argparse
from datetime import datetime, time
import hashlib
import json
import os
from pathlib import Path
import re
import sys

SOURCES = ("ClinVar", "ClinicalTrials.gov")
MAX_BYTES = 8 * 1024 * 1024
IDENTITY_FIELDS = ("gene", "id", "legacy_name", "rsid", "genome_build", "genome_build_provenance", "transcript", "hgvs_c", "hgvs_p")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def strict_fromisoformat(text):
    # Python 3.14 reads T24:00:00 as the next midnight; 3.11-3.13 refuse it.
    # Only that reading moves the date past the one the text starts with, so
    # refusing it here makes every supported interpreter agree.
    parsed = datetime.fromisoformat(text)
    if parsed.time() == time(0) and not text.startswith(date_spellings(parsed.date())):
        raise ValueError("hour must be in 0..23")
    return parsed


def date_spellings(day):
    week_year, week, weekday = day.isocalendar()
    spellings = (f"{day.year:04d}-{day.month:02d}-{day.day:02d}", f"{day.year:04d}{day.month:02d}{day.day:02d}",
                 f"{week_year:04d}-W{week:02d}-{weekday}", f"{week_year:04d}W{week:02d}{weekday}")
    if weekday == 1:
        spellings += (f"{week_year:04d}-W{week:02d}", f"{week_year:04d}W{week:02d}")
    return spellings


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be an explicit timezone-aware ISO string")
    parsed = strict_fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must carry a timezone")
    return parsed


def system_alias(part):
    # macOS ships /etc, /tmp and /var (home of the default temp dir) as links
    # into /private. Only root can create a top-level entry, so trust exactly
    # those three, and only when the link names the same directory there.
    if sys.platform != "darwin" or part.parent != Path("/") or part.name not in ("etc", "tmp", "var"):
        return False
    try:
        return os.readlink(part) in ("private/" + part.name, "/private/" + part.name)
    except OSError:
        return False


def safe_path(path):
    path = Path(path).absolute()
    if ".." in path.parts or any(part.is_symlink() and not system_alias(part) for part in (path, *path.parents)):
        raise ValueError("symlinks and traversal are not accepted")
    return path


def read_bytes(path):
    path = safe_path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("capture must be a regular file no larger than 8 MiB")
    return path.read_bytes()


def capture_path(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("capture paths must be relative POSIX paths")
    part = Path(relative)
    if part.is_absolute() or ".." in part.parts or ":" in relative:
        raise ValueError("capture path escapes its manifest directory")
    return safe_path(root / part)


def condition_basis(query, conditions):
    return "exact_label" if query["disease"].casefold() in [s.casefold() for s in conditions] else "not_established"


def recognized_assertion(assertion):
    # Validate the source shape, not the biological meaning or a vocabulary.
    return (isinstance(assertion, dict) and isinstance(assertion.get("classification"), str)
            and bool(assertion["classification"].strip()))


def adapt_clinvar(payload, query):
    cv = payload["clinvar"]
    identity = {key: payload[key] for key in IDENTITY_FIELDS if key in payload}
    claims = [{"path": "/clinvar/germline_classification", "scope": "record_level_germline",
               "disease_matching_basis": "record_level_unspecified", "assertion": cv.get("germline_classification")}]
    for key in ("aggregates", "submissions"):
        for index, assertion in enumerate(cv.get(key, [])):
            claims.append({"path": f"/clinvar/{key}/{index}", "scope": key,
                           "disease_matching_basis": condition_basis(query, assertion.get("conditions", [])),
                           "assertion": assertion})
    gaps = []
    for claim in claims:
        if not recognized_assertion(claim["assertion"]):
            # Retain the exact raw value and pointer, but never interpret it.
            claim.update(status="unavailable", failure="clinvar_assertion_schema_mismatch")
            gaps.append("clinvar_assertion_schema_mismatch:" + claim["path"])
    disagreements = []
    if isinstance(payload.get("significance_note"), str) and payload["significance_note"]:
        disagreements.append({"kind": "upstream_significance_note", "text": payload["significance_note"],
                              "source": payload.get("significance_source"), "path": "/significance_note"})
    groups = {}
    for claim in claims:
        if claim.get("status") == "unavailable":
            continue
        assertion = claim["assertion"]
        value = assertion.get("classification")
        if isinstance(value, str) and "conflict" in value.casefold():
            disagreements.append({"kind": "upstream_reported_conflict", "path": claim["path"], "value": value})
        if claim["scope"] == "record_level_germline" or not isinstance(value, str):
            continue
        conditions = tuple(sorted(s.casefold() for s in assertion.get("conditions", [])))
        domain = assertion.get("classification_domain")
        if not isinstance(domain, str) or not conditions:
            continue
        key = (claim["scope"], domain, conditions)
        groups.setdefault(key, []).append((value, claim["path"]))
    for (scope, domain, conditions), entries in groups.items():
        values = sorted(set(value for value, _ in entries))
        if len(values) > 1:
            disagreements.append({"kind": "differing_assertions_same_context", "scope": scope,
                                  "classification_domain": domain, "condition_labels_casefolded": list(conditions),
                                  "values": values, "paths": [p for _, p in entries],
                                  "interpretation": "Potential disagreement, not adjudicated; dates, review and submitter context retained."})
    row = {"status": "unavailable" if gaps else "available", "identity": identity, "accession": cv.get("accession"),
            "source_record": {k: v for k, v in cv.items() if k not in ("aggregates", "submissions", "germline_classification")},
            "claims": claims, "gaps": gaps, "disagreements": disagreements}
    if gaps:
        row["failure"] = "clinvar_assertion_schema_mismatch"
    return row


def adapt_trial(payload, query):
    return {"status": "available", "identity": {"nct_id": payload["nct_id"]},
            "registry_record": {k: payload[k] for k in ("nct_id", "source", "title", "status", "conditions", "last_update_posted", "last_update", "last_updated", "summary") if k in payload},
            "disease_matching_basis": condition_basis(query, payload["conditions"]),
            "variant_relationship": "not_established", "claims": [], "gaps": [], "disagreements": [],
            "boundary": "Registry status is not eligibility or a treatment recommendation."}


def unavailable(reason):
    return {"status": "unavailable", "failure": reason, "claims": [], "gaps": [reason], "disagreements": []}


def adapt(payload, source, query, receipt):
    if receipt["exit_code"] != 0:
        return unavailable(f"capture_exit_{receipt['exit_code']}")
    if not isinstance(payload, dict):
        return unavailable("schema_mismatch")
    if payload.get("error") or payload.get("errors"):
        return unavailable("embedded_source_error")
    meta = payload.get("_meta")
    sections = meta.get("section_sources") if isinstance(meta, dict) else None
    if not isinstance(sections, list) or not sections:
        return unavailable("source_provenance_metadata_absent")
    relevant = [s for s in sections if isinstance(s, dict) and
                (s.get("key") == "clinvar" if source == "ClinVar" else s.get("key") == "overview")]
    expected_provider = "NCBI ClinVar" if source == "ClinVar" else "ClinicalTrials.gov"
    if not relevant or any(s.get("outcome") != "data" or not isinstance(s.get("sources"), list) or expected_provider not in s["sources"] for s in relevant):
        return unavailable("required_source_section_not_data")
    source_sections = [s for s in sections if isinstance(s, dict) and isinstance(s.get("sources"), list) and expected_provider in s["sources"]]
    if any(s.get("outcome") not in ("data", "not_requested") or s.get("error") for s in source_sections):
        row = unavailable("embedded_source_section_failure")
        row["source_sections"] = source_sections
        return row
    if source == "ClinVar":
        outcomes = payload.get("section_outcomes", {})
        cv = payload.get("clinvar")
        if not isinstance(outcomes, dict) or not isinstance(outcomes.get("clinvar"), dict) or outcomes["clinvar"].get("outcome") != "data":
            return unavailable("embedded_clinvar_section_failure")
        if not isinstance(cv, dict) or cv.get("error") or cv.get("errors"):
            return unavailable("embedded_clinvar_error_or_missing")
        if any(not isinstance(payload.get(k), str) or not payload[k] for k in ("gene", "id")):
            return unavailable("variant_identity_schema_mismatch")
        if not isinstance(cv.get("accession"), str):
            return unavailable("clinvar_assertion_schema_mismatch")
        for key in ("aggregates", "submissions"):
            values = cv.get(key, [])
            if not isinstance(values, list) or len(values) > 10000 or any(not isinstance(s, dict) for s in values):
                return unavailable("clinvar_assertion_schema_mismatch")
            if any(not isinstance(s.get("conditions", []), list) or any(not isinstance(c, str) for c in s.get("conditions", [])) for s in values):
                return unavailable("clinvar_conditions_schema_mismatch")
        return adapt_clinvar(payload, query)
    if not isinstance(payload.get("nct_id"), str) or not re.fullmatch(r"NCT[0-9]{8}", payload["nct_id"]) or not isinstance(payload.get("status"), str):
        return unavailable("trial_identity_schema_mismatch")
    if not isinstance(payload.get("conditions"), list) or any(not isinstance(c, str) for c in payload["conditions"]):
        return unavailable("trial_conditions_schema_mismatch")
    return adapt_trial(payload, query)


def freshness(source_time, finished_at, kind):
    result = {"source_time": source_time, "retrieved_at": finished_at, "time_kind": kind,
              "age_days": None, "status": "unknown"}
    if source_time is None:
        return result
    try:
        if not isinstance(source_time, str):
            raise ValueError("source time must be text")
        date = strict_fromisoformat(source_time.replace("Z", "+00:00")).date()
        age = (timestamp(finished_at).date() - date).days
        result.update(age_days=age, status="future_source_time" if age < 0 else "dated_not_certified_current")
    except (ValueError, TypeError):
        result["status"] = "invalid_source_time"
    return result


def annotate_freshness(row, receipt):
    if row["status"] != "available":
        return
    if row["source"] == "ClinVar":
        for claim in row["claims"]:
            claim["freshness"] = freshness(claim["assertion"].get("evaluation_date"), receipt["finished_at"], "evaluation_date_not_update")
            if claim["freshness"]["status"] in ("unknown", "invalid_source_time", "future_source_time"):
                row["gaps"].append("assertion_evaluation_time_missing_or_invalid:" + claim["path"])
    else:
        record = row["registry_record"]
        source_time = next((record[k] for k in ("last_update_posted", "last_updated", "last_update") if record.get(k)), None)
        row["freshness"] = freshness(source_time, receipt["finished_at"], "registry_update_time")
        if row["freshness"]["status"] == "unknown":
            row["gaps"].append("source_update_time_absent")
        elif row["freshness"]["status"] in ("invalid_source_time", "future_source_time"):
            row["gaps"].append(row["freshness"]["status"])


def reconcile(manifest_path):
    path = safe_path(manifest_path)
    raw = read_bytes(path)
    envelope = json.loads(raw)
    if not isinstance(envelope, dict) or envelope.get("schema") != "biomedical_captures/v1":
        raise ValueError("expected biomedical_captures/v1")
    if envelope.get("data_class") not in ("public_source_capture", "synthetic_schema_fixture"):
        raise ValueError("data_class must attest public_source_capture or synthetic_schema_fixture; no patient data")
    query = envelope.get("query")
    if not isinstance(query, dict) or any(not isinstance(query.get(k), str) or not query[k].strip() for k in ("gene", "disease")):
        raise ValueError("query requires exact public gene and disease strings")
    if "variant" in query and (not isinstance(query["variant"], str) or not query["variant"].strip()):
        raise ValueError("query variant, when present, must be a nonempty exact string")
    intended = envelope.get("intended_ids", {})
    if not isinstance(intended, dict) or any(k not in IDENTITY_FIELDS + ("nct_id", "accession") or not isinstance(v, str) or not v for k, v in intended.items()):
        raise ValueError("unsupported intended entity identifier field or nonliteral value")
    captures = envelope.get("captures")
    if not isinstance(captures, list) or not 1 <= len(captures) <= 16:
        raise ValueError("captures must contain 1 to 16 receipts")
    rows = []
    for receipt in captures:
        if not isinstance(receipt, dict) or receipt.get("source") not in SOURCES:
            raise ValueError("capture source must be ClinVar or ClinicalTrials.gov")
        source = receipt["source"]
        if not isinstance(receipt.get("argv"), list) or not receipt["argv"] or any(not isinstance(s, str) for s in receipt["argv"]):
            raise ValueError("receipt argv must preserve exact nonempty string array")
        if not isinstance(receipt.get("version"), str) or not receipt["version"]:
            raise ValueError("receipt requires observed BioMCP version")
        start, end = timestamp(receipt.get("started_at")), timestamp(receipt.get("finished_at"))
        if end < start or type(receipt.get("exit_code")) is not int:
            raise ValueError("invalid capture time range or exit code")
        stdout = read_bytes(capture_path(path.parent, receipt.get("stdout_path")))
        stderr = read_bytes(capture_path(path.parent, receipt.get("stderr_path")))
        if digest(stdout) != receipt.get("sha256") or digest(stderr) != receipt.get("stderr_sha256"):
            raise ValueError("capture hash mismatch")
        try:
            payload = json.loads(stdout)
            row = adapt(payload, source, query, receipt)
        except (ValueError, UnicodeError, RecursionError):
            row = unavailable("invalid_source_json")
        if source == "ClinVar" and row["status"] == "available":
            row["identity_status"] = "matched_exact_gene"
            if row["identity"].get("gene", "").casefold() != query["gene"].casefold():
                row["gaps"].append("gene_mismatch")
            variant = query.get("variant")
            candidates = [row["identity"].get(k) for k in ("legacy_name", "id", "rsid", "hgvs_p", "hgvs_c")]
            transcript = row["identity"].get("transcript")
            if transcript and row["identity"].get("hgvs_c"):
                candidates.append(transcript + ":" + row["identity"]["hgvs_c"])
            if variant and variant not in candidates:
                row["gaps"].append("variant_mismatch_or_unresolved_alias")
            for key, value in intended.items():
                if key != "nct_id" and (row.get("accession") if key == "accession" else row["identity"].get(key)) != value:
                    row["gaps"].append(f"{key}_mismatch")
            if row["gaps"]:
                row["identity_status"] = "mismatch"
        if row["status"] == "available":
            if source == "ClinicalTrials.gov":
                if intended.get("nct_id") and intended["nct_id"] != row["identity"]["nct_id"]:
                    row["gaps"].append("nct_id_mismatch")
                if row["disease_matching_basis"] == "not_established":
                    row["gaps"].append("disease_label_match_not_established")
            elif not any(claim["disease_matching_basis"] == "exact_label" for claim in row["claims"]):
                row["gaps"].append("disease_label_match_not_established")
        row.update(source=source, receipt=receipt)
        annotate_freshness(row, receipt)
        rows.append(row)
    for source in SOURCES:
        if not any(row["source"] == source for row in rows):
            rows.append({"source": source, **unavailable("source_capture_missing"), "receipt": None})
    availability = "partial" if any(row["status"] != "available" for row in rows) else "complete"
    status = "partial" if any(row["gaps"] for row in rows) else "complete"
    return {"schema": "biomedical_evidence_matrix/v1", "query": query, "intended_ids": intended,
            "data_class": envelope.get("data_class", "unspecified"),
            "capture_manifest_sha256": digest(raw), "sources": rows,
            "availability": availability, "status": status,
            "boundary": "Public source assertions only; no patient data, clinical eligibility, treatment or consensus inference."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory; never overwrite existing files")
    args = parser.parse_args(argv)
    try:
        output = safe_path(args.output_dir)
        if output.exists() or not output.parent.is_dir():
            raise ValueError("output directory must be new with an existing safe parent")
        matrix = reconcile(args.capture_manifest)
        encoded = (json.dumps(matrix, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
        manifest = {"schema": "biomedical_reconciliation_manifest/v1", "status": matrix["status"],
                    "availability": matrix["availability"], "query": matrix["query"],
                    "capture_manifest_sha256": matrix["capture_manifest_sha256"],
                    "helper_sha256": digest(read_bytes(Path(__file__))),
                    "outputs": {"evidence-matrix.json": digest(encoded)}}
        output.mkdir()
        (output / "evidence-matrix.json").write_bytes(encoded)
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({"status": matrix["status"], "availability": matrix["availability"], "output_dir": str(output)}))
        return 0 if matrix["status"] == "complete" else 3
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        print(f"reconciliation refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
