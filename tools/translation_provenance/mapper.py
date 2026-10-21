"""Fail-closed, directional translation evidence mapper.

Sense assertions in a stream are NOT an authoritative lexical sense registry; output
is a traceability preflight, not a publication or factual translation approval.
"""
import argparse
import hashlib
import json
import sys

from tools.contribution_gate.evidence import (
    exact_source_reference, required, verified_artifact, verified_sources
)

def map_provenance(stream, sources_manifest, *, repo_root=None):
    sources = verified_sources(sources_manifest, repo_root)
    senses = {}
    translations = []
    for line_num, line in enumerate(stream, 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise ValueError("Malformed translation JSONL line " + str(line_num)) from exc
        if not isinstance(entry, dict):
            raise ValueError("Non-object translation stream record")
        kind = entry.get("type")
        if kind == "sense":
            sid = required(entry.get("sense_id"), "sense_id")
            if sid in senses:
                raise ValueError("Duplicate sense_id " + sid)
            for name in ("lexeme_id", "language", "source_locator"):
                required(entry.get(name), "sense " + name)
            source = exact_source_reference(entry.get("source"), sources)
            senses[sid] = {**entry, "_verified_source_id": source["source_id"]}
        elif kind == "translation":
            translations.append(entry)
        else:
            raise ValueError("Unknown record type")
    if not senses or not translations:
        raise ValueError("Independent source-linked sense and translation records required")
    seen = set()
    records = []
    for entry in translations:
        tid = required(entry.get("translation_id"), "translation_id")
        if tid in seen:
            raise ValueError("Duplicate translation_id " + tid)
        seen.add(tid)
        source_id = required(entry.get("from_sense_id"), "from_sense_id")
        target_id = required(entry.get("to_sense_id"), "to_sense_id")
        if source_id not in senses or target_id not in senses:
            raise ValueError("Orphan translation " + tid)
        source = exact_source_reference(entry.get("source"), sources)
        from_sense, to_sense = senses[source_id], senses[target_id]
        from_language = from_sense["language"]
        to_language = to_sense["language"]
        if from_language == to_language:
            raise ValueError("Invalid language direction")
        if (entry.get("from_language", from_language) != from_language or
                entry.get("to_language", to_language) != to_language):
            raise ValueError("Translation direction contradicts sense ownership")
        evidence = entry.get("translation_evidence")
        if not isinstance(evidence, dict):
            raise ValueError("Missing translation evidence " + tid)
        required(evidence.get("source_locator"), "translation source locator")
        verified_artifact(repo_root, evidence.get("artifact_path"),
                          evidence.get("sha256"), "attested translation " + tid)
        record = {
            "translation_id": tid,
            "from_sense_id": source_id, "to_sense_id": target_id,
            "from_lexeme_id": from_sense["lexeme_id"], "to_lexeme_id": to_sense["lexeme_id"],
            "from_language": from_language, "to_language": to_language,
            "from_sense_source_id": from_sense["_verified_source_id"],
            "to_sense_source_id": to_sense["_verified_source_id"],
            "source_id": source["source_id"], "dataset_version": source["dataset_version"],
            "publisher": source["publisher"], "origin_url": source["origin_url"],
            "license_id": source["license"]["id"],
            "license_evidence_url": source["license"]["evidence_url"],
            "artifact_sha256": source["retrieval"]["sha256"],
            "translation_source_locator": evidence["source_locator"],
            "translation_evidence_sha256": evidence["sha256"],
            "evidence_only": True
        }
        record["provenance_hash"] = hashlib.sha256(
            json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        records.append(record)
    # Not a streaming generator: no partial stdout if a later record fails.
    return records

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sources", required=True)
    p.add_argument("--translations", default="-")
    p.add_argument("--repo-root", required=True)
    a = p.parse_args(argv)
    try:
        with open(a.sources, encoding="utf-8") as f:
            ledger = json.load(f)
        if a.translations == "-":
            result = map_provenance(sys.stdin, ledger, repo_root=a.repo_root)
        else:
            with open(a.translations, encoding="utf-8") as f:
                result = map_provenance(f, ledger, repo_root=a.repo_root)
        for record in result:
            print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    except (ValueError, OSError, TypeError) as exc:
        print("BLOCKED:", exc, file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
