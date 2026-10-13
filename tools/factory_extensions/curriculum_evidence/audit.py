"""Read-only, source-gated, language-specific curriculum coverage receipts.

This is NOT a proficiency test, an accreditation registry or a CEFR estimator.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit

KINDS = ("vocabulary", "grammar", "example", "exercise")
STATES = ("unknown", "unassessed", "estimated", "source_attested")
SKILLS = ("reading", "listening", "writing", "speaking")
MAX_ROWS = 10000
MAX_BYTES = 8 * 1024 * 1024
MAX_LINE = 65536
ROOT = Path(__file__).resolve().parents[3]


class AuditError(ValueError):
    pass


MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_LICENSE_BYTES = 2 * 1024 * 1024


def _https(value):
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlsplit(value)
        forbidden = {"token", "key", "access_token", "signature", "auth", "password"}
        return (parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
                and not parsed.password and not (set(parse_qs(parsed.query)) & forbidden))
    except ValueError:
        return False


def _valid_iso_date(value):
    try:
        return date.fromisoformat(value).isoformat() == value
    except (TypeError, ValueError):
        return False


def _file_digest(root, name, *, limit):
    if not isinstance(name, str) or not name or ".." in Path(name).parts or Path(name).is_absolute():
        return None
    try:
        base = root.resolve()
        path = (base / name).resolve()
        if not path.is_relative_to(base) or ".git" in Path(name).parts:
            return None
        if not path.is_file() or path.stat().st_size > limit:
            return None
        digest = hashlib.sha256()
        with path.open("rb") as fp:
            for block in iter(lambda: fp.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


def _approved(source_ref, ledger, *, root=ROOT):
    """Validate current source bytes AND license notice against a reviewed Route05 ledger.

    This is a bounded read-only prerequisite, not independent legal clearance.
    """
    if not isinstance(source_ref, dict) or set(source_ref) != {"source_id", "dataset_version", "artifact_sha256"}:
        return False
    sources = ledger.get("sources", []) if isinstance(ledger, dict) else []
    if not isinstance(sources, list):
        return False
    matches = [s for s in sources if isinstance(s, dict) and s.get("source_id") == source_ref["source_id"]]
    if len(matches) != 1:
        return False
    row = matches[0]
    review, retrieval, license_info = row.get("review"), row.get("retrieval"), row.get("license")
    if not all(isinstance(x, dict) for x in (review, retrieval, license_info)):
        return False
    original = source_ref["artifact_sha256"]
    license_hash = license_info.get("evidence_sha256")
    if not all(isinstance(x, str) and re.fullmatch(r"[0-9a-f]{64}", x)
               for x in (original, license_hash)):
        return False
    license_url = license_info.get("evidence_url")
    if (row.get("status") != "APPROVED_FOR_REDISTRIBUTION"
            or row.get("dataset_version") != source_ref["dataset_version"]
            or retrieval.get("sha256") != original
            or row.get("kind") not in ("dictionary", "morphology", "examples", "font", "pronunciation", "vector_art", "visual_asset")
            or not row.get("publisher") or not row.get("alterations")
            or not retrieval.get("identity") or not isinstance(retrieval.get("date"), str)
            or not _valid_iso_date(retrieval.get("date"))
            or not all(_https(value) for value in (row.get("origin_url"), retrieval.get("url"),
                                                  license_url, review.get("decision_url")))
            or not review.get("reviewer")
            or license_info.get("id") not in ("CC-BY-SA-4.0", "GFDL-1.3-only", "CC0-1.0", "PUBLIC-DOMAIN")
            or any(host in license_url for host in ("creativecommons.org/licenses/",
                                                    "creativecommons.org/publicdomain/zero/",
                                                    "gnu.org/licenses/fdl-"))):
        return False
    if license_info["id"] == "PUBLIC-DOMAIN":
        proof = license_info.get("public_domain_proof")
        if not isinstance(proof, dict) or not all(proof.get(k) for k in ("jurisdiction", "legal_basis", "work_date")):
            return False
    return (_file_digest(root, retrieval.get("artifact_path"), limit=MAX_SOURCE_BYTES) == original
            and _file_digest(root, license_info.get("evidence_path"), limit=MAX_LICENSE_BYTES) == license_hash)


def _bad_prerequisites(rows, invalid_ids=()):
    """Return all endpoints of invalid edges/cycles without recursive traversal."""
    bad = set(invalid_ids)
    graph = {r["record_id"]: r for r in rows}
    for rid, row in graph.items():
        for parent in row["prerequisites"]:
            other = graph.get(parent)
            if other is None:
                bad.add(rid)
            elif (rid == parent or other["language"] != row["language"]
                  or other["curriculum"]["id"] != row["curriculum"]["id"]
                  or other["proficiency"]["proficiency_framework_id"] != row["proficiency"]["proficiency_framework_id"]
                  or (row["proficiency"]["classification_status"] == "source_attested"
                      and other["proficiency"]["classification_status"] != "source_attested")):
                bad.update((rid, parent))
    state = {}
    for root in graph:
        if root in bad or state.get(root) == 2:
            continue
        state[root] = 1
        stack = [(root, iter(graph[root]["prerequisites"]))]
        while stack:
            current, links = stack[-1]
            try:
                parent = next(links)
            except StopIteration:
                state[current] = 2
                stack.pop()
                continue
            if parent not in graph or parent in bad:
                continue
            if state.get(parent) == 1:
                # Mark all participants on the current dependency cycle.
                ids = [n for n, _ in stack]
                bad.update(ids[ids.index(parent):])
            elif state.get(parent) != 2:
                state[parent] = 1
                stack.append((parent, iter(graph[parent]["prerequisites"])))
    # Linear-time reverse-edge propagation; avoid repeated 10k-row scans.
    dependents = {}
    for rid, row in graph.items():
        for parent in row["prerequisites"]:
            dependents.setdefault(parent, set()).add(rid)
    queue = list(bad)
    while queue:
        for child in dependents.get(queue.pop(), ()):
            if child not in bad:
                bad.add(child)
                queue.append(child)
    return bad


def audit(languages, frameworks, ledger, rows, validate_record, *, criteria=None):
    """Validate at most 10k records; produce independent per-language coverage."""
    if not isinstance(languages, list) or not 1 <= len(languages) <= 100:
        raise AuditError("Missing language registry")
    language_map = {r["id"]: r for r in languages}
    if len(language_map) != len(languages):
        raise AuditError("Duplicate language ID")
    standards = {f["proficiency_framework_id"]: f for f in frameworks["frameworks"]}
    source_cache = {}
    def source_is_approved(ref):
        if not isinstance(ref, dict):
            return False
        key = tuple((k, ref.get(k)) for k in ("source_id", "dataset_version", "artifact_sha256"))
        try:
            if key not in source_cache:
                source_cache[key] = _approved(ref, ledger)
            return source_cache[key]
        except TypeError:
            return False

    if criteria is not None:
        if (not isinstance(criteria, dict) or not source_is_approved(criteria.get("source"))
                or not criteria.get("reviewer") or not isinstance(criteria.get("minimums"), dict)
                or set(criteria["minimums"]) != set(KINDS)
                or any(type(v) is not int or v < 0 for v in criteria["minimums"].values())):
            raise AuditError("Editorial targets require approved source, reviewer, and all four counts")
    result = {"schema_version": "1.0.0", "purpose": "content_coverage_not_learner_assessment",
              "admission_status": "NO_APPROVED_CLASSIFICATIONS", "audited_rows": 0,
              "accepted_metadata": 0, "rejected": 0, "rejection_reasons": {}, "languages": {}}
    for lid, lang in sorted(language_map.items()):
        framework_ids = list(lang.get("proficiency", {}).get("framework_ids", []))
        result["languages"][lid] = {
            "framework_ids": framework_ids,
            "framework_gaps": sorted(fid for fid in framework_ids if fid not in standards),
            "scripts": lang.get("scripts", []), "verified_total": 0,
            "unknown_total": 0, "unassessed_total": 0, "estimated_total": 0, "curricula": {},
            "coverage_state": "no_verified_content"}
    accepted = {}
    failures = Counter()
    seen = set()
    duplicates = set()
    for row in rows:
        result["audited_rows"] += 1
        if result["audited_rows"] > MAX_ROWS:
            raise AuditError("Audit row limit exceeded")
        try:
            if not isinstance(row, dict):
                raise AuditError("invalid_row")
            rid, lid, kind = row["record_id"], row["language"], row["kind"]
            if not isinstance(rid, str) or not rid or len(rid) > 128:
                raise AuditError("invalid_identity")
            if rid in seen:
                duplicates.add(rid)
                raise AuditError("duplicate_identity")
            seen.add(rid)
            if lid not in language_map or kind not in KINDS:
                raise AuditError("unknown_language_or_content_kind")
            ref = row["source"]
            if not source_is_approved(ref):
                raise AuditError("source_not_approved")
            proficiency = row["proficiency"]
            if proficiency["record_id"] != rid or proficiency["language"] != lid:
                raise AuditError("record_identity_mismatch")
            validate_record(proficiency)  # canonical standards/proficiency validator
            status = proficiency["classification_status"]
            if status not in STATES:
                raise AuditError("invalid_status")
            fid, level = proficiency["proficiency_framework_id"], proficiency["proficiency_level_id"]
            if status in ("unknown", "unassessed"):
                if fid is not None or level is not None or proficiency.get("evidence"):
                    raise AuditError("unsupported_level_claim")
            else:
                if (fid not in standards or level not in standards[fid]["levels"]
                        or fid not in language_map[lid].get("proficiency", {}).get("framework_ids", [])
                        or not standards[fid].get("version")):
                    raise AuditError("unregistered_framework_or_level")
            if status == "source_attested":
                if not any(e.get("source_id") == ref["source_id"]
                           and e.get("source_version") == ref["dataset_version"]
                           and e.get("locator") for e in proficiency.get("evidence", [])):
                    raise AuditError("classification_source_unbound")
            # Never confuse attested educational material with measured learner competence.
            if any(v.get("status") == "demonstrated" for v in proficiency.get("skills", {}).values()):
                raise AuditError("learner_skill_claim_forbidden")
            cur = row["curriculum"]
            if (not isinstance(cur, dict) or not isinstance(cur.get("id"), str)
                    or not cur["id"] or len(cur["id"]) > 128
                    or cur.get("source_id") != ref["source_id"]
                    or cur.get("source_version") != ref["dataset_version"]
                    or not cur.get("locator")):
                raise AuditError("curriculum_provenance_unbound")
            deps = row["prerequisites"]
            if (not isinstance(deps, list) or len(deps) > 32
                    or len(set(deps)) != len(deps)
                    or any(not isinstance(p, str) for p in deps)):
                raise AuditError("invalid_prerequisites")
            evidence = row.get("prerequisite_evidence", [])
            if (not isinstance(evidence, list) or len(evidence) > 32
                    or len(evidence) != len(deps)
                    or not all(isinstance(e, dict) and set(e) == {
                        "record_id", "source_id", "source_version", "locator", "reviewer_id"}
                        and isinstance(e["record_id"], str)
                        and e["source_id"] == ref["source_id"]
                        and e["source_version"] == ref["dataset_version"]
                        and isinstance(e["locator"], str) and bool(e["locator"].strip())
                        and isinstance(e["reviewer_id"], str) and bool(e["reviewer_id"].strip())
                        for e in evidence)
                    or sorted(e["record_id"] for e in evidence) != sorted(deps)):
                raise AuditError("prerequisite_evidence_unverified")
            tax = row.get("taxonomy", [])
            if not isinstance(tax, list) or len(tax) > 16:
                raise AuditError("invalid_taxonomy")
            for label in tax:
                if (not isinstance(label, dict) or label.get("kind") not in ("topic", "situation")
                        or not isinstance(label.get("value"), str) or not label["value"]
                        or label.get("source_id") != ref["source_id"]
                        or label.get("source_version") != ref["dataset_version"]
                        or not label.get("locator") or not label.get("reviewer_id")):
                    raise AuditError("taxonomy_not_source_attested")
            skill_material = row.get("skill_material", [])
            if not isinstance(skill_material, list) or len(skill_material) > len(SKILLS):
                raise AuditError("invalid_skill_material")
            skill_seen = set()
            for claim in skill_material:
                if (not isinstance(claim, dict) or claim.get("skill") not in SKILLS
                        or claim["skill"] in skill_seen
                        or claim.get("source_id") != ref["source_id"]
                        or claim.get("source_version") != ref["dataset_version"]
                        or not claim.get("locator") or not claim.get("reviewer_id")):
                    raise AuditError("skill_material_not_attested")
                skill_seen.add(claim["skill"])
            accepted[rid] = row
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            code = str(exc) if isinstance(exc, AuditError) else "canonical_or_record_validation_failed"
            failures[code] += 1
    # A single curriculum cannot silently mean different frameworks.
    framework_owners = {}
    collisions = set()
    for rid, row in accepted.items():
        key = (row["language"], row["curriculum"]["id"])
        framework_owners.setdefault(key, {}).setdefault(
            row["proficiency"]["proficiency_framework_id"], set()).add(rid)
    for owners in framework_owners.values():
        if len(owners) > 1:
            for ids in owners.values():
                collisions.update(ids)
    invalid = _bad_prerequisites(list(accepted.values()), duplicates | collisions)
    for rid in invalid:
        accepted.pop(rid, None)
        failures["invalid_prerequisite_graph"] += 1
    for row in accepted.values():
        lang = result["languages"][row["language"]]
        prof = row["proficiency"]
        status = prof["classification_status"]
        if status in ("unknown", "unassessed"):
            lang["unknown_total" if status == "unknown" else "unassessed_total"] += 1
            continue
        if status == "estimated":
            lang["estimated_total"] += 1
            continue
        lang["verified_total"] += 1
        cid = row["curriculum"]["id"]
        entry = lang["curricula"].setdefault(cid, {"framework_id": prof["proficiency_framework_id"],
                                              "framework_version": standards[prof["proficiency_framework_id"]]["version"],
                                              "levels": {}})
        if entry["framework_id"] != prof["proficiency_framework_id"]:
            raise AuditError("Curriculum framework collision")
        stage = entry["levels"].setdefault(prof["proficiency_level_id"], {
            "verified_counts": {k: 0 for k in KINDS},
            "skill_material_counts": {k: 0 for k in SKILLS},
            "topic_counts": {}, "situation_counts": {},
            "sufficiency": "unassessed_no_approved_targets"})
        stage["verified_counts"][row["kind"]] += 1
        for claim in row.get("skill_material", []):
            # Independently attested educational *material*, not a learner result.
            stage["skill_material_counts"][claim["skill"]] += 1
        for label in row.get("taxonomy", []):
            counts = stage["topic_counts" if label["kind"] == "topic" else "situation_counts"]
            counts[label["value"]] = counts.get(label["value"], 0) + 1
    for lang in result["languages"].values():
        if lang["verified_total"]:
            lang["coverage_state"] = "some_source_attested_content_not_certification"
            result["admission_status"] = "PARTIAL_APPROVED_METADATA_ONLY"
        for entry in lang["curricula"].values():
            for stage in entry["levels"].values():
                if criteria is not None:
                    stage["sufficiency"] = (
                        "meets_editorial_targets_not_accreditation" if all(
                            stage["verified_counts"][k] >= criteria["minimums"][k] for k in KINDS)
                        else "below_editorial_targets")
    result["rejected"] = sum(failures.values())
    result["accepted_metadata"] = len(accepted)
    result["rejection_reasons"] = dict(sorted(failures.items()))
    return result


def iter_jsonl(path):
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise AuditError("Missing or oversized approved JSONL input")
    with path.open("rb") as fp:
        for raw in fp:
            if len(raw) > MAX_LINE:
                raise AuditError("Overlong JSONL record")
            yield json.loads(raw.decode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="reviewed, approved input JSONL; optional")
    parser.add_argument("--criteria", type=Path, help="source-approved editorial sufficiency targets")
    parser.add_argument("--output", type=Path, help="local report receipt path; stdout by default")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    from tools.proficiency_mapping.engine import ProficiencyCatalog
    catalog = ProficiencyCatalog()
    def load(rel):
        with (ROOT / rel).open(encoding="utf-8") as fp:
            return json.load(fp)
    languages = load("catalog/language_registry.v1.json")["languages"]
    standards = load("standards/proficiency/frameworks.json")
    ledger = load("legal/ledger/sources.json")
    criteria = json.loads(args.criteria.read_text(encoding="utf-8")) if args.criteria else None
    rows = iter_jsonl(args.input) if args.input else iter(())
    report = audit(languages, standards, ledger, rows, catalog.validate_record, criteria=criteria)
    report["registry_languages"] = len(languages)
    report["approved_ledger_sources"] = sum(s.get("status") == "APPROVED_FOR_REDISTRIBUTION" for s in ledger["sources"])
    report["input_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest() if args.input else None
    report["code_head_sha"] = os.environ.get("GITHUB_SHA")
    output = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AuditError, OSError, ValueError) as exc:
        print("Curriculum audit blocked:", exc, file=sys.stderr)
        raise SystemExit(2)
