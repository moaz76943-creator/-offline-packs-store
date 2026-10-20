import unittest
import hashlib
import tempfile
import shutil
import base64
import json
from pathlib import Path
import sys
import hmac

from community.review.state_machine import ReviewStateMachine, safe_directory, sign

class TestReviewStateMachine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.storage = Path(self.tmpdir) / "storage"
        self.artifacts = Path(self.tmpdir) / "artifacts"
        self.storage.mkdir()
        self.artifacts.mkdir()

        self.val_key = b"val" * 32
        self.rev_key = b"rev" * 32

        self.machine = ReviewStateMachine(
            storage_dir=self.storage,
            artifact_dir=self.artifacts,
            validator_keys={"val1": self.val_key},
            reviewer_keys={"rev1": self.rev_key}
        )

        self.meta = {
            "source_id": "test-src",
            "language": "en",
            "sense_id": "test-sense",
            "license_id": "CC0-1.0",
            "dataset_version": "v1",
            "publisher": "test-pub",
            "origin_url": "https://test.local",
            "record_locator": "test-loc",
            "source_artifact_sha256": "a" * 64,
            "fixture_only": False,
            "rights_status": "APPROVED_FOR_REDISTRIBUTION"
        }

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def digest(self, data: bytes):
        return hashlib.sha256(data).hexdigest()

    def _setup_submission(self, sid, content=b"test content"):
        path = self.artifacts / f"{sid}.txt"
        path.write_bytes(content)
        h = self.digest(content)
        res = self.machine.submit(sid, h, self.meta, path)
        return path, h, res

    def test_submit(self):
        path, h, res = self._setup_submission("sub1")
        self.assertEqual(res["state"], "SUBMITTED")
        self.assertEqual(res["revision"], 1)

    def test_start_validation(self):
        path, h, res = self._setup_submission("sub1")
        res = self.machine.start_validation("sub1")
        self.assertEqual(res["state"], "VALIDATING")

    def test_complete_validation(self):
        path, h, res = self._setup_submission("sub1")
        self.machine.start_validation("sub1")

        state = self.machine._read("sub1")
        token = sign(self.val_key, ReviewStateMachine.payload(state, "VALIDATE", "val1"))

        res = self.machine.complete_validation("sub1", "val1", token)
        self.assertEqual(res["state"], "REVIEW_REQUIRED")

    def test_approve_reject(self):
        path, h, res = self._setup_submission("sub1")
        self.machine.start_validation("sub1")

        state = self.machine._read("sub1")
        val_token = sign(self.val_key, ReviewStateMachine.payload(state, "VALIDATE", "val1"))
        self.machine.complete_validation("sub1", "val1", val_token)

        state = self.machine._read("sub1")

        # Test approval
        app_token = sign(self.rev_key, ReviewStateMachine.payload(state, "APPROVE", "rev1"))
        res = self.machine.review("sub1", "rev1", True, app_token)
        self.assertEqual(res["state"], "APPROVED")

        # Start fresh for rejection
        path2, h2, res2 = self._setup_submission("sub2")
        self.machine.start_validation("sub2")
        state2 = self.machine._read("sub2")
        val_token2 = sign(self.val_key, ReviewStateMachine.payload(state2, "VALIDATE", "val1"))
        self.machine.complete_validation("sub2", "val1", val_token2)

        state2 = self.machine._read("sub2")
        rej_token = sign(self.rev_key, ReviewStateMachine.payload(state2, "REJECT", "rev1"))
        res = self.machine.review("sub2", "rev1", False, rej_token)
        self.assertEqual(res["state"], "REJECTED")

    def test_mark_published_eligible(self):
        path, h, res = self._setup_submission("sub1")
        self.machine.start_validation("sub1")

        state = self.machine._read("sub1")
        val_token = sign(self.val_key, ReviewStateMachine.payload(state, "VALIDATE", "val1"))
        self.machine.complete_validation("sub1", "val1", val_token)

        state = self.machine._read("sub1")
        app_token = sign(self.rev_key, ReviewStateMachine.payload(state, "APPROVE", "rev1"))
        self.machine.review("sub1", "rev1", True, app_token)

        res = self.machine.mark_published_eligible("sub1")
        self.assertEqual(res["state"], "PUBLISHED_ELIGIBLE")

    def test_rejected_sources(self):
        path, h, res = self._setup_submission("rej1")
        self.machine.start_validation("rej1")
        state = self.machine._read("rej1")
        val_token = sign(self.val_key, ReviewStateMachine.payload(state, "VALIDATE", "val1"))
        self.machine.complete_validation("rej1", "val1", val_token)

        state = self.machine._read("rej1")
        rej_token = sign(self.rev_key, ReviewStateMachine.payload(state, "REJECT", "rev1"))
        res = self.machine.review("rej1", "rev1", False, rej_token)
        self.assertEqual(res["state"], "REJECTED")

        # Test rejected submissions can't be published
        with self.assertRaises(ValueError):
            self.machine.mark_published_eligible("rej1")

    def test_stale_approvals(self):
        path, h, res = self._setup_submission("stale1")
        self.machine.start_validation("stale1")
        state = self.machine._read("stale1")
        val_token = sign(self.val_key, ReviewStateMachine.payload(state, "VALIDATE", "val1"))
        self.machine.complete_validation("stale1", "val1", val_token)

        state = self.machine._read("stale1")
        app_token = sign(self.rev_key, ReviewStateMachine.payload(state, "APPROVE", "rev1"))

        # New submission creates revision 2, invalidating previous approval
        path2 = self.artifacts / "stale1_v2.txt"
        path2.write_bytes(b"v2")
        h2 = self.digest(b"v2")
        res2 = self.machine.submit("stale1", h2, self.meta, path2)
        self.assertEqual(res2["revision"], 2)
        self.assertEqual(res2["state"], "SUBMITTED")

        with self.assertRaises(ValueError):
            # Tries to review old revision but current state is SUBMITTED
            self.machine.review("stale1", "rev1", True, app_token)

    def test_repeated_submissions(self):
        path, h, res1 = self._setup_submission("rep1")
        res2 = self.machine.submit("rep1", h, self.meta, path)
        self.assertEqual(res1["revision"], res2["revision"])

        path2 = self.artifacts / "rep1_v2.txt"
        path2.write_bytes(b"v2")
        h2 = self.digest(b"v2")
        res3 = self.machine.submit("rep1", h2, self.meta, path2)
        self.assertEqual(res3["revision"], res1["revision"] + 1)
        self.assertEqual(res3["state"], "SUBMITTED")

    def test_reviewer_state_conflicts(self):
        path, h, res = self._setup_submission("conf1")
        self.machine.start_validation("conf1")

        state = self.machine._read("conf1")
        app_token = sign(self.rev_key, ReviewStateMachine.payload(state, "APPROVE", "rev1"))

        # Cannot review while in VALIDATING
        with self.assertRaises(ValueError):
            self.machine.review("conf1", "rev1", True, app_token)

        val_token = sign(self.val_key, ReviewStateMachine.payload(state, "VALIDATE", "val1"))
        self.machine.complete_validation("conf1", "val1", val_token)

        # Wrong action token
        state = self.machine._read("conf1")
        rej_token = sign(self.rev_key, ReviewStateMachine.payload(state, "REJECT", "rev1"))
        with self.assertRaises(PermissionError):
            self.machine.review("conf1", "rev1", True, rej_token)

        # Wrong key
        bad_token = sign(b"bad", ReviewStateMachine.payload(state, "APPROVE", "rev1"))
        with self.assertRaises(PermissionError):
            self.machine.review("conf1", "rev1", True, bad_token)

    def test_restart(self):
        path, h, res = self._setup_submission("rst1")

        m2 = ReviewStateMachine(
            storage_dir=self.storage,
            artifact_dir=self.artifacts,
            validator_keys={"val1": self.val_key},
            reviewer_keys={"rev1": self.rev_key}
        )

        state = m2._read("rst1")
        self.assertEqual(state["state"], "SUBMITTED")
        self.assertEqual(state["revision"], 1)

if __name__ == '__main__':
    unittest.main()
