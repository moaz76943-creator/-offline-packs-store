import json
import os
import hashlib
import tempfile
import time
from enum import Enum
from typing import Dict, Any, Optional, List

class ReviewState(Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATING = "VALIDATING"
    REJECTED = "REJECTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    PUBLISHED_ELIGIBLE = "PUBLISHED_ELIGIBLE"

class ReviewStateMachine:
    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir
        self.checkpoints_dir = os.path.join(storage_dir, "checkpoints")
        self.handoff_dir = os.path.join(storage_dir, "handoffs")
        os.makedirs(self.checkpoints_dir, exist_ok=True)
        os.makedirs(self.handoff_dir, exist_ok=True)

    def _get_checkpoint_path(self, submission_id: str) -> str:
        return os.path.join(self.checkpoints_dir, f"{submission_id}.json")

    def _read_checkpoint(self, submission_id: str) -> Optional[Dict[str, Any]]:
        path = self._get_checkpoint_path(submission_id)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def _write_checkpoint(self, submission_id: str, data: Dict[str, Any]) -> None:
        path = self._get_checkpoint_path(submission_id)
        # Safe atomic checkpoint writes
        fd, temp_path = tempfile.mkstemp(dir=self.checkpoints_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)

    def submit(self, submission_id: str, content_hash: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Support SUBMITTED state. Detect duplicate contribution versions idempotently."""
        # 5. Verify language, translation direction and lexical sense identity.
        if "language" not in metadata:
            raise ValueError("Missing language in metadata")
        if "translation_direction" not in metadata:
            raise ValueError("Missing translation_direction in metadata")
        if "lexical_sense" not in metadata:
            raise ValueError("Missing lexical_sense in metadata")

        existing = self._read_checkpoint(submission_id)
        if existing:
            # Check if this is the exact same submission
            if existing["content_hash"] == content_hash:
                return existing
            else:
                # Support approved correction submissions as new revisions
                # Keep history, but reset state
                existing["content_hash"] = content_hash
                existing["metadata"] = metadata
                existing["state"] = ReviewState.SUBMITTED.value
                existing["history"].append({"state": ReviewState.SUBMITTED.value, "timestamp": time.time(), "note": "Correction submitted"})
                # We can choose to clear evidence or keep it. Safest is to clear it so it's re-validated.
                existing["evidence"] = {}
                self._write_checkpoint(submission_id, existing)
                return existing

        data = {
            "submission_id": submission_id,
            "content_hash": content_hash,
            "state": ReviewState.SUBMITTED.value,
            "metadata": metadata,
            "history": [{"state": ReviewState.SUBMITTED.value, "timestamp": time.time()}],
            "evidence": {},
        }
        self._write_checkpoint(submission_id, data)
        return data

    def start_validation(self, submission_id: str) -> Dict[str, Any]:
        data = self._read_checkpoint(submission_id)
        if not data:
            raise ValueError(f"Submission {submission_id} not found")

        if data["state"] not in [ReviewState.SUBMITTED.value, ReviewState.VALIDATING.value]:
            raise ValueError(f"Cannot start validation from state {data['state']}")

        if data["state"] != ReviewState.VALIDATING.value:
            data["state"] = ReviewState.VALIDATING.value
            data["history"].append({"state": ReviewState.VALIDATING.value, "timestamp": time.time()})
            self._write_checkpoint(submission_id, data)

        return data

    def provide_evidence(self, submission_id: str, evidence_type: str, evidence_data: Any) -> Dict[str, Any]:
        data = self._read_checkpoint(submission_id)
        if not data:
            raise ValueError(f"Submission {submission_id} not found")

        if data["state"] != ReviewState.VALIDATING.value:
            raise ValueError(f"Cannot provide evidence in state {data['state']}")

        data["evidence"][evidence_type] = evidence_data
        self._write_checkpoint(submission_id, data)
        return data

    def complete_validation(self, submission_id: str) -> Dict[str, Any]:
        data = self._read_checkpoint(submission_id)
        if not data:
            raise ValueError(f"Submission {submission_id} not found")

        if data["state"] != ReviewState.VALIDATING.value:
            raise ValueError(f"Cannot complete validation in state {data['state']}")

        # Prevent bypassing mandatory licensing and content gates.
        if "licensing_check" not in data["evidence"]:
            data["state"] = ReviewState.REJECTED.value
            data["rejection_reason"] = "Missing mandatory licensing check evidence"
            data["history"].append({"state": ReviewState.REJECTED.value, "timestamp": time.time(), "reason": data["rejection_reason"]})
            self._write_checkpoint(submission_id, data)
            return data

        if not data["evidence"]["licensing_check"].get("passed", False):
            data["state"] = ReviewState.REJECTED.value
            data["rejection_reason"] = "Licensing check failed"
            data["history"].append({"state": ReviewState.REJECTED.value, "timestamp": time.time(), "reason": data["rejection_reason"]})
            self._write_checkpoint(submission_id, data)
            return data

        # Check algorithmic checks, but do not treat algorithmic lexical checks as proof of full human-level correctness.
        if "algorithmic_check" in data["evidence"] and not data["evidence"]["algorithmic_check"].get("passed", False):
            data["state"] = ReviewState.REJECTED.value
            data["rejection_reason"] = "Algorithmic check failed"
            data["history"].append({"state": ReviewState.REJECTED.value, "timestamp": time.time(), "reason": data["rejection_reason"]})
            self._write_checkpoint(submission_id, data)
            return data

        # If it passes validation, it requires human review
        data["state"] = ReviewState.REVIEW_REQUIRED.value
        data["history"].append({"state": ReviewState.REVIEW_REQUIRED.value, "timestamp": time.time()})
        self._write_checkpoint(submission_id, data)
        return data

    def review(self, submission_id: str, reviewer_id: str, approved: bool, comments: str = "") -> Dict[str, Any]:
        data = self._read_checkpoint(submission_id)
        if not data:
            raise ValueError(f"Submission {submission_id} not found")

        if data["state"] != ReviewState.REVIEW_REQUIRED.value:
            raise ValueError(f"Cannot review in state {data['state']}")

        if approved:
            data["state"] = ReviewState.APPROVED.value
            data["history"].append({
                "state": ReviewState.APPROVED.value,
                "timestamp": time.time(),
                "reviewer": reviewer_id,
                "comments": comments
            })
        else:
            data["state"] = ReviewState.REJECTED.value
            data["rejection_reason"] = f"Rejected by reviewer {reviewer_id}: {comments}"
            data["history"].append({
                "state": ReviewState.REJECTED.value,
                "timestamp": time.time(),
                "reviewer": reviewer_id,
                "reason": data["rejection_reason"]
            })

        self._write_checkpoint(submission_id, data)
        return data

    def mark_published_eligible(self, submission_id: str) -> Dict[str, Any]:
        data = self._read_checkpoint(submission_id)
        if not data:
            raise ValueError(f"Submission {submission_id} not found")

        if data["state"] != ReviewState.APPROVED.value:
            raise ValueError(f"Cannot mark published eligible in state {data['state']}")

        # Export only approved handoff manifests, not live publication
        data["state"] = ReviewState.PUBLISHED_ELIGIBLE.value
        data["history"].append({"state": ReviewState.PUBLISHED_ELIGIBLE.value, "timestamp": time.time()})
        self._write_checkpoint(submission_id, data)

        # Write handoff manifest
        handoff_path = os.path.join(self.handoff_dir, f"{submission_id}_handoff.json")
        fd, temp_path = tempfile.mkstemp(dir=self.handoff_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({
                "submission_id": submission_id,
                "content_hash": data["content_hash"],
                "metadata": data["metadata"],
                "approved_by": [h["reviewer"] for h in data["history"] if h.get("state") == ReviewState.APPROVED.value]
            }, f, indent=2)
        os.replace(temp_path, handoff_path)

        return data

    def enqueue_manifest(self, manifest_path: str) -> List[Dict[str, Any]]:
        """Permit J087 to enqueue incremental reviews through versioned manifest files"""
        if not os.path.exists(manifest_path):
            raise ValueError(f"Manifest not found at {manifest_path}")

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        results = []
        for item in manifest_data.get("submissions", []):
            res = self.submit(
                submission_id=item["submission_id"],
                content_hash=item["content_hash"],
                metadata=item.get("metadata", {})
            )
            results.append(res)

        return results
