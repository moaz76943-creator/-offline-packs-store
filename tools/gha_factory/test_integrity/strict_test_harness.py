#!/usr/bin/env python3
"""
Strict Test Integrity Harness - Master Constitution Section 15 Compliant:
'Success with zero useful work is prohibited. SKIPPED != PASS.'
Guarantees test suites execute non-zero assertions, validates fixtures
for genuine schema structure, and eliminates false-pass assertions.
"""
import json
import os
import sys

def validate_test_fixture(fixture_path: str) -> tuple:
    if not os.path.isfile(fixture_path):
        return False, f"FIXTURE_NOT_FOUND: {fixture_path}"

    size = os.path.getsize(fixture_path)
    if size == 0:
        return False, f"EMPTY_FIXTURE: File '{fixture_path}' is zero bytes"

    try:
        with open(fixture_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Reject truthy-but-malformed JSON before reporting a valid fixture.
        if not isinstance(data, dict):
            return False, "FALSE_FIXTURE: Fixture root must be an object"
        vocab = data.get('vocabulary', data.get('entries', []))
        if not isinstance(vocab, list) or not vocab:
            return False, "FALSE_FIXTURE: Fixture must contain a nonempty vocabulary list"

        for index, entry in enumerate(vocab):
            if not isinstance(entry, dict):
                return False, f"MALFORMED_ENTRY: Entry {index} must be an object"
            lemma = entry.get('lemma')
            translations = entry.get('translations')
            if not isinstance(lemma, str) or not lemma.strip():
                return False, f"MALFORMED_ENTRY: Entry {index} requires a nonblank string lemma"
            if (not isinstance(translations, list) or not translations or
                    any(not isinstance(item, str) or not item.strip() for item in translations)):
                return False, f"MALFORMED_ENTRY: Entry {index} requires nonblank string translations"

        return True, f"FIXTURE_VALID: {len(vocab)} genuine entries verified."
    except Exception as e:
        return False, f"FIXTURE_PARSE_ERROR: {e}"

def assert_non_empty_results(results: list, test_name: str):
    """Enforces that an evaluated test result collection is non-empty before passing."""
    if not results:
        raise AssertionError(f"FALSE_PASS_DETECTED: Test '{test_name}' evaluated an empty collection without assertions.")
    return True

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/canonical_de_ar_fixture.json"
    ok, msg = validate_test_fixture(path)
    print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
    sys.exit(0 if ok else 1)
