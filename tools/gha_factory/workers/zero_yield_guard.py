#!/usr/bin/env python3
"""
Zero-Yield Guard for Content Factory Workers.
Master Constitution Section 15 Compliant:
'Success with zero useful work is prohibited. Actual claimed work must yield actual output.'
Fails closed if a worker completes with 0 generated records.
"""
import json
import os
import sys

def validate_worker_output(output_path: str, min_expected_entries: int = 1):
    if not os.path.exists(output_path):
        return False, f"ZERO_YIELD_ERROR: Output file '{output_path}' was not generated."
        
    size = os.path.getsize(output_path)
    if size == 0:
        return False, f"ZERO_YIELD_ERROR: Output file '{output_path}' is zero bytes."

    # Inspect JSON output format
    if output_path.endswith('.json'):
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            entries = []
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict):
                entries = data.get('entries', data.get('records', data.get('lexicon', [])))
                
            count = len(entries)
            if count < min_expected_entries:
                return False, f"ZERO_YIELD_ERROR: Worker produced {count} entries (minimum required: {min_expected_entries})."
                
            return True, f"YIELD_VERIFIED: {count} valid entries generated ({size} bytes)."
        except Exception as e:
            return False, f"ZERO_YIELD_PARSE_ERROR: {e}"

    return True, f"YIELD_VERIFIED: File size {size} bytes."

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: zero_yield_guard.py <output_file_path> [min_expected_entries]")
        sys.exit(1)

    path = sys.argv[1]
    min_count = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    passed, message = validate_worker_output(path, min_count)
    print(f"[{'PASS' if passed else 'FAIL'}] {message}")
    sys.exit(0 if passed else 1)
