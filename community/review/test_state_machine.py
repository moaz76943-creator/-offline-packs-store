"""Review-state machine tests.

Direct invocation from any working directory:

    python3 community/review/test_state_machine.py

Discoverable suite from the repository root:

    python3 -m unittest discover -s community/review -p 'test_*.py' -v
"""
import sys
import unittest
import os
import tempfile
import json
import hashlib
import hmac
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from community.review.state_machine import (
    ReviewStateMachine,
    ReviewState,
    sign,
    canonical,
    sha256
)

class TestReviewStateMachine(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.storage_dir = self.root / "storage"
        self.artifact_dir = self.root / "artifacts"
        self.storage_dir.mkdir()
        self.artifact_dir.mkdir()

        self.validator_key = os.urandom(32)
        self.reviewer_key = os.urandom(32)

        self.machine = ReviewStateMachine(
            self.storage_dir,
            self.artifact_dir,
            validator_keys={"val1": self.validator_key},
            reviewer_keys={"rev1": self.reviewer_key}
        )

        self.test_artifact = self.artifact_dir / "test.json"
        self.test_content = b'{"hello": "world"}'
        self.test_artifact.write_bytes(self.test_content)
        self.test_hash = sha256(self.test_artifact)

        self.metadata = {
            "source_id": "src1",
            "language": "eng",
            "translation_direction": "eng-fra",
            "sense_id": "sense1",
            "license_id": "CC-BY-4.0",
            "dataset_version": "1.0",
            "publisher": "Test Pub",
            "origin_url": "http://test.com",
            "record_locator": "loc1",
            "source_artifact_sha256": hashlib.sha256(b"source").hexdigest(),
            "fixture_only": False,
            "rights_status": "APPROVED_FOR_REDISTRIBUTION"
        }

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _sign(self, action, actor, sub_id, rev, key):
        payload = {
            "action": action,
            "actor": actor,
            "submission_id": sub_id,
            "sha256": self.test_hash,
            "metadata_sha256": hashlib.sha256(canonical(self.metadata)).hexdigest(),
            "revision": rev
        }
        return sign(key, payload)

    def test_full_lifecycle(self):
        # SUBMIT
        res = self.machine.submit("sub1", self.test_hash, self.metadata, self.test_artifact)
        self.assertEqual(res["state"], ReviewState.SUBMITTED.value)

        # START VALIDATION
        res = self.machine.start_validation("sub1")
        self.assertEqual(res["state"], ReviewState.VALIDATING.value)

        # COMPLETE VALIDATION
        token = self._sign("VALIDATE", "val1", "sub1", 1, self.validator_key)
        res = self.machine.complete_validation("sub1", "val1", token)
        self.assertEqual(res["state"], ReviewState.REVIEW_REQUIRED.value)

        # APPROVE
        token = self._sign("APPROVE", "rev1", "sub1", 1, self.reviewer_key)
        res = self.machine.review("sub1", "rev1", True, token)
        self.assertEqual(res["state"], ReviewState.APPROVED.value)

        # PUBLISH ELIGIBLE
        res = self.machine.mark_published_eligible("sub1")
        self.assertEqual(res["state"], ReviewState.PUBLISHED_ELIGIBLE.value)

        # VERIFY HANDOFF
        res = self.machine.verify_handoff("sub1")
        self.assertEqual(res["state"], ReviewState.PUBLISHED_ELIGIBLE.value)

    def test_reject(self):
        self.machine.submit("sub2", self.test_hash, self.metadata, self.test_artifact)
        self.machine.start_validation("sub2")

        token = self._sign("VALIDATE", "val1", "sub2", 1, self.validator_key)
        self.machine.complete_validation("sub2", "val1", token)

        token = self._sign("REJECT", "rev1", "sub2", 1, self.reviewer_key)
        res = self.machine.review("sub2", "rev1", False, token)
        self.assertEqual(res["state"], ReviewState.REJECTED.value)

        with self.assertRaises(ValueError):
            self.machine.mark_published_eligible("sub2")

    def test_idempotent_submit(self):
        res1 = self.machine.submit("sub3", self.test_hash, self.metadata, self.test_artifact)
        res2 = self.machine.submit("sub3", self.test_hash, self.metadata, self.test_artifact)
        self.assertEqual(res1["revision"], 1)
        self.assertEqual(res2["revision"], 1)

    def test_new_revision(self):
        self.machine.submit("sub4", self.test_hash, self.metadata, self.test_artifact)

        metadata_v2 = self.metadata.copy()
        metadata_v2["dataset_version"] = "2.0"

        res = self.machine.submit("sub4", self.test_hash, metadata_v2, self.test_artifact)
        self.assertEqual(res["revision"], 2)

    def test_invalid_metadata(self):
        bad_meta = self.metadata.copy()
        bad_meta["rights_status"] = "UNVERIFIED"

        with self.assertRaises(ValueError):
            self.machine.submit("sub5", self.test_hash, bad_meta, self.test_artifact)

    def test_interruption_restart(self):
        # Submit and start validating
        self.machine.submit("sub6", self.test_hash, self.metadata, self.test_artifact)
        self.machine.start_validation("sub6")

        # Re-create machine to simulate restart
        machine2 = ReviewStateMachine(
            self.storage_dir,
            self.artifact_dir,
            validator_keys={"val1": self.validator_key},
            reviewer_keys={"rev1": self.reviewer_key}
        )

        # State should be preserved
        data = machine2._read("sub6")
        self.assertEqual(data["state"], ReviewState.VALIDATING.value)

        # Continue
        token = self._sign("VALIDATE", "val1", "sub6", 1, self.validator_key)
        res = machine2.complete_validation("sub6", "val1", token)
        self.assertEqual(res["state"], ReviewState.REVIEW_REQUIRED.value)

    def test_invalid_token(self):
        self.machine.submit("sub7", self.test_hash, self.metadata, self.test_artifact)
        self.machine.start_validation("sub7")

        # Wrong action token
        token = self._sign("APPROVE", "val1", "sub7", 1, self.validator_key)
        with self.assertRaises(PermissionError):
            self.machine.complete_validation("sub7", "val1", token)


    def test_stale_approval(self):
        self.machine.submit("sub_stale", self.test_hash, self.metadata, self.test_artifact)
        self.machine.start_validation("sub_stale")
        val_token = self._sign("VALIDATE", "val1", "sub_stale", 1, self.validator_key)
        self.machine.complete_validation("sub_stale", "val1", val_token)

        # Stale approval token for revision 1
        stale_token = self._sign("APPROVE", "rev1", "sub_stale", 1, self.reviewer_key)

        # New revision submitted
        metadata_v2 = self.metadata.copy()
        metadata_v2["dataset_version"] = "2.0"
        self.machine.submit("sub_stale", self.test_hash, metadata_v2, self.test_artifact)

        self.machine.start_validation("sub_stale")
        # When updating metadata, sha256 of metadata changes. We need to use new metadata for sign.
        metadata_sha256_v2 = hashlib.sha256(canonical(metadata_v2)).hexdigest()
        payload = {"action": "VALIDATE", "actor": "val1", "submission_id": "sub_stale", "sha256": self.test_hash, "metadata_sha256": metadata_sha256_v2, "revision": 2}
        val_token2 = sign(self.validator_key, payload)
        self.machine.complete_validation("sub_stale", "val1", val_token2)

        # Try to approve with stale token
        with self.assertRaises(PermissionError):
            self.machine.review("sub_stale", "rev1", True, stale_token)

    def test_state_conflicts(self):
        self.machine.submit("sub_conflict", self.test_hash, self.metadata, self.test_artifact)

        # Cannot complete validation before starting
        val_token = self._sign("VALIDATE", "val1", "sub_conflict", 1, self.validator_key)
        with self.assertRaises(ValueError) as ctx:
            self.machine.complete_validation("sub_conflict", "val1", val_token)
        self.assertIn("invalid validation transition", str(ctx.exception))

        # Cannot review before validation is complete
        rev_token = self._sign("APPROVE", "rev1", "sub_conflict", 1, self.reviewer_key)
        with self.assertRaises(ValueError) as ctx:
            self.machine.review("sub_conflict", "rev1", True, rev_token)
        self.assertIn("invalid review transition", str(ctx.exception))

        self.machine.start_validation("sub_conflict")

        # Cannot start validation if already validating
        with self.assertRaises(ValueError) as ctx:
            self.machine.start_validation("sub_conflict")
        self.assertIn("invalid validation transition", str(ctx.exception))

        # Cannot mark published eligible if not approved
        with self.assertRaises(ValueError) as ctx:
            self.machine.mark_published_eligible("sub_conflict")
        self.assertIn("review not approved", str(ctx.exception))


    def test_repeated_submissions(self):
        res1 = self.machine.submit("sub_repeat", self.test_hash, self.metadata, self.test_artifact)
        self.assertEqual(res1["revision"], 1)

        self.machine.start_validation("sub_repeat")
        val_token = self._sign("VALIDATE", "val1", "sub_repeat", 1, self.validator_key)
        self.machine.complete_validation("sub_repeat", "val1", val_token)

        res2 = self.machine.submit("sub_repeat", self.test_hash, self.metadata, self.test_artifact)
        # Should be same revision, idempotency holds even after validation completes
        self.assertEqual(res2["revision"], 1)

if __name__ == '__main__':


    unittest.main()
