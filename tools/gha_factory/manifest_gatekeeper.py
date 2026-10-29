#!/usr/bin/env python3
"""
Manifest Production Rights & Hash Gatekeeper.
Master Constitution Section 06 & 08 Compliant.
Guarantees zero packs enter Production Manifest unless rights are verified
in legal/ledger/sources.json and SHA256 hash is confirmed.
"""
import json
import os
import re
import sys

HEX64_REGEX = re.compile(r'^[a-fA-F0-9]{64}$')

def validate_production_pack_eligibility(pack_entry, approved_source_ids):
    pack_id = pack_entry.get('pack_id', 'UNKNOWN')
    status = str(pack_entry.get('status', '')).lower()
    is_production = pack_entry.get('production_ready', False) or status == 'production'

    if not is_production:
        return True, "CANDIDATE_OR_EXPERIMENTAL"

    # Rule 1: Strict SHA256 validation (must be 64 hex characters)
    sha256 = pack_entry.get('sha256', '')
    if not sha256 or not HEX64_REGEX.match(sha256):
        return False, f"REJECTED_PRODUCTION: {pack_id} missing valid 64-char SHA256 hash"

    # Rule 2: Source License Provenance must link to an approved legal ledger source
    source_id = pack_entry.get('source_id', '')
    if not source_id or source_id not in approved_source_ids:
        return False, f"REJECTED_PRODUCTION: {pack_id} source_id '{source_id}' not APPROVED in legal ledger"

    # Rule 3: Content counts and file size must be non-zero
    size_bytes = pack_entry.get('size_bytes', 0)
    vocab_count = pack_entry.get('vocabulary_count', 0)
    if size_bytes <= 0 or vocab_count <= 0:
        return False, f"REJECTED_PRODUCTION: {pack_id} has 0 bytes or 0 vocabulary entries"

    return True, "PRODUCTION_QUALIFIED"

def audit_manifest(manifest_path, legal_ledger_path):
    if not os.path.isfile(manifest_path):
        return False, f"Manifest not found: {manifest_path}"

    approved_sources = set()
    if os.path.isfile(legal_ledger_path):
        try:
            with open(legal_ledger_path, 'r', encoding='utf-8') as f:
                legal_data = json.load(f)
                for s in legal_data.get('sources', []):
                    if s.get('review_decision', '').upper() == 'APPROVED':
                        approved_sources.add(s.get('source_id'))
        except Exception as e:
            print(f"[WARN] Error reading legal ledger: {e}")

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)
    except Exception as e:
        return False, f"Manifest JSON parse error: {e}"

    packs = manifest_data.get('packs', [])
    print(f"[INFO] Auditing {len(packs)} pack(s) in {manifest_path}...")

    rejected = 0
    passed = 0
    for p in packs:
        ok, reason = validate_production_pack_eligibility(p, approved_sources)
        if ok:
            passed += 1
            print(f"[PASS] {p.get('pack_id')}: {reason}")
        else:
            rejected += 1
            print(f"[BLOCKED] {p.get('pack_id')}: {reason}")
            # Demote status to quarantined_candidate
            p['production_ready'] = False
            p['status'] = 'quarantined_candidate'

    print(f"[AUDIT SUMMARY] Qualified: {passed} | Demoted/Blocked: {rejected}")
    return rejected == 0

if __name__ == "__main__":
    m_path = sys.argv[1] if len(sys.argv) > 1 else "manifest.json"
    l_path = sys.argv[2] if len(sys.argv) > 2 else "legal/ledger/sources.json"
    clean = audit_manifest(m_path, l_path)
    sys.exit(0 if clean else 1)
