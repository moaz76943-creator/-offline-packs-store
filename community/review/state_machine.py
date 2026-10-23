"""Fail-closed review ledger. Authority keys are injected by a trusted operator.

This module does NOT confer legal approval. Do not store keys in the repository.
"""
import fcntl
import hashlib
import hmac
import json
import os
import re
import tempfile
from contextlib import contextmanager
from enum import Enum
from pathlib import Path

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
MAX_CHECKPOINT_BYTES = 512 * 1024


class ReviewState(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATING = "VALIDATING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED_ELIGIBLE = "PUBLISHED_ELIGIBLE"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def sign(key, message):
    """Used only by the separate authorized human/validation service, not intake."""
    return hmac.new(key, canonical(message), hashlib.sha256).hexdigest()


def safe_name(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("unsafe submission/reviewer identity")
    return value


def safe_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("symlink directory")
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("unsafe directory")
    return path.resolve()


def existing_file(path, root):
    root = Path(root).resolve()
    path = Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError("missing, symlinked or escaping content")
    return path


def atomic_json(path, data):
    payload = canonical(data)
    if len(payload) > MAX_CHECKPOINT_BYTES:
        raise ValueError("oversized review checkpoint")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".checkpoint-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class ReviewStateMachine:
    """Keys and artifact root must be provided independently of submissions."""
    def __init__(self, storage_dir, artifact_dir, *, validator_keys=None, reviewer_keys=None):
        self.root = safe_directory(storage_dir)
        self.artifacts = safe_directory(artifact_dir)
        self.checkpoints_dir = safe_directory(self.root / "checkpoints")
        self.handoff_dir = safe_directory(self.root / "handoffs")
        self.validator_keys = validator_keys or {}
        self.reviewer_keys = reviewer_keys or {}
        self.lockfile = self.root / ".review.lock"

    @contextmanager
    def locked(self):
        fd = os.open(self.lockfile, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _file(self, sid):
        return self.checkpoints_dir / (safe_name(sid) + ".json")

    def _read(self, sid):
        path = self._file(sid)
        if not path.exists():
            return None
        if path.is_symlink() or path.stat().st_size > MAX_CHECKPOINT_BYTES:
            raise ValueError("unsafe or oversized checkpoint")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("submission_id") != sid:
            raise ValueError("checkpoint identity mismatch")
        return data

    def _write(self, data):
        atomic_json(self._file(data["submission_id"]), data)
        return data

    @staticmethod
    def _claimed_metadata(meta):
        required = ("source_id", "language", "sense_id", "license_id",
                    "dataset_version", "publisher", "origin_url", "record_locator", "source_artifact_sha256",
                    "translation_direction")
        if not isinstance(meta, dict) or any(not isinstance(meta.get(k), str) or not meta[k].strip() for k in required):
            raise ValueError("incomplete source/sense metadata")
        if (not HASH.fullmatch(meta["source_artifact_sha256"]) or meta.get("fixture_only") is not False or
                meta.get("rights_status") != "APPROVED_FOR_REDISTRIBUTION"):
            raise ValueError("unverified or fixture-only rights")
        return meta

    @staticmethod
    def payload(data, action, actor):
        return {"action": action, "actor": actor, "submission_id": data["submission_id"],
                "sha256": data["content_hash"], "metadata_sha256": hashlib.sha256(canonical(data["metadata"])).hexdigest(),
                "revision": data["revision"]}

    @staticmethod
    def verify(data, action, actor, token, keys):
        key = keys.get(actor)
        if not isinstance(key, bytes) or len(key) < 32 or not isinstance(token, str):
            raise PermissionError("missing trusted reviewer/validator authority")
        if not hmac.compare_digest(sign(key, ReviewStateMachine.payload(data, action, actor)), token):
            raise PermissionError("invalid or stale authorized decision")

    def submit(self, submission_id, content_hash, metadata, artifact_path):
        safe_name(submission_id)
        if not isinstance(content_hash, str) or not HASH.fullmatch(content_hash):
            raise ValueError("invalid SHA-256")
        self._claimed_metadata(metadata)
        path = existing_file(artifact_path, self.artifacts)
        if sha256(path) != content_hash:
            raise ValueError("content hash mismatch")
        rel = str(path.resolve().relative_to(self.artifacts))
        with self.locked():
            old = self._read(submission_id)
            if old and old["content_hash"] == content_hash and old["metadata"] == metadata:
                return old
            revision = old["revision"] + 1 if old else 1
            data = {"submission_id": submission_id, "content_hash": content_hash, "metadata": metadata,
                    "artifact": rel, "revision": revision, "state": ReviewState.SUBMITTED.value,
                    "evidence": {}, "history": (old["history"] if old else []) +
                    [{"state": ReviewState.SUBMITTED.value, "revision": revision}]}
            return self._write(data)

    def _content(self, data):
        path = existing_file(self.artifacts / data["artifact"], self.artifacts)
        if sha256(path) != data["content_hash"]:
            raise ValueError("changed content after staging")
        return path

    def start_validation(self, sid):
        with self.locked():
            data = self._read(sid)
            if not data or data["state"] != ReviewState.SUBMITTED.value:
                raise ValueError("invalid validation transition")
            self._content(data)
            data["state"] = ReviewState.VALIDATING.value
            data["history"].append({"state": data["state"], "revision": data["revision"]})
            return self._write(data)

    def complete_validation(self, sid, validator_id, token):
        with self.locked():
            data = self._read(sid)
            if not data or data["state"] != ReviewState.VALIDATING.value:
                raise ValueError("invalid validation transition")
            self._content(data)
            self.verify(data, "VALIDATE", safe_name(validator_id), token, self.validator_keys)
            data["evidence"]["validator"] = {"id": validator_id, "token": token}
            data["state"] = ReviewState.REVIEW_REQUIRED.value
            data["history"].append({"state": data["state"], "revision": data["revision"]})
            return self._write(data)

    def review(self, sid, reviewer_id, approved, token):
        if type(approved) is not bool:
            raise ValueError("explicit review decision required")
        with self.locked():
            data = self._read(sid)
            if not data or data["state"] != ReviewState.REVIEW_REQUIRED.value:
                raise ValueError("invalid review transition")
            self._content(data)
            action = "APPROVE" if approved else "REJECT"
            self.verify(data, action, safe_name(reviewer_id), token, self.reviewer_keys)
            data["evidence"]["reviewer"] = {"id": reviewer_id, "token": token, "action": action}
            data["state"] = ReviewState.APPROVED.value if approved else ReviewState.REJECTED.value
            data["history"].append({"state": data["state"], "revision": data["revision"], "reviewer": reviewer_id})
            return self._write(data)

    def mark_published_eligible(self, sid):
        with self.locked():
            data = self._read(sid)
            if not data or data["state"] not in (ReviewState.APPROVED.value, ReviewState.PUBLISHED_ELIGIBLE.value):
                raise ValueError("review not approved")
            self._content(data)
            val, rev = data["evidence"]["validator"], data["evidence"]["reviewer"]
            self.verify(data, "VALIDATE", val["id"], val["token"], self.validator_keys)
            self.verify(data, "APPROVE", rev["id"], rev["token"], self.reviewer_keys)
            if data["state"] != ReviewState.PUBLISHED_ELIGIBLE.value:
                data["state"] = ReviewState.PUBLISHED_ELIGIBLE.value
                data["history"].append({"state": data["state"], "revision": data["revision"]})
                self._write(data)
            atomic_json(self.handoff_dir / (safe_name(sid) + "_handoff.json"), data)
            return data

    def verify_handoff(self, sid):
        path = self.handoff_dir / (safe_name(sid) + "_handoff.json")
        if path.is_symlink() or path.stat().st_size > MAX_CHECKPOINT_BYTES:
            raise ValueError("unsafe or oversized handoff")
        with self.locked():
            data = json.loads(path.read_text(encoding="utf-8"))
            current = self._read(sid)
            if data != current or data.get("state") != ReviewState.PUBLISHED_ELIGIBLE.value:
                raise ValueError("stale or forged handoff")
            self._claimed_metadata(data["metadata"])
            self._content(data)
            val, rev = data["evidence"]["validator"], data["evidence"]["reviewer"]
            self.verify(data, "VALIDATE", val["id"], val["token"], self.validator_keys)
            self.verify(data, "APPROVE", rev["id"], rev["token"], self.reviewer_keys)
            return data
