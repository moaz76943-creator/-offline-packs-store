"""Synthetic, offline, deterministic quality drift regression tests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.quality_drift.engine import (
    compare, digest, is_github_commit_evidence, load_baseline,
    persist_immutable, render_markdown, validate_baseline, validate_thresholds,
)

ROOT = Path(__file__).resolve().parents[2]
DEFS = validate_thresholds(json.loads((ROOT / "tools/quality_drift/thresholds.json").read_text()))
SHA1, SHA2 = "1" * 40, "2" * 40
REPO = "moaz76943-creator/-offline-packs-store"


def baseline(version="1.0.0", sha=SHA1, fixture=False, approval="APPROVED"):
    return {
        "schema_version": "1.0.0", "version": version,
        "repository": REPO, "branch": "main", "head_sha": sha,
        "data_class": "fixture" if fixture else "production",
        "approval": {"status": "PENDING" if fixture else approval,
                     "evidence_url": None if fixture else f"https://github.com/{REPO}/commit/{sha}"},
        "previous_digest": None,
        "source_refs": {"public": {"repository": REPO, "branch": "main", "head_sha": sha}},
        "metrics": {}
    }


def measure(b, name, value, status="PASS"):
    b["metrics"][name] = {
        "status": status, "value": value, "source": "public",
        "evidence_url": f"https://github.com/{REPO}/blob/{b['head_sha']}/tools/release_gate/gate.py",
        "evidence_sha": b["head_sha"], "measurement_method": "synthetic regression test",
        "test_fixture": False
    }
    return b


def pair(a, b):
    b["previous_digest"] = digest(a)
    return a, b


class QualityDriftTests(unittest.TestCase):
    def test_baseline_anchor(self):
        b = measure(baseline(), "word_coverage", 1000)
        self.assertIs(validate_baseline(b, DEFS, expected_head=SHA1), b)

    def test_head_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            validate_baseline(baseline(), DEFS, expected_head=SHA2)

    def test_evidence_sha_mismatch_rejected(self):
        b = measure(baseline(), "word_coverage", 2)
        b["metrics"]["word_coverage"]["evidence_sha"] = SHA2
        with self.assertRaises(ValueError):
            validate_baseline(b, DEFS)

    def test_unpinned_pr_link_rejected(self):
        b = measure(baseline(), "word_coverage", 2)
        b["metrics"]["word_coverage"]["evidence_url"] = f"https://github.com/{REPO}/pull/189"
        with self.assertRaises(ValueError):
            validate_baseline(b, DEFS)

    def test_fake_github_host_rejected(self):
        self.assertFalse(is_github_commit_evidence(f"https://github.com.evil/{REPO}/commit/{SHA1}", REPO, SHA1))

    def test_boolean_count_rejected(self):
        with self.assertRaises(ValueError):
            validate_baseline(measure(baseline(), "word_coverage", True), DEFS)

    def test_unknown_cannot_be_zero(self):
        b = baseline()
        b["metrics"]["word_coverage"] = {"status": "UNKNOWN", "value": 0, "source": "public", "evidence_url": None}
        with self.assertRaises(ValueError):
            validate_baseline(b, DEFS)

    def test_not_run_cannot_be_zero(self):
        b = baseline()
        b["metrics"]["word_coverage"] = {"status": "NOT_RUN", "value": 0, "source": "public", "evidence_url": None}
        with self.assertRaises(ValueError):
            validate_baseline(b, DEFS)

    def test_fixture_not_approved(self):
        with self.assertRaises(ValueError):
            validate_baseline(baseline(fixture=True), DEFS)
        b = baseline(fixture=True)
        b["approval"]["status"] = "APPROVED"
        with self.assertRaises(ValueError):
            validate_baseline(b, DEFS, allow_fixture=True)

    def test_private_id_rejected(self):
        b = baseline()
        b["learner_id"] = "secret"
        with self.assertRaises(ValueError):
            validate_baseline(b, DEFS)

    def test_private_aggregate_requires_sanitized_annotation(self):
        b = baseline()
        b["source_refs"]["consumer"] = {"repository": "example/private", "branch": "stage", "head_sha": SHA2}
        with self.assertRaises(ValueError):
            validate_baseline(b, DEFS)
        b["source_refs"]["consumer"]["sanitized_export"] = True
        self.assertIs(validate_baseline(b, DEFS), b)

    def test_immutable_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            b = baseline()
            self.assertEqual(persist_immutable(b, DEFS, td), persist_immutable(b, DEFS, td))

    def test_immutable_replacement_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            b = baseline()
            p, _ = persist_immutable(b, DEFS, td)
            old = p.read_bytes()
            b2 = copy.deepcopy(b)
            b2["approval"]["status"] = "PENDING"
            with self.assertRaises(FileExistsError):
                persist_immutable(b2, DEFS, td)
            self.assertEqual(p.read_bytes(), old)

    def test_tampered_file_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p, _ = persist_immutable(baseline(), DEFS, td)
            wrapped = json.loads(p.read_text())
            wrapped["baseline"]["head_sha"] = SHA2
            p.write_text(json.dumps(wrapped))
            with self.assertRaises(ValueError):
                load_baseline(p, DEFS)

    def test_word_coverage_drop(self):
        a = measure(baseline(), "word_coverage", 1000)
        b = measure(baseline("1.1", SHA2, approval="PENDING"), "word_coverage", 900)
        pair(a, b)
        r = compare(a, b, DEFS)
        self.assertEqual(r["overall"], "FAIL")
        self.assertEqual(r["changes"]["word_coverage"]["status"], "FAIL")
        self.assertTrue(r["alerts"][0]["evidence_urls"])

    def test_small_variance_within_threshold(self):
        a = measure(baseline(), "word_coverage", 1000)
        b = measure(baseline("1.1", SHA2, approval="PENDING"), "word_coverage", 990)
        pair(a, b)
        self.assertEqual(compare(a, b, DEFS)["changes"]["word_coverage"]["status"], "PASS")

    def test_passed_test_count_decline(self):
        a = measure(baseline(), "test_cases_passed", 28)
        b = measure(baseline("1.1", SHA2, approval="PENDING"), "test_cases_passed", 27)
        pair(a, b)
        self.assertEqual(compare(a, b, DEFS)["changes"]["test_cases_passed"]["status"], "FAIL")

    def test_stable_id_errors(self):
        a = measure(baseline(), "stable_id_errors", 0)
        b = measure(baseline("1.1", SHA2, approval="PENDING"), "stable_id_errors", 1)
        pair(a, b)
        self.assertEqual(compare(a, b, DEFS)["changes"]["stable_id_errors"]["status"], "FAIL")

    def test_memory_increase(self):
        a = measure(baseline(), "memory_peak_bytes", 1000)
        b = measure(baseline("1.1", SHA2, approval="PENDING"), "memory_peak_bytes", 1200)
        pair(a, b)
        self.assertEqual(compare(a, b, DEFS)["changes"]["memory_peak_bytes"]["status"], "FAIL")

    def test_zero_baseline_memory_no_division_by_zero(self):
        a = measure(baseline(), "memory_peak_bytes", 0)
        b = measure(baseline("1.1", SHA2, approval="PENDING"), "memory_peak_bytes", 1)
        pair(a, b)
        self.assertEqual(compare(a, b, DEFS)["changes"]["memory_peak_bytes"]["status"], "FAIL")

    def test_previous_failed_current_passing_is_recovery(self):
        a = measure(baseline(), "sqlite_v2_failures", 1, status="FAIL")
        b = measure(baseline("1.1", SHA2, approval="PENDING"), "sqlite_v2_failures", 0)
        pair(a, b)
        e = compare(a, b, DEFS)["changes"]["sqlite_v2_failures"]
        self.assertEqual(e["status"], "PASS")
        self.assertEqual(e["delta"], -1)

    def test_current_failed_gate_still_alerts(self):
        a = measure(baseline(), "fts5_failures", 3)
        b = measure(baseline("1.1", SHA2, approval="PENDING"), "fts5_failures", 1, status="FAIL")
        pair(a, b)
        self.assertEqual(compare(a, b, DEFS)["changes"]["fts5_failures"]["status"], "FAIL")

    def test_wrong_previous_digest_stale(self):
        a = baseline()
        b = baseline("1.1", SHA2, approval="PENDING")
        b["previous_digest"] = "a" * 64
        self.assertEqual(compare(a, b, DEFS)["overall"], "STALE")

    def test_unapproved_predecessor_unknown(self):
        a = baseline(approval="PENDING")
        b = baseline("1.1", SHA2, approval="PENDING")
        pair(a, b)
        self.assertEqual(compare(a, b, DEFS)["overall"], "UNKNOWN")

    def test_not_run_does_not_become_pass(self):
        a = measure(baseline(), "cefr_coverage", 100)
        b = baseline("1.1", SHA2, approval="PENDING")
        b["metrics"]["cefr_coverage"] = {"status": "NOT_RUN", "value": None,
                                         "source": "public", "evidence_url": None}
        pair(a, b)
        e = compare(a, b, DEFS)["changes"]["cefr_coverage"]
        self.assertEqual(e["status"], "NOT_RUN")
        self.assertIsNone(e["delta"])

    def test_missing_metric_unknown(self):
        a = baseline()
        b = baseline("1.1", SHA2, approval="PENDING")
        pair(a, b)
        self.assertEqual(compare(a, b, DEFS)["overall"], "UNKNOWN")

    def test_arabic_markdown_no_score(self):
        a = measure(baseline(), "offline_startup_failures", 0)
        b = measure(baseline("1.1", SHA2, approval="PENDING"), "offline_startup_failures", 1)
        pair(a, b)
        report = compare(a, b, DEFS)
        self.assertIn("تقرير تغير الجودة", render_markdown(report))
        self.assertIn("github.com", render_markdown(report))
        self.assertIsNone(report["quality_score_10"])

    def test_negative_threshold_rejected(self):
        with self.assertRaises(ValueError):
            validate_thresholds({"schema_version": "1.0.0", "metrics": {
                "memory_peak_bytes": {"direction": "lower", "unit": "bytes", "relative_increase_pct": -1}}})


if __name__ == "__main__":
    unittest.main()
