#!/usr/bin/env python3
"""
CEFR Evidence Validator - Master Constitution Section 07 & 09 Compliant.
Guarantees strict CEFR level verification (A1-C2) and enforces
path sandboxing to prevent path traversal or user file corruption.
"""
import json
import os
import sys

VALID_CEFR_LEVELS = {'A1', 'A2', 'B1', 'B2', 'C1', 'C2'}
VALID_SKILLS = {'vocabulary', 'grammar', 'reading', 'listening', 'speaking', 'writing'}

def resolve_safe_evidence_path(base_dir: str, rel_path: str) -> str:
    """Guarantees target file path resolves strictly within the authorized base sandbox."""
    abs_base = os.path.abspath(base_dir)
    target = os.path.abspath(os.path.join(abs_base, rel_path))
    if not (target.startswith(abs_base + os.sep) or target == abs_base):
        raise ValueError(f"SECURITY_VIOLATION: Path traversal detected outside sandbox: '{rel_path}'")
    return target

def validate_cefr_record(record: dict) -> tuple:
    level = str(record.get('level', '')).strip().upper()
    skill = str(record.get('skill', '')).strip().lower()
    term = str(record.get('term', '')).strip()

    if level not in VALID_CEFR_LEVELS:
        return False, f"INVALID_CEFR_LEVEL: '{level}' (Allowed: {sorted(VALID_CEFR_LEVELS)})"
    if skill not in VALID_SKILLS:
        return False, f"INVALID_SKILL: '{skill}' (Allowed: {sorted(VALID_SKILLS)})"
    if not term:
        return False, "EMPTY_TERM: CEFR record must specify target lemma/term"

    return True, "CEFR_RECORD_VALID"

def run_cefr_audit(base_dir: str, input_file_rel: str, output_file_rel: str):
    safe_input = resolve_safe_evidence_path(base_dir, input_file_rel)
    safe_output = resolve_safe_evidence_path(base_dir, output_file_rel)

    if not os.path.isfile(safe_input):
        return False, f"INPUT_FILE_NOT_FOUND: {safe_input}"

    with open(safe_input, 'r', encoding='utf-8') as f:
        data = json.load(f)

    records = data.get('records', [])
    valid_records = []
    quarantined = []

    for r in records:
        ok, msg = validate_cefr_record(r)
        if ok:
            valid_records.append(r)
        else:
            quarantined.append((r, msg))

    # Do not overwrite or corrupt output if zero valid records found
    if not valid_records:
        return False, f"AUDIT_FAILED: 0 valid CEFR records. {len(quarantined)} quarantined."

    os.makedirs(os.path.dirname(safe_output), exist_ok=True)
    with open(safe_output, 'w', encoding='utf-8') as f:
        json.dump({
            'schema': 'cefr_evidence_v2',
            'validated_count': len(valid_records),
            'records': valid_records
        }, f, indent=2, ensure_ascii=False)

    return True, f"AUDIT_SUCCESS: {len(valid_records)} verified records saved to {safe_output}."

if __name__ == "__main__":
    b_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    in_rel = sys.argv[2] if len(sys.argv) > 2 else "evidence/sample_cefr_input.json"
    out_rel = sys.argv[3] if len(sys.argv) > 3 else "evidence/cefr_evidence_validated.json"
    
    try:
        ok, msg = run_cefr_audit(b_dir, in_rel, out_rel)
        print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
        sys.exit(0 if ok else 1)
    except Exception as e:
        print(f"[SECURITY_ERROR] {e}")
        sys.exit(1)
