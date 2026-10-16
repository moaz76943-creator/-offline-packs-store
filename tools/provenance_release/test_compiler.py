import unittest
import json
import tempfile
from pathlib import Path
from tools.provenance_release.compiler import compile_provenance

class TestProvenanceCompiler(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

        self.ledger_path = self.root / "sources.json"
        self.manifest_path = self.root / "manifest.json"
        self.daily_dir = self.root / "daily"
        self.daily_dir.mkdir()

        self.output_manifest = self.root / "release_provenance.json"
        self.output_notice = self.root / "NOTICE.txt"

        self.valid_hash = "ed7002b439e9ac845f22357d822bac1444730fbdb6016d3ec9432297b9ec9f73"
        self.create_artifact("dummy.txt", b"content")
        self.create_artifact("packs/test.pack", b"content")

        # Valid notice content for src1
        self.notice_content = b"src1 Pub CC0-1.0 https://example.com"
        self.create_artifact("notice.txt", self.notice_content)

    def tearDown(self):
        self.tmpdir.cleanup()

    def create_artifact(self, path_str, content):
        p = self.root / path_str
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def get_output(self):
        return json.loads(self.output_manifest.read_text())

    def create_valid_ledger(self, overrides=None):
        src = {
            "source_id": "src1",
            "kind": "dictionary",
            "origin_url": "https://example.com",
            "publisher": "Pub",
            "dataset_version": "v1",
            "status": "APPROVED_FOR_REDISTRIBUTION",
            "alterations": ["none"],
            "retrieval": {
                "identity": "id",
                "url": "https://example.com/file",
                "date": "2023-01-01",
                "artifact_path": "dummy.txt",
                "sha256": self.valid_hash
            },
            "license": {
                "id": "CC0-1.0",
                "evidence_url": "https://example.com/license",
                "evidence_path": "dummy.txt",
                "evidence_sha256": self.valid_hash
            },
            "review": {
                "reviewer": "test",
                "decision_url": "https://example.com/decision"
            }
        }
        if overrides:
            src.update(overrides)
        return {
            "schema_version": "1.0.0",
            "sources": [src]
        }

    def create_valid_manifest(self):
        return {
            "schema_version": "1.0.0",
            "languages": [],
            "packs": [{
                "file": "packs/test.pack"
            }]
        }

    def create_valid_daily(self, overrides=None):
        cand = {
            "asset_id": "cand1",
            "kind": "dictionary",
            "artifact_path": "packs/test.pack",
            "sha256": self.valid_hash,
            "source_refs": [{
                "source_id": "src1",
                "dataset_version": "v1",
                "artifact_sha256": self.valid_hash
            }],
            "output_license_id": "CC0-1.0",
            "compiler_license_id": "CC0-1.0",
            "notices": {
                "src1": "notice.txt"
            },
            "compliance": {},
            "provenance_mode": "source_set",
            "record_provenance_reason": "test",
            "review": {
                "reviewer": "test",
                "decision_url": "https://example.com/decision"
            }
        }
        if overrides:
            cand.update(overrides)
        return {
            "schema_version": "1.0.0",
            "date": "2023-01-01",
            "release_candidates": [cand]
        }

    def test_missing_authors(self):
        ledger = self.create_valid_ledger({"publisher": ""})
        self.ledger_path.write_text(json.dumps(ledger))
        self.manifest_path.write_text(json.dumps(self.create_valid_manifest()))
        (self.daily_dir / "1.json").write_text(json.dumps(self.create_valid_daily()))

        res = compile_provenance(self.root, self.ledger_path, self.manifest_path, self.daily_dir, self.output_manifest, self.output_notice)
        self.assertEqual(res, 1)
        self.assertNotIn("cand1", self.get_output()["artifacts"])

    def test_mixed_licensing(self):
        ledger = self.create_valid_ledger()
        ledger["sources"][0]["license"]["id"] = "CC-BY-SA-4.0"
        self.ledger_path.write_text(json.dumps(ledger))
        self.manifest_path.write_text(json.dumps(self.create_valid_manifest()))

        daily = self.create_valid_daily({"output_license_id": "PUBLIC-DOMAIN"})
        (self.daily_dir / "1.json").write_text(json.dumps(daily))

        res = compile_provenance(self.root, self.ledger_path, self.manifest_path, self.daily_dir, self.output_manifest, self.output_notice)
        self.assertEqual(res, 1)
        self.assertNotIn("cand1", self.get_output()["artifacts"])

    def test_altered_files_invalid_hash(self):
        ledger = self.create_valid_ledger()
        ledger["sources"][0]["retrieval"]["sha256"] = "0" * 64
        self.ledger_path.write_text(json.dumps(ledger))
        self.manifest_path.write_text(json.dumps(self.create_valid_manifest()))
        (self.daily_dir / "1.json").write_text(json.dumps(self.create_valid_daily()))

        res = compile_provenance(self.root, self.ledger_path, self.manifest_path, self.daily_dir, self.output_manifest, self.output_notice)
        self.assertEqual(res, 1)
        self.assertNotIn("cand1", self.get_output()["artifacts"])

    def test_duplicate_provenance(self):
        self.ledger_path.write_text(json.dumps(self.create_valid_ledger()))
        self.manifest_path.write_text(json.dumps(self.create_valid_manifest()))

        daily1 = self.create_valid_daily()
        daily2 = self.create_valid_daily() # duplicate cand1
        (self.daily_dir / "1.json").write_text(json.dumps(daily1))
        (self.daily_dir / "2.json").write_text(json.dumps(daily2))

        res = compile_provenance(self.root, self.ledger_path, self.manifest_path, self.daily_dir, self.output_manifest, self.output_notice)
        self.assertEqual(res, 1) # Global evaluate finds duplicate cand1
        self.assertNotIn("cand1", self.get_output()["artifacts"])

    def test_blocked_license(self):
        ledger = self.create_valid_ledger({"status": "BLOCKED_LICENSE"})
        self.ledger_path.write_text(json.dumps(ledger))
        self.manifest_path.write_text(json.dumps(self.create_valid_manifest()))
        (self.daily_dir / "1.json").write_text(json.dumps(self.create_valid_daily()))

        res = compile_provenance(self.root, self.ledger_path, self.manifest_path, self.daily_dir, self.output_manifest, self.output_notice)
        self.assertEqual(res, 1)
        self.assertNotIn("cand1", self.get_output()["artifacts"])

    def test_review_required(self):
        ledger = self.create_valid_ledger({"status": "REVIEW_REQUIRED"})
        self.ledger_path.write_text(json.dumps(ledger))
        self.manifest_path.write_text(json.dumps(self.create_valid_manifest()))
        (self.daily_dir / "1.json").write_text(json.dumps(self.create_valid_daily()))

        res = compile_provenance(self.root, self.ledger_path, self.manifest_path, self.daily_dir, self.output_manifest, self.output_notice)
        self.assertEqual(res, 1)
        self.assertNotIn("cand1", self.get_output()["artifacts"])

    def test_success(self):
        self.ledger_path.write_text(json.dumps(self.create_valid_ledger()))
        self.manifest_path.write_text(json.dumps(self.create_valid_manifest()))
        (self.daily_dir / "1.json").write_text(json.dumps(self.create_valid_daily()))

        res = compile_provenance(self.root, self.ledger_path, self.manifest_path, self.daily_dir, self.output_manifest, self.output_notice)
        self.assertEqual(res, 0)

        out_man = json.loads(self.output_manifest.read_text())
        self.assertEqual(out_man["schema_version"], "1.0.0")
        self.assertIn("cand1", out_man["artifacts"])
        self.assertEqual(out_man["artifacts"]["cand1"]["output_license"], "CC0-1.0")
        self.assertEqual(out_man["artifacts"]["cand1"]["sources"][0]["status"], "APPROVED_FOR_REDISTRIBUTION")

        notice = self.output_notice.read_text()
        self.assertIn("Machine validation does not constitute a legal opinion.", notice)
        self.assertIn("Artifact: cand1", notice)
        self.assertIn(self.notice_content.decode('utf-8'), notice)

if __name__ == '__main__':
    unittest.main()
