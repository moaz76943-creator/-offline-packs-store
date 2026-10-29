#!/usr/bin/env python3
import json
import sys

MANDATORY_PROVENANCE_FIELDS = [
    'source_id',
    'canonical_url',
    'publisher',
    'license_id',
    'license_url',
    'allowed_uses',
    'attribution_required',
    'source_sha256',
    'license_evidence_sha256',
    'review_decision',
    'retrieval_date',
]

def validate_source_entry(source):
    missing = [f for f in MANDATORY_PROVENANCE_FIELDS if f not in source or not source[f]]
    if missing:
        return False, f"QUARANTINED: Missing fields: {', '.join(missing)}"
    if str(source.get('review_decision', '')).upper() != 'APPROVED':
        return False, "QUARANTINED: Not approved"
    return True, "ADMITTED"

def audit_sources_ledger(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    sources = data.get('sources', [])
    for s in sources:
        ok, msg = validate_source_entry(s)
        print(f"[{'PASS' if ok else 'FAIL'}] {s.get('source_id')}: {msg}")
    return True

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "legal/ledger/sources.json"
    audit_sources_ledger(path)
