"""Closing a queue issue requires the exact verified SUCCEEDED receipt.

An issue is durable history and is never deleted; completed partitions remain
deduped when an auto-seeder inventories both open and closed issues.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_engine import FakeAPI
from test_protocol import NOW, task
from tools.gha_factory.orchestration import api as gh_api, engine, protocol


class VerifiedQueueClosureTests(unittest.TestCase):
    def _claim(self):
        fake = FakeAPI([(1, task())])
        ctx = {"languages": {"de", "ar"}, "sources": [], "admissions": {}}
        with patch.object(engine, "source_gate", return_value="READY"):
            matrix = engine.control(fake, 1, 1, NOW, Path("."), ctx, "a" * 64)
        self.assertEqual([row["number"] for row in matrix], [1])
        return fake, matrix

    def test_valid_success_receipt_closes_issue_and_preserves_body(self):
        fake, matrix = self._claim()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "dispatcher-1"
            folder.mkdir()
            current = protocol.parse(fake.one(1)["body"])
            (folder / "receipt.json").write_text(
                json.dumps(protocol.receipt(current, "SUCCEEDED", 1, 0, None, None)),
                encoding="utf-8",
            )
            result = engine.finalize(fake, matrix, Path(tmp), 1, 1, NOW)
        self.assertEqual(result[0]["state"], "SUCCEEDED")
        self.assertEqual(fake.one(1)["state"], "closed")
        self.assertEqual(protocol.parse(fake.one(1)["body"])["state"], "SUCCEEDED")

    def test_missing_receipt_keeps_retry_issue_open(self):
        fake, matrix = self._claim()
        with tempfile.TemporaryDirectory() as tmp:
            result = engine.finalize(fake, matrix, Path(tmp), 1, 1, NOW)
        self.assertNotEqual(result[0]["state"], "SUCCEEDED")
        self.assertNotEqual(fake.one(1).get("state"), "closed")

    def test_invalid_receipt_cannot_close_issue(self):
        fake, matrix = self._claim()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "dispatcher-1"
            folder.mkdir()
            (folder / "receipt.json").write_text("{}")
            with self.assertRaises(ValueError):
                engine.finalize(fake, matrix, Path(tmp), 1, 1, NOW)
        self.assertNotEqual(fake.one(1).get("state"), "closed")

    def test_api_rejects_non_success_closure(self):
        client = gh_api.GitHub(token="test-only")
        client.request = lambda path, body=None, method="GET": (path, body, method)
        with self.assertRaises(ValueError):
            client.update(7, task(state="READY"), close_verified=True)

    def test_api_closes_success_with_one_atomic_patch(self):
        fake, matrix = self._claim()
        current = protocol.parse(fake.one(1)["body"])
        verified = protocol.finish(
            current, protocol.receipt(current, "SUCCEEDED", 1, 0, None, None), NOW
        )
        client = gh_api.GitHub(token="test-only")
        client.request = lambda path, body=None, method="GET": (path, body, method)
        path, body, method = client.update(7, verified, close_verified=True)
        self.assertEqual((path, method), ("/issues/7", "PATCH"))
        self.assertEqual(body["state"], "closed")
        self.assertEqual(protocol.parse(body["body"])["state"], "SUCCEEDED")


if __name__ == "__main__":
    unittest.main()
