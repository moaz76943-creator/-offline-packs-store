import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import sys
import subprocess

class TestAttributionGenerator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.ledger_path = self.temp_path / "sources.json"
        self.refs_path = self.temp_path / "refs.json"
        self.out_dir = self.temp_path / "out"

        self.valid_source = {
            "source_id": "source1",
            "kind": "dictionary",
            "origin_url": "https://example.com/source1",
            "publisher": "Author One",
            "dataset_version": "1.0",
            "retrieval": {
                "identity": "id1",
                "url": "https://example.com/source1.zip",
                "date": "2023-01-01",
                "artifact_path": "path1",
                "sha256": "a" * 64
            },
            "license": {
                "id": "CC-BY-SA-4.0",
                "evidence_url": "https://example.com/license",
                "evidence_path": "path",
                "evidence_sha256": "b" * 64
            },
            "status": "APPROVED_FOR_REDISTRIBUTION",
            "alterations": ["none"],
            "review": {
                "reviewer": "me",
                "decision_url": "https://example.com/decision"
            }
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_ledger(self, sources):
        with open(self.ledger_path, "w", encoding="utf-8") as f:
            json.dump({"schema_version": "1.0.0", "sources": sources}, f)

    def write_refs(self, refs):
        with open(self.refs_path, "w", encoding="utf-8") as f:
            json.dump(refs, f)

    def run_generator(self, ledger_path, refs_path, out_dir):
        cmd = [
            sys.executable,
            "-m", "tools.attribution.generator",
            "--ledger", str(ledger_path),
            "--refs", str(refs_path),
            "--out-dir", str(out_dir)
        ]
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_missing_authors(self):
        source_missing_author = dict(self.valid_source)
        source_missing_author["publisher"] = ""
        self.write_ledger([source_missing_author])

        refs = [{
            "source_id": "source1",
            "dataset_version": "1.0",
            "artifact_sha256": "a" * 64
        }]
        self.write_refs(refs)

        result = self.run_generator(self.ledger_path, self.refs_path, self.out_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing publisher", result.stderr)

    def test_changed_source_versions(self):
        self.write_ledger([self.valid_source])

        refs = [{
            "source_id": "source1",
            "dataset_version": "1.1",
            "artifact_sha256": "a" * 64
        }]
        self.write_refs(refs)

        result = self.run_generator(self.ledger_path, self.refs_path, self.out_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed source version", result.stderr)

    def test_conflicting_hash(self):
        self.write_ledger([self.valid_source])

        refs = [{
            "source_id": "source1",
            "dataset_version": "1.0",
            "artifact_sha256": "c" * 64
        }]
        self.write_refs(refs)

        result = self.run_generator(self.ledger_path, self.refs_path, self.out_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("conflicting artifact hash", result.stderr)

    def test_combined_source_packages(self):
        source2 = dict(self.valid_source)
        source2["source_id"] = "source2"
        source2["publisher"] = "Author Two"
        source2["retrieval"] = dict(source2["retrieval"])
        source2["retrieval"]["sha256"] = "c" * 64

        self.write_ledger([self.valid_source, source2])

        refs = [
            {
                "source_id": "source1",
                "dataset_version": "1.0",
                "artifact_sha256": "a" * 64
            },
            {
                "source_id": "source2",
                "dataset_version": "1.0",
                "artifact_sha256": "c" * 64
            }
        ]
        self.write_refs(refs)

        result = self.run_generator(self.ledger_path, self.refs_path, self.out_dir)
        self.assertEqual(result.returncode, 0, result.stderr)

        # Check files
        notice1 = self.out_dir / "source1_notice.txt"
        notice2 = self.out_dir / "source2_notice.txt"
        attribution = self.out_dir / "attribution.json"

        self.assertTrue(notice1.exists())
        self.assertTrue(notice2.exists())
        self.assertTrue(attribution.exists())

        with open(attribution, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["source_id"], "source1")
            self.assertEqual(data[1]["source_id"], "source2")

    def test_invalid_notices_missing_url(self):
        source_missing_url = dict(self.valid_source)
        source_missing_url["origin_url"] = ""
        self.write_ledger([source_missing_url])

        refs = [{
            "source_id": "source1",
            "dataset_version": "1.0",
            "artifact_sha256": "a" * 64
        }]
        self.write_refs(refs)

        result = self.run_generator(self.ledger_path, self.refs_path, self.out_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing origin_url", result.stderr)

    def test_invalid_notices_missing_license(self):
        source_missing_license = dict(self.valid_source)
        source_missing_license["license"] = {}
        self.write_ledger([source_missing_license])

        refs = [{
            "source_id": "source1",
            "dataset_version": "1.0",
            "artifact_sha256": "a" * 64
        }]
        self.write_refs(refs)

        result = self.run_generator(self.ledger_path, self.refs_path, self.out_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing license", result.stderr)

    def test_invalid_notices_unknown_source(self):
        self.write_ledger([self.valid_source])

        refs = [{
            "source_id": "unknown_source",
            "dataset_version": "1.0",
            "artifact_sha256": "a" * 64
        }]
        self.write_refs(refs)

        result = self.run_generator(self.ledger_path, self.refs_path, self.out_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found in ledger", result.stderr)

    def test_repeated_generation_is_stable(self):
        source2 = dict(self.valid_source)
        source2["source_id"] = "source2"
        source2["retrieval"] = dict(source2["retrieval"])
        source2["retrieval"]["sha256"] = "c" * 64

        self.write_ledger([source2, self.valid_source])

        refs = [
            {
                "source_id": "source2",
                "dataset_version": "1.0",
                "artifact_sha256": "c" * 64
            },
            {
                "source_id": "source1",
                "dataset_version": "1.0",
                "artifact_sha256": "a" * 64
            }
        ]
        self.write_refs(refs)

        self.run_generator(self.ledger_path, self.refs_path, self.out_dir)
        with open(self.out_dir / "attribution.json", "r", encoding="utf-8") as f:
            content1 = f.read()

        self.run_generator(self.ledger_path, self.refs_path, self.out_dir)
        with open(self.out_dir / "attribution.json", "r", encoding="utf-8") as f:
            content2 = f.read()

        self.assertEqual(content1, content2)

    def test_modifications(self):
        source = dict(self.valid_source)
        source["alterations"] = ["fixed typos", "normalized text"]
        self.write_ledger([source])

        refs = [{
            "source_id": "source1",
            "dataset_version": "1.0",
            "artifact_sha256": "a" * 64
        }]
        self.write_refs(refs)

        result = self.run_generator(self.ledger_path, self.refs_path, self.out_dir)
        self.assertEqual(result.returncode, 0)

        notice_path = self.out_dir / "source1_notice.txt"
        with open(notice_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("Modifications:", content)
            self.assertIn("- fixed typos", content)
            self.assertIn("- normalized text", content)

    def test_public_domain_proof(self):
        source = dict(self.valid_source)
        source["license"] = {
            "id": "PUBLIC-DOMAIN",
            "evidence_url": "https://example.com",
            "evidence_path": "path",
            "evidence_sha256": "b" * 64,
            "public_domain_proof": {
                "jurisdiction": "US",
                "legal_basis": "Expired copyright",
                "work_date": "1920"
            }
        }
        self.write_ledger([source])

        refs = [{
            "source_id": "source1",
            "dataset_version": "1.0",
            "artifact_sha256": "a" * 64
        }]
        self.write_refs(refs)

        result = self.run_generator(self.ledger_path, self.refs_path, self.out_dir)
        self.assertEqual(result.returncode, 0)

        notice_path = self.out_dir / "source1_notice.txt"
        with open(notice_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("Public Domain Proof:", content)
            self.assertIn("Jurisdiction: US", content)
            self.assertIn("Legal Basis: Expired copyright", content)
            self.assertIn("Work Date: 1920", content)

if __name__ == "__main__":
    unittest.main()
