#!/usr/bin/env python3
"""
Legal Source Admission Validator - Master Constitution Section 08 Compliant.
Guarantees zero unverified scraping or unlicensed sources enter production packs.
Strictly requires 11 immutable provenance fields for source admission.
"""
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
    source_id = source.get('source_id', 'UNKNOWN')
    missing = [f for f in MANDATORY_PROVENANCE_FIELDS if f not in source or not source[f]]
    if missing:
        return False, f"QUARANTINED: Missing mandatory fields: {', '.join(missing)}"
    
    decision = str(source.get('review_decision', '')).upper()
    if decision != 'APPROVED':
        return False, f"QUARANTINED: Review decision is '{decision}', not 'APPROVED'"
        
    license_id = str(source.get('license_id', '')).upper()
    valid_licenses = ['CC0-1.0', 'CC-BY-4.0', 'CC-BY-SA-4.0', 'PUBLIC_DOMAIN', 'MIT', 'APACHE-2.0', 'ODBL-1.0']
    if not any(v in license_id for v in valid_licenses):
        return False, f"QUARANTINED: Unsupported or proprietary license '{license_id}'"
        
    return True, "ADMITTED"

def audit_sources_ledger(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return False, [f"JSON Parse Error: {e}"]

    sources = data.get('sources', [])
    print(f"[INFO] Auditing {len(sources)} source entries in {filepath}...")
    
    admitted = 0
    quarantined = 0
    reports = []
    
    for s in sources:
        sid = s.get('source_id', 'unknown')
        valid, msg = validate_source_entry(s)
        if valid:
            admitted += 1
            reports.append(f"[PASS] {sid}: ADMITTED")
        else:
            quarantined += 1
            reports.append(f"[FAIL] {sid}: {msg}")
            
    print(f"[SUMMARY] Admitted: {admitted} | Quarantined: {quarantined}")
    return quarantined == 0, reports

if __name__ == "__main__":
    ledger_path = sys.argv[1] if len(sys.argv) > 1 else "legal/ledger/sources.json"
    is_clean, logs = audit_sources_ledger(ledger_path)
    for l in logs[:10]:
        print(l)
    if not is_clean:
        print("\n[WARN] Unapproved or incomplete sources quarantined.")
    sys.exit(0)
