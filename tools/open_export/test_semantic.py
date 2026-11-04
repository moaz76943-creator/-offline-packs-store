import unittest
import os
import shutil
import tempfile
import json
from pathlib import Path
from tools.open_export.exporter import CommunityExporter, ExportError

class TestSemanticIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "source"
        self.src.mkdir()
        self.out = self.tmp / "output"
        self.out.mkdir()
        self.review = self.tmp / "review"
        self.review.mkdir()

        self.repo = self.tmp / "repo"
        (self.repo / "legal/ledger").mkdir(parents=True)
        (self.repo / "catalog").mkdir(parents=True)

        with (self.repo / "legal/ledger/sources.json").open("w") as f:
            json.dump({"sources": [{
                "source_id": "sem_source",
                "status": "APPROVED_FOR_REDISTRIBUTION",
                "retrieval": {"sha256": "fake_source_sha256"},
                "dataset_version": "v1",
                "publisher": "test",
                "origin_url": "test",
                "license": {"id": "CC0-1.0", "evidence_url": "test"},
                "kind": "vector_art"
            }]}, f)

        with (self.repo / "catalog/content_readiness.v1.json").open("w") as f:
            json.dump({"schema_version": "1.0.0", "states": {"en": {}}}, f)

        class MockMachine:
            def verify_handoff(self, sub_id):
                if sub_id == "sub1":
                    return {
                        "content_hash": self.token_sha,
                        "artifact": "item.bin",
                        "metadata": {
                            "language": "en",
                            "source_id": "sem_source",
                            "license_id": "CC0-1.0",
                            "dataset_version": "v1",
                            "source_artifact_sha256": "fake_source_sha256",
                            "publisher": "test",
                            "origin_url": "test",
                            "record_locator": "loc"
                        }
                    }
                raise KeyError(sub_id)
        self.machine = MockMachine()

        from tools.visual_lexicon.core import encode_token
        import hashlib
        token = {
            "concept_id": "test-concept",
            "version": 1,
            "viewBox": [0, 0, 24, 24],
            "paths": ["M0,0 L24,24"],
            "palette": ["#000", "#FFF"],
            "semantic_label": "test label"
        }
        self.token_bytes, _ = encode_token(token)
        self.machine.token_sha = hashlib.sha256(self.token_bytes).hexdigest()
        self.token_sha = self.machine.token_sha

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_semantic_export(self):
        with (self.src / "item.bin").open("wb") as f:
            f.write(self.token_bytes)

        with (self.src / "manifest.json").open("w") as f:
            json.dump({"items": [{
                "id": "sem1",
                "type": "semantic",
                "filename": "item.bin",
                "sha256": self.token_sha,
                "submission_id": "sub1",
                "source_id": "sem_source",
                "source_version": "v1",
                "license": "CC0-1.0"
            }]}, f)


        from unittest.mock import patch

        with patch('legal.ledger.admission.evaluate', return_value=[]):
            exporter = CommunityExporter(str(self.src), str(self.out), self.machine, repository_root=str(self.repo))
            res = exporter.run()
            self.assertTrue(res["items"] == 1)
