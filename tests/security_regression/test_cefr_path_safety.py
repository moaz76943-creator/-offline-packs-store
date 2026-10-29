#!/usr/bin/env python3
"""Regression test for CEFR evidence CLI path traversal protection."""
import os
import unittest

def is_safe_evidence_path(base_dir: str, target_path: str) -> bool:
    """Verifies that target_path resolves strictly within base_dir (prevents Zip Slip / traversal)."""
    abs_base = os.path.abspath(base_dir)
    abs_target = os.path.abspath(os.path.join(base_dir, target_path))
    return abs_target.startswith(abs_base + os.sep) or abs_target == abs_base

class TestCefrPathSafety(unittest.TestCase):
    def test_safe_paths(self):
        self.assertTrue(is_safe_evidence_path("/tmp/polyglot", "evidence/cefr_a1.json"))
        self.assertTrue(is_safe_evidence_path("/tmp/polyglot", "packs/de_ar/manifest.json"))

    def test_path_traversal_attempts_blocked(self):
        self.assertFalse(is_safe_evidence_path("/tmp/polyglot", "../../../etc/passwd"))
        self.assertFalse(is_safe_evidence_path("/tmp/polyglot", "evidence/../../sensitive.key"))
        self.assertFalse(is_safe_evidence_path("/tmp/polyglot", "/etc/shadow"))

if __name__ == "__main__":
    unittest.main()
