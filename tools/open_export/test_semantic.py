import unittest
import sys
import os
import json
import base64
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from tools.open_export.exporter import CommunityExporter
from tools.open_export.test_lifecycle import SecurityRegression

class TestSemanticExport(SecurityRegression):
    def manifest(self, filename, sha, sid="item1", item_type="lexical"):
        (self.src / "manifest.json").write_text(json.dumps({"items": [{
            "id": sid, "type": item_type, "filename": filename, "sha256": sha,
            "submission_id": sid, "source_id": "src-test", "license": "CC0-1.0",
            "source_version": "1.0"}]}))

    def test_export_semantic_token(self):
        content = b'x\x9cM\xcdA\x0f\x82 \x14\xc0\xf1\xaf\xc2\xe8j\x8a\xce\x93\xb7\xea\xd2\xa5[7\xe7\x18\xd1[\xb2!8x\x9a\xd5\xfa\xee\x01\xd6\x16\x83\x03\xff\xdf\xe0\xbd\xe8\x0c\xce+khC\xca\x8cPi\x8d\x84\x11\xb9\xba\x86@\x11<\xf2o\xa2A\xc5\x84\xbduQ\xceA\xc8n\xbd\x06\xf0vr\x12"\xf4\x88cS\x14\xf1e.\xed\x10Q+\t\xc6\'=\x1c\xd8\xb6\xccYz\x02\x830\xa8$\xd7\xe2\x02\xfa7-M\xd1\xc8\x11\x16\xfco\xb3\x82\xfb\xde.!\xb5,#aWu<]\xa0Qh@\x8c\xdf\xb7t\xc3\xd2\xa2k\xc7\xde\xa7zb\x84\xf5U=W\xf5\x91=\x93\xdd\xc0\x0e\x80\xee\x11\xb9{\x7f\x00\x83\xbcM\xf9'
        name, sha = self.stage(content=content)
        self.certify()
        self.meta["kind"] = "vector_art"
        (self.root / "claimed.json").write_text(json.dumps(self.meta))

        self.manifest(name, sha, item_type="semantic")

        def mock_evaluate(ledger, *args):
            for s in ledger["sources"]:
                if s.get("source_id") == "src-test":
                    s["kind"] = "vector_art"
            return []

        with patch.dict(sys.modules, {"legal.ledger.admission": SimpleNamespace(evaluate=mock_evaluate)}):
            exporter = CommunityExporter(self.src, self.out, self.machine, repository_root=self.root)
            result = exporter.run()
            self.assertTrue(result["release"])
